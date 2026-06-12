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


# ── Path-C hypotheses: overnight-gap conditioning (pre-registered 2026-06-12) ───
# Genuinely different family: conditions on the OVERNIGHT GAP (today's first RTH
# bar open vs the prior trading date's RTH close) — a variable no prior trial
# used. Frozen spec in docs/audits/validation-trial-ledger.md (Path C); do NOT
# vary thresholds/exits without a new ledger registration.

# First sessions on the new contract after the Dec-2025/Mar-2026 expirations.
# The archive is IBKR continuous spliced unadjusted at expiry, so these "gaps"
# embed the calendar spread (phantom gaps). Registered exclusion — Path C.
PATHC_ROLL_EXCLUDED_DATES = frozenset({"2025-12-22", "2026-03-23"})
_PATHC_GAP_FLOOR_PTS = 5.0   # cost floor: target must clear >=5x the ~1 pt RT cost
_PATHC_SMALL_CEIL = 0.30     # |gap| <= 0.30 x ATR_d for gap_fade_small
_PATHC_LARGE_FLOOR = 0.70    # |gap| >= 0.70 x ATR_d for gap_continue_large
_PATHC_ATR_DAYS = 14
# Bars to walk back from the session's first RTH bar to find the prior RTH
# close. Fri 09:30 -> Mon 09:30 spans ~250 5m bars incl. Sunday ETH; 1000
# tolerates holidays and data gaps.
_PATHC_PRIOR_CLOSE_LOOKBACK = 1000


def _daily_atr(df: pd.DataFrame, today: str, n: int = _PATHC_ATR_DAYS) -> Optional[float]:
    """Wilder ATR over ET-calendar-date aggregates STRICTLY BEFORE ``today``.

    Full ETH range per date; the archive's first (possibly partial) calendar
    date is excluded. Returns None until ``n`` TRs exist (i.e. until 14
    complete prior daily aggregates are available) — per the Path-C frozen
    spec, sessions without a valid ATR_d fire nothing in the ATR-gated trials.
    """
    ts_arr = df["time"].to_numpy()
    hi_arr = df["high"].to_numpy(dtype=float)
    lo_arr = df["low"].to_numpy(dtype=float)
    cl_arr = df["close"].to_numpy(dtype=float)
    days: Dict[str, list] = {}
    order: list = []
    for k in range(len(df)):
        d = _et_dt(int(ts_arr[k])).strftime("%Y-%m-%d")
        if d >= today:  # df is time-ordered; nothing after today's bars matters
            break
        rec = days.get(d)
        if rec is None:
            days[d] = [hi_arr[k], lo_arr[k], cl_arr[k]]
            order.append(d)
        else:
            rec[0] = max(rec[0], hi_arr[k])
            rec[1] = min(rec[1], lo_arr[k])
            rec[2] = cl_arr[k]
    daily = [days[d] for d in order[1:]]  # drop first (possibly partial) date
    if len(daily) < n + 1:
        return None
    atr: Optional[float] = None
    trs: list = []
    for i in range(1, len(daily)):
        h, l, _c = daily[i]
        pc = daily[i - 1][2]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        if atr is None:
            trs.append(tr)
            if len(trs) == n:
                atr = sum(trs) / n
        else:
            atr = (atr * (n - 1) + tr) / n
    return atr


