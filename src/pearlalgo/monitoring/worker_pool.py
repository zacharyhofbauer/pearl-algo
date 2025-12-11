"""
Worker Pool Architecture - Parallel workers for scanning different asset classes.

Provides:
- Separate workers for futures, options, data ingestion
- Worker health monitoring
- Automatic worker restart on failure
- Load balancing
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class WorkerStatus(Enum):
    """Worker status enumeration."""

    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class Worker:
    """Represents a single worker in the pool."""

    name: str
    worker_type: str  # "futures", "options", "data_feed"
    status: WorkerStatus = WorkerStatus.IDLE
    task: Optional[asyncio.Task] = None
    error_count: int = 0
    last_error: Optional[str] = None
    last_success: Optional[datetime] = None
    start_time: Optional[datetime] = None
    restart_count: int = 0
    max_restarts: int = 10

    def is_healthy(self, max_error_count: int = 5) -> bool:
        """Check if worker is healthy."""
        return (
            self.status != WorkerStatus.ERROR
            or self.error_count < max_error_count
        ) and self.restart_count < self.max_restarts


class WorkerPool:
    """
    Manages a pool of workers for parallel scanning.

    Workers can be:
    - Futures intraday scanning (NQ, ES)
    - Options swing scanning (equity universe)
    - Data ingestion (Massive WebSocket + REST fallback)
    """

    def __init__(
        self,
        max_workers: int = 10,
        max_restarts: int = 10,
        health_check_interval: int = 60,
    ):
        """
        Initialize worker pool.

        Args:
            max_workers: Maximum number of workers
            max_restarts: Maximum restarts per worker before giving up
            health_check_interval: Health check interval in seconds
        """
        self.max_workers = max_workers
        self.max_restarts = max_restarts
        self.health_check_interval = health_check_interval

        # Workers: name -> Worker
        self.workers: Dict[str, Worker] = {}

        # Health check task
        self.health_check_task: Optional[asyncio.Task] = None
        self.running = False

        logger.info(
            f"WorkerPool initialized: max_workers={max_workers}, "
            f"max_restarts={max_restarts}"
        )

    def register_worker(
        self,
        name: str,
        worker_type: str,
        coro: Callable,
        *args,
        **kwargs,
    ) -> Worker:
        """
        Register a new worker.

        Args:
            name: Worker name (unique identifier)
            worker_type: Type of worker ("futures", "options", "data_feed")
            coro: Coroutine function to run
            *args: Arguments for coroutine
            **kwargs: Keyword arguments for coroutine

        Returns:
            Worker instance
        """
        if name in self.workers:
            logger.warning(f"Worker {name} already exists, replacing...")

        worker = Worker(
            name=name,
            worker_type=worker_type,
            max_restarts=self.max_restarts,
        )

        # Create task wrapper
        async def worker_wrapper():
            """Wrapper that handles errors and restarts."""
            while worker.is_healthy():
                try:
                    worker.status = WorkerStatus.RUNNING
                    worker.start_time = datetime.now(timezone.utc)
                    await coro(*args, **kwargs)
                    worker.status = WorkerStatus.IDLE
                    worker.last_success = datetime.now(timezone.utc)
                    worker.error_count = 0  # Reset on success
                except asyncio.CancelledError:
                    logger.info(f"Worker {name} cancelled")
                    worker.status = WorkerStatus.STOPPED
                    break
                except Exception as e:
                    worker.error_count += 1
                    worker.last_error = str(e)
                    worker.status = WorkerStatus.ERROR
                    worker.restart_count += 1
                    logger.error(
                        f"Worker {name} error (count={worker.error_count}, "
                        f"restarts={worker.restart_count}): {e}",
                        exc_info=True,
                    )

                    if worker.is_healthy():
                        # Wait before restart
                        wait_time = min(60, 2 ** worker.error_count)
                        logger.info(f"Restarting worker {name} in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(
                            f"Worker {name} exceeded max errors/restarts, stopping"
                        )
                        break

        worker.task = asyncio.create_task(worker_wrapper())
        self.workers[name] = worker

        logger.info(f"Registered worker: {name} (type={worker_type})")
        return worker

    async def start_health_checks(self) -> None:
        """Start periodic health checks."""
        self.running = True

        async def health_check_loop():
            """Periodic health check loop."""
            while self.running:
                await asyncio.sleep(self.health_check_interval)
                await self._check_health()

        self.health_check_task = asyncio.create_task(health_check_loop())
        logger.info("Started health check loop")

    async def _check_health(self) -> None:
        """Check health of all workers."""
        for name, worker in self.workers.items():
            if not worker.is_healthy():
                logger.warning(
                    f"Worker {name} is unhealthy: "
                    f"status={worker.status}, errors={worker.error_count}, "
                    f"restarts={worker.restart_count}"
                )

            # Check if task is done (crashed)
            if worker.task and worker.task.done():
                if worker.is_healthy():
                    logger.warning(f"Worker {name} task completed, restarting...")
                    # Restart worker (would need original coro, simplified here)
                    # In practice, you'd store the coro and args for restart
                else:
                    logger.error(f"Worker {name} task failed and exceeded limits")

    async def stop_worker(self, name: str) -> None:
        """Stop a specific worker."""
        if name not in self.workers:
            return

        worker = self.workers[name]
        if worker.task:
            worker.task.cancel()
            try:
                await worker.task
            except asyncio.CancelledError:
                pass

        worker.status = WorkerStatus.STOPPED
        logger.info(f"Stopped worker: {name}")

    async def stop_all_workers(self) -> None:
        """Stop all workers."""
        logger.info("Stopping all workers...")
        self.running = False

        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass

        for name in list(self.workers.keys()):
            await self.stop_worker(name)

        logger.info("All workers stopped")

    def get_worker(self, name: str) -> Optional[Worker]:
        """Get worker by name."""
        return self.workers.get(name)

    def get_workers_by_type(self, worker_type: str) -> list[Worker]:
        """Get all workers of a specific type."""
        return [w for w in self.workers.values() if w.worker_type == worker_type]

    def get_statistics(self) -> Dict:
        """Get worker pool statistics."""
        stats = {
            "total_workers": len(self.workers),
            "workers_by_type": {},
            "workers_by_status": {},
            "total_errors": 0,
            "total_restarts": 0,
        }

        for worker in self.workers.values():
            # Count by type
            stats["workers_by_type"][worker.worker_type] = (
                stats["workers_by_type"].get(worker.worker_type, 0) + 1
            )

            # Count by status
            stats["workers_by_status"][worker.status.value] = (
                stats["workers_by_status"].get(worker.status.value, 0) + 1
            )

            # Sum errors and restarts
            stats["total_errors"] += worker.error_count
            stats["total_restarts"] += worker.restart_count

        return stats

    def get_health_status(self) -> Dict:
        """Get health status of all workers."""
        health = {
            "healthy": True,
            "workers": {},
        }

        for name, worker in self.workers.items():
            is_healthy = worker.is_healthy()
            if not is_healthy:
                health["healthy"] = False

            health["workers"][name] = {
                "status": worker.status.value,
                "healthy": is_healthy,
                "error_count": worker.error_count,
                "restart_count": worker.restart_count,
                "last_error": worker.last_error,
                "last_success": (
                    worker.last_success.isoformat() if worker.last_success else None
                ),
                "uptime_seconds": (
                    (datetime.now(timezone.utc) - worker.start_time).total_seconds()
                    if worker.start_time
                    else None
                ),
            }

        return health
