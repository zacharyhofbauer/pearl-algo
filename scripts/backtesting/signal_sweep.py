#!/usr/bin/env python3
"""
Signal-Type Sweep Backtest (MNQ/NQ)

Purpose:
  Backtest *each signal family/type* in isolation (and a few combos) so you can
  clearly see what is working vs not working on a given historical window.

Typical usage:
  # Use existing cached parquet (example: 6 weeks)
  python scripts/backtesting/signal_sweep.py --data-path data/historical/MNQ_1m_6w.parquet --decision 5m

  # True ~6 month run (after you have data/historical/MNQ_1m_26w.parquet)
  python scripts/backtesting/signal_sweep.py --data-path data/historical/MNQ_1m_26w.parquet --decision 5m --lookback-weeks 26

Outputs:
  reports/signal_sweep_<timestamp>/
    - sweep.csv
    - sweep.json
    - winner.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pearlalgo.strategies.nq_intraday.backtest_adapter import (  # noqa: E402
    BacktestResult,
    run_full_backtest,
    run_full_backtest_5m_decision,
)
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig  # noqa: E402
from pearlalgo.utils.logger import log_silence  # noqa: E402


def load_ohlcv_data(path: Path) -> pd.DataFrame:
    """Load OHLCV data from parquet/CSV and normalize to tz-aware DateTimeIndex."""
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    if path.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("timestamp", "time", "datetime", "date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
                df = df.dropna(subset=[col]).set_index(col)
                break

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must have a DateTimeIndex or a 'timestamp' column")

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df = df.sort_index()

    # Ensure lowercase OHLCV columns exist
    mapping = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    for old, new in mapping.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return df


def slice_by_date_range(
    df: pd.DataFrame,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    lookback_weeks: Optional[int] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Slice data by start/end or lookback_weeks."""
    dataset_start = df.index[0]
    dataset_end = df.index[-1]

    start_dt = pd.to_datetime(start, utc=True) if start else None
    end_dt = pd.to_datetime(end, utc=True) if end else None
    if lookback_weeks and start_dt is None:
        anchor = end_dt or dataset_end
        start_dt = anchor - pd.Timedelta(weeks=int(lookback_weeks))

    sliced = df
    if start_dt is not None:
        sliced = sliced[sliced.index >= start_dt]
    if end_dt is not None:
        sliced = sliced[sliced.index <= end_dt]

    if sliced.empty:
        raise ValueError("No data after slicing")

    info = {
        "dataset_start": dataset_start.isoformat(),
        "dataset_end": dataset_end.isoformat(),
        "requested_start": start_dt.isoformat() if start_dt is not None else None,
        "requested_end": end_dt.isoformat() if end_dt is not None else None,
        "actual_start": sliced.index[0].isoformat(),
        "actual_end": sliced.index[-1].isoformat(),
        "bars_total": int(len(df)),
        "bars_sliced": int(len(sliced)),
    }
    return sliced, info


@dataclass
class SweepCase:
    name: str
    enabled_signals: List[str]
    disabled_signals: List[str]
    description: str = ""


@dataclass
class SweepRow:
    name: str
    enabled_signals: str
    disabled_signals: str
    total_trades: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    total_signals: int
    signals_per_day: float
    avg_confidence: float
    avg_rr: float
    score: float
    description: str = ""


def _score(res: BacktestResult) -> float:
    """Score used for ranking in the sweep output."""
    pnl = float(res.total_pnl or 0.0)
    pf = float(res.profit_factor or 0.0)
    dd = float(res.max_drawdown or 0.0)
    sharpe = float(res.sharpe_ratio or 0.0)
    # Reward pnl + PF + Sharpe, penalize drawdown.
    return (pnl * max(0.25, pf) * (1.0 + max(0.0, sharpe))) - (0.5 * dd)


