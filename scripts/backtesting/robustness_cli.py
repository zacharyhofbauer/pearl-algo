#!/usr/bin/env python3
"""
Backtest Robustness CLI

Adds practical tools for:
- Parameter sweeps
- Walk-forward evaluation
- Monte Carlo / bootstrap robustness on trade P&L

Examples:
  # Sweep a single parameter
  python scripts/backtesting/robustness_cli.py sweep --data-path data/mnq_1m.parquet \\
    --decision 5m --config-path signals.min_confidence --values 0.45 0.5 0.55 --lookback-weeks 4

  # Walk-forward: choose best value on each train window, evaluate on next test window
  python scripts/backtesting/robustness_cli.py walkforward --data-path data/mnq_1m.parquet \\
    --decision 5m --config-path signals.min_confidence --values 0.45 0.5 0.55 \\
    --train-weeks 8 --test-weeks 2

  # Bootstrap: estimate distribution from an existing report folder
  python scripts/backtesting/robustness_cli.py bootstrap --report-dir reports/backtest_MNQ_5m_20251215_20251229_20251231_171839
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pearlalgo.backtesting.config_overrides import (  # noqa: E402
    apply_nq_intraday_config_override,
    make_service_config_override,
)
from pearlalgo.config.config_loader import service_config_override  # noqa: E402
from pearlalgo.strategies.nq_intraday.backtest_adapter import (  # noqa: E402
    run_full_backtest,
    run_full_backtest_5m_decision,
)
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig  # noqa: E402


def load_ohlcv_data(path: Path) -> pd.DataFrame:
    """Load OHLCV data from parquet or CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    if path.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    # Normalize index to DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("timestamp", "time", "datetime", "date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
                df = df.dropna(subset=[col]).set_index(col)
                break

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must have a DateTimeIndex or a timestamp column")

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")

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
    """Slice dataframe with basic integrity metadata."""
    dataset_start = df.index[0]
    dataset_end = df.index[-1]

    start_dt = pd.to_datetime(start, utc=True) if start else None
    end_dt = pd.to_datetime(end, utc=True) if end else None
    if lookback_weeks and start_dt is None:
        anchor = end_dt or dataset_end
        start_dt = anchor - pd.Timedelta(weeks=lookback_weeks)

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


def _score_result(total_pnl: float, max_drawdown: float) -> float:
    """Simple score: reward PnL, penalize drawdown."""
    return float(total_pnl) - 0.5 * float(max_drawdown)


@dataclass
class SweepRow:
    value: Any
    score: float
    total_trades: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    total_signals: int


def _run_backtest_with_override(
    df_1m: pd.DataFrame,
    *,
    decision: str,
    symbol: str,
    tick_value: float,
    contracts: int,
    slippage_ticks: float,
    max_pos: int,
    config_path: str,
    value: Any,
) -> Tuple[SweepRow, Dict[str, Any]]:
    base_cfg = NQIntradayConfig.from_config_file()
    base_cfg.symbol = symbol

    cfg = copy.deepcopy(base_cfg)
    cfg = apply_nq_intraday_config_override(cfg, config_path, value)

    svc_override = make_service_config_override(config_path, value)

    def _run() -> Any:
        if decision == "5m":
            return run_full_backtest_5m_decision(
                df_1m,
                config=cfg,
                position_size=contracts,
                tick_value=tick_value,
                slippage_ticks=slippage_ticks,
                max_concurrent_trades=max_pos,
                return_trades=False,
                decision_rule="5min",
                context_rule_1="1h",
                context_rule_2="4h",
            )
        return run_full_backtest(
            df_1m,
            config=cfg,
            position_size=contracts,
            tick_value=tick_value,
            slippage_ticks=slippage_ticks,
            max_concurrent_trades=max_pos,
            return_trades=False,
        )

    if svc_override:
        with service_config_override(svc_override):
            res = _run()
    else:
        res = _run()

    total_pnl = float(res.total_pnl or 0.0)
    max_dd = float(res.max_drawdown or 0.0)
    score = _score_result(total_pnl, max_dd)

    row = SweepRow(
        value=value,
        score=score,
        total_trades=int(res.total_trades or 0),
        win_rate=float(res.win_rate or 0.0),
        total_pnl=total_pnl,
        profit_factor=float(res.profit_factor or 0.0),
        max_drawdown=max_dd,
        sharpe_ratio=float(res.sharpe_ratio or 0.0),
        total_signals=int(res.total_signals or 0),
    )

    meta = {"service_override": svc_override, "strategy_override": {config_path: value}}
    return row, meta


