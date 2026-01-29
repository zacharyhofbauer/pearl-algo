"""Tests for Market Agent Data Fetcher."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.market_agent.data_fetcher import MarketAgentDataFetcher


@pytest.fixture
def mock_data_provider():
    """Create a mock data provider."""
    provider = MagicMock()
    provider.fetch_historical = MagicMock(return_value=pd.DataFrame())
    provider.get_latest_bar = MagicMock(return_value=None)
    return provider


@pytest.fixture
def sample_ohlcv_df():
    """Create sample OHLCV dataframe."""
    n = 50
    timestamps = pd.date_range(
        start=datetime.now(timezone.utc) - timedelta(hours=2),
        periods=n,
        freq="5min",
        tz=timezone.utc,
    )
    return pd.DataFrame({
        "open": [100.0 + i * 0.1 for i in range(n)],
        "high": [101.0 + i * 0.1 for i in range(n)],
        "low": [99.0 + i * 0.1 for i in range(n)],
        "close": [100.5 + i * 0.1 for i in range(n)],
        "volume": [1000 + i * 10 for i in range(n)],
    }, index=timestamps)


@pytest.fixture
def sample_latest_bar():
    """Create sample latest bar."""
    return {
        "timestamp": datetime.now(timezone.utc),
        "open": 105.0,
        "high": 106.0,
        "low": 104.0,
        "close": 105.5,
        "volume": 1500,
    }


class TestMarketAgentDataFetcherInit:
    """Test MarketAgentDataFetcher initialization."""

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_init_with_defaults(self, mock_config, mock_data_provider):
        """Test initialization with default config."""
        mock_config.return_value = {"data": {}}

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        assert fetcher.data_provider == mock_data_provider
        assert fetcher._data_buffer is None
        assert fetcher._enable_base_cache is False
        assert fetcher._enable_mtf_cache is False

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_init_with_custom_config(self, mock_config, mock_data_provider):
        """Test initialization with custom config."""
        mock_config.return_value = {
            "data": {
                "buffer_size": 200,
                "enable_base_cache": True,
                "base_refresh_seconds": 120,
            }
        }

        fetcher = MarketAgentDataFetcher(mock_data_provider, config={"symbol": "NQ"})

        assert fetcher._buffer_size == 200
        assert fetcher._enable_base_cache is True
        assert fetcher._base_refresh_seconds == 120
        assert fetcher.config.get("symbol") == "NQ"


class TestNormalizeToStrategyBuffer:
    """Test _normalize_to_strategy_buffer method."""

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_empty_dataframe(self, mock_config, mock_data_provider):
        """Test with empty dataframe."""
        mock_config.return_value = {"data": {}}
        fetcher = MarketAgentDataFetcher(mock_data_provider)

        result = fetcher._normalize_to_strategy_buffer(pd.DataFrame(), 100)

        assert result.empty

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_with_timestamp_column(self, mock_config, mock_data_provider):
        """Test dataframe that already has timestamp column."""
        mock_config.return_value = {"data": {}}
        fetcher = MarketAgentDataFetcher(mock_data_provider)

        df = pd.DataFrame({
            "timestamp": pd.date_range(start="2024-01-01", periods=10, freq="5min"),
            "close": [100.0] * 10,
        })

        result = fetcher._normalize_to_strategy_buffer(df, 100)

        assert "timestamp" in result.columns
        assert len(result) == 10

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_with_datetime_index(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test dataframe with DatetimeIndex."""
        mock_config.return_value = {"data": {}}
        fetcher = MarketAgentDataFetcher(mock_data_provider)

        result = fetcher._normalize_to_strategy_buffer(sample_ohlcv_df, 100)

        assert "timestamp" in result.columns
        assert len(result) == 50

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_buffer_size_limit(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test that buffer size is limited."""
        mock_config.return_value = {"data": {}}
        fetcher = MarketAgentDataFetcher(mock_data_provider)

        result = fetcher._normalize_to_strategy_buffer(sample_ohlcv_df, 20)

        assert len(result) == 20

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_removes_index_column(self, mock_config, mock_data_provider):
        """Test that stray 'index' column is removed."""
        mock_config.return_value = {"data": {}}
        fetcher = MarketAgentDataFetcher(mock_data_provider)

        df = pd.DataFrame({
            "timestamp": pd.date_range(start="2024-01-01", periods=10, freq="5min"),
            "close": [100.0] * 10,
            "index": range(10),  # Stray index column
        })

        result = fetcher._normalize_to_strategy_buffer(df, 100)

        assert "index" not in result.columns
        assert "timestamp" in result.columns


class TestGetBufferSize:
    """Test get_buffer_size method."""

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_empty_buffer(self, mock_config, mock_data_provider):
        """Test with no buffer."""
        mock_config.return_value = {"data": {}}
        fetcher = MarketAgentDataFetcher(mock_data_provider)

        assert fetcher.get_buffer_size() == 0

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_with_buffer(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test with populated buffer."""
        mock_config.return_value = {"data": {}}
        fetcher = MarketAgentDataFetcher(mock_data_provider)
        fetcher._data_buffer = sample_ohlcv_df

        assert fetcher.get_buffer_size() == 50


class TestGetCacheStats:
    """Test get_cache_stats method."""

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_initial_stats(self, mock_config, mock_data_provider):
        """Test initial cache stats are zero."""
        mock_config.return_value = {"data": {}}
        fetcher = MarketAgentDataFetcher(mock_data_provider)

        stats = fetcher.get_cache_stats()

        assert stats["base_hits"] == 0
        assert stats["base_misses"] == 0
        assert stats["base_hit_rate"] == 0.0
        assert stats["mtf_5m_hits"] == 0
        assert stats["mtf_15m_hits"] == 0

    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    def test_stats_after_cache_activity(self, mock_config, mock_data_provider):
        """Test cache stats after some activity."""
        mock_config.return_value = {"data": {}}
        fetcher = MarketAgentDataFetcher(mock_data_provider)

        # Simulate cache activity
        fetcher._base_cache_hits = 8
        fetcher._base_cache_misses = 2
        fetcher._mtf_cache_hits_5m = 5
        fetcher._mtf_cache_misses_5m = 5

        stats = fetcher.get_cache_stats()

        assert stats["base_hits"] == 8
        assert stats["base_misses"] == 2
        assert stats["base_hit_rate"] == 0.8
        assert stats["mtf_5m_hit_rate"] == 0.5


class TestFetchLatestData:
    """Test fetch_latest_data method."""

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_with_empty_provider_data(self, mock_config, mock_data_provider):
        """Test fetch when provider returns empty data."""
        mock_config.return_value = {"data": {}}
        mock_data_provider.fetch_historical.return_value = pd.DataFrame()
        mock_data_provider.get_latest_bar.return_value = None

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        result = await fetcher.fetch_latest_data()

        assert result["df"].empty
        assert result["latest_bar"] is None

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_with_valid_data(self, mock_config, mock_data_provider, sample_ohlcv_df, sample_latest_bar):
        """Test fetch with valid provider data."""
        mock_config.return_value = {"data": {}}
        mock_data_provider.fetch_historical.return_value = sample_ohlcv_df
        mock_data_provider.get_latest_bar.return_value = sample_latest_bar

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        result = await fetcher.fetch_latest_data()

        assert not result["df"].empty
        assert result["latest_bar"] is not None
        assert result["latest_bar"]["close"] == 105.5

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_uses_historical_fallback(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test that historical data is used as fallback when no latest bar."""
        mock_config.return_value = {"data": {}}
        mock_data_provider.fetch_historical.return_value = sample_ohlcv_df
        mock_data_provider.get_latest_bar.return_value = None

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        result = await fetcher.fetch_latest_data()

        # Should use last row from historical as fallback
        assert result["latest_bar"] is not None
        assert result["latest_bar"]["_data_source"] == "historical_fallback"

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_handles_provider_exception(self, mock_config, mock_data_provider):
        """Test that exceptions are handled gracefully."""
        mock_config.return_value = {"data": {}}
        mock_data_provider.fetch_historical.side_effect = Exception("Connection error")

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        # Should not raise, should return empty data
        result = await fetcher.fetch_latest_data()

        assert result["df"].empty
        assert result["latest_bar"] is None


class TestFetchBaseHistoricalData:
    """Test _fetch_base_historical_data method."""

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_without_cache(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test fetch without caching enabled."""
        mock_config.return_value = {"data": {"enable_base_cache": False}}
        mock_data_provider.fetch_historical.return_value = sample_ohlcv_df

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=2)

        result = await fetcher._fetch_base_historical_data(start, end)

        assert not result.empty
        assert fetcher._base_cache_misses == 1

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_with_cache_hit(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test cache hit when data is fresh."""
        mock_config.return_value = {
            "data": {
                "enable_base_cache": True,
                "base_refresh_seconds": 60,
            }
        }
        mock_data_provider.fetch_historical.return_value = sample_ohlcv_df

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        # Populate cache
        fetcher._base_historical_cache = sample_ohlcv_df
        fetcher._base_last_refresh = datetime.now(timezone.utc)

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=2)

        result = await fetcher._fetch_base_historical_data(start, end)

        assert not result.empty
        assert fetcher._base_cache_hits == 1
        # Should not have called fetch_historical
        assert mock_data_provider.fetch_historical.call_count == 0

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_with_cache_miss(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test cache miss when data is stale."""
        mock_config.return_value = {
            "data": {
                "enable_base_cache": True,
                "base_refresh_seconds": 60,
            }
        }
        mock_data_provider.fetch_historical.return_value = sample_ohlcv_df

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        # Populate cache with stale data
        fetcher._base_historical_cache = sample_ohlcv_df
        fetcher._base_last_refresh = datetime.now(timezone.utc) - timedelta(seconds=120)

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=2)

        result = await fetcher._fetch_base_historical_data(start, end)

        assert not result.empty
        assert fetcher._base_cache_misses == 1
        # Should have called fetch_historical
        assert mock_data_provider.fetch_historical.call_count == 1


class TestFetchMultitimeframeData:
    """Test multi-timeframe data fetching."""

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_uncached(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test uncached multi-timeframe fetch."""
        mock_config.return_value = {"data": {"enable_mtf_cache": False}}
        mock_data_provider.fetch_historical.return_value = sample_ohlcv_df

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        end = datetime.now(timezone.utc)
        df_5m, df_15m = await fetcher._fetch_multitimeframe_data(end)

        # Both should be fetched
        assert mock_data_provider.fetch_historical.call_count == 2

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_cached_hit(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test cached multi-timeframe fetch with cache hit."""
        mock_config.return_value = {
            "data": {
                "enable_mtf_cache": True,
                "mtf_refresh_seconds_5m": 300,
                "mtf_refresh_seconds_15m": 900,
            }
        }
        mock_data_provider.fetch_historical.return_value = sample_ohlcv_df

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        # Populate caches
        fetcher._data_buffer_5m = sample_ohlcv_df
        fetcher._data_buffer_15m = sample_ohlcv_df
        fetcher._mtf_last_refresh_5m = datetime.now(timezone.utc)
        fetcher._mtf_last_refresh_15m = datetime.now(timezone.utc)

        end = datetime.now(timezone.utc)
        df_5m, df_15m = await fetcher._fetch_multitimeframe_data(end)

        # Should not fetch, use cache
        assert mock_data_provider.fetch_historical.call_count == 0
        assert fetcher._mtf_cache_hits_5m == 1
        assert fetcher._mtf_cache_hits_15m == 1

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_fetch_handles_exception(self, mock_config, mock_data_provider):
        """Test that exceptions are handled gracefully."""
        mock_config.return_value = {"data": {"enable_mtf_cache": False}}
        mock_data_provider.fetch_historical.side_effect = Exception("Network error")

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        end = datetime.now(timezone.utc)
        df_5m, df_15m = await fetcher._fetch_multitimeframe_data_uncached(end)

        # Should return empty dataframes, not raise
        assert df_5m.empty
        assert df_15m.empty


class TestDataSourceMetadata:
    """Test data source metadata in latest_bar."""

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_realtime_data_source(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test real-time data source detection."""
        mock_config.return_value = {"data": {}}
        mock_data_provider.fetch_historical.return_value = sample_ohlcv_df

        # Latest bar with very fresh timestamp
        latest_bar = {
            "timestamp": datetime.now(timezone.utc) - timedelta(seconds=5),
            "open": 105.0,
            "high": 106.0,
            "low": 104.0,
            "close": 105.5,
            "volume": 1500,
        }
        mock_data_provider.get_latest_bar.return_value = latest_bar

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        result = await fetcher.fetch_latest_data()

        assert result["latest_bar"]["_data_source"] == "real-time"
        assert result["latest_bar"]["_data_level"] == "level1"

    @pytest.mark.asyncio
    @patch("pearlalgo.market_agent.data_fetcher.load_service_config")
    async def test_historical_data_source(self, mock_config, mock_data_provider, sample_ohlcv_df):
        """Test historical data source detection."""
        mock_config.return_value = {"data": {}}
        mock_data_provider.fetch_historical.return_value = sample_ohlcv_df

        # Latest bar with older timestamp
        latest_bar = {
            "timestamp": datetime.now(timezone.utc) - timedelta(minutes=5),
            "open": 105.0,
            "high": 106.0,
            "low": 104.0,
            "close": 105.5,
            "volume": 1500,
        }
        mock_data_provider.get_latest_bar.return_value = latest_bar

        fetcher = MarketAgentDataFetcher(mock_data_provider)

        result = await fetcher.fetch_latest_data()

        assert result["latest_bar"]["_data_source"] == "historical"
        assert result["latest_bar"]["_data_level"] == "historical"
