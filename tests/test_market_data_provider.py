"""
Test Market Data Provider Interface - Verify interface compliance.
"""

import pytest
from unittest.mock import Mock, AsyncMock

from pearlalgo.data_providers.market_data_provider import MarketDataProvider


class MockProvider(MarketDataProvider):
    """Mock provider for testing interface."""
    
    async def get_underlier_price(self, symbol: str) -> float:
        return 100.0
    
    async def get_option_chain(self, symbol: str, filters=None):
        return []
    
    async def get_option_quotes(self, contracts):
        return []
    
    async def subscribe_realtime(self, symbols):
        while True:
            yield {}
    
    async def validate_connection(self) -> bool:
        return True
    
    async def validate_market_data_entitlements(self):
        return {
            "options_data": True,
            "realtime_quotes": True,
            "historical_data": True,
            "account_type": "paper",
        }


@pytest.mark.asyncio
async def test_mock_provider_implements_interface():
    """Test mock provider implements all required methods."""
    provider = MockProvider()
    
    # Test all methods can be called
    price = await provider.get_underlier_price("SPY")
    assert price == 100.0
    
    options = await provider.get_option_chain("SPY")
    assert isinstance(options, list)
    
    quotes = await provider.get_option_quotes(["SPY 20241220 450 C"])
    assert isinstance(quotes, list)
    
    connected = await provider.validate_connection()
    assert connected is True
    
    entitlements = await provider.validate_market_data_entitlements()
    assert entitlements["account_type"] == "paper"


def test_provider_interface_abstract():
    """Test that MarketDataProvider cannot be instantiated directly."""
    from abc import ABC
    
    # Should raise TypeError when trying to instantiate
    with pytest.raises(TypeError):
        MarketDataProvider()