def _case_matrix(include_combos: bool) -> List[SweepCase]:
    """
    Define the sweep cases.

    Important nuance:
    - Some scanners gate on base keys (e.g., "sr_bounce", "vwap_reversion"), so we must enable the base
      and then optionally disable the unwanted side (e.g., "sr_bounce_short").
    - Custom indicators gate on indicator.name *and* the emitted signal type; we enable both the indicator name
      and a prefix for its signal types ("pc_", "sd_", "smd_").
    """
    cases: List[SweepCase] = [
        # Core strategy signals (scanner-native)
        SweepCase("momentum_long", ["momentum_long"], [], "Scanner: momentum_long only"),
        SweepCase("momentum_short", ["momentum_short"], [], "Scanner: momentum_short only"),
        SweepCase("mean_reversion_long", ["mean_reversion_long"], [], "Scanner: mean_reversion_long only"),
        SweepCase("mean_reversion_short", ["mean_reversion_short"], [], "Scanner: mean_reversion_short only"),
        SweepCase("breakout_long", ["breakout_long"], [], "Scanner: breakout_long only"),
        SweepCase("breakout_short", ["breakout_short"], [], "Scanner: breakout_short only"),
        SweepCase("sr_bounce_long", ["sr_bounce"], ["sr_bounce_short"], "Scanner: sr_bounce_long only"),
        SweepCase("sr_bounce_short", ["sr_bounce"], ["sr_bounce_long"], "Scanner: sr_bounce_short only"),
        SweepCase("vwap_rev_long", ["vwap_reversion"], ["vwap_reversion_short"], "Scanner: vwap_reversion_long only"),
        SweepCase("vwap_rev_short", ["vwap_reversion"], ["vwap_reversion_long"], "Scanner: vwap_reversion_short only"),
        # Custom indicator signals
        SweepCase("tbt", ["tbt"], [], "Indicator: tbt_chartprime (tbt_breakout_long/short)"),
        SweepCase("power_channel", ["power_channel", "pc_"], [], "Indicator: power_channel (pc_*)"),
        SweepCase("supply_demand_zones", ["supply_demand_zones", "sd_"], [], "Indicator: supply_demand_zones (sd_*)"),
        SweepCase("smart_money_divergence", ["smart_money_divergence", "smd_"], [], "Indicator: smart_money_divergence (smd_*)"),
    ]

    if include_combos:
        cases.extend(
            [
                SweepCase("mrL+momS", ["mean_reversion_long", "momentum_short"], [], "Combo: mean_reversion_long + momentum_short"),
                SweepCase("breakouts_only", ["breakout_long", "breakout_short"], [], "Combo: breakout long+short"),
                SweepCase("mr_only", ["mean_reversion_long", "mean_reversion_short", "vwap_reversion"], [], "Combo: mean reversion family"),
                SweepCase("all_core_no_engulf", ["sr_bounce", "mean_reversion", "momentum", "breakout", "vwap_reversion"], ["engulfing"], "Combo: core families (no engulf)"),
            ]
        )

    return cases


