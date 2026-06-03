"""Faithful, self-contained intraday signal sources for the validation 4-way.

Each function takes the bar history up to and including the current bar and
returns a (0- or 1-element) list of signals FOR THE LAST BAR ONLY — the engine
calls it per bar. All compute their own indicators so they match the strategy's
textbook definition rather than the live composite confidence engine.

Conventions:
  - df columns: time (unix s), open, high, low, close, volume.
  - All entries are at the signal bar's close; the engine applies slippage.
  - Stops/targets are ATR-based unless noted (VWAP-reversion targets the mean).
  - RTH = 09:30–16:00 America/New_York, weekdays.
"""
from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_ET = ZoneInfo("America/New_York")
_RTH_OPEN = dtime(9, 30)
_RTH_CLOSE = dtime(16, 0)


# ── indicators ────────────────────────────────────────────────────────────────
def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _wilder_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    # Wilder's smoothing == EMA with alpha = 1/n.
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def _et_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=ZoneInfo("UTC")).astimezone(_ET)


def _in_rth(ts: int) -> bool:
    d = _et_dt(ts)
    if d.weekday() >= 5:  # Sat/Sun
        return False
    return _RTH_OPEN <= d.time() < _RTH_CLOSE


def _session_id(ts: int) -> str:
    """RTH session key = ET calendar date (RTH does not cross midnight)."""
    return _et_dt(ts).strftime("%Y-%m-%d")


def _rth_session_mask(df: pd.DataFrame, last_ts: int) -> pd.Series:
    """Boolean mask of bars in the SAME RTH session as ``last_ts`` (>= 09:30 ET)."""
    sess = _session_id(last_ts)
    et = df["time"].apply(_et_dt)
    same_day = et.apply(lambda d: d.strftime("%Y-%m-%d")) == sess
    in_rth = et.apply(lambda d: _RTH_OPEN <= d.time() < _RTH_CLOSE)
    return same_day & in_rth


def _session_vwap_bands(df: pd.DataFrame, last_ts: int, k: float):
    """Session-anchored VWAP + volume-weighted ±k-sigma bands at the last bar.

    Returns (vwap, lower, upper) floats, or (None, None, None) if no session vol.
    """
    mask = _rth_session_mask(df, last_ts)
    sess = df.loc[mask]
    vol = sess["volume"].to_numpy(dtype=float)
    if vol.sum() <= 0:
        return None, None, None
    tp = ((sess["high"] + sess["low"] + sess["close"]) / 3.0).to_numpy(dtype=float)
    vwap = float((tp * vol).sum() / vol.sum())
    var = float((vol * (tp - vwap) ** 2).sum() / vol.sum())
    sd = var ** 0.5
    return vwap, vwap - k * sd, vwap + k * sd


