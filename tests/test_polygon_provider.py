"""
Comprehensive tests for Polygon.io data provider.

Includes unit tests, mocked tests, and integration test scaffolding.
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
import asyncio

from pearlalgo.data_providers.polygon_provider import PolygonDataProvider
from pearlalgo.data_providers.polygon_config import PolygonConfig
from pearlalgo.data_providers.polygon_health import PolygonHealthMonitor


class TestPolygonConfig:
    """Test Polygon configuration."""
    
    def test_config_from_api_key(self):
        """Test creating config from API key."""
        config = PolygonConfig(api_key="test_key_123")
        assert config.api_key == "test_key_123"
        assert config.base_url == "https://api.polygon.io"
        assert config.rate_limit_delay == 0.25
    
    def test_config_custom_settings(self):
        """Test config with custom settings."""
        config = PolygonConfig(
            api_key="test_key",
            rate_limit_delay=0.5,
            max_retries=5,
            requests_per_minute=100
        )
        assert config.rate_limit_delay == 0.5
        assert config.max_retries == 5
        assert config.requests_per_minute == 100
    
    @patch.dict("os.environ", {"POLYGON_API_KEY": "env_key_123"})
    def test_config_from_env(self):
        """Test creating config from environment variables."""
        config = PolygonConfig.from_env()
        assert config.api_key == "env_key_123"
    
    @patch.dict("os.environ", {}, clear=True)
    def test_config_from_env_missing_key(self):
        """Test config from env raises error when key missing."""
        with pytest.raises(ValueError, match="Polygon API key required"):
            PolygonConfig.from_env()


class TestPolygonProviderUnit:
    """Unit tests for Polygon provider (mocked)."""
    
    @pytest.fixture
    def provider(self):
        """Create Polygon provider with test API key."""
        return PolygonDataProvider(api_key="test_key_123")
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, provider):
        """Test rate limiting logic."""
        import time
        
        start = time.time()
        await provider._rate_limit()
        await provider._rate_limit()
        elapsed = time.time() - start
        
        # Should have at least rate_limit_delay between calls
        assert elapsed >= provider.rate_limit_delay * 0.9  # Allow small margin
    
    @pytest.mark.asyncio
    async def test_session_management(self, provider):
        """Test session creation and reuse."""
        session1 = await provider._get_session()
        session2 = await provider._get_session()
        
        # Should reuse same session
        assert session1 is session2
        
        # Close and verify new session created
        await provider.close()
        session3 = await provider._get_session()
        assert session3 is not session1
    
    @pytest.mark.asyncio
    async def test_get_latest_bar_success(self, provider):
        """Test successful get_latest_bar call."""
        mock_response = {
            "status": "OK",
            "resultsCount": 1,
            "results": [{
                "t": 1609459200000,  # timestamp in ms
                "o": 100.0,
                "h": 105.0,
                "l": 95.0,
                "c": 102.0,
                "v": 1000,
                "vw": 101.5
            }]
        }
        
        # Create proper async context manager mock
        mock_response_obj = AsyncMock()
        mock_response_obj.status = 200
        mock_response_obj.json = AsyncMock(return_value=mock_response)
        
        # Create async context manager for session.get()
        mock_get_context = AsyncMock()
        mock_get_context.__aenter__ = AsyncMock(return_value=mock_response_obj)
        mock_get_context.__aexit__ = AsyncMock(return_value=None)
        
        mock_session_obj = AsyncMock()
        mock_session_obj.get = MagicMock(return_value=mock_get_context)
        
        with patch.object(provider, '_get_session', return_value=mock_session_obj):
            result = await provider._get_latest_bar_impl("AAPL")
            
            assert result is not None
            assert result["close"] == 102.0
            assert result["volume"] == 1000
            assert "timestamp" in result
    
    @pytest.mark.asyncio
    async def test_get_latest_bar_rate_limit(self, provider):
        """Test handling of rate limit (429) response."""
        # Create proper async context manager mock
        mock_response_obj = AsyncMock()
        mock_response_obj.status = 429
        
        mock_get_context = AsyncMock()
        mock_get_context.__aenter__ = AsyncMock(return_value=mock_response_obj)
        mock_get_context.__aexit__ = AsyncMock(return_value=None)
        
        mock_session_obj = AsyncMock()
        mock_session_obj.get = MagicMock(return_value=mock_get_context)
        
        with patch.object(provider, '_get_session', return_value=mock_session_obj):
            result = await provider._get_latest_bar_impl("AAPL")
            
            # Should return None on rate limit
            assert result is None
    
    @pytest.mark.asyncio
    async def test_get_latest_bar_unauthorized(self, provider):
        """Test handling of unauthorized (401) response."""
        # Create proper async context manager mock
        mock_response_obj = AsyncMock()
        mock_response_obj.status = 401
        
        mock_get_context = AsyncMock()
        mock_get_context.__aenter__ = AsyncMock(return_value=mock_response_obj)
        mock_get_context.__aexit__ = AsyncMock(return_value=None)
        
        mock_session_obj = AsyncMock()
        mock_session_obj.get = MagicMock(return_value=mock_get_context)
        
        with patch.object(provider, '_get_session', return_value=mock_session_obj):
            result = await provider._get_latest_bar_impl("AAPL")
            
            # Should return None on unauthorized
            assert result is None
    
    @pytest.mark.asyncio
    async def test_fetch_historical_chunking(self, provider):
        """Test historical data fetching with date chunking."""
        # Mock successful responses
        mock_response_data = {
            "status": "OK",
            "results": [
                {
                    "t": int((datetime.now(timezone.utc) - timedelta(days=i)).timestamp() * 1000),
                    "o": 100.0 + i,
                    "h": 105.0 + i,
                    "l": 95.0 + i,
                    "c": 102.0 + i,
                    "v": 1000
                }
                for i in range(5)
            ]
        }
        
        # Create proper async context manager mock
        mock_response_obj = AsyncMock()
        mock_response_obj.status = 200
        mock_response_obj.json = AsyncMock(return_value=mock_response_data)
        
        mock_get_context = AsyncMock()
        mock_get_context.__aenter__ = AsyncMock(return_value=mock_response_obj)
        mock_get_context.__aexit__ = AsyncMock(return_value=None)
        
        mock_session_obj = AsyncMock()
        mock_session_obj.get = MagicMock(return_value=mock_get_context)
        
        with patch.object(provider, '_get_session', return_value=mock_session_obj):
            start = datetime.now(timezone.utc) - timedelta(days=60)
            end = datetime.now(timezone.utc)
            
            df = await provider._fetch_historical_async("AAPL", start=start, end=end, timeframe="1d")
            
            # Should have data (even if mocked)
            assert isinstance(df, pd.DataFrame)


class TestPolygonHealthMonitor:
    """Test Polygon health monitoring."""
    
    def test_health_monitor_initialization(self):
        """Test health monitor initialization."""
        monitor = PolygonHealthMonitor()
        assert monitor.metrics.total_requests == 0
        assert monitor.metrics.successful_requests == 0
    
    def test_record_successful_request(self):
        """Test recording successful request."""
        monitor = PolygonHealthMonitor()
        monitor.record_request(duration=0.5, success=True)
        
        assert monitor.metrics.total_requests == 1
        assert monitor.metrics.successful_requests == 1
        assert monitor.metrics.failed_requests == 0
        assert monitor.metrics.success_rate() == 1.0
    
    def test_record_failed_request(self):
        """Test recording failed request."""
        monitor = PolygonHealthMonitor()
        monitor.record_request(duration=0.5, success=False, error="Timeout")
        
        assert monitor.metrics.total_requests == 1
        assert monitor.metrics.successful_requests == 0
        assert monitor.metrics.failed_requests == 1
        assert monitor.metrics.success_rate() == 0.0
        assert monitor.metrics.last_error == "Timeout"
    
    def test_record_rate_limit(self):
        """Test recording rate limit hit."""
        monitor = PolygonHealthMonitor()
        monitor.record_rate_limit()
        
        assert monitor.metrics.rate_limit_hits == 1
    
    def test_health_status(self):
        """Test health status calculation."""
        monitor = PolygonHealthMonitor()
        
        # Initially healthy (no requests)
        assert monitor.is_healthy() is True
        
        # Record some failures
        for _ in range(6):
            monitor.record_request(duration=0.5, success=False)
        
        # Should be unhealthy with < 50% success rate
        assert monitor.is_healthy() is False
    
    def test_health_metrics_dict(self):
        """Test converting health metrics to dictionary."""
        monitor = PolygonHealthMonitor()
        monitor.record_request(duration=0.5, success=True)
        
        health_dict = monitor.get_health()
        
        assert "total_requests" in health_dict
        assert "success_rate" in health_dict
        assert "is_healthy" in health_dict
        assert health_dict["is_healthy"] is True


class TestPolygonProviderIntegration:
    """Integration tests for Polygon provider (requires API key)."""
    
    @pytest.fixture
    def api_key(self):
        """Get API key from environment or skip test."""
        import os
        key = os.getenv("POLYGON_API_KEY")
        if not key:
            pytest.skip("POLYGON_API_KEY not set - skipping integration test")
        return key
    
    @pytest.fixture
    def provider(self, api_key):
        """Create Polygon provider with real API key."""
        return PolygonDataProvider(api_key=api_key)
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_get_latest_bar_real(self, provider):
        """Test getting latest bar with real API (integration test)."""
        result = await provider.get_latest_bar("AAPL")
        
        # Should return data or None (depending on API key validity)
        assert result is None or isinstance(result, dict)
        
        if result:
            assert "timestamp" in result
            assert "close" in result
            assert "volume" in result
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_fetch_historical_real(self, provider):
        """Test fetching historical data with real API (integration test)."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        
        df = provider.fetch_historical(
            symbol="AAPL",
            start=start,
            end=end,
            timeframe="1d"
        )
        
        # Should return DataFrame (may be empty if API key invalid)
        assert isinstance(df, pd.DataFrame)
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_circuit_breaker_real(self, provider):
        """Test circuit breaker with real API calls."""
        # Make multiple calls to test circuit breaker
        for _ in range(3):
            try:
                await provider.get_latest_bar("AAPL")
            except Exception:
                pass
        
        # Circuit breaker should still be functional
        assert provider.circuit_breaker is not None