def _run_case(
    df: pd.DataFrame,
    *,
    case: SweepCase,
    decision: str,
    symbol: str,
    tick_value: float,
    contracts: int,
    slippage_ticks: float,
    max_pos: int,
    disable_dynamic_sizing: bool,
) -> BacktestResult:
    cfg = NQIntradayConfig.from_config_file()
    cfg.symbol = symbol

    # Apply case-specific gating
    cfg.enabled_signals = list(case.enabled_signals)
    cfg.disabled_signals = list(case.disabled_signals)

    if disable_dynamic_sizing:
        cfg.enable_dynamic_sizing = False

    if decision == "5m":
        return run_full_backtest_5m_decision(
            df,
            config=cfg,
            position_size=contracts,
            tick_value=tick_value,
            slippage_ticks=slippage_ticks,
            max_concurrent_trades=max_pos,
            return_trades=False,
            max_contracts=max(1, contracts),
        )
    return run_full_backtest(
        df,
        config=cfg,
        position_size=contracts,
        tick_value=tick_value,
        slippage_ticks=slippage_ticks,
        max_concurrent_trades=max_pos,
        return_trades=False,
        max_contracts=max(1, contracts),
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest each signal type/family and rank best vs worst")
    p.add_argument("--data-path", type=Path, required=True, help="Path to OHLCV data (parquet/CSV)")
    p.add_argument("--decision", choices=["1m", "5m"], default="5m", help="Decision timeframe (default: 5m)")
    p.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    p.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    p.add_argument("--lookback-weeks", type=int, help="Alternative to --start: weeks of lookback from end")
    p.add_argument("--symbol", type=str, default="MNQ", choices=["MNQ", "NQ"], help="Symbol (default: MNQ)")
    p.add_argument("--contracts", type=int, default=5, help="Fixed contracts (used if dynamic sizing is disabled)")
    p.add_argument("--slippage-ticks", type=float, default=0.5, help="Slippage in ticks (default: 0.5)")
    p.add_argument("--max-pos", type=int, default=1, help="Max concurrent trades (default: 1)")
    p.add_argument("--include-combos", action="store_true", help="Include a small set of combo strategies")
    p.add_argument("--disable-dynamic-sizing", action="store_true", help="Disable dynamic sizing for fair per-signal comparison")
    p.add_argument("--output-dir", type=Path, default=None, help="Output directory (default: reports/signal_sweep_<ts>)")

    args = p.parse_args()

    df = load_ohlcv_data(args.data_path)
    df_sliced, meta = slice_by_date_range(df, start=args.start, end=args.end, lookback_weeks=args.lookback_weeks)

    tick_value = 20.0 if args.symbol.upper() == "NQ" else 2.0

    days = max(1e-9, (df_sliced.index[-1] - df_sliced.index[0]).total_seconds() / 86400.0)

    out_dir = args.output_dir
    if out_dir is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = PROJECT_ROOT / "reports" / f"signal_sweep_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = _case_matrix(include_combos=bool(args.include_combos))

    rows: List[SweepRow] = []
    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] Running case: {case.name} ({case.description})", flush=True)
        # Backtests can produce extremely verbose logs inside scanner loops.
        # Silence logs for speed and readability (the outputs are the CSV/JSON artifacts).
        with log_silence():
            res = _run_case(
                df_sliced,
                case=case,
                decision=args.decision,
                symbol=args.symbol,
                tick_value=tick_value,
                contracts=int(args.contracts),
                slippage_ticks=float(args.slippage_ticks),
                max_pos=int(args.max_pos),
                disable_dynamic_sizing=bool(args.disable_dynamic_sizing),
            )

        # Signals/day from verification (best) else from total_signals / days
        spd = None
        try:
            if res.verification is not None:
                spd = float(getattr(res.verification, "signals_per_day", 0.0) or 0.0)
        except Exception:
            spd = None
        if spd is None or spd <= 0:
            spd = float(res.total_signals or 0) / float(days)

        row = SweepRow(
            name=case.name,
            enabled_signals=",".join(case.enabled_signals),
            disabled_signals=",".join(case.disabled_signals),
            total_trades=int(res.total_trades or 0),
            win_rate=float(res.win_rate or 0.0),
            total_pnl=float(res.total_pnl or 0.0),
            profit_factor=float(res.profit_factor or 0.0),
            max_drawdown=float(res.max_drawdown or 0.0),
            sharpe_ratio=float(res.sharpe_ratio or 0.0),
            total_signals=int(res.total_signals or 0),
            signals_per_day=float(spd),
            avg_confidence=float(res.avg_confidence or 0.0),
            avg_rr=float(res.avg_risk_reward or 0.0),
            score=_score(res),
            description=case.description,
        )
        rows.append(row)

    # Rank (best score first)
    rows_sorted = sorted(rows, key=lambda r: r.score, reverse=True)

    # Write CSV/JSON
    df_out = pd.DataFrame([asdict(r) for r in rows_sorted])
    df_out.to_csv(out_dir / "sweep.csv", index=False)
    with open(out_dir / "sweep.json", "w") as f:
        json.dump(
            {
                "meta": meta,
                "decision": args.decision,
                "symbol": args.symbol,
                "tick_value": tick_value,
                "dynamic_sizing_disabled": bool(args.disable_dynamic_sizing),
                "cases": [asdict(r) for r in rows_sorted],
            },
            f,
            indent=2,
        )

    winner = rows_sorted[0] if rows_sorted else None
    if winner:
        with open(out_dir / "winner.txt", "w") as f:
            f.write(
                f"Winner: {winner.name}\n"
                f"Enabled: {winner.enabled_signals}\n"
                f"Disabled: {winner.disabled_signals}\n"
                f"PnL: {winner.total_pnl:.2f}\n"
                f"PF: {winner.profit_factor:.2f}\n"
                f"WR: {winner.win_rate*100:.1f}%\n"
                f"MaxDD: {winner.max_drawdown:.2f}\n"
                f"Sharpe: {winner.sharpe_ratio:.2f}\n"
            )

    print(f"\nSignal sweep complete: {out_dir}")
    if winner:
        print(f"Winner: {winner.name} | PnL {winner.total_pnl:.2f} | PF {winner.profit_factor:.2f} | WR {winner.win_rate*100:.1f}% | DD {winner.max_drawdown:.2f}")


if __name__ == "__main__":
    main()

