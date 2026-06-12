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

    def record(self, trade: SimTrade, tf_minutes: int, commission_points: float = 0.0) -> float:
        """Record a closed trade. ``commission_points`` is the round-trip cost
        (in index points) subtracted from this trade's P&L so totals/expectancy
        are net-of-cost. Returns the trade's NET points (for bootstrap CIs)."""
        if not trade.is_closed:
            return 0.0
        self.entries += 1
        pnl = trade.pnl_points() - commission_points
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
        return pnl

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
    *,
    slippage_points: float = 0.25,
) -> None:
    """Close ``trade`` using a first-touch SL/TP model, or time out.

    Issue #53 fidelity upgrade: applies ``slippage_points`` to every
    SL / TP fill so the replay scorecard reflects real broker behavior
    rather than the optimistic at-the-exact-trigger fill. MNQ tick is
    0.25, so the default of 0.25 pt is one adverse tick — conservative
    but not catastrophic.

    Slippage direction:
      - SL hit: exit_price moves AWAY from entry (worse for trader).
      - TP hit: exit_price moves AWAY from entry (worse — you don't get
        quite the target you asked for).
      - Timeout: apply no slippage (market close, no adverse move).
    """
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
                trade.exit_price = trade.stop_loss - slippage_points
                trade.exit_reason = "sl"
                trade.exit_time = bar_ts
                return
            if hi >= trade.take_profit:
                trade.exit_price = trade.take_profit - slippage_points
                trade.exit_reason = "tp"
                trade.exit_time = bar_ts
                return
        else:  # short
            if hi >= trade.stop_loss:
                trade.exit_price = trade.stop_loss + slippage_points
                trade.exit_reason = "sl"
                trade.exit_time = bar_ts
                return
            if lo <= trade.take_profit:
                trade.exit_price = trade.take_profit + slippage_points
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


def _extract_trigger(sig: Dict[str, Any]) -> str:
    """Issue #53: robust trigger-attribution for the replay scorecard.

    ``generate_signals`` emits ``entry_trigger`` for directional signals
    and also sets ``signal_type`` / ``type`` / ``signal_source`` on every
    signal. Prefer the most-specific label available; fall back through
    the chain before giving up on "unknown" so per-trigger breakdowns
    are actually actionable.
    """
    for key in ("entry_trigger", "signal_type", "type", "signal_source"):
        value = sig.get(key)
        if value and str(value).strip() and str(value).strip() != "unknown":
            return str(value).strip()
    return "unknown"


# Registered held-out slice (docs/audits/validation-trial-ledger.md): data from
# this ET date onward is reserved for the one-shot Tier-5 read. The harness
# refuses to load it unless the caller explicitly opts in (--tier5-held-out).
HELD_OUT_START_DATE = "2026-04-20"


def _held_out_start_ts() -> int:
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI

    return int(
        _dt.strptime(HELD_OUT_START_DATE, "%Y-%m-%d")
        .replace(tzinfo=_ZI("America/New_York"))
        .timestamp()
    )


def clamp_to_held_out(win_from: int, win_to: int, *, allow_held_out: bool):
    """Apply the held-out guard to a resolved [win_from, win_to] window.

    Returns ``(win_from, win_to, clamped)``. Trailing windows that would
    silently overlap the held-out slice (the trial 7-10 contamination
    mechanism) are clamped to the boundary; explicit ``--end`` violations are
    rejected earlier, in ``main()``, so the user sees an error rather than a
    silent clamp.
    """
    if allow_held_out:
        return win_from, win_to, False
    boundary = _held_out_start_ts()
    if win_to <= boundary:
        return win_from, win_to, False
    return min(win_from, boundary), boundary, True