def cmd_sweep(args: argparse.Namespace) -> int:
    df = load_ohlcv_data(Path(args.data_path))
    df_sliced, date_info = slice_by_date_range(df, start=args.start, end=args.end, lookback_weeks=args.lookback_weeks)

    symbol = args.symbol
    tick_value = 2.0 if symbol == "MNQ" else 20.0

    out_dir = Path(args.output_dir) if args.output_dir else Path("reports") / f"sweep_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: List[SweepRow] = []
    metas: List[Dict[str, Any]] = []
    for v in args.values:
        row, meta = _run_backtest_with_override(
            df_sliced,
            decision=args.decision,
            symbol=symbol,
            tick_value=tick_value,
            contracts=args.contracts,
            slippage_ticks=args.slippage_ticks,
            max_pos=args.max_pos,
            config_path=args.config_path,
            value=v,
        )
        rows.append(row)
        metas.append(meta)

    df_out = pd.DataFrame([asdict(r) for r in rows]).sort_values("score", ascending=False)
    df_out.to_csv(out_dir / "sweep.csv", index=False)

    payload = {
        "kind": "sweep",
        "config_path": args.config_path,
        "values": args.values,
        "decision": args.decision,
        "symbol": symbol,
        "date_range": date_info,
        "results": df_out.to_dict(orient="records"),
        "metas": metas,
    }
    with open(out_dir / "sweep.json", "w") as f:
        json.dump(payload, f, indent=2, default=str)

    best = df_out.iloc[0].to_dict() if not df_out.empty else None
    print(f"✅ Sweep complete: {len(rows)} runs")
    print(f"Output: {out_dir}")
    if best:
        print(f"Best: value={best['value']} score={best['score']:.2f} pnl={best['total_pnl']:.2f} dd={best['max_drawdown']:.2f}")
    return 0


def cmd_walkforward(args: argparse.Namespace) -> int:
    df = load_ohlcv_data(Path(args.data_path))

    # Slice to a bounded range first (optional)
    df_sliced, date_info = slice_by_date_range(df, start=args.start, end=args.end, lookback_weeks=args.lookback_weeks)
    start_ts = df_sliced.index[0]
    end_ts = df_sliced.index[-1]

    train = pd.Timedelta(weeks=args.train_weeks)
    test = pd.Timedelta(weeks=args.test_weeks)
    step = pd.Timedelta(weeks=args.step_weeks or args.test_weeks)

    symbol = args.symbol
    tick_value = 2.0 if symbol == "MNQ" else 20.0

    out_dir = Path(args.output_dir) if args.output_dir else Path("reports") / f"walkforward_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cursor = start_ts
    windows = []
    while cursor + train + test <= end_ts:
        train_start = cursor
        train_end = cursor + train
        test_start = train_end
        test_end = train_end + test

        df_train = df_sliced[(df_sliced.index >= train_start) & (df_sliced.index < train_end)]
        df_test = df_sliced[(df_sliced.index >= test_start) & (df_sliced.index < test_end)]
        if df_train.empty or df_test.empty:
            cursor = cursor + step
            continue

        # Pick best value on train
        train_rows = []
        for v in args.values:
            row, _ = _run_backtest_with_override(
                df_train,
                decision=args.decision,
                symbol=symbol,
                tick_value=tick_value,
                contracts=args.contracts,
                slippage_ticks=args.slippage_ticks,
                max_pos=args.max_pos,
                config_path=args.config_path,
                value=v,
            )
            train_rows.append(row)

        train_df = pd.DataFrame([asdict(r) for r in train_rows]).sort_values("score", ascending=False)
        best_val = train_df.iloc[0]["value"]

        # Evaluate best on test
        test_row, _ = _run_backtest_with_override(
            df_test,
            decision=args.decision,
            symbol=symbol,
            tick_value=tick_value,
            contracts=args.contracts,
            slippage_ticks=args.slippage_ticks,
            max_pos=args.max_pos,
            config_path=args.config_path,
            value=best_val,
        )

        windows.append(
            {
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "best_value": best_val,
                "train_best": train_df.iloc[0].to_dict(),
                "test": asdict(test_row),
            }
        )

        cursor = cursor + step

    wf_df = pd.DataFrame(
        [
            {
                "test_start": w["test_start"],
                "test_end": w["test_end"],
                "best_value": w["best_value"],
                "test_score": w["test"]["score"],
                "test_total_pnl": w["test"]["total_pnl"],
                "test_max_drawdown": w["test"]["max_drawdown"],
                "test_win_rate": w["test"]["win_rate"],
                "test_total_trades": w["test"]["total_trades"],
                "test_profit_factor": w["test"]["profit_factor"],
            }
            for w in windows
        ]
    )
    wf_df.to_csv(out_dir / "walkforward.csv", index=False)
    with open(out_dir / "walkforward.json", "w") as f:
        json.dump(
            {
                "kind": "walkforward",
                "config_path": args.config_path,
                "values": args.values,
                "decision": args.decision,
                "symbol": symbol,
                "date_range": date_info,
                "windows": windows,
            },
            f,
            indent=2,
            default=str,
        )

    print(f"✅ Walk-forward complete: {len(windows)} windows")
    print(f"Output: {out_dir}")
    return 0


