from __future__ import annotations

import pandas as pd

from pearlalgo.utils.volume_pressure import (
    compute_signed_volume_series,
    compute_volume_pressure_summary,
    format_volume_pressure,
    timeframe_to_minutes,
)


def test_timeframe_to_minutes() -> None:
    assert timeframe_to_minutes("5m") == 5
    assert timeframe_to_minutes("15m") == 15
    assert timeframe_to_minutes("1h") == 60
    assert timeframe_to_minutes("") is None
    assert timeframe_to_minutes("bad") is None


def test_compute_signed_volume_series() -> None:
    df = pd.DataFrame(
        {
            "open": [10, 10, 10],
            "close": [11, 9, 10],
            "volume": [100, 200, 300],
        }
    )
    s = compute_signed_volume_series(df, open_col="open", close_col="close", volume_col="volume")
    assert s is not None
    assert float(s.iloc[0]) == 100.0
    assert float(s.iloc[1]) == -200.0
    assert float(s.iloc[2]) == 0.0


def test_compute_volume_pressure_summary_buyers() -> None:
    df = pd.DataFrame(
        {
            "open": [10] * 10,
            "close": [11] * 10,  # all green candles
            "volume": [100] * 10,
        }
    )
    summary = compute_volume_pressure_summary(df, lookback_bars=10, baseline_bars=10)
    assert summary is not None
    assert summary.bias == "buyers"
    assert summary.score > 0


def test_compute_volume_pressure_summary_sellers() -> None:
    df = pd.DataFrame(
        {
            "open": [10] * 10,
            "close": [9] * 10,  # all red candles
            "volume": [100] * 10,
        }
    )
    summary = compute_volume_pressure_summary(df, lookback_bars=10, baseline_bars=10)
    assert summary is not None
    assert summary.bias == "sellers"
    assert summary.score < 0


def test_compute_volume_pressure_summary_mixed() -> None:
    df = pd.DataFrame(
        {
            "open": [10] * 20,
            "close": [11] * 10 + [9] * 10,  # balanced
            "volume": [100] * 20,
        }
    )
    summary = compute_volume_pressure_summary(df, lookback_bars=20, baseline_bars=20)
    assert summary is not None
    assert summary.bias == "mixed"


def test_format_volume_pressure_includes_period_and_vol_ratio() -> None:
    df = pd.DataFrame(
        {
            "open": [10] * 30,
            "close": [11] * 30,
            "volume": [100] * 30,
        }
    )
    summary = compute_volume_pressure_summary(df, lookback_bars=24, baseline_bars=30)
    assert summary is not None
    msg = format_volume_pressure(summary, timeframe_minutes=5, data_fresh=True)
    assert "Pressure:" in msg
    assert "Δ" in msg
    assert "Vol" in msg
    assert "2h" in msg  # 24 * 5m = 120m















