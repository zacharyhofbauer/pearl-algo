"""
Integration tests for 24/7 continuous service.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from pearlalgo.monitoring.continuous_service import ContinuousService


@pytest.fixture
def config():
    """Create test configuration."""
    return {
        "monitoring": {
            "workers": {
                "futures": {
                    "enabled": True,
                    "symbols": ["ES", "NQ"],
                    "interval": 60,
                    "strategy": "intraday_swing",
                },
                "options": {
                    "enabled": True,
                    "universe": ["SPY", "QQQ"],
                    "interval": 900,
                    "strategy": "swing_momentum",
                },
            },
            "data_feeds": {
                "
                    "rate_limit": 5,
                    "reconnect_delay": 5.0,
                },
            },
            "health": {
                "enabled": True,
                "port": 8080,
            },
        },
    }


@pytest.mark.asyncio
async def test_service_initialization(config):
    """Test service initialization."""
    service = ContinuousService(config=config)

    assert service.config == config
    assert service.worker_pool is not None
    assert service.buffer_manager is not None
    assert service.health_checker is not None


@pytest.mark.asyncio
async def test_worker_registration(config):
    """Test worker registration in service."""
    service = ContinuousService(config=config)

    # Workers should be registered during start
    # For testing, manually register
    async def dummy_futures_worker(symbols, strategy, interval):
        await asyncio.sleep(0.1)

    service.worker_pool.register_worker(
        "futures_scanner",
        "futures",
        dummy_futures_worker,
        symbols=["ES", "NQ"],
        strategy="intraday_swing",
        interval=60,
    )

    assert "futures_scanner" in service.worker_pool.workers


@pytest.mark.asyncio
async def test_service_shutdown(config):
    """Test service graceful shutdown."""
    service = ContinuousService(config=config)

    # Trigger shutdown
    service.shutdown_requested = True

    # Shutdown should complete without errors
    await service.shutdown()

    # Workers should be stopped
    assert len(service.worker_pool.workers) == 0 or all(
        w.status.value == "stopped" for w in service.worker_pool.workers.values()
    )
