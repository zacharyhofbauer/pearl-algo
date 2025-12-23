"""
Error recovery tests for the NQ Agent.

These tests target *observable behavior* (pause reason / circuit breaker state),
not internal attribute twiddling.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pandas as pd
import pytest

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


class _DisconnectedExecutor:
    def is_connected(self) -> bool:  # pragma: no cover (simple stub)
        return False


class StubIBKRProvider(DataProvider):
    """Minimal provider that looks like a disconnected IBKR provider to ErrorHandler."""

    def __init__(self) -> None:
        self._executor = _DisconnectedExecutor()

    def fetch_historical(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_latest_bar(self, symbol: str):  # matches fetcher hasattr() usage
        return None


@pytest.mark.asyncio
async def test_connection_failure_circuit_breaker_pauses_service(tmp_path) -> None:
    provider = StubIBKRProvider()

    config = NQIntradayConfig()
    config.scan_interval = 0.05  # type: ignore[assignment]

    service = NQAgentService(data_provider=provider, config=config, state_dir=tmp_path)
    service.max_connection_failures = 1  # trigger immediately

    task = asyncio.create_task(service.start())

    # Wait until the service pauses due to connection failures.
    for _ in range(40):
        if service.paused:
            break
        await asyncio.sleep(0.05)

    assert service.paused
    assert service.pause_reason == "connection_failures"

    await service.stop("test")
    await asyncio.wait_for(task, timeout=2.0)






