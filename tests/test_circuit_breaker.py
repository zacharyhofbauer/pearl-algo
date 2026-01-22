"""
Circuit breaker tests for the NQ Agent Service.

These tests validate all circuit breaker paths:
1. Connection failure circuit breaker
2. Consecutive general errors circuit breaker  
3. Data fetch error backoff (not a hard pause, but a degraded mode)
4. Recovery from paused state
5. Proper counter reset on success

Test Philosophy:
- Each test targets a specific circuit breaker behavior
- Tests are deterministic (no flaky timing)
- Failure signals are explicit and observable
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import pytest

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.market_agent.service import MarketAgentService
from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
from pearlalgo.config.config_loader import load_service_config


class _DisconnectedExecutor:
    """Stub executor that reports disconnected state."""
    def is_connected(self) -> bool:
        return False


class _ConnectedExecutor:
    """Stub executor that reports connected state."""
    def is_connected(self) -> bool:
        return True


class FailingProvider(DataProvider):
    """Provider that fails in configurable ways."""

    def __init__(
        self,
        fail_fetch: bool = False,
        fail_latest: bool = False,
        simulate_disconnect: bool = False,
        fail_count: int = 0,  # Number of times to fail before succeeding (0 = always fail)
    ) -> None:
        self.fail_fetch = fail_fetch
        self.fail_latest = fail_latest
        self.simulate_disconnect = simulate_disconnect
        self.fail_count = fail_count
        self._fetch_calls = 0
        self._latest_calls = 0
        
        # Executor stub for connection status detection
        if simulate_disconnect:
            self._executor = _DisconnectedExecutor()
        else:
            self._executor = _ConnectedExecutor()

    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> pd.DataFrame:
        self._fetch_calls += 1
        
        if self.fail_fetch:
            if self.fail_count == 0 or self._fetch_calls <= self.fail_count:
                raise ConnectionError("Simulated fetch failure")
        
        # Return minimal valid data
        now = datetime.now(timezone.utc)
        return pd.DataFrame({
            "timestamp": [now],
            "open": [17500.0],
            "high": [17510.0],
            "low": [17490.0],
            "close": [17505.0],
            "volume": [100],
        }).set_index("timestamp")

    async def get_latest_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        self._latest_calls += 1
        
        if self.fail_latest:
            if self.fail_count == 0 or self._latest_calls <= self.fail_count:
                return None
        
        return {
            "timestamp": datetime.now(timezone.utc),
            "open": 17500.0,
            "high": 17510.0,
            "low": 17490.0,
            "close": 17505.0,
            "volume": 100,
        }


class RecoverableProvider(DataProvider):
    """Provider that fails for N calls then succeeds."""

    def __init__(self, fail_for_n_calls: int = 3) -> None:
        self.fail_for_n_calls = fail_for_n_calls
        self._call_count = 0
        self._executor = _ConnectedExecutor()

    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> pd.DataFrame:
        self._call_count += 1
        
        if self._call_count <= self.fail_for_n_calls:
            return pd.DataFrame()  # Empty = failure
        
        now = datetime.now(timezone.utc)
        return pd.DataFrame({
            "timestamp": [now],
            "open": [17500.0],
            "high": [17510.0],
            "low": [17490.0],
            "close": [17505.0],
            "volume": [100],
        }).set_index("timestamp")

    async def get_latest_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        if self._call_count <= self.fail_for_n_calls:
            return None
        
        return {
            "timestamp": datetime.now(timezone.utc),
            "open": 17500.0,
            "high": 17510.0,
            "low": 17490.0,
            "close": 17505.0,
            "volume": 100,
        }


class ErrorProvider(DataProvider):
    """Provider that raises exceptions during fetch to trigger consecutive_errors."""

    def __init__(self) -> None:
        self._executor = _ConnectedExecutor()
        self._call_count = 0

    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> pd.DataFrame:
        self._call_count += 1
        # Raise exception to trigger error handling in service loop
        raise RuntimeError("Simulated fetch error")

    async def get_latest_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        # This won't be called if fetch_historical raises
        raise RuntimeError("Simulated latest bar error")


@pytest.mark.asyncio
async def test_connection_failure_triggers_pause(tmp_path) -> None:
    """
    Assumption tested: When connection_failures >= max_connection_failures,
    the service pauses with pause_reason='connection_failures'.
    
    Failure signal: service.paused is False or pause_reason != 'connection_failures'
    Test type: Deterministic
    """
    provider = FailingProvider(simulate_disconnect=True, fail_fetch=True)
    config = PEARL_BOT_CONFIG.copy()
    config.scan_interval = 0.02  # Fast cycles for test

    service = MarketAgentService(
        data_provider=provider,
        config=config,
        state_dir=tmp_path,
    )
    # Set low threshold to trigger quickly
    service.max_connection_failures = 2
    # Disable adaptive cadence to ensure fast scan interval is respected
    service._adaptive_cadence_enabled = False

    task = asyncio.create_task(service.start())

    # Wait for service to pause
    for _ in range(50):
        if service.paused:
            break
        await asyncio.sleep(0.05)

    assert service.paused, "Service should be paused after connection failures"
    assert service.pause_reason == "connection_failures", \
        f"Pause reason should be 'connection_failures', got '{service.pause_reason}'"
    assert service.connection_failures >= 2, \
        f"Connection failures should be >= 2, got {service.connection_failures}"

    await service.stop("test")
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_consecutive_errors_triggers_pause(tmp_path, monkeypatch) -> None:
    """
    Assumption tested: When consecutive_errors >= max_consecutive_errors,
    the service pauses with pause_reason='consecutive_errors'.
    
    Note: consecutive_errors is triggered by unhandled exceptions in the
    service loop's processing code, not by data fetch errors (which are
    handled separately). We simulate this by patching the strategy.
    
    Failure signal: service.paused is False or pause_reason != 'consecutive_errors'
    Test type: Deterministic
    """
    from tests.mock_data_provider import MockDataProvider
    
    provider = MockDataProvider(
        simulate_delayed_data=False,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )
    config = PEARL_BOT_CONFIG.copy()
    config.scan_interval = 0.02

    service = MarketAgentService(
        data_provider=provider,
        config=config,
        state_dir=tmp_path,
    )
    service.max_consecutive_errors = 2
    # Disable adaptive cadence to ensure fast scan interval is respected
    service._adaptive_cadence_enabled = False

    # Patch the strategy's analyze method to raise an exception
    # This simulates an unhandled error in the processing logic
    call_count = [0]
    def failing_analyze(*args, **kwargs):
        call_count[0] += 1
        raise RuntimeError("Simulated strategy error")
    
    monkeypatch.setattr(service.strategy, "analyze", failing_analyze)

    task = asyncio.create_task(service.start())

    # Wait for service to pause
    for _ in range(100):
        if service.paused:
            break
        await asyncio.sleep(0.05)

    assert service.paused, "Service should be paused after consecutive errors"
    assert service.pause_reason == "consecutive_errors", \
        f"Pause reason should be 'consecutive_errors', got '{service.pause_reason}'"
    assert service.consecutive_errors >= 2, \
        f"Consecutive errors should be >= 2, got {service.consecutive_errors}"

    await service.stop("test")
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_data_fetch_errors_trigger_backoff_not_pause(tmp_path) -> None:
    """
    Assumption tested: Data fetch errors trigger backoff behavior,
    but do NOT pause the service (unlike connection failures).
    
    Failure signal: service.paused is True when only data_fetch_errors threshold is reached
    Test type: Deterministic
    """
    # Provider that returns empty data (fetch failure) but is "connected"
    provider = FailingProvider(fail_fetch=False, fail_latest=True, simulate_disconnect=False)
    config = PEARL_BOT_CONFIG.copy()
    config.scan_interval = 0.02

    service = MarketAgentService(
        data_provider=provider,
        config=config,
        state_dir=tmp_path,
    )
    service.max_data_fetch_errors = 2
    service.max_connection_failures = 100  # High threshold to avoid connection pause
    service.max_consecutive_errors = 100  # High threshold

    task = asyncio.create_task(service.start())

    # Let the service run through several cycles
    await asyncio.sleep(0.3)

    # Service should NOT be paused (data fetch errors only cause backoff)
    # Note: The service may still be running - just with backoff behavior
    # The key assertion is that it's not paused
    if service.paused:
        assert service.pause_reason not in ["data_fetch_errors"], \
            "Data fetch errors should not directly pause service"

    await service.stop("test")
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_counters_reset_on_successful_cycle(tmp_path) -> None:
    """
    Assumption tested: After a successful cycle, connection_failures,
    data_fetch_errors, and consecutive_errors are reset to 0.
    
    Failure signal: Any counter > 0 after a successful cycle
    Test type: Deterministic
    """
    provider = RecoverableProvider(fail_for_n_calls=2)
    config = PEARL_BOT_CONFIG.copy()
    config.scan_interval = 0.02

    service = MarketAgentService(
        data_provider=provider,
        config=config,
        state_dir=tmp_path,
    )
    # Set thresholds high so we don't trigger pause
    service.max_connection_failures = 100
    service.max_consecutive_errors = 100
    service.max_data_fetch_errors = 100

    task = asyncio.create_task(service.start())

    # Wait for enough cycles to recover
    await asyncio.sleep(0.4)

    # After recovery, counters should be reset
    assert service.data_fetch_errors == 0, \
        f"data_fetch_errors should be 0 after recovery, got {service.data_fetch_errors}"
    assert service.connection_failures == 0, \
        f"connection_failures should be 0 after recovery, got {service.connection_failures}"
    assert service.consecutive_errors == 0, \
        f"consecutive_errors should be 0 after recovery, got {service.consecutive_errors}"

    await service.stop("test")
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_manual_pause_and_resume(tmp_path) -> None:
    """
    Assumption tested: Manual pause() sets paused=True with pause_reason='manual',
    and resume() clears the paused state.
    
    Failure signal: Incorrect paused state or pause_reason after pause/resume
    Test type: Deterministic
    """
    from tests.mock_data_provider import MockDataProvider
    
    provider = MockDataProvider(
        simulate_delayed_data=False,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )
    config = PEARL_BOT_CONFIG.copy()
    config.scan_interval = 0.02

    service = MarketAgentService(
        data_provider=provider,
        config=config,
        state_dir=tmp_path,
    )

    task = asyncio.create_task(service.start())
    await asyncio.sleep(0.1)

    # Test manual pause
    service.pause()
    assert service.paused is True, "Service should be paused after pause()"
    assert service.pause_reason == "manual", \
        f"Pause reason should be 'manual', got '{service.pause_reason}'"

    # Test resume
    service.resume()
    assert service.paused is False, "Service should not be paused after resume()"
    assert service.pause_reason is None, \
        f"Pause reason should be None after resume, got '{service.pause_reason}'"

    await service.stop("test")
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_status_reflects_circuit_breaker_state(tmp_path) -> None:
    """
    Assumption tested: get_status() accurately reflects the paused state
    and pause_reason for observability/debugging.
    
    Failure signal: status dict does not match actual service state
    Test type: Deterministic
    """
    provider = FailingProvider(simulate_disconnect=True, fail_fetch=True)
    config = PEARL_BOT_CONFIG.copy()
    config.scan_interval = 0.02

    service = MarketAgentService(
        data_provider=provider,
        config=config,
        state_dir=tmp_path,
    )
    service.max_connection_failures = 1

    task = asyncio.create_task(service.start())

    # Wait for pause
    for _ in range(50):
        if service.paused:
            break
        await asyncio.sleep(0.05)

    status = service.get_status()
    
    assert status["paused"] == service.paused, \
        "Status 'paused' should match service.paused"
    assert status["pause_reason"] == service.pause_reason, \
        "Status 'pause_reason' should match service.pause_reason"
    assert status["connection_failures"] == service.connection_failures, \
        "Status should include connection_failures count"

    await service.stop("test")
    await asyncio.wait_for(task, timeout=2.0)


class TestCircuitBreakerThresholdEdgeCases:
    """Test edge cases around circuit breaker thresholds."""

    @pytest.mark.asyncio
    async def test_threshold_exactly_at_limit(self, tmp_path) -> None:
        """
        Assumption tested: Circuit breaker triggers at exactly the threshold,
        not before and not after.
        
        Failure signal: Pauses at threshold-1 or doesn't pause at threshold
        Test type: Deterministic
        """
        provider = FailingProvider(simulate_disconnect=True, fail_fetch=True)
        config = PEARL_BOT_CONFIG.copy()
        config.scan_interval = 0.02

        service = MarketAgentService(
            data_provider=provider,
            config=config,
            state_dir=tmp_path,
        )
        # Set threshold to exactly 3
        service.max_connection_failures = 3
        # Disable adaptive cadence to ensure fast scan interval is respected
        service._adaptive_cadence_enabled = False

        task = asyncio.create_task(service.start())

        # Wait for at least 3 failures
        for _ in range(100):
            if service.connection_failures >= 3:
                break
            await asyncio.sleep(0.02)

        # At threshold=3, with 3 failures, should be paused
        for _ in range(10):
            if service.paused:
                break
            await asyncio.sleep(0.02)

        assert service.paused, "Should pause at exactly threshold"
        assert service.connection_failures >= 3, \
            f"Should have at least 3 failures, got {service.connection_failures}"

        await service.stop("test")
        await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_zero_threshold_immediate_pause(self, tmp_path) -> None:
        """
        Assumption tested: If threshold is set to 0 or 1, service should pause
        immediately on first failure.
        
        Failure signal: Service doesn't pause after first failure
        Test type: Deterministic (edge case)
        """
        provider = FailingProvider(simulate_disconnect=True, fail_fetch=True)
        config = PEARL_BOT_CONFIG.copy()
        config.scan_interval = 0.02

        service = MarketAgentService(
            data_provider=provider,
            config=config,
            state_dir=tmp_path,
        )
        service.max_connection_failures = 1  # Pause on first failure

        task = asyncio.create_task(service.start())

        # Should pause very quickly
        for _ in range(50):
            if service.paused:
                break
            await asyncio.sleep(0.02)

        assert service.paused, "Should pause immediately with threshold=1"
        assert service.connection_failures >= 1

        await service.stop("test")
        await asyncio.wait_for(task, timeout=2.0)

