"""
Unit tests for IBKRProvider with a mocked IBKRExecutor.

Covers:
1. Circuit breaker state transitions  (ConnectionCircuitBreaker in isolation)
2. Provider data fetching              (mocked executor, no network)
3. Error classification                (connection errors, IBKR Error 162)
4. Cache behavior                      (read-through on open, write on success)

Uses unittest.mock to replace the IBKRExecutor so no IB Gateway is needed.
"""

from __future__ import annotations

import time
from concurrent.futures import Future as ConcurrentFuture
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.data_providers.ibkr.ibkr_provider import (
    ConnectionCircuitBreaker,
    IBKRProvider,
)


# -- Helpers ------------------------------------------------------------------


def _resolved_future(result) -> ConcurrentFuture:
    """Return a ConcurrentFuture already resolved with *result*."""
    f: ConcurrentFuture = ConcurrentFuture()
    f.set_result(result)
    return f


def _failed_future(exc: BaseException) -> ConcurrentFuture:
    """Return a ConcurrentFuture already resolved with an exception."""
    f: ConcurrentFuture = ConcurrentFuture()
    f.set_exception(exc)
    return f


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def mock_executor():
    """Mock IBKRExecutor that never touches the network."""
    executor = MagicMock()
    executor.start.return_value = None
    executor.stop.return_value = None
    executor.is_connected.return_value = True
    return executor


@pytest.fixture
def mock_settings():
    """Lightweight mock of Settings (only the fields IBKRProvider reads)."""
    s = MagicMock()
    s.ib_host = "127.0.0.1"
    s.ib_port = 4001
    s.ib_data_client_id = 10
    s.ib_client_id = 1
    return s


@pytest.fixture
def ibkr_provider(mock_settings, mock_executor):
    """IBKRProvider wired to the mock executor (no real IB connection)."""
    with patch(
        "pearlalgo.data_providers.ibkr.ibkr_provider.IBKRExecutor",
        return_value=mock_executor,
    ):
        provider = IBKRProvider(
            settings=mock_settings,
            host="127.0.0.1",
            port=4001,
            client_id=10,
        )
    return provider


# =============================================================================
# 1. Circuit Breaker State Transitions
# =============================================================================


class TestCircuitBreakerTransitions:
    """Verify the ConnectionCircuitBreaker state machine in isolation."""

    def test_initial_state_is_closed(self):
        cb = ConnectionCircuitBreaker()
        assert cb.state == "closed"
        assert not cb.is_open

    def test_opens_after_n_consecutive_failures(self):
        cb = ConnectionCircuitBreaker(failure_threshold=3)
        # Two failures: still closed
        for _ in range(2):
            cb.record_failure()
        assert cb.state == "closed", "Must not open before threshold"

        # Third failure: threshold reached
        cb.record_failure()
        assert cb.state == "open"
        assert cb.is_open

    def test_open_state_serves_cached_data(self):
        cb = ConnectionCircuitBreaker(failure_threshold=2)
        cached_df = pd.DataFrame({"close": [100.0, 101.0]})
        cached_bar = {"close": 99.5, "volume": 42}
        cb.cache_df(cached_df)
        cb.cache_bar(cached_bar)

        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open

        assert not cb.get_cached_df().empty
        assert list(cb.get_cached_df()["close"]) == [100.0, 101.0]
        assert cb.get_cached_bar() == cached_bar

    def test_transitions_to_half_open_after_cooldown(self):
        cb = ConnectionCircuitBreaker(failure_threshold=2, recovery_seconds=30.0)
        cb.record_failure()
        cb.record_failure()
        assert cb._state == "open"

        # Simulate elapsed cooldown by shifting _opened_at into the past
        cb._opened_at = time.monotonic() - 35
        assert cb.state == "half_open"

    def test_success_in_half_open_resets_to_closed(self):
        cb = ConnectionCircuitBreaker(failure_threshold=2, recovery_seconds=30.0)
        cb.record_failure()
        cb.record_failure()
        cb._opened_at = time.monotonic() - 35  # past cooldown
        assert cb.state == "half_open"

        cb.record_success()
        assert cb.state == "closed"
        assert cb._consecutive_failures == 0

    def test_failure_in_half_open_reopens_circuit(self):
        cb = ConnectionCircuitBreaker(failure_threshold=2, recovery_seconds=30.0)
        cb.record_failure()
        cb.record_failure()
        cb._opened_at = time.monotonic() - 35  # past cooldown
        assert cb.state == "half_open"

        # Probe fails -> circuit re-opens
        cb.record_failure()
        assert cb._state == "open"


# =============================================================================
# 2. Provider Data Fetching (Mocked Executor)
# =============================================================================


