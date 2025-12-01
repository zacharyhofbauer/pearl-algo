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

from pearlalgo.futures.config import load_profile
from pearlalgo.futures.performance import DEFAULT_PERF_PATH, load_performance, summarize_daily_performance
from pearlalgo.futures.risk import compute_risk_state


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
        
        # Enhanced metrics from summarize_daily_performance
        daily_summary = summarize_daily_performance(perf_path, date=today)
        if daily_summary:
            win_rate = daily_summary.get("win_rate", 0.0)
            avg_pnl = daily_summary.get("avg_realized_pnl", 0.0)
            worst_dd = daily_summary.get("worst_drawdown", 0.0)
            avg_time = daily_summary.get("avg_time_in_trade_minutes", 0.0)
            trades = int(daily_summary.get("trades", 0))
            print(f"Today trades: {trades}, win rate: {win_rate*100:.1f}%, avg P&L: {color(f'{avg_pnl:.2f}', GREEN if avg_pnl >= 0 else RED)}")
            print(f"Worst drawdown: {color(f'{worst_dd:.2f}', RED if worst_dd < 0 else GREEN)}, avg time in trade: {avg_time:.1f} min")
        
        print("Per-symbol (today):")
        per_sym = perf_by_symbol(df, today)
        print_per_symbol(per_sym, symbols=("ES", "NQ", "GC"))
        
        # Show last trade_reason for each symbol
        if not df.empty:
            today_df = df[df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in df.columns else df
            if not today_df.empty and "trade_reason" in today_df.columns:
                print("Last trade reasons:")
                for sym in ("ES", "NQ", "GC"):
                    sym_df = today_df[today_df["symbol"] == sym]
                    if not sym_df.empty:
                        last_reason = sym_df.iloc[-1].get("trade_reason")
                        # Handle NaN/None values
                        if pd.isna(last_reason) or last_reason is None:
                            last_reason = "N/A"
                        print(f"  {sym}: {last_reason}")
    
    # Risk state section
    section("Risk State")
    profile = load_profile()
    if not df.empty:
        today_df = df[df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in df.columns else df
        trades_today = len(today_df) if not today_df.empty else 0
        realized_pnl = today_stats.get("realized", 0.0)
        risk_state = compute_risk_state(
            profile,
            day_start_equity=profile.starting_balance,
            realized_pnl=realized_pnl,
            unrealized_pnl=0.0,
            trades_today=trades_today,
            max_trades=profile.max_trades,
            now=datetime.now(timezone.utc),
        )
        status_color = GREEN if risk_state.status == "OK" else YELLOW if risk_state.status == "NEAR_LIMIT" else RED
        print(f"Status: {color(risk_state.status, status_color)}")
        print(f"Remaining buffer: {color(f'{risk_state.remaining_loss_buffer:.2f}', GREEN if risk_state.remaining_loss_buffer > 0 else RED)}")
        if risk_state.max_trades:
            remaining_trades = max(0, risk_state.max_trades - trades_today)
            print(f"Trades today: {trades_today}/{risk_state.max_trades}, remaining: {remaining_trades}")
        if risk_state.cooldown_until:
            print(f"Cooldown until: {color(risk_state.cooldown_until.isoformat(), YELLOW)}")
    else:
        print("No data available (run signals first)")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
