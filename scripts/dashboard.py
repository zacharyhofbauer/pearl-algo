#!/usr/bin/env python
from __future__ import annotations

"""
🎯 PearlAlgo Unified Trading Dashboard
Combines the best features from status_dashboard and comprehensive_dashboard
into one perfect, efficient monitoring tool.
"""

import ast
import re
import sys
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
import os

original_cwd = os.getcwd()
try:
    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    modules_to_remove = [k for k in list(sys.modules.keys()) if k == "pearlalgo"]
    for mod in modules_to_remove:
        del sys.modules[mod]
except Exception:
    pass

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich import box
from rich.text import Text

from pearlalgo.futures.config import load_profile
from pearlalgo.futures.performance import (
    DEFAULT_PERF_PATH,
    load_performance,
    calculate_profit_factor,
)
from pearlalgo.futures.risk import compute_risk_state

console = Console()

# Import helper functions directly (avoid circular import)
# These are defined in status_dashboard.py, but we'll redefine key ones here
MICRO_SYMBOLS = {"MGC", "MYM", "MCL", "MNQ", "MES", "M2K", "M6E", "M6B", "M6A", "M6J"}
MINI_SYMBOLS = {"ES", "NQ", "GC", "YM", "CL", "NG", "ZB", "ZN", "ZF", "ZT"}


# Define helper functions directly (no longer importing from status_dashboard)
def get_us_eastern_time(utc_time: datetime) -> str:
    """Convert UTC time to US/Eastern timezone string."""
    if US_EASTERN:
        try:
            eastern_time = utc_time.astimezone(US_EASTERN)
            return eastern_time.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            pass
    # Fallback: manual offset (EST = UTC-5, EDT = UTC-4)
    offset_hours = -4
    eastern_time = utc_time.replace(tzinfo=timezone.utc) + pd.Timedelta(
        hours=offset_hours
    )
    return eastern_time.strftime("%Y-%m-%d %H:%M:%S EST")