def _base(df: pd.DataFrame, atr_len: int):
    """Common last-bar context. Returns dict or None if insufficient history."""
    if df is None or len(df) < max(atr_len + 2, 25):
        return None
    last = df.iloc[-1]
    ts = int(last["time"])
    if not _in_rth(ts):
        return None
    atr = float(_wilder_atr(df, atr_len).iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        return None
    return {"ts": ts, "close": float(last["close"]), "atr": atr}


def _signal(direction, entry, stop, target, trigger, ts, conf=0.5):
    return {
        "direction": direction,
        "entry_price": float(entry),
        "stop_loss": float(stop),
        "take_profit": float(target),
        "confidence": conf,
        "entry_trigger": trigger,
        "signal_type": trigger,
        "signal_id": f"{trigger}-{ts}",
    }


# ── strategies ──────────────────────────────────────────────────────────────────
def pine_simple_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """Faithful pine/mnq_rth_long_bias.pine: EMA9/21 cross + VWAP filter, RTH-only,
    LONG-ONLY, ATR stop (1.5x) / target (2R = 3.0x ATR)."""
    p = (config or {}).get("vparams", {})
    ef_n, es_n = p.get("ema_fast", 9), p.get("ema_slow", 21)
    atr_len = p.get("atr_len", 14)
    stop_atr, target_r = p.get("stop_atr", 1.5), p.get("target_r", 2.0)
    ctx = _base(df, atr_len)
    if ctx is None:
        return []
    ef = _ema(df["close"], ef_n)
    es = _ema(df["close"], es_n)
    bull_cross = ef.iloc[-2] <= es.iloc[-2] and ef.iloc[-1] > es.iloc[-1]
    if not bull_cross:
        return []
    vwap, _, _ = _session_vwap_bands(df, ctx["ts"], k=1.0)
    if vwap is None or ctx["close"] <= vwap:  # VWAP filter: longs only above VWAP
        return []
    c, atr = ctx["close"], ctx["atr"]
    return [_signal("long", c, c - stop_atr * atr, c + stop_atr * target_r * atr,
                    "pine_ema_vwap", ctx["ts"])]


def orb_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """5-min Opening-Range Breakout: range = first ``or_minutes`` of the RTH
    session; long on first close above OR-high, short on first close below
    OR-low. Two-sided. ATR stop/target."""
    p = (config or {}).get("vparams", {})
    or_minutes = p.get("or_minutes", 15)
    atr_len = p.get("atr_len", 14)
    stop_atr, target_r = p.get("stop_atr", 1.5), p.get("target_r", 2.0)
    ctx = _base(df, atr_len)
    if ctx is None:
        return []
    mask = _rth_session_mask(df, ctx["ts"])
    sess = df.loc[mask]
    if len(sess) < 2:
        return []
    open_dt = _et_dt(int(sess.iloc[0]["time"]))
    cutoff = open_dt.replace(hour=_RTH_OPEN.hour, minute=_RTH_OPEN.minute, second=0, microsecond=0)
    cutoff_ts = cutoff.timestamp() + or_minutes * 60
    orb_bars = sess[sess["time"] < cutoff_ts]
    after = sess[sess["time"] >= cutoff_ts]
    if len(orb_bars) == 0 or len(after) < 1:
        return []
    or_hi, or_lo = float(orb_bars["high"].max()), float(orb_bars["low"].min())
    # Only fire on the FIRST breakout bar (this bar breaks, prior bar didn't).
    cur, prev = ctx["close"], float(df.iloc[-2]["close"])
    c, atr = ctx["close"], ctx["atr"]
    if cur > or_hi and prev <= or_hi:
        return [_signal("long", c, c - stop_atr * atr, c + stop_atr * target_r * atr, "orb", ctx["ts"])]
    if cur < or_lo and prev >= or_lo:
        return [_signal("short", c, c + stop_atr * atr, c - stop_atr * target_r * atr, "orb", ctx["ts"])]
    return []


def vwap_reversion_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """Fade extension to ±k-sigma VWAP bands; target = VWAP (the mean), ATR stop.
    Two-sided. Fires on the first bar that closes beyond a band."""
    p = (config or {}).get("vparams", {})
    atr_len = p.get("atr_len", 14)
    band_k = p.get("band_k", 2.0)
    stop_atr = p.get("stop_atr", 1.5)
    ctx = _base(df, atr_len)
    if ctx is None:
        return []
    vwap, lower, upper = _session_vwap_bands(df, ctx["ts"], k=band_k)
    if vwap is None:
        return []
    # Prior bar's bands for "first touch" detection.
    if len(df) < 3:
        return []
    pv, pl, pu = _session_vwap_bands(df.iloc[:-1], int(df.iloc[-2]["time"]), k=band_k)
    if pv is None:
        return []
    c, atr, prev = ctx["close"], ctx["atr"], float(df.iloc[-2]["close"])
    # Long: dipped below lower band this bar (prior bar wasn't below).
    if c <= lower and prev > pl and vwap > c:
        return [_signal("long", c, c - stop_atr * atr, vwap, "vwap_reversion", ctx["ts"])]
    # Short: spiked above upper band this bar.
    if c >= upper and prev < pu and vwap < c:
        return [_signal("short", c, c + stop_atr * atr, vwap, "vwap_reversion", ctx["ts"])]
    return []


STRATEGY_FNS = {
    "pine": pine_simple_signals,
    "orb": orb_signals,
    "vwap_reversion": vwap_reversion_signals,
}
