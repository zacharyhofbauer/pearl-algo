"""
Tests for NotificationQueue - Async notification delivery system.

Tests cover:
- Priority levels and ordering
- Queue operations (enqueue, start, stop)
- Retry behavior with exponential backoff
- Notification delivery via callbacks
- Statistics tracking
- Queue overflow handling
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pearlalgo.market_agent.notification_queue import (
    NotificationQueue,
    Notification,
    Priority,
)


class TestPriority:
    """Tests for Priority enum."""

    def test_priority_values(self):
        """Should have correct priority values (lower = higher priority)."""
        assert Priority.CRITICAL < Priority.HIGH
        assert Priority.HIGH < Priority.NORMAL
        assert Priority.NORMAL < Priority.LOW

    def test_priority_ordering(self):
        """Priority values should be orderable."""
        priorities = [Priority.LOW, Priority.CRITICAL, Priority.NORMAL, Priority.HIGH]
        sorted_priorities = sorted(priorities)
        
        assert sorted_priorities == [
            Priority.CRITICAL,
            Priority.HIGH,
            Priority.NORMAL,
            Priority.LOW,
        ]


class TestNotification:
    """Tests for Notification dataclass."""

    def test_creation_with_required_fields(self):
        """Should create notification with required fields."""
        notification = Notification(
            priority=Priority.NORMAL.value,
            timestamp=1234567890.0,
            notification_type="message",
            payload={"message": "test"},
        )
        
        assert notification.priority == Priority.NORMAL.value
        assert notification.notification_type == "message"
        assert notification.payload == {"message": "test"}
        assert notification.retry_count == 0
        assert notification.max_retries == 3

    def test_notifications_are_ordered_by_priority(self):
        """Should order notifications by priority."""
        high = Notification(
            priority=Priority.HIGH.value,
            timestamp=1234567890.0,
            notification_type="entry",
            payload={},
        )
        low = Notification(
            priority=Priority.LOW.value,
            timestamp=1234567890.0,
            notification_type="status",
            payload={},
        )
        
        # High priority should be "less than" low priority for queue ordering
        assert high < low


class TestNotificationQueue:
    """Tests for NotificationQueue class."""

    @pytest.fixture
    def mock_notifier(self):
        """Create a mock Telegram notifier."""
        notifier = MagicMock()
        notifier.send_message = AsyncMock()
        notifier.send_enhanced_status = AsyncMock()
        notifier.send_dashboard = AsyncMock()
        notifier.send_circuit_breaker_alert = AsyncMock()
        notifier.send_data_quality_alert = AsyncMock()
        notifier.send_entry_notification = AsyncMock()
        notifier.send_exit_notification = AsyncMock()
        notifier.send_heartbeat = AsyncMock()
        notifier.send_startup_notification = AsyncMock()
        notifier.send_shutdown_notification = AsyncMock()
        notifier.send_recovery_notification = AsyncMock()
        notifier.telegram = MagicMock()
        notifier.telegram.send_message = AsyncMock()
        notifier.telegram.notify_risk_warning = AsyncMock()
        return notifier

    def test_initialization(self, mock_notifier):
        """Should initialize with default values."""
        queue = NotificationQueue(mock_notifier)
        
        assert queue.notifier == mock_notifier
        assert queue.max_queue_size == 1000
        assert queue.max_retries == 3
        assert queue._running is False
        assert queue.queue_size == 0

    def test_initialization_with_custom_values(self, mock_notifier):
        """Should initialize with custom values."""
        queue = NotificationQueue(
            mock_notifier,
            max_queue_size=500,
            batch_delay_seconds=1.0,
            max_retries=5,
            retry_backoff_base=3.0,
        )
        
        assert queue.max_queue_size == 500
        assert queue.batch_delay == 1.0
        assert queue.max_retries == 5
        assert queue.retry_backoff_base == 3.0


class TestNotificationQueueAsync:
    """Async tests for NotificationQueue."""

    @pytest.fixture
    def mock_notifier(self):
        """Create a mock Telegram notifier."""
        notifier = MagicMock()
        notifier.send_message = AsyncMock()
        notifier.send_enhanced_status = AsyncMock()
        notifier.send_dashboard = AsyncMock()
        notifier.send_circuit_breaker_alert = AsyncMock()
        notifier.send_data_quality_alert = AsyncMock()
        notifier.send_entry_notification = AsyncMock()
        notifier.send_exit_notification = AsyncMock()
        notifier.send_heartbeat = AsyncMock()
        notifier.send_startup_notification = AsyncMock()
        notifier.send_shutdown_notification = AsyncMock()
        notifier.send_recovery_notification = AsyncMock()
        notifier.telegram = MagicMock()
        notifier.telegram.send_message = AsyncMock()
        notifier.telegram.notify_risk_warning = AsyncMock()
        return notifier

    @pytest.mark.asyncio
    async def test_start_and_stop(self, mock_notifier):
        """Should start and stop the queue processor."""
        queue = NotificationQueue(mock_notifier)
        
        await queue.start()
        assert queue.is_running is True
        
        await queue.stop(timeout=1.0)
        assert queue.is_running is False

    @pytest.mark.asyncio
    async def test_enqueue_message(self, mock_notifier):
        """Should enqueue a message notification."""
        queue = NotificationQueue(mock_notifier)
        
        result = await queue.enqueue_message("Test message")
        
        assert result is True
        assert queue.queue_size == 1
        stats = queue.get_stats()
        assert stats["enqueued"] == 1

    @pytest.mark.asyncio
    async def test_enqueue_with_priority(self, mock_notifier):
        """Should enqueue with specified priority."""
        queue = NotificationQueue(mock_notifier)
        
        await queue.enqueue_message("Low priority", priority=Priority.LOW)
        await queue.enqueue_message("Critical", priority=Priority.CRITICAL)
        
        assert queue.queue_size == 2

    @pytest.mark.asyncio
    async def test_enqueue_returns_false_when_full(self, mock_notifier):
        """Should return False when queue is full."""
        queue = NotificationQueue(mock_notifier, max_queue_size=2)
        
        await queue.enqueue_message("First")
        await queue.enqueue_message("Second")
        result = await queue.enqueue_message("Third")  # Queue full
        
        assert result is False
        assert queue.queue_size == 2
        stats = queue.get_stats()
        assert stats["dropped"] == 1

    @pytest.mark.asyncio
    async def test_delivery_message(self, mock_notifier):
        """Should deliver message via notifier."""
        queue = NotificationQueue(mock_notifier, batch_delay_seconds=0.01)
        
        await queue.start()
        await queue.enqueue_message("Test message")
        
        # Wait for processing
        await asyncio.sleep(0.1)
        await queue.stop(timeout=1.0)
        
        mock_notifier.send_message.assert_called_once_with("Test message")
        stats = queue.get_stats()
        assert stats["delivered"] == 1

    @pytest.mark.asyncio
    async def test_delivery_status(self, mock_notifier):
        """Should deliver status update via notifier."""
        queue = NotificationQueue(mock_notifier, batch_delay_seconds=0.01)
        
        await queue.start()
        status = {"running": True, "pnl": 100.0}
        await queue.enqueue_status(status)
        
        await asyncio.sleep(0.1)
        await queue.stop(timeout=1.0)
        
        mock_notifier.send_enhanced_status.assert_called_once_with(status)

    @pytest.mark.asyncio
    async def test_delivery_circuit_breaker(self, mock_notifier):
        """Should deliver circuit breaker alert via notifier."""
        queue = NotificationQueue(mock_notifier, batch_delay_seconds=0.01)
        
        await queue.start()
        await queue.enqueue_circuit_breaker("max_errors", {"count": 10})
        
        await asyncio.sleep(0.1)
        await queue.stop(timeout=1.0)
        
        mock_notifier.send_circuit_breaker_alert.assert_called_once_with(
            "max_errors",
            {"count": 10},
        )

    @pytest.mark.asyncio
    async def test_delivery_entry_notification(self, mock_notifier):
        """Should deliver entry notification via notifier."""
        queue = NotificationQueue(mock_notifier, batch_delay_seconds=0.01)
        
        await queue.start()
        signal = {"type": "ema_cross", "direction": "long"}
        await queue.enqueue_entry(
            signal_id="sig_123",
            entry_price=17500.0,
            signal=signal,
        )
        
        await asyncio.sleep(0.1)
        await queue.stop(timeout=1.0)
        
        mock_notifier.send_entry_notification.assert_called_once_with(
            signal_id="sig_123",
            entry_price=17500.0,
            signal=signal,
            buffer_data=None,
        )

    @pytest.mark.asyncio
    async def test_delivery_exit_notification(self, mock_notifier):
        """Should deliver exit notification via notifier."""
        queue = NotificationQueue(mock_notifier, batch_delay_seconds=0.01)
        
        await queue.start()
        signal = {"type": "ema_cross", "direction": "long"}
        await queue.enqueue_exit(
            signal_id="sig_123",
            exit_price=17550.0,
            exit_reason="take_profit",
            pnl=50.0,
            signal=signal,
            hold_duration_minutes=15.0,
        )
        
        await asyncio.sleep(0.1)
        await queue.stop(timeout=1.0)
        
        mock_notifier.send_exit_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_delivery_with_custom_callback(self, mock_notifier):
        """Should call custom callback for delivery."""
        queue = NotificationQueue(mock_notifier, batch_delay_seconds=0.01)
        
        callback = AsyncMock()
        
        await queue.start()
        await queue.enqueue(
            notification_type="custom",
            payload={"custom_data": "test"},
            callback=callback,
        )
        
        await asyncio.sleep(0.1)
        await queue.stop(timeout=1.0)
        
        callback.assert_called_once_with(custom_data="test")

    @pytest.mark.asyncio
    async def test_priority_ordering_in_delivery(self, mock_notifier):
        """Should process higher priority notifications first."""
        queue = NotificationQueue(mock_notifier, batch_delay_seconds=0.01)
        
        delivery_order = []
        
        async def track_delivery(message):
            delivery_order.append(message)
        
        mock_notifier.send_message = track_delivery
        
        # Enqueue in reverse priority order
        await queue.enqueue_message("low", priority=Priority.LOW)
        await queue.enqueue_message("normal", priority=Priority.NORMAL)
        await queue.enqueue_message("critical", priority=Priority.CRITICAL)
        
        await queue.start()
        await asyncio.sleep(0.2)
        await queue.stop(timeout=1.0)
        
        # Should be delivered in priority order
        assert delivery_order == ["critical", "normal", "low"]

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, mock_notifier):
        """Should retry failed notifications."""
        queue = NotificationQueue(
            mock_notifier,
            batch_delay_seconds=0.01,
            retry_backoff_base=0.1,  # Fast backoff for testing
            max_retries=2,
        )
        
        # First call fails, second succeeds
        mock_notifier.send_message.side_effect = [Exception("Failed"), None]
        
        await queue.start()
        await queue.enqueue_message("Retry test")
        
        await asyncio.sleep(0.5)  # Wait for retry
        await queue.stop(timeout=1.0)
        
        # Should have been called twice (initial + retry)
        assert mock_notifier.send_message.call_count == 2
        stats = queue.get_stats()
        assert stats["retried"] >= 1
        assert stats["delivered"] == 1

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, mock_notifier):
        """Should mark as failed after max retries."""
        queue = NotificationQueue(
            mock_notifier,
            batch_delay_seconds=0.01,
            retry_backoff_base=0.05,
            max_retries=2,
        )
        
        # All calls fail
        mock_notifier.send_message.side_effect = Exception("Always fails")
        
        await queue.start()
        await queue.enqueue_message("Will fail")
        
        await asyncio.sleep(1.0)  # Wait for all retries
        await queue.stop(timeout=1.0)
        
        stats = queue.get_stats()
        assert stats["failed"] >= 1


class TestNotificationQueueConvenienceMethods:
    """Tests for convenience methods."""

    @pytest.fixture
    def mock_notifier(self):
        """Create a mock notifier."""
        notifier = MagicMock()
        for method in [
            "send_message", "send_enhanced_status", "send_dashboard",
            "send_circuit_breaker_alert", "send_data_quality_alert",
            "send_entry_notification", "send_exit_notification",
            "send_heartbeat", "send_startup_notification",
            "send_shutdown_notification", "send_recovery_notification",
        ]:
            setattr(notifier, method, AsyncMock())
        notifier.telegram = MagicMock()
        notifier.telegram.send_message = AsyncMock()
        notifier.telegram.notify_risk_warning = AsyncMock()
        return notifier

    @pytest.mark.asyncio
    async def test_enqueue_dashboard(self, mock_notifier):
        """Should enqueue dashboard notification."""
        queue = NotificationQueue(mock_notifier)
        
        status = {"running": True}
        result = await queue.enqueue_dashboard(status, chart_path="/tmp/chart.png")
        
        assert result is True
        assert queue.queue_size == 1

    @pytest.mark.asyncio
    async def test_enqueue_data_quality_alert(self, mock_notifier):
        """Should enqueue data quality alert."""
        queue = NotificationQueue(mock_notifier, min_tier="debug")
        
        result = await queue.enqueue_data_quality_alert(
            alert_type="stale_data",
            message="Data is stale",
            details={"age_minutes": 5},
        )
        
        assert result is True

    @pytest.mark.asyncio
    async def test_enqueue_heartbeat(self, mock_notifier):
        """Should enqueue heartbeat notification."""
        queue = NotificationQueue(mock_notifier, min_tier="debug")
        
        result = await queue.enqueue_heartbeat({"cycle": 100})
        
        assert result is True

    @pytest.mark.asyncio
    async def test_enqueue_startup(self, mock_notifier):
        """Should enqueue startup notification."""
        queue = NotificationQueue(mock_notifier)
        
        result = await queue.enqueue_startup({"market": "NQ"})
        
        assert result is True

    @pytest.mark.asyncio
    async def test_enqueue_shutdown(self, mock_notifier):
        """Should enqueue shutdown notification with CRITICAL priority."""
        queue = NotificationQueue(mock_notifier)
        
        result = await queue.enqueue_shutdown({"reason": "manual"})
        
        assert result is True
        # Shutdown should have CRITICAL priority
        notification = await queue._queue.get()
        assert notification.priority == Priority.CRITICAL.value

    @pytest.mark.asyncio
    async def test_enqueue_recovery(self, mock_notifier):
        """Should enqueue recovery notification."""
        queue = NotificationQueue(mock_notifier, min_tier="debug")
        
        result = await queue.enqueue_recovery({"recovered_from": "error"})
        
        assert result is True

    @pytest.mark.asyncio
    async def test_enqueue_raw_message(self, mock_notifier):
        """Should enqueue raw message notification."""
        queue = NotificationQueue(mock_notifier)
        
        result = await queue.enqueue_raw_message(
            message="*Bold* message",
            parse_mode="Markdown",
            dedupe=False,
        )
        
        assert result is True

    @pytest.mark.asyncio
    async def test_enqueue_risk_warning(self, mock_notifier):
        """Should enqueue risk warning with CRITICAL priority."""
        queue = NotificationQueue(mock_notifier)
        
        result = await queue.enqueue_risk_warning(
            message="High drawdown alert",
            risk_status="elevated",
        )
        
        assert result is True
        # Risk warning should have CRITICAL priority
        notification = await queue._queue.get()
        assert notification.priority == Priority.CRITICAL.value


class TestNotificationQueueStats:
    """Tests for statistics tracking."""

    @pytest.fixture
    def mock_notifier(self):
        """Create a mock notifier."""
        notifier = MagicMock()
        notifier.send_message = AsyncMock()
        return notifier

    @pytest.mark.asyncio
    async def test_get_stats_initial(self, mock_notifier):
        """Should return initial stats."""
        queue = NotificationQueue(mock_notifier)
        
        stats = queue.get_stats()
        
        assert stats["enqueued"] == 0
        assert stats["delivered"] == 0
        assert stats["failed"] == 0
        assert stats["dropped"] == 0
        assert stats["retried"] == 0
        assert stats["pending"] == 0

    @pytest.mark.asyncio
    async def test_stats_track_enqueued(self, mock_notifier):
        """Should track enqueued count."""
        queue = NotificationQueue(mock_notifier)
        
        await queue.enqueue_message("Test 1")
        await queue.enqueue_message("Test 2")
        
        stats = queue.get_stats()
        assert stats["enqueued"] == 2
        assert stats["pending"] == 2

    @pytest.mark.asyncio
    async def test_stats_track_delivered(self, mock_notifier):
        """Should track delivered count."""
        queue = NotificationQueue(mock_notifier, batch_delay_seconds=0.01)
        
        await queue.start()
        await queue.enqueue_message("Test")
        await asyncio.sleep(0.1)
        await queue.stop(timeout=1.0)
        
        stats = queue.get_stats()
        assert stats["delivered"] == 1
        assert stats["pending"] == 0

    @pytest.mark.asyncio
    async def test_is_running_property(self, mock_notifier):
        """Should report running state correctly."""
        queue = NotificationQueue(mock_notifier)
        
        assert queue.is_running is False
        
        await queue.start()
        assert queue.is_running is True
        
        await queue.stop(timeout=1.0)
        assert queue.is_running is False

    @pytest.mark.asyncio
    async def test_queue_size_property(self, mock_notifier):
        """Should report queue size correctly."""
        queue = NotificationQueue(mock_notifier)
        
        assert queue.queue_size == 0
        
        await queue.enqueue_message("Test 1")
        await queue.enqueue_message("Test 2")
        
        assert queue.queue_size == 2
