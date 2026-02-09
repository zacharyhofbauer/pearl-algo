"""
Tests for storage/async_sqlite_queue.py

Validates the async SQLite write queue including:
- Priority handling
- Queue operations (enqueue, worker)
- Backpressure
- Metrics
- Graceful shutdown
"""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from pearlalgo.storage.async_sqlite_queue import (
    AsyncSQLiteQueue,
    AsyncSQLiteQueueMetrics,
    QueuedWrite,
    WritePriority,
)


class TestWritePriority:
    """Tests for WritePriority enum."""

    def test_priority_ordering(self) -> None:
        """HIGH priority should sort before MEDIUM, MEDIUM before LOW."""
        high = WritePriority.HIGH
        medium = WritePriority.MEDIUM
        low = WritePriority.LOW

        assert high.value < medium.value < low.value

    def test_queued_write_comparison(self) -> None:
        """QueuedWrite should sort by priority."""
        high_write = QueuedWrite(
            priority=WritePriority.HIGH,
            operation="add_trade",
            kwargs={},
        )
        low_write = QueuedWrite(
            priority=WritePriority.LOW,
            operation="add_cycle_diagnostics",
            kwargs={},
        )

        # HIGH priority writes should sort before LOW
        assert high_write < low_write
        assert not (low_write < high_write)


class TestAsyncSQLiteQueueMetrics:
    """Tests for AsyncSQLiteQueueMetrics."""

    def test_to_dict(self) -> None:
        """Metrics should serialize to dictionary."""
        metrics = AsyncSQLiteQueueMetrics(
            queue_depth=5,
            total_writes=100,
            total_drops=2,
            total_errors=1,
            writes_per_second=3.5,
            avg_latency_ms=5.5,
            worker_running=True,
        )

        result = metrics.to_dict()

        assert result["queue_depth"] == 5
        assert result["total_writes"] == 100
        assert result["total_drops"] == 2
        assert result["total_errors"] == 1
        assert result["writes_per_second"] == 3.5
        assert result["avg_latency_ms"] == 5.5
        assert result["worker_running"] is True

    def test_defaults(self) -> None:
        """Metrics should have sensible defaults."""
        metrics = AsyncSQLiteQueueMetrics()

        assert metrics.queue_depth == 0
        assert metrics.total_writes == 0
        assert metrics.worker_running is False