class TestPolygonProviderErrorHandling:
    """Test error handling and edge cases."""
    
    @pytest.fixture
    def provider(self):
        """Create Polygon provider."""
        return PolygonDataProvider(api_key="test_key")
    
    @pytest.mark.asyncio
    async def test_network_error_handling(self, provider):
        """Test handling of network errors."""
        with patch.object(provider, '_get_session', side_effect=aiohttp.ClientError("Network error")):
            result = await provider.get_latest_bar("AAPL")
            
            # Should return None on network error
            assert result is None
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, provider):
        """Test handling of timeouts."""
        with patch.object(provider, '_get_session', side_effect=asyncio.TimeoutError()):
            result = await provider.get_latest_bar("AAPL")
            
            # Should return None on timeout
            assert result is None
    
    @pytest.mark.asyncio
    async def test_invalid_json_response(self, provider):
        """Test handling of invalid JSON response."""
        # Create proper async context manager mock
        mock_response_obj = AsyncMock()
        mock_response_obj.status = 200
        mock_response_obj.json = AsyncMock(side_effect=ValueError("Invalid JSON"))
        
        mock_get_context = AsyncMock()
        mock_get_context.__aenter__ = AsyncMock(return_value=mock_response_obj)
        mock_get_context.__aexit__ = AsyncMock(return_value=None)
        
        mock_session_obj = AsyncMock()
        mock_session_obj.get = MagicMock(return_value=mock_get_context)
        
        with patch.object(provider, '_get_session', return_value=mock_session_obj):
            result = await provider.get_latest_bar("AAPL")
            
            # Should handle gracefully
            assert result is None or isinstance(result, dict)