def run_backtest(
    config_path: Path,
    *,
    symbol: str = "MNQ",
    tf: str = "5m",
    days: int = 30,
    warmup_bars: int = 120,
    max_hold_minutes: int = 180,
    max_concurrent: int = 1,
    slippage_points: float = 0.25,
    commission_points: float = 1.0,
    ts_from: Optional[int] = None,
    ts_to: Optional[int] = None,
    strategy_fn: Optional[Any] = None,
    strategy_name: str = "composite",
    allow_held_out: bool = False,
) -> Dict[str, Any]:
    """Replay the archive through ``config_path`` and return the scorecard dict.

    ``strategy_fn`` overrides the signal source (default: the live
    ``generate_signals``). Isolated validation strategies live in
    ``pearlalgo.validation.strategies`` and share the same call contract.

    ``commission_points`` is the round-trip cost per contract in index points
    (MNQ: ~$2 RT / $2 per point ≈ 1.0 pt). Set 0.0 to see gross-of-commission.

    ``allow_held_out`` lifts the registered held-out guard (Tier-5 one-shot
    read only); by default the window is clamped to ``HELD_OUT_START_DATE``.
    """
    import pandas as pd
    from pearlalgo.config.config_loader import (
        build_strategy_config_from_yaml,
        load_service_config,
    )
    from pearlalgo.persistence.candle_archive import get_archive
    from pearlalgo.trading_bots.signal_generator import (
        CONFIG as _DEFAULT_STRATEGY_CONFIG,
        generate_signals,
    )

    sig_fn = strategy_fn or generate_signals
    tf_min = _tf_minutes(tf)
    now_ts = int(time.time())
    # Explicit [ts_from, ts_to] wins; otherwise fall back to the trailing --days
    # window. Explicit ranges let us run dev-only and hold out the recent slice.
    win_to = now_ts if ts_to is None else int(ts_to)
    win_from = (win_to - days * 86400) if ts_from is None else int(ts_from)
    win_from, win_to, clamped = clamp_to_held_out(
        win_from, win_to, allow_held_out=allow_held_out
    )
    if clamped:
        if ts_from is None:
            win_from = win_to - days * 86400  # keep the full trailing span, pre-boundary
        print(
            f"[held-out guard] window end clamped to {HELD_OUT_START_DATE} (ET) — the "
            f"registered held-out slice is untouched by default "
            f"(docs/audits/validation-trial-ledger.md). Pass --tier5-held-out for the "
            f"one-shot Tier-5 read.",
            file=sys.stderr,
        )
    archive = get_archive()
    rows = archive.query_range(
        symbol=symbol, tf=tf, ts_from=win_from, ts_to=win_to,
        limit=(win_to - win_from) // (tf_min * 60) + 500,
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

    # Issue #53: flatten active-strategy params to root so generate_signals
    # gets the call shape it expects (matches what the live service does
    # via config_loader.build_strategy_config). Previously a raw
    # load_service_config caused KeyError('min_risk_reward') because the
    # value lives under ``signals.min_risk_reward`` not the root.
    raw = load_service_config(config_path=str(config_path), validate=False)
    merged = build_strategy_config_from_yaml(dict(_DEFAULT_STRATEGY_CONFIG), raw)
    merged.setdefault("symbol", symbol)
    merged.setdefault("timeframe", tf)

    scorecard = Scorecard()
    open_trades: List[SimTrade] = []  # resolved trades still occupying a concurrency slot
    closed_trades: List[SimTrade] = []
    per_trade_net_points: List[float] = []
    total_signals = 0
    # Bound the forward scan so we don't copy the whole tail per admission;
    # simulate_exit returns at the deadline anyway, but a bounded window keeps
    # this O(trades * max_hold) instead of O(trades * n).
    max_fwd_bars = (max_hold_minutes // tf_min) + 2

    from datetime import datetime, timezone

    # Build the frame once and slice it per bar (cheaper than reconstructing a
    # DataFrame from list-of-dicts every iteration; same data, same RangeIndex).
    full_df = pd.DataFrame(rows)

    for i in range(warmup_bars, len(rows)):
        df_slice = full_df.iloc[: i + 1].copy()
        bar = rows[i]
        bar_ts = int(bar["time"])
        bar_time = datetime.fromtimestamp(bar_ts, tz=timezone.utc)
        try:
            signals = sig_fn(df_slice, config=merged, current_time=bar_time)
        except Exception as exc:  # pragma: no cover — surfaced in the scorecard
            return {
                "error": f"generate_signals raised: {type(exc).__name__}: {exc}",
                "candles_processed": i,
            }
        total_signals += len(signals or [])

        # Free concurrency slots held by trades whose exit has already passed.
        open_trades = [t for t in open_trades if (t.exit_time or 0) > bar_ts]

        # Admit new signals up to the concurrency cap. Each admitted trade is
        # resolved IMMEDIATELY against the forward window (first-touch SL/TP, or
        # max-hold timeout) so it is held across bars rather than force-closed at
        # the next bar — the prior single-bar call was the exit-sim bug.
        for sig in signals or []:
            if len(open_trades) >= max_concurrent:
                break
            stop = sig.get("stop_loss")
            take = sig.get("take_profit")
            if stop is None or take is None:
                continue
            entry_price = float(sig.get("entry_price") or bar["close"])
            # Entry slippage: long fills ~1 tick above the last print, short ~1
            # tick below (mirror the live-broker bias).
            direction = str(sig.get("direction") or "long")
            if direction == "long":
                entry_price += slippage_points
            else:
                entry_price -= slippage_points
            trade = SimTrade(
                signal_id=str(sig.get("signal_id") or f"sim-{i}-{len(closed_trades)}"),
                trigger=_extract_trigger(sig),
                direction=direction,
                entry_time=bar_ts,
                entry_price=entry_price,
                stop_loss=float(stop),
                take_profit=float(take),
                confidence=float(sig.get("confidence") or 0.0),
            )
            simulate_exit(
                trade, rows[i + 1: i + 1 + max_fwd_bars],
                max_hold_minutes=max_hold_minutes,
                slippage_points=slippage_points,
            )
            if not trade.is_closed:
                continue  # no forward bars left (end of data) — skip unresolved
            net = scorecard.record(trade, tf_min, commission_points=commission_points)
            per_trade_net_points.append(round(net, 4))
            closed_trades.append(trade)
            open_trades.append(trade)  # occupies a slot until exit_time passes

    scorecard_dict = scorecard.to_dict()
    scorecard_dict["net_points_per_trade"] = per_trade_net_points
    scorecard_dict["meta"] = {
        "config_path": str(config_path),
        "strategy": strategy_name,
        "symbol": symbol,
        "timeframe": tf,
        "days_requested": days,
        "window_from": win_from,
        "window_to": win_to,
        "warmup_bars": warmup_bars,
        "max_hold_minutes": max_hold_minutes,
        "max_concurrent": max_concurrent,
        "slippage_points": slippage_points,
        "commission_points": commission_points,
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
    slippage = m.get("slippage_points")
    if slippage is not None:
        flag = "(NO-SLIPPAGE — results flattered)" if slippage == 0 else ""
        lines.append(f"Slippage applied: {slippage} pts / side {flag}")
    commission = m.get("commission_points")
    if commission is not None:
        cflag = "(NO-COMMISSION — results flattered)" if commission == 0 else ""
        lines.append(f"Commission applied: {commission} pts / round-trip {cflag}  (expectancy below is NET)")
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
    parser.add_argument("--start", default=None, help="Window start date YYYY-MM-DD (ET); overrides --days")
    parser.add_argument("--end", default=None, help="Window end date YYYY-MM-DD (ET, inclusive); overrides --days")
    parser.add_argument("--warmup-bars", type=int, default=120)
    parser.add_argument("--max-hold-minutes", type=int, default=180)
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument(
        "--slippage-points",
        type=float,
        default=0.25,
        help=(
            "Adverse fill slippage applied to SL / TP / entry (default 0.25 "
            "= one MNQ tick). Set to 0.0 to reproduce the pre-#53 "
            "no-slippage behavior (not recommended — flatters scorecards)."
        ),
    )
    parser.add_argument(
        "--commission-points",
        type=float,
        default=1.0,
        help=(
            "Round-trip commission per contract in index points (default 1.0 "
            "= ~$2 RT on MNQ at $2/pt). Set 0.0 for gross-of-commission."
        ),
    )
    parser.add_argument(
        "--strategy",
        default="composite",
        choices=[
            "composite", "pine", "orb", "vwap_reversion",
            "opening_drive", "opening_drive_5", "tod_rth_long", "overnight_seasonality",
        ],
        help=(
            "Signal source: 'composite' = live generate_signals (the RICH strategy); "
            "pine/orb/vwap_reversion = isolated validation strategies; "
            "opening_drive[_5]/tod_rth_long/overnight_seasonality = Path-B time-based hypotheses."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON scorecard on stdout")
    parser.add_argument(
        "--tier5-held-out",
        action="store_true",
        help=(
            f"Allow loading the registered held-out slice ({HELD_OUT_START_DATE} onward). "
            "Reserved for the one-shot Tier-5 read — see docs/audits/validation-trial-ledger.md."
        ),
    )
    args = parser.parse_args(argv)

    # Held-out guard, explicit-date branch: a typed --end inside the held-out
    # slice is an error (the user asked for something registration forbids),
    # not a silent clamp. ISO dates compare lexicographically.
    if args.end and args.end >= HELD_OUT_START_DATE and not args.tier5_held_out:
        print(
            f"ERROR: --end {args.end} reaches into the registered held-out slice "
            f"({HELD_OUT_START_DATE} onward, reserved for the one-shot Tier-5 read — "
            f"docs/audits/validation-trial-ledger.md). Last legal --end is the day "
            f"before; pass --tier5-held-out only for the sanctioned Tier-5 run.",
            file=sys.stderr,
        )
        return 1
    if args.tier5_held_out:
        print(
            "=== TIER-5 HELD-OUT RUN — this is the one-shot read of the registered "
            "held-out slice. ===",
            file=sys.stderr,
        )

    sfn = None
    if args.strategy != "composite":
        from pearlalgo.validation.strategies import STRATEGY_FNS
        sfn = STRATEGY_FNS[args.strategy]

    ts_from = ts_to = None
    if args.start or args.end:
        from datetime import datetime as _dt, timedelta as _td
        from zoneinfo import ZoneInfo as _ZI
        _ET = _ZI("America/New_York")
        if args.start:
            ts_from = int(_dt.strptime(args.start, "%Y-%m-%d").replace(tzinfo=_ET).timestamp())
        if args.end:  # inclusive: end-of-day
            ts_to = int((_dt.strptime(args.end, "%Y-%m-%d").replace(tzinfo=_ET) + _td(days=1)).timestamp())

    result = run_backtest(
        config_path=Path(args.config),
        symbol=args.symbol,
        tf=args.tf,
        days=args.days,
        ts_from=ts_from,
        ts_to=ts_to,
        warmup_bars=args.warmup_bars,
        max_hold_minutes=args.max_hold_minutes,
        max_concurrent=args.max_concurrent,
        slippage_points=args.slippage_points,
        commission_points=args.commission_points,
        strategy_fn=sfn,
        strategy_name=args.strategy,
        allow_held_out=args.tier5_held_out,
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(_format_scorecard_text(result))

    return 0 if "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())
