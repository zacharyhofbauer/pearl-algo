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
def fetcher(mock_data_provider, config):
    """Create a data fetcher instance."""
    return NQAgentDataFetcher(mock_data_provider, config)


@pytest.mark.asyncio
async def test_fetcher_initialization(fetcher):
    """Test data fetcher initializes correctly."""
    assert fetcher is not None
    assert fetcher.config.symbol == "NQ"
    assert fetcher._data_buffer is None or fetcher._data_buffer.empty


@pytest.mark.asyncio
async def test_fetcher_fetch_latest_data(fetcher, mock_data_provider):
    """Test fetching latest data."""
    result = await fetcher.fetch_latest_data()
    
    assert "df" in result
    assert "latest_bar" in result
    assert isinstance(result["df"], pd.DataFrame)
    assert result["latest_bar"] is not None
    assert "timestamp" in result["latest_bar"]
    assert "close" in result["latest_bar"]


@pytest.mark.asyncio
async def test_fetcher_buffer_management(fetcher, mock_data_provider):
    """Test data buffer management."""
    # Fetch data multiple times
    for _ in range(5):
        await fetcher.fetch_latest_data()
    
    # Check buffer size is limited
    buffer_size = fetcher.get_buffer_size()
    assert buffer_size <= fetcher._buffer_size
    assert buffer_size > 0


@pytest.mark.asyncio
async def test_fetcher_empty_data_handling(fetcher, mock_data_provider):
    """Test handling of empty data."""
    # Mock empty dataframe
    mock_data_provider.fetch_historical = MagicMock(return_value=pd.DataFrame())
    mock_data_provider.get_latest_bar = AsyncMock(return_value=None)
    
    result = await fetcher.fetch_latest_data()
    
    assert result["df"].empty
    assert result["latest_bar"] is None


@pytest.mark.asyncio
async def test_fetcher_stale_data_detection(fetcher, mock_data_provider):
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
    
    mock_data_provider.fetch_historical = MagicMock(return_value=df)
    
    # Fetch should complete but may log warning
    result = await fetcher.fetch_latest_data()
    assert "df" in result


@pytest.mark.asyncio
async def test_fetcher_missing_values_handling(fetcher, mock_data_provider):
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
    
    mock_data_provider.fetch_historical = MagicMock(return_value=df)
    
    # Should handle missing values gracefully
    result = await fetcher.fetch_latest_data()
    assert "df" in result


@pytest.mark.asyncio
async def test_fetcher_error_handling(fetcher, mock_data_provider):
    """Test error handling in data fetcher."""
    # Make provider raise error
    mock_data_provider.fetch_historical = MagicMock(side_effect=Exception("Fetch error"))
    mock_data_provider.get_latest_bar = AsyncMock(side_effect=Exception("Latest bar error"))
    
    # Should return empty data instead of raising
    result = await fetcher.fetch_latest_data()
    
    assert result["df"].empty
    assert result["latest_bar"] is None


@pytest.mark.asyncio
async def test_fetcher_historical_fallback(fetcher, mock_data_provider):
    """Test fallback to historical data when latest_bar unavailable."""
    # Mock get_latest_bar to return None
    mock_data_provider.get_latest_bar = AsyncMock(return_value=None)
    
    # Should use last row from historical data
    result = await fetcher.fetch_latest_data()
    
    # Should still have latest_bar from historical data
    assert result["latest_bar"] is not None
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



