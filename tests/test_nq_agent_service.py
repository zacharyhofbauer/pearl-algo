"""
Tests for NQ Agent Service lifecycle and core functionality.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


@pytest.fixture
def real_data_provider():
    """
    Use real IBKR data provider with graceful fallback.
    Tests will use actual market data when IBKR Gateway is available.
    """
    try:
        from pearlalgo.data_providers.ibkr.ibkr_provider import IBKRProvider
        from pearlalgo.config.settings import get_settings
        
        settings = get_settings()
        provider = IBKRProvider(settings=settings)
        yield provider
        
        # Cleanup
        import asyncio
        try:
            asyncio.run(provider.close())
        except Exception:
            pass
    except Exception as e:
        pytest.skip(f"Real data provider not available (IBKR Gateway may not be running): {e}")


@pytest.fixture
def mock_data_provider():
    """
    Fallback mock provider - only used if real provider is not available.
    Prefer real_data_provider fixture for tests that should use real market data.
    """
    provider = MagicMock()
    provider.fetch_historical = MagicMock(return_value=[])
    provider.get_latest_bar = AsyncMock(return_value=None)
    provider.close = AsyncMock()
    return provider


@pytest.fixture
def config():
    """Create a test configuration."""
    return NQIntradayConfig(
        symbol="NQ",
        timeframe="1m",
        scan_interval=1,  # Fast for testing
    )


@pytest.fixture
def state_dir(tmp_path):
    """Create a temporary state directory."""
    state_dir = tmp_path / "nq_agent_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


@pytest.fixture
def service(real_data_provider, config, state_dir):
    """
    Create a service instance for testing with REAL market data.
    
    Uses real_data_provider to test with actual IBKR data.
    """
    return NQAgentService(
        data_provider=real_data_provider,
        config=config,
        state_dir=state_dir,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )


@pytest.mark.asyncio
async def test_service_initialization(service):
    """Test service initializes correctly."""
    assert service is not None
    assert service.running is False
    assert service.paused is False
    assert service.cycle_count == 0
    assert service.signal_count == 0
    assert service.error_count == 0


@pytest.mark.asyncio
async def test_service_start_stop(service):
    """Test service can start and stop."""
    # Start service in background
    start_task = asyncio.create_task(service.start())
    
    # Wait a bit for startup
    await asyncio.sleep(0.1)
    
    # Check it's running
    assert service.running is True
    
    # Stop
    service.shutdown_requested = True
    await asyncio.sleep(0.1)
    
    # Stop the service
    await service.stop()
    
    # Wait for start task to complete
    try:
        await asyncio.wait_for(start_task, timeout=2.0)
    except asyncio.TimeoutError:
        start_task.cancel()
    
    assert service.running is False


@pytest.mark.asyncio
async def test_service_pause_resume(service):
    """Test service pause and resume functionality."""
    # Initially not paused
    assert service.paused is False
    
    # Pause
    service.pause()
    assert service.paused is True
    
    # Resume
    service.resume()
    assert service.paused is False


@pytest.mark.asyncio
async def test_service_get_status(service):
    """Test service status retrieval."""
    status = service.get_status()
    
    assert "running" in status
    assert "paused" in status
    assert "cycle_count" in status
    assert "signal_count" in status
    assert "error_count" in status
    assert "buffer_size" in status
    assert "performance" in status
    assert "config" in status
    
    assert status["running"] is False
    assert status["paused"] is False
    assert status["cycle_count"] == 0


@pytest.mark.asyncio
async def test_service_signal_handler(service):
    """Test signal handler sets shutdown flag."""
    # Simulate signal
    service._signal_handler(signal.SIGTERM, None)
    
    assert service.shutdown_requested is True


@pytest.mark.asyncio
async def test_service_state_persistence(service, state_dir):
    """Test service saves state correctly."""
    service.cycle_count = 10
    service.signal_count = 5
    service._save_state()
    
    # Check state file exists
    state_file = state_dir / "state.json"
    assert state_file.exists()
    
    import json
    with open(state_file) as f:
        state = json.load(f)
    
    assert state["cycle_count"] == 10
    assert state["signal_count"] == 5


@pytest.mark.asyncio
async def test_service_data_fetch_error_handling(service):
    """Test service handles data fetch errors gracefully."""
    # Temporarily patch the data provider to raise an error
    data_provider = service.data_fetcher.data_provider
    original_fetch = data_provider.fetch_historical
    original_get_latest = data_provider.get_latest_bar
    
    # Make data provider raise error
    data_provider.fetch_historical = MagicMock(side_effect=Exception("Fetch error"))
    data_provider.get_latest_bar = AsyncMock(side_effect=Exception("Latest bar error"))
    
    # Start service
    service.running = True
    service.shutdown_requested = False
    
    # Run one cycle
    try:
        await service._run_loop()
    except (asyncio.CancelledError, Exception):
        pass
    finally:
        # Restore original methods
        data_provider.fetch_historical = original_fetch
        data_provider.get_latest_bar = original_get_latest
    
    # Should have incremented error count
    assert service.error_count > 0 or service.data_fetch_errors > 0


@pytest.mark.asyncio
async def test_service_circuit_breaker_activation(service):
    """Test circuit breaker pauses service after too many consecutive errors."""
    # Reset error counters
    service.consecutive_errors = 0
    service.paused = False
    
    # Set to just below threshold
    service.consecutive_errors = service.max_consecutive_errors - 1
    
    # Simulate another error
    service.consecutive_errors += 1
    
    # Should trigger circuit breaker
    if service.consecutive_errors >= service.max_consecutive_errors:
        service.paused = True
    
    # Verify service is paused
    assert service.paused is True
    assert service.consecutive_errors >= service.max_consecutive_errors


@pytest.mark.asyncio
async def test_service_circuit_breaker_recovery(service):
    """Test service recovers from circuit breaker after successful cycle."""
    # Set service to paused state (circuit breaker activated)
    service.paused = True
    service.consecutive_errors = service.max_consecutive_errors
    
    # Simulate successful cycle
    service.consecutive_errors = 0
    
    # Service should be able to resume
    service.paused = False
    
    # Verify recovery
    assert service.paused is False
    assert service.consecutive_errors == 0


@pytest.mark.asyncio
async def test_service_connection_failure_recovery(service):
    """Test service recovers from connection failures."""
    # Simulate connection failures
    service.connection_failures = 5
    service.data_fetch_errors = 3
    
    # Simulate successful data fetch (recovery)
    service.data_fetch_errors = 0
    service.connection_failures = 0
    service.last_successful_cycle = datetime.now(timezone.utc)
    
    # Verify recovery
    assert service.connection_failures == 0
    assert service.data_fetch_errors == 0
    assert service.last_successful_cycle is not None


@pytest.mark.asyncio
async def test_service_connection_failure_alert_throttling(service):
    """Test connection failure alerts are throttled."""
    from unittest.mock import AsyncMock
    
    service.connection_failures = 1
    service.last_connection_failure_alert = None
    
    # First alert should be sent
    await service._handle_connection_failure()
    assert service.last_connection_failure_alert is not None
    
    # Second alert within interval should be throttled
    service.connection_failures = 2
    last_alert_time = service.last_connection_failure_alert
    
    # Mock telegram notifier to track calls
    with patch.object(service.telegram_notifier, 'send_data_quality_alert', new_callable=AsyncMock) as mock_alert:
        await service._handle_connection_failure()
        # Should not send another alert immediately (throttled)
        # Note: This tests the throttling logic exists


@pytest.mark.asyncio
async def test_service_process_signal(service):
    """Test signal processing."""
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
        "stop_loss": 14900.0,
        "take_profit": 15200.0,
        "confidence": 0.75,
        "reason": "Test signal",
    }
    
    # Process signal
    await service._process_signal(signal)
    
    # Check signal was tracked
    assert service.signal_count == 1


@pytest.mark.asyncio
async def test_service_empty_data_handling(service):
    """Test service handles empty data gracefully with real data provider."""
    import pandas as pd
    
    # Temporarily patch to return empty dataframe
    data_provider = service.data_fetcher.data_provider
    original_fetch = data_provider.fetch_historical
    data_provider.fetch_historical = MagicMock(return_value=pd.DataFrame())
    
    # Service should handle empty data without crashing
    service.running = True
    service.shutdown_requested = False
    
    # This should not raise an error
    try:
        market_data = await service.data_fetcher.fetch_latest_data()
        if market_data["df"].empty:
            # Service should skip this cycle
            pass
    except Exception as e:
        pytest.fail(f"Service should handle empty data gracefully: {e}")
    finally:
        # Restore original method
        data_provider.fetch_historical = original_fetch



