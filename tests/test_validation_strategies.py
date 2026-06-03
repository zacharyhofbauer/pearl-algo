"""Tests for the isolated validation signal sources (pine / orb / vwap_reversion).

Drives each strategy over growing bar slices (like the engine) on synthetic data
and asserts the core behaviors: RTH gating, EMA-cross detection, long-only for
pine, breakout for orb, band-fade for vwap_reversion, and stop/target geometry.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from pearlalgo.validation.strategies.signal_fns import (
    _ema,
    _in_rth,
    _wilder_atr,
    orb_signals,
    pine_simple_signals,
    vwap_reversion_signals,
)

ET = ZoneInfo("America/New_York")


def _df(closes, *, start="2026-01-05 09:30", rng=2.0, vol=100.0):
    """Build a 5m OHLCV frame from a close series anchored at an ET datetime."""
    t0 = datetime.strptime(start, "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    rows = []
    for k, c in enumerate(closes):
        ts = int((t0 + timedelta(minutes=5 * k)).timestamp())
        rows.append({"time": ts, "open": float(c), "high": float(c) + rng,
                     "low": float(c) - rng, "close": float(c), "volume": vol})
    return pd.DataFrame(rows)


def _run(fn, df, warmup=25):
    """Replay fn over growing slices; return all signals it would emit."""
    out = []
    for i in range(warmup, len(df)):
        out.extend(fn(df.iloc[: i + 1].copy()))
    return out


# ── indicators ────────────────────────────────────────────────────────────────
def test_ema_tracks_and_atr_positive():
    s = pd.Series([100.0 + i for i in range(30)])
    assert _ema(s, 9).iloc[-1] > _ema(s, 21).iloc[-1]  # fast above slow on an uptrend
    df = _df([100 + i for i in range(30)])
    assert _wilder_atr(df, 14).iloc[-1] > 0


def test_in_rth_gating():
    rth = int(datetime(2026, 1, 5, 10, 0, tzinfo=ET).timestamp())     # Mon 10:00 ET
    overnight = int(datetime(2026, 1, 5, 3, 0, tzinfo=ET).timestamp())  # Mon 03:00 ET
    weekend = int(datetime(2026, 1, 3, 10, 0, tzinfo=ET).timestamp())  # Sat 10:00 ET
    assert _in_rth(rth) is True
    assert _in_rth(overnight) is False
    assert _in_rth(weekend) is False


# ── pine (EMA9/21 + VWAP, long-only) ────────────────────────────────────────────
def test_pine_fires_long_on_uptrend_cross():
    # 28 flat bars so the EMA cross lands at index 28 (after _run's warmup of 25),
    # then a ramp up. (A shorter flat would cross before warmup and be missed.)
    closes = [100.0] * 28 + [100 + i for i in range(1, 12)]
    sigs = _run(pine_simple_signals, _df(closes))
    assert len(sigs) >= 1
    assert all(s["direction"] == "long" for s in sigs)        # long-only
    s = sigs[0]
    assert s["entry_trigger"] == "pine_ema_vwap"
    assert s["stop_loss"] < s["entry_price"] < s["take_profit"]
    # target is 2R (target_r=2.0): (tp-entry) ~= 2*(entry-sl)
    r = s["entry_price"] - s["stop_loss"]
    assert abs((s["take_profit"] - s["entry_price"]) - 2 * r) < 1e-6


def test_pine_no_signal_on_downtrend():
    closes = [120.0] * 22 + [120 - i for i in range(1, 16)]  # flat then ramp DOWN
    assert _run(pine_simple_signals, _df(closes)) == []       # long-only -> nothing


def test_pine_respects_rth_gate():
    closes = [100.0] * 22 + [100 + i for i in range(1, 16)]
    # Same bullish setup but anchored overnight -> no signals.
    assert _run(pine_simple_signals, _df(closes, start="2026-01-05 01:00")) == []


# ── orb ──────────────────────────────────────────────────────────────────────────
def test_orb_fires_on_breakout():
    # First 15 min (3 bars) range ~100±2, then a clean break to 110.
    closes = [100.0, 100.5, 99.5] + [100.0] * 24 + [110.0, 111.0]
    sigs = _run(orb_signals, _df(closes))
    longs = [s for s in sigs if s["direction"] == "long"]
    assert len(longs) >= 1
    assert longs[0]["entry_trigger"] == "orb"


# ── vwap_reversion ────────────────────────────────────────────────────────────────
def test_vwap_reversion_fires_on_dip_below_band():
    # Oscillating session (non-zero sigma so bands are real) then a sharp dip far
    # below the lower band -> fade long toward the mean.
    closes = [100.0 + (1.0 if k % 2 else -1.0) for k in range(28)] + [85.0]
    sigs = _run(vwap_reversion_signals, _df(closes))
    longs = [s for s in sigs if s["direction"] == "long"]
    assert len(longs) >= 1
    s = longs[0]
    assert s["entry_trigger"] == "vwap_reversion"
    assert s["take_profit"] > s["entry_price"]   # target = VWAP (above a dip)
    assert s["stop_loss"] < s["entry_price"]
