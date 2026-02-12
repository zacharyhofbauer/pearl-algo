"""Incident analysis: trade records, exposure metrics, and reporting.

Extracted from ``scripts/monitoring/incident_report.py`` to provide
reusable analytics primitives.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pearlalgo.utils.market_hours import ET
from pearlalgo.utils.paths import parse_utc_timestamp


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TradeRecord:
    """Single closed trade parsed from the signals JSONL file."""

    signal_id: str
    exit_time: datetime
    entry_time: Optional[datetime]
    direction: str
    entry_price: float
    exit_price: float
    pnl: float
    is_win: bool
    exit_reason: str
    position_size: float
    tick_value: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    entry_trigger: str
    regime: str
    confidence: Optional[float]
    risk_reward: Optional[float]
    duplicate: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    if pct <= 0:
        return min(values)
    if pct >= 1:
        return max(values)
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return d0 + d1


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_trades(
    signals_file: Path,
    start_utc: datetime,
) -> Tuple[List[TradeRecord], List[Dict[str, Any]]]:
    """Load closed trades from *signals_file* that exited after *start_utc*."""
    trades: List[TradeRecord] = []
    raw_records: List[Dict[str, Any]] = []
    if not signals_file.exists():
        return trades, raw_records
    with signals_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            status = record.get("status")
            exit_time_str = record.get("exit_time")
            if status != "exited" or not exit_time_str:
                continue

            try:
                exit_time = parse_utc_timestamp(exit_time_str)
            except Exception:
                continue

            if exit_time < start_utc:
                continue

            sig = record.get("signal", {}) or {}
            if not isinstance(sig, dict):
                sig = {}

            entry_time = None
            entry_time_str = record.get("entry_time")
            if entry_time_str:
                try:
                    entry_time = parse_utc_timestamp(entry_time_str)
                except Exception:
                    entry_time = None

            indicators = sig.get("indicators", {}) or {}
            if not isinstance(indicators, dict):
                indicators = {}

            market_regime = sig.get("market_regime") or sig.get("regime") or {}
            if isinstance(market_regime, dict):
                regime = str(market_regime.get("regime", "unknown") or "unknown")
            else:
                regime = str(market_regime or "unknown")

            position_size = _safe_float(sig.get("position_size", 1.0), 1.0)
            tick_value = _safe_float(sig.get("tick_value", 2.0), 2.0)
            entry_price = _safe_float(sig.get("entry_price"), 0.0)
            exit_price = _safe_float(record.get("exit_price"), 0.0)

            trades.append(
                TradeRecord(
                    signal_id=str(record.get("signal_id") or ""),
                    exit_time=exit_time,
                    entry_time=entry_time,
                    direction=str(sig.get("direction", "unknown") or "unknown"),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=_safe_float(record.get("pnl"), 0.0),
                    is_win=bool(record.get("is_win", False)),
                    exit_reason=str(record.get("exit_reason", "unknown") or "unknown"),
                    position_size=position_size,
                    tick_value=tick_value,
                    stop_loss=(
                        _safe_float(sig.get("stop_loss"), 0.0) if sig.get("stop_loss") is not None else None
                    ),
                    take_profit=(
                        _safe_float(sig.get("take_profit"), 0.0) if sig.get("take_profit") is not None else None
                    ),
                    entry_trigger=str(indicators.get("entry_trigger", sig.get("entry_trigger", "unknown")) or "unknown"),
                    regime=regime,
                    confidence=(
                        float(sig.get("confidence")) if sig.get("confidence") is not None else None
                    ),
                    risk_reward=(
                        float(sig.get("risk_reward")) if sig.get("risk_reward") is not None else None
                    ),
                    duplicate=bool(record.get("duplicate", False)),
                )
            )
            raw_records.append(record)

    return trades, raw_records


def load_events(
    events_file: Path,
    start_utc: datetime,
) -> Dict[str, int]:
    """Load event counts from *events_file* since *start_utc*."""
    counts: Dict[str, int] = defaultdict(int)
    if not events_file.exists():
        return counts
    with events_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = record.get("timestamp")
            if not ts:
                continue
            try:
                event_time = parse_utc_timestamp(ts)
            except Exception:
                continue
            if event_time < start_utc:
                continue
            event_type = str(record.get("type", "unknown") or "unknown")
            counts[event_type] += 1
    return counts


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def compute_exposure(trades: List[TradeRecord]) -> Dict[str, Any]:
    """Compute concurrent-position and stop-risk exposure metrics."""
    intervals: List[Tuple[datetime, int]] = []
    risk_events: List[Tuple[datetime, float]] = []
    stop_points: List[float] = []

    for t in trades:
        if t.entry_time and t.exit_time:
            intervals.append((t.entry_time, 1))
            intervals.append((t.exit_time, -1))
        if t.stop_loss is not None and t.entry_price > 0:
            stop_pts = abs(t.entry_price - t.stop_loss)
            stop_points.append(stop_pts)
            if t.entry_time and t.exit_time:
                risk_dollars = stop_pts * t.tick_value * t.position_size
                risk_events.append((t.entry_time, risk_dollars))
                risk_events.append((t.exit_time, -risk_dollars))

    def _fold_events(events: List[Tuple[datetime, float]]) -> Dict[str, Any]:
        if not events:
            return {"max": 0.0, "series_points": 0}
        events_sorted = sorted(events, key=lambda x: (x[0], 0 if x[1] < 0 else 1))
        current = 0.0
        max_val = 0.0
        for _, delta in events_sorted:
            current += delta
            max_val = max(max_val, current)
        return {"max": max_val, "series_points": len(events_sorted)}

    exposure: Dict[str, Any] = {
        "max_concurrent_positions": 0,
        "max_stop_risk_dollars": 0.0,
        "stop_points_stats": {
            "count": len(stop_points),
            "min": min(stop_points) if stop_points else None,
            "max": max(stop_points) if stop_points else None,
            "avg": sum(stop_points) / len(stop_points) if stop_points else None,
            "p50": _percentile(stop_points, 0.5),
            "p90": _percentile(stop_points, 0.9),
        },
    }

    if intervals:
        intervals_sorted = sorted(intervals, key=lambda x: (x[0], 0 if x[1] < 0 else 1))
        current = 0
        max_val = 0
        for _, delta in intervals_sorted:
            current += delta
            max_val = max(max_val, current)
        exposure["max_concurrent_positions"] = max_val

    risk_summary = _fold_events(risk_events)
    exposure["max_stop_risk_dollars"] = risk_summary["max"]
    exposure["risk_event_points"] = risk_summary["series_points"]
    return exposure


def group_stats(
    trades: List[TradeRecord],
    key_fn: Callable[[TradeRecord], Any],
) -> Dict[str, Dict[str, Any]]:
    """Group *trades* by *key_fn* and compute per-bucket statistics."""
    buckets: Dict[str, List[TradeRecord]] = defaultdict(list)
    for t in trades:
        buckets[str(key_fn(t) or "unknown")].append(t)
    results: Dict[str, Dict[str, Any]] = {}
    for key, items in buckets.items():
        total_pnl = sum(t.pnl for t in items)
        wins = sum(1 for t in items if t.is_win)
        results[key] = {
            "count": len(items),
            "wins": wins,
            "losses": len(items) - wins,
            "win_rate": wins / len(items) if items else 0.0,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(items) if items else 0.0,
        }
    return results


def build_incident_report(
    trades: List[TradeRecord],
    start_utc: datetime,
    event_counts: Dict[str, int],
    challenge_state: Optional[Dict[str, Any]],
    challenge_history: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Build a complete incident-report dict from analysed trade data."""
    total_pnl = sum(t.pnl for t in trades)
    wins = sum(1 for t in trades if t.is_win)
    losses = len(trades) - wins
    avg_pnl = total_pnl / len(trades) if trades else 0.0

    biggest_losses = sorted(
        [t for t in trades if t.pnl < 0],
        key=lambda t: t.pnl,
    )[:10]

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start_utc": start_utc.isoformat(),
        "window_start_et": start_utc.astimezone(ET).isoformat(),
        "window_end_utc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(trades) if trades else 0.0,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
        },
        "breakdown": {
            "by_direction": group_stats(trades, lambda t: t.direction),
            "by_entry_trigger": group_stats(trades, lambda t: t.entry_trigger),
            "by_regime": group_stats(trades, lambda t: t.regime),
            "by_exit_reason": group_stats(trades, lambda t: t.exit_reason),
        },
        "exposure": compute_exposure(trades),
        "duplicates": {
            "count": sum(1 for t in trades if t.duplicate),
        },
        "events": event_counts,
        "biggest_losses": [
            {
                **asdict(t),
                "exit_time": t.exit_time.isoformat(),
                "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            }
            for t in biggest_losses
        ],
        "challenge_state": challenge_state,
        "challenge_history": challenge_history[-5:] if challenge_history else None,
    }
    return report
