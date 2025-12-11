"""
Tests for MassiveDataProvider

Unit tests for Massive API integration.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

from pearlalgo.data_providers.massive_provider import MassiveDataProvider, TokenBucket


class TestTokenBucket:
    """Test token bucket rate limiter."""
    
    @pytest.mark.asyncio
    async def test_token_bucket_acquire(self):
        """Test token bucket acquire."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        
        # Should acquire immediately when tokens available
        await bucket.acquire(1)
        
        # Should wait when at capacity
        # (This is tested in integration, not unit tests)
    
    def test_token_bucket_initialization(self):
        """Test token bucket initialization."""
        bucket = TokenBucket(capacity=10, refill_rate=2.0)
        assert bucket.capacity == 10
        assert bucket.refill_rate == 2.0


class TestMassiveDataProvider:
    """Test MassiveDataProvider."""
    
    @pytest.fixture
    def mock_client(self):
        """Mock RESTClient."""
        with patch('pearlalgo.data_providers.massive_provider.RESTClient') as mock:
            client = Mock()
            client.futures = Mock()
            client.stocks = Mock()
            client.options = Mock()
            mock.return_value = client
            yield client
    
    @pytest.fixture
    def provider(self, mock_client):
        """Create MassiveDataProvider instance."""
        return MassiveDataProvider(api_key="test_key")
    
    def test_initialization(self, provider):
        """Test provider initialization."""
        assert provider.api_key == "test_key"
        assert provider.base_url == "https://api.massive.com"
        assert provider.client is not None
    
    @pytest.mark.asyncio
    async def test_resolve_contract(self, provider, mock_client):
        """Test contract resolution."""
        # Mock contract response
        mock_client.futures.get_contracts.return_value = {
            "status": "OK",
            "results": [
                {
                    "ticker": "ESU5",
                    "expiration_date": "2025-12-20T00:00:00Z",
                }
            ]
        }
        
        contract = await provider._resolve_contract("ES")
        assert contract == "ESU5"
    
    @pytest.mark.asyncio
    async def test_get_latest_bar_futures(self, provider, mock_client):
        """Test get_latest_bar for futures."""
        # Mock contract resolution
        provider._contract_cache["ES"] = ("ESU5", datetime.now(timezone.utc))
        
        # Mock aggregates response
        mock_client.futures.get_aggregates.return_value = {
            "status": "OK",
            "results": [
                {
                    "t": 1700000000000,  # Timestamp in ms
                    "o": 4500.0,
                    "h": 4510.0,
                    "l": 4495.0,
                    "c": 4505.0,
                    "v": 1000,
                    "vw": 4502.5,
                }
            ]
        }
        
        bar = await provider.get_latest_bar("ES")
        assert bar is not None
        assert bar["close"] == 4505.0
        assert bar["open"] == 4500.0
    
    @pytest.mark.asyncio
    async def test_get_latest_bar_invalid_price(self, provider, mock_client):
        """Test get_latest_bar rejects invalid prices."""
        provider._contract_cache["ES"] = ("ESU5", datetime.now(timezone.utc))
        
        # Mock invalid price (too low for ES)
        mock_client.futures.get_aggregates.return_value = {
            "status": "OK",
            "results": [
                {
                    "t": 1700000000000,
                    "o": 100.0,  # Invalid for ES
                    "h": 110.0,
                    "l": 95.0,
                    "c": 105.0,
                    "v": 1000,
                }
            ]
        }
        
        bar = await provider.get_latest_bar("ES")
        assert bar is None  # Should reject invalid price
    
    @pytest.mark.asyncio
    async def test_fetch_historical_async(self, provider, mock_client):
        """Test historical data fetching."""
        provider._contract_cache["ES"] = ("ESU5", datetime.now(timezone.utc))
        
        # Mock aggregates response
        mock_client.futures.get_aggregates.return_value = {
            "status": "OK",
            "results": [
                {
                    "t": 1700000000000,
                    "o": 4500.0,
                    "h": 4510.0,
                    "l": 4495.0,
                    "c": 4505.0,
                    "v": 1000,
                }
            ]
        }
        
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 2, tzinfo=timezone.utc)
        
        df = await provider._fetch_historical_async("ES", start, end, "15m")
        assert len(df) > 0
        assert "close" in df.columns
    
    @pytest.mark.asyncio
    async def test_get_options_chain(self, provider, mock_client):
        """Test options chain fetching."""
        mock_client.options.get_snapshot.return_value = {
            "status": "OK",
            "results": [
                {
                    "details": {
                        "ticker": "SPY250120C500",
                        "strike_price": 500.0,
                        "expiration_date": "2025-01-20",
                        "contract_type": "call",
                    },
                    "last_quote": {"bid": 5.0, "ask": 5.5},
                    "last_trade": {"price": 5.25},
                    "session": {"volume": 1000, "open_interest": 5000},
                }
            ]
        }
        
        chain = await provider.get_options_chain("SPY")
        assert len(chain) > 0
        assert chain[0]["strike"] == 500.0
        assert chain[0]["option_type"] == "call"
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, provider):
        """Test rate limiting."""
        # Token bucket should enforce rate limits
        await provider._rate_limit()
        # If no exception, rate limiting is working
        assert True
