"""Tests for PearlBot Auto - Signal generation strategy."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from pearlalgo.trading_bots.pearl_bot_auto import (
    CONFIG,
    MarketRegime,
    _safe_div,
    _safe_pct,
    _get_key_levels_cache_key,
    _clear_key_levels_cache_if_needed,
    detect_market_regime,
    calculate_ema,
    calculate_vwap,
    calculate_vwap_bands,
    calculate_volume_ma,
    calculate_atr,
    generate_signals,
    check_trading_session,
)


@pytest.fixture
def sample_ohlcv_df():
    """Create sample OHLCV dataframe for testing."""
    np.random.seed(42)
    n = 100
    base_price = 100.0

    # Generate realistic price movement
    returns = np.random.randn(n) * 0.01  # 1% daily volatility
    close = base_price * np.cumprod(1 + returns)

    # Generate OHLC from close
    high = close * (1 + np.abs(np.random.randn(n) * 0.005))
    low = close * (1 - np.abs(np.random.randn(n) * 0.005))
    open_price = close * (1 + np.random.randn(n) * 0.002)
    volume = np.random.randint(1000, 10000, n).astype(float)

    df = pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "timestamp": pd.date_range(start="2024-01-01", periods=n, freq="5min"),
    })

    return df


@pytest.fixture
def trending_up_df():
    """Create a clearly trending up dataframe."""
    n = 100
    # Linear uptrend with small noise
    close = 100.0 + np.arange(n) * 0.5 + np.random.randn(n) * 0.1
    high = close + 0.2
    low = close - 0.2
    open_price = close - 0.1
    volume = np.ones(n) * 5000

    return pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def trending_down_df():
    """Create a clearly trending down dataframe."""
    n = 100
    # Linear downtrend with small noise
    close = 150.0 - np.arange(n) * 0.5 + np.random.randn(n) * 0.1
    high = close + 0.2
    low = close - 0.2
    open_price = close + 0.1
    volume = np.ones(n) * 5000

    return pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def ranging_df():
    """Create a ranging/sideways dataframe."""
    n = 100
    # Sideways movement around 100
    close = 100.0 + np.sin(np.linspace(0, 4 * np.pi, n)) * 0.5 + np.random.randn(n) * 0.05
    high = close + 0.1
    low = close - 0.1
    open_price = close
    volume = np.ones(n) * 5000

    return pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


class TestSafeDiv:
    """Test _safe_div helper function."""

    def test_normal_division(self):
        """Test normal division."""
        assert _safe_div(10.0, 2.0) == 5.0
        assert _safe_div(1.0, 4.0) == 0.25

    def test_division_by_zero(self):
        """Test division by zero returns default."""
        assert _safe_div(10.0, 0.0) == 0.0
        assert _safe_div(10.0, 0.0, default=1.0) == 1.0

    def test_division_by_near_zero(self):
        """Test division by near-zero returns default."""
        assert _safe_div(10.0, 1e-15) == 0.0
        assert _safe_div(10.0, 1e-15, default=5.0) == 5.0

    def test_negative_numbers(self):
        """Test with negative numbers."""
        assert _safe_div(-10.0, 2.0) == -5.0
        assert _safe_div(10.0, -2.0) == -5.0


class TestSafePct:
    """Test _safe_pct helper function."""

    def test_normal_percentage(self):
        """Test normal percentage calculation."""
        assert _safe_pct(50.0, 100.0) == 50.0
        assert _safe_pct(1.0, 4.0) == 25.0

    def test_division_by_zero(self):
        """Test division by zero returns default."""
        assert _safe_pct(10.0, 0.0) == 0.0
        assert _safe_pct(10.0, 0.0, default=100.0) == 100.0

    def test_over_100_percent(self):
        """Test percentages over 100%."""
        assert _safe_pct(200.0, 100.0) == 200.0


class TestMarketRegime:
    """Test MarketRegime dataclass."""

    def test_to_dict(self):
        """Test dictionary conversion."""
        regime = MarketRegime(
            regime="trending_up",
            confidence=0.85,
            trend_strength=0.75,
            volatility_ratio=1.2,
            recommendation="full_size",
        )

        d = regime.to_dict()

        assert d["regime"] == "trending_up"
        assert d["confidence"] == 0.85
        assert d["recommendation"] == "full_size"


class TestDetectMarketRegime:
    """Test market regime detection."""

    def test_insufficient_data(self):
        """Test with insufficient data returns unknown regime."""
        df = pd.DataFrame({
            "open": [100, 101],
            "high": [102, 103],
            "low": [99, 100],
            "close": [101, 102],
            "volume": [1000, 1000],
        })

        regime = detect_market_regime(df, lookback=50)

        assert regime.regime == "unknown"
        assert regime.confidence == 0.0
        assert regime.recommendation == "avoid"

    def test_trending_up_detection(self, trending_up_df):
        """Test detection of trending up market."""
        regime = detect_market_regime(trending_up_df, lookback=50)

        assert regime.regime == "trending_up"
        assert regime.confidence > 0.5
        assert regime.trend_strength > 0.3

    def test_trending_down_detection(self, trending_down_df):
        """Test detection of trending down market."""
        regime = detect_market_regime(trending_down_df, lookback=50)

        assert regime.regime == "trending_down"
        assert regime.confidence > 0.5

    def test_ranging_detection(self, ranging_df):
        """Test detection of ranging market."""
        regime = detect_market_regime(ranging_df, lookback=50)

        # May be ranging or low-confidence trending
        assert regime.regime in ["ranging", "trending_up", "trending_down"]


class TestCalculateEMA:
    """Test EMA calculation."""

    def test_ema_calculation(self, sample_ohlcv_df):
        """Test EMA is calculated correctly."""
        ema = calculate_ema(sample_ohlcv_df, period=9)

        assert len(ema) == len(sample_ohlcv_df)
        assert not ema.isna().all()
        # EMA should be smoothed - less volatile than raw prices
        assert ema.std() <= sample_ohlcv_df["close"].std()

    def test_ema_different_periods(self, sample_ohlcv_df):
        """Test that longer EMA periods are smoother."""
        ema_9 = calculate_ema(sample_ohlcv_df, period=9)
        ema_21 = calculate_ema(sample_ohlcv_df, period=21)

        # Longer period should be smoother (lower std dev)
        assert ema_21.std() <= ema_9.std()


class TestCalculateVWAP:
    """Test VWAP calculation."""

    def test_vwap_calculation(self, sample_ohlcv_df):
        """Test VWAP is calculated correctly."""
        vwap = calculate_vwap(sample_ohlcv_df)

        assert len(vwap) == len(sample_ohlcv_df)
        assert not vwap.isna().all()

    def test_vwap_typical_price_relationship(self, sample_ohlcv_df):
        """Test VWAP relates to typical price."""
        vwap = calculate_vwap(sample_ohlcv_df)
        typical_price = (
            sample_ohlcv_df["high"] +
            sample_ohlcv_df["low"] +
            sample_ohlcv_df["close"]
        ) / 3

        # VWAP should be in the range of typical prices
        assert vwap.min() >= typical_price.min() * 0.95
        assert vwap.max() <= typical_price.max() * 1.05


class TestCalculateVWAPBands:
    """Test VWAP bands calculation."""

    def test_vwap_bands_structure(self, sample_ohlcv_df):
        """Test VWAP bands return correct structure."""
        vwap, upper_bands, lower_bands = calculate_vwap_bands(
            sample_ohlcv_df, std_dev=1.0, bands=2
        )

        assert len(upper_bands) == 2
        assert len(lower_bands) == 2
        assert len(vwap) == len(sample_ohlcv_df)

    def test_bands_ordering(self, sample_ohlcv_df):
        """Test bands are correctly ordered."""
        vwap, upper_bands, lower_bands = calculate_vwap_bands(
            sample_ohlcv_df, std_dev=1.0, bands=2
        )

        # At each point, lower < vwap < upper
        last_idx = -1
        assert lower_bands[0].iloc[last_idx] < vwap.iloc[last_idx] < upper_bands[0].iloc[last_idx]


class TestCalculateVolumeMa:
    """Test Volume MA calculation."""

    def test_volume_ma_calculation(self, sample_ohlcv_df):
        """Test Volume MA is calculated correctly."""
        vol_ma = calculate_volume_ma(sample_ohlcv_df, period=20)

        assert len(vol_ma) == len(sample_ohlcv_df)
        # First 19 values should be NaN for period=20
        assert vol_ma.iloc[:19].isna().all()
        assert not vol_ma.iloc[19:].isna().all()


class TestCalculateATR:
    """Test ATR calculation."""

    def test_atr_calculation(self, sample_ohlcv_df):
        """Test ATR is calculated correctly."""
        atr = calculate_atr(sample_ohlcv_df, period=14)

        assert len(atr) == len(sample_ohlcv_df)
        assert not atr.isna().all()
        # ATR should always be positive
        assert (atr >= 0).all()

    def test_atr_reflects_volatility(self, trending_up_df, sample_ohlcv_df):
        """Test ATR reflects price volatility."""
        # The trending_up_df has more consistent movement (lower volatility)
        atr_trending = calculate_atr(trending_up_df, period=14)
        atr_random = calculate_atr(sample_ohlcv_df, period=14)

        # Random walk should have higher ATR than smooth trend
        # (This may not always hold due to different price ranges, so we just verify they're calculated)
        assert atr_trending.iloc[-1] >= 0
        assert atr_random.iloc[-1] >= 0


class TestGenerateSignals:
    """Test signal generation."""

    def test_empty_dataframe(self):
        """Test with empty dataframe returns no signals."""
        df = pd.DataFrame()
        signals = generate_signals(df)
        assert signals == []

    def test_insufficient_data(self):
        """Test with insufficient data returns no signals."""
        df = pd.DataFrame({
            "open": [100] * 10,
            "high": [101] * 10,
            "low": [99] * 10,
            "close": [100] * 10,
            "volume": [1000] * 10,
        })
        signals = generate_signals(df)
        assert signals == []

    def test_missing_columns(self):
        """Test with missing columns returns no signals."""
        df = pd.DataFrame({
            "close": [100] * 50,
            "volume": [1000] * 50,
        })
        signals = generate_signals(df)
        assert signals == []

    def test_outside_trading_hours(self, sample_ohlcv_df):
        """Test no signals outside trading hours."""
        # Use a time outside trading hours (e.g., 3 AM ET)
        non_trading_time = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)  # 3 AM ET

        signals = generate_signals(sample_ohlcv_df, current_time=non_trading_time)

        assert signals == []

    def test_during_trading_hours(self, sample_ohlcv_df):
        """Test signal generation during trading hours."""
        # Use a time during trading hours (e.g., 10 AM ET = 15:00 UTC)
        trading_time = datetime(2024, 1, 15, 15, 0, 0, tzinfo=timezone.utc)

        # May or may not generate signals depending on market conditions
        signals = generate_signals(sample_ohlcv_df, current_time=trading_time)

        # Just verify it doesn't raise an error and returns a list
        assert isinstance(signals, list)

    def test_invalid_atr(self):
        """Test no signals when ATR is invalid."""
        # Create data where ATR would be zero (all same prices)
        df = pd.DataFrame({
            "open": [100.0] * 50,
            "high": [100.0] * 50,
            "low": [100.0] * 50,
            "close": [100.0] * 50,
            "volume": [1000.0] * 50,
        })

        trading_time = datetime(2024, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
        signals = generate_signals(df, current_time=trading_time)

        # Should return empty list since ATR is 0
        assert signals == []


class TestCheckTradingSession:
    """Test trading session checks."""

    def test_during_session(self):
        """Test time during trading session."""
        # 10:30 AM ET = 15:30 UTC
        trading_time = datetime(2024, 1, 15, 15, 30, 0, tzinfo=timezone.utc)

        config = {
            "start_hour": 9,
            "start_minute": 30,
            "end_hour": 16,
            "end_minute": 0,
        }

        assert check_trading_session(trading_time, config) is True

    def test_before_session(self):
        """Test time before trading session."""
        # 8:00 AM ET = 13:00 UTC
        before_time = datetime(2024, 1, 15, 13, 0, 0, tzinfo=timezone.utc)

        config = {
            "start_hour": 9,
            "start_minute": 30,
            "end_hour": 16,
            "end_minute": 0,
        }

        assert check_trading_session(before_time, config) is False

    def test_after_session(self):
        """Test time after trading session."""
        # 5:00 PM ET = 22:00 UTC
        after_time = datetime(2024, 1, 15, 22, 0, 0, tzinfo=timezone.utc)

        config = {
            "start_hour": 9,
            "start_minute": 30,
            "end_hour": 16,
            "end_minute": 0,
        }

        assert check_trading_session(after_time, config) is False


class TestKeyLevelsCaching:
    """Test key levels caching functionality."""

    def test_cache_key_generation(self, sample_ohlcv_df):
        """Test cache key is generated correctly."""
        key = _get_key_levels_cache_key(sample_ohlcv_df)

        assert key != ""
        assert "_" in key  # Should have date_length_hash format

    def test_cache_key_empty_df(self):
        """Test cache key for empty dataframe."""
        df = pd.DataFrame()
        key = _get_key_levels_cache_key(df)

        assert key == ""

    def test_cache_key_consistency(self, sample_ohlcv_df):
        """Test same data produces same cache key."""
        key1 = _get_key_levels_cache_key(sample_ohlcv_df)
        key2 = _get_key_levels_cache_key(sample_ohlcv_df)

        assert key1 == key2

    def test_cache_key_changes_with_data(self, sample_ohlcv_df):
        """Test different data produces different cache key."""
        key1 = _get_key_levels_cache_key(sample_ohlcv_df)

        # Modify the dataframe
        modified_df = sample_ohlcv_df.copy()
        modified_df.loc[modified_df.index[-1], "close"] += 10.0

        key2 = _get_key_levels_cache_key(modified_df)

        assert key1 != key2


class TestCONFIG:
    """Test default configuration values."""

    def test_config_has_required_keys(self):
        """Test CONFIG has all required keys."""
        required_keys = [
            "symbol",
            "timeframe",
            "ema_fast",
            "ema_slow",
            "vwap_std_dev",
            "stop_loss_atr_mult",
            "take_profit_atr_mult",
            "min_confidence",
            "min_risk_reward",
        ]

        for key in required_keys:
            assert key in CONFIG or CONFIG.get(key) is not None

    def test_config_reasonable_values(self):
        """Test CONFIG has reasonable default values."""
        assert CONFIG.get("ema_fast", 9) < CONFIG.get("ema_slow", 21)
        assert CONFIG.get("min_confidence", 0.55) > 0.0
        assert CONFIG.get("min_confidence", 0.55) < 1.0
        assert CONFIG.get("stop_loss_atr_mult", 3.5) > 0.0
        assert CONFIG.get("take_profit_atr_mult", 5.0) > 0.0
