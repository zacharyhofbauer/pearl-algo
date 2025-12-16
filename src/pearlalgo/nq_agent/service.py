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

from pearlalgo.utils.logger import logger

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
        self.health_monitor = HealthMonitor(state_dir=state_dir)

        # Load service configuration
        service_config = load_service_config()
        service_settings = service_config.get("service", {})
        circuit_breaker_settings = service_config.get("circuit_breaker", {})
        alert_settings = service_config.get("alerts", {})
        data_settings = service_config.get("data", {})

        self.running = False
        self.shutdown_requested = False
        self.paused = False
        self.start_time: Optional[datetime] = None
        self.cycle_count = 0
        self.signal_count = 0
        self.error_count = 0
        self.last_status_update: Optional[datetime] = None
        self.status_update_interval = service_settings.get("status_update_interval", 1800)
        self.last_heartbeat: Optional[datetime] = None
        self.heartbeat_interval = service_settings.get("heartbeat_interval", 3600)
        self.state_save_interval = service_settings.get("state_save_interval", 10)
        self.consecutive_errors = 0
        self.max_consecutive_errors = circuit_breaker_settings.get("max_consecutive_errors", 10)
        self.data_fetch_errors = 0
        self.max_data_fetch_errors = circuit_breaker_settings.get("max_data_fetch_errors", 5)
        self.connection_failures = 0
        self.max_connection_failures = circuit_breaker_settings.get("max_connection_failures", 10)
        self.last_connection_failure_alert: Optional[datetime] = None
        self.connection_failure_alert_interval = alert_settings.get("connection_failure_interval", 600)
        self.last_successful_cycle: Optional[datetime] = None
        self.last_data_quality_alert: Optional[datetime] = None
        self.data_quality_alert_interval = alert_settings.get("data_quality_interval", 300)
        self.stale_data_threshold_minutes = data_settings.get("stale_data_threshold_minutes", 10)
        self.connection_timeout_minutes = data_settings.get("connection_timeout_minutes", 30)
        
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

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("NQ Agent Service starting...")

        # Send startup notification
        try:
            config_dict = {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
                "stop_loss_atr_multiplier": self.config.stop_loss_atr_multiplier,
                "take_profit_risk_reward": self.config.take_profit_risk_reward,
                "max_risk_per_trade": self.config.max_risk_per_trade,
            }
            await self.telegram_notifier.send_startup_notification(config_dict)
        except Exception as e:
            logger.warning(f"Could not send startup notification: {e}")

        try:
            await self._run_loop()
        except Exception as e:
            logger.error(f"Service error: {e}", exc_info=True)
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the service."""
        if not self.running:
            return

        logger.info("Stopping NQ Agent Service...")
        self.shutdown_requested = True

        # Save final state
        self._save_state()

        # Send shutdown notification
        try:
            uptime_delta = datetime.now(timezone.utc) - self.start_time if self.start_time else None
            summary = {
                "uptime_hours": int(uptime_delta.total_seconds() / 3600) if uptime_delta else 0,
                "uptime_minutes": int((uptime_delta.total_seconds() % 3600) / 60) if uptime_delta else 0,
                "cycle_count": self.cycle_count,
                "signal_count": self.signal_count,
                "error_count": self.error_count,
            }

            # Add performance metrics if available
            try:
                performance = self.performance_tracker.get_performance_metrics(days=7)
                summary["wins"] = performance.get("wins", 0)
                summary["losses"] = performance.get("losses", 0)
                summary["total_pnl"] = performance.get("total_pnl", 0)
            except Exception:
                pass

            await self.telegram_notifier.send_shutdown_notification(summary)
        except Exception as e:
            logger.warning(f"Could not send shutdown notification: {e}")

        self.running = False
        logger.info("NQ Agent Service stopped")

    async def _run_loop(self) -> None:
        """Main service loop."""
        logger.info(f"Starting main loop (scan_interval={self.config.scan_interval}s)")

        while not self.shutdown_requested:
            try:
                # Skip if paused
                if self.paused:
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
                                f"Too many connection failures ({self.connection_failures}), "
                                "pausing service. IB Gateway may be down."
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
                            f"Too many data fetch errors ({self.data_fetch_errors}), "
                            f"waiting {self.config.scan_interval * 2}s before retry"
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

                    logger.debug("No market data available, waiting...")
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
                            latest_bar_time = datetime.fromisoformat(latest_bar_time.replace("Z", "+00:00"))
                        age_seconds = (datetime.now(timezone.utc) - latest_bar_time.replace(tzinfo=timezone.utc)).total_seconds()
                        stale_threshold_seconds = self.stale_data_threshold_minutes * 60
                        data_fresh = age_seconds < stale_threshold_seconds
                
                market_open = self.strategy.scanner.is_market_hours()
                regime_info = "unknown"
                if hasattr(self.strategy, 'scanner') and hasattr(self.strategy.scanner, 'regime_detector'):
                    # Try to get last detected regime (would need to store it)
                    regime_info = "detected"
                
                logger.info(
                    f"Cycle {self.cycle_count}: signals={len(signals)}, "
                    f"data_fresh={data_fresh}, market_open={market_open}, "
                    f"buffer_size={self.data_fetcher.get_buffer_size()}"
                )

                # Process signals
                for signal in signals:
                    await self._process_signal(signal)

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
                logger.info("Service loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in service loop: {e}", exc_info=True)
                self.error_count += 1
                self.consecutive_errors += 1

                # Circuit breaker: if too many consecutive errors, pause service
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logger.error(
                        f"Too many consecutive errors ({self.consecutive_errors}), "
                        "pausing service. Manual intervention required."
                    )
                    await self.telegram_notifier.send_circuit_breaker_alert(
                        "Too many consecutive errors",
                        {
                            "consecutive_errors": self.consecutive_errors,
                            "error_type": "general",
                            "action_taken": "Service paused",
                        }
                    )
                    self.paused = True

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

    async def _process_signal(self, signal: Dict) -> None:
        """
        Process a trading signal.
        
        Args:
            signal: Signal dictionary
        """
        try:
            # Track signal generation (delegates to state_manager for persistence)
            signal_id = self.performance_tracker.track_signal_generated(signal)

            # Send to Telegram (await async call)
            success = await self.telegram_notifier.send_signal(signal)

            if success:
                logger.info(f"Signal sent to Telegram: {signal.get('type')} {signal.get('direction')}")
            else:
                logger.warning("Failed to send signal to Telegram")

            self.signal_count += 1

        except Exception as e:
            logger.error(f"Error processing signal: {e}", exc_info=True)
            self.error_count += 1

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
        logger.info("Service paused")

    def resume(self) -> None:
        """Resume the service."""
        self.paused = False
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

        return {
            "running": self.running,
            "paused": self.paused,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime": uptime,
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "error_count": self.error_count,
            "connection_failures": self.connection_failures,
            "connection_status": connection_status,
            "buffer_size": self.data_fetcher.get_buffer_size(),
            "performance": performance,
            "data_source_health": data_source_health,
            "last_successful_cycle": (
                self.last_successful_cycle.isoformat() if self.last_successful_cycle else None
            ),
            "config": {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
            },
        }

    def _save_state(self) -> None:
        """Save current service state."""
        state = {
            "running": self.running,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "buffer_size": self.data_fetcher.get_buffer_size(),
            "config": {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
            },
        }
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
            await self.telegram_notifier.send_heartbeat(status)
            self.last_heartbeat = now

    async def _check_data_quality(self, market_data: Dict) -> None:
        """Check data quality and send alerts if needed."""
        now = datetime.now(timezone.utc)

        # Check if we should send data quality alerts (throttle)
        if (
            self.last_data_quality_alert is not None
            and (now - self.last_data_quality_alert).total_seconds() < self.data_quality_alert_interval
        ):
            return

        # Use DataQualityChecker for validation
        validation = self.data_quality_checker.validate_market_data(market_data)

        # Check for stale data
        if not validation["freshness"]["is_fresh"]:
            age_minutes = validation["freshness"]["age_minutes"]
            await self.telegram_notifier.send_data_quality_alert(
                "stale_data",
                f"Data is {age_minutes:.1f} minutes old",
                {"age_minutes": age_minutes},
            )
            self.last_data_quality_alert = now
            return

        # Check for empty data
        df = market_data.get("df")
        if df is not None and df.empty:
            await self.telegram_notifier.send_data_quality_alert(
                "data_gap",
                "No market data available",
                {},
            )
            self.last_data_quality_alert = now
            return

        # Check buffer size
        if not validation["buffer_size"]["is_adequate"]:
            buffer_size = validation["buffer_size"]["buffer_size"]
            await self.telegram_notifier.send_data_quality_alert(
                "buffer_issue",
                f"Buffer size is low: {buffer_size} bars",
                {"buffer_size": buffer_size},
            )
            self.last_data_quality_alert = now


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
        logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown_requested = True
