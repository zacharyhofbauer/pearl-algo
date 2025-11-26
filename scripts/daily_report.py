#!/usr/bin/env python
from __future__ import annotations

"""
Generate a simple daily markdown report from signals, trades journal, and the futures performance log.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def load_latest(path_glob: str):
    paths = sorted(Path().glob(path_glob))
    return paths[-1] if paths else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate daily report markdown.")
    parser.add_argument("--date", help="YYYYMMDD; default today", default=None)
    parser.add_argument(
        "--performance-path",
        default="data/performance/futures_decisions.csv",
        help="Futures performance log (decisions/trades).",
    )
    parser.add_argument("--journal-path", default="journal/trades.csv", help="Legacy trades journal path.")
    args = parser.parse_args(argv)

    today = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    signals_path = load_latest(f"signals/{today}_signals.csv")
    trades_path = Path(args.journal_path)
    perf_path = Path(args.performance_path)

    signals = pd.read_csv(signals_path) if signals_path and signals_path.exists() else pd.DataFrame()
    trades = pd.read_csv(trades_path) if trades_path.exists() else pd.DataFrame()
    perf = pd.read_csv(perf_path, parse_dates=["timestamp"]) if perf_path.exists() else pd.DataFrame()
    if not perf.empty:
        perf = perf[perf["timestamp"].dt.strftime("%Y%m%d") == today]

    report_dir = Path("reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{today}_report.md"

    lines = []
    lines.append(f"# Daily Report {today}")
    lines.append("")
    lines.append("## Signals")
    if not signals.empty:
        lines.append(signals.to_markdown(index=False))
    else:
        lines.append("No signals.")
    lines.append("")
    lines.append("## Trades (legacy journal)")
    if not trades.empty and "timestamp" in trades.columns:
        today_trades = trades[trades["timestamp"].str.startswith(today)]
        lines.append(today_trades.to_markdown(index=False) if not today_trades.empty else "No trades.")
    else:
        lines.append("No trades.")
    lines.append("")
    lines.append("## Futures Performance Log")
    if not perf.empty:
        lines.append(perf.tail(20).to_markdown(index=False))
    else:
        lines.append("No performance rows for this date.")
    lines.append("")
    lines.append("## Summary")
    if not perf.empty and "realized_pnl" in perf.columns:
        lines.append(f"- Realized PnL (sum): {perf['realized_pnl'].fillna(0).sum():.2f}")
        lines.append(f"- Decisions logged: {len(perf)}")
    elif not trades.empty:
        pnl = trades["pnl_after"].iloc[-1] if "pnl_after" in trades.columns else 0.0
        lines.append(f"- PnL (latest): {pnl}")
        lines.append(f"- Trades count: {len(trades)}")
    else:
        lines.append("- PnL: n/a")
    lines.append("")
    lines.append("## Risk Flags")
    lines.append("- Check RISK_HALT file; monitor daily loss limits.")
    lines.append("")
    lines.append("## Prep Checklist")
    lines.append("- Review signals and trades.")
    lines.append("- Check Gateway/IBC status.")
    lines.append("- Verify data freshness.")

    report_path.write_text("\n".join(lines))
    print(f"[OK] Wrote report -> {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
