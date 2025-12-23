"""
NQ Agent Service

Main 24/7 service for running NQ intraday strategy.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import math

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp, parse_utc_timestamp

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
from pearlalgo.nq_agent.health_monitor import HealthMonitor
from pearlalgo.nq_agent.performance_tracker import PerformanceTracker
from pearlalgo.nq_agent.state_manager import NQAgentStateManager
from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
from pearlalgo.utils.cadence import CadenceMetrics, CadenceScheduler
from pearlalgo.utils.data_quality import DataQualityChecker
from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.market_hours import get_market_hours
from pearlalgo.utils.volume_pressure import (
    compute_volume_pressure_summary,
    format_volume_pressure,
    timeframe_to_minutes,
)


class NQAgentService:
    """
    24/7 service for NQ intraday trading strategy.
    
    Runs independently, fetches data, generates signals, and sends to Telegram.
    """

    def __init__(
        self,
        data_provider: DataProvider,
        config: Optional[NQIntradayConfig] = None,
        state_dir: Optional[Path] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ):
        """
        Initialize NQ agent service.
        
        Args:
            data_provider: Data provider instance
            config: Strategy configuration (optional)
            state_dir: State directory (optional)
            telegram_bot_token: Telegram bot token (optional)
            telegram_chat_id: Telegram chat ID (optional)
        """
        self.config = config or NQIntradayConfig()
        self.strategy = NQIntradayStrategy(config=self.config)
        self.data_fetcher = NQAgentDataFetcher(data_provider, config=self.config)
        self.state_manager = NQAgentStateManager(state_dir=state_dir)
        self.performance_tracker = PerformanceTracker(
            state_dir=state_dir,
            state_manager=self.state_manager,
        )
        self.telegram_notifier = NQAgentTelegramNotifier(
            bot_token=telegram_bot_token,
            chat_id=telegram_chat_id,
        )
        
        # Log Telegram configuration status
        if self.telegram_notifier.enabled:
            logger.info(
                f"Telegram notifications enabled: bot_token={'***' if telegram_bot_token else 'MISSING'}, "
                f"chat_id={'***' if telegram_chat_id else 'MISSING'}, "
                f"telegram_instance={self.telegram_notifier.telegram is not None}"
            )
        else:
            logger.warning(
                "Telegram notifications DISABLED - signals will not be sent to Telegram. "
                f"bot_token={'present' if telegram_bot_token else 'MISSING'}, "
                f"chat_id={'present' if telegram_chat_id else 'MISSING'}"
            )
        
        self.health_monitor = HealthMonitor(state_dir=state_dir)

        # Load service configuration
        service_config = load_service_config()
        service_settings = service_config.get("service", {})
        circuit_breaker_settings = service_config.get("circuit_breaker", {})
        data_settings = service_config.get("data", {})

        self.running = False
        self.shutdown_requested = False
        self.paused = False
        self.pause_reason: Optional[str] = None
        self.start_time: Optional[datetime] = None
        
        # Load persisted state to restore counters
        saved_state = self.state_manager.load_state()
        self.cycle_count = saved_state.get("cycle_count", 0)
        # Restore signal_count from saved state OR count from signals file (more accurate)
        saved_signal_count = saved_state.get("signal_count", 0)
        try:
            # Count actual signals in signals file for accuracy
            signals_file = self.state_manager.signals_file
            if signals_file.exists():
                actual_signal_count = sum(1 for _ in open(signals_file)) if signals_file.exists() else 0
                self.signal_count = max(saved_signal_count, actual_signal_count)
                logger.info(f"Restored signal_count: {self.signal_count} (from state: {saved_signal_count}, from file: {actual_signal_count})")
            else:
                self.signal_count = saved_signal_count
                logger.info(f"Restored signal_count: {self.signal_count} (from state, no signals file yet)")
        except Exception as e:
            logger.warning(f"Could not count signals from file, using saved state: {e}")
            self.signal_count = saved_signal_count
        
        self.error_count = saved_state.get("error_count", 0)
        # Telegram delivery observability (backward-compatible defaults)
        self.signals_sent = int(saved_state.get("signals_sent", 0) or 0)
        self.signals_send_failures = int(saved_state.get("signals_send_failures", 0) or 0)
        self.last_signal_send_error: Optional[str] = saved_state.get("last_signal_send_error")
        self.last_signal_generated_at: Optional[str] = saved_state.get("last_signal_generated_at")
        self.last_signal_sent_at: Optional[str] = saved_state.get("last_signal_sent_at")
        self.last_signal_id_prefix: Optional[str] = saved_state.get("last_signal_id_prefix")

        # Session baselines (initialized on start)
        self._cycle_count_at_start: Optional[int] = None
        self._signal_count_at_start: Optional[int] = None
        self._signals_sent_at_start: Optional[int] = None
        self._signals_fail_at_start: Optional[int] = None
        self.last_status_update: Optional[datetime] = None
        self.status_update_interval = service_settings.get("status_update_interval", 1800)
        self.last_heartbeat: Optional[datetime] = None
        self.heartbeat_interval = service_settings.get("heartbeat_interval", 3600)
        # Dashboard chart (hourly mplfinance screenshot)
        self.last_dashboard_chart_sent: Optional[datetime] = None
        self.dashboard_chart_interval = service_settings.get("dashboard_chart_interval", 3600)  # 1 hour default
        self.dashboard_chart_lookback_hours = float(service_settings.get("dashboard_chart_lookback_hours", 48) or 48)
        self.dashboard_chart_timeframe = str(service_settings.get("dashboard_chart_timeframe", "auto") or "auto")
        self.dashboard_chart_max_bars = int(service_settings.get("dashboard_chart_max_bars", 420) or 420)
        self.dashboard_chart_show_pressure = bool(service_settings.get("dashboard_chart_show_pressure", True))
        # Buy/Sell pressure (dashboard observability)
        self.pressure_lookback_bars = int(service_settings.get("pressure_lookback_bars", 24) or 24)
        self.pressure_baseline_bars = int(service_settings.get("pressure_baseline_bars", 120) or 120)
        self.state_save_interval = service_settings.get("state_save_interval", 10)
        self.connection_failure_alert_interval = service_settings.get("connection_failure_alert_interval", 600)
        self.data_quality_alert_interval = service_settings.get("data_quality_alert_interval", 300)
        self.consecutive_errors = 0
        self.max_consecutive_errors = circuit_breaker_settings.get("max_consecutive_errors", 10)
        self.data_fetch_errors = 0
        self.max_data_fetch_errors = circuit_breaker_settings.get("max_data_fetch_errors", 5)
        self.connection_failures = 0
        self.max_connection_failures = circuit_breaker_settings.get("max_connection_failures", 10)
        self.last_connection_failure_alert: Optional[datetime] = None
        self.last_successful_cycle: Optional[datetime] = None
        self.last_data_quality_alert: Optional[datetime] = None
        self._last_stale_data_alert_type: Optional[str] = None  # Track last alert type to prevent duplicates
        # Smarter alert cadence state (reduce Telegram spam)
        self._last_stale_bucket: Optional[int] = None
        self._last_buffer_severity: Optional[str] = None
        self._was_stale_during_market: bool = False
        self._was_data_gap: bool = False
        self._was_buffer_inadequate: bool = False
        self.stale_data_threshold_minutes = data_settings.get("stale_data_threshold_minutes", 10)
        self.connection_timeout_minutes = data_settings.get("connection_timeout_minutes", 30)
        self.buffer_size_target = int(data_settings.get("buffer_size", 100) or 100)
        
        # Initialize data quality checker
        self.data_quality_checker = DataQualityChecker(
            stale_data_threshold_minutes=self.stale_data_threshold_minutes
        )

        # Cadence scheduler for fixed-interval timing (start-to-start)
        # "fixed" = start-to-start timing with skip-ahead for missed cycles
        # "sleep_after" = legacy sleep-after-work semantics
        self.cadence_mode = service_settings.get("cadence_mode", "fixed")
        self.cadence_scheduler: Optional[CadenceScheduler] = None
        if self.cadence_mode == "fixed":
            self.cadence_scheduler = CadenceScheduler(
                interval_seconds=float(self.config.scan_interval),
            )
            logger.info(
                f"Cadence scheduler initialized: mode=fixed, interval={self.config.scan_interval}s"
            )
        else:
            logger.info(
                f"Cadence scheduler disabled: mode={self.cadence_mode} (legacy sleep-after-work)"
            )

        logger.info("NQAgentService initialized")

    async def start(self) -> None:
        """Start the service."""
        if self.running:
            logger.warning("Service already running")
            return

        self.running = True
        self.shutdown_requested = False
        self.start_time = datetime.now(timezone.utc)
        # Establish session baselines for derived counters (cycles/signals since start)
        self._cycle_count_at_start = int(self.cycle_count or 0)
        self._signal_count_at_start = int(self.signal_count or 0)
        self._signals_sent_at_start = int(self.signals_sent or 0)
        self._signals_fail_at_start = int(self.signals_send_failures or 0)

        # Setup signal handlers
        # Note: These set shutdown_requested flag, stop() is called in finally block
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("NQ Agent Service starting...")

        # Send startup notification immediately (before connection attempts)
        # This ensures user gets notified even if connection fails
        try:
            config_dict = {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
                "stop_loss_atr_multiplier": self.config.stop_loss_atr_multiplier,
                "take_profit_risk_reward": self.config.take_profit_risk_reward,
                "max_risk_per_trade": self.config.max_risk_per_trade,
                "current_time": get_utc_timestamp(),
            }

            # Include explicit market/session gates so startup never shows UNKNOWN in Telegram UI.
            try:
                config_dict["futures_market_open"] = bool(get_market_hours().is_market_open())
            except Exception:
                config_dict["futures_market_open"] = None
            try:
                config_dict["strategy_session_open"] = bool(self.strategy.scanner.is_market_hours())
            except Exception:
                config_dict["strategy_session_open"] = None
            
            # Try to get latest price for startup message (non-blocking, timeout quickly)
            try:
                market_data = await asyncio.wait_for(
                    self.data_fetcher.fetch_latest_data(),
                    timeout=5.0
                )
                if market_data.get("latest_bar"):
                    latest_bar = market_data["latest_bar"]
                    if isinstance(latest_bar, dict) and "close" in latest_bar:
                        config_dict["latest_price"] = latest_bar["close"]
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug(f"Could not fetch price for startup notification: {e}")
                # Continue without price - service will still start
            
            await self.telegram_notifier.send_startup_notification(config_dict)
            logger.info("Startup notification sent to Telegram")
        except Exception as e:
            logger.error(f"Could not send startup notification: {e}", exc_info=True)

        try:
            await self._run_loop()
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt, shutting down gracefully...")
            await self.stop("Keyboard interrupt (Ctrl+C)")
        except Exception as e:
            logger.error(f"Service error: {e}", exc_info=True)
            await self.stop(f"Error: {str(e)[:50]}")
        finally:
            # Ensure stop is called even if exception occurred
            if self.running:
                await self.stop("Final cleanup")

    async def stop(self, shutdown_reason: str = "Normal shutdown") -> None:
        """Stop the service."""
        if not self.running:
            return

        logger.info(f"Stopping NQ Agent Service... ({shutdown_reason})")
        self.shutdown_requested = True

        # Save final state
        try:
            self._save_state()
        except Exception as e:
            logger.warning(f"Could not save final state: {e}")

        # Send shutdown notification (with timeout to ensure it doesn't block)
        # IMPORTANT: Send this BEFORE setting running=False so Telegram is still available
        try:
            uptime_delta = datetime.now(timezone.utc) - self.start_time if self.start_time else None
            summary = {
                "uptime_hours": int(uptime_delta.total_seconds() / 3600) if uptime_delta else 0,
                "uptime_minutes": int((uptime_delta.total_seconds() % 3600) / 60) if uptime_delta else 0,
                "cycle_count": self.cycle_count,
                "signal_count": self.signal_count,
                "error_count": self.error_count,
                "shutdown_reason": shutdown_reason,
            }

            # Add performance metrics if available
            try:
                performance = self.performance_tracker.get_performance_metrics(days=7)
                summary["wins"] = performance.get("wins", 0)
                summary["losses"] = performance.get("losses", 0)
                summary["total_pnl"] = performance.get("total_pnl", 0)
            except Exception:
                pass

            # Send with timeout to ensure it doesn't hang, but log if it fails
            logger.info(f"Sending shutdown notification: {shutdown_reason}")
            try:
                await asyncio.wait_for(
                    self.telegram_notifier.send_shutdown_notification(summary),
                    timeout=10.0  # Increased timeout to give more time
                )
                logger.info("✅ Shutdown notification sent to Telegram")
            except asyncio.TimeoutError:
                logger.error("❌ Timeout sending shutdown notification - Telegram may be slow or unreachable")
                # Try one more time without timeout as last resort
                try:
                    await self.telegram_notifier.send_shutdown_notification(summary)
                    logger.info("✅ Shutdown notification sent on retry")
                except Exception as retry_e:
                    logger.error(f"❌ Failed to send shutdown notification on retry: {retry_e}")
        except Exception as e:
            logger.error(f"❌ Error sending shutdown notification: {e}", exc_info=True)

        self.running = False
        logger.info("NQ Agent Service stopped")

    async def _run_loop(self) -> None:
        """Main service loop."""
        logger.info(
            "Starting main loop",
            extra={
                "scan_interval": self.config.scan_interval,
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "cadence_mode": self.cadence_mode,
            },
        )

        while not self.shutdown_requested:
            # Mark cycle start for cadence tracking (fixed-cadence mode)
            if self.cadence_scheduler:
                cadence_lag = self.cadence_scheduler.mark_cycle_start()
                if cadence_lag > 1000:  # More than 1s lag
                    logger.warning(
                        f"Cadence lag detected: {cadence_lag:.0f}ms behind schedule",
                        extra={"cycle": self.cycle_count, "cadence_lag_ms": cadence_lag},
                    )

            try:
                # Skip if paused
                if self.paused:
                    logger.info(
                        "Service paused; skipping cycle",
                        extra={
                            "cycle": self.cycle_count,
                            "pause_reason": self.pause_reason,
                        },
                    )
                    # Reset cadence scheduler on pause to avoid catch-up storm on resume
                    if self.cadence_scheduler:
                        self.cadence_scheduler.reset()
                    await asyncio.sleep(self.config.scan_interval)
                    continue

                # Fetch latest data with error handling
                try:
                    market_data = await self.data_fetcher.fetch_latest_data()

                    # Check if data is empty due to connection issues
                    is_connection_error = ErrorHandler.is_connection_error_from_data(
                        market_data,
                        data_provider=self.data_fetcher.data_provider,
                        last_successful_cycle=self.last_successful_cycle,
                    )

                    if is_connection_error:
                        # This is a connection issue, not just empty data
                        self.connection_failures += 1
                        self.data_fetch_errors += 1
                        self.error_count += 1

                        # Alert on connection failures
                        await self._handle_connection_failure()

                        # Circuit breaker: pause service if too many connection failures
                        if self.connection_failures >= self.max_connection_failures:
                            logger.error(
                                "Circuit breaker triggered: connection failures",
                                extra={
                                    "connection_failures": self.connection_failures,
                                    "max_connection_failures": self.max_connection_failures,
                                    "cycle": self.cycle_count,
                                },
                            )
                            await self.telegram_notifier.send_circuit_breaker_alert(
                                "IB Gateway connection lost",
                                {
                                    "connection_failures": self.connection_failures,
                                    "error_type": "connection",
                                    "action_taken": "Service paused - IB Gateway appears to be down",
                                }
                            )
                            self.paused = True
                            self.pause_reason = "connection_failures"

                        await self._sleep_until_next_cycle()
                        continue

                    # Success - reset error counters
                    self.data_fetch_errors = 0
                    self.connection_failures = 0
                    self.last_successful_cycle = datetime.now(timezone.utc)

                    # Check data quality
                    await self._check_data_quality(market_data)

                except Exception as e:
                    # Use ErrorHandler for standardized error handling
                    error_info = ErrorHandler.handle_data_fetch_error(
                        e,
                        context={"cycle_count": self.cycle_count},
                    )
                    self.data_fetch_errors += 1
                    self.error_count += 1

                    # Check if this is a connection error
                    if error_info.get("is_connection_error", False):
                        self.connection_failures += 1
                        await self._handle_connection_failure()

                    # Alert on consecutive fetch failures
                    if self.data_fetch_errors >= 3:
                        await self.telegram_notifier.send_data_quality_alert(
                            "fetch_failure",
                            f"Consecutive data fetch failures: {self.data_fetch_errors}",
                            {"consecutive_failures": self.data_fetch_errors},
                        )

                    # Circuit breaker: if too many data fetch errors, wait longer
                    if self.data_fetch_errors >= self.max_data_fetch_errors:
                        logger.warning(
                            "Data fetch error threshold reached; backing off",
                            extra={
                                "data_fetch_errors": self.data_fetch_errors,
                                "max_data_fetch_errors": self.max_data_fetch_errors,
                                "backoff_seconds": self.config.scan_interval * 2,
                                "cycle": self.cycle_count,
                            },
                        )
                        await self._notify_error("Data fetch failures", f"{self.data_fetch_errors} consecutive errors")
                        # Backoff: sleep longer than normal cycle, reset cadence scheduler
                        if self.cadence_scheduler:
                            self.cadence_scheduler.reset()
                        await asyncio.sleep(self.config.scan_interval * 2)
                    else:
                        await self._sleep_until_next_cycle()
                    continue

                if market_data["df"].empty:
                    # Empty data could be normal (market closed) or a problem
                    # Check if we've had recent successful cycles
                    if self.last_successful_cycle:
                        time_since_success = (datetime.now(timezone.utc) - self.last_successful_cycle).total_seconds()
                        timeout_seconds = self.connection_timeout_minutes * 60
                        if time_since_success > timeout_seconds:
                            logger.warning(f"No market data for {self.connection_timeout_minutes}+ minutes - possible connection issue")
                            await self._handle_connection_failure()

                    # Determine quiet reason for observability
                    quiet_reason = self._get_quiet_reason(market_data, has_data=False)
                    
                    logger.debug(
                        "No market data available, waiting",
                        extra={
                            "cycle": self.cycle_count,
                            "connection_failures": self.connection_failures,
                            "quiet_reason": quiet_reason,
                        },
                    )
                    
                    # Still emit dashboard even when quiet (observability)
                    await self._check_dashboard(market_data, quiet_reason=quiet_reason)
                    self.cycle_count += 1
                    
                    await self._sleep_until_next_cycle()
                    continue

                # Generate signals
                signals = self.strategy.analyze(market_data)
                
                # Log cycle summary for observability
                data_fresh = True
                if market_data.get("latest_bar"):
                    latest_bar_time = market_data["latest_bar"].get("timestamp")
                    if latest_bar_time:
                        if isinstance(latest_bar_time, str):
                            latest_bar_time = parse_utc_timestamp(latest_bar_time)
                        age_seconds = (datetime.now(timezone.utc) - latest_bar_time.replace(tzinfo=timezone.utc)).total_seconds()
                        stale_threshold_seconds = self.stale_data_threshold_minutes * 60
                        data_fresh = age_seconds < stale_threshold_seconds
                
                strategy_session_open = self.strategy.scanner.is_market_hours()
                futures_market_open = False
                try:
                    futures_market_open = bool(get_market_hours().is_market_open())
                except Exception:
                    futures_market_open = False
                regime_info = "unknown"
                if hasattr(self.strategy, 'scanner') and hasattr(self.strategy.scanner, 'regime_detector'):
                    # Try to get last detected regime (would need to store it)
                    regime_info = "detected"
                
                logger.info(
                    "Cycle completed",
                    extra={
                        "cycle": self.cycle_count,
                        "signals": len(signals),
                        "data_fresh": data_fresh,
                        # Keep legacy field name for backward compatibility, but make semantics explicit.
                        # Historically this has meant the strategy trading session window (09:30–16:00 ET).
                        "market_open": strategy_session_open,
                        "strategy_session_open": strategy_session_open,
                        "futures_market_open": futures_market_open,
                        "buffer_size": self.data_fetcher.get_buffer_size(),
                        "error_count": self.error_count,
                        "consecutive_errors": self.consecutive_errors,
                        "connection_failures": self.connection_failures,
                        "data_fetch_errors": self.data_fetch_errors,
                    },
                )

                # Process signals
                if signals:
                    logger.info(f"🔔 Processing {len(signals)} signal(s) from strategy analysis")
                    for i, signal in enumerate(signals, 1):
                        signal_type = signal.get('type', 'unknown')
                        signal_direction = signal.get('direction', 'unknown')
                        logger.info(f"  Signal {i}/{len(signals)}: {signal_type} {signal_direction}")
                        # Get buffer data for chart generation
                        buffer_data = market_data.get("df", pd.DataFrame())
                        await self._process_signal(signal, buffer_data=buffer_data)
                else:
                    logger.debug(f"No signals generated in cycle {self.cycle_count}")

                # Virtual PnL lifecycle: exit signals when TP/SL is touched (no Telegram spam).
                # This grades signal quality without auto-trading.
                try:
                    self._update_virtual_trade_exits(market_data)
                except Exception as e:
                    logger.debug(f"Virtual exit update failed (non-fatal): {e}")

                # Send periodic dashboard (replaces status + heartbeat)
                # Determine quiet reason if no signals (for observability)
                quiet_reason = None
                signal_diagnostics = None
                if not signals:
                    quiet_reason = self._get_quiet_reason(market_data, has_data=True, no_signals=True)
                    # Get signal diagnostics for no-signal observability
                    if hasattr(self.strategy, 'generator') and hasattr(self.strategy.generator, 'last_diagnostics'):
                        signal_diagnostics = self.strategy.generator.last_diagnostics
                await self._check_dashboard(market_data, quiet_reason=quiet_reason, signal_diagnostics=signal_diagnostics)

                # Save state periodically
                if self.cycle_count % self.state_save_interval == 0:
                    self._save_state()

                self.cycle_count += 1

                # Wait for next cycle (fixed-cadence or legacy sleep-after-work)
                await self._sleep_until_next_cycle()

            except asyncio.CancelledError:
                logger.info("Service loop cancelled", extra={"cycle": self.cycle_count})
                break
            except Exception as e:
                logger.error(
                    f"Error in service loop: {e}",
                    exc_info=True,
                    extra={"cycle": self.cycle_count},
                )
                self.error_count += 1
                self.consecutive_errors += 1

                # Circuit breaker: if too many consecutive errors, pause service
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logger.error(
                        "Circuit breaker triggered: consecutive errors",
                        extra={
                            "consecutive_errors": self.consecutive_errors,
                            "max_consecutive_errors": self.max_consecutive_errors,
                            "cycle": self.cycle_count,
                        },
                    )
                    await self.telegram_notifier.send_circuit_breaker_alert(
                        "Too many consecutive errors",
                        {
                            "consecutive_errors": self.consecutive_errors,
                            "error_type": "general",
                            "action_taken": "Service paused",
                        },
                    )
                    self.paused = True
                    self.pause_reason = "consecutive_errors"

                await self._sleep_until_next_cycle()
            else:
                # Reset consecutive errors on successful cycle
                had_errors = self.consecutive_errors > 0
                self.consecutive_errors = 0

                # Send recovery notification if we had errors and now recovered
                if had_errors:
                    try:
                        await self.telegram_notifier.send_recovery_notification({
                            "issue": "Consecutive errors resolved",
                            "recovery_time_seconds": 0,
                        })
                    except Exception as e:
                        logger.warning(f"Could not send recovery notification: {e}")

    async def _process_signal(self, signal: Dict, buffer_data: Optional[pd.DataFrame] = None) -> None:
        """
        Process a trading signal.
        
        Args:
            signal: Signal dictionary
            buffer_data: Optional DataFrame with OHLCV data for chart generation
        """
        try:
            # Track signal generation (delegates to state_manager for persistence)
            signal_id = self.performance_tracker.track_signal_generated(signal)
            self.last_signal_generated_at = get_utc_timestamp()
            self.last_signal_id_prefix = str(signal_id)[:16]

            # Virtual entry: enter immediately at the signal's entry price.
            # This enables per-signal PnL tracking without requiring IBKR fills.
            try:
                entry_price = float(signal.get("entry_price") or 0.0)
                if entry_price > 0:
                    self.performance_tracker.track_entry(
                        signal_id=signal_id,
                        entry_price=entry_price,
                        entry_time=datetime.now(timezone.utc),
                    )
            except Exception as e:
                logger.debug(f"Could not track virtual entry for {signal_id}: {e}")

            # Send to Telegram (await async call) with buffer data for chart generation
            signal_type = signal.get('type', 'unknown')
            signal_direction = signal.get('direction', 'unknown')
            logger.info(f"Processing signal: {signal_type} {signal_direction}")
            
            success = await self.telegram_notifier.send_signal(signal, buffer_data=buffer_data)

            if success:
                logger.info(f"✅ Signal sent to Telegram: {signal_type} {signal_direction}")
                self.signals_sent += 1
                self.last_signal_sent_at = get_utc_timestamp()
                # Clear last error on success to avoid stale operator confusion.
                self.last_signal_send_error = None
            else:
                logger.error(
                    f"❌ Failed to send signal to Telegram: {signal_type} {signal_direction}. "
                    f"Telegram enabled: {self.telegram_notifier.enabled}, "
                    f"Telegram instance: {self.telegram_notifier.telegram is not None}"
                )
                self.signals_send_failures += 1
                try:
                    err = None
                    if self.telegram_notifier.telegram is not None:
                        err = getattr(self.telegram_notifier.telegram, "last_error", None)
                    if err:
                        self.last_signal_send_error = str(err)[:200]
                except Exception:
                    # Keep prior error if we can’t read the latest reason.
                    pass

            self.signal_count += 1

        except Exception as e:
            logger.error(f"Error processing signal: {e}", exc_info=True)
            self.error_count += 1

    def _update_virtual_trade_exits(self, market_data: Dict) -> None:
        """
        Update virtual trade exits for any `entered` signals when TP/SL is touched.

        Rules:
        - Entry is immediate at signal generation time.
        - Exit occurs on first *touch* of TP/SL using latest bar OHLC.
        - If TP and SL are both touched in the same bar, tiebreak is determined by
          config.virtual_pnl_tiebreak ("stop_loss" = conservative, "take_profit" = optimistic).
        """
        # Get tiebreak preference from config (default to conservative "stop_loss")
        tiebreak = getattr(self.config, "virtual_pnl_tiebreak", "stop_loss")
        latest_bar = market_data.get("latest_bar") if isinstance(market_data, dict) else None
        if not isinstance(latest_bar, dict):
            return

        # Parse bar timestamp (UTC)
        bar_ts = latest_bar.get("timestamp")
        if isinstance(bar_ts, str):
            bar_ts = parse_utc_timestamp(bar_ts)
        elif isinstance(bar_ts, pd.Timestamp):
            bar_ts = bar_ts.to_pydatetime()
        if isinstance(bar_ts, datetime) and bar_ts.tzinfo is None:
            bar_ts = bar_ts.replace(tzinfo=timezone.utc)

        try:
            bar_high = float(latest_bar.get("high") or latest_bar.get("close") or 0.0)
            bar_low = float(latest_bar.get("low") or latest_bar.get("close") or 0.0)
        except Exception:
            return
        if bar_high <= 0 or bar_low <= 0:
            return

        # Consider only recently tracked signals for performance; active trades should be among them.
        try:
            recent = self.state_manager.get_recent_signals(limit=300)
        except Exception:
            return

        exited_this_cycle: set[str] = set()
        for rec in recent:
            try:
                if not isinstance(rec, dict) or rec.get("status") != "entered":
                    continue
                sig_id = str(rec.get("signal_id") or "")
                if not sig_id or sig_id in exited_this_cycle:
                    continue

                # Optional: only evaluate once bars have progressed beyond entry_time
                entry_time_str = rec.get("entry_time")
                if entry_time_str and isinstance(bar_ts, datetime):
                    try:
                        et = parse_utc_timestamp(str(entry_time_str))
                        if et and et.tzinfo is None:
                            et = et.replace(tzinfo=timezone.utc)
                        if et and bar_ts < et:
                            continue
                    except Exception:
                        pass

                sig = rec.get("signal", {}) or {}
                direction = str(sig.get("direction") or "long").lower()
                try:
                    stop = float(sig.get("stop_loss") or 0.0)
                    target = float(sig.get("take_profit") or 0.0)
                except Exception:
                    continue
                if stop <= 0 or target <= 0:
                    continue

                exit_reason = None
                exit_price = None

                if direction == "short":
                    hit_tp = bar_low <= target
                    hit_sl = bar_high >= stop
                    if hit_tp and hit_sl:
                        # Both touched in same bar - use configured tiebreak
                        if tiebreak == "take_profit":
                            exit_reason = "take_profit"
                            exit_price = target
                        else:  # Default to conservative "stop_loss"
                            exit_reason = "stop_loss"
                            exit_price = stop
                    elif hit_sl:
                        exit_reason = "stop_loss"
                        exit_price = stop
                    elif hit_tp:
                        exit_reason = "take_profit"
                        exit_price = target
                else:
                    hit_tp = bar_high >= target
                    hit_sl = bar_low <= stop
                    if hit_tp and hit_sl:
                        # Both touched in same bar - use configured tiebreak
                        if tiebreak == "take_profit":
                            exit_reason = "take_profit"
                            exit_price = target
                        else:  # Default to conservative "stop_loss"
                            exit_reason = "stop_loss"
                            exit_price = stop
                    elif hit_sl:
                        exit_reason = "stop_loss"
                        exit_price = stop
                    elif hit_tp:
                        exit_reason = "take_profit"
                        exit_price = target

                if exit_reason and exit_price is not None:
                    perf = self.performance_tracker.track_exit(
                        signal_id=sig_id,
                        exit_price=float(exit_price),
                        exit_reason=str(exit_reason),
                        exit_time=bar_ts if isinstance(bar_ts, datetime) else None,
                    )
                    exited_this_cycle.add(sig_id)
                    if perf:
                        logger.info(
                            "Virtual exit: %s | %s | exit=%s | pnl=%s",
                            sig_id[:16],
                            exit_reason,
                            f"{float(exit_price):.2f}",
                            f"{float(perf.get('pnl', 0.0)):.2f}",
                        )
            except Exception:
                continue

    async def _check_dashboard(
        self,
        market_data: Optional[Dict] = None,
        quiet_reason: Optional[str] = None,
        signal_diagnostics=None,
    ) -> None:
        """
        Send periodic dashboard message (replaces status + heartbeat).
        
        Args:
            market_data: Current market data (may be empty)
            quiet_reason: Why the agent is quiet (e.g., "StrategySessionClosed")
            signal_diagnostics: SignalDiagnostics from the signal generator
        """
        now = datetime.now(timezone.utc)

        # Check if it's time for a text dashboard update (every 15m by default)
        if (
            self.last_status_update is None
            or (now - self.last_status_update).total_seconds() >= self.status_update_interval
        ):
            await self._send_dashboard(market_data, quiet_reason=quiet_reason, signal_diagnostics=signal_diagnostics)
            self.last_status_update = now

        # Check if it's time for a dashboard chart (every 60m by default)
        if (
            self.last_dashboard_chart_sent is None
            or (now - self.last_dashboard_chart_sent).total_seconds() >= self.dashboard_chart_interval
        ):
            await self._send_dashboard_chart()
            self.last_dashboard_chart_sent = now

    async def _send_dashboard_chart(self) -> None:
        """
        Generate and send a 24h/5m mplfinance dashboard chart.
        
        Fetches 24h of 5m historical data and generates a TradingView-style chart.
        """
        try:
            # Check if chart generator is available
            if not self.telegram_notifier.chart_generator:
                logger.debug("Chart generator not available for dashboard chart")
                return

            # Fetch lookback window for chart (prefer direct historical fetch; fallback to buffers)
            # Ensure we always show at least a useful minimum window (operator request: >= 6h)
            min_lookback_hours = 6.0
            lookback_hours = float(self.dashboard_chart_lookback_hours or 48)
            if lookback_hours < min_lookback_hours:
                lookback_hours = min_lookback_hours
            chart_tf = (self.dashboard_chart_timeframe or "auto").strip().lower()

            def _choose_timeframe(hours: float, max_bars: int) -> str:
                # Keep candle count under max_bars for readability.
                candidates = ["5m", "15m", "30m", "1h"]
                if chart_tf in candidates:
                    return chart_tf
                # auto
                for tf in candidates:
                    mins = timeframe_to_minutes(tf) or 0
                    if mins <= 0:
                        continue
                    bars = int((hours * 60.0) / float(mins))
                    if bars <= max_bars:
                        return tf
                return "1h"

            chosen_tf = _choose_timeframe(lookback_hours, int(self.dashboard_chart_max_bars or 420))
            max_bars = int(self.dashboard_chart_max_bars or 420)
            tf_mins = float(timeframe_to_minutes(chosen_tf) or 5)
            bars_target = int((lookback_hours * 60.0) / tf_mins)
            # Guarantee at least 6h of history regardless of timeframe selection.
            min_bars_for_min_hours = int(math.ceil((min_lookback_hours * 60.0) / tf_mins))
            bars_target = max(50, min_bars_for_min_hours, min(max_bars, bars_target))

            logger.debug(
                f"Fetching dashboard chart data: lookback_hours={lookback_hours}, timeframe={chosen_tf}, bars={bars_target}"
            )

            chart_data = None
            try:
                end = datetime.now(timezone.utc)
                start = end - timedelta(hours=lookback_hours)
                loop = asyncio.get_event_loop()
                df_hist = await loop.run_in_executor(
                    None,
                    lambda: self.data_fetcher.data_provider.fetch_historical(
                        self.config.symbol,
                        start=start,
                        end=end,
                        timeframe=chosen_tf,
                    ),
                )
                if isinstance(df_hist, pd.DataFrame) and not df_hist.empty:
                    chart_data = df_hist.tail(min(int(bars_target), len(df_hist))).copy()
            except Exception as e:
                logger.debug(f"Direct historical fetch for dashboard chart failed: {e}")

            # If the full lookback request failed, retry with the minimum window (less load, more likely to succeed).
            if chart_data is None or chart_data.empty:
                try:
                    end = datetime.now(timezone.utc)
                    start = end - timedelta(hours=min_lookback_hours)
                    loop = asyncio.get_event_loop()
                    df_hist = await loop.run_in_executor(
                        None,
                        lambda: self.data_fetcher.data_provider.fetch_historical(
                            self.config.symbol,
                            start=start,
                            end=end,
                            timeframe=chosen_tf,
                        ),
                    )
                    if isinstance(df_hist, pd.DataFrame) and not df_hist.empty:
                        chart_data = df_hist.tail(min(int(bars_target), len(df_hist))).copy()
                except Exception as e:
                    logger.debug(f"Min-window historical fetch for dashboard chart failed: {e}")
            
            def _resample_ohlcv(df_in: pd.DataFrame, target_tf: str) -> pd.DataFrame:
                """Best-effort resample of OHLCV data to target timeframe."""
                try:
                    mins = timeframe_to_minutes(target_tf)
                    if not mins or mins <= 0:
                        return df_in
                    rule = f"{int(mins)}T"
                    df = df_in.copy()
                    if "timestamp" in df.columns:
                        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
                        df = df.dropna(subset=["timestamp"]).set_index("timestamp")
                    elif isinstance(df.index, pd.DatetimeIndex):
                        pass
                    else:
                        return df_in

                    need_cols = {"open", "high", "low", "close"}
                    if not need_cols.issubset(set(df.columns)):
                        return df_in

                    ohlc = df[["open", "high", "low", "close"]].resample(rule).agg(
                        {"open": "first", "high": "max", "low": "min", "close": "last"}
                    )
                    if "volume" in df.columns:
                        vol = df["volume"].resample(rule).sum()
                        ohlc["volume"] = vol
                    ohlc = ohlc.dropna(subset=["open", "high", "low", "close"]).reset_index()
                    return ohlc
                except Exception:
                    return df_in

            # Buffer fallback (timeframe-aware). This should be rare; used only if historical fetch fails.
            if chart_data is None or chart_data.empty:
                buf = None
                try:
                    if chosen_tf == "15m":
                        buf = getattr(self.data_fetcher, "_data_buffer_15m", None)
                    elif chosen_tf == "5m":
                        buf = getattr(self.data_fetcher, "_data_buffer_5m", None)
                    # If we don't have a matching buffer, resample from whatever we do have.
                    if buf is None or not isinstance(buf, pd.DataFrame) or buf.empty:
                        base = (
                            getattr(self.data_fetcher, "_data_buffer", None)
                            or getattr(self.data_fetcher, "_data_buffer_5m", None)
                            or getattr(self.data_fetcher, "_data_buffer_15m", None)
                        )
                        if isinstance(base, pd.DataFrame) and not base.empty:
                            buf = _resample_ohlcv(base, chosen_tf)
                except Exception:
                    buf = None

                if isinstance(buf, pd.DataFrame) and not buf.empty:
                    chart_data = buf.tail(min(int(bars_target), len(buf))).copy()
                    logger.debug(f"Using buffer fallback for dashboard chart: {len(chart_data)} bars (tf={chosen_tf})")
            
            if chart_data is None or chart_data.empty or len(chart_data) < 20:
                logger.debug("Not enough data for dashboard chart (need at least 20 bars)")
                return
            
            # Generate the chart
            # Prefer an accurate label based on the actual data window (avoids "48h" when fallback data is shorter).
            range_label = None
            try:
                tmin = None
                tmax = None
                if isinstance(chart_data, pd.DataFrame):
                    if "timestamp" in chart_data.columns:
                        ts = pd.to_datetime(chart_data["timestamp"], errors="coerce")
                        if not ts.isna().all():
                            tmin = ts.min()
                            tmax = ts.max()
                    elif isinstance(chart_data.index, pd.DatetimeIndex) and len(chart_data.index) > 0:
                        tmin = chart_data.index.min()
                        tmax = chart_data.index.max()
                if tmin is not None and tmax is not None and pd.notna(tmin) and pd.notna(tmax):
                    hrs = float((tmax - tmin).total_seconds()) / 3600.0
                    if hrs >= 72:
                        range_label = f"{max(1, int(round(hrs / 24.0)))}d"
                    else:
                        range_label = f"{max(1, int(round(hrs)))}h"
            except Exception:
                range_label = None
            if not range_label:
                range_label = f"{int(lookback_hours)}h" if lookback_hours < 72 else f"{int(round(lookback_hours/24))}d"

            chart_path = self.telegram_notifier.chart_generator.generate_dashboard_chart(
                data=chart_data,
                symbol=self.config.symbol,
                timeframe=chosen_tf,
                lookback_bars=min(int(bars_target), len(chart_data)),
                range_label=range_label,
                figsize=(16, 7),
                dpi=150,
                show_pressure=self.dashboard_chart_show_pressure,
            )
            
            if chart_path and chart_path.exists():
                # Send the chart
                success = await self.telegram_notifier.send_dashboard_chart(
                    chart_path=chart_path,
                    symbol=self.config.symbol,
                    timeframe=chosen_tf,
                    range_label=range_label,
                )
                
                # Clean up temp file
                try:
                    chart_path.unlink()
                except Exception:
                    pass
                
                if success:
                    logger.info("Dashboard chart sent to Telegram")
                else:
                    logger.warning("Failed to send dashboard chart")
            else:
                logger.debug("Dashboard chart generation returned no path")
                
        except Exception as e:
            logger.error(f"Error generating/sending dashboard chart: {e}", exc_info=True)

    async def _send_dashboard(
        self,
        market_data: Optional[Dict] = None,
        quiet_reason: Optional[str] = None,
        signal_diagnostics=None,
    ) -> None:
        """
        Send consolidated dashboard to Telegram.
        
        Args:
            market_data: Current market data (may be empty)
            quiet_reason: Why the agent is quiet (for observability)
            signal_diagnostics: SignalDiagnostics from the signal generator
        """
        try:
            # Get base status
            status = self.get_status()
            
            # Add current time
            status["current_time"] = datetime.now(timezone.utc)
            status["symbol"] = self.config.symbol
            
            # Add quiet reason for observability (why no signals)
            if quiet_reason:
                status["quiet_reason"] = quiet_reason
            
            # Add signal diagnostics when no signals (for observability)
            if signal_diagnostics is not None:
                status["signal_diagnostics"] = signal_diagnostics.format_compact()
                status["signal_diagnostics_raw"] = signal_diagnostics.to_dict()
            
            # Try to get latest price
            try:
                if market_data and market_data.get("latest_bar"):
                    latest_bar = market_data["latest_bar"]
                    if isinstance(latest_bar, dict) and "close" in latest_bar:
                        status["latest_price"] = latest_bar["close"]
            except Exception:
                pass
            
            # Get recent closes for sparkline
            recent_closes = self._get_recent_closes(market_data)
            status["recent_closes"] = recent_closes
            
            # Get MTF trend arrows
            mtf_trends = self._compute_mtf_trends(market_data)
            status["mtf_trends"] = mtf_trends

            # Buy/Sell pressure (volume-based proxy) for 15m dashboard notifications
            try:
                df_for_pressure = None
                if market_data and "df" in market_data and market_data["df"] is not None:
                    df_for_pressure = market_data["df"]
                elif getattr(self.data_fetcher, "_data_buffer", None) is not None:
                    df_for_pressure = getattr(self.data_fetcher, "_data_buffer")

                if isinstance(df_for_pressure, pd.DataFrame) and not df_for_pressure.empty:
                    summary = compute_volume_pressure_summary(
                        df_for_pressure,
                        lookback_bars=self.pressure_lookback_bars,
                        baseline_bars=self.pressure_baseline_bars,
                        open_col="open",
                        close_col="close",
                        volume_col="volume",
                    )
                    if summary is not None:
                        tf_min = timeframe_to_minutes(getattr(self.config, "timeframe", "") or "")
                        status["buy_sell_pressure_raw"] = summary.to_dict()
                        status["buy_sell_pressure"] = format_volume_pressure(
                            summary,
                            timeframe_minutes=tf_min,
                            data_fresh=status.get("data_fresh"),
                        )
            except Exception:
                # Never let optional observability break the dashboard.
                pass
            
            await self.telegram_notifier.send_dashboard(status)
        except Exception as e:
            logger.error(f"Error sending dashboard: {e}", exc_info=True)
    
    def _get_recent_closes(self, market_data: Optional[Dict] = None) -> list:
        """Extract recent close prices for sparkline."""
        try:
            if market_data and "df" in market_data and not market_data["df"].empty:
                df = market_data["df"]
                if "close" in df.columns:
                    # Get last 50 closes (about 4 hours of 5m data)
                    closes = df["close"].tail(50).tolist()
                    return [float(c) for c in closes if c is not None]
            
            # Fallback to buffer
            if self.data_fetcher._data_buffer is not None and not self.data_fetcher._data_buffer.empty:
                df = self.data_fetcher._data_buffer
                if "close" in df.columns:
                    closes = df["close"].tail(50).tolist()
                    return [float(c) for c in closes if c is not None]
        except Exception as e:
            logger.debug(f"Could not get recent closes for sparkline: {e}")
        
        return []
    
    def _compute_mtf_trends(self, market_data: Optional[Dict] = None) -> dict:
        """
        Compute compact trend arrows for multiple timeframes.
        
        Returns dict mapping timeframe -> slope value for trend_arrow() conversion.
        """
        trends = {}
        
        try:
            # 5m trend from primary buffer (which is now 5m)
            if self.data_fetcher._data_buffer is not None and len(self.data_fetcher._data_buffer) >= 10:
                df = self.data_fetcher._data_buffer
                if "close" in df.columns:
                    closes = df["close"].tail(10)
                    if len(closes) >= 2:
                        slope = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
                        trends["5m"] = float(slope)
            
            # 15m trend from 15m buffer
            if market_data and "df_15m" in market_data and not market_data["df_15m"].empty:
                df_15m = market_data["df_15m"]
                if "close" in df_15m.columns and len(df_15m) >= 5:
                    closes = df_15m["close"].tail(5)
                    if len(closes) >= 2:
                        slope = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
                        trends["15m"] = float(slope)
            
            # Resample from available data to get longer timeframes
            # (these will be computed from 15m data if available)
            if market_data and "df_15m" in market_data and not market_data["df_15m"].empty:
                df_15m = market_data["df_15m"]
                if "close" in df_15m.columns:
                    # 1h: look at 4 bars of 15m data
                    if len(df_15m) >= 4:
                        closes_1h = df_15m["close"].tail(4)
                        if len(closes_1h) >= 2:
                            slope = (closes_1h.iloc[-1] - closes_1h.iloc[0]) / closes_1h.iloc[0] * 100
                            trends["1h"] = float(slope)
                    
                    # 4h: look at 16 bars of 15m data
                    if len(df_15m) >= 16:
                        closes_4h = df_15m["close"].tail(16)
                        if len(closes_4h) >= 2:
                            slope = (closes_4h.iloc[-1] - closes_4h.iloc[0]) / closes_4h.iloc[0] * 100
                            trends["4h"] = float(slope)
                    
                    # 1D: look at all available 15m data (up to 96 bars = 24h)
                    if len(df_15m) >= 20:
                        closes_1d = df_15m["close"].tail(min(96, len(df_15m)))
                        if len(closes_1d) >= 2:
                            slope = (closes_1d.iloc[-1] - closes_1d.iloc[0]) / closes_1d.iloc[0] * 100
                            trends["1D"] = float(slope)
        except Exception as e:
            logger.debug(f"Could not compute MTF trends: {e}")
        
        return trends

    def _get_quiet_reason(
        self,
        market_data: Optional[Dict] = None,
        has_data: bool = True,
        no_signals: bool = False,
    ) -> str:
        """
        Determine why the agent is quiet (not generating signals).
        
        Returns a human-readable reason for observability.
        
        Args:
            market_data: Current market data
            has_data: Whether we have any data (False = empty DataFrame)
            no_signals: Whether we had data but no signals were generated
            
        Returns:
            String reason code like "StrategySessionClosed", "FuturesMarketClosed", etc.
        """
        try:
            # Check strategy session first (more specific)
            strategy_session_open = self.strategy.scanner.is_market_hours()
            if not strategy_session_open:
                return "StrategySessionClosed"
            
            # Check futures market hours
            futures_market_open = get_market_hours().is_market_open()
            if not futures_market_open:
                return "FuturesMarketClosed"
            
            # Check if we have no data
            if not has_data or (market_data and market_data.get("df") is not None and market_data["df"].empty):
                # Could be a data gap or stale data
                if self.last_successful_cycle:
                    time_since_success = (datetime.now(timezone.utc) - self.last_successful_cycle).total_seconds()
                    if time_since_success > self.stale_data_threshold_minutes * 60:
                        return "StaleData"
                    elif time_since_success > 60:
                        return "DataGap"
                return "NoData"
            
            # We have data but no signals
            if no_signals:
                # Check data freshness
                latest_bar = market_data.get("latest_bar") if market_data else None
                if latest_bar:
                    bar_time = latest_bar.get("timestamp")
                    if bar_time:
                        if isinstance(bar_time, str):
                            bar_time = parse_utc_timestamp(bar_time)
                        age_seconds = (datetime.now(timezone.utc) - bar_time.replace(tzinfo=timezone.utc)).total_seconds()
                        if age_seconds > self.stale_data_threshold_minutes * 60:
                            return "StaleData"
                
                # No signals but data is fresh - strategy just didn't find opportunities
                return "NoOpportunity"
            
            return "Active"
            
        except Exception as e:
            logger.debug(f"Could not determine quiet reason: {e}")
            return "Unknown"

    async def _check_status_update(self) -> None:
        """Send periodic status updates to Telegram (legacy, now uses dashboard)."""
        # Kept for backward compatibility - now handled by _check_dashboard
        pass

    async def _send_status_update(self) -> None:
        """Send status update to Telegram (legacy, now uses dashboard)."""
        try:
            # Use enhanced status with performance metrics
            status = self.get_status()
            await self.telegram_notifier.send_enhanced_status(status)
        except Exception as e:
            logger.error(f"Error sending status update: {e}", exc_info=True)

    def pause(self) -> None:
        """Pause the service."""
        self.paused = True
        self.pause_reason = "manual"
        logger.info("Service paused", extra={"pause_reason": self.pause_reason})

    def resume(self) -> None:
        """Resume the service."""
        self.paused = False
        self.pause_reason = None
        # Reset cadence scheduler to avoid catch-up storm
        if self.cadence_scheduler:
            self.cadence_scheduler.reset()
        logger.info("Service resumed")

    async def _sleep_until_next_cycle(self) -> None:
        """
        Sleep until the next cycle should start.
        
        In fixed-cadence mode, computes sleep time to maintain start-to-start timing.
        In legacy mode, sleeps for the full scan_interval after work completes.
        """
        if self.cadence_scheduler:
            # Fixed-cadence mode: compute sleep time based on cycle end
            sleep_time = self.cadence_scheduler.mark_cycle_end()
            metrics = self.cadence_scheduler.get_metrics()
            
            # Log if we're running behind schedule
            if metrics.missed_cycles > 0:
                logger.debug(
                    f"Cadence: {metrics.cycle_duration_ms:.0f}ms work, "
                    f"sleeping {sleep_time*1000:.0f}ms, "
                    f"{metrics.missed_cycles} cycles skipped total"
                )
            
            await asyncio.sleep(sleep_time)
        else:
            # Legacy mode: sleep full interval after work
            await asyncio.sleep(self.config.scan_interval)

    async def _notify_error(self, title: str, message: str) -> None:
        """Notify about errors via Telegram."""
        try:
            if self.telegram_notifier.enabled and self.telegram_notifier.telegram:
                await self.telegram_notifier.telegram.notify_risk_warning(
                    f"{title}\n\n{message}",
                    risk_status="ERROR",
                )
        except Exception as e:
            logger.error(f"Error sending error notification: {e}")

    def get_status(self) -> Dict:
        """Get current service status."""
        uptime = None
        if self.start_time:
            uptime_delta = datetime.now(timezone.utc) - self.start_time
            uptime = {
                "hours": int(uptime_delta.total_seconds() / 3600),
                "minutes": int((uptime_delta.total_seconds() % 3600) / 60),
            }

        # Get performance metrics
        performance = self.performance_tracker.get_performance_metrics(days=7)

        # Get health status
        health = self.health_monitor.get_overall_health(
            data_provider=self.data_fetcher.data_provider,
            telegram_notifier=self.telegram_notifier,
        )

        # Extract data source health
        data_source_health = health.get("components", {}).get("data_provider", {})

        # Check connection status
        connection_status = "unknown"
        try:
            if hasattr(self.data_fetcher.data_provider, '_executor'):
                executor = self.data_fetcher.data_provider._executor
                if hasattr(executor, 'is_connected'):
                    connection_status = "connected" if executor.is_connected() else "disconnected"
        except Exception:
            pass

        # Get latest bar for order book info
        latest_bar = None
        try:
            # Try to get latest market data (non-blocking)
            if hasattr(self, 'data_fetcher'):
                # Get the last fetched market data if available
                if hasattr(self.data_fetcher, '_last_market_data'):
                    market_data = self.data_fetcher._last_market_data
                    latest_bar = market_data.get("latest_bar")
        except Exception:
            pass  # Ignore errors when getting latest bar for status

        # Market/session status
        futures_market_open = None
        try:
            futures_market_open = bool(get_market_hours().is_market_open())
        except Exception:
            futures_market_open = None

        strategy_session_open = None
        try:
            strategy_session_open = bool(self.strategy.scanner.is_market_hours())
        except Exception:
            strategy_session_open = None

        return {
            "running": self.running,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime": uptime,
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "signals_sent": self.signals_sent,
            "signals_send_failures": self.signals_send_failures,
            "last_signal_send_error": self.last_signal_send_error,
            "last_signal_generated_at": self.last_signal_generated_at,
            "last_signal_sent_at": self.last_signal_sent_at,
            "last_signal_id_prefix": self.last_signal_id_prefix,
            "cycle_count_session": (
                (self.cycle_count - self._cycle_count_at_start)
                if self._cycle_count_at_start is not None
                else None
            ),
            "signal_count_session": (
                (self.signal_count - self._signal_count_at_start)
                if self._signal_count_at_start is not None
                else None
            ),
            "signals_sent_session": (
                (self.signals_sent - self._signals_sent_at_start)
                if self._signals_sent_at_start is not None
                else None
            ),
            "signals_send_failures_session": (
                (self.signals_send_failures - self._signals_fail_at_start)
                if self._signals_fail_at_start is not None
                else None
            ),
            "latest_bar": latest_bar,  # Include for order book transparency
            "error_count": self.error_count,
            "connection_failures": self.connection_failures,
            "connection_status": connection_status,
            "buffer_size": self.data_fetcher.get_buffer_size(),
            "buffer_size_target": self.buffer_size_target,
            "futures_market_open": futures_market_open,
            "strategy_session_open": strategy_session_open,
            "performance": performance,
            "data_source_health": data_source_health,
            "last_successful_cycle": (
                get_utc_timestamp() if self.last_successful_cycle else None
            ),
            "config": {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
            },
            # Cadence metrics for observability
            "cadence_mode": self.cadence_mode,
            "cadence_metrics": (
                self.cadence_scheduler.get_metrics().to_dict()
                if self.cadence_scheduler
                else None
            ),
        }

    def _save_state(self) -> None:
        """Save current service state."""
        # Include lightweight data freshness metadata for Telegram UI / operators.
        latest_bar_timestamp = None
        latest_bar_age_minutes = None
        data_fresh = None
        try:
            last_market_data = getattr(self.data_fetcher, "_last_market_data", None) or {}
            freshness = self.data_quality_checker.check_data_freshness(
                last_market_data.get("latest_bar"),
                last_market_data.get("df"),
            )
            ts = freshness.get("timestamp")
            if ts:
                latest_bar_timestamp = ts.isoformat()
                latest_bar_age_minutes = float(freshness.get("age_minutes", 0.0))
                data_fresh = bool(freshness.get("is_fresh", False))
        except Exception:
            # Never let status persistence fail due to optional metadata.
            pass

        state = {
            "running": self.running,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "signals_sent": self.signals_sent,
            "signals_send_failures": self.signals_send_failures,
            "last_signal_send_error": self.last_signal_send_error,
            "last_signal_generated_at": self.last_signal_generated_at,
            "last_signal_sent_at": self.last_signal_sent_at,
            "last_signal_id_prefix": self.last_signal_id_prefix,
            "cycle_count_session": (
                (self.cycle_count - self._cycle_count_at_start)
                if self._cycle_count_at_start is not None
                else None
            ),
            "signal_count_session": (
                (self.signal_count - self._signal_count_at_start)
                if self._signal_count_at_start is not None
                else None
            ),
            "signals_sent_session": (
                (self.signals_sent - self._signals_sent_at_start)
                if self._signals_sent_at_start is not None
                else None
            ),
            "signals_send_failures_session": (
                (self.signals_send_failures - self._signals_fail_at_start)
                if self._signals_fail_at_start is not None
                else None
            ),
            "buffer_size": self.data_fetcher.get_buffer_size(),
            "buffer_size_target": self.buffer_size_target,
            "data_fresh": data_fresh,
            "latest_bar_timestamp": latest_bar_timestamp,
            "latest_bar_age_minutes": latest_bar_age_minutes,
            "last_successful_cycle": (
                self.last_successful_cycle.isoformat() if self.last_successful_cycle else None
            ),
            # Market/session status used by Telegram UI and operators.
            # - futures_market_open: CME ETH + maintenance break semantics
            # - strategy_session_open: 09:30–16:00 ET strategy window
            "futures_market_open": None,
            "strategy_session_open": None,
            "config": {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
            },
            # Cadence metrics for observability
            "cadence_mode": self.cadence_mode,
            "cadence_metrics": (
                self.cadence_scheduler.get_metrics().to_dict()
                if self.cadence_scheduler
                else None
            ),
            # Buy/Sell pressure (volume-based proxy) for /status parity with push dashboard
            "buy_sell_pressure": None,
            "buy_sell_pressure_raw": None,
        }
        try:
            state["futures_market_open"] = bool(get_market_hours().is_market_open())
        except Exception:
            state["futures_market_open"] = None
        try:
            state["strategy_session_open"] = bool(self.strategy.scanner.is_market_hours())
        except Exception:
            state["strategy_session_open"] = None

        # Compute and persist buy/sell pressure from last market data (best-effort)
        try:
            last_market_data = getattr(self.data_fetcher, "_last_market_data", None) or {}
            df_for_pressure = last_market_data.get("df")
            if isinstance(df_for_pressure, pd.DataFrame) and not df_for_pressure.empty:
                summary = compute_volume_pressure_summary(
                    df_for_pressure,
                    lookback_bars=self.pressure_lookback_bars,
                    baseline_bars=self.pressure_baseline_bars,
                    open_col="open",
                    close_col="close",
                    volume_col="volume",
                )
                if summary is not None:
                    tf_min = timeframe_to_minutes(getattr(self.config, "timeframe", "") or "")
                    state["buy_sell_pressure_raw"] = summary.to_dict()
                    state["buy_sell_pressure"] = format_volume_pressure(
                        summary,
                        timeframe_minutes=tf_min,
                        data_fresh=data_fresh,
                    )
        except Exception:
            pass

        self.state_manager.save_state(state)

    async def _check_heartbeat(self) -> None:
        """Send periodic heartbeat messages."""
        now = datetime.now(timezone.utc)

        # Check if it's time for a heartbeat
        if (
            self.last_heartbeat is None
            or (now - self.last_heartbeat).total_seconds() >= self.heartbeat_interval
        ):
            status = self.get_status()
            status["last_successful_cycle"] = (
                self.last_successful_cycle.isoformat() if self.last_successful_cycle else None
            )
            
            # Add current time and latest price to heartbeat
            status["current_time"] = now
            status["symbol"] = self.config.symbol
            
            # Try to get latest price and order book info
            try:
                market_data = await self.data_fetcher.fetch_latest_data()
                if market_data.get("latest_bar"):
                    latest_bar = market_data["latest_bar"]
                    if isinstance(latest_bar, dict) and "close" in latest_bar:
                        status["latest_price"] = latest_bar["close"]
                        # Include latest_bar for order book transparency in heartbeat
                        status["latest_bar"] = latest_bar
            except Exception as e:
                logger.debug(f"Could not fetch price for heartbeat: {e}")
            
            await self.telegram_notifier.send_heartbeat(status)
            self.last_heartbeat = now

    async def _check_data_quality(self, market_data: Dict) -> None:
        """Check data quality and send alerts if needed."""
        now = datetime.now(timezone.utc)

        # Use DataQualityChecker for validation
        validation = self.data_quality_checker.validate_market_data(market_data)

        # Global throttling (safety): don’t emit too often even if state oscillates.
        throttled = (
            self.last_data_quality_alert is not None
            and (now - self.last_data_quality_alert).total_seconds() < self.data_quality_alert_interval
        )

        # Market open/closed matters for stale data interpretation
        is_market_open = False
        try:
            from pearlalgo.utils.market_hours import get_market_hours

            is_market_open = bool(get_market_hours().is_market_open())
        except Exception:
            # Fail quiet to avoid spam outside market hours if market-hours util breaks
            is_market_open = False

        def _stale_bucket(age_min: float) -> int:
            # Send only when age crosses key thresholds to reduce spam.
            base = [5, 10, 20, 40, 60, int(self.stale_data_threshold_minutes)]
            thresholds = sorted({t for t in base if t > 0})
            for t in reversed(thresholds):
                if age_min >= t:
                    return t
            return int(self.stale_data_threshold_minutes)

        def _buffer_severity(buf: int) -> str:
            # Buffer is “inadequate” only when < 10 bars (DataQualityChecker default).
            if buf <= 0:
                return "empty"
            if buf <= 3:
                return "critical"
            if buf <= 7:
                return "warning"
            return "low"

        # 1) Stale data (only alert during market hours)
        if not validation["freshness"]["is_fresh"]:
            age_minutes = float(validation["freshness"].get("age_minutes", 0.0) or 0.0)
            if is_market_open:
                bucket = _stale_bucket(age_minutes)
                # Only send when bucket changes (10→20→40→60...) AND we’re not throttled.
                if (self._last_stale_bucket != bucket) and (not throttled):
                    await self.telegram_notifier.send_data_quality_alert(
                        "stale_data",
                        f"Data is {age_minutes:.1f} minutes old",
                        {"age_minutes": age_minutes, "bucket": bucket},
                    )
                    self.last_data_quality_alert = now
                    self._last_stale_data_alert_type = "stale_data"
                self._last_stale_bucket = bucket
                self._was_stale_during_market = True
            else:
                logger.debug(
                    f"Data is {age_minutes:.1f} minutes old but market is closed - expected"
                )
            return

        # Recovery: data is fresh again after being stale during market hours.
        if self._was_stale_during_market and is_market_open:
            # Avoid “flapping” recovery spam; allow recovery after 60s even if main throttle is 5m.
            can_recover = (
                self.last_data_quality_alert is None
                or (now - self.last_data_quality_alert).total_seconds() >= 60
            )
            if can_recover:
                await self.telegram_notifier.send_data_quality_alert(
                    "recovery",
                    "Market data recovered (fresh bars again)",
                    {},
                )
                self.last_data_quality_alert = now
            self._was_stale_during_market = False
            self._last_stale_bucket = None

        # 2) Data gap (empty dataframe)
        df = market_data.get("df")
        if df is not None and df.empty:
            self._was_data_gap = True
            if (self._last_stale_data_alert_type != "data_gap") and (not throttled):
                await self.telegram_notifier.send_data_quality_alert(
                    "data_gap",
                    "No market data available",
                    {},
                )
                self.last_data_quality_alert = now
                self._last_stale_data_alert_type = "data_gap"
            return
        if self._was_data_gap:
            can_recover = (
                self.last_data_quality_alert is None
                or (now - self.last_data_quality_alert).total_seconds() >= 60
            )
            if can_recover:
                await self.telegram_notifier.send_data_quality_alert(
                    "recovery",
                    "Market data gap recovered",
                    {},
                )
                self.last_data_quality_alert = now
            self._was_data_gap = False

        # 3) Buffer size issues (only send when severity changes)
        if not validation["buffer_size"]["is_adequate"]:
            buffer_size = int(validation["buffer_size"].get("buffer_size", 0) or 0)
            severity = _buffer_severity(buffer_size)
            if (self._last_buffer_severity != severity) and (not throttled):
                await self.telegram_notifier.send_data_quality_alert(
                    "buffer_issue",
                    f"Buffer size is low: {buffer_size} bars",
                    {"buffer_size": buffer_size, "severity": severity},
                )
                self.last_data_quality_alert = now
                self._last_stale_data_alert_type = "buffer_issue"
            self._last_buffer_severity = severity
            self._was_buffer_inadequate = True
            return

        # Recovery: buffer is adequate again
        if self._was_buffer_inadequate:
            can_recover = (
                self.last_data_quality_alert is None
                or (now - self.last_data_quality_alert).total_seconds() >= 60
            )
            if can_recover:
                await self.telegram_notifier.send_data_quality_alert(
                    "recovery",
                    "Buffer recovered (enough bars for strategy)",
                    {},
                )
                self.last_data_quality_alert = now
            self._was_buffer_inadequate = False
            self._last_buffer_severity = None


    async def _handle_connection_failure(self) -> None:
        """Handle connection failure and send alerts if needed."""
        now = datetime.now(timezone.utc)

        # Throttle connection failure alerts
        if (
            self.last_connection_failure_alert is None
            or (now - self.last_connection_failure_alert).total_seconds() >= self.connection_failure_alert_interval
        ):
            await self.telegram_notifier.send_data_quality_alert(
                "fetch_failure",
                f"IB Gateway connection issue detected ({self.connection_failures} failures). "
                "Check if IB Gateway is running.",
                {
                    "connection_failures": self.connection_failures,
                    "error_type": "connection",
                    "suggestion": "Run: ./scripts/check_gateway_status.sh or ./scripts/start_ibgateway_ibc.sh",
                },
            )
            self.last_connection_failure_alert = now

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        signal_names = {
            signal.SIGINT: "SIGINT (Ctrl+C)",
            signal.SIGTERM: "SIGTERM",
        }
        signal_name = signal_names.get(signum, f"Signal {signum}")
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self.shutdown_requested = True
