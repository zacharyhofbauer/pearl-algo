#!/usr/bin/env python
from __future__ import annotations

"""
ASCII status dashboard for PearlAlgo IBKR futures setup.
- Checks IB Gateway service status
- Shows recent gateway logs (tail)
- Shows latest signals/report files
- Summarizes performance log counts
"""

import subprocess
from datetime import datetime
from pathlib import Path


def run_cmd(cmd: list[str]) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return out.strip()
    except Exception as exc:
        return f"ERROR: {exc}"


def gateway_status() -> str:
    return run_cmd(["systemctl", "is-active", "ibgateway.service"])


def gateway_log_tail(lines: int = 10) -> str:
    return run_cmd(["journalctl", "-u", "ibgateway.service", "-n", str(lines), "--no-pager"])


def latest_file(pattern: str) -> str:
    paths = sorted(Path().glob(pattern))
    return str(paths[-1]) if paths else "-"


def performance_summary(path: Path) -> str:
    if not path.exists():
        return "performance log missing"
    import pandas as pd

    try:
        df = pd.read_csv(path)
        total = len(df)
        trades = df.dropna(subset=["realized_pnl"]).shape[0] if "realized_pnl" in df.columns else 0
        return f"{total} decisions, {trades} with realized_pnl"
    except Exception as exc:
        return f"failed to read: {exc}"


def main() -> int:
    print("========= PearlAlgo Status Dashboard =========")
    print(f"Timestamp (UTC): {datetime.utcnow().isoformat()}Z")
    print("----------------------------------------------")
    print(f"IB Gateway status: {gateway_status()}")
    print("----------------------------------------------")
    print("Gateway log tail (last 10 lines):")
    print(gateway_log_tail(10))
    print("----------------------------------------------")
    print("Latest files:")
    print(f"- Signals: {latest_file('signals/*_signals.csv')}")
    print(f"- Report:  {latest_file('reports/*_report.md')}")
    perf_path = Path("data/performance/futures_decisions.csv")
    print(f"- Performance log: {perf_path if perf_path.exists() else 'missing'} ({performance_summary(perf_path)})")
    print("----------------------------------------------")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
