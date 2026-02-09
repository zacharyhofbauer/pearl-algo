"""
Observability Orchestrator

Coordinates performance tracking, dashboard delivery, and notifications.
Thin delegation layer that routes calls to PerformanceTracker,
NotificationQueue, and TelegramNotifier.

Part of the Arch-2 decomposition: service.py → orchestrator classes.
This file provides the framework; actual method migration happens incrementally.
"""

from __future__ import annotations

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