class TestProviderDataFetching:
    """fetch_historical and get_latest_bar with a mocked executor."""

    @pytest.mark.asyncio
    async def test_fetch_historical_returns_dataframe_on_success(
        self, ibkr_provider, mock_executor,
    ):
        """Successful executor call -> non-empty DataFrame with standard columns."""
        ibkr_provider.validate_connection = AsyncMock(return_value=True)

        # Executor returns a non-empty list of bars
        mock_executor.submit_task.return_value = _resolved_future([MagicMock()])

        now = datetime.now(timezone.utc)
        df_from_ib = pd.DataFrame({
            "date": pd.to_datetime([now]),
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1000],
        })

        with patch(
            "pearlalgo.data_providers.ibkr.ibkr_provider.util.df",
            return_value=df_from_ib,
        ):
            result = await ibkr_provider._fetch_historical_async("AAPL")

        assert not result.empty
        assert "close" in result.columns
        assert result["close"].iloc[0] == 101.0

    @pytest.mark.asyncio
    async def test_fetch_historical_returns_empty_df_on_failure(
        self, ibkr_provider, mock_executor,
    ):
        """Executor raises -> graceful degradation returns empty DataFrame."""
        ibkr_provider.validate_connection = AsyncMock(return_value=True)
        mock_executor.submit_task.return_value = _failed_future(
            RuntimeError("connection reset"),
        )

        result = await ibkr_provider._fetch_historical_async("AAPL")
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    @pytest.mark.asyncio
    async def test_get_latest_bar_cached_when_circuit_open(self, ibkr_provider):
        """When circuit is open, cached bar is returned immediately."""
        cached = {"close": 150.0, "open": 149.0}
        ibkr_provider._circuit_breaker.cache_bar(cached)
        # Force the circuit open (recovery_seconds=60 so it stays open)
        ibkr_provider._circuit_breaker._state = "open"
        ibkr_provider._circuit_breaker._opened_at = time.monotonic()

        result = await ibkr_provider.get_latest_bar("AAPL")
        assert result == cached

    @pytest.mark.asyncio
    async def test_get_latest_bar_none_when_no_cache(self, ibkr_provider):
        """Circuit open + no cached bar -> None."""
        ibkr_provider._circuit_breaker._state = "open"
        ibkr_provider._circuit_breaker._opened_at = time.monotonic()

        result = await ibkr_provider.get_latest_bar("AAPL")
        assert result is None


# =============================================================================
# 3. Error Classification
# =============================================================================


class TestErrorClassification:
    """Connection errors and IBKR-specific error codes."""

    @pytest.mark.asyncio
    async def test_connection_error_increments_circuit_failures(
        self, ibkr_provider, mock_executor,
    ):
        """Generic connection error is recorded as a circuit breaker failure."""
        ibkr_provider.validate_connection = AsyncMock(return_value=True)
        mock_executor.submit_task.return_value = _failed_future(
            ConnectionError("broker unavailable"),
        )

        before = ibkr_provider._circuit_breaker._consecutive_failures
        await ibkr_provider._fetch_historical_async("AAPL")
        assert ibkr_provider._circuit_breaker._consecutive_failures == before + 1

    @pytest.mark.asyncio
    async def test_error_162_returns_empty_df_without_tripping_breaker(
        self, ibkr_provider, mock_executor,
    ):
        """Error 162 (TWS session conflict) returns empty DF and does NOT
        record a circuit breaker failure (handled as a special case)."""
        ibkr_provider.validate_connection = AsyncMock(return_value=True)
        mock_executor.submit_task.return_value = _failed_future(
            Exception(
                "Error 162: Historical data request pacing violation / "
                "TWS session connected from different IP"
            ),
        )

        result = await ibkr_provider._fetch_historical_async("AAPL")

        assert isinstance(result, pd.DataFrame)
        assert result.empty
        # Error 162 is handled inline -- breaker should NOT have tripped
        assert ibkr_provider._circuit_breaker._consecutive_failures == 0


# =============================================================================
# 4. Cache Behavior
# =============================================================================


class TestCacheBehavior:
    """Cached data is served when circuit opens and updated on success."""

    @pytest.mark.asyncio
    async def test_cached_historical_df_returned_when_circuit_open(
        self, ibkr_provider,
    ):
        """Open circuit -> provider returns previously-cached DataFrame."""
        cached = pd.DataFrame({"close": [200.0, 201.0]})
        ibkr_provider._circuit_breaker.cache_df(cached)
        ibkr_provider._circuit_breaker._state = "open"
        ibkr_provider._circuit_breaker._opened_at = time.monotonic()

        result = await ibkr_provider._fetch_historical_async("AAPL")
        assert not result.empty
        assert list(result["close"]) == [200.0, 201.0]

    @pytest.mark.asyncio
    async def test_cache_updated_on_successful_fetch(
        self, ibkr_provider, mock_executor,
    ):
        """After a successful fetch, circuit breaker cache holds the new data."""
        ibkr_provider.validate_connection = AsyncMock(return_value=True)
        mock_executor.submit_task.return_value = _resolved_future([MagicMock()])

        now = datetime.now(timezone.utc)
        df_from_ib = pd.DataFrame({
            "date": pd.to_datetime([now]),
            "open": [300.0],
            "high": [302.0],
            "low": [299.0],
            "close": [301.0],
            "volume": [5000],
        })

        with patch(
            "pearlalgo.data_providers.ibkr.ibkr_provider.util.df",
            return_value=df_from_ib,
        ):
            await ibkr_provider._fetch_historical_async("AAPL")

        cached = ibkr_provider._circuit_breaker.get_cached_df()
        assert not cached.empty
        assert cached["close"].iloc[0] == 301.0
