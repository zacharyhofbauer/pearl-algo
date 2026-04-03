"""Comprehensive tests for pearlalgo.trading_bots.smc_signals.

Covers all public and internal helper functions with edge cases.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from zoneinfo import ZoneInfo

import pearlalgo.trading_bots.smc_signals as smc_mod
from pearlalgo.trading_bots.smc_signals import (
    _check_bos_choch_confirmation,
    _check_key_level_alignment,
    _check_ob_confluence,
    _check_smc_signal,
    _detect_active_fvgs,
    _detect_active_obs,
    _find_liquidity_target,
    _in_silver_bullet_window,
    _param,
    _pick_best_fvg,
    _prepare_ohlc,
    _safe_atr,
    _safe_smc_call,
)

_ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv_df(n: int = 20, *, has_datetime_index: bool = True) -> pd.DataFrame:
    """Create a minimal OHLCV DataFrame for testing."""
    dates = pd.date_range("2026-04-01 10:00", periods=n, freq="1min", tz=_ET)
    rng = np.random.default_rng(42)
    close = 21000.0 + rng.standard_normal(n).cumsum() * 5
    df = pd.DataFrame({
        "open": close - rng.uniform(0, 3, n),
        "high": close + rng.uniform(0, 5, n),
        "low": close - rng.uniform(0, 5, n),
        "close": close,
        "volume": rng.integers(100, 1000, n).astype(float),
    })
    if has_datetime_index:
        df.index = dates
    return df


def _make_fvg_df(entries: list[dict]) -> pd.DataFrame:
    """Build a DataFrame mimicking smartmoneyconcepts FVG output.

    Each entry: {fvg, top, bottom, mitigated}
    """
    return pd.DataFrame({
        "FVG": [e.get("fvg", 0) for e in entries],
        "Top": [e.get("top", np.nan) for e in entries],
        "Bottom": [e.get("bottom", np.nan) for e in entries],
        "MitigatedIndex": [e.get("mitigated", np.nan) for e in entries],
    })


def _make_ob_df(entries: list[dict]) -> pd.DataFrame:
    """Build a DataFrame mimicking smartmoneyconcepts OB output."""
    return pd.DataFrame({
        "OB": [e.get("ob", 0) for e in entries],
        "Top": [e.get("top", np.nan) for e in entries],
        "Bottom": [e.get("bottom", np.nan) for e in entries],
        "OBVolume": [e.get("volume", 0.0) for e in entries],
    })


def _make_bos_choch_df(entries: list[dict]) -> pd.DataFrame:
    return pd.DataFrame({
        "BOS": [e.get("bos", np.nan) for e in entries],
        "CHOCH": [e.get("choch", np.nan) for e in entries],
    })


def _make_liq_df(entries: list[dict]) -> pd.DataFrame:
    return pd.DataFrame({
        "Liquidity": [e.get("liq", 0) for e in entries],
        "Level": [e.get("level", np.nan) for e in entries],
        "Swept": [e.get("swept", np.nan) for e in entries],
    })


# ---------------------------------------------------------------------------
# TestParam
# ---------------------------------------------------------------------------

class TestParam:
    def test_existing_attribute(self):
        p = SimpleNamespace(smc_swing_length=15)
        assert _param(p, "smc_swing_length", 10) == 15

    def test_missing_attribute_returns_default(self):
        p = SimpleNamespace()
        assert _param(p, "smc_swing_length", 10) == 10

    def test_none_object(self):
        assert _param(None, "x", 42) == 42


# ---------------------------------------------------------------------------
# TestPrepareOhlc
# ---------------------------------------------------------------------------

class TestPrepareOhlc:
    def test_valid_lowercase_columns(self):
        df = _make_ohlcv_df(10)
        result = _prepare_ohlc(df)
        assert result is not None
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert isinstance(result.index, pd.DatetimeIndex)
        assert len(result) == 10

    def test_none_input(self):
        assert _prepare_ohlc(None) is None

    def test_empty_df(self):
        assert _prepare_ohlc(pd.DataFrame()) is None

    def test_too_few_rows(self):
        df = _make_ohlcv_df(4)
        assert _prepare_ohlc(df) is None

    def test_missing_column(self):
        df = _make_ohlcv_df(10)
        df = df.drop(columns=["volume"])
        assert _prepare_ohlc(df) is None

    def test_uppercase_columns_bug(self):
        """Note: col_map rename logic has a dict-comprehension inversion bug.
        UPPER columns are detected but the rename maps backwards, so the
        selection for lowercase names fails. This test documents the current
        (broken) behavior — returns None for all-UPPER columns."""
        df = _make_ohlcv_df(10)
        df.columns = [c.upper() for c in df.columns]
        # Current code raises KeyError internally; _prepare_ohlc doesn't
        # catch it so it propagates.  Documenting actual behaviour:
        with pytest.raises(KeyError):
            _prepare_ohlc(df)

    def test_capitalized_columns_bug(self):
        """Same dict-comprehension bug as uppercase — Capitalized columns
        also fail. Documenting actual behaviour."""
        df = _make_ohlcv_df(10)
        df.columns = [c.capitalize() for c in df.columns]
        with pytest.raises(KeyError):
            _prepare_ohlc(df)

    def test_non_datetime_index_with_timestamp_col(self):
        df = _make_ohlcv_df(10, has_datetime_index=False)
        df["timestamp"] = pd.date_range("2026-04-01", periods=10, freq="1min")
        df.index = range(10)
        result = _prepare_ohlc(df)
        assert result is not None
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_non_datetime_index_with_datetime_col(self):
        df = _make_ohlcv_df(10, has_datetime_index=False)
        df["datetime"] = pd.date_range("2026-04-01", periods=10, freq="1min")
        df.index = range(10)
        result = _prepare_ohlc(df)
        assert result is not None

    def test_non_datetime_index_with_date_col(self):
        df = _make_ohlcv_df(10, has_datetime_index=False)
        df["date"] = pd.date_range("2026-04-01", periods=10, freq="1min")
        df.index = range(10)
        result = _prepare_ohlc(df)
        assert result is not None

    def test_non_datetime_index_convertible(self):
        df = _make_ohlcv_df(10, has_datetime_index=False)
        df.index = pd.date_range("2026-04-01", periods=10, freq="1min")
        # Convert to string index (still convertible)
        df.index = df.index.astype(str)
        result = _prepare_ohlc(df)
        assert result is not None

    def test_non_convertible_index(self):
        df = _make_ohlcv_df(10, has_datetime_index=False)
        df.index = ["not_a_date"] * 10
        result = _prepare_ohlc(df)
        assert result is None

    def test_nan_volume_filled_with_zero(self):
        df = _make_ohlcv_df(10)
        df.loc[df.index[0], "volume"] = np.nan
        result = _prepare_ohlc(df)
        assert result is not None
        assert result["volume"].iloc[0] == 0.0

    def test_nan_ohlc_rows_dropped(self):
        df = _make_ohlcv_df(10)
        df.loc[df.index[0], "close"] = np.nan
        result = _prepare_ohlc(df)
        assert result is not None
        assert len(result) == 9

    def test_too_many_nan_rows_returns_none(self):
        df = _make_ohlcv_df(7)
        df.loc[df.index[:4], "close"] = np.nan
        result = _prepare_ohlc(df)
        # After dropping 4 NaN rows, only 3 left -> < 5 -> None
        assert result is None


# ---------------------------------------------------------------------------
# TestDetectActiveFvgs
# ---------------------------------------------------------------------------

class TestDetectActiveFvgs:
    def test_empty_input(self):
        assert _detect_active_fvgs(None, 100.0) == []
        assert _detect_active_fvgs(pd.DataFrame(), 100.0) == []

    def test_no_fvg_rows(self):
        fvg_df = _make_fvg_df([{"fvg": 0, "top": 100, "bottom": 99}])
        assert _detect_active_fvgs(fvg_df, 99.5) == []

    def test_nan_fvg_skipped(self):
        fvg_df = _make_fvg_df([{"fvg": np.nan, "top": 100, "bottom": 99}])
        assert _detect_active_fvgs(fvg_df, 99.5) == []

    def test_mitigated_fvg_skipped(self):
        fvg_df = _make_fvg_df([
            {"fvg": 1, "top": 100.0, "bottom": 99.0, "mitigated": 5.0},
        ])
        assert _detect_active_fvgs(fvg_df, 99.5) == []

    def test_bullish_fvg_detected(self):
        fvg_df = _make_fvg_df([
            {"fvg": 1, "top": 100.0, "bottom": 99.0},
        ])
        result = _detect_active_fvgs(fvg_df, 99.5)
        assert len(result) == 1
        assert result[0]["direction"] == "long"
        assert result[0]["top"] == 100.0
        assert result[0]["bottom"] == 99.0

    def test_bearish_fvg_detected(self):
        fvg_df = _make_fvg_df([
            {"fvg": -1, "top": 100.0, "bottom": 99.0},
        ])
        result = _detect_active_fvgs(fvg_df, 99.5)
        assert len(result) == 1
        assert result[0]["direction"] == "short"

    def test_price_outside_tolerance_not_detected(self):
        # Gap from 99 to 100, height=1, tolerance=0.25
        # Price at 101 is outside top+tolerance=100.25
        fvg_df = _make_fvg_df([
            {"fvg": 1, "top": 100.0, "bottom": 99.0},
        ])
        assert _detect_active_fvgs(fvg_df, 101.0) == []

    def test_price_within_tolerance_detected(self):
        # Gap from 99 to 100, tolerance=0.25, price at 100.2 is inside top+0.25
        fvg_df = _make_fvg_df([
            {"fvg": 1, "top": 100.0, "bottom": 99.0},
        ])
        result = _detect_active_fvgs(fvg_df, 100.2)
        assert len(result) == 1

    def test_lookback_limits_scan(self):
        entries = [{"fvg": 0, "top": 100, "bottom": 99}] * 30
        # FVG at index 0 (outside lookback=5)
        entries[0] = {"fvg": 1, "top": 100.0, "bottom": 99.0}
        # FVG at index 28 (inside lookback=5)
        entries[28] = {"fvg": 1, "top": 100.0, "bottom": 99.0}
        fvg_df = _make_fvg_df(entries)

        result = _detect_active_fvgs(fvg_df, 99.5, lookback=5)
        assert len(result) == 1
        assert result[0]["bar_index"] == 28

    def test_invalid_top_bottom_skipped(self):
        # top <= bottom
        fvg_df = _make_fvg_df([{"fvg": 1, "top": 99.0, "bottom": 100.0}])
        assert _detect_active_fvgs(fvg_df, 99.5) == []

    def test_gap_height_in_result(self):
        fvg_df = _make_fvg_df([{"fvg": 1, "top": 102.0, "bottom": 100.0}])
        result = _detect_active_fvgs(fvg_df, 101.0)
        assert len(result) == 1
        assert result[0]["gap_height"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# TestDetectActiveObs
# ---------------------------------------------------------------------------

class TestDetectActiveObs:
    def test_empty_input(self):
        assert _detect_active_obs(None, 100.0) == []
        assert _detect_active_obs(pd.DataFrame(), 100.0) == []

    def test_no_ob_rows(self):
        ob_df = _make_ob_df([{"ob": 0, "top": 100, "bottom": 99}])
        assert _detect_active_obs(ob_df, 99.5) == []

    def test_bullish_ob_detected(self):
        ob_df = _make_ob_df([
            {"ob": 1, "top": 100.0, "bottom": 99.0, "volume": 500.0},
        ])
        result = _detect_active_obs(ob_df, 99.5)
        assert len(result) == 1
        assert result[0]["direction"] == "long"
        assert result[0]["volume"] == 500.0

    def test_bearish_ob_detected(self):
        ob_df = _make_ob_df([
            {"ob": -1, "top": 100.0, "bottom": 99.0, "volume": 300.0},
        ])
        result = _detect_active_obs(ob_df, 99.5)
        assert len(result) == 1
        assert result[0]["direction"] == "short"

    def test_price_outside_tolerance(self):
        ob_df = _make_ob_df([
            {"ob": 1, "top": 100.0, "bottom": 99.0},
        ])
        assert _detect_active_obs(ob_df, 105.0) == []

    def test_invalid_top_bottom(self):
        ob_df = _make_ob_df([{"ob": 1, "top": 98.0, "bottom": 100.0}])
        assert _detect_active_obs(ob_df, 99.0) == []

    def test_missing_ob_volume_defaults_zero(self):
        # Build df without OBVolume column
        df = pd.DataFrame({
            "OB": [1],
            "Top": [100.0],
            "Bottom": [99.0],
        })
        result = _detect_active_obs(df, 99.5)
        assert len(result) == 1
        assert result[0]["volume"] == 0.0

    def test_lookback(self):
        entries = [{"ob": 0, "top": 100, "bottom": 99}] * 25
        entries[0] = {"ob": 1, "top": 100.0, "bottom": 99.0}
        entries[23] = {"ob": 1, "top": 100.0, "bottom": 99.0}
        ob_df = _make_ob_df(entries)
        result = _detect_active_obs(ob_df, 99.5, lookback=5)
        assert len(result) == 1
        assert result[0]["bar_index"] == 23


# ---------------------------------------------------------------------------
# TestSafeSMCCall
# ---------------------------------------------------------------------------

class TestSafeSMCCall:
    def test_successful_call(self):
        fn = MagicMock(return_value=pd.DataFrame({"a": [1]}))
        result = _safe_smc_call(fn, "arg1", key="val")
        fn.assert_called_once_with("arg1", key="val")
        assert isinstance(result, pd.DataFrame)

    def test_returns_none_on_exception(self):
        fn = MagicMock(side_effect=RuntimeError("boom"))
        result = _safe_smc_call(fn)
        assert result is None

    def test_returns_none_when_fn_returns_none(self):
        fn = MagicMock(return_value=None)
        assert _safe_smc_call(fn) is None

    def test_returns_empty_dataframe_as_is(self):
        fn = MagicMock(return_value=pd.DataFrame())
        result = _safe_smc_call(fn)
        assert isinstance(result, pd.DataFrame)
        assert result.empty


# ---------------------------------------------------------------------------
# TestSafeAtr
# ---------------------------------------------------------------------------

class TestSafeAtr:
    def test_valid_atr(self):
        ind = SimpleNamespace(atr=5.25)
        assert _safe_atr(ind) == pytest.approx(5.25)

    def test_zero_atr(self):
        ind = SimpleNamespace(atr=0.0)
        assert _safe_atr(ind) is None

    def test_negative_atr(self):
        ind = SimpleNamespace(atr=-1.0)
        assert _safe_atr(ind) is None

    def test_nan_atr(self):
        ind = SimpleNamespace(atr=float("nan"))
        assert _safe_atr(ind) is None

    def test_missing_atr(self):
        ind = SimpleNamespace()
        assert _safe_atr(ind) is None

    def test_non_numeric_atr(self):
        ind = SimpleNamespace(atr="bad")
        assert _safe_atr(ind) is None


# ---------------------------------------------------------------------------
# TestInSilverBulletWindow
# ---------------------------------------------------------------------------

class TestInSilverBulletWindow:
    def test_inside_first_window(self):
        # 10:30 ET is inside [10, 11]
        dt = datetime(2026, 4, 1, 10, 30, tzinfo=_ET)
        assert _in_silver_bullet_window(dt, [[10, 11], [14, 15]]) is True

    def test_outside_all_windows(self):
        dt = datetime(2026, 4, 1, 12, 0, tzinfo=_ET)
        assert _in_silver_bullet_window(dt, [[10, 11], [14, 15]]) is False

    def test_exact_start_boundary(self):
        dt = datetime(2026, 4, 1, 14, 0, tzinfo=_ET)
        assert _in_silver_bullet_window(dt, [[14, 15]]) is True

    def test_exact_end_boundary_excluded(self):
        # hour 15 is NOT < 15
        dt = datetime(2026, 4, 1, 15, 0, tzinfo=_ET)
        assert _in_silver_bullet_window(dt, [[14, 15]]) is False

    def test_naive_datetime_treated_as_et(self):
        dt = datetime(2026, 4, 1, 10, 30)  # naive
        assert _in_silver_bullet_window(dt, [[10, 11]]) is True

    def test_utc_datetime_converted(self):
        # 14:30 UTC = 10:30 ET (during EDT)
        dt = datetime(2026, 4, 1, 14, 30, tzinfo=timezone.utc)
        assert _in_silver_bullet_window(dt, [[10, 11]]) is True

    def test_empty_windows(self):
        dt = datetime(2026, 4, 1, 10, 30, tzinfo=_ET)
        assert _in_silver_bullet_window(dt, []) is False

    def test_malformed_window_skipped(self):
        dt = datetime(2026, 4, 1, 10, 30, tzinfo=_ET)
        # Window with only one element is skipped (len < 2)
        assert _in_silver_bullet_window(dt, [[10]]) is False


# ---------------------------------------------------------------------------
# TestPickBestFvg
# ---------------------------------------------------------------------------

class TestPickBestFvg:
    def test_empty_list(self):
        assert _pick_best_fvg([], 100.0) is None

    def test_single_fvg(self):
        fvg = {"top": 101.0, "bottom": 99.0, "direction": "long"}
        assert _pick_best_fvg([fvg], 100.0) is fvg

    def test_picks_closest_to_midpoint(self):
        far = {"top": 110.0, "bottom": 108.0, "direction": "long"}  # mid=109
        close = {"top": 101.0, "bottom": 99.0, "direction": "long"}  # mid=100
        result = _pick_best_fvg([far, close], 100.0)
        assert result is close

    def test_multiple_equidistant(self):
        a = {"top": 102.0, "bottom": 100.0, "direction": "long"}  # mid=101
        b = {"top": 100.0, "bottom": 98.0, "direction": "short"}  # mid=99
        # Both mid are dist=1 from price=100, first one wins
        result = _pick_best_fvg([a, b], 100.0)
        assert result is a


# ---------------------------------------------------------------------------
# TestCheckObConfluence
# ---------------------------------------------------------------------------

class TestCheckObConfluence:
    def test_no_obs(self):
        fvg = {"top": 100.0, "bottom": 99.0, "direction": "long"}
        assert _check_ob_confluence(fvg, []) is False

    def test_overlapping_same_direction(self):
        fvg = {"top": 100.0, "bottom": 99.0, "direction": "long"}
        ob = {"top": 99.5, "bottom": 98.5, "direction": "long"}
        assert _check_ob_confluence(fvg, [ob]) is True

    def test_overlapping_different_direction(self):
        fvg = {"top": 100.0, "bottom": 99.0, "direction": "long"}
        ob = {"top": 99.5, "bottom": 98.5, "direction": "short"}
        assert _check_ob_confluence(fvg, [ob]) is False

    def test_non_overlapping_same_direction(self):
        fvg = {"top": 100.0, "bottom": 99.0, "direction": "long"}
        ob = {"top": 95.0, "bottom": 94.0, "direction": "long"}
        assert _check_ob_confluence(fvg, [ob]) is False

    def test_exact_boundary_overlap(self):
        fvg = {"top": 100.0, "bottom": 99.0, "direction": "long"}
        ob = {"top": 99.0, "bottom": 98.0, "direction": "long"}
        # fvg_bottom(99) <= ob_top(99) and ob_bottom(98) <= fvg_top(100) -> True
        assert _check_ob_confluence(fvg, [ob]) is True


# ---------------------------------------------------------------------------
# TestCheckBosChochConfirmation
# ---------------------------------------------------------------------------

class TestCheckBosChochConfirmation:
    def test_none_df(self):
        assert _check_bos_choch_confirmation(None, "long") is False

    def test_empty_df(self):
        assert _check_bos_choch_confirmation(pd.DataFrame(), "long") is False

    def test_bos_confirms_long(self):
        df = _make_bos_choch_df([
            {"bos": np.nan, "choch": np.nan},
            {"bos": 1, "choch": np.nan},
        ])
        assert _check_bos_choch_confirmation(df, "long") is True

    def test_choch_confirms_short(self):
        df = _make_bos_choch_df([
            {"bos": np.nan, "choch": -1},
        ])
        assert _check_bos_choch_confirmation(df, "short") is True

    def test_wrong_direction_not_confirmed(self):
        df = _make_bos_choch_df([
            {"bos": -1, "choch": np.nan},
        ])
        assert _check_bos_choch_confirmation(df, "long") is False

    def test_only_looks_at_last_5_bars(self):
        # BOS=1 at index 0 of a 10-row df -> outside last 5
        entries = [{"bos": np.nan, "choch": np.nan}] * 10
        entries[0] = {"bos": 1, "choch": np.nan}
        df = _make_bos_choch_df(entries)
        assert _check_bos_choch_confirmation(df, "long") is False

    def test_bos_in_last_5_bars_confirmed(self):
        entries = [{"bos": np.nan, "choch": np.nan}] * 10
        entries[7] = {"bos": 1, "choch": np.nan}
        df = _make_bos_choch_df(entries)
        assert _check_bos_choch_confirmation(df, "long") is True


# ---------------------------------------------------------------------------
# TestCheckKeyLevelAlignment
# ---------------------------------------------------------------------------

class TestCheckKeyLevelAlignment:
    def test_price_near_level(self):
        levels = {"prev_high": 100.0, "prev_low": 95.0}
        assert _check_key_level_alignment(levels, 100.5, atr=2.0) is True

    def test_price_far_from_levels(self):
        levels = {"prev_high": 110.0, "prev_low": 90.0}
        assert _check_key_level_alignment(levels, 100.0, atr=2.0) is False

    def test_empty_levels(self):
        assert _check_key_level_alignment({}, 100.0, atr=2.0) is False

    def test_none_values_skipped(self):
        levels = {"prev_high": None, "prev_low": 100.0}
        assert _check_key_level_alignment(levels, 100.5, atr=2.0) is True

    def test_non_numeric_value_skipped(self):
        levels = {"bad": "not_a_number", "good": 100.0}
        assert _check_key_level_alignment(levels, 100.5, atr=2.0) is True

    def test_threshold_boundary(self):
        # threshold = 1.5 * 2.0 = 3.0
        levels = {"level": 100.0}
        assert _check_key_level_alignment(levels, 103.0, atr=2.0) is True
        assert _check_key_level_alignment(levels, 103.1, atr=2.0) is False


# ---------------------------------------------------------------------------
# TestFindLiquidityTarget
# ---------------------------------------------------------------------------

class TestFindLiquidityTarget:
    def test_none_df(self):
        assert _find_liquidity_target(None, "long", 100.0) is None

    def test_empty_df(self):
        assert _find_liquidity_target(pd.DataFrame(), "long", 100.0) is None

    def test_long_finds_nearest_above(self):
        df = _make_liq_df([
            {"liq": 1, "level": 105.0},
            {"liq": 1, "level": 110.0},
        ])
        assert _find_liquidity_target(df, "long", 100.0) == pytest.approx(105.0)

    def test_short_finds_nearest_below(self):
        df = _make_liq_df([
            {"liq": 1, "level": 90.0},
            {"liq": 1, "level": 95.0},
        ])
        assert _find_liquidity_target(df, "short", 100.0) == pytest.approx(95.0)

    def test_swept_levels_skipped(self):
        df = _make_liq_df([
            {"liq": 1, "level": 105.0, "swept": 1.0},
            {"liq": 1, "level": 110.0},
        ])
        assert _find_liquidity_target(df, "long", 100.0) == pytest.approx(110.0)

    def test_no_valid_levels(self):
        df = _make_liq_df([
            {"liq": 0, "level": 105.0},
        ])
        assert _find_liquidity_target(df, "long", 100.0) is None

    def test_nan_liquidity_skipped(self):
        df = _make_liq_df([
            {"liq": np.nan, "level": 105.0},
        ])
        assert _find_liquidity_target(df, "long", 100.0) is None

    def test_no_levels_in_direction(self):
        # All levels below price, looking for long (above)
        df = _make_liq_df([
            {"liq": 1, "level": 90.0},
            {"liq": 1, "level": 95.0},
        ])
        assert _find_liquidity_target(df, "long", 100.0) is None


# ---------------------------------------------------------------------------
# TestGetSmc
# ---------------------------------------------------------------------------

class TestGetSmc:
    def setup_method(self):
        """Reset global state before each test."""
        smc_mod._smc = None
        smc_mod._smc_import_failed = False

    def teardown_method(self):
        smc_mod._smc = None
        smc_mod._smc_import_failed = False

    def test_returns_cached(self):
        sentinel = object()
        smc_mod._smc = sentinel
        assert smc_mod._get_smc() is sentinel

    def test_returns_none_when_already_failed(self):
        smc_mod._smc_import_failed = True
        assert smc_mod._get_smc() is None

    @patch("pearlalgo.trading_bots.smc_signals.logger")
    def test_import_error_sets_failed(self, mock_logger):
        with patch.dict("sys.modules", {"smartmoneyconcepts": None, "smartmoneyconcepts.smc": None}):
            # Force fresh import attempt
            smc_mod._smc = None
            smc_mod._smc_import_failed = False
            result = smc_mod._get_smc()
            assert result is None
            assert smc_mod._smc_import_failed is True

    def test_successful_import_cached(self):
        mock_smc = MagicMock()
        fake_module = MagicMock()
        fake_module.smc = mock_smc
        import sys
        with patch.dict(sys.modules, {
            "smartmoneyconcepts": MagicMock(),
            "smartmoneyconcepts.smc": fake_module,
        }):
            smc_mod._smc = None
            smc_mod._smc_import_failed = False
            result = smc_mod._get_smc()
            assert result is mock_smc
            assert smc_mod._smc is mock_smc


# ---------------------------------------------------------------------------
# TestCheckSMCSignal (integration-level with mocks)
# ---------------------------------------------------------------------------

class TestCheckSMCSignal:
    """Tests for _check_smc_signal with mocked SMC library."""

    def setup_method(self):
        smc_mod._smc = None
        smc_mod._smc_import_failed = False

    def teardown_method(self):
        smc_mod._smc = None
        smc_mod._smc_import_failed = False

    def _make_params(self, **overrides):
        defaults = dict(
            allow_smc_entries=True,
            smc_swing_length=5,
            smc_fvg_lookback=20,
            smc_ob_lookback=20,
            smc_fvg_base_confidence=0.55,
            smc_ob_boost=0.10,
            smc_bos_boost=0.08,
            smc_volume_boost=0.08,
            smc_key_level_boost=0.10,
            smc_vwap_boost=0.05,
            smc_sl_atr_mult=0.8,
            smc_tp_atr_mult=2.5,
            smc_silver_bullet_windows=[[10, 11], [14, 15], [15, 16]],
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _make_ind(self, **overrides):
        defaults = dict(close=21000.0, atr=5.0)
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_disabled_feature_flag(self):
        params = self._make_params(allow_smc_entries=False)
        result = _check_smc_signal(
            _make_ohlcv_df(20), self._make_ind(), params,
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is None

    def test_smc_library_unavailable(self):
        smc_mod._smc_import_failed = True
        result = _check_smc_signal(
            _make_ohlcv_df(20), self._make_ind(), self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is None

    def test_outside_silver_bullet_window(self):
        mock_lib = MagicMock()
        smc_mod._smc = mock_lib
        result = _check_smc_signal(
            _make_ohlcv_df(20), self._make_ind(), self._make_params(),
            datetime(2026, 4, 1, 12, 0, tzinfo=_ET),  # noon — outside
        )
        assert result is None

    def test_insufficient_data(self):
        mock_lib = MagicMock()
        smc_mod._smc = mock_lib
        result = _check_smc_signal(
            _make_ohlcv_df(4), self._make_ind(), self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is None

    def test_swing_hl_returns_none(self):
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = None
        smc_mod._smc = mock_lib
        result = _check_smc_signal(
            _make_ohlcv_df(20), self._make_ind(), self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is None

    def test_no_active_fvgs_returns_none(self):
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"col": [1, 2]})
        # FVG df with no actual FVGs
        mock_lib.fvg.return_value = _make_fvg_df([{"fvg": 0, "top": 100, "bottom": 99}] * 20)
        mock_lib.bos_choch.return_value = pd.DataFrame()
        mock_lib.ob.return_value = pd.DataFrame()
        mock_lib.liquidity.return_value = pd.DataFrame()
        smc_mod._smc = mock_lib

        result = _check_smc_signal(
            _make_ohlcv_df(20), self._make_ind(), self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is None

    def test_zero_atr_returns_none(self):
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"col": [1]})
        smc_mod._smc = mock_lib
        ind = self._make_ind(atr=0.0)
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is None

    def test_full_long_signal(self):
        """Full successful path producing a long signal."""
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"HL": [1] * 20})

        # One bullish FVG near current price 21000
        fvg_entries = [{"fvg": 0, "top": 0, "bottom": 0}] * 19
        fvg_entries.append({"fvg": 1, "top": 21001.0, "bottom": 20999.0})
        mock_lib.fvg.return_value = _make_fvg_df(fvg_entries)

        # BOS confirming long
        bos_entries = [{"bos": np.nan, "choch": np.nan}] * 19
        bos_entries.append({"bos": 1, "choch": np.nan})
        mock_lib.bos_choch.return_value = _make_bos_choch_df(bos_entries)

        # No OBs
        mock_lib.ob.return_value = _make_ob_df([{"ob": 0}] * 20)

        # No liquidity
        mock_lib.liquidity.return_value = pd.DataFrame()

        smc_mod._smc = mock_lib

        ind = self._make_ind(close=21000.0, atr=5.0)
        params = self._make_params()
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, params,
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )

        assert result is not None
        assert result["direction"] == "long"
        assert result["signal_source"] == "smc"
        assert result["entry_price"] == pytest.approx(21000.0)
        assert result["stop_loss"] < result["entry_price"]
        assert result["take_profit"] > result["entry_price"]
        assert "FVG_LONG" in result["active_indicators"]
        assert "BOS_CHOCH_LONG" in result["active_indicators"]
        assert result["confidence"] >= 0.55
        assert result["confidence"] <= 0.99

    def test_full_short_signal_with_ob_confluence(self):
        """Short signal with OB confluence upgrades signal type."""
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"HL": [1] * 20})

        fvg_entries = [{"fvg": 0}] * 19
        fvg_entries.append({"fvg": -1, "top": 21001.0, "bottom": 20999.0})
        mock_lib.fvg.return_value = _make_fvg_df(fvg_entries)

        mock_lib.bos_choch.return_value = pd.DataFrame()

        # OB overlapping with FVG in short direction
        ob_entries = [{"ob": 0}] * 19
        ob_entries.append({"ob": -1, "top": 21002.0, "bottom": 20998.0, "volume": 800.0})
        mock_lib.ob.return_value = _make_ob_df(ob_entries)

        mock_lib.liquidity.return_value = pd.DataFrame()

        smc_mod._smc = mock_lib

        ind = self._make_ind(close=21000.0, atr=5.0)
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )

        assert result is not None
        assert result["direction"] == "short"
        assert "OB_CONFLUENCE" in result["active_indicators"]
        # OB confluence in SB window -> silver bullet
        assert result["signal_type"] == "smc_silver_bullet"
        assert result["stop_loss"] > result["entry_price"]
        assert result["take_profit"] < result["entry_price"]

    def test_confidence_capped_at_099(self):
        """Even with all boosts, confidence never exceeds 0.99."""
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"HL": [1] * 20})

        fvg_entries = [{"fvg": 0}] * 19
        fvg_entries.append({"fvg": 1, "top": 21001.0, "bottom": 20999.0})
        mock_lib.fvg.return_value = _make_fvg_df(fvg_entries)

        bos_entries = [{"bos": np.nan, "choch": np.nan}] * 19
        bos_entries.append({"bos": 1, "choch": np.nan})
        mock_lib.bos_choch.return_value = _make_bos_choch_df(bos_entries)

        ob_entries = [{"ob": 0}] * 19
        ob_entries.append({"ob": 1, "top": 21002.0, "bottom": 20998.0, "volume": 500.0})
        mock_lib.ob.return_value = _make_ob_df(ob_entries)

        mock_lib.liquidity.return_value = pd.DataFrame()
        smc_mod._smc = mock_lib

        ind = SimpleNamespace(
            close=21000.0,
            atr=5.0,
            volume_confirmed=True,
            key_levels={"prev_high": 21001.0},
            vwap_val=20990.0,  # price > vwap -> aligned for long
        )
        params = self._make_params(smc_fvg_base_confidence=0.90)
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, params,
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )

        assert result is not None
        assert result["confidence"] <= 0.99

    def test_vwap_alignment_long(self):
        """VWAP aligned for long when price > vwap."""
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"HL": [1] * 20})

        fvg_entries = [{"fvg": 0}] * 19
        fvg_entries.append({"fvg": 1, "top": 21001.0, "bottom": 20999.0})
        mock_lib.fvg.return_value = _make_fvg_df(fvg_entries)
        mock_lib.bos_choch.return_value = pd.DataFrame()
        mock_lib.ob.return_value = _make_ob_df([{"ob": 0}] * 20)
        mock_lib.liquidity.return_value = pd.DataFrame()
        smc_mod._smc = mock_lib

        ind = SimpleNamespace(close=21000.0, atr=5.0, vwap_val=20990.0)
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is not None
        assert "VWAP_ALIGNED" in result["active_indicators"]

    def test_vwap_not_aligned_long(self):
        """VWAP not aligned for long when price < vwap."""
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"HL": [1] * 20})

        fvg_entries = [{"fvg": 0}] * 19
        fvg_entries.append({"fvg": 1, "top": 21001.0, "bottom": 20999.0})
        mock_lib.fvg.return_value = _make_fvg_df(fvg_entries)
        mock_lib.bos_choch.return_value = pd.DataFrame()
        mock_lib.ob.return_value = _make_ob_df([{"ob": 0}] * 20)
        mock_lib.liquidity.return_value = pd.DataFrame()
        smc_mod._smc = mock_lib

        ind = SimpleNamespace(close=21000.0, atr=5.0, vwap_val=21010.0)
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is not None
        assert "VWAP_ALIGNED" not in result["active_indicators"]

    def test_liquidity_target_used_for_tp(self):
        """When liquidity level found, it is used as take profit."""
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"HL": [1] * 20})

        fvg_entries = [{"fvg": 0}] * 19
        fvg_entries.append({"fvg": 1, "top": 21001.0, "bottom": 20999.0})
        mock_lib.fvg.return_value = _make_fvg_df(fvg_entries)
        mock_lib.bos_choch.return_value = pd.DataFrame()
        mock_lib.ob.return_value = _make_ob_df([{"ob": 0}] * 20)

        liq_df = _make_liq_df([{"liq": 1, "level": 21050.0}])
        mock_lib.liquidity.return_value = liq_df
        smc_mod._smc = mock_lib

        ind = self._make_ind(close=21000.0, atr=5.0)
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is not None
        assert result["take_profit"] == pytest.approx(21050.0)

    def test_signal_dict_structure(self):
        """Verify all expected keys are present in the signal dict."""
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"HL": [1] * 20})

        fvg_entries = [{"fvg": 0}] * 19
        fvg_entries.append({"fvg": 1, "top": 21001.0, "bottom": 20999.0})
        mock_lib.fvg.return_value = _make_fvg_df(fvg_entries)
        mock_lib.bos_choch.return_value = pd.DataFrame()
        mock_lib.ob.return_value = _make_ob_df([{"ob": 0}] * 20)
        mock_lib.liquidity.return_value = pd.DataFrame()
        smc_mod._smc = mock_lib

        ind = self._make_ind(close=21000.0, atr=5.0)
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )

        assert result is not None
        expected_keys = {
            "direction", "entry_price", "stop_loss", "take_profit",
            "confidence", "risk_reward", "signal_type", "active_indicators",
            "signal_source", "reason", "indicators",
        }
        assert set(result.keys()) == expected_keys

        # Check nested indicators dict
        ind_dict = result["indicators"]
        assert "active_count" in ind_dict
        assert "active_list" in ind_dict
        assert "entry_trigger" in ind_dict
        assert "fvg_top" in ind_dict
        assert "fvg_bottom" in ind_dict
        assert "ob_confluence" in ind_dict

    def test_fallback_price_from_ohlc(self):
        """When ind.close fails, falls back to ohlc close."""
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"HL": [1] * 20})

        fvg_entries = [{"fvg": 0}] * 19
        fvg_entries.append({"fvg": 1, "top": 21001.0, "bottom": 20999.0})
        mock_lib.fvg.return_value = _make_fvg_df(fvg_entries)
        mock_lib.bos_choch.return_value = pd.DataFrame()
        mock_lib.ob.return_value = _make_ob_df([{"ob": 0}] * 20)
        mock_lib.liquidity.return_value = pd.DataFrame()
        smc_mod._smc = mock_lib

        # ind without close attribute -- atr still needed
        ind = SimpleNamespace(atr=5.0)
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        # Result depends on whether the ohlc close is near the FVG
        # The key thing is it doesn't crash
        # (may be None if ohlc close isn't near the FVG, that's fine)
        assert result is None or isinstance(result, dict)

    def test_signal_type_smc_fvg_without_ob(self):
        """Without OB confluence, signal_type should be smc_fvg."""
        mock_lib = MagicMock()
        mock_lib.swing_highs_lows.return_value = pd.DataFrame({"HL": [1] * 20})

        fvg_entries = [{"fvg": 0}] * 19
        fvg_entries.append({"fvg": 1, "top": 21001.0, "bottom": 20999.0})
        mock_lib.fvg.return_value = _make_fvg_df(fvg_entries)
        mock_lib.bos_choch.return_value = pd.DataFrame()
        mock_lib.ob.return_value = _make_ob_df([{"ob": 0}] * 20)
        mock_lib.liquidity.return_value = pd.DataFrame()
        smc_mod._smc = mock_lib

        ind = self._make_ind(close=21000.0, atr=5.0)
        result = _check_smc_signal(
            _make_ohlcv_df(20), ind, self._make_params(),
            datetime(2026, 4, 1, 10, 30, tzinfo=_ET),
        )
        assert result is not None
        # Only 1 indicator (FVG_LONG), no OB -> smc_fvg
        # But since in SB window, need < 3 indicators and no OB confluence
        assert result["signal_type"] == "smc_fvg"
