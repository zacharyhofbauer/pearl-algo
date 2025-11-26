#!/usr/bin/env python
from __future__ import annotations

"""
PearlAlgo Futures Desk — Status Dashboard (ANSI-only).
Shows IB Gateway status, workflow files, and performance stats for ES/NQ/GC.
"""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from pearlalgo.futures.performance import DEFAULT_PERF_PATH, load_performance


CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
GREEN = "\033[1;32m"
RED = "\033[1;31m"
RESET = "\033[0m"


def color(text: str, code: str) -> str:
    return f"{code}{text}{RESET}"


def run_cmd(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
    except Exception as exc:
        return f"ERROR: {exc}"


def gateway_status() -> tuple[str, str]:
    status = run_cmd(["systemctl", "is-active", "ibgateway.service"])
    log_tail = run_cmd(["journalctl", "-q", "-u", "ibgateway.service", "-n", "20", "--no-pager"])
    version = ""
    for line in log_tail.splitlines():
        if "Running GATEWAY" in line:
            version = line.strip()
            break
    return status, version


def latest_today(prefix: str, suffix: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = Path(prefix) / f"{today}{suffix}"
    return str(path) if path.exists() else "missing"


def perf_stats(df: pd.DataFrame, date_filter: str | None = None) -> dict[str, float]:
    if df.empty:
        return {"rows": 0, "realized": 0.0}
    if date_filter:
        df = df[df["timestamp"].dt.strftime("%Y%m%d") == date_filter]
    if df.empty:
        return {"rows": 0, "realized": 0.0}
    realized = df["realized_pnl"].fillna(0).sum() if "realized_pnl" in df.columns else 0.0
    return {"rows": float(len(df)), "realized": float(realized)}


def perf_by_symbol(df: pd.DataFrame, date_filter: str | None = None) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    if df.empty:
        return stats
    if date_filter:
        df = df[df["timestamp"].dt.strftime("%Y%m%d") == date_filter]
    for sym, sub in df.groupby("symbol"):
        realized = sub["realized_pnl"].fillna(0).sum() if "realized_pnl" in sub.columns else 0.0
        stats[sym] = {"trades": float(len(sub)), "realized": float(realized)}
    return stats


def section(title: str) -> None:
    print(color(f"--- {title} ---", CYAN))


def format_status(active: str) -> str:
    return color(active, GREEN) if active == "active" else color(active, RED)


def print_per_symbol(stats: dict[str, dict[str, float]], symbols: Iterable[str]) -> None:
    for sym in symbols:
        st = stats.get(sym, {"trades": 0, "realized": 0.0})
        realized = st.get("realized", 0.0)
        pnl_color = GREEN if realized >= 0 else RED
        print(f"  {sym}: trades={int(st.get('trades', 0))}, realized={color(f'{realized:.2f}', pnl_color)}")


def main() -> int:
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y%m%d")

    print(color("============================================", CYAN))
    print(color(" PearlAlgo Futures Desk — Status Dashboard", YELLOW))
    print(color("============================================", CYAN))
    print(f"Timestamp (UTC): {now.isoformat()}")
    print()

    section("IB Gateway")
    status, version = gateway_status()
    print(f"Status: {format_status(status)}")
    if version:
        print(f"Version: {version}")
    print()

    section("Workflow Files")
    print(f"Signals:  {latest_today('signals', '_signals.csv')}")
    print(f"Report:   {latest_today('reports', '_report.md')}")
    perf_path = DEFAULT_PERF_PATH
    print(f"Perf CSV: {perf_path if perf_path.exists() else 'missing'}")
    print()

    section("Performance")
    df = load_performance(perf_path)
    total_stats = perf_stats(df)
    today_stats = perf_stats(df, today)
    total_pnl_color = GREEN if total_stats["realized"] >= 0 else RED
    today_pnl_color = GREEN if today_stats["realized"] >= 0 else RED

    if df.empty:
        print(color("No performance log yet (run live_paper_loop.py).", RED))
    else:
        total_realized = total_stats["realized"]
        today_realized = today_stats["realized"]
        print(f"Total rows: {int(total_stats['rows'])}, realized: {color(f'{total_realized:.2f}', total_pnl_color)}")
        print(f"Today rows: {int(today_stats['rows'])}, realized: {color(f'{today_realized:.2f}', today_pnl_color)}")
        print("Per-symbol (today):")
        per_sym = perf_by_symbol(df, today)
        print_per_symbol(per_sym, symbols=("ES", "NQ", "GC"))

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
