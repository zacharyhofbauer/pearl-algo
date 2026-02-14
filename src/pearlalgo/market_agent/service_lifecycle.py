"""
Service Lifecycle Mixin -- start(), stop(), OS signal handling.

Extracted from service.py for better code organization.
This is the trading agent's lifecycle code -- handle with care.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp
from pearlalgo.utils.market_hours import get_market_hours
from pearlalgo.market_agent.audit_logger import AuditEventType
from pearlalgo.market_agent.notification_queue import Priority

if TYPE_CHECKING:
    pass  # MarketAgentService accessed via self


class ServiceLifecycleMixin:
    """Mixin providing start/stop lifecycle methods for MarketAgentService."""

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
        signal.signal(signal.SIGINT, self._os_signal_handler)
        signal.signal(signal.SIGTERM, self._os_signal_handler)

        logger.info("NQ Agent Service starting...")

        # Start audit logger background writer
        if self.audit_logger is not None:
            self.audit_logger.start()
            self.audit_logger.log_system_event(
                AuditEventType.SYSTEM_START,
                {"symbol": self.symbol, "timeframe": self.timeframe},
            )

        # Start notification queue for async Telegram delivery
        await self.notification_queue.start()
        logger.info("Notification queue started")

        # Startup flow:
        # 1) Rich startup notification (stable)
        # 2) Immediately follow with the /start-style visual dashboard (chart + caption + buttons)
        market_data = {}
        try:
            # Try to fetch a bar quickly so startup can include price.
            # Use a lightweight path to avoid slow startup when IBKR is flaky.
            try:
                market_data = await self.data_fetcher.fetch_startup_snapshot(timeout_seconds=2.5) or {}
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug(f"Could not fetch market data for startup: {e}")
                market_data = {}

            config_dict = {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
                "current_time": get_utc_timestamp(),
            }

            # Gates (explicit so startup never shows UNKNOWN).
            try:
                config_dict["futures_market_open"] = bool(get_market_hours().is_market_open())
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
                config_dict["futures_market_open"] = None
            try:
                from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
                config_dict["strategy_session_open"] = check_trading_session(datetime.now(timezone.utc), self.config)
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
                config_dict["strategy_session_open"] = None

            try:
                lb = (market_data or {}).get("latest_bar")
                if isinstance(lb, dict) and "close" in lb:
                    config_dict["latest_price"] = lb.get("close")
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

            await self.notification_queue.enqueue_startup(config_dict, priority=Priority.NORMAL)
            logger.info("Startup notification queued")
        except Exception as e:
            logger.debug(f"Could not send startup notification: {e}")

        # Skip automatic dashboard on startup - user can type /start for full dashboard
        # This keeps startup notifications clean and gives user control
        now = datetime.now(timezone.utc)
        self.last_status_update = now
        self.last_dashboard_chart_sent = now  # Prevent auto-chart on first cycle
        logger.info("Startup complete - user can use /start for dashboard")

        # Persist running=True so dashboard shows agent online immediately
        try:
            self._save_state(force=True)
        except Exception as e:
            logger.warning(f"Could not save startup state: {e}", exc_info=True)

        # Connect execution adapter if enabled
        if self.execution_adapter is not None:
            try:
                connected = await self.execution_adapter.connect()
                if connected:
                    logger.info(
                        f"Execution adapter connected (mode={self._execution_config.mode.value}, "
                        f"armed={self.execution_adapter.armed})"
                    )
                else:
                    logger.warning("Execution adapter failed to connect - orders will not be placed")
            except Exception as e:
                logger.error(f"Error connecting execution adapter: {e}", exc_info=True)

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

        # Log shutdown audit event and stop audit logger
        if self.audit_logger is not None:
            try:
                self.audit_logger.log_system_event(
                    AuditEventType.SYSTEM_STOP,
                    {"reason": shutdown_reason, "cycle_count": self.cycle_count},
                )
                self.audit_logger.stop(timeout=3.0)
            except Exception as e:
                logger.warning(f"Error stopping audit logger: {e}")

        # Flush async SQLite queue before shutdown
        if self._async_sqlite_queue is not None:
            try:
                self._async_sqlite_queue.stop(timeout=5.0)
            except Exception as e:
                logger.warning(f"Error stopping async SQLite queue: {e}")

        # Stop notification queue gracefully (drains pending notifications)
        try:
            await self.notification_queue.stop(timeout=10.0)
            queue_stats = self.notification_queue.get_stats()
            logger.info(f"Notification queue stopped: {queue_stats}")
        except Exception as e:
            logger.warning(f"Error stopping notification queue: {e}")

        # Save final state (unconditional -- shutdown safety net)
        try:
            self._save_state(force=True)
        except Exception as e:
            logger.warning(f"Could not save final state: {e}", exc_info=True)

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
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

            # Send with timeout to ensure it doesn't hang, but log if it fails
            logger.info(f"Sending shutdown notification: {shutdown_reason}")
            try:
                await asyncio.wait_for(
                    self.telegram_notifier.send_shutdown_notification(summary),
                    timeout=10.0  # Increased timeout to give more time
                )
                logger.info("Shutdown notification sent to Telegram")
            except asyncio.TimeoutError:
                logger.error("Timeout sending shutdown notification - Telegram may be slow or unreachable")
                # Try one more time without timeout as last resort
                try:
                    await self.telegram_notifier.send_shutdown_notification(summary)
                    logger.info("Shutdown notification sent on retry")
                except Exception as retry_e:
                    logger.error(f"Failed to send shutdown notification on retry: {retry_e}")
        except Exception as e:
            logger.error(f"Error sending shutdown notification: {e}", exc_info=True)

        # Disconnect execution adapter
        if self.execution_adapter is not None:
            try:
                # Disarm first as safety measure
                self.execution_adapter.disarm()
                await self.execution_adapter.disconnect()
                logger.info("Execution adapter disconnected")
            except Exception as e:
                logger.warning(f"Error disconnecting execution adapter: {e}")

        self.running = False
        # Persist a final state with running=False so /start doesn't show stale "ON"
        # after a stop/shutdown notification.
        try:
            self._save_state(force=True)
        except Exception as e:
            logger.warning(f"Could not save stopped state: {e}", exc_info=True)
        logger.info("NQ Agent Service stopped")
