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


def compute_spaceman_key_levels(
    df: pd.DataFrame,
    tz_name: str = "America/New_York",
) -> Dict[str, Any]:
    """
    Compute additional "SpacemanBTC Key Levels" style higher-timeframe levels.

    This is inspired by the TradingView script:
      "Key Levels SpacemanBTC" (community variants)

    Designed for chart/HUD use:
    - Uses ONLY the passed dataframe (no external provider calls).
    - Returns partial data when history is insufficient (callers should treat missing values as optional).

    Output schema (all floats, optional):
      {
        "tz": "...",
        "intra_4h": {"current": {"open": ...}, "previous": {"high": ..., "low": ..., "mid": ...}},
        "weekly":    {"current": {"open": ...}, "previous": {"high": ..., "low": ..., "mid": ...}},
        "monthly":   {"current": {"open": ...}, "previous": {"high": ..., "low": ..., "mid": ...}},
        "quarterly": {"current": {"open": ...}, "previous": {"high": ..., "low": ..., "mid": ...}},
        "yearly":    {"current": {"open": ..., "high": ..., "low": ..., "mid": ...}},
        "monday":    {"high": ..., "low": ..., "mid": ...},
      }
    """
    ts_utc = _to_utc_ts_series(df)
    if ts_utc is None or df is None or df.empty:
        return {"tz": tz_name}
    if not all(c in df.columns for c in ("open", "high", "low", "close")):
        return {"tz": tz_name}

    # Normalize series
    open_ = pd.to_numeric(df["open"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")

    # Build an ordered working frame (needed for "open = first")
    try:
        t = pd.to_datetime(ts_utc, errors="coerce")
    except Exception:
        return {"tz": tz_name}

    w = pd.DataFrame(
        {
            "ts": t,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
        }
    ).dropna(subset=["ts"])
    if w.empty:
        return {"tz": tz_name}

    # Ensure stable ordering
    w = w.sort_values("ts").reset_index(drop=True)

    out: Dict[str, Any] = {"tz": tz_name}

    # ------------------------------------------------------------
    # 4H (Prev 4H H/L/M + current 4H open)
    # ------------------------------------------------------------
    try:
        tmp = w.set_index(pd.DatetimeIndex(w["ts"]))
        # pandas deprecates uppercase frequency strings (FutureWarning in pandas>=2.2)
        bars_4h = tmp[["open", "high", "low", "close"]].resample("4h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}
        )
        bars_4h = bars_4h.dropna(subset=["open", "high", "low"])
        if len(bars_4h) >= 2:
            cur = bars_4h.iloc[-1]
            prev = bars_4h.iloc[-2]
            out["intra_4h"] = {
                "current": {"open": float(cur["open"])},
                "previous": {
                    "high": float(prev["high"]),
                    "low": float(prev["low"]),
                    "mid": float((float(prev["high"]) + float(prev["low"])) / 2.0),
                },
            }
    except Exception:
        pass

    # Local time keys for higher TF grouping (TradingView-like)
    try:
        local = w["ts"].dt.tz_convert(tz_name)
        local_naive = local.dt.tz_localize(None)
    except Exception:
        # If tz conversion fails, fall back to naive (assume already local)
        local_naive = pd.to_datetime(w["ts"], errors="coerce").dt.tz_localize(None)

    # Helper: compute OHLC aggregates per group
    def _agg_by_key(key: pd.Series) -> pd.DataFrame:
        tmp2 = w.copy()
        tmp2["key"] = key.values
        tmp2 = tmp2.dropna(subset=["key"])
        if tmp2.empty:
            return pd.DataFrame()
        g = tmp2.groupby("key", sort=True)
        o = g["open"].first()
        h = g["high"].max()
        l = g["low"].min()
        out_df = pd.DataFrame({"open": o, "high": h, "low": l})
        out_df["mid"] = (out_df["high"] + out_df["low"]) / 2.0
        return out_df

    # Current "week start" (Monday) key
    try:
        day_start = local_naive.dt.floor("D")
        week_start = day_start - pd.to_timedelta(local_naive.dt.weekday, unit="D")
    except Exception:
        week_start = pd.Series([pd.NaT] * len(w))

    # Weekly
    try:
        weekly_df = _agg_by_key(week_start)
        if not weekly_df.empty:
            cur_key = week_start.iloc[-1]
            keys = list(weekly_df.index)
            if cur_key in weekly_df.index:
                cur_row = weekly_df.loc[cur_key]
                # Find previous key if available
                prev_key = None
                idx = keys.index(cur_key) if cur_key in keys else None
                if idx is not None and idx - 1 >= 0:
                    prev_key = keys[idx - 1]
                out["weekly"] = {"current": {"open": float(cur_row["open"])}}
                if prev_key is not None:
                    prev_row = weekly_df.loc[prev_key]
                    out["weekly"]["previous"] = {
                        "high": float(prev_row["high"]),
                        "low": float(prev_row["low"]),
                        "mid": float(prev_row["mid"]),
                    }
    except Exception:
        pass

    # Monthly
    try:
        month_key = local_naive.dt.to_period("M").dt.to_timestamp()
        monthly_df = _agg_by_key(month_key)
        if not monthly_df.empty:
            cur_key = month_key.iloc[-1]
            keys = list(monthly_df.index)
            if cur_key in monthly_df.index:
                cur_row = monthly_df.loc[cur_key]
                prev_key = None
                idx = keys.index(cur_key) if cur_key in keys else None
                if idx is not None and idx - 1 >= 0:
                    prev_key = keys[idx - 1]
                out["monthly"] = {"current": {"open": float(cur_row["open"])}}
                if prev_key is not None:
                    prev_row = monthly_df.loc[prev_key]
                    out["monthly"]["previous"] = {
                        "high": float(prev_row["high"]),
                        "low": float(prev_row["low"]),
                        "mid": float(prev_row["mid"]),
                    }
    except Exception:
        pass

    # Quarterly
    try:
        q_key = local_naive.dt.to_period("Q").dt.start_time
        quarterly_df = _agg_by_key(q_key)
        if not quarterly_df.empty:
            cur_key = q_key.iloc[-1]
            keys = list(quarterly_df.index)
            if cur_key in quarterly_df.index:
                cur_row = quarterly_df.loc[cur_key]
                prev_key = None
                idx = keys.index(cur_key) if cur_key in keys else None
                if idx is not None and idx - 1 >= 0:
                    prev_key = keys[idx - 1]
                out["quarterly"] = {"current": {"open": float(cur_row["open"])}}
                if prev_key is not None:
                    prev_row = quarterly_df.loc[prev_key]
                    out["quarterly"]["previous"] = {
                        "high": float(prev_row["high"]),
                        "low": float(prev_row["low"]),
                        "mid": float(prev_row["mid"]),
                    }
    except Exception:
        pass

    # Yearly (current year open + current high/low/mid)
    try:
        y_key = local_naive.dt.to_period("Y").dt.start_time
        yearly_df = _agg_by_key(y_key)
        if not yearly_df.empty:
            cur_key = y_key.iloc[-1]
            if cur_key in yearly_df.index:
                cur_row = yearly_df.loc[cur_key]
                out["yearly"] = {
                    "current": {
                        "open": float(cur_row["open"]),
                        "high": float(cur_row["high"]),
                        "low": float(cur_row["low"]),
                        "mid": float(cur_row["mid"]),
                    }
                }
    except Exception:
        pass

    # Monday range (high/low/mid for Monday of current week)
    try:
        cur_week = week_start.iloc[-1]
        if pd.notna(cur_week):
            monday_date = pd.Timestamp(cur_week)
            day_start = local_naive.dt.floor("D")
            is_monday = (day_start == monday_date)
            if bool(is_monday.any()):
                h = float(w.loc[is_monday.values, "high"].max())
                l = float(w.loc[is_monday.values, "low"].min())
                if np.isfinite(h) and np.isfinite(l) and h > 0 and l > 0:
                    out["monday"] = {"high": h, "low": l, "mid": float((h + l) / 2.0)}
    except Exception:
        pass

    return out


def compute_tbt_trendlines(
    df: pd.DataFrame,
    period: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    TBT-style trendlines + breakout detection (bounded).

    This matches the core semantics of the TradingView Pine indicator:
      "Trendline Breakouts With Targets [ Chartprime ]" (MPL 2.0)

    Key behaviors preserved:
    - Pivots are confirmed `right = period//2` bars after the pivot bar (Pine `ta.pivothigh/low`).
    - Trendlines are built from the most recent two confirmed pivots (highs for bearish line, lows for bullish line).
    - Breakout is detected on close crossing the active trendline.
    - Short breakout uses a small buffer: `Zband * 0.1`.
    - Target/stop projection uses `Zband * 20`.
    - Zband is volatility-adjusted and shifted 20 bars in the original Pine.

    This is used for HUD/chart overlay only (not execution), so it is intentionally bounded.
    """
    if df is None or df.empty:
        return None
    if not all(c in df.columns for c in ("open", "high", "low", "close")):
        return None
    if len(df) < (period * 2):
        return None

    ts_utc = _to_utc_ts_series(df)
    if ts_utc is None or ts_utc.dropna().empty:
        return None

    p = int(max(2, period))
    right = max(1, p // 2)
    left = p

    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")

    # Zband (Pine volAdj): min(ATR(30)*0.3, close*0.3%)[20] / 2
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_30 = tr.rolling(30, min_periods=5).mean()
    base = np.minimum(atr_30 * 0.3, close * 0.003)
    zband_series = (pd.Series(base, index=df.index)).shift(20) / 2.0
    zband_series = zband_series.fillna((pd.Series(base, index=df.index)) / 2.0)
    try:
        zband = float(zband_series.iloc[-1])
    except Exception:
        zband = 0.0

    if not np.isfinite(zband) or zband <= 0:
        return None

    # Pivot detection (Pine-confirmed): output value at detection bar i, where pivot is at i-right.
    hi_arr = high.to_numpy(dtype=float)
    lo_arr = low.to_numpy(dtype=float)
    n = len(df)

    piv_h_events: List[Tuple[int, int, float]] = []  # (detect_idx, pivot_idx, pivot_val)
    piv_l_events: List[Tuple[int, int, float]] = []

    for i in range(left + right, n):
        pivot_idx = i - right
        a = pivot_idx - left
        b = pivot_idx + right + 1
        if a < 0 or b > n:
            continue

        # Pivot high
        w_hi = hi_arr[a:b]
        pv_hi = hi_arr[pivot_idx]
        if np.isfinite(pv_hi):
            mx = np.nanmax(w_hi)
            if np.isfinite(mx) and pv_hi == mx and np.sum(w_hi == pv_hi) == 1:
                piv_h_events.append((i, pivot_idx, float(pv_hi)))

        # Pivot low
        w_lo = lo_arr[a:b]
        pv_lo = lo_arr[pivot_idx]
        if np.isfinite(pv_lo):
            mn = np.nanmin(w_lo)
            if np.isfinite(mn) and pv_lo == mn and np.sum(w_lo == pv_lo) == 1:
                piv_l_events.append((i, pivot_idx, float(pv_lo)))

    def _latest_line(events: List[Tuple[int, int, float]]) -> Optional[Dict[str, Any]]:
        if len(events) < 2:
            return None
        # Use last two pivots (prev, curr)
        det_prev, piv_prev, y_prev = events[-2]
        det_curr, piv_curr, y_curr = events[-1]

        try:
            t1 = pd.Timestamp(ts_utc.iloc[piv_prev])
            t2 = pd.Timestamp(ts_utc.iloc[piv_curr])
        except Exception:
            return None
        if pd.isna(t1) or pd.isna(t2):
            return None

        dt = (t2 - t1).total_seconds()
        slope = float((y_curr - y_prev) / dt) if dt != 0 else 0.0

        # Current/previous line values (at last two bars)
        try:
            t_last = pd.Timestamp(ts_utc.iloc[-1])
            t_prev = pd.Timestamp(ts_utc.iloc[-2])
            y_last = float(y_prev + (t_last - t1).total_seconds() * slope)
            y_prev_line = float(y_prev + (t_prev - t1).total_seconds() * slope)
        except Exception:
            return None

        return {
            "start_time": t1.isoformat(),
            "start_price": float(y_prev),
            "end_time": t2.isoformat(),
            "end_price": float(y_curr),
            "slope_per_sec": float(slope),
            "updated_idx": int(det_curr),
            "y_last": float(y_last),
            "y_prev": float(y_prev_line),
        }

    bearish = _latest_line(piv_h_events)
    bullish = _latest_line(piv_l_events)

    x_last = len(df) - 1
    x_prev = len(df) - 2

    long_breakout = False
    short_breakout = False

    # Freshness gate: allow for <period bars after last pivot confirmation (Pine StartPrice[Period] != StartPrice)
    def _fresh(updated_idx: int) -> bool:
        try:
            return int((x_last - int(updated_idx))) < p
        except Exception:
            return False

    if bearish and float(bearish.get("slope_per_sec", 0.0) or 0.0) <= 0 and _fresh(int(bearish.get("updated_idx", 0) or 0)):
        try:
            long_breakout = bool(close.iloc[x_prev] < float(bearish["y_prev"]) and close.iloc[x_last] > float(bearish["y_last"]))
        except Exception:
            long_breakout = False

    if bullish and float(bullish.get("slope_per_sec", 0.0) or 0.0) >= 0 and _fresh(int(bullish.get("updated_idx", 0) or 0)):
        try:
            buf = zband * 0.1
            short_breakout = bool(
                (close.iloc[x_prev] > (float(bullish["y_prev"]) - buf))
                and (close.iloc[x_last] < (float(bullish["y_last"]) - buf))
            )
        except Exception:
            short_breakout = False

    tp = None
    sl = None
    try:
        if long_breakout:
            tp = float(high.iloc[-1] + (zband * 20.0))
            sl = float(low.iloc[-1] - (zband * 20.0))
        elif short_breakout:
            tp = float(low.iloc[-1] - (zband * 20.0))
            sl = float(high.iloc[-1] + (zband * 20.0))
    except Exception:
        tp = None
        sl = None

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


