#!/usr/bin/env python3
# ============================================================================
# Category: Monitoring
# Purpose: Generate incident report for recent drawdown window
# Usage:
#   python3 scripts/monitoring/incident_report.py --market NQ
# ============================================================================
"""
Incident Report Generator

Summarizes performance since a session start time (default: 18:00 ET) with:
- total PnL
- trade breakdown by direction/trigger/regime
- largest-loss drivers
- exposure metrics (concurrent positions, stop-risk exposure)
- duplicate signal counts

Outputs a JSON report into data/agent_state/<MARKET>/exports/.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pearlalgo.utils.market_hours import ET
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_events_file,
    get_signals_file,
    parse_utc_timestamp,
)


@dataclass
class TradeRecord:
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


def _parse_time_hhmm(value: str) -> Tuple[int, int]:
    parts = str(value).split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {value}")
    return int(parts[0]), int(parts[1])


def _default_window_start(now_utc: Optional[datetime] = None, start_hhmm: str = "18:00") -> datetime:
    now_utc = now_utc or datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    sh, sm = _parse_time_hhmm(start_hhmm)
    start_et = now_et.replace(hour=sh, minute=sm, second=0, microsecond=0)
    if now_et < start_et:
        start_et -= timedelta(days=1)
    return start_et.astimezone(timezone.utc)


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


def _load_trades(signals_file: Path, start_utc: datetime) -> Tuple[List[TradeRecord], List[Dict[str, Any]]]:
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


def _load_events(events_file: Path, start_utc: datetime) -> Dict[str, int]:
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


def _compute_exposure(trades: List[TradeRecord]) -> Dict[str, Any]:
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

    exposure = {
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


def _group_stats(trades: List[TradeRecord], key_fn) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, List[TradeRecord]] = defaultdict(list)
    for t in trades:
        buckets[str(key_fn(t) or "unknown")].append(t)
    results = {}
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


def _build_report(
    trades: List[TradeRecord],
    start_utc: datetime,
    event_counts: Dict[str, int],
    challenge_state: Optional[Dict[str, Any]],
    challenge_history: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    total_pnl = sum(t.pnl for t in trades)
    wins = sum(1 for t in trades if t.is_win)
    losses = len(trades) - wins
    avg_pnl = total_pnl / len(trades) if trades else 0.0

    biggest_losses = sorted(
        [t for t in trades if t.pnl < 0],
        key=lambda t: t.pnl,
    )[:10]

    report = {
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
            "by_direction": _group_stats(trades, lambda t: t.direction),
            "by_entry_trigger": _group_stats(trades, lambda t: t.entry_trigger),
            "by_regime": _group_stats(trades, lambda t: t.regime),
            "by_exit_reason": _group_stats(trades, lambda t: t.exit_reason),
        },
        "exposure": _compute_exposure(trades),
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a recent drawdown incident report")
    parser.add_argument("--market", default="NQ", help="Market label (default: NQ)")
    parser.add_argument("--state-dir", default=None, help="Override state directory")
    parser.add_argument("--since-iso", default=None, help="Explicit UTC ISO timestamp to start from")
    parser.add_argument("--since-et", default="18:00", help="Start time (ET, HH:MM). Default: 18:00")
    parser.add_argument("--output-path", default=None, help="Override report output path")
    args = parser.parse_args()

    state_dir = ensure_state_dir(Path(args.state_dir) if args.state_dir else None)
    signals_file = get_signals_file(state_dir)
    events_file = get_events_file(state_dir)

    if args.since_iso:
        try:
            start_utc = parse_utc_timestamp(args.since_iso)
        except Exception as e:
            raise SystemExit(f"Invalid --since-iso: {e}")
    else:
        start_utc = _default_window_start(start_hhmm=args.since_et)

    trades, _ = _load_trades(signals_file, start_utc)
    event_counts = _load_events(events_file, start_utc)

    challenge_state = None
    challenge_history = None
    try:
        challenge_state_path = state_dir / "challenge_state.json"
        if challenge_state_path.exists():
            challenge_state = json.loads(challenge_state_path.read_text(encoding="utf-8"))
    except Exception:
        challenge_state = None
    try:
        challenge_history_path = state_dir / "challenge_history.json"
        if challenge_history_path.exists():
            challenge_history = json.loads(challenge_history_path.read_text(encoding="utf-8"))
    except Exception:
        challenge_history = None

    report = _build_report(
        trades=trades,
        start_utc=start_utc,
        event_counts=event_counts,
        challenge_state=challenge_state,
        challenge_history=challenge_history,
    )

    exports_dir = state_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output_path) if args.output_path else (exports_dir / f"incident_report_{timestamp}.json")
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote incident report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