class TestAsyncSQLiteQueue:
    """Tests for AsyncSQLiteQueue."""

    def test_init(self) -> None:
        """Should initialize with correct parameters."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(
            trade_db=mock_db,
            max_queue_size=500,
            priority_trades=True,
        )

        assert queue_obj._trade_db == mock_db
        assert queue_obj._max_queue_size == 500
        assert queue_obj._priority_trades is True
        assert not queue_obj._running

    def test_start_and_stop(self) -> None:
        """Should start and stop worker thread."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=10)

        # Start
        queue_obj.start()
        assert queue_obj._running is True
        assert queue_obj._worker_thread is not None
        assert queue_obj._worker_thread.is_alive()

        # Stop
        queue_obj.stop(timeout=2.0)
        assert queue_obj._running is False

    def test_enqueue_when_not_running(self) -> None:
        """Should return False when enqueueing to stopped queue."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db)

        result = queue_obj.enqueue("add_trade", signal_id="test")

        assert result is False
        assert queue_obj._total_drops == 1

    def test_enqueue_medium_priority(self) -> None:
        """Should enqueue MEDIUM priority writes."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=10)
        queue_obj.start()

        try:
            result = queue_obj.enqueue(
                "add_signal_event",
                priority=WritePriority.MEDIUM,
                signal_id="test",
            )

            assert result is True
        finally:
            queue_obj.stop(timeout=1.0)

    def test_enqueue_high_priority(self) -> None:
        """Should enqueue HIGH priority writes and track count."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=10)
        queue_obj.start()

        try:
            result = queue_obj.enqueue(
                "add_trade",
                priority=WritePriority.HIGH,
                signal_id="test",
            )

            assert result is True
            assert queue_obj._total_high_priority_writes == 1
        finally:
            queue_obj.stop(timeout=1.0)

    def test_worker_processes_writes(self) -> None:
        """Worker should process queued writes."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=10)
        queue_obj.start()

        try:
            # Enqueue a write
            queue_obj.enqueue(
                "add_trade",
                priority=WritePriority.HIGH,
                signal_id="test123",
                outcome="win",
            )

            # Give worker time to process
            time.sleep(0.5)

            # Verify write was executed
            mock_db.add_trade.assert_called_once()
            call_kwargs = mock_db.add_trade.call_args.kwargs
            assert call_kwargs["signal_id"] == "test123"
            assert call_kwargs["outcome"] == "win"
        finally:
            queue_obj.stop(timeout=1.0)

    def test_get_metrics(self) -> None:
        """Should return current metrics."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=10)
        queue_obj.start()

        try:
            metrics = queue_obj.get_metrics()

            assert isinstance(metrics, AsyncSQLiteQueueMetrics)
            assert metrics.worker_running is True
        finally:
            queue_obj.stop(timeout=1.0)

    def test_backpressure_threshold(self) -> None:
        """Should detect backpressure when queue is 80% full."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=10)

        # Backpressure threshold is 80% = 8 items
        assert queue_obj._backpressure_threshold == 8

    def test_is_backpressure_active(self) -> None:
        """Should report backpressure when queue exceeds threshold."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=10)
        queue_obj._running = True  # Simulate running without starting worker

        # Queue is empty
        assert queue_obj.is_backpressure_active() is False

        # Fill queue to threshold
        for i in range(8):
            queue_obj._queue.put_nowait(
                QueuedWrite(
                    priority=WritePriority.LOW,
                    operation="test",
                    kwargs={"i": i},
                )
            )

        # Should now be active
        assert queue_obj.is_backpressure_active() is True


class TestAsyncSQLiteQueueOperations:
    """Tests for specific queue operations."""

    def test_execute_write_add_trade(self) -> None:
        """Should call add_trade on TradeDatabase."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db)

        write = QueuedWrite(
            priority=WritePriority.HIGH,
            operation="add_trade",
            kwargs={"signal_id": "test", "outcome": "win"},
        )

        queue_obj._execute_write(write)

        mock_db.add_trade.assert_called_once_with(signal_id="test", outcome="win")

    def test_execute_write_add_signal_event(self) -> None:
        """Should call add_signal_event on TradeDatabase."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db)

        write = QueuedWrite(
            priority=WritePriority.MEDIUM,
            operation="add_signal_event",
            kwargs={"event_type": "generated"},
        )

        queue_obj._execute_write(write)

        mock_db.add_signal_event.assert_called_once_with(event_type="generated")

    def test_execute_write_add_cycle_diagnostics(self) -> None:
        """Should call add_cycle_diagnostics on TradeDatabase."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db)

        write = QueuedWrite(
            priority=WritePriority.LOW,
            operation="add_cycle_diagnostics",
            kwargs={"cycle_id": 1},
        )

        queue_obj._execute_write(write)

        mock_db.add_cycle_diagnostics.assert_called_once_with(cycle_id=1)

    def test_execute_write_unknown_operation(self) -> None:
        """Should log warning for unknown operations."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db)

        write = QueuedWrite(
            priority=WritePriority.LOW,
            operation="unknown_operation",
            kwargs={},
        )

        # Should not raise
        queue_obj._execute_write(write)


class TestQueueFullScenarios:
    """Tests for queue-full behavior with different priority levels.

    Validates that:
    - LOW priority writes are dropped immediately when the queue is full
    - HIGH priority writes block and succeed once the worker drains space
    - Priority ordering is respected (HIGH before MEDIUM before LOW)
    - MEDIUM priority writes are dropped after the 0.1s timeout
    """

    def test_low_priority_dropped_when_queue_full(self) -> None:
        """LOW priority write is dropped immediately when queue is full."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=5)
        queue_obj._running = True  # Simulate running without starting worker

        # Fill queue completely
        for i in range(5):
            queue_obj._queue.put_nowait(
                QueuedWrite(priority=WritePriority.LOW, operation="filler", kwargs={"i": i})
            )

        assert queue_obj._queue.full()
        drops_before = queue_obj._total_drops

        result = queue_obj.enqueue(
            "add_cycle_diagnostics", priority=WritePriority.LOW, cycle_id=99,
        )

        assert result is False
        assert queue_obj._total_drops == drops_before + 1

    def test_high_priority_blocks_when_queue_full(self) -> None:
        """HIGH priority write succeeds after worker drains space from full queue."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=5)
        queue_obj._running = True  # Simulate running without starting worker

        # Fill queue completely
        for i in range(5):
            queue_obj._queue.put_nowait(
                QueuedWrite(
                    priority=WritePriority.LOW,
                    operation="add_cycle_diagnostics",
                    kwargs={"i": i},
                )
            )
        assert queue_obj._queue.full()

        # Simulate a worker draining one item after a short delay
        def drain_one():
            time.sleep(0.2)
            try:
                queue_obj._queue.get_nowait()
            except queue.Empty:
                pass

        drain_thread = threading.Thread(target=drain_one)
        drain_thread.start()

        # HIGH priority enqueue will block until drain_thread frees space
        result = queue_obj.enqueue(
            "add_trade", priority=WritePriority.HIGH, signal_id="urgent",
        )
        drain_thread.join(timeout=2.0)

        assert result is True
        assert queue_obj._total_high_priority_writes == 1

    def test_priority_ordering_under_contention(self) -> None:
        """HIGH priority writes are processed before MEDIUM and LOW by the worker."""
        mock_db = MagicMock()
        processed_order: list[str] = []

        mock_db.add_trade.side_effect = lambda **kw: processed_order.append(kw.get("tag", ""))
        mock_db.add_signal_event.side_effect = lambda **kw: processed_order.append(kw.get("tag", ""))
        mock_db.add_cycle_diagnostics.side_effect = lambda **kw: processed_order.append(kw.get("tag", ""))

        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=10)

        # Enqueue in deliberately wrong order: LOW, MEDIUM, HIGH
        queue_obj._queue.put_nowait(
            QueuedWrite(priority=WritePriority.LOW, operation="add_cycle_diagnostics", kwargs={"tag": "low"})
        )
        queue_obj._queue.put_nowait(
            QueuedWrite(priority=WritePriority.MEDIUM, operation="add_signal_event", kwargs={"tag": "medium"})
        )
        queue_obj._queue.put_nowait(
            QueuedWrite(priority=WritePriority.HIGH, operation="add_trade", kwargs={"tag": "high"})
        )

        # Drain in priority order (simulating worker behavior)
        while not queue_obj._queue.empty():
            write = queue_obj._queue.get_nowait()
            queue_obj._execute_write(write)

        assert processed_order[0] == "high", f"Expected HIGH first, got: {processed_order}"

    def test_medium_priority_dropped_after_timeout_when_queue_full(self) -> None:
        """MEDIUM priority write is dropped after the 0.1s timeout when queue is full."""
        mock_db = MagicMock()
        queue_obj = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=5)
        queue_obj._running = True  # Simulate running without starting worker

        # Fill queue completely
        for i in range(5):
            queue_obj._queue.put_nowait(
                QueuedWrite(priority=WritePriority.LOW, operation="filler", kwargs={"i": i})
            )
        assert queue_obj._queue.full()
        drops_before = queue_obj._total_drops

        start = time.monotonic()
        result = queue_obj.enqueue(
            "add_signal_event", priority=WritePriority.MEDIUM, signal_id="med_1",
        )
        elapsed = time.monotonic() - start

        assert result is False
        assert queue_obj._total_drops == drops_before + 1
        # Should have waited approximately 0.1s before dropping
        assert elapsed >= 0.08, f"Expected ~0.1s wait, got {elapsed:.3f}s"
