"""
Tests for data providers (Polygon, Tradier, Local Parquet).
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import shutil

from pearlalgo.data_providers.factory import create_data_provider
from pearlalgo.data_providers.normalizer import DataNormalizer
from pearlalgo.data_providers.local_parquet_provider import LocalParquetProvider


class TestDataProviderFactory:
    """Test data provider factory."""

    def test_create_local_parquet_provider(self):
        """Test creating local Parquet provider."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = create_data_provider(
                "local_parquet", root_dir=tmpdir
            )

            assert isinstance(provider, LocalParquetProvider)
            assert provider.root_dir == Path(tmpdir)


class TestLocalParquetProvider:
    """Test local Parquet provider."""

    def test_save_and_load_historical(self):
        """Test saving and loading historical data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalParquetProvider(root_dir=tmpdir)

            # Create sample data
            dates = pd.date_range(
                start="2024-01-01", end="2024-01-10", freq="D"
            )
            df = pd.DataFrame(
                {
                    "open": 100.0,
                    "high": 105.0,
                    "low": 95.0,
                    "close": 102.0,
                    "volume": 1000,
                },
                index=dates,
            )

            # Save
            success = provider.save_historical(
                df=df, symbol="QQQ", timeframe="1d", overwrite=True
            )
            assert success

            # Load
            loaded_df = provider.fetch_historical(
                symbol="QQQ", timeframe="1d"
            )

            assert not loaded_df.empty
            assert len(loaded_df) == len(df)
            assert "open" in loaded_df.columns
            assert "close" in loaded_df.columns

    def test_list_symbols(self):
        """Test listing available symbols."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalParquetProvider(root_dir=tmpdir)

            # Create files
            dates = pd.date_range(start="2024-01-01", end="2024-01-05", freq="D")
            for symbol in ["QQQ", "SPY"]:
                df = pd.DataFrame(
                    {
                        "open": 100.0,
                        "high": 105.0,
                        "low": 95.0,
                        "close": 102.0,
                        "volume": 1000,
                    },
                    index=dates,
                )
                provider.save_historical(
                    df=df, symbol=symbol, timeframe="1d", overwrite=True
                )

            symbols = provider.list_symbols(timeframe="1d")
            assert "QQQ" in symbols
            assert "SPY" in symbols


class TestDataNormalizer:
    """Test data normalization."""

    def test_normalize_ohlcv(self):
        """Test OHLCV data normalization."""
        normalizer = DataNormalizer()

        # Create data with non-standard column names
        dates = pd.date_range(start="2024-01-01", end="2024-01-05", freq="D")
        df = pd.DataFrame(
            {
                "o": 100.0,  # lowercase
                "h": 105.0,
                "l": 95.0,
                "c": 102.0,  # lowercase
                "v": 1000,  # lowercase
            },
            index=dates,
        )

        normalized = normalizer.normalize_ohlcv(df)

        assert "open" in normalized.columns
        assert "high" in normalized.columns
        assert "low" in normalized.columns
        assert "close" in normalized.columns
        assert "volume" in normalized.columns

    def test_validate_ohlcv(self):
        """Test OHLCV data validation."""
        normalizer = DataNormalizer()

        # Valid data
        dates = pd.date_range(start="2024-01-01", end="2024-01-05", freq="D")
        df = pd.DataFrame(
            {
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 102.0,
                "volume": 1000,
            },
            index=dates,
        )

        assert normalizer.validate_ohlcv(df)

        # Invalid data (missing columns)
        invalid_df = pd.DataFrame({"open": [100.0]}, index=[dates[0]])
        assert not normalizer.validate_ohlcv(invalid_df)