def get_trading_processes() -> list[dict[str, Any]]:
    """Get list of running trading processes with details."""
    processes = []
    try:
        result = subprocess.run(
            ["pgrep", "-af", "pearlalgo trade"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line and "pearlalgo trade" in line:
                    parts = line.split(" ", 1)
                    if len(parts) >= 2:
                        pid = parts[0]
                        cmd = parts[1]
                        symbols = []
                        strategy = "unknown"
                        contract_type = "unknown"

                        for sym in MICRO_SYMBOLS:
                            if sym in cmd:
                                symbols.append(sym)
                                contract_type = "micro"
                        if contract_type == "unknown":
                            for sym in MINI_SYMBOLS:
                                if sym in cmd:
                                    symbols.append(sym)
                                    contract_type = "mini"

                        if "--strategy" in cmd:
                            match = re.search(r"--strategy\s+(\w+)", cmd)
                            if match:
                                strategy = match.group(1)

                        processes.append(
                            {
                                "pid": pid,
                                "command": cmd[:80] + "..." if len(cmd) > 80 else cmd,
                                "symbols": symbols,
                                "strategy": strategy,
                                "contract_type": contract_type,
                            }
                        )
    except Exception:
        pass
    return processes


def detect_contract_type(symbols: list[str]) -> str:
    """Detect if trading micro or mini contracts based on symbols."""
    has_micro = any(sym in MICRO_SYMBOLS for sym in symbols)
    has_mini = any(sym in MINI_SYMBOLS for sym in symbols)
    if has_micro and has_mini:
        return "mixed"
    elif has_micro:
        return "micro"
    elif has_mini:
        return "mini"
    else:
        return "unknown"


def gateway_status() -> tuple[str, str, bool]:
    """Get IB Gateway status and version."""
    result = subprocess.run(["pgrep", "-f", "IbcGateway"], capture_output=True)
    is_running = result.returncode == 0
    pid = result.stdout.decode().strip() if is_running else None

    result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
    port_listening = "4002" in result.stdout

    version = ""
    try:
        log_tail = run_cmd(
            ["journalctl", "-q", "-u", "ibgateway.service", "-n", "50", "--no-pager"]
        )
        for line in log_tail.splitlines():
            if (
                "Running GATEWAY" in line
                or "IB Gateway" in line
                or "version" in line.lower()
            ):
                version = line.strip()[:100]
                break
        if not version and pid:
            try:
                ps_result = run_cmd(["ps", "-p", pid, "-o", "args="])
                if "gateway" in ps_result.lower():
                    match = re.search(r"(\d+\.\d+\.\d+)", ps_result)
                    if match:
                        version = f"IB Gateway {match.group(1)}"
            except Exception:
                pass
    except Exception:
        pass

    status = "✅ Running" if (is_running and port_listening) else "❌ Not Running"
    return status, version, is_running and port_listening


def compute_sharpe_ratio(perf_df: pd.DataFrame, risk_free_rate: float = 0.0) -> float:
    """Compute Sharpe ratio from P&L returns."""
    if perf_df.empty or "realized_pnl" not in perf_df.columns:
        return 0.0
    pnl = perf_df["realized_pnl"].dropna()
    if len(pnl) < 2:
        return 0.0
    returns = pnl.diff().dropna()
    if len(returns) < 2:
        return 0.0
    mean_return = returns.mean()
    std_return = returns.std()
    if std_return == 0 or pd.isna(std_return):
        return 0.0
    sharpe = (mean_return - risk_free_rate) / std_return
    return float(sharpe) if not pd.isna(sharpe) else 0.0


def compute_sortino_ratio(perf_df: pd.DataFrame, risk_free_rate: float = 0.0) -> float:
    """Compute Sortino ratio from P&L returns (downside deviation only)."""
    if perf_df.empty or "realized_pnl" not in perf_df.columns:
        return 0.0
    pnl = perf_df["realized_pnl"].dropna()
    if len(pnl) < 2:
        return 0.0
    returns = pnl.diff().dropna()
    if len(returns) < 2:
        return 0.0
    mean_return = returns.mean()
    downside_returns = returns[returns < 0]
    if len(downside_returns) == 0:
        return 10.0 if mean_return > 0 else 0.0
    downside_std = downside_returns.std()
    if downside_std == 0 or pd.isna(downside_std):
        return 0.0
    sortino = (mean_return - risk_free_rate) / downside_std
    return float(sortino) if not pd.isna(sortino) else 0.0


def compute_trade_statistics(perf_df: pd.DataFrame) -> dict[str, Any]:
    """Compute comprehensive trade statistics."""
    if perf_df.empty:
        return {
            "total_trades": 0,
            "winners": 0,
            "losers": 0,
            "win_rate": 0.0,
            "avg_hold_time_minutes": 0.0,
            "largest_winner": 0.0,
            "largest_loser": 0.0,
            "avg_pnl_per_trade": 0.0,
        }
    # Try to get trades with full timing info, but fall back to just PnL if needed
    if "entry_time" in perf_df.columns and "exit_time" in perf_df.columns:
        completed_trades = perf_df.dropna(subset=["realized_pnl"])
        # Filter to only rows that have both entry and exit times if available
        has_times = (
            completed_trades["entry_time"].notna()
            & completed_trades["exit_time"].notna()
        )
        if has_times.any():
            completed_trades = completed_trades[has_times]
    else:
        completed_trades = perf_df.dropna(subset=["realized_pnl"])
    if completed_trades.empty:
        completed_trades = perf_df.dropna(subset=["realized_pnl"])
    if completed_trades.empty:
        return {
            "total_trades": 0,
            "winners": 0,
            "losers": 0,
            "win_rate": 0.0,
            "avg_hold_time_minutes": 0.0,
            "largest_winner": 0.0,
            "largest_loser": 0.0,
            "avg_pnl_per_trade": 0.0,
        }
    pnl_col = completed_trades["realized_pnl"].fillna(0.0)
    winners = pnl_col[pnl_col > 0]
    losers = pnl_col[pnl_col < 0]
    avg_hold_time = 0.0
    if (
        "entry_time" in completed_trades.columns
        and "exit_time" in completed_trades.columns
    ):
        try:
            # Ensure both datetime columns are timezone-aware or both are naive
            entry_times = pd.to_datetime(completed_trades["entry_time"])
            exit_times = pd.to_datetime(completed_trades["exit_time"])
            
            # Normalize timezones: if one is aware and one is naive, make both aware (UTC)
            entry_tz = entry_times.dt.tz
            exit_tz = exit_times.dt.tz
            
            if entry_tz is None and exit_tz is not None:
                # Entry is naive, exit is aware - make entry aware (assume UTC)
                entry_times = entry_times.dt.tz_localize('UTC')
            elif exit_tz is None and entry_tz is not None:
                # Exit is naive, entry is aware - make exit aware (assume UTC)
                exit_times = exit_times.dt.tz_localize('UTC')
            elif entry_tz is not None and exit_tz is not None:
                # Both are aware - ensure same timezone
                if entry_tz != exit_tz:
                    exit_times = exit_times.dt.tz_convert(entry_tz)
            
            # Now safe to subtract
            durations = (exit_times - entry_times).dt.total_seconds() / 60.0
            durations = durations.dropna()
            if len(durations) > 0:
                avg_hold_time = float(durations.mean())
        except (TypeError, ValueError) as e:
            # If timezone handling fails, skip duration calculation
            # This can happen with mixed timezone data
            pass
    total_trades = len(completed_trades)
    win_rate = (len(winners) / total_trades * 100.0) if total_trades > 0 else 0.0
    largest_winner = float(winners.max()) if len(winners) > 0 else 0.0
    largest_loser = float(losers.min()) if len(losers) > 0 else 0.0
    avg_pnl = float(pnl_col.mean()) if len(pnl_col) > 0 else 0.0
    return {
        "total_trades": total_trades,
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": win_rate,
        "avg_hold_time_minutes": avg_hold_time,
        "largest_winner": largest_winner,
        "largest_loser": largest_loser,
        "avg_pnl_per_trade": avg_pnl,
    }


def aggregate_pnl_by_symbol(perf_df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Aggregate realized and unrealized P&L by symbol."""
    result: dict[str, dict[str, float]] = {}
    if perf_df.empty:
        return {"TOTAL": {"realized": 0.0, "unrealized": 0.0}}
    if "symbol" not in perf_df.columns:
        return {"TOTAL": {"realized": 0.0, "unrealized": 0.0}}
    for symbol in perf_df["symbol"].unique():
        if pd.isna(symbol):
            continue
        sym_df = perf_df[perf_df["symbol"] == symbol]
        realized = (
            sym_df["realized_pnl"].fillna(0.0).sum()
            if "realized_pnl" in sym_df.columns
            else 0.0
        )
        unrealized = 0.0
        if "unrealized_pnl" in sym_df.columns:
            unrealized_vals = sym_df["unrealized_pnl"].dropna()
            if len(unrealized_vals) > 0:
                unrealized = float(unrealized_vals.iloc[-1])
        result[str(symbol)] = {
            "realized": float(realized),
            "unrealized": float(unrealized),
        }
    total_realized = sum(v["realized"] for v in result.values())
    total_unrealized = sum(v["unrealized"] for v in result.values())
    result["TOTAL"] = {"realized": total_realized, "unrealized": total_unrealized}
    return result


def parse_sr_dict_from_notes(notes: str) -> dict[str, Any]:
    """Parse SR dictionary from notes field."""
    if not notes or pd.isna(notes):
        return {}
    try:
        match = re.search(r"sr\s*=\s*\{([^}]+)\}", str(notes))
        if match:
            dict_str = "{" + match.group(1) + "}"
            dict_str = re.sub(r"np\.float64\(([^)]+)\)", r"\1", dict_str)
            parsed = ast.literal_eval(dict_str)
            if isinstance(parsed, dict):
                result = {}
                for k, v in parsed.items():
                    if hasattr(v, "item"):
                        result[k] = v.item()
                    else:
                        result[k] = v
                return result
    except Exception:
        pass
    return {}


def extract_signal_context(
    perf_df: pd.DataFrame, signals_df: pd.DataFrame
) -> pd.DataFrame:
    """Extract technical analysis context from performance CSV notes and merge with signals."""
    if perf_df.empty:
        return pd.DataFrame()
    context_rows = []
    for symbol in perf_df["symbol"].unique():
        if pd.isna(symbol):
            continue
        sym_perf = perf_df[perf_df["symbol"] == symbol].sort_values(
            "timestamp", ascending=False
        )
        sym_signals = (
            signals_df[signals_df["symbol"] == symbol].sort_values(
                "timestamp", ascending=False
            )
            if not signals_df.empty
            else pd.DataFrame()
        )
        for idx, row in sym_perf.head(3).iterrows():
            notes = row.get("notes", "")
            sr_dict = parse_sr_dict_from_notes(notes)
            signal_row = None
            if not sym_signals.empty:
                perf_time = row.get("timestamp")
                if pd.notna(perf_time):
                    time_diffs = abs(
                        (sym_signals["timestamp"] - perf_time).dt.total_seconds()
                    )
                    if len(time_diffs) > 0:
                        closest_idx = time_diffs.idxmin()
                        if time_diffs[closest_idx] < 300:
                            signal_row = sym_signals.loc[closest_idx]
            context_row = {
                "symbol": str(symbol),
                "strategy": row.get("strategy_name", "unknown"),
                "direction": signal_row.get(
                    "direction", row.get("side", "FLAT")
                ).upper()
                if signal_row is not None
                else row.get("side", "FLAT").upper(),
                "entry_price": row.get("entry_price"),
                "stop_price": None,
                "target_price": None,
                "vwap": sr_dict.get("vwap"),
                "support1": sr_dict.get("support1"),
                "resistance1": sr_dict.get("resistance1"),
                "pivot_levels": f"S1: {sr_dict.get('support1', 'N/A')}, R1: {sr_dict.get('resistance1', 'N/A')}"
                if sr_dict
                else "N/A",
                "trade_reason": row.get("trade_reason")
                or (
                    ", ".join([k for k, v in sr_dict.items() if v is not None])
                    if sr_dict
                    else None
                ),
                "confidence": None,
                "timestamp": row.get("timestamp"),
            }
            context_rows.append(context_row)
    if not context_rows:
        return pd.DataFrame()
    return pd.DataFrame(context_rows)


def find_latest_file(pattern: str, directory: str) -> tuple[Path, bool]:
    """Find latest file matching pattern in directory."""
    dir_path = Path(directory)
    if not dir_path.exists():
        return Path(directory) / pattern, False
    matches = sorted(
        dir_path.glob(pattern),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    if matches:
        return matches[0], True
    return Path(directory) / pattern, False


# Try to import pytz
try:
    import pytz

    US_EASTERN = pytz.timezone("US/Eastern")
except ImportError:
    US_EASTERN = None


def get_decision_reasoning(
    perf_df: pd.DataFrame, signals_df: pd.DataFrame
) -> dict[str, Any]:
    """Extract decision reasoning from latest signals and performance log."""
    reasoning = {}

    if perf_df.empty:
        return reasoning

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_df = (
        perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
        if "timestamp" in perf_df.columns
        else pd.DataFrame()
    )

    for symbol in perf_df["symbol"].dropna().unique():
        sym_df = (
            today_df[today_df["symbol"] == symbol]
            if not today_df.empty
            else pd.DataFrame()
        )
        if sym_df.empty:
            continue

        last_row = sym_df.sort_values("timestamp", ascending=False).iloc[0]
        side = last_row.get("side", "FLAT").upper()
        notes = last_row.get("notes", "")
        trade_reason = last_row.get("trade_reason", "")

        # Parse SR dict from notes
        sr_dict = parse_sr_dict_from_notes(notes)

        reasoning[str(symbol)] = {
            "side": side,
            "reason": trade_reason or "No specific reason",
            "vwap": sr_dict.get("vwap"),
            "support1": sr_dict.get("support1"),
            "resistance1": sr_dict.get("resistance1"),
            "price": last_row.get("entry_price") or last_row.get("exit_price"),
            "timestamp": last_row.get("timestamp"),
        }

    return reasoning


def create_header_panel(
    processes: list[dict[str, Any]], refresh_interval: int, seconds_until_refresh: float
) -> Panel:
    """Create unified header with system info, trading processes, and refresh indicator."""
    now_utc = datetime.now(timezone.utc)
    now_eastern = get_us_eastern_time(now_utc)

    status, version, is_ready = gateway_status()

    content = Text()
    content.append("🎯 PearlAlgo Unified Trading Dashboard\n", style="bold cyan")
    content.append(
        f"UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} | ET: {now_eastern}\n",
        style="dim",
    )
    content.append(f"Gateway: {status}", style="bold green" if is_ready else "bold red")
    if version:
        content.append(f" | {version[:60]}", style="dim")

    # Trading processes info
    if processes:
        content.append("\n\n", style="dim")
        all_symbols = []
        all_strategies = set()
        for proc in processes:
            all_symbols.extend(proc.get("symbols", []))
            all_strategies.add(proc.get("strategy", "unknown"))

        if all_symbols:
            contract_type = detect_contract_type(all_symbols)
            contract_display = {
                "micro": "[bold cyan]Micro[/bold cyan]",
                "mini": "[bold green]Mini/Standard[/bold green]",
                "mixed": "[bold yellow]Mixed[/bold yellow]",
            }.get(contract_type, "Unknown")

            content.append(f"Contract Type: {contract_display} | ", style="dim")
            content.append(
                f"Symbols: {', '.join(sorted(set(all_symbols)))} | ", style="yellow"
            )
            content.append(
                f"Strategies: {', '.join(sorted(all_strategies))}", style="cyan"
            )
    else:
        content.append("\n\n", style="dim")
        content.append("⚠️  No active trading processes", style="bold yellow")

    # Refresh indicator
    progress = (refresh_interval - seconds_until_refresh) / refresh_interval
    seconds_left = int(seconds_until_refresh)
    bar_length = 30
    filled = int(bar_length * progress)
    bar = "█" * filled + "░" * (bar_length - filled)
    content.append(
        f"\n\n🔄 Refresh in {seconds_left:2d}s [{progress * 100:3.0f}%] ", style="dim"
    )
    content.append(
        bar, style="green" if progress > 0.8 else "yellow" if progress > 0.5 else "cyan"
    )

    return Panel(content, border_style="cyan", box=box.DOUBLE)


def create_risk_summary_panel(perf_df: pd.DataFrame, profile: Any, today: str) -> Panel:
    """Create comprehensive risk summary panel."""
    today_df = (
        perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
        if "timestamp" in perf_df.columns and not perf_df.empty
        else pd.DataFrame()
    )
    trades_today = len(today_df) if not today_df.empty else 0

    pnl_by_symbol = aggregate_pnl_by_symbol(today_df if not today_df.empty else perf_df)
    total_realized = pnl_by_symbol.get("TOTAL", {}).get("realized", 0.0)
    total_unrealized = pnl_by_symbol.get("TOTAL", {}).get("unrealized", 0.0)

    risk_state = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=total_realized,
        unrealized_pnl=total_unrealized,
        trades_today=trades_today,
        max_trades=profile.max_trades,
        now=datetime.now(timezone.utc),
    )

    drawdown_pct = 0.0
    if risk_state.daily_loss_limit > 0:
        drawdown_pct = (
            (risk_state.daily_loss_limit - risk_state.remaining_loss_buffer)
            / risk_state.daily_loss_limit
        ) * 100.0

    if drawdown_pct < 50:
        risk_indicator = "✅ OK"
        risk_color = "green"
    elif drawdown_pct < 80:
        risk_indicator = "⚠️  NEAR_LIMIT"
        risk_color = "yellow"
    else:
        risk_indicator = "❌ HARD_STOP"
        risk_color = "red"

    sharpe = compute_sharpe_ratio(today_df if not today_df.empty else perf_df)
    sortino = compute_sortino_ratio(today_df if not today_df.empty else perf_df)

    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Metric", style="cyan", width=18)
    table.add_column("Value", style="white", width=20)

    table.add_row(
        "Risk State:", f"[bold {risk_color}]{risk_indicator} ({risk_state.status})[/]"
    )
    table.add_row("", "")
    table.add_row("Remaining Drawdown:", f"${risk_state.remaining_loss_buffer:,.2f}")
    table.add_row("Daily Loss Limit:", f"${risk_state.daily_loss_limit:,.2f}")
    table.add_row("Drawdown Used:", f"{drawdown_pct:.1f}%")
    table.add_row("", "")
    table.add_row("Sharpe Ratio:", f"{sharpe:.2f}")
    table.add_row("Sortino Ratio:", f"{sortino:.2f}")
    table.add_row("", "")
    total_pnl = total_realized + total_unrealized
    pnl_color = "green" if total_pnl >= 0 else "red"
    table.add_row("Total Realized P&L:", f"[{pnl_color}]${total_realized:,.2f}[/]")
    table.add_row("Total Unrealized P&L:", f"[{pnl_color}]${total_unrealized:,.2f}[/]")
    table.add_row("Total P&L:", f"[bold {pnl_color}]${total_pnl:,.2f}[/]")

    return Panel(table, title="⚠️  Risk Summary", border_style=risk_color)


def create_per_symbol_table(perf_df: pd.DataFrame, profile: Any, today: str) -> Table:
    """Create per-symbol metrics table."""
    today_df = (
        perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
        if "timestamp" in perf_df.columns and not perf_df.empty
        else pd.DataFrame()
    )

    signals_path, _ = find_latest_file("*_signals.csv", "signals")
    signals_df = pd.read_csv(signals_path) if signals_path.exists() else pd.DataFrame()
    if not signals_df.empty and "timestamp" in signals_df.columns:
        signals_df["timestamp"] = pd.to_datetime(
            signals_df["timestamp"], errors="coerce"
        )

    table = Table(show_header=True, box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Symbol", style="yellow", width=8, justify="center")
    table.add_column("Last Signal", width=10, justify="center")
    table.add_column("Side", justify="center", width=8)
    table.add_column("Realized P&L", justify="right", width=14)
    table.add_column("Unrealized P&L", justify="right", width=16)
    table.add_column("Position", justify="right", width=8)
    table.add_column("Trades", justify="right", width=7)
    table.add_column("Max", justify="right", width=6)

    pnl_by_symbol = aggregate_pnl_by_symbol(today_df if not today_df.empty else perf_df)
    symbols = sorted(
        set(perf_df["symbol"].dropna().unique()) if not perf_df.empty else []
    )

    if not symbols:
        table.add_row("[dim]No data[/dim]", "", "", "", "", "", "", "")
        return table

    for symbol in symbols:
        sym_today = (
            today_df[today_df["symbol"] == symbol]
            if not today_df.empty
            else pd.DataFrame()
        )

        last_signal_time = "N/A"
        last_signal_side = "FLAT"
        if not sym_today.empty:
            last_row = sym_today.sort_values("timestamp", ascending=False).iloc[0]
            last_signal_time = (
                last_row["timestamp"].strftime("%H:%M:%S")
                if pd.notna(last_row.get("timestamp"))
                else "N/A"
            )
            last_signal_side = last_row.get("side", "FLAT").upper()
        elif not signals_df.empty:
            sym_signals = signals_df[signals_df["symbol"] == symbol]
            if not sym_signals.empty:
                last_sig = sym_signals.sort_values("timestamp", ascending=False).iloc[0]
                last_signal_time = (
                    last_sig["timestamp"].strftime("%H:%M:%S")
                    if pd.notna(last_sig.get("timestamp"))
                    else "N/A"
                )
                last_signal_side = last_sig.get("direction", "FLAT").upper()

        realized = pnl_by_symbol.get(str(symbol), {}).get("realized", 0.0)
        unrealized = pnl_by_symbol.get(str(symbol), {}).get("unrealized", 0.0)
        realized_color = "green" if realized >= 0 else "red"
        unrealized_color = "green" if unrealized >= 0 else "red"

        position_size = 0
        if not sym_today.empty:
            last_filled = sym_today["filled_size"].dropna()
            if len(last_filled) > 0:
                position_size = int(last_filled.iloc[-1])

        trades_count = len(sym_today) if not sym_today.empty else 0
        max_contracts = profile.max_contracts_by_symbol.get(str(symbol).upper(), 0)

        table.add_row(
            str(symbol),
            last_signal_time,
            f"[bold green]{last_signal_side}[/]"
            if last_signal_side in ["LONG", "BUY"]
            else f"[bold red]{last_signal_side}[/]"
            if last_signal_side in ["SHORT", "SELL"]
            else f"[dim]{last_signal_side}[/]",
            f"[{realized_color}]${realized:,.2f}[/]",
            f"[{unrealized_color}]${unrealized:,.2f}[/]",
            str(position_size),
            str(trades_count),
            str(max_contracts),
        )

    return table


def create_decision_reasoning_panel(
    perf_df: pd.DataFrame, signals_df: pd.DataFrame
) -> Panel:
    """Create panel showing why trades are/aren't happening - agentic thinking."""
    reasoning = get_decision_reasoning(perf_df, signals_df)

    table = Table(show_header=True, box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Symbol", style="yellow", width=8, justify="center")
    table.add_column("Signal", justify="center", width=8)
    table.add_column("Price", justify="right", width=10)
    table.add_column("VWAP", justify="right", width=10)
    table.add_column("S1/R1", width=15)
    table.add_column("Reason", width=30)

    if not reasoning:
        table.add_row("[dim]No recent decisions[/dim]", "", "", "", "", "")
        return Panel(table, title="🧠 Agent Decision Reasoning", border_style="cyan")

    for symbol, data in list(reasoning.items())[:8]:  # Show last 8
        side = data["side"]
        side_color = "green" if side == "LONG" else "red" if side == "SHORT" else "dim"
        price = f"${data['price']:,.2f}" if data.get("price") else "N/A"
        vwap = f"${data['vwap']:,.2f}" if data.get("vwap") else "N/A"
        s1 = f"${data['support1']:,.2f}" if data.get("support1") else "N/A"
        r1 = f"${data['resistance1']:,.2f}" if data.get("resistance1") else "N/A"
        s1r1 = f"S1:{s1} R1:{r1}" if s1 != "N/A" or r1 != "N/A" else "N/A"
        reason = str(data.get("reason", "No reason"))[:30]

        table.add_row(
            symbol,
            f"[{side_color}]{side}[/]",
            price,
            vwap,
            s1r1,
            reason,
        )

    return Panel(table, title="🧠 Agent Decision Reasoning", border_style="cyan")


def create_trade_stats_panel(perf_df: pd.DataFrame, today: str) -> Panel:
    """Create trade statistics panel."""
    today_df = (
        perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
        if "timestamp" in perf_df.columns and not perf_df.empty
        else pd.DataFrame()
    )

    stats = compute_trade_statistics(today_df if not today_df.empty else perf_df)

    # Calculate profit factor
    trades_for_pf = today_df if not today_df.empty else perf_df
    profit_factor = 0.0
    if not trades_for_pf.empty and "realized_pnl" in trades_for_pf.columns:
        profit_factor = calculate_profit_factor(
            trades_for_pf.dropna(subset=["realized_pnl"])
        )

    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Metric", style="cyan", width=18)
    table.add_column("Value", style="white", width=20)

    table.add_row("Total Trades:", f"{stats['total_trades']}")
    table.add_row(
        "Winners:", f"[green]{stats['winners']}[/] ({stats['win_rate']:.1f}%)"
    )
    table.add_row(
        "Losers:", f"[red]{stats['losers']}[/] ({100 - stats['win_rate']:.1f}%)"
    )
    table.add_row("", "")
    table.add_row("Profit Factor:", f"{profit_factor:.2f}")
    table.add_row("Avg Hold Time:", f"{stats['avg_hold_time_minutes']:.1f} min")
    table.add_row("Largest Winner:", f"[green]${stats['largest_winner']:,.2f}[/]")
    table.add_row("Largest Loser:", f"[red]${stats['largest_loser']:,.2f}[/]")
    table.add_row("Avg P&L/Trade:", f"${stats['avg_pnl_per_trade']:,.2f}")

    return Panel(table, title="📊 Trade Statistics", border_style="cyan")


def create_recent_trades_panel(perf_df: pd.DataFrame) -> Panel:
    """Create recent trades panel."""
    if perf_df.empty:
        return Panel(
            "[dim]No trades yet[/dim]", title="📝 Recent Trades", border_style="yellow"
        )

    table = Table(show_header=True, box=box.SIMPLE, header_style="bold cyan")
    table.add_column("Time", style="dim", width=10)
    table.add_column("Symbol", style="yellow", width=8)
    table.add_column("Side", justify="center", width=8)
    table.add_column("Size", justify="right", width=6)
    table.add_column("Price", justify="right", width=12)
    table.add_column("P&L", justify="right", width=12)

    for _, row in perf_df.tail(8).iterrows():
        timestamp = row.get("timestamp", pd.NaT)
        time_str = timestamp.strftime("%H:%M:%S") if pd.notna(timestamp) else "N/A"

        symbol = str(row.get("symbol", "N/A"))
        side = str(row.get("side", "FLAT")).upper()
        size = row.get("filled_size", row.get("requested_size", 0)) or 0
        price = row.get("entry_price") or row.get("exit_price") or 0.0
        pnl = row.get("realized_pnl") or row.get("unrealized_pnl") or 0.0

        side_color = (
            "[green]" if side == "LONG" else "[red]" if side == "SHORT" else "[dim]"
        )
        pnl_color = "[green]" if pnl > 0 else "[red]" if pnl < 0 else "[dim]"

        table.add_row(
            time_str,
            symbol,
            f"{side_color}{side}[/]",
            str(int(size)) if size else "0",
            f"${price:,.2f}" if price else "N/A",
            f"{pnl_color}${pnl:,.2f}[/]",
        )

    return Panel(table, title="📝 Recent Trades", border_style="cyan")


def create_signal_context_table(
    perf_df: pd.DataFrame, signals_df: pd.DataFrame
) -> Table:
    """Create latest signal context table."""
    context_df = extract_signal_context(perf_df, signals_df)

    table = Table(show_header=True, box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Symbol", style="yellow", width=8, justify="center")
    table.add_column("Strategy", width=10, justify="center")
    table.add_column("Direction", justify="center", width=8)
    table.add_column("Entry", justify="right", width=10)
    table.add_column("VWAP", justify="right", width=10)
    table.add_column("Reason", width=25)

    if context_df.empty:
        table.add_row("[dim]No signal context[/dim]", "", "", "", "", "")
        return table

    for _, row in context_df.head(8).iterrows():
        direction = row.get("direction", "FLAT")
        dir_color = (
            "green"
            if direction in ["LONG", "BUY"]
            else "red"
            if direction in ["SHORT", "SELL"]
            else "dim"
        )

        entry = (
            f"{row.get('entry_price', 0):.2f}"
            if pd.notna(row.get("entry_price"))
            else "N/A"
        )
        vwap = f"{row.get('vwap', 0):.2f}" if pd.notna(row.get("vwap")) else "N/A"
        reason = (
            str(row.get("trade_reason", "N/A"))[:25]
            if pd.notna(row.get("trade_reason"))
            else "N/A"
        )

        table.add_row(
            str(row.get("symbol", "N/A")),
            str(row.get("strategy", "N/A")),
            f"[{dir_color}]{direction}[/]",
            entry,
            vwap,
            reason,
        )

    return table


def create_equity_curve_panel(perf_df: pd.DataFrame, profile: Any, today: str) -> Panel:
    """Create equity curve visualization panel."""
    today_df = (
        perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
        if "timestamp" in perf_df.columns and not perf_df.empty
        else pd.DataFrame()
    )

    if today_df.empty:
        return Panel(
            "[dim]No data for equity curve[/dim]",
            title="📈 Equity Curve",
            border_style="cyan",
        )

    # Calculate cumulative P&L
    trades = today_df.dropna(subset=["realized_pnl"]).sort_values("timestamp")
    if trades.empty:
        return Panel(
            "[dim]No completed trades for equity curve[/dim]",
            title="📈 Equity Curve",
            border_style="cyan",
        )

    starting_equity = profile.starting_balance
    cumulative_pnl = trades["realized_pnl"].cumsum()
    equity_curve = starting_equity + cumulative_pnl

    # Create ASCII chart
    if len(equity_curve) < 2:
        return Panel(
            "[dim]Insufficient data for chart[/dim]",
            title="📈 Equity Curve",
            border_style="cyan",
        )

    min_equity = equity_curve.min()
    max_equity = equity_curve.max()
    range_equity = max_equity - min_equity if max_equity != min_equity else 1.0

    # Create simple text chart (20 characters wide)
    chart_width = 30
    chart_height = 8

    # Sample points for display
    num_points = min(chart_width, len(equity_curve))
    step = max(1, len(equity_curve) // num_points)
    sampled_equity = equity_curve.iloc[::step].tail(num_points)

    # Build chart
    chart_lines = []
    for row in range(chart_height - 1, -1, -1):
        line = ""
        threshold = min_equity + (range_equity * row / chart_height)
        for val in sampled_equity:
            if val >= threshold:
                line += "█"
            else:
                line += " "
        chart_lines.append(line)

    # Add labels
    content = Text()
    content.append(f"Starting: ${starting_equity:,.2f}\n", style="dim")
    content.append(
        f"Current: ${equity_curve.iloc[-1]:,.2f}\n",
        style="bold green" if equity_curve.iloc[-1] >= starting_equity else "bold red",
    )
    content.append(
        f"High: ${max_equity:,.2f} | Low: ${min_equity:,.2f}\n\n", style="dim"
    )

    # Add chart
    for line in chart_lines:
        content.append(
            line + "\n",
            style="green" if equity_curve.iloc[-1] >= starting_equity else "red",
        )

    content.append(f"\n[{min_equity:,.0f}]", style="dim")
    content.append(
        " " * (chart_width - len(f"[{min_equity:,.0f}]") - len(f"[{max_equity:,.0f}]"))
    )
    content.append(f"[{max_equity:,.0f}]", style="dim")

    return Panel(content, title="📈 Equity Curve", border_style="cyan")


def create_files_panel() -> Panel:
    """Create workflow files panel."""
    signals_path, signals_exists = find_latest_file("*_signals.csv", "signals")
    report_path, report_exists = find_latest_file("*_report.md", "reports")
    perf_path = DEFAULT_PERF_PATH
    perf_exists = perf_path.exists()

    content = Text()
    signals_status = "✅" if signals_exists else "❌"
    report_status = "✅" if report_exists else "❌"
    perf_status = "✅" if perf_exists else "❌"

    content.append(f"Signals:  {signals_status} ", style="bold")
    content.append(f"{signals_path.name}\n", style="dim")
    content.append(f"Report:   {report_status} ", style="bold")
    content.append(f"{report_path.name}\n", style="dim")
    content.append(f"Perf CSV: {perf_status} ", style="bold")
    content.append(f"{perf_path.name}", style="dim")

    return Panel(content, title="📁 Files & Logs", border_style="cyan")


def analyze_why_no_trades(
    perf_df: pd.DataFrame, signals_df: pd.DataFrame, profile: Any
) -> Panel:
    """Analyze why trades aren't happening."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_df = (
        perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
        if "timestamp" in perf_df.columns and not perf_df.empty
        else pd.DataFrame()
    )

    # Count FLAT signals
    flat_count = 0
    long_count = 0
    short_count = 0

    if not today_df.empty:
        flat_count = len(today_df[today_df["side"].str.upper() == "FLAT"])
        long_count = len(today_df[today_df["side"].str.upper() == "LONG"])
        short_count = len(today_df[today_df["side"].str.upper() == "SHORT"])

    # Check risk state
    pnl_by_symbol = aggregate_pnl_by_symbol(today_df if not today_df.empty else perf_df)
    total_realized = pnl_by_symbol.get("TOTAL", {}).get("realized", 0.0)
    total_unrealized = pnl_by_symbol.get("TOTAL", {}).get("unrealized", 0.0)

    risk_state = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=total_realized,
        unrealized_pnl=total_unrealized,
        trades_today=len(today_df) if not today_df.empty else 0,
        max_trades=profile.max_trades,
        now=datetime.now(timezone.utc),
    )

    content = Text()

    if flat_count > 0:
        content.append("📊 Signal Analysis:\n", style="bold")
        content.append(f"  FLAT signals: {flat_count}\n", style="yellow")
        content.append(f"  LONG signals: {long_count}\n", style="green")
        content.append(f"  SHORT signals: {short_count}\n", style="red")
        content.append("\n", style="dim")
        content.append("💡 Why FLAT?\n", style="bold")
        content.append("  • Strategy filters too conservative\n", style="dim")
        content.append("  • No clear support/resistance levels\n", style="dim")
        content.append("  • Price not near key levels\n", style="dim")
        content.append("  • EMA filter blocking trades\n", style="dim")

    if risk_state.status != "OK":
        content.append("\n", style="dim")
        content.append(f"⚠️  Risk State: {risk_state.status}\n", style="bold yellow")
        if risk_state.status == "HARD_STOP":
            content.append("  Trading halted - daily loss limit reached\n", style="red")
        elif risk_state.status == "COOLDOWN":
            content.append(
                f"  Cooldown active until {risk_state.cooldown_until.strftime('%H:%M:%S') if risk_state.cooldown_until else 'N/A'}\n",
                style="yellow",
            )
        elif risk_state.status == "NEAR_LIMIT":
            content.append(
                "  Approaching risk limits - sizing reduced\n", style="yellow"
            )

    if not today_df.empty and today_df["filled_size"].fillna(0).sum() == 0:
        content.append("\n", style="dim")
        content.append("🚫 No Fills:\n", style="bold red")
        content.append("  • All signals are FLAT (no trade opportunity)\n", style="dim")
        content.append("  • Check strategy parameters\n", style="dim")
        content.append("  • Verify market data is current\n", style="dim")

    if content.plain == "":
        content.append("✅ System operating normally\n", style="green")
        content.append("Trades executing as expected", style="dim")

    return Panel(content, title="🔍 Trade Analysis", border_style="cyan")


def create_menu_panel() -> Panel:
    """Create interactive menu panel with common commands."""
    menu_text = Text()
    menu_text.append("📋 Quick Actions Menu\n\n", style="bold cyan")

    menu_items = [
        ("1", "Generate Signals", "pearlalgo signals --strategy sr --symbols ES NQ GC"),
        ("2", "Start Micro Trading", "bash scripts/start_micro.sh"),
        ("3", "Start Standard Trading", "bash scripts/start_standard.sh"),
        ("4", "Stop All Trading", "bash scripts/kill_my_processes.sh"),
        ("5", "Performance Analysis", "python scripts/analyze_performance.py"),
        ("6", "Test Broker Connection", "python scripts/test_broker_connection.py"),
        ("7", "Gateway Status", "pearlalgo gateway status"),
        ("8", "Gateway Start", "pearlalgo gateway start --wait"),
        ("9", "Gateway Restart", "pearlalgo gateway restart"),
        ("A", "View Latest Signals", "ls -lt signals/*.csv | head -1"),
        ("B", "View Latest Report", "ls -lt reports/*.md | head -1"),
        ("C", "View Trading Logs", "tail -f logs/micro_trading.log"),
        ("D", "System Health Check", "python scripts/system_health_check.py"),
        ("E", "Walk-Forward Test", "python scripts/walk_forward_test.py --help"),
        ("F", "Validate Backtest", "python scripts/validate_backtest.py --help"),
        ("Q", "Quit Dashboard", ""),
    ]

    for key, label, cmd in menu_items:
        menu_text.append(f"[bold yellow]{key}[/] ", style="bold")
        menu_text.append(f"{label:25s}", style="cyan")
        if cmd:
            menu_text.append(f"  [dim]{cmd[:50]}[/]", style="dim")
        menu_text.append("\n")

    menu_text.append(
        "\n[dim]Press number/letter to execute, or Ctrl+C to exit[/dim]", style="dim"
    )

    return Panel(menu_text, title="🎯 Quick Actions", border_style="cyan")


def create_dashboard(
    refresh_interval: int = 60,
    seconds_until_refresh: float = 60.0,
    show_menu: bool = False,
) -> Layout:
    """Create the unified dashboard layout."""
    layout = Layout()

    # Load data
    perf_path = DEFAULT_PERF_PATH
    perf_df = load_performance(perf_path)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    profile = load_profile()

    signals_path, _ = find_latest_file("*_signals.csv", "signals")
    signals_df = pd.read_csv(signals_path) if signals_path.exists() else pd.DataFrame()
    if not signals_df.empty and "timestamp" in signals_df.columns:
        signals_df["timestamp"] = pd.to_datetime(
            signals_df["timestamp"], errors="coerce"
        )

    processes = get_trading_processes()

    # Main layout
    layout.split_column(
        Layout(name="header", size=8),
        Layout(name="main"),
        Layout(name="footer", size=2),
    )

    layout["main"].split_row(
        Layout(name="left", ratio=1, minimum_size=50),
        Layout(name="center", ratio=2, minimum_size=60),
        Layout(name="right", ratio=1, minimum_size=50),
    )

    layout["left"].split_column(
        Layout(name="risk", size=20),
        Layout(name="stats", size=14),
        Layout(name="equity", size=12),
        Layout(name="files", size=6),
    )

    layout["center"].split_column(
        Layout(name="per_symbol", ratio=2), Layout(name="signals", ratio=1)
    )

    if show_menu:
        layout["right"].split_column(
            Layout(name="menu", size=20),
            Layout(name="reasoning", size=12),
            Layout(name="trades", size=10),
            Layout(name="analysis", size=8),
        )
    else:
        layout["right"].split_column(
            Layout(name="reasoning", size=16),
            Layout(name="trades", size=12),
            Layout(name="analysis", size=10),
        )

    # Populate panels
    layout["header"].update(
        create_header_panel(processes, refresh_interval, seconds_until_refresh)
    )
    layout["risk"].update(create_risk_summary_panel(perf_df, profile, today))
    layout["stats"].update(create_trade_stats_panel(perf_df, today))
    layout["equity"].update(create_equity_curve_panel(perf_df, profile, today))
    layout["files"].update(create_files_panel())
    layout["per_symbol"].update(
        Panel(
            create_per_symbol_table(perf_df, profile, today),
            title="📈 Per-Symbol Metrics",
            border_style="cyan",
        )
    )
    layout["signals"].update(
        Panel(
            create_signal_context_table(perf_df, signals_df),
            title="📋 Latest Signals",
            border_style="cyan",
        )
    )
    if show_menu:
        layout["menu"].update(create_menu_panel())
    layout["reasoning"].update(create_decision_reasoning_panel(perf_df, signals_df))
    layout["trades"].update(create_recent_trades_panel(perf_df))
    layout["analysis"].update(analyze_why_no_trades(perf_df, signals_df, profile))

    # Footer
    footer_text = Text(
        "Press Ctrl+C to exit | Refresh: " + str(refresh_interval) + "s",
        style="dim",
        justify="center",
    )
    layout["footer"].update(Panel(footer_text, border_style="dim"))

    return layout


def execute_menu_command(choice: str) -> bool:
    """Execute a menu command based on user choice. Returns True if should continue, False to quit."""
    import subprocess

    commands = {
        "1": {
            "cmd": [
                "pearlalgo",
                "signals",
                "--strategy",
                "sr",
                "--symbols",
                "ES",
                "NQ",
                "GC",
            ],
            "desc": "Generate signals for ES, NQ, GC",
        },
        "2": {
            "cmd": ["bash", "scripts/start_micro.sh"],
            "desc": "Start micro contracts trading",
        },
        "3": {
            "cmd": ["bash", "scripts/start_standard.sh"],
            "desc": "Start standard contracts trading",
        },
        "4": {
            "cmd": ["bash", "scripts/kill_my_processes.sh"],
            "desc": "Stop all trading processes",
        },
        "5": {
            "cmd": ["python", "scripts/analyze_performance.py", "--summary"],
            "desc": "Show performance summary",
        },
        "6": {
            "cmd": ["python", "scripts/test_broker_connection.py"],
            "desc": "Test IBKR broker connection",
        },
        "7": {
            "cmd": ["pearlalgo", "gateway", "status"],
            "desc": "Check IB Gateway status",
        },
        "8": {
            "cmd": ["pearlalgo", "gateway", "start", "--wait"],
            "desc": "Start IB Gateway",
        },
        "9": {
            "cmd": ["pearlalgo", "gateway", "restart"],
            "desc": "Restart IB Gateway",
        },
        "A": {
            "cmd": ["ls", "-lt", "signals/"],
            "desc": "List latest signals files",
        },
        "B": {
            "cmd": ["ls", "-lt", "reports/"],
            "desc": "List latest reports",
        },
        "C": {
            "cmd": ["tail", "-30", "logs/micro_trading.log"],
            "desc": "View recent trading logs",
        },
        "D": {
            "cmd": ["python", "scripts/system_health_check.py"],
            "desc": "Run system health check",
        },
        "E": {
            "cmd": ["python", "scripts/walk_forward_test.py", "--help"],
            "desc": "Show walk-forward test help",
        },
        "F": {
            "cmd": ["python", "scripts/validate_backtest.py", "--help"],
            "desc": "Show backtest validation help",
        },
        "Q": None,  # Quit
    }

    choice_upper = choice.upper()
    if choice_upper not in commands:
        console.print(f"[red]Invalid choice: {choice}[/red]")
        return True

    if choice_upper == "Q":
        return False

    cmd_info = commands[choice_upper]
    if not cmd_info:
        return False

    cmd = cmd_info["cmd"]
    desc = cmd_info.get("desc", "")

    console.print(f"[cyan]Executing: {desc}[/cyan]")
    console.print(f"[dim]{' '.join(cmd)}[/dim]\n")

    try:
        result = subprocess.run(cmd, cwd=SCRIPT_DIR, capture_output=False, text=True)
        if result.returncode == 0:
            console.print("\n[green]✓ Command completed successfully[/green]")
        else:
            console.print(
                f"\n[yellow]⚠ Command completed with exit code: {result.returncode}[/yellow]"
            )
    except FileNotFoundError:
        console.print(
            "[red]Error: Command not found. Make sure you're in the project directory.[/red]"
        )
    except Exception as e:
        console.print(f"[red]Error executing command: {e}[/red]")

    return True


def main() -> int:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="PearlAlgo Trading Dashboard")
    parser.add_argument("--live", action="store_true", help="Live updating dashboard")
    parser.add_argument(
        "--once", action="store_true", help="Show dashboard once and exit"
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=60,
        metavar="SECONDS",
        help="Refresh interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--menu", action="store_true", help="Show interactive menu (requires --once)"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive mode with menu and keyboard input",
    )
    args = parser.parse_args()

    refresh_interval = max(1, args.refresh)
    show_menu = args.menu or args.interactive

    if args.interactive:
        # Interactive mode with menu
        console.print("[bold cyan]📊 PearlAlgo Interactive Dashboard[/bold cyan]")
        console.print(
            "[dim]Enter number/letter to execute command, 'Q' to quit[/dim]\n"
        )

        try:
            while True:
                # Clear screen and show dashboard
                console.clear()
                console.print(
                    create_dashboard(refresh_interval, refresh_interval, show_menu=True)
                )
                console.print("\n" + "=" * 80 + "\n")
                console.print(
                    "[bold yellow]Enter command (1-9, A-F, Q to quit): [/bold yellow]",
                    end="",
                )

                choice = input().strip().upper()

                if not choice:
                    continue

                console.print(f"\n[cyan]Selected: {choice}[/cyan]\n")

                if not execute_menu_command(choice):
                    break

                console.print("\n[dim]Press Enter to return to dashboard...[/dim]")
                input()
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Dashboard closed[/bold yellow]\n")
    elif args.live or not args.once:
        # Live updating mode
        start_time = time.time()
        with Live(
            create_dashboard(refresh_interval, refresh_interval, show_menu=show_menu),
            refresh_per_second=2,
            screen=True,
        ) as live:
            try:
                while True:
                    elapsed = time.time() - start_time
                    seconds_until_refresh = refresh_interval - (
                        elapsed % refresh_interval
                    )
                    live.update(
                        create_dashboard(
                            refresh_interval, seconds_until_refresh, show_menu=show_menu
                        )
                    )
                    time.sleep(0.5)
            except KeyboardInterrupt:
                console.print("\n[bold yellow]Dashboard closed[/bold yellow]\n")
    else:
        # Show once
        console.print(
            create_dashboard(refresh_interval, refresh_interval, show_menu=show_menu)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
