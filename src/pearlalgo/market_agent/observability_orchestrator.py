"""
Observability Orchestrator

Coordinates performance tracking, dashboard delivery, and notifications.

Part of the Arch-2 decomposition: service.py → orchestrator classes.

**Already migrated:**
- ``track_performance()`` — signal outcome recording
- ``get_daily_performance()`` — daily metrics aggregation
- ``send_notification()`` — enqueue Telegram messages
- ``get_daily_summary()`` — dashboard-ready summary
- ``notify_error()`` — error notification via queue
- ``compute_quiet_period_minutes()`` — time since last signal

**To migrate next (marked with ``# TODO(1A-migrate)`` in service.py):**
- ``_check_dashboard()`` — periodic dashboard scheduling
- ``_generate_dashboard_chart()`` — chart capture + export
- ``_send_dashboard()`` — dashboard delivery
- ``get_status()`` — full status snapshot
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger

if TYPE_CHECKING:
    from pearlalgo.market_agent.performance_tracker import PerformanceTracker
    from pearlalgo.market_agent.notification_queue import NotificationQueue
    from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager


class ObservabilityOrchestrator:
    """
    Orchestrates observability: performance metrics, dashboards, and alerts.

    Dependencies are injected via the constructor so the class is independently
    testable and avoids circular imports with service.py.

    Current scope (delegation layer):
    - ``track_performance()``: delegates to PerformanceTracker
    - ``send_notification()``: delegates to NotificationQueue
    - ``get_daily_summary()``: aggregates metrics for dashboard / Telegram

    Future scope (method migration):
    - Dashboard chart generation & scheduling
    - ML lift metrics refresh
    - Cycle diagnostics persistence
    """

    def __init__(
        self,
        *,
        performance_tracker: "PerformanceTracker",
        notification_queue: "NotificationQueue",
        telegram_notifier: "MarketAgentTelegramNotifier",
        state_manager: "MarketAgentStateManager",
    ):
        self._performance_tracker = performance_tracker
        self._notification_queue = notification_queue
        self._telegram_notifier = telegram_notifier
        self._state_manager = state_manager

        logger.debug("ObservabilityOrchestrator initialized")

    # ------------------------------------------------------------------
    # Delegation: performance tracking
    # ------------------------------------------------------------------

    def track_performance(self, signal: Dict[str, Any]) -> None:
        """
        Record a signal outcome in the performance tracker.

        Delegates to ``PerformanceTracker.record_signal()``.
        """
        try:
            self._performance_tracker.record_signal(signal)
        except Exception as exc:
            logger.warning("Performance tracking failed (non-fatal): %s", exc)

    def get_daily_performance(self) -> Dict[str, Any]:
        """
        Return today's aggregated performance metrics.

        Delegates to ``PerformanceTracker.get_daily_performance()``.
        """
        try:
            return self._performance_tracker.get_daily_performance()
        except Exception as exc:
            logger.warning("Daily performance query failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Delegation: notifications
    # ------------------------------------------------------------------

    async def send_notification(
        self,
        message: str,
        *,
        priority: Optional[Any] = None,
    ) -> None:
        """
        Enqueue a raw Telegram notification via the notification queue.

        Args:
            message: Notification text.
            priority: Optional priority level (from NotificationQueue.Priority).
        """
        try:
            kwargs: Dict[str, Any] = {}
            if priority is not None:
                kwargs["priority"] = priority
            await self._notification_queue.enqueue_raw_message(message, **kwargs)
        except Exception as exc:
            logger.warning("Notification enqueue failed: %s", exc)

    # ------------------------------------------------------------------
    # Delegation: aggregated summary
    # ------------------------------------------------------------------

    def get_daily_summary(self) -> Dict[str, Any]:
        """
        Build a summary dict suitable for dashboards and daily reports.

        Combines performance metrics with notification queue health.
        """
        perf = self.get_daily_performance()
        queue_stats: Dict[str, Any] = {}
        try:
            queue_stats = {
                "queue_size": getattr(self._notification_queue, "queue_size", 0),
                "telegram_enabled": getattr(self._telegram_notifier, "enabled", False),
            }
        except Exception as exc:
            logger.debug("Non-critical summary field error: %s", exc)

        return {
            "performance": perf,
            "notifications": queue_stats,
        }

    # ------------------------------------------------------------------
    # Error notification (migrated from service.py)
    # ------------------------------------------------------------------

    async def notify_error(self, error_message: str, *, context: str = "") -> None:
        """Send an error notification via the notification queue.

        This is a convenience wrapper that formats a user-friendly error
        message and enqueues it at high priority.
        """
        try:
            prefix = f"[{context}] " if context else ""
            # Truncate to avoid Telegram message-length limits
            truncated = error_message[:500] if len(error_message) > 500 else error_message
            await self._notification_queue.enqueue_raw_message(
                f"⚠️ {prefix}{truncated}",
            )
        except Exception as exc:
            logger.debug("Error notification enqueue failed: %s", exc)

    # ------------------------------------------------------------------
    # Quiet-period calculation (migrated from service.py)
    # ------------------------------------------------------------------

    def compute_quiet_period_minutes(
        self,
        last_signal_at: Optional[datetime],
    ) -> Optional[float]:
        """Compute minutes since the last signal was generated.

        Returns ``None`` if *last_signal_at* is not set (no signals yet).
        """
        if last_signal_at is None:
            return None
        try:
            now = datetime.now(timezone.utc)
            delta = now - last_signal_at
            return delta.total_seconds() / 60.0
        except Exception:
            return None
