"""
Tests for Contract Discovery

Unit tests for futures contract discovery and caching.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, timezone

from pearlalgo.futures.contract_discovery import ContractDiscovery


class TestContractDiscovery:
    """Test ContractDiscovery."""
    
    @pytest.fixture
    def mock_client(self):
        """Mock RESTClient."""
        with patch('pearlalgo.futures.contract_discovery.RESTClient') as mock:
            client = Mock()
            client.futures = Mock()
            mock.return_value = client
            yield client
    
    @pytest.fixture
    def discovery(self, mock_client):
        """Create ContractDiscovery instance."""
        return ContractDiscovery(api_key="test_key", client=mock_client)
    
    @pytest.mark.asyncio
    async def test_get_active_contract(self, discovery, mock_client):
        """Test getting active contract."""
        # Mock contract response
        mock_client.futures.get_contracts.return_value = {
            "status": "OK",
            "results": [
                {
                    "ticker": "ESU5",
                    "expiration_date": "2025-12-20T00:00:00Z",
                },
                {
                    "ticker": "ESZ5",
                    "expiration_date": "2025-12-27T00:00:00Z",
                }
            ]
        }
        
        contract = await discovery.get_active_contract("ES")
        assert contract == "ESU5"  # Should return nearest expiration
    
    @pytest.mark.asyncio
    async def test_contract_caching(self, discovery, mock_client):
        """Test contract caching."""
        # First call - should query API
        mock_client.futures.get_contracts.return_value = {
            "status": "OK",
            "results": [
                {
                    "ticker": "ESU5",
                    "expiration_date": "2025-12-20T00:00:00Z",
                }
            ]
        }
        
        contract1 = await discovery.get_active_contract("ES")
        assert contract1 == "ESU5"
        
        # Second call - should use cache
        contract2 = await discovery.get_active_contract("ES")
        assert contract2 == "ESU5"
        # Should only call API once
        assert mock_client.futures.get_contracts.call_count == 1
    
    @pytest.mark.asyncio
    async def test_refresh_contract_cache(self, discovery, mock_client):
        """Test cache refresh."""
        # Add to cache
        discovery._cache["ES"] = ("ESU5", datetime.now(timezone.utc))
        
        # Mock new contract
        mock_client.futures.get_contracts.return_value = {
            "status": "OK",
            "results": [
                {
                    "ticker": "ESZ5",
                    "expiration_date": "2025-12-27T00:00:00Z",
                }
            ]
        }
        
        await discovery.refresh_contract_cache("ES")
        
        # Should have new contract
        contract = await discovery.get_active_contract("ES")
        assert contract == "ESZ5"
    
    def test_get_contract_expiration(self, discovery):
        """Test parsing contract expiration."""
        # ESU5 = ES + U (Sep) + 5 (2025)
        expiration = discovery.get_contract_expiration("ESU5")
        assert expiration is not None
        assert expiration.year == 2025
        assert expiration.month == 9  # September
    
    def test_get_cache_status(self, discovery):
        """Test cache status."""
        discovery._cache["ES"] = (
            "ESU5",
            datetime.now(timezone.utc) + timedelta(hours=2)
        )
        
        status = discovery.get_cache_status()
        assert "ES" in status
        assert status["ES"]["contract_code"] == "ESU5"
        assert status["ES"]["is_valid"] is True
