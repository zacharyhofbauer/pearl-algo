"""Failure-mode tests for signal generator fallback behavior."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from pearlalgo.trading_bots import signal_generator as sg


def _sample_df(rows: int = 30) -> pd.DataFrame:
    """Build a minimal OHLCV frame for signal checks."""
    closes = [100.0 + (i * 0.1) for i in range(rows)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000.0 for _ in closes],
        }
    )


def _sample_indicator_result(df: pd.DataFrame) -> sg.IndicatorResult:
    """Create an IndicatorResult object with stable defaults for tests."""
    regime = sg.MarketRegime(
        regime="ranging",
        confidence=0.8,
        trend_strength=0.2,
        volatility_ratio=1.0,
        recommendation="full_size",
        adx_value=10.0,
    )
    return sg.IndicatorResult(
        close=float(df["close"].iloc[-1]),
        prev_close=float(df["close"].iloc[-2]),
        atr=1.0,
        atr_series=pd.Series([1.0] * len(df)),
        ema_fast=pd.Series(df["close"]),
        ema_slow=pd.Series(df["close"]),
        vwap_series=pd.Series(df["close"]),
        vwap_val=float(df["close"].iloc[-1]),
        ema_cross_up=False,
        ema_cross_down=False,
        volume_confirmed=False,
        sr_signal=None,
        sr_confidence=0.0,
        tbt_signal=None,
        tbt_confidence=0.0,
        sd_signal=None,
        sd_confidence=0.0,
        key_levels={},
        key_level_signal=None,
        key_level_confidence=0.0,
        key_level_info={},
        vwap_band_signal=None,
        regime=regime,
        adx_value=10.0,
        vwap_cross_signal=None,
        vwap_retest_signal=None,
        trend_breakout_signal=None,
        trend_momentum_signal=None,
    )


def test_detect_vwap_cross_invalid_vwap_series_returns_false() -> None:
    """Invalid VWAP values should degrade gracefully to no signal."""
    df = pd.DataFrame({"close": [100.0, 101.0]})
    vwap_series = pd.Series(["bad", "data"])

    bullish, bearish = sg.detect_vwap_cross(df, vwap_series=vwap_series)

    assert bullish is False
    assert bearish is False


def test_check_vwap_2sd_signal_band_error_returns_none(monkeypatch) -> None:
    """Band-calculation exceptions should fallback to None without raising."""
    df = _sample_df()
    params = sg.StrategyParams(
        allow_vwap_2sd_entries=True,
        vwap_2sd_window_start="00:00",
        vwap_2sd_window_end="23:59",
        adx_trending_threshold=25.0,
    )
    ind = _sample_indicator_result(df)

    def _raise_band_error(*args, **kwargs):
        raise TypeError("bad band data")

    monkeypatch.setattr(sg, "calculate_vwap_bands", _raise_band_error)

    result = sg._check_vwap_2sd_signal(
        df=df,
        ind=ind,
        params=params,
        current_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert result is None
