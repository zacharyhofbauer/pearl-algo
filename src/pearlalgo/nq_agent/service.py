"""
NQ Agent Service

Main 24/7 service for running NQ intraday strategy.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

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
from pearlalgo.utils.data_quality import DataQualityChecker
from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.market_hours import get_market_hours


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
            },
        )

        while not self.shutdown_requested:
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

                        await asyncio.sleep(self.config.scan_interval)
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
                        await asyncio.sleep(self.config.scan_interval * 2)
                    else:
                        await asyncio.sleep(self.config.scan_interval)
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

                    logger.debug(
                        "No market data available, waiting",
                        extra={
                            "cycle": self.cycle_count,
                            "connection_failures": self.connection_failures,
                        },
                    )
                    await asyncio.sleep(self.config.scan_interval)
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

                # Send periodic status updates
                await self._check_status_update()

                # Send periodic heartbeats
                await self._check_heartbeat()

                # Save state periodically
                if self.cycle_count % self.state_save_interval == 0:
                    self._save_state()

                self.cycle_count += 1

                # Wait for next cycle
                await asyncio.sleep(self.config.scan_interval)

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

                await asyncio.sleep(self.config.scan_interval)
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

        Rules (v1 defaults):
        - Entry is immediate at signal generation time.
        - Exit occurs on first *touch* of TP/SL using latest bar OHLC.
        - If TP and SL are both touched in the same bar, exit is **conservative** (SL first).
        """
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

    async def _check_status_update(self) -> None:
        """Send periodic status updates to Telegram."""
        now = datetime.now(timezone.utc)

        # Check if it's time for a status update
        if (
            self.last_status_update is None
            or (now - self.last_status_update).total_seconds() >= self.status_update_interval
        ):
            await self._send_status_update()
            self.last_status_update = now

    async def _send_status_update(self) -> None:
        """Send status update to Telegram."""
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
        logger.info("Service resumed")

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
        }
        try:
            state["futures_market_open"] = bool(get_market_hours().is_market_open())
        except Exception:
            state["futures_market_open"] = None
        try:
            state["strategy_session_open"] = bool(self.strategy.scanner.is_market_hours())
        except Exception:
            state["strategy_session_open"] = None
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
