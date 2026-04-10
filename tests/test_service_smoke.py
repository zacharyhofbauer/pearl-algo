"""
Smoke test: verify MarketAgentService can start, process one iteration, and shut down.

This test catches wiring regressions between the service, strategy, data fetcher,
and state manager without requiring external dependencies (IBKR, Tradovate, Telegram).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.market_agent.service import MarketAgentService
from pearlalgo.trading_bots.signal_generator import CONFIG as PEARL_BOT_CONFIG
from tests.mock_data_provider import MockDataProvider


@pytest.mark.asyncio
async def test_service_smoke_start_iterate_stop(tmp_path: Path) -> None:
    """Service should start, run at least one scan cycle, and shut down cleanly."""
    provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)

    config = PEARL_BOT_CONFIG.copy()
    config["scan_interval"] = 0.05  # fast cycle for test

    service = MarketAgentService(data_provider=provider, config=config, state_dir=tmp_path)
    service._adaptive_cadence_enabled = False

    task = asyncio.create_task(service.start())
    # Let the service run several cycles (first cycle may include init overhead)
    await asyncio.sleep(1.0)
    await service.stop("smoke_test")
    await asyncio.wait_for(task, timeout=5.0)

    assert not service.running
    # Verify the service processed at least one scan cycle
    assert service.cycle_count >= 1


@pytest.mark.asyncio
async def test_service_smoke_state_dir_created(tmp_path: Path) -> None:
    """Service should create its state directory on startup."""
    provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)
    state_dir = tmp_path / "agent_state" / "MNQ"

    config = PEARL_BOT_CONFIG.copy()
    config["scan_interval"] = 0.05

    service = MarketAgentService(data_provider=provider, config=config, state_dir=state_dir)

    task = asyncio.create_task(service.start())
    await asyncio.sleep(0.3)
    await service.stop("smoke_test")
    await asyncio.wait_for(task, timeout=3.0)

    # State dir should exist after service ran
    assert state_dir.exists()


@pytest.mark.asyncio
async def test_service_smoke_handles_provider_error(tmp_path: Path) -> None:
    """Service should survive a data provider error without crashing."""
    provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)

    # Make the provider fail on the first fetch, then succeed
    call_count = 0
    original_fetch = provider.fetch_historical

    def flaky_fetch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("Simulated IBKR disconnect")
        return original_fetch(*args, **kwargs)

    provider.fetch_historical = flaky_fetch  # type: ignore[assignment]

    config = PEARL_BOT_CONFIG.copy()
    config["scan_interval"] = 0.05

    service = MarketAgentService(data_provider=provider, config=config, state_dir=tmp_path)

    task = asyncio.create_task(service.start())
    await asyncio.sleep(0.5)
    await service.stop("smoke_test")
    await asyncio.wait_for(task, timeout=3.0)

    # Service should have survived the error and still be stoppable
    assert not service.running
