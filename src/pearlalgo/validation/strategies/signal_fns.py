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
# "No-touch" stop/target offset (fraction of price) for hold-to-time strategies:
# placed so far from entry that first-touch SL/TP never fires, leaving the engine's
# max-hold timeout to govern the exit (an MNQ move of ±50% intraday/overnight is
# impossible). This measures pure time-conditioned drift without an ATR stop lever.
_HOLD_SENTINEL = 0.5
# Bars to look back when locating the current RTH session (cheap, bounded — the
# entry bar is always within the first ~30 min of RTH, so today's 09:30 open is a
# few bars back). Keeps the per-bar session-mask O(1) in the total series length
# instead of the O(n^2) a full-df _rth_session_mask().apply() would cost.
_SESSION_LOOKBACK = 120


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


def _hold_signal(direction, c, trigger, ts):
    """Build a hold-to-time signal: stop/target set ±``_HOLD_SENTINEL`` from entry
    so first-touch never fires and the max-hold timeout governs the exit."""
    c = float(c)
    if direction == "long":
        return _signal("long", c, c * (1 - _HOLD_SENTINEL), c * (1 + _HOLD_SENTINEL), trigger, ts)
    return _signal("short", c, c * (1 + _HOLD_SENTINEL), c * (1 - _HOLD_SENTINEL), trigger, ts)


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


# ── Path-B hypotheses: genuinely-different (NOT EMA/VWAP/ORB) time-based bets ────
# Tested 2026-06-03 on free 5m dev data after all four intraday families were
# killed at Tier-0. These have NO crossover/breakout trigger — they bet on
# time-of-day / opening-drive drift and hold to a session boundary via the
# max-hold timeout (not an ATR stop). See docs/audits/validation-trial-ledger.md.
def _opening_drive_core(df, drive_minutes, atr_len=14, trigger="opening_drive"):
    """Shared core for the opening-drive continuation hypothesis. At the close of
    the first ``drive_minutes`` of the RTH session, enter in the SIGN direction of
    (close − session-open) and hold to RTH close. Fires once per session."""
    if df is None or len(df) < 2:
        return []
    cur_ts = int(df.iloc[-1]["time"])
    cur_dt = _et_dt(cur_ts)
    cur_min = cur_dt.hour * 60 + cur_dt.minute
    cutoff_min = _RTH_OPEN.hour * 60 + _RTH_OPEN.minute + drive_minutes
    # O(1) gate: only the bar at/just-after the drive cutoff can fire. Skips the
    # session-mask on ~every other bar (the 30-min slack tolerates data gaps).
    if cur_dt.weekday() >= 5 or not (cutoff_min <= cur_min < cutoff_min + 30):
        return []
    ctx = _base(df, atr_len)
    if ctx is None:
        return []
    recent = df.iloc[-_SESSION_LOOKBACK:]
    mask = _rth_session_mask(recent, cur_ts)
    sess = recent.loc[mask]
    if len(sess) < 2:
        return []
    cutoff_ts = cur_dt.replace(hour=_RTH_OPEN.hour, minute=_RTH_OPEN.minute,
                               second=0, microsecond=0).timestamp() + drive_minutes * 60
    prev_ts = int(df.iloc[-2]["time"])
    # Fire once: this is the first bar at/after the drive cutoff, the prior bar was
    # before it, AND the prior bar is in the same RTH session (no overnight gap).
    if not (prev_ts < cutoff_ts <= cur_ts):
        return []
    if not bool(mask.iloc[-2]):
        return []
    # Drive = net move from the session open to this (the decision) bar's close.
    drive = float(ctx["close"]) - float(sess.iloc[0]["open"])
    if drive == 0:
        return []
    return [_hold_signal("long" if drive > 0 else "short", ctx["close"], trigger, cur_ts)]


def opening_drive_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """Opening-drive CONTINUATION (15-min window): enter in the sign direction of
    the first 15 min of RTH, hold to the close. Genuinely different from ORB — it
    keys off the sign of the opening RETURN, not a range-extreme breakout."""
    p = (config or {}).get("vparams", {})
    return _opening_drive_core(df, p.get("drive_minutes", 15), p.get("atr_len", 14))


def opening_drive_5_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """Opening-drive continuation, 5-minute window (the one allowed robust-lever
    variation of the drive-window length). Distinct trigger for attribution."""
    p = (config or {}).get("vparams", {})
    return _opening_drive_core(df, 5, p.get("atr_len", 14), trigger="opening_drive_5")


def tod_rth_long_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """Time-of-day long-bias: enter LONG on the FIRST RTH bar of each session and
    hold to the close. Unconditional (no price trigger) — a pure time-conditioned
    bet on the 922-trade RTH long-bias prior. Exit via the max-hold timeout."""
    p = (config or {}).get("vparams", {})
    if df is None or len(df) < 2:
        return []
    cur_dt = _et_dt(int(df.iloc[-1]["time"]))
    # O(1) gate: the session's first RTH bar is in the opening half-hour.
    if cur_dt.weekday() >= 5 or not (_RTH_OPEN <= cur_dt.time() < dtime(10, 0)):
        return []
    ctx = _base(df, p.get("atr_len", 14))
    if ctx is None:
        return []
    # First RTH bar of the session = current bar in RTH (guaranteed by _base) and
    # the prior bar NOT in the same RTH session (it was overnight / a prior day).
    prev_dt = _et_dt(int(df.iloc[-2]["time"]))
    prev_in_session = (prev_dt.date() == cur_dt.date()) and (_RTH_OPEN <= prev_dt.time() < _RTH_CLOSE)
    if prev_in_session:
        return []
    return [_hold_signal("long", ctx["close"], "tod_rth_long", ctx["ts"])]


def overnight_seasonality_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """Overnight seasonality: enter SHORT at the first bar ≥ 18:00 ET each
    session-date (the overnight open) and hold ~overnight via the max-hold timeout.
    Pure time-conditioned bet; direction=short from the local prior that the
    overnight long-biased bot lost −$4,477. Deliberately does NOT use the RTH-only
    helpers (_base/_in_rth/_session_id/_rth_session_mask) — they would gate it out."""
    p = (config or {}).get("vparams", {})
    direction = p.get("direction", "short")
    entry_hour = p.get("entry_hour", 18)
    if df is None or len(df) < 3:
        return []
    last = df.iloc[-1]
    ts = int(last["time"])
    d = _et_dt(ts)
    if d.time() < dtime(entry_hour, 0):
        return []
    # Fire once per ET date: current bar ≥ entry_hour, prior bar a different ET date
    # or before entry_hour. (No weekday filter needed: there is no Fri/Sat 18:00 ET
    # session in the data, so this naturally fires only on Sun–Thu evenings.)
    prev = _et_dt(int(df.iloc[-2]["time"]))
    prev_before = (prev.date() != d.date()) or (prev.time() < dtime(entry_hour, 0))
    if not prev_before:
        return []
    return [_hold_signal(direction, last["close"], "overnight_seasonality", ts)]


STRATEGY_FNS = {
    "pine": pine_simple_signals,
    "orb": orb_signals,
    "vwap_reversion": vwap_reversion_signals,
    "opening_drive": opening_drive_signals,
    "opening_drive_5": opening_drive_5_signals,
    "tod_rth_long": tod_rth_long_signals,
    "overnight_seasonality": overnight_seasonality_signals,
}
