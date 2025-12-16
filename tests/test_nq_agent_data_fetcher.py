"""
Tests for NQ Agent Data Fetcher.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


@pytest.fixture
def mock_data_provider():
    """Create a mock data provider."""
    provider = MagicMock()
    
    # Create sample historical data
    dates = pd.date_range(
        start=datetime.now(timezone.utc) - timedelta(hours=2),
        end=datetime.now(timezone.utc),
        freq="1min",
    )[:100]
    
    df = pd.DataFrame({
        "open": [15000 + i * 0.1 for i in range(len(dates))],
        "high": [15010 + i * 0.1 for i in range(len(dates))],
        "low": [14990 + i * 0.1 for i in range(len(dates))],
        "close": [15005 + i * 0.1 for i in range(len(dates))],
        "volume": [1000 + i for i in range(len(dates))],
    }, index=dates)
    
    provider.fetch_historical = MagicMock(return_value=df)
    provider.get_latest_bar = AsyncMock(return_value={
        "timestamp": datetime.now(timezone.utc),
        "open": 15000.0,
        "high": 15010.0,
        "low": 14990.0,
        "close": 15005.0,
        "volume": 1000,
    })
    
    return provider


@pytest.fixture
def config():
    """Create a test configuration."""
    return NQIntradayConfig(
        symbol="NQ",
        timeframe="1m",
    )


@pytest.fixture
def fetcher(real_data_provider, config):
    """
    Create a data fetcher instance with REAL market data.
    
    Uses real_data_provider to test with actual IBKR data.
    """
    return NQAgentDataFetcher(real_data_provider, config)


@pytest.mark.asyncio
async def test_fetcher_initialization(fetcher):
    """Test data fetcher initializes correctly."""
    assert fetcher is not None
    assert fetcher.config.symbol == "NQ"
    assert fetcher._data_buffer is None or fetcher._data_buffer.empty


@pytest.mark.asyncio
async def test_fetcher_fetch_latest_data(fetcher):
    """Test fetching latest data with real IBKR provider."""
    # Wait for connection with timeout
    import asyncio
    max_wait = 30.0  # Maximum wait time for connection
    start_time = asyncio.get_event_loop().time()
    
    # Try to fetch data, with timeout handling
    try:
        result = await asyncio.wait_for(fetcher.fetch_latest_data(), timeout=max_wait)
    except asyncio.TimeoutError:
        pytest.skip(f"IBKR Gateway connection timed out after {max_wait}s - Gateway may be busy or not ready")
    
    assert "df" in result
    assert "latest_bar" in result
    assert isinstance(result["df"], pd.DataFrame)
    # latest_bar might be None if no data available, which is OK
    if result["latest_bar"] is not None:
        assert "timestamp" in result["latest_bar"]
        assert "close" in result["latest_bar"]


@pytest.mark.asyncio
async def test_fetcher_buffer_management(fetcher):
    """Test data buffer management."""
    # Fetch data multiple times
    for _ in range(5):
        await fetcher.fetch_latest_data()
    
    # Check buffer size is limited
    buffer_size = fetcher.get_buffer_size()
    assert buffer_size <= fetcher._buffer_size
    assert buffer_size > 0


@pytest.mark.asyncio
async def test_fetcher_empty_data_handling(fetcher):
    """Test handling of empty data with real provider."""
    # Temporarily patch to return empty data
    original_fetch = fetcher.data_provider.fetch_historical
    original_get_latest = fetcher.data_provider.get_latest_bar
    
    fetcher.data_provider.fetch_historical = MagicMock(return_value=pd.DataFrame())
    fetcher.data_provider.get_latest_bar = AsyncMock(return_value=None)
    
    try:
        result = await fetcher.fetch_latest_data()
        
        assert result["df"].empty
        assert result["latest_bar"] is None
    finally:
        # Restore original methods
        fetcher.data_provider.fetch_historical = original_fetch
        fetcher.data_provider.get_latest_bar = original_get_latest


@pytest.mark.asyncio
async def test_fetcher_stale_data_detection(fetcher):
    """Test stale data detection."""
    # Create stale data (old timestamp)
    stale_timestamp = datetime.now(timezone.utc) - timedelta(minutes=15)
    
    dates = pd.date_range(
        start=stale_timestamp - timedelta(hours=1),
        end=stale_timestamp,
        freq="1min",
    )[:50]
    
    df = pd.DataFrame({
        "open": [15000] * len(dates),
        "high": [15010] * len(dates),
        "low": [14990] * len(dates),
        "close": [15005] * len(dates),
        "volume": [1000] * len(dates),
        "timestamp": dates,
    }, index=dates)
    
    # Temporarily patch for stale data test
    original_fetch = fetcher.data_provider.fetch_historical
    fetcher.data_provider.fetch_historical = MagicMock(return_value=df)
    
    # Fetch should complete but may log warning
    try:
        result = await fetcher.fetch_latest_data()
        assert "df" in result
    finally:
        # Restore original method
        fetcher.data_provider.fetch_historical = original_fetch


@pytest.mark.asyncio
async def test_fetcher_missing_values_handling(fetcher):
    """Test handling of missing values in data."""
    # Create data with missing values
    dates = pd.date_range(
        start=datetime.now(timezone.utc) - timedelta(hours=1),
        end=datetime.now(timezone.utc),
        freq="1min",
    )[:50]
    
    df = pd.DataFrame({
        "open": [15000.0 if i % 2 == 0 else None for i in range(len(dates))],
        "high": [15010.0] * len(dates),
        "low": [14990.0] * len(dates),
        "close": [15005.0] * len(dates),
        "volume": [1000] * len(dates),
    }, index=dates)
    
    # Temporarily patch for missing values test
    original_fetch = fetcher.data_provider.fetch_historical
    fetcher.data_provider.fetch_historical = MagicMock(return_value=df)
    
    # Should handle missing values gracefully
    try:
        result = await fetcher.fetch_latest_data()
        assert "df" in result
    finally:
        # Restore original method
        fetcher.data_provider.fetch_historical = original_fetch


@pytest.mark.asyncio
async def test_fetcher_error_handling(fetcher):
    """Test error handling in data fetcher."""
    # Make provider raise error
    # Temporarily patch to raise errors
    original_fetch = fetcher.data_provider.fetch_historical
    original_get_latest = fetcher.data_provider.get_latest_bar
    
    fetcher.data_provider.fetch_historical = MagicMock(side_effect=Exception("Fetch error"))
    fetcher.data_provider.get_latest_bar = AsyncMock(side_effect=Exception("Latest bar error"))
    
    # Should return empty data instead of raising
    try:
        result = await fetcher.fetch_latest_data()
        
        assert result["df"].empty
        assert result["latest_bar"] is None
    finally:
        # Restore original methods
        fetcher.data_provider.fetch_historical = original_fetch
        fetcher.data_provider.get_latest_bar = original_get_latest


@pytest.mark.asyncio
async def test_fetcher_historical_fallback(fetcher):
    """Test fallback to historical data when latest_bar unavailable."""
    # Mock get_latest_bar to return None
    # Temporarily patch for fallback test
    original_get_latest = fetcher.data_provider.get_latest_bar
    fetcher.data_provider.get_latest_bar = AsyncMock(return_value=None)
    
    # Should use last row from historical data
    try:
        result = await fetcher.fetch_latest_data()
        
        # Should still have latest_bar from historical data
        assert result["latest_bar"] is not None
    finally:
        # Restore original method
        fetcher.data_provider.get_latest_bar = original_get_latest
    assert "timestamp" in result["latest_bar"]


@pytest.mark.asyncio
async def test_fetcher_get_buffer_size(fetcher):
    """Test buffer size retrieval."""
    # Initially empty
    size = fetcher.get_buffer_size()
    assert size == 0
    
    # After fetching, should have data
    await fetcher.fetch_latest_data()
    size = fetcher.get_buffer_size()
    assert size > 0


@pytest.mark.asyncio
async def test_fetcher_data_quality_alert_thresholds(fetcher):
    """Test data quality alert thresholds."""
    from datetime import timedelta
    
    # Test stale data threshold (> 10 minutes)
    stale_timestamp = datetime.now(timezone.utc) - timedelta(minutes=11)
    
    dates = pd.date_range(
        start=stale_timestamp - timedelta(hours=1),
        end=stale_timestamp,
        freq="1m",
    )[:50]
    
    df = pd.DataFrame({
        "open": [15000] * len(dates),
        "high": [15010] * len(dates),
        "low": [14990] * len(dates),
        "close": [15005] * len(dates),
        "volume": [1000] * len(dates),
        "timestamp": dates,
    }, index=dates)
    
    latest_bar = {
        "timestamp": stale_timestamp,
        "open": 15000.0,
        "high": 15010.0,
        "low": 14990.0,
        "close": 15005.0,
        "volume": 1000,
    }
    
    # Temporarily patch for stale data test
    original_fetch = fetcher.data_provider.fetch_historical
    original_get_latest = fetcher.data_provider.get_latest_bar
    fetcher.data_provider.fetch_historical = MagicMock(return_value=df)
    fetcher.data_provider.get_latest_bar = AsyncMock(return_value=latest_bar)
    
    try:
        result = await fetcher.fetch_latest_data()
        # Data should be marked as stale (age > 10 minutes)
        assert result["latest_bar"] is not None
        # Age check would be done in service layer
    finally:
        fetcher.data_provider.fetch_historical = original_fetch
        fetcher.data_provider.get_latest_bar = original_get_latest


@pytest.mark.asyncio
async def test_fetcher_buffer_size_alert_threshold(fetcher):
    """Test buffer size alert threshold (< 10 bars)."""
    # Create minimal data (less than threshold)
    dates = pd.date_range(
        start=datetime.now(timezone.utc) - timedelta(minutes=5),
        end=datetime.now(timezone.utc),
        freq="1min",
    )[:5]  # Only 5 bars (below threshold of 10)
    
    df = pd.DataFrame({
        "open": [15000] * len(dates),
        "high": [15010] * len(dates),
        "low": [14990] * len(dates),
        "close": [15005] * len(dates),
        "volume": [1000] * len(dates),
    }, index=dates)
    
    # Temporarily patch for small buffer test
    original_fetch = fetcher.data_provider.fetch_historical
    fetcher.data_provider.fetch_historical = MagicMock(return_value=df)
    
    try:
        result = await fetcher.fetch_latest_data()
        buffer_size = fetcher.get_buffer_size()
        # Buffer size should be small (< 10)
        assert buffer_size < 10
        # Alert would be triggered in service layer
    finally:
        fetcher.data_provider.fetch_historical = original_fetch


@pytest.mark.asyncio
async def test_fetcher_multitimeframe_data(fetcher):
    """Test multi-timeframe data fetching."""
    # Fetch data which should include multi-timeframe
    result = await fetcher.fetch_latest_data()
    
    # Should have multi-timeframe data
    assert "df_5m" in result
    assert "df_15m" in result
    assert isinstance(result["df_5m"], pd.DataFrame)
    assert isinstance(result["df_15m"], pd.DataFrame)



