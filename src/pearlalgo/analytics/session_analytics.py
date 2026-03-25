"""
Session & time-based performance analytics.

Extracted from ``api_server._get_session_analytics`` so the computation logic
lives in the analytics package and can be reused / tested independently.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ── session definitions (ET timezone) ────────────────────────────────────
_SESSION_DEFS = {
    "overnight": {"start": 18, "end": 4, "name": "Overnight"},
    "premarket": {"start": 4, "end": 6, "name": "Premarket"},
    "morning": {"start": 6, "end": 10, "name": "Morning"},
    "midday": {"start": 10, "end": 14, "name": "Midday"},
    "afternoon": {"start": 14, "end": 17, "name": "Afternoon"},
    "close": {"start": 17, "end": 18, "name": "Close"},
}

_DURATION_DEFS = {
    "quick": "Quick (<30m)",
    "medium": "Medium (30-60m)",
    "long": "Long (60m+)",
}


def _get_et_tz():
    """Return the America/New_York ZoneInfo, with backports fallback."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
    return ZoneInfo("America/New_York")


def _get_session_for_hour(hour: int) -> str:
    """Determine which session an hour belongs to."""
    if hour >= 18 or hour < 4:
        return "overnight"
    elif 4 <= hour < 6:
        return "premarket"
    elif 6 <= hour < 10:
        return "morning"
    elif 10 <= hour < 14:
        return "midday"
    elif 14 <= hour < 17:
        return "afternoon"
    else:  # 17-18
        return "close"


def _parse_iso(ts: str) -> datetime:
    """Parse a trade timestamp → naive ET datetime.  # FIXED 2026-03-25: ET timestamps"""
    from pearlalgo.utils.paths import parse_trade_timestamp
    return parse_trade_timestamp(str(ts))


# ── public API ───────────────────────────────────────────────────────────