def _max_drawdown_from_pnls(pnls: np.ndarray) -> float:
    """Compute max drawdown from a sequence of trade PnLs."""
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    return float(np.max(dd)) if dd.size else 0.0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    if args.report_dir:
        report_dir = Path(args.report_dir)
        trades_path = report_dir / "trades.csv"
    else:
        trades_path = Path(args.trades_csv)

    if not trades_path.exists():
        raise FileNotFoundError(f"Trades CSV not found: {trades_path}")

    df = pd.read_csv(trades_path)
    if "pnl" not in df.columns:
        raise ValueError("trades.csv must include a 'pnl' column")

    pnls = df["pnl"].fillna(0).astype(float).to_numpy()
    n = pnls.size
    if n == 0:
        raise ValueError("No trades found for bootstrap")

    iters = int(args.iterations)
    rng = np.random.default_rng(int(args.seed) if args.seed is not None else None)

    totals = np.zeros(iters, dtype=float)
    max_dds = np.zeros(iters, dtype=float)
    for i in range(iters):
        sample = rng.choice(pnls, size=n, replace=True)
        totals[i] = float(np.sum(sample))
        max_dds[i] = _max_drawdown_from_pnls(sample)

    def pct(a: np.ndarray, q: float) -> float:
        return float(np.percentile(a, q))

    summary = {
        "kind": "bootstrap",
        "source": str(trades_path),
        "trades": int(n),
        "iterations": int(iters),
        "p_profitable": float(np.mean(totals > 0)),
        "total_pnl": {
            "p05": pct(totals, 5),
            "p25": pct(totals, 25),
            "p50": pct(totals, 50),
            "p75": pct(totals, 75),
            "p95": pct(totals, 95),
        },
        "max_drawdown": {
            "p05": pct(max_dds, 5),
            "p25": pct(max_dds, 25),
            "p50": pct(max_dds, 50),
            "p75": pct(max_dds, 75),
            "p95": pct(max_dds, 95),
        },
    }

    out_dir = Path(args.output_dir) if args.output_dir else Path("reports") / f"bootstrap_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "bootstrap_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"✅ Bootstrap complete: {iters} iterations")
    print(f"Output: {out_dir}")
    print(f"P(profitable): {summary['p_profitable']:.1%}")
    print(f"Total P&L p50: {summary['total_pnl']['p50']:.2f}  (p05: {summary['total_pnl']['p05']:.2f})")
    print(f"Max DD p50: {summary['max_drawdown']['p50']:.2f}  (p95: {summary['max_drawdown']['p95']:.2f})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest robustness tools")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Common backtest args
    def add_bt_args(p):
        p.add_argument("--data-path", required=True)
        p.add_argument("--symbol", choices=["MNQ", "NQ"], default="MNQ")
        p.add_argument("--decision", choices=["1m", "5m"], default="5m")
        p.add_argument("--start", help="Start date (YYYY-MM-DD)")
        p.add_argument("--end", help="End date (YYYY-MM-DD)")
        p.add_argument("--lookback-weeks", type=int)
        p.add_argument("--contracts", type=int, default=5)
        p.add_argument("--slippage-ticks", type=float, default=0.5)
        p.add_argument("--max-pos", type=int, default=1)
        p.add_argument("--output-dir", default=None)

    p_sweep = sub.add_parser("sweep", help="Parameter sweep")
    add_bt_args(p_sweep)
    p_sweep.add_argument("--config-path", required=True, help="e.g., signals.min_confidence or risk.stop_loss_atr_multiplier")
    p_sweep.add_argument("--values", nargs="+", required=True, help="Values to test (auto-cast)")

    p_wf = sub.add_parser("walkforward", help="Walk-forward: optimize on train window, test on next window")
    add_bt_args(p_wf)
    p_wf.add_argument("--config-path", required=True)
    p_wf.add_argument("--values", nargs="+", required=True)
    p_wf.add_argument("--train-weeks", type=int, default=8)
    p_wf.add_argument("--test-weeks", type=int, default=2)
    p_wf.add_argument("--step-weeks", type=int, default=None)

    p_boot = sub.add_parser("bootstrap", help="Bootstrap robustness from trades.csv")
    g = p_boot.add_mutually_exclusive_group(required=True)
    g.add_argument("--report-dir", default=None)
    g.add_argument("--trades-csv", default=None)
    p_boot.add_argument("--iterations", type=int, default=5000)
    p_boot.add_argument("--seed", type=int, default=None)
    p_boot.add_argument("--output-dir", default=None)

    args = parser.parse_args()

    # Cast values to floats/ints/bools when possible
    if getattr(args, "values", None):
        casted = []
        for v in args.values:
            raw = str(v)
            if raw.lower() in ("true", "false"):
                casted.append(raw.lower() == "true")
                continue
            try:
                if "." in raw:
                    casted.append(float(raw))
                else:
                    casted.append(int(raw))
                continue
            except Exception:
                pass
            casted.append(raw)
        args.values = casted

    if args.cmd == "sweep":
        return cmd_sweep(args)
    if args.cmd == "walkforward":
        return cmd_walkforward(args)
    if args.cmd == "bootstrap":
        return cmd_bootstrap(args)
    raise ValueError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())


