"""
TradingView-style HUD context builder (Python).

This module computes *lightweight, bounded* context objects to support chart rendering
that matches the “daily trader HUD” style (sessions, key levels, zones, etc.).

Design constraints
- Must be fast on every scan cycle (no heavy nested loops / unbounded history).
- Output must be JSON-serializable (state_manager persists signals to JSONL).
- Works with either a `timestamp` column or a DatetimeIndex.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import warnings

import numpy as np
import pandas as pd


def _to_utc_ts_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """Return tz-aware UTC timestamps for df or None if unavailable."""
    if df is None or df.empty:
        return None

    ts: Optional[pd.Series] = None

    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce")
    elif isinstance(df.index, pd.DatetimeIndex):
        ts = pd.Series(df.index, index=df.index)
        ts = pd.to_datetime(ts, errors="coerce")
    else:
        return None

    if ts is None:
        return None

    # Ensure tz-aware UTC. IB data may come back tz-naive.
    try:
        if getattr(ts.dt, "tz", None) is None:
            ts = ts.dt.tz_localize(timezone.utc)  # type: ignore[assignment]
        else:
            ts = ts.dt.tz_convert(timezone.utc)  # type: ignore[assignment]
    except Exception:
        # If tz-localize fails (mixed types), fall back to coercion.
        try:
            ts = pd.to_datetime(ts, utc=True, errors="coerce")
        except Exception:
            return None

    return ts


def _parse_hhmm(s: str) -> time:
    s = (s or "").strip()
    if len(s) == 4 and s.isdigit():
        return time(int(s[:2]), int(s[2:]))
    # Accept HH:MM too.
    if ":" in s:
        parts = s.split(":")
        return time(int(parts[0]), int(parts[1]))
    raise ValueError(f"Invalid time string: {s}")


def _time_to_min(t: time) -> int:
    return int(t.hour) * 60 + int(t.minute)


@dataclass(frozen=True)
class SessionDef:
    name: str
    session: str  # e.g. "0900-1500"
    timezone: str
    color: str

    def start_end_minutes(self) -> Tuple[int, int]:
        raw = (self.session or "").strip()
        if "-" not in raw:
            raise ValueError(f"Invalid session: {raw}")
        a, b = raw.split("-", 1)
        start = _time_to_min(_parse_hhmm(a))
        end = _time_to_min(_parse_hhmm(b))
        return start, end


def default_sessions() -> List[SessionDef]:
    """Matches the Key Levels SpacemanBTC Pine defaults (UTC-based sessions)."""
    return [
        SessionDef("Tokyo", "0000-0900", "UTC", "#2962FF"),
        SessionDef("London", "0800-1600", "UTC", "#FF9800"),
        SessionDef("New York", "1400-2100", "UTC", "#089981"),
    ]


def compute_sessions(
    df: pd.DataFrame,
    sessions: Optional[List[SessionDef]] = None,
    tick_size: float = 0.25,
    max_segments_per_session: int = 3,
) -> List[Dict[str, Any]]:
    """Compute visible session segments for chart shading and labels."""
    ts_utc = _to_utc_ts_series(df)
    if ts_utc is None:
        return []

    sessions = sessions or default_sessions()
    out: List[Dict[str, Any]] = []

    for s in sessions:
        try:
            tz = pd.Timestamp.now(tz=timezone.utc).tz_convert(s.timezone).tzinfo  # type: ignore[assignment]
            # pandas Timestamp tz_convert returns tzinfo; we just need the tz name to convert via pandas
            local = ts_utc.dt.tz_convert(s.timezone)
        except Exception:
            continue

        start_min, end_min = s.start_end_minutes()
        mins = local.dt.hour * 60 + local.dt.minute

        if start_min <= end_min:
            in_sess = (mins >= start_min) & (mins < end_min)
            sess_date = local.dt.floor("D")
        else:
            # Cross-midnight session: date attribution to the start day.
            in_sess = (mins >= start_min) | (mins < end_min)
            sess_date = local.dt.floor("D")
            sess_date = sess_date.where(mins >= start_min, sess_date - pd.Timedelta(days=1))

        if not bool(in_sess.any()):
            continue

        df_sess = df.loc[in_sess.values].copy()
        local_sess_date = sess_date.loc[in_sess.values].copy()

        # Group into segments per (session_date) and keep the most recent N.
        grp = df_sess.groupby(local_sess_date)
        keys = list(grp.groups.keys())[-max_segments_per_session:]

        for k in keys:
            # pandas FutureWarning (pandas>=2.3):
            # When grouping with a length-1 list-like, get_group will require a
            # length-1 tuple key in a future version. Suppress the warning
            # without changing behavior (chart output determinism depends on it).
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"When grouping with a length-1 list-like.*",
                    category=FutureWarning,
                )
                try:
                    g = grp.get_group(k)
                except KeyError:
                    # Forward-compat (future pandas may require a 1-tuple key)
                    g = grp.get_group((k,))
            if g.empty:
                continue

            # Need timestamps for start/end.
            g_ts = _to_utc_ts_series(g)
            if g_ts is None or g_ts.dropna().empty:
                continue
            g_ts = g_ts.dropna()

            high = float(pd.to_numeric(g.get("high"), errors="coerce").max())
            low = float(pd.to_numeric(g.get("low"), errors="coerce").min())
            open_ = float(pd.to_numeric(g.get("open"), errors="coerce").iloc[0])
            close_ = float(pd.to_numeric(g.get("close"), errors="coerce").iloc[-1])
            avg = float(pd.to_numeric(g.get("close"), errors="coerce").mean())

            rng = high - low
            ticks = int(round(rng / tick_size)) if tick_size > 0 else 0

            out.append(
                {
                    "name": s.name,
                    "timezone": s.timezone,
                    "color": s.color,
                    "session": s.session,
                    "start": g_ts.iloc[0].isoformat(),
                    "end": g_ts.iloc[-1].isoformat(),
                    "open": open_,
                    "close": close_,
                    "high": high,
                    "low": low,
                    "avg": avg,
                    "range_ticks": ticks,
                }
            )

    # Sort by start time
    out.sort(key=lambda x: x.get("start") or "")
    return out


def compute_power_channel(
    df: pd.DataFrame,
    length: int = 130,
    atr_len: int = 200,
    atr_half_mult: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """ChartPrime-style S&R Power Channel (simplified, last-window only)."""
    if df is None or df.empty:
        return None
    if not all(c in df.columns for c in ("open", "high", "low", "close")):
        return None

    n = min(int(length), len(df))
    if n < 5:
        return None

    d = df.tail(n).copy()
    high_max = float(pd.to_numeric(d["high"], errors="coerce").max())
    low_min = float(pd.to_numeric(d["low"], errors="coerce").min())
    mid = (high_max + low_min) / 2.0

    # True range + ATR(atr_len)
    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window=max(2, int(atr_len)), min_periods=2).mean()
    atr_last = float(atr.iloc[-1]) if not atr.empty else 0.0
    band = atr_last * float(atr_half_mult)

    up = (pd.to_numeric(d["close"], errors="coerce") > pd.to_numeric(d["open"], errors="coerce")).sum()
    down = (pd.to_numeric(d["close"], errors="coerce") < pd.to_numeric(d["open"], errors="coerce")).sum()

    return {
        "length": int(length),
        "atr_len": int(atr_len),
        "band": float(band),
        "max": high_max,
        "min": low_min,
        "mid": float(mid),
        "top_line": float(high_max + band),
        "bottom_line": float(low_min - band),
        "res_area_top": float(high_max + band),
        "res_area_bottom": float(high_max - band),
        "sup_area_top": float(low_min + band),
        "sup_area_bottom": float(low_min - band),
        "buy_power": int(up),
        "sell_power": int(down),
    }


def compute_visible_range_supply_demand(
    df: pd.DataFrame,
    threshold_pct: float = 10.0,
    bins: int = 50,
) -> Optional[Dict[str, Any]]:
    """
    LuxAlgo Visible Range S/D approximation using bar OHLCV only.

    The original script uses lower-TF intrabar volume to bin volume within the
    visible range. Here we approximate by distributing each bar's volume evenly
    across the price buckets it spans (bounded, fast).
    """
    if df is None or df.empty:
        return None
    if not all(c in df.columns for c in ("high", "low", "volume")):
        return None

    high_max = float(pd.to_numeric(df["high"], errors="coerce").max())
    low_min = float(pd.to_numeric(df["low"], errors="coerce").min())
    if not np.isfinite(high_max) or not np.isfinite(low_min) or high_max <= low_min:
        return None

    bins = int(max(2, min(500, bins)))
    rng = high_max - low_min
    step = rng / bins
    if step <= 0:
        return None

    vols = np.zeros(bins, dtype=float)
    # Precompute bucket edges/centers
    centers = low_min + (np.arange(bins) + 0.5) * step

    highs = pd.to_numeric(df["high"], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(df["low"], errors="coerce").to_numpy(dtype=float)
    v = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0).to_numpy(dtype=float)

    for hi, lo, vol in zip(highs, lows, v):
        if not np.isfinite(hi) or not np.isfinite(lo) or vol <= 0:
            continue
        lo_i = int((min(hi, lo) - low_min) / step)
        hi_i = int((max(hi, lo) - low_min) / step)
        lo_i = max(0, min(bins - 1, lo_i))
        hi_i = max(0, min(bins - 1, hi_i))
        span = hi_i - lo_i + 1
        if span <= 0:
            continue
        vols[lo_i : hi_i + 1] += vol / span

    total = float(vols.sum())
    if total <= 0:
        return None

    thr = max(0.0, min(100.0, float(threshold_pct))) / 100.0

    # Demand: bottom-up
    cum_bot = np.cumsum(vols)
    d_idx = int(np.searchsorted(cum_bot, thr * total, side="left"))
    d_idx = max(0, min(bins - 1, d_idx))
    demand_bottom = low_min
    demand_top = low_min + (d_idx + 1) * step
    demand_avg = (demand_bottom + demand_top) / 2.0
    demand_wavg = float((centers[: d_idx + 1] * vols[: d_idx + 1]).sum() / max(1e-12, vols[: d_idx + 1].sum()))

    # Supply: top-down
    cum_top = np.cumsum(vols[::-1])
    s_rev_idx = int(np.searchsorted(cum_top, thr * total, side="left"))
    s_rev_idx = max(0, min(bins - 1, s_rev_idx))
    s_idx = bins - 1 - s_rev_idx
    supply_top = high_max
    supply_bottom = low_min + s_idx * step
    supply_avg = (supply_top + supply_bottom) / 2.0
    supply_wavg = float((centers[s_idx:] * vols[s_idx:]).sum() / max(1e-12, vols[s_idx:].sum()))

    equi_avg = (high_max + low_min) / 2.0
    equi_wavg = (supply_wavg + demand_wavg) / 2.0

    return {
        "threshold_pct": float(threshold_pct),
        "bins": int(bins),
        "range_high": high_max,
        "range_low": low_min,
        "supply": {
            "top": float(supply_top),
            "bottom": float(supply_bottom),
            "avg": float(supply_avg),
            "wavg": float(supply_wavg),
        },
        "demand": {
            "top": float(demand_top),
            "bottom": float(demand_bottom),
            "avg": float(demand_avg),
            "wavg": float(demand_wavg),
        },
        "equilibrium": {"avg": float(equi_avg), "wavg": float(equi_wavg)},
    }


def _compute_session_levels(
    df: pd.DataFrame,
    tz_name: str,
    start_min: int,
    end_min: int,
) -> Dict[str, Any]:
    """
    Compute current open + previous session high/low for a session window.

    This is used for both RTH (non-cross-midnight) and ETH (cross-midnight).
    """
    ts_utc = _to_utc_ts_series(df)
    if ts_utc is None:
        return {}

    local = ts_utc.dt.tz_convert(tz_name)
    mins = local.dt.hour * 60 + local.dt.minute

    if start_min <= end_min:
        in_sess = (mins >= start_min) & (mins < end_min)
        sess_date = local.dt.floor("D")
    else:
        in_sess = (mins >= start_min) | (mins < end_min)
        sess_date = local.dt.floor("D")
        sess_date = sess_date.where(mins >= start_min, sess_date - pd.Timedelta(days=1))

    if not bool(in_sess.any()):
        return {}

    d = df.loc[in_sess.values].copy()
    sess_date = sess_date.loc[in_sess.values]
    if d.empty:
        return {}

    # Choose current session by latest bar’s session date.
    try:
        cur_date = sess_date.iloc[-1]
    except Exception:
        return {}

    unique_dates = list(pd.Index(sess_date.unique()).sort_values())
    if cur_date not in unique_dates:
        return {}
    cur_idx = unique_dates.index(cur_date)
    prev_date = unique_dates[cur_idx - 1] if cur_idx - 1 >= 0 else None

    def _stats(g: pd.DataFrame) -> Dict[str, Any]:
        high = float(pd.to_numeric(g["high"], errors="coerce").max())
        low = float(pd.to_numeric(g["low"], errors="coerce").min())
        mid = (high + low) / 2.0
        open_ = float(pd.to_numeric(g["open"], errors="coerce").iloc[0])
        return {"high": high, "low": low, "mid": float(mid), "open": open_}

    cur = d.loc[sess_date == cur_date]
    cur_stats = _stats(cur) if not cur.empty else {}

    prev_stats = {}
    if prev_date is not None:
        prev = d.loc[sess_date == prev_date]
        prev_stats = _stats(prev) if not prev.empty else {}

    return {"current": cur_stats, "previous": prev_stats}


def compute_key_levels(
    df: pd.DataFrame,
    tz_name: str = "America/New_York",
) -> Dict[str, Any]:
    """
    Compute both RTH and ETH key levels (open + prev-day H/L/Mid).

    Output is compact and designed for right-side label merging in charts.
    """
    # RTH: 09:30–16:00 ET
    rth = _compute_session_levels(df, tz_name=tz_name, start_min=9 * 60 + 30, end_min=16 * 60)
    # ETH: 18:00–17:00 ET (cross-midnight)
    eth = _compute_session_levels(df, tz_name=tz_name, start_min=18 * 60, end_min=17 * 60)
    return {"tz": tz_name, "rth": rth, "eth": eth}


def compute_tbt_trendlines(
    df: pd.DataFrame,
    period: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    Simplified TBT-style trendlines + breakout detection (bounded).

    We fit trendlines from the most recent two pivot highs (bearish) and pivot
    lows (bullish) and check for close cross.
    """
    if df is None or df.empty:
        return None
    if not all(c in df.columns for c in ("open", "high", "low", "close")):
        return None
    if len(df) < (period * 2):
        return None

    p = int(max(2, period))
    right = max(1, p // 2)
    left = p
    win = left + right + 1

    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")

    ph = high.rolling(win, center=True, min_periods=win).max()
    pl = low.rolling(win, center=True, min_periods=win).min()

    pivot_high_idx = np.where((high == ph).to_numpy(dtype=bool))[0]
    pivot_low_idx = np.where((low == pl).to_numpy(dtype=bool))[0]

    def _last_two(idxs: np.ndarray) -> Optional[Tuple[int, int]]:
        if idxs is None or len(idxs) < 2:
            return None
        return int(idxs[-2]), int(idxs[-1])

    last_two_hi = _last_two(pivot_high_idx)
    last_two_lo = _last_two(pivot_low_idx)

    def _line_at(x1: int, y1: float, x2: int, y2: float, x: int) -> float:
        if x2 == x1:
            return float(y2)
        m = (y2 - y1) / (x2 - x1)
        return float(y2 + m * (x - x2))

    x_last = len(df) - 1
    x_prev = len(df) - 2

    bearish = None
    bullish = None

    if last_two_hi:
        a, b = last_two_hi
        bearish = {
            "x1": a,
            "y1": float(high.iloc[a]),
            "x2": b,
            "y2": float(high.iloc[b]),
            "y_last": _line_at(a, float(high.iloc[a]), b, float(high.iloc[b]), x_last),
            "y_prev": _line_at(a, float(high.iloc[a]), b, float(high.iloc[b]), x_prev),
        }

    if last_two_lo:
        a, b = last_two_lo
        bullish = {
            "x1": a,
            "y1": float(low.iloc[a]),
            "x2": b,
            "y2": float(low.iloc[b]),
            "y_last": _line_at(a, float(low.iloc[a]), b, float(low.iloc[b]), x_last),
            "y_prev": _line_at(a, float(low.iloc[a]), b, float(low.iloc[b]), x_prev),
        }

    long_breakout = False
    short_breakout = False
    if bearish:
        long_breakout = bool(close.iloc[x_prev] < bearish["y_prev"] and close.iloc[x_last] > bearish["y_last"])
    if bullish:
        short_breakout = bool(close.iloc[x_prev] > bullish["y_prev"] and close.iloc[x_last] < bullish["y_last"])

    # Target sizing (approx) – used only for chart HUD, not strategy execution.
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_30 = tr.rolling(30, min_periods=5).mean()
    atr_val = float(atr_30.iloc[-1]) if not atr_30.empty else float(tr.rolling(14, min_periods=2).mean().iloc[-1])
    last_close = float(close.iloc[-1])
    zband = min(atr_val * 0.3, last_close * 0.003) / 2.0

    tp = None
    sl = None
    if long_breakout:
        tp = float(high.iloc[-1] + (zband * 20.0))
        sl = float(low.iloc[-1] - (zband * 20.0))
    elif short_breakout:
        tp = float(low.iloc[-1] - (zband * 20.0))
        sl = float(high.iloc[-1] + (zband * 20.0))

    return {
        "period": int(period),
        "zband": float(zband),
        "bearish": bearish,
        "bullish": bullish,
        "long_breakout": bool(long_breakout),
        "short_breakout": bool(short_breakout),
        "tp": tp,
        "sl": sl,
    }


def build_hud_context(
    df: pd.DataFrame,
    *,
    symbol: str = "MNQ",
    tick_size: float = 0.25,
    vwap_data: Optional[Dict[str, Any]] = None,
    volume_profile: Optional[Dict[str, Any]] = None,
    sr_levels: Optional[Dict[str, Any]] = None,
    threshold_pct: float = 10.0,
    bins: int = 50,
    power_length: int = 130,
    tbt_period: int = 10,
) -> Dict[str, Any]:
    """
    Build a compact, JSON-safe HUD context dict for chart rendering.
    """
    ctx: Dict[str, Any] = {
        "symbol": str(symbol),
        "tick_size": float(tick_size),
    }

    # Sessions (Tokyo/London/NY)
    try:
        ctx["sessions"] = compute_sessions(df, tick_size=tick_size)
    except Exception:
        ctx["sessions"] = []

    # Key levels (RTH + ETH)
    try:
        ctx["key_levels"] = compute_key_levels(df)
    except Exception:
        ctx["key_levels"] = {}

    # Visible range supply/demand zones (approx)
    try:
        ctx["supply_demand_vr"] = compute_visible_range_supply_demand(df, threshold_pct=threshold_pct, bins=bins)
    except Exception:
        ctx["supply_demand_vr"] = None

    # Power channel
    try:
        ctx["power_channel"] = compute_power_channel(df, length=power_length)
    except Exception:
        ctx["power_channel"] = None

    # Trendlines + breakout targets (simplified)
    try:
        ctx["tbt"] = compute_tbt_trendlines(df, period=tbt_period)
    except Exception:
        ctx["tbt"] = None

    # Pass-through existing context (small + already JSON-safe)
    if isinstance(vwap_data, dict):
        ctx["vwap"] = vwap_data
    if isinstance(volume_profile, dict):
        ctx["volume_profile"] = volume_profile
    if isinstance(sr_levels, dict):
        ctx["sr_levels"] = sr_levels

    return ctx


