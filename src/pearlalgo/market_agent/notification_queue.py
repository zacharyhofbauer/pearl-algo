"""
Async Notification Queue for Telegram Integration.

This module provides a decoupled notification system that prevents Telegram
failures from blocking the main trading service loop.

Key Features:
- Async queue-based notification delivery
- Automatic retry with exponential backoff
- Graceful degradation when Telegram is unavailable
- Priority levels for critical vs informational messages
- Notification batching for high-frequency updates

Usage:
    from pearlalgo.market_agent.notification_queue import NotificationQueue

    # Create queue with notifier
    queue = NotificationQueue(telegram_notifier)

    # Start background processing
    await queue.start()

    # Queue notifications (non-blocking)
    await queue.enqueue_signal(signal, priority=Priority.HIGH)
    await queue.enqueue_status(status, priority=Priority.LOW)

    # Graceful shutdown
    await queue.stop()
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Callable, Coroutine, Dict, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger

if TYPE_CHECKING:
    from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier


class Priority(IntEnum):
    """Notification priority levels."""
    CRITICAL = 0  # Circuit breaker, risk warnings
    HIGH = 1      # Signals, entries, exits
    NORMAL = 2    # Status updates, heartbeats
    LOW = 3       # Dashboard charts, metrics


@dataclass(order=True)
class Notification:
    """A queued notification with metadata."""
    priority: int
    timestamp: float = field(compare=False)
    notification_type: str = field(compare=False)
    payload: Dict[str, Any] = field(compare=False)
    callback: Optional[Callable[..., Coroutine]] = field(compare=False, default=None)
    retry_count: int = field(compare=False, default=0)
    max_retries: int = field(compare=False, default=3)


class NotificationQueue:
    """
    Async notification queue for Telegram integration.

    This class decouples Telegram notifications from the main service loop,
    ensuring that Telegram failures don't block signal generation or trading.
    """

    def __init__(
        self,
        telegram_notifier: "MarketAgentTelegramNotifier",
        max_queue_size: int = 1000,
        batch_delay_seconds: float = 0.5,
        max_retries: int = 3,
        retry_backoff_base: float = 2.0,
    ):
        """
        Initialize the notification queue.

        Args:
            telegram_notifier: The Telegram notifier instance
            max_queue_size: Maximum queue size (oldest dropped when full)
            batch_delay_seconds: Delay between processing batches
            max_retries: Maximum retry attempts per notification
            retry_backoff_base: Base for exponential backoff (seconds)
        """
        self.notifier = telegram_notifier
        self.max_queue_size = max_queue_size
        self.batch_delay = batch_delay_seconds
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base

        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = {
            "enqueued": 0,
            "delivered": 0,
            "failed": 0,
            "dropped": 0,
            "retried": 0,
        }

    async def start(self) -> None:
        """Start the background notification processor."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("Notification queue started")

    async def stop(self, timeout: float = 10.0) -> None:
        """
        Stop the notification processor gracefully.

        Args:
            timeout: Maximum time to wait for pending notifications
        """
        if not self._running:
            return

        self._running = False

        # Wait for queue to drain (with timeout)
        try:
            await asyncio.wait_for(self._drain_queue(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Notification queue drain timed out, {self._queue.qsize()} items remaining")

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info(f"Notification queue stopped: {self._stats}")

    async def _drain_queue(self) -> None:
        """Drain remaining items from the queue."""
        while not self._queue.empty():
            await asyncio.sleep(0.1)

    async def _process_loop(self) -> None:
        """Main processing loop for notifications."""
        while self._running:
            try:
                # Get next notification (with timeout to check running state)
                try:
                    notification = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Process the notification
                success = await self._deliver(notification)

                if not success and notification.retry_count < notification.max_retries:
                    # Schedule retry with backoff
                    notification.retry_count += 1
                    backoff = self.retry_backoff_base ** notification.retry_count
                    await asyncio.sleep(backoff)

                    # Re-queue for retry
                    try:
                        self._queue.put_nowait(notification)
                        self._stats["retried"] += 1
                    except asyncio.QueueFull:
                        self._stats["dropped"] += 1
                        logger.warning(f"Notification dropped after retry (queue full): {notification.notification_type}")
                elif not success:
                    self._stats["failed"] += 1
                    logger.warning(f"Notification failed after {notification.max_retries} retries: {notification.notification_type}")
                else:
                    self._stats["delivered"] += 1

                self._queue.task_done()

                # Small delay between notifications
                await asyncio.sleep(self.batch_delay)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in notification processor: {e}")
                await asyncio.sleep(1.0)

    async def _deliver(self, notification: Notification) -> bool:
        """
        Deliver a notification via Telegram.

        Args:
            notification: The notification to deliver

        Returns:
            True if delivered successfully, False otherwise
        """
        try:
            if notification.callback:
                await notification.callback(**notification.payload)
                return True

            # Handle built-in notification types
            ntype = notification.notification_type
            payload = notification.payload

            if ntype == "signal":
                return await self.notifier.send_signal(
                    payload.get("signal"),
                    buffer_data=payload.get("buffer_data"),
                )
            elif ntype == "message":
                await self.notifier.send_message(payload.get("message", ""))
                return True
            elif ntype == "status":
                await self.notifier.send_enhanced_status(payload.get("status", {}))
                return True
            elif ntype == "dashboard":
                await self.notifier.send_dashboard(
                    payload.get("status", {}),
                    chart_path=payload.get("chart_path"),
                )
                return True
            elif ntype == "circuit_breaker":
                await self.notifier.send_circuit_breaker_alert(
                    payload.get("reason", ""),
                    payload.get("details"),
                )
                return True
            elif ntype == "data_quality":
                await self.notifier.send_data_quality_alert(
                    payload.get("alert_type", "unknown"),
                    payload.get("message", ""),
                    payload.get("details"),
                )
                return True
            elif ntype == "entry":
                await self.notifier.send_entry_notification(
                    signal_id=payload.get("signal_id", ""),
                    entry_price=payload.get("entry_price", 0.0),
                    signal=payload.get("signal", {}),
                    buffer_data=payload.get("buffer_data"),
                )
                return True
            elif ntype == "exit":
                await self.notifier.send_exit_notification(
                    signal_id=payload.get("signal_id", ""),
                    exit_price=payload.get("exit_price", 0.0),
                    exit_reason=payload.get("exit_reason", ""),
                    pnl=payload.get("pnl", 0.0),
                    signal=payload.get("signal", {}),
                    hold_duration_minutes=payload.get("hold_duration_minutes"),
                    buffer_data=payload.get("buffer_data"),
                )
                return True
            elif ntype == "heartbeat":
                await self.notifier.send_heartbeat(payload.get("status", {}))
                return True
            elif ntype == "startup":
                await self.notifier.send_startup_notification(payload.get("config", {}))
                return True
            elif ntype == "shutdown":
                await self.notifier.send_shutdown_notification(payload.get("summary", {}))
                return True
            elif ntype == "recovery":
                await self.notifier.send_recovery_notification(payload.get("recovery_info", {}))
                return True
            elif ntype == "raw_message":
                # Direct access to underlying TelegramAlerts for raw message sends
                if self.notifier.telegram:
                    await self.notifier.telegram.send_message(
                        payload.get("message", ""),
                        parse_mode=payload.get("parse_mode"),
                        dedupe=payload.get("dedupe", True),
                    )
                    return True
                return False
            elif ntype == "risk_warning":
                # Direct access to underlying TelegramAlerts for risk warnings
                if self.notifier.telegram:
                    await self.notifier.telegram.notify_risk_warning(
                        payload.get("message", ""),
                        risk_status=payload.get("risk_status"),
                    )
                    return True
                return False
            else:
                logger.warning(f"Unknown notification type: {ntype}")
                return False

        except Exception as e:
            logger.debug(f"Notification delivery failed ({notification.notification_type}): {e}")
            return False

    async def enqueue(
        self,
        notification_type: str,
        payload: Dict[str, Any],
        priority: Priority = Priority.NORMAL,
        callback: Optional[Callable[..., Coroutine]] = None,
    ) -> bool:
        """
        Enqueue a notification for delivery.

        Args:
            notification_type: Type of notification
            payload: Notification data
            priority: Delivery priority
            callback: Optional custom callback coroutine

        Returns:
            True if enqueued, False if queue is full
        """
        notification = Notification(
            priority=priority.value,
            timestamp=datetime.now(timezone.utc).timestamp(),
            notification_type=notification_type,
            payload=payload,
            callback=callback,
            max_retries=self.max_retries,
        )

        try:
            self._queue.put_nowait(notification)
            self._stats["enqueued"] += 1
            return True
        except asyncio.QueueFull:
            self._stats["dropped"] += 1
            logger.warning(f"Notification dropped (queue full): {notification_type}")
            return False

    async def enqueue_signal(
        self,
        signal: Any,
        buffer_data: Optional[Any] = None,
        priority: Priority = Priority.HIGH,
    ) -> bool:
        """Convenience method to enqueue a signal notification."""
        return await self.enqueue(
            "signal",
            {"signal": signal, "buffer_data": buffer_data},
            priority=priority,
        )

    async def enqueue_message(
        self,
        message: str,
        priority: Priority = Priority.NORMAL,
    ) -> bool:
        """Convenience method to enqueue a text message."""
        return await self.enqueue(
            "message",
            {"message": message},
            priority=priority,
        )

    async def enqueue_status(
        self,
        status: Dict[str, Any],
        priority: Priority = Priority.LOW,
    ) -> bool:
        """Convenience method to enqueue a status update."""
        return await self.enqueue(
            "status",
            {"status": status},
            priority=priority,
        )

    async def enqueue_circuit_breaker(
        self,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
        priority: Priority = Priority.CRITICAL,
    ) -> bool:
        """Convenience method to enqueue a circuit breaker alert."""
        return await self.enqueue(
            "circuit_breaker",
            {"reason": reason, "details": details},
            priority=priority,
        )

    async def enqueue_dashboard(
        self,
        status: Dict[str, Any],
        chart_path: Optional[Any] = None,
        priority: Priority = Priority.LOW,
    ) -> bool:
        """Convenience method to enqueue a dashboard notification."""
        return await self.enqueue(
            "dashboard",
            {"status": status, "chart_path": chart_path},
            priority=priority,
        )

    async def enqueue_data_quality_alert(
        self,
        alert_type: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        priority: Priority = Priority.NORMAL,
    ) -> bool:
        """Convenience method to enqueue a data quality alert."""
        return await self.enqueue(
            "data_quality",
            {"alert_type": alert_type, "message": message, "details": details or {}},
            priority=priority,
        )

    async def enqueue_entry(
        self,
        signal_id: str,
        entry_price: float,
        signal: Dict[str, Any],
        buffer_data: Optional[Any] = None,
        priority: Priority = Priority.HIGH,
    ) -> bool:
        """Convenience method to enqueue an entry notification."""
        return await self.enqueue(
            "entry",
            {
                "signal_id": signal_id,
                "entry_price": entry_price,
                "signal": signal,
                "buffer_data": buffer_data,
            },
            priority=priority,
        )

    async def enqueue_exit(
        self,
        signal_id: str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        signal: Dict[str, Any],
        hold_duration_minutes: Optional[float] = None,
        buffer_data: Optional[Any] = None,
        priority: Priority = Priority.HIGH,
    ) -> bool:
        """Convenience method to enqueue an exit notification."""
        return await self.enqueue(
            "exit",
            {
                "signal_id": signal_id,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "pnl": pnl,
                "signal": signal,
                "hold_duration_minutes": hold_duration_minutes,
                "buffer_data": buffer_data,
            },
            priority=priority,
        )

    async def enqueue_heartbeat(
        self,
        status: Dict[str, Any],
        priority: Priority = Priority.LOW,
    ) -> bool:
        """Convenience method to enqueue a heartbeat."""
        return await self.enqueue(
            "heartbeat",
            {"status": status},
            priority=priority,
        )

    async def enqueue_startup(
        self,
        config: Dict[str, Any],
        priority: Priority = Priority.NORMAL,
    ) -> bool:
        """Convenience method to enqueue a startup notification."""
        return await self.enqueue(
            "startup",
            {"config": config},
            priority=priority,
        )

    async def enqueue_shutdown(
        self,
        summary: Dict[str, Any],
        priority: Priority = Priority.CRITICAL,
    ) -> bool:
        """Convenience method to enqueue a shutdown notification."""
        return await self.enqueue(
            "shutdown",
            {"summary": summary},
            priority=priority,
        )

    async def enqueue_recovery(
        self,
        recovery_info: Dict[str, Any],
        priority: Priority = Priority.NORMAL,
    ) -> bool:
        """Convenience method to enqueue a recovery notification."""
        return await self.enqueue(
            "recovery",
            {"recovery_info": recovery_info},
            priority=priority,
        )

    async def enqueue_raw_message(
        self,
        message: str,
        parse_mode: Optional[str] = None,
        dedupe: bool = True,
        priority: Priority = Priority.NORMAL,
    ) -> bool:
        """Convenience method to enqueue a raw Telegram message."""
        return await self.enqueue(
            "raw_message",
            {"message": message, "parse_mode": parse_mode, "dedupe": dedupe},
            priority=priority,
        )

    async def enqueue_risk_warning(
        self,
        message: str,
        risk_status: Optional[str] = None,
        priority: Priority = Priority.CRITICAL,
    ) -> bool:
        """Convenience method to enqueue a risk warning."""
        return await self.enqueue(
            "risk_warning",
            {"message": message, "risk_status": risk_status},
            priority=priority,
        )

    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        return {
            **self._stats,
            "pending": self._queue.qsize(),
        }

    @property
    def is_running(self) -> bool:
        """Check if the queue processor is running."""
        return self._running

    @property
    def queue_size(self) -> int:
        """Get current queue size."""
        return self._queue.qsize()
