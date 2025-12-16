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
async def test_ibkr_provider_implements_data_provider():
    """Test IBKR provider implements DataProvider interface."""
    from pearlalgo.data_providers.base import DataProvider
    
    settings = get_settings()
    provider = IBKRProvider(settings=settings)
    
    # Check it implements the base DataProvider interface
    assert isinstance(provider, DataProvider)
    
    # Check it has required methods
    assert hasattr(provider, "fetch_historical")
    assert hasattr(provider, "get_latest_bar")
    assert hasattr(provider, "close")
    
    # Cleanup
    await provider.close()
