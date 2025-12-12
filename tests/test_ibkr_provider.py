"""
Test IBKR Provider - Basic connection and data fetching tests.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from pearlalgo.data_providers.ibkr.ibkr_provider import IBKRProvider
from pearlalgo.config.settings import get_settings


@pytest.mark.asyncio
async def test_ibkr_provider_initialization():
    """Test IBKR provider can be initialized."""
    settings = get_settings()
    provider = IBKRProvider(
        settings=settings,
        host="127.0.0.1",
        port=4002,
        client_id=1,
    )
    
    assert provider is not None
    assert provider.host == "127.0.0.1"
    assert provider.port == 4002
    assert provider.client_id == 1
    
    # Cleanup
    await provider.close()


@pytest.mark.asyncio
async def test_ibkr_provider_implements_interface():
    """Test IBKR provider implements MarketDataProvider interface."""
    from pearlalgo.data_providers.market_data_provider import MarketDataProvider
    
    settings = get_settings()
    provider = IBKRProvider(settings=settings)
    
    # Check it implements the interface
    assert isinstance(provider, MarketDataProvider)
    
    # Cleanup
    await provider.close()


def test_market_data_provider_interface():
    """Test MarketDataProvider interface is properly defined."""
    from abc import ABC
    from pearlalgo.data_providers.market_data_provider import MarketDataProvider
    
    # Check it's an abstract base class
    assert issubclass(MarketDataProvider, ABC)
    
    # Check required methods exist
    assert hasattr(MarketDataProvider, "get_underlier_price")
    assert hasattr(MarketDataProvider, "get_option_chain")
    assert hasattr(MarketDataProvider, "get_option_quotes")
    assert hasattr(MarketDataProvider, "subscribe_realtime")
    assert hasattr(MarketDataProvider, "validate_connection")
    assert hasattr(MarketDataProvider, "validate_market_data_entitlements")
