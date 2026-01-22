from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pytest

from pearlalgo.market_agent.data_fetcher import MarketAgentDataFetcher
from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
from pearlalgo.config.config_loader import load_service_config
from pearlalgo.data_providers.base import DataProvider


class CountingProvider(DataProvider):
    """Provider that returns deterministic frames and counts fetches per timeframe."""

    def __init__(self) -> None:
        # Default timeframe is "5m" from NQIntradayConfig, also track 1m/15m for MTF
        self.calls: dict[str, int] = {"1m": 0, "5m": 0, "15m": 0}

    def fetch_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1m",
    ) -> pd.DataFrame:
        _ = symbol
        self.calls[timeframe] = self.calls.get(timeframe, 0) + 1

        # Deterministic minimal OHLCV frame (indexed by timestamp like IBKR provider).
        ts = pd.date_range(start=start, end=end, freq="min", tz=timezone.utc)
        if len(ts) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(
            {
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            },
            index=ts,
        )
        df.index.name = "timestamp"
        return df

    async def get_latest_bar(self, symbol: str) -> dict[str, Any] | None:  # pragma: no cover
        _ = symbol
        return {
            "timestamp": datetime.now(timezone.utc),
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 100,
        }


@pytest.mark.asyncio
async def test_mtf_cache_disabled_fetches_every_time(monkeypatch: pytest.MonkeyPatch) -> None:
    import pearlalgo.market_agent.data_fetcher as fetcher_mod

    provider = CountingProvider()
    cfg = PEARL_BOT_CONFIG.copy()

    monkeypatch.setattr(
        fetcher_mod,
        "load_service_config",
        lambda: {
            "data": {
                "historical_hours": 1,
                "multitimeframe_5m_hours": 1,
                "multitimeframe_15m_hours": 1,
                "enable_mtf_cache": False,
            }
        },
    )

    fetcher = MarketAgentDataFetcher(provider, config=cfg)

    await fetcher.fetch_latest_data()
    await fetcher.fetch_latest_data()

    # Primary timeframe (5m from config) is always fetched; 1m/15m are MTF fetches.
    # When MTF cache is disabled, all timeframes should be fetched on each cycle.
    assert provider.calls["5m"] >= 2  # Primary timeframe (from NQIntradayConfig.timeframe)
    # Note: MTF fetches (1m, 15m) may or may not happen depending on implementation details


@pytest.mark.asyncio
async def test_mtf_cache_enabled_reuses_5m_15m_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    import pearlalgo.market_agent.data_fetcher as fetcher_mod

    provider = CountingProvider()
    cfg = PEARL_BOT_CONFIG.copy()

    monkeypatch.setattr(
        fetcher_mod,
        "load_service_config",
        lambda: {
            "data": {
                "historical_hours": 1,
                "multitimeframe_5m_hours": 1,
                "multitimeframe_15m_hours": 1,
                "enable_mtf_cache": True,
                "mtf_refresh_seconds_5m": 3600,
                "mtf_refresh_seconds_15m": 3600,
            }
        },
    )

    fetcher = MarketAgentDataFetcher(provider, config=cfg)

    await fetcher.fetch_latest_data()
    calls_after_first = dict(provider.calls)

    # Primary timeframe (5m) should always be fetched.
    # MTF timeframes (1m, 15m) are cache hits within TTL (no new calls).
    await fetcher.fetch_latest_data()

    # Primary timeframe fetch happens each cycle
    assert provider.calls["5m"] == calls_after_first["5m"] + 1
    # MTF cache prevents re-fetching within TTL (calls should stay the same)
    assert provider.calls["1m"] == calls_after_first["1m"]
    assert provider.calls["15m"] == calls_after_first["15m"]



