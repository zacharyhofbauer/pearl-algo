#!/usr/bin/env python
from __future__ import annotations

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
    args = parser.parse_args(argv)

    today = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    signals_path = load_latest(f"signals/{today}_signals.csv")
    trades_path = Path("journal/trades.csv")

    signals = pd.read_csv(signals_path) if signals_path and signals_path.exists() else pd.DataFrame()
    trades = pd.read_csv(trades_path) if trades_path.exists() else pd.DataFrame()

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
    lines.append("## Trades")
    if not trades.empty:
        today_trades = trades[trades["timestamp"].str.startswith(today)]
        lines.append(today_trades.to_markdown(index=False) if not today_trades.empty else "No trades.")
    else:
        lines.append("No trades.")
    lines.append("")
    lines.append("## Summary")
    if not trades.empty:
        pnl = trades["pnl_after"].iloc[-1] if "pnl_after" in trades.columns else 0.0
        lines.append(f"- PnL (latest): {pnl}")
        lines.append(f"- Trades count: {len(trades)}")
    else:
        lines.append("- PnL: n/a")
    lines.append("")
    lines.append("## Risk Flags")
    lines.append("- Risk monitor not implemented (placeholder).")
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
