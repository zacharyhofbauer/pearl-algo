#!/usr/bin/env python3
"""
Strategy Selection Report

Builds a drawdown-aware report from historical trade outcomes to help
choose a single, consistent strategy.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _parse_iso(dt: Optional[str]) -> Optional[datetime]:
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class TradeRecord:
    signal_type: str
    direction: str
    pnl: float
    is_win: bool
    exit_time: Optional[datetime]
    entry_time: Optional[datetime]
    session: str
    regime: str
    volatility: str

    @property
    def hold_minutes(self) -> Optional[float]:
        if not self.exit_time or not self.entry_time:
            return None
        delta = self.exit_time - self.entry_time
        return max(0.0, delta.total_seconds() / 60.0)


def _iter_exited_signals(signals_path: Path) -> Iterable[TradeRecord]:
    with open(signals_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") != "exited":
                continue
            signal = rec.get("signal", {}) or {}
            signal_type = (
                rec.get("signal_type")
                or signal.get("type")
                or signal.get("signal_type")
                or "unknown"
            )
            direction = signal.get("direction", rec.get("direction", "unknown")) or "unknown"
            pnl = float(rec.get("pnl", 0.0) or 0.0)
            is_win = bool(rec.get("is_win", False))
            exit_time = _parse_iso(rec.get("exit_time"))
            entry_time = _parse_iso(rec.get("entry_time"))
            regime = (signal.get("regime") or {}) if isinstance(signal.get("regime"), dict) else {}
            yield TradeRecord(
                signal_type=str(signal_type),
                direction=str(direction),
                pnl=pnl,
                is_win=is_win,
                exit_time=exit_time,
                entry_time=entry_time,
                session=str(regime.get("session") or "unknown"),
                regime=str(regime.get("regime") or "unknown"),
                volatility=str(regime.get("volatility") or "unknown"),
            )


@dataclass
class SummaryRow:
    key: str
    count: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    max_drawdown: float
    avg_hold_minutes: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _compute_drawdown(pnls: List[Tuple[Optional[datetime], float]]) -> float:
    ordered = sorted(
        pnls,
        key=lambda x: x[0] or datetime.now(timezone.utc),
    )
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for _, pnl in ordered:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return float(max_dd)


def _summarize(records: List[TradeRecord]) -> SummaryRow:
    count = len(records)
    wins = sum(1 for r in records if r.is_win)
    losses = count - wins
    total_pnl = sum(r.pnl for r in records)
    avg_pnl = total_pnl / count if count else 0.0
    pnls = [(r.exit_time, r.pnl) for r in records]
    max_dd = _compute_drawdown(pnls)
    holds = [r.hold_minutes for r in records if r.hold_minutes is not None]
    avg_hold = sum(holds) / len(holds) if holds else None
    win_rate = wins / count if count else 0.0
    return SummaryRow(
        key="",
        count=count,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_pnl=avg_pnl,
        max_drawdown=max_dd,
        avg_hold_minutes=avg_hold,
    )


def _rank_rows(rows: List[SummaryRow]) -> List[Dict[str, Any]]:
    ranked = []
    for row in rows:
        # Drawdown-first score: reward pnl but penalize drawdown.
        score = float(row.total_pnl) - 0.75 * float(row.max_drawdown)
        ranked.append({**row.to_dict(), "score": score})
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked


def _group_by(records: List[TradeRecord], key_fn) -> List[SummaryRow]:
    groups: Dict[str, List[TradeRecord]] = {}
    for r in records:
        key = key_fn(r)
        groups.setdefault(key, []).append(r)
    rows = []
    for key, items in groups.items():
        row = _summarize(items)
        row.key = key
        rows.append(row)
    return rows


def build_report(signals_path: Path) -> Dict[str, Any]:
    records = list(_iter_exited_signals(signals_path))
    summary = _summarize(records)

    by_type = _group_by(records, lambda r: r.signal_type)
    by_type_dir = _group_by(records, lambda r: f"{r.signal_type}:{r.direction}")
    by_session = _group_by(records, lambda r: r.session)
    by_regime = _group_by(records, lambda r: r.regime)
    by_vol = _group_by(records, lambda r: r.volatility)
    by_session_regime = _group_by(records, lambda r: f"{r.session}:{r.regime}")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals_path": str(signals_path),
        "overall": summary.to_dict(),
        "ranked_by_type": _rank_rows(by_type),
        "ranked_by_type_direction": _rank_rows(by_type_dir),
        "ranked_by_session": _rank_rows(by_session),
        "ranked_by_regime": _rank_rows(by_regime),
        "ranked_by_volatility": _rank_rows(by_vol),
        "ranked_by_session_regime": _rank_rows(by_session_regime),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a drawdown-aware strategy selection report")
    parser.add_argument(
        "--signals-path",
        type=Path,
        default=Path("data/agent_state/NQ/signals.jsonl"),
        help="Path to signals.jsonl with exited trades",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/agent_state/NQ/exports"),
        help="Output directory for report JSON",
    )
    parser.add_argument(
        "--out-name",
        type=str,
        default=None,
        help="Optional output filename (defaults to strategy_selection_<timestamp>.json)",
    )
    args = parser.parse_args()

    if not args.signals_path.exists():
        raise FileNotFoundError(f"signals.jsonl not found: {args.signals_path}")

    report = build_report(args.signals_path)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.out_name:
        out_path = args.out_dir / args.out_name
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = args.out_dir / f"strategy_selection_{ts}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote strategy selection report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
