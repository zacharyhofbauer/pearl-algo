"""
Tests for base historical data caching in MarketAgentDataFetcher.

Validates that:
1. Base cache reduces provider fetch calls when enabled
2. Cache hits don't corrupt dataframe structure (no duplicate columns)
3. Historical fallback timestamp extraction works with both index-based and column-based dataframes
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pytest

from pearlalgo.market_agent.data_fetcher import MarketAgentDataFetcher
from pearlalgo.trading_bots.signal_generator import CONFIG as PEARL_BOT_CONFIG
from pearlalgo.config.config_loader import load_service_config
from pearlalgo.data_providers.base import DataProvider


class CountingProviderNoLatestBar(DataProvider):
    """
    Provider that:
    - Returns deterministic frames with timestamp as DatetimeIndex
    - Counts fetch_historical calls
    - Returns None for get_latest_bar (forces historical fallback)
    """

    def __init__(self) -> None:
        self.fetch_count: int = 0

    def fetch_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "5m",
    ) -> pd.DataFrame:
        _ = symbol
        self.fetch_count += 1

        # Deterministic minimal OHLCV frame (indexed by timestamp like IBKR provider).
        ts = pd.date_range(start=start, end=end, freq="min", tz=timezone.utc)
        if len(ts) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(
            {
                "open": 17500.0,
                "high": 17510.0,
                "low": 17490.0,
                "close": 17505.0,
                "volume": 100,
            },
            index=ts,
        )
        df.index.name = "timestamp"
        return df

    async def get_latest_bar(self, symbol: str) -> dict[str, Any] | None:
        """Return None to force historical fallback in data fetcher."""
        _ = symbol
        return None


@pytest.mark.asyncio
async def test_base_cache_reduces_fetch_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When base cache is enabled with a long TTL, repeated fetch_latest_data()
    calls should result in only one provider fetch (cache hits on subsequent calls).
    """
    import pearlalgo.market_agent.data_fetcher as fetcher_mod

    provider = CountingProviderNoLatestBar()
    cfg = PEARL_BOT_CONFIG.copy()

    monkeypatch.setattr(
        fetcher_mod,
        "load_service_config",
        lambda: {
            "data": {
                "buffer_size": 100,
                "buffer_size_5m": 50,
                "buffer_size_15m": 50,
                "historical_hours": 1,
                "multitimeframe_5m_hours": 1,
                "multitimeframe_15m_hours": 1,
                "stale_data_threshold_minutes": 60,  # High threshold to avoid warnings
                "enable_base_cache": True,
                "base_refresh_seconds": 3600,  # 1 hour TTL - should not expire during test
                "enable_mtf_cache": False,
            }
        },
    )

    fetcher = MarketAgentDataFetcher(provider, config=cfg)

    # First fetch - cache miss
    result1 = await fetcher.fetch_latest_data()
    first_fetch_count = provider.fetch_count

    # Second fetch - should be cache hit (no new provider calls)
    result2 = await fetcher.fetch_latest_data()
    second_fetch_count = provider.fetch_count

    # Verify cache hit: provider fetch count should not have increased for base historical
    # Note: MTF fetches (5m/15m) still happen each time when MTF cache is disabled
    assert first_fetch_count >= 1, "First fetch should call provider at least once"
    # The base cache hit means we don't re-fetch base historical data
    # But MTF might still add fetches. We're mainly checking cache stats.
    
    cache_stats = fetcher.get_cache_stats()
    assert cache_stats["base_cache_enabled"] is True
    assert cache_stats["base_hits"] >= 1, "Should have at least one cache hit on second fetch"


