"""Tests for ML Feature Engineering Layer."""

import numpy as np
import pandas as pd
import pytest

from pearlalgo.learning.feature_engineer import (
    FeatureEngineer,
    FeatureConfig,
    FeatureVector,
)


@pytest.fixture
def sample_ohlcv_data() -> pd.DataFrame:
    """Create sample OHLCV data."""
    np.random.seed(42)
    n = 100
    
    # Generate realistic price data
    base_price = 15000
    returns = np.random.normal(0.0001, 0.002, n)
    close = base_price * np.cumprod(1 + returns)
    
    high = close * (1 + np.abs(np.random.normal(0, 0.001, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.001, n)))
    open_ = close * (1 + np.random.normal(0, 0.0005, n))
    volume = np.random.randint(100, 10000, n)
    
    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })


@pytest.fixture
def feature_engineer() -> FeatureEngineer:
    """Create feature engineer instance."""
    config = FeatureConfig(
        short_window=5,
        medium_window=20,
        long_window=50,
    )
    return FeatureEngineer(config)


class TestFeatureConfig:
    """Test FeatureConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = FeatureConfig()
        
        assert config.short_window == 5
        assert config.medium_window == 20
        assert config.long_window == 50
        assert config.normalize_features is True
    
    def test_from_dict(self):
        """Test creating config from dictionary."""
        config = FeatureConfig.from_dict({
            "short_window": 10,
            "medium_window": 30,
            "compute_microstructure": False,
        })
        
        assert config.short_window == 10
        assert config.medium_window == 30
        assert config.compute_microstructure is False


class TestFeatureVector:
    """Test FeatureVector container."""
    
    def test_to_array(self):
        """Test converting to numpy array."""
        fv = FeatureVector(
            features={"a": 1.0, "b": 2.0, "c": 3.0},
        )
        
        arr = fv.to_array(["a", "b", "c"])
        assert arr.shape == (3,)
        assert arr[0] == 1.0
        assert arr[1] == 2.0
        assert arr[2] == 3.0
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        fv = FeatureVector(
            features={"rsi": 0.7},
            symbol="MNQ",
            signal_type="momentum_long",
        )
        
        result = fv.to_dict()
        assert result["symbol"] == "MNQ"
        assert result["signal_type"] == "momentum_long"
        assert result["features"]["rsi"] == 0.7
    
    def test_num_features(self):
        """Test feature count."""
        fv = FeatureVector(features={"a": 1, "b": 2, "c": 3})
        assert fv.num_features == 3


class TestFeatureEngineer:
    """Test FeatureEngineer class."""
    
    def test_compute_features_basic(self, feature_engineer, sample_ohlcv_data):
        """Test basic feature computation."""
        fv = feature_engineer.compute_features(sample_ohlcv_data)
        
        assert fv.num_features > 30  # Should compute 30+ features
        assert "momentum_short" in fv.features
        assert "rsi_14" in fv.features
        assert "volume_ratio" in fv.features
    
    def test_compute_features_empty_data(self, feature_engineer):
        """Test handling of empty data."""
        empty_df = pd.DataFrame()
        fv = feature_engineer.compute_features(empty_df)
        
        assert fv.num_features == 0
    
    def test_compute_features_insufficient_data(self, feature_engineer):
        """Test handling of insufficient data."""
        small_df = pd.DataFrame({
            "Open": [100, 101],
            "High": [102, 103],
            "Low": [99, 100],
            "Close": [101, 102],
            "Volume": [1000, 1100],
        })
        
        fv = feature_engineer.compute_features(small_df)
        # Should still return a vector, possibly with defaults
        assert isinstance(fv, FeatureVector)
    
    def test_price_action_features(self, feature_engineer, sample_ohlcv_data):
        """Test price action features are computed."""
        fv = feature_engineer.compute_features(sample_ohlcv_data)
        
        # Check key price action features exist
        assert "momentum_short" in fv.price_action
        assert "momentum_medium" in fv.price_action
        assert "rsi_14" in fv.price_action
        assert "atr_14_pct" in fv.price_action
        assert "trend_strength" in fv.price_action
    
    def test_volume_features(self, feature_engineer, sample_ohlcv_data):
        """Test volume features are computed."""
        fv = feature_engineer.compute_features(sample_ohlcv_data)
        
        assert "volume_ratio" in fv.volume_profile
        assert "volume_trend" in fv.volume_profile
        assert "vwap_deviation" in fv.volume_profile
    
    def test_time_features(self, feature_engineer, sample_ohlcv_data):
        """Test time features are computed."""
        # Add datetime index
        sample_ohlcv_data.index = pd.date_range(
            start="2024-01-02 09:30",
            periods=len(sample_ohlcv_data),
            freq="1min",
        )
        
        fv = feature_engineer.compute_features(sample_ohlcv_data)
        
        assert "hour_sin" in fv.time_features
        assert "hour_cos" in fv.time_features
        assert "session_phase" in fv.time_features
    
    def test_feature_normalization(self, feature_engineer, sample_ohlcv_data):
        """Test features are normalized."""
        fv = feature_engineer.compute_features(sample_ohlcv_data)
        
        # Most normalized features should be in reasonable range
        for name, value in fv.features.items():
            assert np.isfinite(value), f"Feature {name} is not finite: {value}"
    
    def test_sequential_features(self, feature_engineer, sample_ohlcv_data):
        """Test sequential features from trade history."""
        recent_outcomes = [
            {"is_win": True, "pnl": 50, "signal_type": "momentum_long"},
            {"is_win": False, "pnl": -30, "signal_type": "momentum_long"},
            {"is_win": True, "pnl": 80, "signal_type": "sr_bounce"},
        ]
        
        fv = feature_engineer.compute_features(
            sample_ohlcv_data,
            recent_outcomes=recent_outcomes,
        )
        
        assert "recent_win_rate" in fv.sequential
        assert "recent_avg_pnl" in fv.sequential
        assert "recent_streak" in fv.sequential
    
    def test_get_feature_names(self, feature_engineer, sample_ohlcv_data):
        """Test getting feature names after computation."""
        # Compute features first
        feature_engineer.compute_features(sample_ohlcv_data)
        
        names = feature_engineer.get_feature_names()
        assert len(names) > 0
        assert isinstance(names, list)
        assert all(isinstance(n, str) for n in names)
    
    def test_column_normalization(self, feature_engineer):
        """Test column name normalization."""
        # Test with lowercase columns
        df = pd.DataFrame({
            "open": [100, 101, 102],
            "high": [102, 103, 104],
            "low": [99, 100, 101],
            "close": [101, 102, 103],
            "volume": [1000, 1100, 1200],
        })
        
        # Should handle lowercase columns
        fv = feature_engineer.compute_features(df)
        assert isinstance(fv, FeatureVector)


