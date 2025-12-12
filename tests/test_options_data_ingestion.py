"""
Tests for Options Data Ingestion
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, date

from pearlalgo.data_providers.


@pytest.fixture
def mock_
    """Mock ."""
    client = MagicMock()
    
    # Mock options chain iterator
    mock_option = MagicMock()
    mock_option.details = MagicMock()
    mock_option.details.ticker = "QQQ240119C00400"
    mock_option.details.strike_price = 400.0
    mock_option.details.expiration_date = "2024-01-19T00:00:00Z"
    mock_option.details.contract_type = "call"
    mock_option.last_quote = MagicMock()
    mock_option.last_quote.bid = 2.50
    mock_option.last_quote.ask = 2.60
    mock_option.last_trade = MagicMock()
    mock_option.last_trade.price = 2.55
    mock_option.session = MagicMock()
    mock_option.session.volume = 1500
    mock_option.session.open_interest = 5000
    
    client.list_snapshot_options_chain = MagicMock(return_value=iter([mock_option]))
    
    return client


@pytest.mark.asyncio
async def test_get_options_chain_basic(mock_
    """Test basic options chain retrieval."""
    provider = 
    provider.client = mock_
    
    options = await provider.get_options_chain("QQQ")
    
    assert len(options) > 0
    assert options[0]["strike"] == 400.0
    assert options[0]["option_type"] == "call"


@pytest.mark.asyncio
async def test_get_options_chain_filtered_by_dte(mock_
    """Test options chain filtering by DTE."""
    provider = 
    provider.client = mock_
    
    # Test intraday filtering (0-7 DTE)
    options = await provider.get_options_chain(
        "QQQ",
        min_dte=0,
        max_dte=7,
    )
    
    # Should filter by DTE
    for opt in options:
        if "dte" in opt:
            assert 0 <= opt["dte"] <= 7


@pytest.mark.asyncio
async def test_get_options_chain_filtered_by_volume(mock_
    """Test options chain filtering by volume."""
    provider = 
    provider.client = mock_
    
    options = await provider.get_options_chain(
        "QQQ",
        min_volume=1000,
    )
    
    # All options should have volume >= 1000
    for opt in options:
        assert opt.get("volume", 0) >= 1000


@pytest.mark.asyncio
async def test_get_options_chain_filtered_by_strike(mock_
    """Test options chain filtering by strike proximity."""
    provider = 
    provider.client = mock_
    
    underlying_price = 400.0
    
    options = await provider.get_options_chain(
        "QQQ",
        strike_proximity_pct=0.10,  # Within 10%
        underlying_price=underlying_price,
    )
    
    # All options should be within 10% of underlying
    for opt in options:
        if opt.get("strike"):
            strike_diff_pct = abs(opt["strike"] - underlying_price) / underlying_price
            assert strike_diff_pct <= 0.10


@pytest.mark.asyncio
async def test_get_options_chain_filtered_intraday(mock_
    """Test get_options_chain_filtered for intraday mode."""
    provider = 
    provider.client = mock_
    
    options = await provider.get_options_chain_filtered(
        "QQQ",
        mode="intraday",
        underlying_price=400.0,
    )
    
    # Should return filtered options for intraday
    assert isinstance(options, list)


@pytest.mark.asyncio
async def test_get_options_chain_filtered_swing(mock_
    """Test get_options_chain_filtered for swing mode."""
    provider = 
    provider.client = mock_
    
    options = await provider.get_options_chain_filtered(
        "QQQ",
        mode="swing",
        underlying_price=400.0,
    )
    
    # Should return filtered options for swing
    assert isinstance(options, list)


@pytest.mark.asyncio
async def test_get_stock_data(mock_
    """Test stock data retrieval."""
    # Mock stock aggregates
    mock_bar = MagicMock()
    mock_bar.close = 400.0
    mock_bar.open = 399.0
    mock_bar.high = 401.0
    mock_bar.low = 398.0
    mock_bar.volume = 1000000
    mock_bar.timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    mock_.get_previous_close_agg = MagicMock(return_value=mock_bar)
    
    provider = 
    provider.client = mock_
    
    bar = await provider.get_latest_bar("QQQ")
    
    assert bar is not None
    assert bar["close"] == 400.0
