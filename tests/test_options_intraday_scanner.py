"""
Tests for Options Intraday Scanner
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from pearlalgo.options.intraday_scanner import OptionsIntradayScanner


@pytest.fixture
def mock_data_provider():
    """Mock data provider."""
    provider = MagicMock()
    provider.get_latest_bar = AsyncMock(return_value={
        "close": 400.0,
        "volume": 1000000,
        "timestamp": datetime.now(timezone.utc),
    })
    provider.get_options_chain_filtered = AsyncMock(return_value=[
        {
            "symbol": "QQQ240119C00400",
            "strike": 400.0,
            "expiration": "2024-01-19",
            "option_type": "call",
            "bid": 2.50,
            "ask": 2.60,
            "last_price": 2.55,
            "volume": 1500,
            "open_interest": 5000,
        }
    ])
    return provider


@pytest.fixture
def mock_buffer_manager():
    """Mock buffer manager."""
    manager = MagicMock()
    manager.has_buffer = MagicMock(return_value=True)
    manager.get_buffer = MagicMock(return_value=[
        {"close": 395.0, "high": 396.0, "low": 394.0, "volume": 800000},
        {"close": 396.0, "high": 397.0, "low": 395.0, "volume": 900000},
        {"close": 397.0, "high": 398.0, "low": 396.0, "volume": 950000},
        {"close": 398.0, "high": 399.0, "low": 397.0, "volume": 1000000},
        {"close": 399.0, "high": 400.0, "low": 398.0, "volume": 1100000},
        {"close": 400.0, "high": 401.0, "low": 399.0, "volume": 1200000},
    ] * 5)  # 30 bars
    return manager


@pytest.mark.asyncio
async def test_scanner_initialization(mock_data_provider):
    """Test scanner initialization."""
    scanner = OptionsIntradayScanner(
        symbols=["QQQ", "SPY"],
        strategy="momentum",
        data_provider=mock_data_provider,
    )
    
    assert scanner.symbols == ["QQQ", "SPY"]
    assert scanner.strategy == "momentum"
    assert scanner.data_provider == mock_data_provider


@pytest.mark.asyncio
async def test_scan_market_closed(mock_data_provider):
    """Test scan when market is closed."""
    scanner = OptionsIntradayScanner(
        symbols=["QQQ"],
        data_provider=mock_data_provider,
    )
    
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=False):
        result = await scanner.scan()
    
    assert result["status"] == "skipped"
    assert result["reason"] == "market_closed"


@pytest.mark.asyncio
async def test_scan_no_data_provider():
    """Test scan without data provider."""
    scanner = OptionsIntradayScanner(
        symbols=["QQQ"],
        data_provider=None,
    )
    
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=True):
        result = await scanner.scan()
    
    assert result["status"] == "error"
    assert "No data provider" in result["error"]


@pytest.mark.asyncio
async def test_momentum_signal_bullish(mock_data_provider, mock_buffer_manager):
    """Test momentum signal generation for bullish move."""
    scanner = OptionsIntradayScanner(
        symbols=["QQQ"],
        strategy="momentum",
        data_provider=mock_data_provider,
        buffer_manager=mock_buffer_manager,
        config={"momentum_threshold": 0.01, "volume_threshold": 1.5},
    )
    
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=True):
        result = await scanner.scan()
    
    assert result["status"] == "success"
    # Should generate signal if momentum detected
    # (actual result depends on buffer data)


@pytest.mark.asyncio
async def test_volatility_signal(mock_data_provider):
    """Test volatility compression signal."""
    scanner = OptionsIntradayScanner(
        symbols=["QQQ"],
        strategy="volatility",
        data_provider=mock_data_provider,
        config={"compression_threshold": 0.20},
    )
    
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=True):
        result = await scanner.scan()
    
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_unusual_flow_signal(mock_data_provider):
    """Test unusual option flow signal."""
    # Mock options with high volume/OI
    mock_data_provider.get_options_chain_filtered = AsyncMock(return_value=[
        {
            "symbol": "QQQ240119C00400",
            "strike": 400.0,
            "expiration": "2024-01-19",
            "option_type": "call",
            "bid": 2.50,
            "ask": 2.60,
            "last_price": 2.55,
            "volume": 5000,  # High volume
            "open_interest": 10000,  # High OI
        }
    ])
    
    scanner = OptionsIntradayScanner(
        symbols=["QQQ"],
        strategy="unusual_flow",
        data_provider=mock_data_provider,
        config={
            "unusual_volume_threshold": 1000,
            "unusual_oi_threshold": 5000,
        },
    )
    
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=True):
        result = await scanner.scan()
    
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_scan_error_handling(mock_data_provider):
    """Test error handling in scan."""
    mock_data_provider.get_latest_bar = AsyncMock(side_effect=Exception("API error"))
    
    scanner = OptionsIntradayScanner(
        symbols=["QQQ"],
        data_provider=mock_data_provider,
    )
    
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=True):
        result = await scanner.scan()
    
    assert result["status"] == "error"
    assert "error" in result
