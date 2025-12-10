"""
Unit tests for worker pool.
"""

import pytest
import asyncio
from datetime import datetime, timezone

from pearlalgo.monitoring.worker_pool import WorkerPool, Worker, WorkerStatus


@pytest.fixture
def worker_pool():
    """Create a worker pool for testing."""
    return WorkerPool(max_workers=5, max_restarts=3)


@pytest.mark.asyncio
async def test_worker_registration(worker_pool):
    """Test worker registration."""
    async def dummy_worker():
        await asyncio.sleep(0.1)

    worker = worker_pool.register_worker(
        "test_worker", "test", dummy_worker
    )

    assert worker.name == "test_worker"
    assert worker.worker_type == "test"
    assert "test_worker" in worker_pool.workers


@pytest.mark.asyncio
async def test_worker_health(worker_pool):
    """Test worker health checking."""
    async def healthy_worker():
        await asyncio.sleep(0.1)

    worker = worker_pool.register_worker(
        "healthy", "test", healthy_worker
    )

    assert worker.is_healthy()
    assert worker.status == WorkerStatus.IDLE or worker.status == WorkerStatus.RUNNING


@pytest.mark.asyncio
async def test_worker_statistics(worker_pool):
    """Test worker pool statistics."""
    async def dummy_worker():
        await asyncio.sleep(0.1)

    worker_pool.register_worker("worker1", "futures", dummy_worker)
    worker_pool.register_worker("worker2", "options", dummy_worker)

    stats = worker_pool.get_statistics()
    assert stats["total_workers"] == 2
    assert stats["workers_by_type"]["futures"] == 1
    assert stats["workers_by_type"]["options"] == 1


@pytest.mark.asyncio
async def test_worker_stop(worker_pool):
    """Test stopping a worker."""
    async def long_worker():
        await asyncio.sleep(10)

    worker = worker_pool.register_worker("long", "test", long_worker)

    # Stop worker
    await worker_pool.stop_worker("long")

    assert worker.status == WorkerStatus.STOPPED


@pytest.mark.asyncio
async def test_worker_restart_on_error(worker_pool):
    """Test worker restart on error."""
    error_count = 0

    async def failing_worker():
        nonlocal error_count
        error_count += 1
        if error_count < 2:
            raise Exception("Test error")
        await asyncio.sleep(0.1)

    worker = worker_pool.register_worker(
        "failing", "test", failing_worker
    )

    # Wait for worker to run and potentially restart
    await asyncio.sleep(1)

    # Worker should have restarted
    assert worker.restart_count > 0 or worker.error_count > 0
