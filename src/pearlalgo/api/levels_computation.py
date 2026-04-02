"""Extracted from server.py — computes key price levels from daily OHLC bars."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def _calc_mid(high: Optional[float], low: Optional[float]) -> Optional[float]:
    """Calculate midpoint of high and low, returning None if either is None."""
    if high is not None and low is not None:
        return round((high + low) / 2, 2)
    return None


def bars_to_levels(bars: List[Dict[str, Any]], now_utc: datetime, *, et_tz) -> Dict[str, Any]:
    """
    Compute key price levels from daily OHLC bars.

    Expects bars sorted ascending by time with keys: time, open, high, low, close.

    Parameters
    ----------
    bars : list of dict
        Daily OHLCV bars.
    now_utc : datetime
        Current time as naive ET datetime.
    et_tz : pytz timezone
        The Eastern Time timezone object (``pytz.timezone("America/New_York")``).
    """
    if not bars:
        return {k: None for k in [
            "daily_open", "prev_day_high", "prev_day_low", "prev_day_mid",
            "monday_high", "monday_low", "monday_mid",
            "weekly_open", "prev_week_high", "prev_week_low", "prev_week_mid",
            "monthly_open", "prev_month_high", "prev_month_low", "prev_month_mid",
        ]}

    from datetime import date as _date

    # Convert bar timestamps to date-keyed dicts
    daily: List[Dict[str, Any]] = []
    for b in bars:
        ts = b.get("time", 0)
        dt = datetime.fromtimestamp(ts, tz=et_tz).replace(tzinfo=None) if ts else None  # FIXED 2026-03-25: ET
        if dt is None:
            continue
        daily.append({
            "date": dt.date(),
            "weekday": dt.weekday(),  # 0=Monday
            "open": b.get("open"),
            "high": b.get("high"),
            "low": b.get("low"),
            "close": b.get("close"),
        })

    daily.sort(key=lambda x: x["date"])
    result: Dict[str, Any] = {}

    # --- Daily levels ---
    if len(daily) >= 1:
        today_bar = daily[-1]
        result["daily_open"] = today_bar["open"]
    else:
        result["daily_open"] = None

    if len(daily) >= 2:
        prev_bar = daily[-2]
        result["prev_day_high"] = prev_bar["high"]
        result["prev_day_low"] = prev_bar["low"]
        result["prev_day_mid"] = _calc_mid(prev_bar["high"], prev_bar["low"])
    else:
        result["prev_day_high"] = None
        result["prev_day_low"] = None
        result["prev_day_mid"] = None

    # --- Monday range (current week) ---
    today = now_utc.date()
    # Find the Monday of the current ISO week
    days_since_monday = today.weekday()  # 0=Mon
    this_monday = today - timedelta(days=days_since_monday)

    monday_bar = None
    for d in daily:
        if d["date"] == this_monday:
            monday_bar = d
            break

    if monday_bar:
        result["monday_high"] = monday_bar["high"]
        result["monday_low"] = monday_bar["low"]
        result["monday_mid"] = _calc_mid(monday_bar["high"], monday_bar["low"])
    else:
        result["monday_high"] = None
        result["monday_low"] = None
        result["monday_mid"] = None

    # --- Weekly levels ---
    # Group bars by ISO week
    weeks: Dict[tuple, List[Dict]] = defaultdict(list)
    for d in daily:
        iso = d["date"].isocalendar()
        weeks[(iso[0], iso[1])].append(d)

    sorted_weeks = sorted(weeks.keys())
    if sorted_weeks:
        current_week_key = sorted_weeks[-1]
        current_week_bars = weeks[current_week_key]
        # Weekly open = open of first bar of the week
        result["weekly_open"] = current_week_bars[0]["open"]

        if len(sorted_weeks) >= 2:
            prev_week_key = sorted_weeks[-2]
            prev_week_bars = weeks[prev_week_key]
            pw_high = max(b["high"] for b in prev_week_bars if b["high"] is not None)
            pw_low = min(b["low"] for b in prev_week_bars if b["low"] is not None)
            result["prev_week_high"] = pw_high
            result["prev_week_low"] = pw_low
            result["prev_week_mid"] = _calc_mid(pw_high, pw_low)
        else:
            result["prev_week_high"] = None
            result["prev_week_low"] = None
            result["prev_week_mid"] = None
    else:
        result["weekly_open"] = None
        result["prev_week_high"] = None
        result["prev_week_low"] = None
        result["prev_week_mid"] = None

    # --- Monthly levels ---
    months: Dict[tuple, List[Dict]] = defaultdict(list)
    for d in daily:
        months[(d["date"].year, d["date"].month)].append(d)

    sorted_months = sorted(months.keys())
    if sorted_months:
        current_month_key = sorted_months[-1]
        current_month_bars = months[current_month_key]
        result["monthly_open"] = current_month_bars[0]["open"]

        if len(sorted_months) >= 2:
            prev_month_key = sorted_months[-2]
            prev_month_bars = months[prev_month_key]
            pm_high = max(b["high"] for b in prev_month_bars if b["high"] is not None)
            pm_low = min(b["low"] for b in prev_month_bars if b["low"] is not None)
            result["prev_month_high"] = pm_high
            result["prev_month_low"] = pm_low
            result["prev_month_mid"] = _calc_mid(pm_high, pm_low)
        else:
            result["prev_month_high"] = None
            result["prev_month_low"] = None
            result["prev_month_mid"] = None
    else:
        result["monthly_open"] = None
        result["prev_month_high"] = None
        result["prev_month_low"] = None
        result["prev_month_mid"] = None

    return result
