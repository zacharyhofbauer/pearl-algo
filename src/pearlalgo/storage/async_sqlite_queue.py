"""
Async SQLite Write Queue

Non-blocking SQLite writes via background thread worker.
Ensures the main scan loop never waits for I/O.

Features:
- Priority queue (trade exits always written; cycle diagnostics drop first if full)
- Graceful shutdown (flush pending writes)
- Error resilience (failed writes logged but don't crash worker)
- Observability (queue depth, writes/sec, drops)
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from pearlalgo.utils.logger import logger


class WritePriority(Enum):
    """Priority levels for queued writes."""
    HIGH = 1    # Trade exits, signal events (never drop)
    MEDIUM = 2  # Signal events (generated)
    LOW = 3     # Cycle diagnostics, regime snapshots (drop first when queue full)


@dataclass
class QueuedWrite:
    """A write operation to be executed by the background worker."""
    priority: WritePriority
    operation: str  # "add_trade", "add_signal_event", "add_cycle_diagnostics", "add_regime_snapshot"
    kwargs: Dict[str, Any]
    enqueued_at: float = field(default_factory=time.monotonic)
    
    def __lt__(self, other: "QueuedWrite") -> bool:
        """Compare by priority (lower enum value = higher priority)."""
        return self.priority.value < other.priority.value


@dataclass
class AsyncSQLiteQueueMetrics:
    """Metrics for async SQLite queue observability."""
    queue_depth: int = 0
    total_writes: int = 0
    total_drops: int = 0
    total_errors: int = 0
    total_high_priority_writes: int = 0
    total_backpressure_waits: int = 0
    writes_per_second: float = 0.0
    avg_latency_ms: float = 0.0
    worker_running: bool = False
    backpressure_active: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for state persistence."""
        return {
            "queue_depth": self.queue_depth,
            "total_writes": self.total_writes,
            "total_drops": self.total_drops,
            "total_errors": self.total_errors,
            "total_high_priority_writes": self.total_high_priority_writes,
            "total_backpressure_waits": self.total_backpressure_waits,
            "writes_per_second": round(self.writes_per_second, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "worker_running": self.worker_running,
            "backpressure_active": self.backpressure_active,
        }


class AsyncSQLiteQueue:
    """
    Async SQLite write queue with background worker thread.
    
    Ensures main loop never blocks on SQLite I/O.
    """
    
    def __init__(
        self,
        trade_db: Any,  # TradeDatabase instance
        max_queue_size: int = 1000,
        priority_trades: bool = True,
    ):
        """
        Initialize async SQLite queue.
        
        Args:
            trade_db: TradeDatabase instance to delegate writes to
            max_queue_size: Maximum queued writes (older LOW priority writes drop if full)
            priority_trades: If True, trade exits are HIGH priority (never drop)
        """
        self._trade_db = trade_db
        self._max_queue_size = max_queue_size
        self._priority_trades = priority_trades
        
        # Priority queue (lower priority value = higher priority)
        self._queue: queue.PriorityQueue[QueuedWrite] = queue.PriorityQueue(maxsize=max_queue_size)
        
        # Worker thread
        self._worker_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._running = False
        
        # Metrics
        self._total_writes = 0
        self._total_drops = 0
        self._total_errors = 0
        self._total_high_priority_writes = 0
        self._total_backpressure_waits = 0
        self._write_times: list[float] = []
        self._metrics_start_time = time.monotonic()
        
        # Backpressure configuration
        self._backpressure_threshold = int(max_queue_size * 0.8)  # 80% full
        self._high_priority_timeout = 5.0  # Max time to wait for HIGH priority writes
        
        logger.info(
            f"AsyncSQLiteQueue initialized: max_queue={max_queue_size}, priority_trades={priority_trades}, "
            f"backpressure_threshold={self._backpressure_threshold}"
        )
    
    def start(self) -> None:
        """Start the background worker thread."""
        if self._running:
            logger.warning("AsyncSQLiteQueue already running")
            return
        
        self._running = True
        self._shutdown_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="AsyncSQLiteWorker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("AsyncSQLiteQueue worker started")
    
    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the worker thread and flush pending writes.
        
        Args:
            timeout: Maximum time to wait for flush (seconds)
        """
        if not self._running:
            return
        
        logger.info(f"Stopping AsyncSQLiteQueue (pending writes: {self._queue.qsize()})...")
        self._shutdown_event.set()
        
        if self._worker_thread:
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                logger.warning(f"Worker thread did not stop within {timeout}s (may have unflushed writes)")
        
        self._running = False
        logger.info("AsyncSQLiteQueue stopped")
    
    def enqueue(
        self,
        operation: str,
        priority: WritePriority = WritePriority.MEDIUM,
        **kwargs,
    ) -> bool:
        """
        Enqueue a write operation.
        
        Priority handling:
        - HIGH: NEVER dropped. Will block briefly if queue is full (backpressure).
        - MEDIUM: Dropped only if queue is full AND no LOW priority items to evict.
        - LOW: Dropped immediately if queue is full.
        
        Args:
            operation: Operation name ("add_trade", "add_signal_event", "add_cycle_diagnostics")
            priority: Write priority
            **kwargs: Arguments to pass to the TradeDatabase method
        
        Returns:
            True if enqueued successfully, False if dropped
        """
        if not self._running:
            logger.debug(f"AsyncSQLiteQueue not running, dropping write: {operation}")
            self._total_drops += 1
            return False
        
        write = QueuedWrite(
            priority=priority,
            operation=operation,
            kwargs=kwargs,
        )
        
        try:
            # Non-blocking put: if queue is full, handle by priority
            self._queue.put_nowait(write)
            if priority == WritePriority.HIGH:
                self._total_high_priority_writes += 1
            return True
        except queue.Full:
            # Queue full: handle based on priority
            if priority == WritePriority.HIGH:
                # HIGH priority NEVER drops - block with timeout (backpressure)
                self._total_backpressure_waits += 1
                try:
                    logger.warning(
                        f"AsyncSQLiteQueue full - applying backpressure for HIGH priority write: {operation}"
                    )
                    # Block up to timeout waiting for space
                    self._queue.put(write, timeout=self._high_priority_timeout)
                    self._total_high_priority_writes += 1
                    return True
                except queue.Full:
                    # Even after waiting, queue is still full
                    # As a last resort, execute HIGH priority write synchronously
                    logger.error(
                        f"AsyncSQLiteQueue backpressure timeout - executing HIGH priority write synchronously: {operation}"
                    )
                    try:
                        self._execute_write(write)
                        self._total_writes += 1
                        self._total_high_priority_writes += 1
                        return True
                    except Exception as e:
                        self._total_errors += 1
                        logger.error(f"Synchronous HIGH priority write failed: {e}")
                        return False
            elif priority == WritePriority.MEDIUM:
                # MEDIUM priority: try once more with short wait, then drop
                try:
                    self._queue.put(write, timeout=0.1)
                    return True
                except queue.Full:
                    self._total_drops += 1
                    logger.warning(f"Dropped MEDIUM priority write (queue full): {operation}")
                    return False
            else:
                # LOW priority: drop immediately
                self._total_drops += 1
                logger.debug(f"Dropped LOW priority write (queue full): {operation}")
                return False
    
    def is_backpressure_active(self) -> bool:
        """Check if queue is under backpressure (above threshold)."""
        return self._queue.qsize() >= self._backpressure_threshold
    
    def _worker_loop(self) -> None:
        """Background worker thread loop."""
        logger.info("AsyncSQLiteQueue worker loop started")
        
        while not self._shutdown_event.is_set():
            try:
                # Block with timeout so we can check shutdown_event periodically
                try:
                    write = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # Execute write
                start_time = time.monotonic()
                try:
                    self._execute_write(write)
                    self._total_writes += 1
                    
                    # Track latency
                    latency_ms = (time.monotonic() - start_time) * 1000
                    self._write_times.append(latency_ms)
                    if len(self._write_times) > 1000:
                        self._write_times = self._write_times[-1000:]
                    
                except Exception as e:
                    self._total_errors += 1
                    logger.debug(f"SQLite write failed (non-fatal): {write.operation} | {e}")
                finally:
                    self._queue.task_done()
                
            except Exception as e:
                logger.error(f"AsyncSQLiteQueue worker error: {e}", exc_info=True)
        
        # Flush remaining writes on shutdown
        remaining = self._queue.qsize()
        if remaining > 0:
            logger.info(f"Flushing {remaining} pending SQLite writes...")
            flushed = 0
            while not self._queue.empty() and flushed < remaining:
                try:
                    write = self._queue.get_nowait()
                    self._execute_write(write)
                    self._total_writes += 1
                    flushed += 1
                    self._queue.task_done()
                except queue.Empty:
                    break
                except Exception as e:
                    self._total_errors += 1
                    logger.debug(f"Flush write failed: {e}")
            logger.info(f"Flushed {flushed}/{remaining} writes")
        
        logger.info("AsyncSQLiteQueue worker loop exited")
    
    def _execute_write(self, write: QueuedWrite) -> None:
        """Execute a queued write operation."""
        operation = write.operation
        kwargs = write.kwargs
        
        if operation == "add_trade":
            self._trade_db.add_trade(**kwargs)
        elif operation == "add_signal_event":
            self._trade_db.add_signal_event(**kwargs)
        elif operation == "add_cycle_diagnostics":
            self._trade_db.add_cycle_diagnostics(**kwargs)
        elif operation == "add_regime_snapshot":
            self._trade_db.add_regime_snapshot(**kwargs)
        else:
            logger.warning(f"Unknown SQLite operation: {operation}")
    
    def get_metrics(self) -> AsyncSQLiteQueueMetrics:
        """Get current queue metrics for observability."""
        elapsed = time.monotonic() - self._metrics_start_time
        writes_per_sec = self._total_writes / max(1.0, elapsed)
        
        avg_latency = 0.0
        if self._write_times:
            avg_latency = sum(self._write_times) / len(self._write_times)
        
        return AsyncSQLiteQueueMetrics(
            queue_depth=self._queue.qsize(),
            total_writes=self._total_writes,
            total_drops=self._total_drops,
            total_errors=self._total_errors,
            total_high_priority_writes=self._total_high_priority_writes,
            total_backpressure_waits=self._total_backpressure_waits,
            writes_per_second=writes_per_sec,
            avg_latency_ms=avg_latency,
            worker_running=self._running and (self._worker_thread is not None) and self._worker_thread.is_alive(),
            backpressure_active=self.is_backpressure_active(),
        )


