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
    opening_drive_5_signals,
    opening_drive_signals,
    orb_signals,
    overnight_seasonality_signals,
    pine_simple_signals,
    tod_rth_long_signals,
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


# ── Path-B: opening-drive (sign of opening return, hold to session close) ─────────
# Anchored at 07:00 ET (Mon) so the RTH open (09:30) lands at index 30 — past
# _run's warmup=25 and _base's 25-bar minimum — and the entry bars are visited.
def test_opening_drive_long_on_up_open():
    sigs = _run(opening_drive_signals, _df([100.0 + 0.5 * k for k in range(60)], start="2026-01-05 07:00"))
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "long" and s["entry_trigger"] == "opening_drive"
    assert s["stop_loss"] < s["entry_price"] < s["take_profit"]


def test_opening_drive_short_on_down_open():
    sigs = _run(opening_drive_signals, _df([200.0 - 0.5 * k for k in range(60)], start="2026-01-05 07:00"))
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "short"
    assert s["stop_loss"] > s["entry_price"] > s["take_profit"]


def test_opening_drive_fires_once_per_session():
    sigs = _run(opening_drive_signals, _df([100.0 + 0.5 * k for k in range(90)], start="2026-01-05 07:00"))
    assert len(sigs) == 1


def test_opening_drive_gated_out_overnight():
    # Anchored entirely overnight -> _base RTH gate -> never fires.
    assert _run(opening_drive_signals, _df([100.0 + 0.5 * k for k in range(60)], start="2026-01-05 00:00")) == []


def test_opening_drive_5_uses_five_minute_window():
    sigs = _run(opening_drive_5_signals, _df([100.0 + 0.5 * k for k in range(60)], start="2026-01-05 07:00"))
    assert len(sigs) == 1
    assert sigs[0]["entry_trigger"] == "opening_drive_5" and sigs[0]["direction"] == "long"


# ── Path-B: tod_rth_long (unconditional long on the RTH open, hold to close) ──────
def test_tod_rth_long_fires_long_once_at_open():
    sigs = _run(tod_rth_long_signals, _df([100.0] * 60, start="2026-01-05 07:00"))
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "long" and s["entry_trigger"] == "tod_rth_long"
    assert s["stop_loss"] < s["entry_price"] < s["take_profit"]


def test_tod_rth_long_gated_out_overnight():
    assert _run(tod_rth_long_signals, _df([100.0] * 60, start="2026-01-05 00:00")) == []


# ── Path-B: overnight_seasonality (short at 18:00 ET, hold overnight) ─────────────
# Anchored at 15:55 ET (Mon) so the 18:00 overnight open lands at index 25.
def test_overnight_seasonality_fires_short_at_overnight_open():
    sigs = _run(overnight_seasonality_signals, _df([100.0] * 45, start="2026-01-05 15:55"))
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "short" and s["entry_trigger"] == "overnight_seasonality"
    assert s["stop_loss"] > s["entry_price"] > s["take_profit"]   # short geometry


def test_overnight_seasonality_not_gated_out_at_night():
    # Regression guard: it MUST fire at 18:00+ ET (must NOT use the RTH-only helpers).
    assert len(_run(overnight_seasonality_signals, _df([100.0] * 45, start="2026-01-05 15:55"))) >= 1


def test_overnight_seasonality_no_signal_during_rth():
    # Bars entirely inside RTH (09:30 -> ~12:55) never reach 18:00 ET -> no signal.
    assert _run(overnight_seasonality_signals, _df([100.0] * 40, start="2026-01-05 09:30")) == []


def test_overnight_seasonality_fires_once_per_date():
    sigs = _run(overnight_seasonality_signals, _df([100.0] * 70, start="2026-01-05 15:55"))
    assert len(sigs) == 1
