#!/usr/bin/env python3
"""Backtest-config replay gate (Issue 24-A).

Replays the candle archive through a proposed runtime YAML and prints a
scorecard so strategy tuning moves from ``tune → deploy → wait → check
broker`` to ``tune → replay → read → iterate``.

Usage::

    python scripts/ops/backtest_config.py
    python scripts/ops/backtest_config.py --config config/live/tradovate_paper.yaml
    python scripts/ops/backtest_config.py --days 30 --tf 5m --warmup-bars 120
    python scripts/ops/backtest_config.py --json > audits/2026-04-23-replay.json

Scope:
  * Uses ``pearlalgo.persistence.candle_archive.get_archive()`` for data.
  * Drives the existing ``pearlalgo.trading_bots.signal_generator.
    generate_signals`` with the merged config from ``config_loader``.
  * Simulates exits with a simple first-touch model: each bar after the
    signal is checked for SL/TP hit using high/low; if neither, exits at
    ``max_hold_minutes`` (default 180) on the close.
  * Prints a per-trigger scorecard + the overall totals.

Non-goals:
  * Not a perfect replication of live order flow (no slippage model, no
    bracket modify, no broker-side stop walk). Intended as a FAST
    scorecard for YAML tuning, not P&L attribution.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


@dataclass
class SimTrade:
    signal_id: str
    trigger: str
    direction: str
    entry_time: int
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    exit_time: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "tp", "sl", "timeout"

    @property
    def is_closed(self) -> bool:
        return self.exit_reason is not None

    def pnl_points(self) -> float:
        if self.exit_price is None:
            return 0.0
        if self.direction == "long":
            return self.exit_price - self.entry_price
        return self.entry_price - self.exit_price


@dataclass
class Scorecard:
    entries: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    total_points: float = 0.0
    gross_win_points: float = 0.0
    gross_loss_points: float = 0.0
    max_win_points: float = 0.0
    max_loss_points: float = 0.0
    peak_equity: float = 0.0
    max_drawdown_points: float = 0.0
    by_trigger: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    hold_minutes_distribution: Dict[str, int] = field(default_factory=dict)

    def record(self, trade: SimTrade, tf_minutes: int) -> None:
        if not trade.is_closed:
            return
        self.entries += 1
        pnl = trade.pnl_points()
        self.total_points += pnl

        if trade.exit_reason == "tp":
            self.wins += 1
            self.gross_win_points += pnl
            self.max_win_points = max(self.max_win_points, pnl)
        elif trade.exit_reason == "sl":
            self.losses += 1
            self.gross_loss_points += pnl
            self.max_loss_points = min(self.max_loss_points, pnl)
        else:
            self.timeouts += 1
            if pnl >= 0:
                self.wins += 1
                self.gross_win_points += pnl
                self.max_win_points = max(self.max_win_points, pnl)
            else:
                self.losses += 1
                self.gross_loss_points += pnl
                self.max_loss_points = min(self.max_loss_points, pnl)

        self.peak_equity = max(self.peak_equity, self.total_points)
        drawdown = self.peak_equity - self.total_points
        self.max_drawdown_points = max(self.max_drawdown_points, drawdown)

        by = self.by_trigger.setdefault(
            trade.trigger,
            {"entries": 0, "wins": 0, "losses": 0, "total_points": 0.0},
        )
        by["entries"] += 1
        by["total_points"] += pnl
        if pnl > 0:
            by["wins"] += 1
        elif pnl < 0:
            by["losses"] += 1

        if trade.exit_time is not None and trade.entry_time is not None:
            duration_min = max(1, (trade.exit_time - trade.entry_time) // 60)
            bucket_key = _bucket(duration_min, tf_minutes)
            self.hold_minutes_distribution[bucket_key] = (
                self.hold_minutes_distribution.get(bucket_key, 0) + 1
            )

    def to_dict(self) -> Dict[str, Any]:
        win_rate = self.wins / self.entries if self.entries else 0.0
        avg_win = (
            self.gross_win_points / self.wins if self.wins else 0.0
        )
        avg_loss = (
            self.gross_loss_points / self.losses if self.losses else 0.0
        )
        expectancy = (
            (self.total_points / self.entries) if self.entries else 0.0
        )
        return {
            "entries": self.entries,
            "wins": self.wins,
            "losses": self.losses,
            "timeouts": self.timeouts,
            "win_rate": round(win_rate, 4),
            "total_points": round(self.total_points, 2),
            "avg_win_points": round(avg_win, 2),
            "avg_loss_points": round(avg_loss, 2),
            "max_win_points": round(self.max_win_points, 2),
            "max_loss_points": round(self.max_loss_points, 2),
            "max_drawdown_points": round(self.max_drawdown_points, 2),
            "expectancy_points_per_trade": round(expectancy, 2),
            "by_trigger": {
                k: {
                    **v,
                    "win_rate": round(
                        v["wins"] / v["entries"] if v["entries"] else 0.0, 4
                    ),
                    "avg_points": round(
                        v["total_points"] / v["entries"] if v["entries"] else 0.0,
                        2,
                    ),
                }
                for k, v in sorted(self.by_trigger.items())
            },
            "hold_duration_buckets": dict(sorted(self.hold_minutes_distribution.items())),
        }


def _bucket(minutes: int, tf_minutes: int) -> str:
    # Coarse hold-time buckets so the distribution is scannable.
    edges = [5, 15, 30, 60, 120, 240]
    labels = ["<=5m", "5-15m", "15-30m", "30-60m", "60-120m", "120-240m", ">240m"]
    for i, edge in enumerate(edges):
        if minutes <= edge:
            return labels[i]
    return labels[-1]


def simulate_exit(
    trade: SimTrade,
    future_candles: List[Dict[str, Any]],
    max_hold_minutes: int,
) -> None:
    """Close ``trade`` using a first-touch SL/TP model, or time out."""
    entry_ts = trade.entry_time
    deadline = entry_ts + max_hold_minutes * 60

    for bar in future_candles:
        bar_ts = int(bar["time"])
        if bar_ts <= entry_ts:
            continue
        hi = float(bar["high"])
        lo = float(bar["low"])
        if trade.direction == "long":
            if lo <= trade.stop_loss:
                trade.exit_price = trade.stop_loss
                trade.exit_reason = "sl"
                trade.exit_time = bar_ts
                return
            if hi >= trade.take_profit:
                trade.exit_price = trade.take_profit
                trade.exit_reason = "tp"
                trade.exit_time = bar_ts
                return
        else:  # short
            if hi >= trade.stop_loss:
                trade.exit_price = trade.stop_loss
                trade.exit_reason = "sl"
                trade.exit_time = bar_ts
                return
            if lo <= trade.take_profit:
                trade.exit_price = trade.take_profit
                trade.exit_reason = "tp"
                trade.exit_time = bar_ts
                return
        if bar_ts >= deadline:
            trade.exit_price = float(bar["close"])
            trade.exit_reason = "timeout"
            trade.exit_time = bar_ts
            return

    # Fell off the end of the window without hitting either.
    if future_candles:
        last = future_candles[-1]
        trade.exit_price = float(last["close"])
        trade.exit_reason = "timeout"
        trade.exit_time = int(last["time"])


def _tf_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 60 * 24
    raise ValueError(f"unsupported timeframe: {tf!r}")


def run_backtest(
    config_path: Path,
    *,
    symbol: str = "MNQ",
    tf: str = "5m",
    days: int = 30,
    warmup_bars: int = 120,
    max_hold_minutes: int = 180,
    max_concurrent: int = 1,
) -> Dict[str, Any]:
    """Replay the archive through ``config_path`` and return the scorecard dict."""
    import pandas as pd
    from pearlalgo.config.config_loader import load_service_config
    from pearlalgo.persistence.candle_archive import get_archive
    from pearlalgo.trading_bots.signal_generator import generate_signals

    tf_min = _tf_minutes(tf)
    now_ts = int(time.time())
    ts_from = now_ts - days * 86400
    archive = get_archive()
    rows = archive.query_range(
        symbol=symbol, tf=tf, ts_from=ts_from, ts_to=now_ts, limit=days * 24 * 60 // tf_min + 500
    )
    if len(rows) <= warmup_bars:
        return {
            "error": (
                f"not enough candles in archive: have {len(rows)} <= warmup {warmup_bars}. "
                f"Run the backfill (scripts/ops/backfill_ibkr_historical.py) first."
            ),
            "candles_available": len(rows),
            "warmup_bars": warmup_bars,
        }

    merged = load_service_config(config_path=str(config_path), validate=False)
    merged = dict(merged)
    merged.setdefault("symbol", symbol)
    merged.setdefault("timeframe", tf)

    scorecard = Scorecard()
    open_trades: List[SimTrade] = []
    closed_trades: List[SimTrade] = []
    total_signals = 0

    from datetime import datetime, timezone

    for i in range(warmup_bars, len(rows)):
        df_slice = pd.DataFrame(rows[: i + 1])
        bar = rows[i]
        bar_time = datetime.fromtimestamp(int(bar["time"]), tz=timezone.utc)
        try:
            signals = generate_signals(df_slice, config=merged, current_time=bar_time)
        except Exception as exc:  # pragma: no cover — surfaced in the scorecard
            return {
                "error": f"generate_signals raised: {type(exc).__name__}: {exc}",
                "candles_processed": i,
            }
        total_signals += len(signals or [])

        # Close any open trades that resolved between the previous bar and this one.
        still_open = []
        for trade in open_trades:
            simulate_exit(trade, [bar], max_hold_minutes=max_hold_minutes)
            if trade.is_closed:
                scorecard.record(trade, tf_min)
                closed_trades.append(trade)
            else:
                still_open.append(trade)
        open_trades = still_open

        # Admit new signals up to the concurrency cap.
        for sig in signals or []:
            if len(open_trades) >= max_concurrent:
                break
            entry_price = float(sig.get("entry_price") or bar["close"])
            stop = sig.get("stop_loss")
            take = sig.get("take_profit")
            if stop is None or take is None:
                continue
            trade = SimTrade(
                signal_id=str(sig.get("signal_id") or f"sim-{i}-{len(closed_trades)}"),
                trigger=str(sig.get("entry_trigger") or sig.get("signal_type") or "unknown"),
                direction=str(sig.get("direction") or "long"),
                entry_time=int(bar["time"]),
                entry_price=entry_price,
                stop_loss=float(stop),
                take_profit=float(take),
                confidence=float(sig.get("confidence") or 0.0),
            )
            open_trades.append(trade)

    # Close any positions still open at the end of the window on the last close.
    if rows:
        tail = [rows[-1]]
        for trade in open_trades:
            simulate_exit(trade, tail, max_hold_minutes=max_hold_minutes)
            if trade.is_closed:
                scorecard.record(trade, tf_min)
                closed_trades.append(trade)

    scorecard_dict = scorecard.to_dict()
    scorecard_dict["meta"] = {
        "config_path": str(config_path),
        "symbol": symbol,
        "timeframe": tf,
        "days_requested": days,
        "warmup_bars": warmup_bars,
        "max_hold_minutes": max_hold_minutes,
        "max_concurrent": max_concurrent,
        "candles_processed": len(rows),
        "signals_generated": total_signals,
        "trades_opened": len(closed_trades),
    }
    return scorecard_dict


def _format_scorecard_text(sc: Dict[str, Any]) -> str:
    if "error" in sc:
        return f"ERROR: {sc['error']}"
    m = sc.get("meta", {})
    lines = []
    lines.append("─── Pearl-Algo Config Backtest ───")
    lines.append(
        f"Config: {m.get('config_path')} | Symbol: {m.get('symbol')} | TF: {m.get('timeframe')} | "
        f"Days: {m.get('days_requested')} | Candles: {m.get('candles_processed')}"
    )
    lines.append(
        f"Signals generated: {m.get('signals_generated')} | Trades opened: {m.get('trades_opened')}"
    )
    lines.append("")
    lines.append(f"Entries:         {sc['entries']}")
    lines.append(f"Wins / Losses:   {sc['wins']} / {sc['losses']}  (timeouts: {sc['timeouts']})")
    lines.append(f"Win rate:        {sc['win_rate']*100:.1f}%")
    lines.append(f"Total points:    {sc['total_points']:+.2f}")
    lines.append(f"Expectancy/t:    {sc['expectancy_points_per_trade']:+.2f} pts")
    lines.append(f"Avg win / loss:  {sc['avg_win_points']:+.2f} / {sc['avg_loss_points']:+.2f}")
    lines.append(f"Max win / loss:  {sc['max_win_points']:+.2f} / {sc['max_loss_points']:+.2f}")
    lines.append(f"Max drawdown:    {sc['max_drawdown_points']:.2f} pts")
    lines.append("")
    if sc["by_trigger"]:
        lines.append("Per-trigger:")
        for trigger, stats in sc["by_trigger"].items():
            lines.append(
                f"  {trigger:<22} entries={stats['entries']:>3}  win%={stats['win_rate']*100:5.1f}  "
                f"pts={stats['total_points']:+7.2f}  avg={stats['avg_points']:+5.2f}"
            )
    if sc["hold_duration_buckets"]:
        lines.append("")
        lines.append("Hold duration distribution:")
        for bucket, n in sc["hold_duration_buckets"].items():
            lines.append(f"  {bucket:<10} {n:>4}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Pearl-Algo config backtest (Issue 24-A).")
    parser.add_argument(
        "--config",
        default=str(_REPO_ROOT / "config" / "live" / "tradovate_paper.yaml"),
        help="Path to the runtime YAML to replay",
    )
    parser.add_argument("--symbol", default="MNQ")
    parser.add_argument("--tf", default="5m", help="Timeframe: 1m, 5m, 15m, 1h, 4h, 1d")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--warmup-bars", type=int, default=120)
    parser.add_argument("--max-hold-minutes", type=int, default=180)
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument("--json", action="store_true", help="Emit JSON scorecard on stdout")
    args = parser.parse_args(argv)

    result = run_backtest(
        config_path=Path(args.config),
        symbol=args.symbol,
        tf=args.tf,
        days=args.days,
        warmup_bars=args.warmup_bars,
        max_hold_minutes=args.max_hold_minutes,
        max_concurrent=args.max_concurrent,
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(_format_scorecard_text(result))

    return 0 if "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())