def _gap_context(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Conditioning context at the FIRST RTH bar of a session, else None.

    Fires once per session by construction: the current bar must be in the
    opening half-hour, in RTH, with the prior bar outside the same session.
    Roll-excluded dates return None (registered exclusion).
    """
    if df is None or len(df) < 2:
        return None
    cur = df.iloc[-1]
    cur_ts = int(cur["time"])
    cur_dt = _et_dt(cur_ts)
    # O(1) gate: only a bar in the opening half-hour can be the session's first.
    if cur_dt.weekday() >= 5 or not (_RTH_OPEN <= cur_dt.time() < dtime(10, 0)):
        return None
    prev_dt = _et_dt(int(df.iloc[-2]["time"]))
    prev_in_session = (prev_dt.date() == cur_dt.date()) and (
        _RTH_OPEN <= prev_dt.time() < _RTH_CLOSE
    )
    if prev_in_session:
        return None
    today = cur_dt.strftime("%Y-%m-%d")
    if today in PATHC_ROLL_EXCLUDED_DATES:
        return None
    prior_close: Optional[float] = None
    lo_idx = max(-1, len(df) - 2 - _PATHC_PRIOR_CLOSE_LOOKBACK)
    for i in range(len(df) - 2, lo_idx, -1):
        d = _et_dt(int(df.iloc[i]["time"]))
        if (
            d.strftime("%Y-%m-%d") != today
            and d.weekday() < 5
            and _RTH_OPEN <= d.time() < _RTH_CLOSE
        ):
            prior_close = float(df.iloc[i]["close"])
            break
    if prior_close is None:
        return None
    return {
        "ts": cur_ts,
        "close": float(cur["close"]),
        "gap": float(cur["open"]) - prior_close,
        "prior_close": prior_close,
        "atr_d": _daily_atr(df, today),
    }


def _gap_fade_signal(ctx: Dict[str, Any], trigger: str) -> List[Dict[str, Any]]:
    """Shared fade exit geometry: target = prior RTH close (the fill), stop =
    entry -+ remaining distance (1:1 R), engine max-hold to RTH close. Skips
    when the gap pre-filled by the entry-bar close or the remaining distance
    is below the cost floor."""
    gap, close, target = ctx["gap"], ctx["close"], ctx["prior_close"]
    pre_filled = (gap > 0 and close <= target) or (gap < 0 and close >= target)
    remaining = abs(target - close)
    if pre_filled or remaining < _PATHC_GAP_FLOOR_PTS:
        return []
    if gap < 0:  # down-gap: fade = long, fill target above
        return [_signal("long", close, close - remaining, target, trigger, ctx["ts"])]
    return [_signal("short", close, close + remaining, target, trigger, ctx["ts"])]


def gap_fade_small_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """Trial 16 (PRIMARY): fade small overnight gaps.
    Condition: 5.0 pt <= |gap| <= 0.30 x ATR_d(14); requires valid ATR_d."""
    ctx = _gap_context(df)
    if ctx is None or ctx["atr_d"] is None:
        return []
    g = abs(ctx["gap"])
    if not (_PATHC_GAP_FLOOR_PTS <= g <= _PATHC_SMALL_CEIL * ctx["atr_d"]):
        return []
    return _gap_fade_signal(ctx, "gap_fade_small")


def gap_fade_all_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """Trial 17: fade ALL overnight gaps >= the cost floor (no size ceiling).
    Deliberately carries NO ATR_d gate — its condition uses no ATR (registered
    pre-hoc; this is the dilution control containing trial 16's trades)."""
    ctx = _gap_context(df)
    if ctx is None or abs(ctx["gap"]) < _PATHC_GAP_FLOOR_PTS:
        return []
    return _gap_fade_signal(ctx, "gap_fade_all")


def gap_continue_large_signals(df, config=None, current_time=None) -> List[Dict[str, Any]]:
    """Trial 18: continue LARGE overnight gaps (|gap| >= 0.70 x ATR_d).
    Direction WITH the gap sign; sentinel hold to RTH close (pure conditional
    drift read, no stop lever — Path-B mechanics)."""
    ctx = _gap_context(df)
    if ctx is None or ctx["atr_d"] is None:
        return []
    if abs(ctx["gap"]) < _PATHC_LARGE_FLOOR * ctx["atr_d"]:
        return []
    direction = "long" if ctx["gap"] > 0 else "short"
    return [_hold_signal(direction, ctx["close"], "gap_continue_large", ctx["ts"])]


STRATEGY_FNS = {
    "pine": pine_simple_signals,
    "orb": orb_signals,
    "vwap_reversion": vwap_reversion_signals,
    "opening_drive": opening_drive_signals,
    "opening_drive_5": opening_drive_5_signals,
    "tod_rth_long": tod_rth_long_signals,
    "overnight_seasonality": overnight_seasonality_signals,
    "gap_fade_small": gap_fade_small_signals,
    "gap_fade_all": gap_fade_all_signals,
    "gap_continue_large": gap_continue_large_signals,
}