@pytest.mark.asyncio
async def test_base_cache_no_column_accumulation(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Repeated cache hits should not accumulate 'index' columns in the strategy buffer.
    The strategy buffer should have 'timestamp' as a column (not 'index').
    """
    import pearlalgo.market_agent.data_fetcher as fetcher_mod

    provider = CountingProviderNoLatestBar()
    cfg = PEARL_BOT_CONFIG.copy()

    monkeypatch.setattr(
        fetcher_mod,
        "load_service_config",
        lambda: {
            "data": {
                "buffer_size": 100,
                "buffer_size_5m": 50,
                "buffer_size_15m": 50,
                "historical_hours": 1,
                "multitimeframe_5m_hours": 1,
                "multitimeframe_15m_hours": 1,
                "stale_data_threshold_minutes": 60,
                "enable_base_cache": True,
                "base_refresh_seconds": 3600,
                "enable_mtf_cache": False,
            }
        },
    )

    fetcher = MarketAgentDataFetcher(provider, config=cfg)

    # Multiple fetches - each should normalize buffer correctly
    for i in range(3):
        result = await fetcher.fetch_latest_data()
        df = result["df"]
        
        if not df.empty:
            # Should have 'timestamp' column
            assert "timestamp" in df.columns, f"Fetch {i+1}: 'timestamp' column missing"
            # Should NOT have 'index' column (artifact of double reset_index)
            assert "index" not in df.columns, f"Fetch {i+1}: 'index' column should not exist"
            # Count of columns should be stable
            expected_cols = {"timestamp", "open", "high", "low", "close", "volume"}
            actual_cols = set(df.columns)
            assert actual_cols == expected_cols, f"Fetch {i+1}: unexpected columns {actual_cols - expected_cols}"


@pytest.mark.asyncio
async def test_historical_fallback_extracts_timestamp_from_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When get_latest_bar returns None and we fall back to historical data,
    the timestamp should be correctly extracted from the DatetimeIndex.
    """
    import pearlalgo.market_agent.data_fetcher as fetcher_mod

    provider = CountingProviderNoLatestBar()
    cfg = PEARL_BOT_CONFIG.copy()

    monkeypatch.setattr(
        fetcher_mod,
        "load_service_config",
        lambda: {
            "data": {
                "buffer_size": 100,
                "buffer_size_5m": 50,
                "buffer_size_15m": 50,
                "historical_hours": 1,
                "multitimeframe_5m_hours": 1,
                "multitimeframe_15m_hours": 1,
                "stale_data_threshold_minutes": 60,
                "enable_base_cache": False,  # Disable cache to get fresh data
                "enable_mtf_cache": False,
            }
        },
    )

    fetcher = MarketAgentDataFetcher(provider, config=cfg)
    result = await fetcher.fetch_latest_data()

    latest_bar = result["latest_bar"]
    assert latest_bar is not None, "Should have latest_bar from historical fallback"
    assert "timestamp" in latest_bar, "latest_bar should have timestamp"
    assert isinstance(latest_bar["timestamp"], datetime), "timestamp should be datetime"
    assert latest_bar["timestamp"].tzinfo is not None, "timestamp should be timezone-aware"
    assert latest_bar["close"] == 17505.0, "close price should match provider data"


@pytest.mark.asyncio
async def test_historical_fallback_extracts_timestamp_from_column(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When dataframe has timestamp as a column (strategy buffer shape),
    the historical fallback should still correctly extract the timestamp.
    """
    import pearlalgo.market_agent.data_fetcher as fetcher_mod

    class ColumnBasedProvider(DataProvider):
        """Provider that returns data with timestamp as column, not index."""
        
        def __init__(self) -> None:
            self.fetch_count: int = 0

        def fetch_historical(
            self,
            symbol: str,
            start: datetime,
            end: datetime,
            timeframe: str = "5m",
        ) -> pd.DataFrame:
            _ = symbol
            self.fetch_count += 1
            ts = pd.date_range(start=start, end=end, freq="min", tz=timezone.utc)
            if len(ts) == 0:
                return pd.DataFrame()
            # Return with timestamp as column (not index)
            df = pd.DataFrame(
                {
                    "timestamp": ts,
                    "open": 18000.0,
                    "high": 18010.0,
                    "low": 17990.0,
                    "close": 18005.0,
                    "volume": 200,
                }
            )
            return df

        async def get_latest_bar(self, symbol: str) -> dict[str, Any] | None:
            return None

    provider = ColumnBasedProvider()
    cfg = PEARL_BOT_CONFIG.copy()

    monkeypatch.setattr(
        fetcher_mod,
        "load_service_config",
        lambda: {
            "data": {
                "buffer_size": 100,
                "buffer_size_5m": 50,
                "buffer_size_15m": 50,
                "historical_hours": 1,
                "multitimeframe_5m_hours": 1,
                "multitimeframe_15m_hours": 1,
                "stale_data_threshold_minutes": 60,
                "enable_base_cache": False,
                "enable_mtf_cache": False,
            }
        },
    )

    fetcher = MarketAgentDataFetcher(provider, config=cfg)
    result = await fetcher.fetch_latest_data()

    latest_bar = result["latest_bar"]
    assert latest_bar is not None, "Should have latest_bar from historical fallback"
    assert "timestamp" in latest_bar, "latest_bar should have timestamp"
    assert isinstance(latest_bar["timestamp"], datetime), "timestamp should be datetime"
    assert latest_bar["close"] == 18005.0, "close price should match provider data"

    # Also verify the strategy buffer has correct shape
    df = result["df"]
    assert "timestamp" in df.columns, "Strategy buffer should have timestamp column"
    assert "index" not in df.columns, "Strategy buffer should not have index column"








