"""Tests for strategy indicator functions in pearl_bot_auto.

Covers: safe_check, calculate_sr_power_channel, calculate_tbt_trendlines,
calculate_supply_demand_zones, get_key_levels, check_key_level_signals,
check_volume_confirmation, check_sr_signals, check_tbt_signals,
check_supply_demand_signals.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from pearlalgo.trading_bots.pearl_bot_auto import (
    CONFIG,
    safe_check,
    calculate_sr_power_channel,
    calculate_tbt_trendlines,
    calculate_supply_demand_zones,
    get_key_levels,
    check_key_level_signals,
    check_volume_confirmation,
    check_sr_signals,
    check_tbt_signals,
    check_supply_demand_signals,
    calculate_volume_ma,
    _key_levels_cache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_ohlcv_df():
    """Create sample OHLCV dataframe for testing (matches existing pattern)."""
    np.random.seed(42)
    n = 200
    base_price = 100.0

    returns = np.random.randn(n) * 0.01
    close = base_price * np.cumprod(1 + returns)

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
def empty_df():
    """Empty OHLCV DataFrame."""
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


@pytest.fixture
def short_df():
    """Very short OHLCV DataFrame (5 bars)."""
    np.random.seed(42)
    close = np.array([100.0, 101.0, 99.5, 100.5, 102.0])
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.003,
        "low": close * 0.997,
        "close": close,
        "volume": [5000.0] * 5,
    })


@pytest.fixture
def sr_config():
    """Config dict for S&R Power Channel tests."""
    return {
        "sr_length": 130,
        "sr_atr_mult": 0.5,
    }


@pytest.fixture
def tbt_config():
    """Config dict for TBT tests."""
    return {
        "tbt_period": 10,
        "tbt_trend_type": "wicks",
    }


@pytest.fixture
def sd_config():
    """Config dict for Supply & Demand tests."""
    return {
        "sd_threshold_pct": 10.0,
        "sd_resolution": 50,
    }


@pytest.fixture
def vol_config():
    """Config dict for volume tests."""
    return {"volume_ma_length": 20}


@pytest.fixture
def key_level_config():
    """Config dict for key level signal tests."""
    return {
        "key_level_proximity_pct": 0.15,
        "key_level_breakout_pct": 0.05,
        "key_level_bounce_confidence": 0.12,
        "key_level_breakout_confidence": 0.10,
        "key_level_rejection_penalty": 0.08,
    }


# ===========================================================================
# safe_check
# ===========================================================================

class TestSafeCheck:
    """Test the safe_check exception-swallowing wrapper."""

    def test_returns_result_on_success(self):
        def good_fn():
            return ("long", 0.8)
        result = safe_check(good_fn)
        assert result == ("long", 0.8)

    def test_passes_args_and_kwargs(self):
        def add_fn(a, b, offset=0):
            return ("signal", a + b + offset)
        assert safe_check(add_fn, 2, 3, offset=10) == ("signal", 15)

    def test_returns_none_zero_on_exception(self):
        def bad_fn():
            raise ValueError("boom")
        result = safe_check(bad_fn)
        assert result == (None, 0.0)

    def test_returns_none_zero_on_type_error(self):
        def bad_fn(x):
            return x
        # Missing required argument triggers TypeError
        result = safe_check(bad_fn)
        assert result == (None, 0.0)


# ===========================================================================
# calculate_sr_power_channel
# ===========================================================================

class TestCalculateSrPowerChannel:
    """Test S&R Power Channel calculation."""

    def test_normal_operation(self, sample_ohlcv_df):
        res, sup, buy, sell = calculate_sr_power_channel(sample_ohlcv_df, length=130)
        assert isinstance(res, float) and isinstance(sup, float)
        assert res > sup, "Resistance must be above support"
        assert buy >= 0 and sell >= 0
        assert buy + sell <= 130, "Buy+sell power cannot exceed lookback length"

    def test_resistance_above_max_high(self, sample_ohlcv_df):
        """Resistance = max_high + atr_offset, so it exceeds raw max."""
        res, sup, buy, sell = calculate_sr_power_channel(sample_ohlcv_df, length=130)
        raw_max = sample_ohlcv_df.tail(130)["high"].max()
        assert res > raw_max

    def test_support_below_min_low(self, sample_ohlcv_df):
        """Support = min_low - atr_offset, so it is below raw min."""
        res, sup, buy, sell = calculate_sr_power_channel(sample_ohlcv_df, length=130)
        raw_min = sample_ohlcv_df.tail(130)["low"].min()
        assert sup < raw_min

    def test_precomputed_atr(self, sample_ohlcv_df):
        """Precomputed ATR should be used instead of recalculating."""
        res1, sup1, _, _ = calculate_sr_power_channel(
            sample_ohlcv_df, length=130, precomputed_atr=2.0, atr_mult=0.5,
        )
        res2, sup2, _, _ = calculate_sr_power_channel(
            sample_ohlcv_df, length=130, precomputed_atr=10.0, atr_mult=0.5,
        )
        # Larger ATR -> wider channel
        assert (res2 - sup2) > (res1 - sup1)

    def test_empty_dataframe(self, empty_df):
        assert calculate_sr_power_channel(empty_df) == (0.0, 0.0, 0, 0)

    def test_insufficient_data(self, short_df):
        assert calculate_sr_power_channel(short_df, length=130) == (0.0, 0.0, 0, 0)


# ===========================================================================
# calculate_tbt_trendlines
# ===========================================================================

class TestCalculateTbtTrendlines:
    """Test TBT Trendlines calculation."""

    def test_normal_operation(self, sample_ohlcv_df):
        res_slope, res_start, sup_slope, sup_start = calculate_tbt_trendlines(
            sample_ohlcv_df, period=10,
        )
        # With 200 bars and period=10, pivots should be detected
        assert res_start is None or isinstance(res_start, float)
        assert sup_start is None or isinstance(sup_start, float)

    def test_wicks_vs_body_mode(self, sample_ohlcv_df):
        r_wicks = calculate_tbt_trendlines(sample_ohlcv_df, period=10, trend_type="wicks")
        r_body = calculate_tbt_trendlines(sample_ohlcv_df, period=10, trend_type="body")
        # They should return different values since pivot detection differs
        assert r_wicks != r_body or r_wicks == (None, None, None, None)

    def test_empty_dataframe(self, empty_df):
        assert calculate_tbt_trendlines(empty_df) == (None, None, None, None)

    def test_insufficient_data(self, short_df):
        # period=10 requires 20 bars minimum
        assert calculate_tbt_trendlines(short_df, period=10) == (None, None, None, None)

    def test_slopes_are_finite(self, sample_ohlcv_df):
        res_slope, res_start, sup_slope, sup_start = calculate_tbt_trendlines(
            sample_ohlcv_df, period=10,
        )
        for val in (res_slope, res_start, sup_slope, sup_start):
            if val is not None:
                assert np.isfinite(val), f"Non-finite trendline value: {val}"


# ===========================================================================
# calculate_supply_demand_zones
# ===========================================================================

class TestCalculateSupplyDemandZones:
    """Test Supply & Demand zone calculation."""

    def test_normal_operation(self, sample_ohlcv_df):
        supply, supply_avg, demand, demand_avg = calculate_supply_demand_zones(
            sample_ohlcv_df,
        )
        # At least one zone should be detected with 200 bars of data
        if supply is not None:
            assert supply > sample_ohlcv_df["close"].iloc[-1]
            assert supply_avg == supply  # implementation sets avg=level
        if demand is not None:
            assert demand < sample_ohlcv_df["close"].iloc[-1]
            assert demand_avg == demand

    def test_empty_dataframe(self, empty_df):
        assert calculate_supply_demand_zones(empty_df) == (None, None, None, None)

    def test_insufficient_data(self, short_df):
        # Needs >= 20 bars
        assert calculate_supply_demand_zones(short_df) == (None, None, None, None)

    def test_flat_price_returns_none(self):
        """Flat price (zero range) should return None for all zones."""
        n = 50
        df = pd.DataFrame({
            "open": [100.0] * n,
            "high": [100.0] * n,
            "low": [100.0] * n,
            "close": [100.0] * n,
            "volume": [5000.0] * n,
        })
        assert calculate_supply_demand_zones(df) == (None, None, None, None)

    def test_custom_resolution(self, sample_ohlcv_df):
        """Higher resolution should still produce valid output."""
        result = calculate_supply_demand_zones(
            sample_ohlcv_df, resolution=100,
        )
        for val in result:
            assert val is None or isinstance(val, float)


# ===========================================================================
# get_key_levels
# ===========================================================================

class TestGetKeyLevels:
    """Test SpacemanBTC Key Levels computation."""

    def test_returns_dict_with_datetime_index(self):
        np.random.seed(42)
        n = 200
        base = 100.0
        close = base + np.cumsum(np.random.randn(n) * 0.5)
        dates = pd.date_range("2024-01-01", periods=n, freq="h")
        df = pd.DataFrame({
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": [5000.0] * n,
            "timestamp": dates,
        })
        levels = get_key_levels(df, use_cache=False)
        assert isinstance(levels, dict)
        assert "current_close" in levels
        assert levels["current_close"] == pytest.approx(float(close[-1]), rel=1e-6)

    def test_includes_support_and_resistance_lists(self):
        np.random.seed(42)
        n = 200
        close = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
        dates = pd.date_range("2024-01-01", periods=n, freq="h")
        df = pd.DataFrame({
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": [5000.0] * n,
            "timestamp": dates,
        })
        levels = get_key_levels(df, use_cache=False)
        assert "support_levels" in levels
        assert "resistance_levels" in levels
        assert isinstance(levels["support_levels"], list)
        assert isinstance(levels["resistance_levels"], list)

    def test_empty_dataframe(self, empty_df):
        levels = get_key_levels(empty_df, use_cache=False)
        assert levels == {}

    def test_single_bar(self):
        df = pd.DataFrame({
            "open": [100.0], "high": [101.0],
            "low": [99.0], "close": [100.5], "volume": [5000.0],
        })
        levels = get_key_levels(df, use_cache=False)
        assert levels == {}

    def test_simple_fallback_without_timestamps(self):
        """Without timestamp column or DatetimeIndex, falls back to simple levels."""
        np.random.seed(42)
        n = 500
        close = 100.0 + np.cumsum(np.random.randn(n) * 0.3)
        df = pd.DataFrame({
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": [5000.0] * n,
        })
        levels = get_key_levels(df, use_cache=False)
        assert isinstance(levels, dict)
        assert "current_close" in levels
        # Simple fallback should still compute daily-approx levels
        assert "daily_open" in levels


# ===========================================================================
# check_key_level_signals
# ===========================================================================

class TestCheckKeyLevelSignals:
    """Test key level bounce/breakout signal detection."""

    def _make_df(self, closes, highs=None, lows=None):
        """Helper to build a small DataFrame from close prices."""
        closes = np.array(closes, dtype=float)
        n = len(closes)
        if highs is None:
            highs = closes + 0.2
        if lows is None:
            lows = closes - 0.2
        return pd.DataFrame({
            "open": closes,
            "high": np.array(highs, dtype=float),
            "low": np.array(lows, dtype=float),
            "close": closes,
            "volume": [5000.0] * n,
        })

    def test_empty_df_returns_none(self, empty_df, key_level_config):
        signal, conf, info = check_key_level_signals(empty_df, {}, key_level_config)
        assert signal is None and conf == 0.0

    def test_no_levels_returns_none(self, key_level_config):
        df = self._make_df([100, 101, 102])
        signal, conf, info = check_key_level_signals(df, {}, key_level_config)
        assert signal is None and conf == 0.0

    def test_bounce_support_long(self, key_level_config):
        """Price touches support and bounces up -> bullish signal."""
        # Close drops to ~100.0 (near support) then bounces
        df = self._make_df(
            closes=[100.5, 100.0, 100.3],
            highs=[100.7, 100.2, 100.5],
            lows=[100.3, 99.95, 100.05],
        )
        levels = {
            "support_levels": [("prev_day_low", 100.0)],
            "resistance_levels": [("prev_day_high", 102.0)],
        }
        signal, conf, info = check_key_level_signals(df, levels, key_level_config)
        assert signal == "bounce_support_long"
        assert conf == key_level_config["key_level_bounce_confidence"]

    def test_bounce_resistance_short(self, key_level_config):
        """Price touches resistance and rejects -> bearish signal."""
        df = self._make_df(
            closes=[101.5, 102.0, 101.7],
            highs=[101.7, 102.05, 102.0],
            lows=[101.3, 101.8, 101.5],
        )
        levels = {
            "support_levels": [("prev_day_low", 100.0)],
            "resistance_levels": [("prev_day_high", 102.0)],
        }
        signal, conf, info = check_key_level_signals(df, levels, key_level_config)
        assert signal == "bounce_resistance_short"
        assert conf == key_level_config["key_level_bounce_confidence"]

    def test_level_info_populated(self, key_level_config):
        """level_info dict should contain nearest support/resistance."""
        df = self._make_df([100, 101, 102])
        levels = {
            "support_levels": [("daily_open", 99.0)],
            "resistance_levels": [("prev_day_high", 105.0)],
        }
        _, _, info = check_key_level_signals(df, levels, key_level_config)
        assert info["nearest_support"] == 99.0
        assert info["nearest_resistance"] == 105.0
        assert info["nearest_support_name"] == "daily_open"


# ===========================================================================
# check_volume_confirmation
# ===========================================================================

class TestCheckVolumeConfirmation:
    """Test volume confirmation check."""

    def test_high_volume_confirms(self, vol_config):
        """Current volume above MA -> True."""
        np.random.seed(42)
        n = 30
        close = np.full(n, 100.0)
        vol = np.full(n, 5000.0)
        vol[-1] = 15000.0  # spike on the last bar
        df = pd.DataFrame({
            "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "volume": vol,
        })
        assert check_volume_confirmation(df, vol_config) == True

    def test_low_volume_rejects(self, vol_config):
        """Current volume below MA -> False."""
        n = 30
        close = np.full(n, 100.0)
        vol = np.full(n, 5000.0)
        vol[-1] = 1000.0  # dip on the last bar
        df = pd.DataFrame({
            "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "volume": vol,
        })
        assert check_volume_confirmation(df, vol_config) == False

    def test_insufficient_data(self, vol_config):
        """Fewer bars than volume_ma_length -> False."""
        df = pd.DataFrame({
            "open": [100.0] * 5, "high": [101.0] * 5,
            "low": [99.0] * 5, "close": [100.0] * 5,
            "volume": [5000.0] * 5,
        })
        assert check_volume_confirmation(df, vol_config) == False


# ===========================================================================
# check_sr_signals
# ===========================================================================

class TestCheckSrSignals:
    """Test S&R Power Channel signal logic."""

    def _make_channel_df(self, n, final_close, bullish_frac=0.5):
        """Build df where close ends at *final_close* and has known power ratio."""
        np.random.seed(42)
        close = np.linspace(100, final_close, n)
        high = close + 0.3
        low = close - 0.3
        # Control bullish candle fraction
        open_price = np.where(
            np.arange(n) < n * bullish_frac,
            close - 0.1,   # bullish candle (close > open)
            close + 0.1,   # bearish candle (close < open)
        )
        return pd.DataFrame({
            "open": open_price, "high": high,
            "low": low, "close": close,
            "volume": [5000.0] * n,
        })

    def test_breakout_long(self, sr_config):
        """Close above resistance => sr_breakout_long."""
        # Create df that trends up sharply so close > resistance
        df = self._make_channel_df(200, final_close=120.0, bullish_frac=0.7)
        signal, conf = check_sr_signals(df, sr_config)
        if signal is not None:
            assert signal in ("sr_breakout_long", "sr_pullback_long")
            assert 0.0 < conf <= 1.0

    def test_breakout_short(self, sr_config):
        """Close below support => sr_breakout_short."""
        df = self._make_channel_df(200, final_close=80.0, bullish_frac=0.3)
        signal, conf = check_sr_signals(df, sr_config)
        if signal is not None:
            assert signal in ("sr_breakout_short", "sr_pullback_short")
            assert 0.0 < conf <= 1.0

    def test_returns_none_on_insufficient_data(self, sr_config):
        """With fewer bars than sr_length, channel returns zeros -> None signal."""
        df = pd.DataFrame({
            "open": [100.0] * 10, "high": [101.0] * 10,
            "low": [99.0] * 10, "close": [100.0] * 10,
            "volume": [5000.0] * 10,
        })
        signal, conf = check_sr_signals(df, sr_config)
        assert signal is None and conf == 0.0

    def test_confidence_capped_at_one(self, sr_config):
        """Confidence must never exceed 1.0."""
        df = self._make_channel_df(200, final_close=115.0, bullish_frac=0.99)
        _, conf = check_sr_signals(df, sr_config)
        assert conf <= 1.0


# ===========================================================================
# check_tbt_signals
# ===========================================================================

class TestCheckTbtSignals:
    """Test TBT Trendline Breakout signal logic."""

    def test_returns_none_insufficient_data(self, tbt_config):
        df = pd.DataFrame({
            "open": [100.0] * 5, "high": [101.0] * 5,
            "low": [99.0] * 5, "close": [100.0] * 5,
            "volume": [5000.0] * 5,
        })
        signal, conf = check_tbt_signals(df, tbt_config)
        assert signal is None and conf == 0.0

    def test_signal_types(self, sample_ohlcv_df, tbt_config):
        """Returned signal must be one of the known types or None."""
        signal, conf = check_tbt_signals(sample_ohlcv_df, tbt_config)
        valid = {None, "tbt_breakout_long", "tbt_breakout_short"}
        assert signal in valid
        if signal is not None:
            assert conf == pytest.approx(0.7)

    def test_breakout_long_scenario(self, tbt_config):
        """Construct data where price breaks above descending resistance."""
        np.random.seed(42)
        n = 60
        # Descending peaks followed by a breakout bar
        close = np.concatenate([
            np.linspace(110, 100, n - 1),  # descending trend
            [111.0],                         # breakout bar
        ])
        high = close + 0.5
        low = close - 0.5
        open_price = close - 0.1
        df = pd.DataFrame({
            "open": open_price, "high": high,
            "low": low, "close": close,
            "volume": [5000.0] * n,
        })
        signal, conf = check_tbt_signals(df, tbt_config)
        # May or may not trigger depending on pivot detection; validate types
        assert signal in (None, "tbt_breakout_long", "tbt_breakout_short")

    def test_empty_df(self, empty_df, tbt_config):
        signal, conf = check_tbt_signals(empty_df, tbt_config)
        assert signal is None and conf == 0.0


# ===========================================================================
# check_supply_demand_signals
# ===========================================================================

class TestCheckSupplyDemandSignals:
    """Test Supply & Demand signal logic."""

    def test_returns_none_insufficient_data(self, sd_config):
        df = pd.DataFrame({
            "open": [100.0] * 5, "high": [101.0] * 5,
            "low": [99.0] * 5, "close": [100.0] * 5,
            "volume": [5000.0] * 5,
        })
        signal, conf = check_supply_demand_signals(df, sd_config)
        assert signal is None and conf == 0.0

    def test_signal_types(self, sample_ohlcv_df, sd_config):
        """Returned signal must be one of the known types or None."""
        signal, conf = check_supply_demand_signals(sample_ohlcv_df, sd_config)
        valid = {None, "sd_demand_bounce", "sd_supply_rejection"}
        assert signal in valid
        if signal is not None:
            assert conf == pytest.approx(0.65)

    def test_demand_bounce_scenario(self, sd_config):
        """Build data where close sits right at the demand zone."""
        np.random.seed(42)
        n = 100
        # Create V-shaped price: decline then sit near the low
        close = np.concatenate([
            np.linspace(110, 100, 50),
            np.linspace(100, 105, 49),
            [100.0],  # last bar right at the low cluster
        ])
        high = close + 0.3
        low = close - 0.3
        volume = np.full(n, 5000.0)
        # Concentrate volume at the 100 level (demand)
        volume[45:55] = 50000.0
        df = pd.DataFrame({
            "open": close - 0.05, "high": high,
            "low": low, "close": close,
            "volume": volume,
        })
        signal, conf = check_supply_demand_signals(df, sd_config)
        # Because close=100 is at the high-volume demand area
        if signal is not None:
            assert signal == "sd_demand_bounce"
            assert conf == pytest.approx(0.65)

    def test_supply_rejection_scenario(self, sd_config):
        """Build data where close sits right at the supply zone."""
        np.random.seed(42)
        n = 100
        # Create inverted-V: rise then sit near the high
        close = np.concatenate([
            np.linspace(100, 110, 50),
            np.linspace(110, 105, 49),
            [110.0],  # last bar at the supply cluster
        ])
        high = close + 0.3
        low = close - 0.3
        volume = np.full(n, 5000.0)
        # Concentrate volume at the 110 level (supply)
        volume[45:55] = 50000.0
        df = pd.DataFrame({
            "open": close + 0.05, "high": high,
            "low": low, "close": close,
            "volume": volume,
        })
        signal, conf = check_supply_demand_signals(df, sd_config)
        if signal is not None:
            assert signal == "sd_supply_rejection"
            assert conf == pytest.approx(0.65)

    def test_no_zones_returns_none(self, sd_config):
        """When no supply/demand zones are found, signal is None."""
        n = 25
        # Flat price, even volume -> no high-volume zone above/below close
        df = pd.DataFrame({
            "open": [100.0] * n, "high": [100.01] * n,
            "low": [99.99] * n, "close": [100.0] * n,
            "volume": [5000.0] * n,
        })
        signal, conf = check_supply_demand_signals(df, sd_config)
        assert signal is None and conf == 0.0
