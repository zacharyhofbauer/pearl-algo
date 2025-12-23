"""
Edge case tests for the NQ Agent.

These are intentionally small, fast, and assertion-driven (no placeholders).
"""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from tests.mock_data_provider import MockDataProvider


@pytest.mark.asyncio
async def test_data_fetcher_no_data_returns_empty() -> None:
    """Fetcher should not throw if both historical and latest_bar are unavailable."""
    provider = MockDataProvider(base_price=17500.0, volatility=0.0, trend=0.0)

    # Force provider to return no historical data and no latest bar.
    provider.fetch_historical = lambda *args, **kwargs: pd.DataFrame()  # type: ignore[assignment]

    async def _no_latest_bar(*args, **kwargs):
        return None

    provider.get_latest_bar = _no_latest_bar  # type: ignore[assignment]

    fetcher = NQAgentDataFetcher(provider, config=NQIntradayConfig())
    result = await fetcher.fetch_latest_data()

    # In a hard no-data scenario the fetcher may return the minimal shape.
    assert set(result.keys()) >= {"df", "latest_bar"}
    assert result["latest_bar"] is None
    assert result["df"].empty


@pytest.mark.asyncio
async def test_data_fetcher_schema_contains_ohlcv_columns_when_present() -> None:
    """When historical data exists, the OHLCV contract should be present."""
    provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)
    fetcher = NQAgentDataFetcher(provider, config=NQIntradayConfig())

    result = await fetcher.fetch_latest_data()
    assert set(result.keys()) >= {"df", "latest_bar", "df_5m", "df_15m"}

    if not result["df"].empty:
        for col in ("open", "high", "low", "close", "volume"):
            assert col in result["df"].columns


@pytest.mark.asyncio
async def test_service_start_stop_short_run(tmp_path) -> None:
    """Service should start and stop cleanly when run for a short time."""
    provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)

    config = NQIntradayConfig()
    # Keep the test tight: faster loop cadence and short overall runtime.
    config.scan_interval = 0.05  # type: ignore[assignment]

    service = NQAgentService(data_provider=provider, config=config, state_dir=tmp_path)

    task = asyncio.create_task(service.start())
    await asyncio.sleep(0.2)
    await service.stop("test")
    await asyncio.wait_for(task, timeout=2.0)

    assert not service.running






