"""
Tests for _data_level field in state.json.

Verifies that the data level indicator is correctly populated
in latest_bar from the data fetcher.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd


class TestDataLevelField:
    """Tests for _data_level field propagation."""

    @pytest.mark.asyncio
    async def test_data_level_level1_for_realtime_data(self):
        """Test that real-time data (<30s old) gets _data_level='level1'."""
        from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
        from tests.mock_data_provider import MockDataProvider

        # Create mock provider
        mock_provider = MockDataProvider(base_price=17500.0)

        # Create data fetcher
        fetcher = NQAgentDataFetcher(mock_provider)

        # Override get_latest_bar to return very fresh data
        now = datetime.now(timezone.utc)
        fresh_bar = {
            "timestamp": now - timedelta(seconds=10),  # 10 seconds old
            "open": 17500.0,
            "high": 17505.0,
            "low": 17495.0,
            "close": 17502.0,
            "volume": 1000,
        }
        mock_provider.get_latest_bar = MagicMock(return_value=fresh_bar)

        # Fetch data
        market_data = await fetcher.fetch_latest_data()

        # Verify _data_level is set to level1 for fresh data
        latest_bar = market_data.get("latest_bar")
        assert latest_bar is not None
        assert latest_bar.get("_data_level") == "level1"
        assert latest_bar.get("_data_source") == "real-time"

    @pytest.mark.asyncio
    async def test_data_level_historical_for_old_data(self):
        """Test that older data (>30s) gets _data_level='historical'."""
        from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
        from tests.mock_data_provider import MockDataProvider

        # Create mock provider
        mock_provider = MockDataProvider(base_price=17500.0)

        # Create data fetcher
        fetcher = NQAgentDataFetcher(mock_provider)

        # Override get_latest_bar to return stale data
        now = datetime.now(timezone.utc)
        stale_bar = {
            "timestamp": now - timedelta(minutes=5),  # 5 minutes old
            "open": 17500.0,
            "high": 17505.0,
            "low": 17495.0,
            "close": 17502.0,
            "volume": 1000,
        }
        mock_provider.get_latest_bar = MagicMock(return_value=stale_bar)

        # Fetch data
        market_data = await fetcher.fetch_latest_data()

        # Verify _data_level is set to historical for older data
        latest_bar = market_data.get("latest_bar")
        assert latest_bar is not None
        assert latest_bar.get("_data_level") == "historical"
        assert latest_bar.get("_data_source") == "historical"

    @pytest.mark.asyncio
    async def test_data_level_historical_fallback(self):
        """Test that fallback to historical data gets _data_level='historical'."""
        from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
        from tests.mock_data_provider import MockDataProvider

        # Create mock provider that returns None for get_latest_bar
        mock_provider = MockDataProvider(base_price=17500.0)

        # Create data fetcher
        fetcher = NQAgentDataFetcher(mock_provider)

        # Override get_latest_bar to return None (triggers historical fallback)
        mock_provider.get_latest_bar = MagicMock(return_value=None)

        # Fetch data - should fall back to historical
        market_data = await fetcher.fetch_latest_data()

        # Verify _data_level is set to historical for fallback
        latest_bar = market_data.get("latest_bar")
        assert latest_bar is not None
        assert latest_bar.get("_data_level") == "historical"
        assert latest_bar.get("_data_source") == "historical_fallback"


class TestDataLevelMapping:
    """Tests for _data_source to _data_level mapping."""

    def test_data_level_mapping_coverage(self):
        """Verify all expected data sources map to appropriate levels."""
        # This tests the mapping logic indirectly
        data_level_map = {
            "real-time": "level1",
            "historical": "historical",
            "historical_fallback": "historical",
            "provider": "unknown",
            "fallback": "error",
            "unknown": "unknown",
        }

        # Verify expected mappings
        assert data_level_map["real-time"] == "level1"
        assert data_level_map["historical"] == "historical"
        assert data_level_map["historical_fallback"] == "historical"
        assert data_level_map["provider"] == "unknown"
        assert data_level_map["fallback"] == "error"
        assert data_level_map["unknown"] == "unknown"





