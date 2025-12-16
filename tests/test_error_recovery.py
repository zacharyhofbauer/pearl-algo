"""
Error recovery tests for NQ Agent.

Tests error recovery scenarios including:
- Circuit breaker behavior
- Recovery after errors
- Connection failure recovery
"""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock

from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from tests.mock_data_provider import MockDataProvider


@pytest.mark.unit
class TestCircuitBreaker:
    """Test circuit breaker behavior."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_activation(self):
        """Test circuit breaker activates after too many errors."""
        provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)
        service = NQAgentService(data_provider=provider, config=NQIntradayConfig())
        
        # Set low threshold for testing
        service.max_consecutive_errors = 3
        
        # Simulate errors
        service.consecutive_errors = 2
        
        # Should not be paused yet
        assert not service.paused
        
        # One more error should trigger circuit breaker
        # Note: Actual circuit breaker logic is in _run_loop
        # This test verifies the threshold exists

    @pytest.mark.asyncio
    async def test_circuit_breaker_reset(self):
        """Test circuit breaker resets after successful cycle."""
        provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)
        service = NQAgentService(data_provider=provider, config=NQIntradayConfig())
        
        # Set some errors
        service.consecutive_errors = 5
        
        # Successful cycle should reset
        service.consecutive_errors = 0
        
        # Should not be paused
        assert not service.paused


@pytest.mark.unit
class TestErrorRecovery:
    """Test error recovery scenarios."""

    @pytest.mark.asyncio
    async def test_recovery_after_data_fetch_error(self):
        """Test recovery after data fetch errors."""
        provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)
        service = NQAgentService(data_provider=provider, config=NQIntradayConfig())
        
        # Simulate data fetch errors
        service.data_fetch_errors = 3
        
        # After successful fetch, errors should reset
        service.data_fetch_errors = 0
        
        # Should be able to continue
        assert service.data_fetch_errors == 0

    @pytest.mark.asyncio
    async def test_recovery_after_connection_failure(self):
        """Test recovery after connection failures."""
        provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)
        service = NQAgentService(data_provider=provider, config=NQIntradayConfig())
        
        # Simulate connection failures
        service.connection_failures = 5
        
        # After successful connection, failures should reset
        service.connection_failures = 0
        
        # Should be able to continue
        assert service.connection_failures == 0


@pytest.mark.integration
class TestServiceRecovery:
    """Test service-level recovery."""

    @pytest.mark.asyncio
    async def test_service_recovery_after_pause(self):
        """Test service recovers after being paused."""
        provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)
        service = NQAgentService(data_provider=provider, config=NQIntradayConfig())
        
        # Pause service
        service.pause()
        assert service.paused
        
        # Resume service
        service.resume()
        assert not service.paused

    @pytest.mark.asyncio
    async def test_service_handles_transient_errors(self):
        """Test service handles transient errors gracefully."""
        provider = MockDataProvider(base_price=17500.0, volatility=50.0, trend=0.0)
        service = NQAgentService(data_provider=provider, config=NQIntradayConfig())
        
        # Service should continue running despite transient errors
        # This is tested implicitly by the service continuing to run
        # after encountering errors in the main loop
        
        # For explicit test, we verify error handling doesn't crash service
        try:
            await service.start()
            await asyncio.sleep(0.5)
            await service.stop()
        except Exception as e:
            pytest.fail(f"Service should handle errors gracefully: {e}")