def compute_session_analytics(
    signals: List[Dict[str, Any]],
    performance_trades: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute session and time-based performance analytics.

    Parameters
    ----------
    signals:
        Rows from ``signals.jsonl`` (list of dicts).  Used for status
        breakdown, hold-duration analysis from signal timestamps, and
        calendar data.
    performance_trades:
        The ``trades`` list from ``performance.json``.  Used for session /
        hourly / direction / duration analysis based on closed-trade data.

    Returns
    -------
    dict
        Keys: ``session_performance``, ``best_hours``, ``worst_hours``,
        ``hold_duration``, ``direction_breakdown``, ``status_breakdown``,
        ``calendar_data``.
    """
    et_tz = _get_et_tz()

    # ── accumulators ─────────────────────────────────────────────────
    sessions: Dict[str, Dict[str, Any]] = {
        key: {"name": defn["name"], "pnl": 0.0, "wins": 0, "losses": 0}
        for key, defn in _SESSION_DEFS.items()
    }

    hourly_stats: Dict[int, Dict[str, Any]] = {
        h: {"pnl": 0.0, "trades": 0, "wins": 0} for h in range(24)
    }

    duration_stats: Dict[str, Dict[str, Any]] = {
        key: {"name": label, "pnl": 0.0, "wins": 0, "losses": 0}
        for key, label in _DURATION_DEFS.items()
    }

    direction_stats: Dict[str, Dict[str, Any]] = {
        "long": {"count": 0, "pnl": 0.0},
        "short": {"count": 0, "pnl": 0.0},
    }

    status_breakdown: Dict[str, int] = {
        "generated": 0,
        "entered": 0,
        "exited": 0,
        "cancelled": 0,
    }

    # ── process performance.json trades (closed trades) ──────────────
    if performance_trades:
        try:
            for trade in performance_trades:
                exit_time_str = trade.get("exit_time")
                entry_time_str = trade.get("entry_time")
                pnl = trade.get("pnl", 0.0) or 0.0
                is_win = trade.get("is_win", pnl > 0)
                direction = trade.get("direction", "long").lower()

                # Direction stats
                if direction in direction_stats:
                    direction_stats[direction]["count"] += 1
                    direction_stats[direction]["pnl"] += pnl

                if exit_time_str:
                    try:
                        exit_time = _parse_iso(exit_time_str)
                        # FIXED 2026-03-25: timestamps are now stored as ET — no conversion needed
                        hour = exit_time.hour if exit_time.tzinfo is None else exit_time.astimezone(et_tz).hour

                        # Session stats
                        session_key = _get_session_for_hour(hour)
                        sessions[session_key]["pnl"] += pnl
                        if is_win:
                            sessions[session_key]["wins"] += 1
                        else:
                            sessions[session_key]["losses"] += 1

                        # Hourly stats
                        hourly_stats[hour]["pnl"] += pnl
                        hourly_stats[hour]["trades"] += 1
                        if is_win:
                            hourly_stats[hour]["wins"] += 1
                    except (ValueError, TypeError):
                        pass

                # Duration stats from performance.json
                if entry_time_str and exit_time_str:
                    try:
                        entry_time = _parse_iso(entry_time_str)
                        exit_time = _parse_iso(exit_time_str)
                        duration_minutes = (exit_time - entry_time).total_seconds() / 60

                        if duration_minutes < 30:
                            duration_key = "quick"
                        elif duration_minutes < 60:
                            duration_key = "medium"
                        else:
                            duration_key = "long"

                        duration_stats[duration_key]["pnl"] += pnl
                        if is_win:
                            duration_stats[duration_key]["wins"] += 1
                        else:
                            duration_stats[duration_key]["losses"] += 1
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.debug("Non-critical: %s", e)

    # ── process signals for status breakdown AND hold duration ────────
    if signals:
        try:
            for s in signals:
                if s.get("status") == "exited":
                    et_str = s.get("entry_time")
                    xt_str = s.get("exit_time")
                    pnl = s.get("pnl", 0) or 0
                    is_win = pnl > 0
                    if et_str and xt_str:
                        try:
                            et_dt = _parse_iso(et_str)
                            xt_dt = _parse_iso(xt_str)
                            dur_min = (xt_dt - et_dt).total_seconds() / 60
                            if dur_min < 30:
                                dk = "quick"
                            elif dur_min < 60:
                                dk = "medium"
                            else:
                                dk = "long"
                            duration_stats[dk]["pnl"] += pnl
                            if is_win:
                                duration_stats[dk]["wins"] += 1
                            else:
                                duration_stats[dk]["losses"] += 1
                        except (ValueError, TypeError):
                            pass

            for s in signals:
                status = s.get("status", "").lower()
                if status in status_breakdown:
                    status_breakdown[status] += 1
        except Exception as e:
            logger.debug("Non-critical: %s", e)

    # ── format session performance ───────────────────────────────────
    session_performance = []
    for key, session in sessions.items():
        total = session["wins"] + session["losses"]
        win_rate = round(session["wins"] / total * 100, 1) if total > 0 else 0.0
        session_performance.append({
            "id": key,
            "name": session["name"],
            "pnl": round(session["pnl"], 2),
            "wins": session["wins"],
            "losses": session["losses"],
            "win_rate": win_rate,
        })

    # ── best / worst hours (min 5 trades) ────────────────────────────
    qualified_hours = [
        {"hour": h, **stats}
        for h, stats in hourly_stats.items()
        if stats["trades"] >= 5
    ]

    sorted_by_pnl = sorted(qualified_hours, key=lambda x: x["pnl"], reverse=True)
    best_hours: List[Dict[str, Any]] = []
    worst_hours: List[Dict[str, Any]] = []

    for h in sorted_by_pnl[:3]:
        win_rate = round(h["wins"] / h["trades"] * 100, 1) if h["trades"] > 0 else 0.0
        best_hours.append({
            "hour": h["hour"],
            "hour_label": f"{h['hour']:02d}:00 ET",
            "pnl": round(h["pnl"], 2),
            "trades": h["trades"],
            "win_rate": win_rate,
        })

    for h in sorted_by_pnl[-3:][::-1]:  # Reverse to get worst first
        if h["pnl"] < 0:  # Only include negative hours
            win_rate = round(h["wins"] / h["trades"] * 100, 1) if h["trades"] > 0 else 0.0
            worst_hours.append({
                "hour": h["hour"],
                "hour_label": f"{h['hour']:02d}:00 ET",
                "pnl": round(h["pnl"], 2),
                "trades": h["trades"],
                "win_rate": win_rate,
            })

    # ── hold duration breakdown ──────────────────────────────────────
    hold_duration: List[Dict[str, Any]] = []
    for key, dur in duration_stats.items():
        total = dur["wins"] + dur["losses"]
        win_rate = round(dur["wins"] / total * 100, 1) if total > 0 else 0.0
        hold_duration.append({
            "id": key,
            "name": dur["name"],
            "pnl": round(dur["pnl"], 2),
            "wins": dur["wins"],
            "losses": dur["losses"],
            "win_rate": win_rate,
        })

    # ── direction breakdown ──────────────────────────────────────────
    direction_breakdown = {
        "long": {
            "count": direction_stats["long"]["count"],
            "pnl": round(direction_stats["long"]["pnl"], 2),
        },
        "short": {
            "count": direction_stats["short"]["count"],
            "pnl": round(direction_stats["short"]["pnl"], 2),
        },
    }

    # ── calendar data (from signals) ─────────────────────────────────
    cal_by_date: Dict[str, Dict[str, float]] = defaultdict(lambda: {"pnl": 0.0, "trades": 0})
    if signals:
        try:
            for s in signals:
                if s.get("status") != "exited":
                    continue
                xt = s.get("exit_time", "")
                if xt:
                    dk = str(xt)[:10]
                    cal_by_date[dk]["pnl"] += (s.get("pnl") or 0)
                    cal_by_date[dk]["trades"] += 1
        except Exception as e:
            logger.debug("Non-critical: %s", e)

    calendar_data = [
        {"date": d, "pnl": round(v["pnl"], 2), "trades": int(v["trades"])}
        for d, v in sorted(cal_by_date.items())
    ]

    return {
        "session_performance": session_performance,
        "best_hours": best_hours,
        "worst_hours": worst_hours,
        "hold_duration": hold_duration,
        "direction_breakdown": direction_breakdown,
        "status_breakdown": status_breakdown,
        "calendar_data": calendar_data,
    }
