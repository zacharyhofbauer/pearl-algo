"""
Strategy Selection Report

Builds a drawdown-aware report from historical trade outcomes to help
choose a single, consistent strategy.

This module provides the business logic for strategy analysis. The CLI
wrapper is located at scripts/backtesting/strategy_selection.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _parse_iso(dt: Optional[str]) -> Optional[datetime]:
    """Parse ISO format datetime string."""
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class TradeRecord:
    """Represents a single trade from signals.jsonl with exited status."""
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
        """Calculate hold duration in minutes."""
        if not self.exit_time or not self.entry_time:
            return None
        delta = self.exit_time - self.entry_time
        return max(0.0, delta.total_seconds() / 60.0)


@dataclass
class SummaryRow:
    """Summary statistics for a group of trades."""
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
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


def iter_exited_signals(signals_path: Path) -> Iterable[TradeRecord]:
    """
    Iterate over exited trades from a signals.jsonl file.

    Args:
        signals_path: Path to signals.jsonl file

    Yields:
        TradeRecord for each exited trade
    """
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


def compute_drawdown(pnls: List[Tuple[Optional[datetime], float]]) -> float:
    """
    Compute maximum drawdown from a series of P&L values.

    Args:
        pnls: List of (datetime, pnl) tuples

    Returns:
        Maximum drawdown value
    """
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


def summarize(records: List[TradeRecord]) -> SummaryRow:
    """
    Summarize a list of trade records into aggregate statistics.

    Args:
        records: List of TradeRecord objects

    Returns:
        SummaryRow with aggregate statistics
    """
    count = len(records)
    wins = sum(1 for r in records if r.is_win)
    losses = count - wins
    total_pnl = sum(r.pnl for r in records)
    avg_pnl = total_pnl / count if count else 0.0
    pnls = [(r.exit_time, r.pnl) for r in records]
    max_dd = compute_drawdown(pnls)
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


def rank_rows(rows: List[SummaryRow]) -> List[Dict[str, Any]]:
    """
    Rank summary rows by a drawdown-penalized score.

    Score = total_pnl - 0.75 * max_drawdown

    Args:
        rows: List of SummaryRow objects

    Returns:
        List of dicts with score field, sorted by score descending
    """
    ranked = []
    for row in rows:
        score = float(row.total_pnl) - 0.75 * float(row.max_drawdown)
        ranked.append({**row.to_dict(), "score": score})
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked


def _group_by(records: List[TradeRecord], key_fn) -> List[SummaryRow]:
    """Group records by a key function and summarize each group."""
    groups: Dict[str, List[TradeRecord]] = {}
    for r in records:
        key = key_fn(r)
        groups.setdefault(key, []).append(r)
    rows = []
    for key, items in groups.items():
        row = summarize(items)
        row.key = key
        rows.append(row)
    return rows


def build_report(signals_path: Path) -> Dict[str, Any]:
    """
    Build a comprehensive strategy selection report.

    Args:
        signals_path: Path to signals.jsonl file

    Returns:
        Dictionary with overall stats and ranked breakdowns by various dimensions
    """
    records = list(iter_exited_signals(signals_path))
    summary = summarize(records)

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
        "ranked_by_type": rank_rows(by_type),
        "ranked_by_type_direction": rank_rows(by_type_dir),
        "ranked_by_session": rank_rows(by_session),
        "ranked_by_regime": rank_rows(by_regime),
        "ranked_by_volatility": rank_rows(by_vol),
        "ranked_by_session_regime": rank_rows(by_session_regime),
    }
