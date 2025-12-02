#!/usr/bin/env python
from __future__ import annotations

"""
🎯 PearlAlgo Futures Desk — Quant-Grade Trading Dashboard
Professional terminal dashboard with advanced risk metrics, performance analytics,
and technical signal context for futures traders.
"""

import ast
import re
import sys
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

# Add project root to path (for editable install)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
# Ensure we're in project root and it's in path
import os
original_cwd = os.getcwd()
try:
    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    # Remove any conflicting pearlalgo modules from cache (but keep submodules)
    modules_to_remove = [k for k in list(sys.modules.keys()) if k == 'pearlalgo']
    for mod in modules_to_remove:
        del sys.modules[mod]
except Exception:
    pass  # If chdir fails, continue anyway

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich import box
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn
from rich.align import Align

from pearlalgo.futures.config import load_profile
from pearlalgo.futures.performance import DEFAULT_PERF_PATH, load_performance, summarize_daily_performance
from pearlalgo.futures.risk import compute_risk_state, RiskState

console = Console()

# Try to import pytz for timezone conversion, fallback to manual calculation
try:
    import pytz
    US_EASTERN = pytz.timezone('US/Eastern')
except ImportError:
    US_EASTERN = None

# Micro contract symbols
MICRO_SYMBOLS = {"MGC", "MYM", "MCL", "MNQ", "MES", "M2K", "M6E", "M6B", "M6A", "M6J"}
MINI_SYMBOLS = {"ES", "NQ", "GC", "YM", "CL", "NG", "ZB", "ZN", "ZF", "ZT"}


def run_cmd(cmd: list[str]) -> str:
    """Run command and return output."""
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=5).strip()
    except Exception as exc:
        return f"ERROR: {exc}"


def get_us_eastern_time(utc_time: datetime) -> str:
    """Convert UTC time to US/Eastern timezone string."""
    if US_EASTERN:
        try:
            eastern_time = utc_time.astimezone(US_EASTERN)
            return eastern_time.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception:
            pass
    # Fallback: manual offset (EST = UTC-5, EDT = UTC-4)
    # Simple approximation: assume EDT (UTC-4) for now
    offset_hours = -4
    eastern_time = utc_time.replace(tzinfo=timezone.utc) + pd.Timedelta(hours=offset_hours)
    return eastern_time.strftime('%Y-%m-%d %H:%M:%S EST')


def get_trading_processes() -> list[dict[str, Any]]:
    """Get list of running trading processes with details."""
    processes = []
    try:
        result = subprocess.run(
            ["pgrep", "-af", "pearlalgo trade"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line and "pearlalgo trade" in line:
                    parts = line.split(" ", 1)
                    if len(parts) >= 2:
                        pid = parts[0]
                        cmd = parts[1]
                        # Extract symbols and strategy from command
                        symbols = []
                        strategy = "unknown"
                        contract_type = "unknown"
                        
                        # Check for micro symbols
                        for sym in MICRO_SYMBOLS:
                            if sym in cmd:
                                symbols.append(sym)
                                contract_type = "micro"
                        # Check for mini/standard symbols
                        if contract_type == "unknown":
                            for sym in MINI_SYMBOLS:
                                if sym in cmd:
                                    symbols.append(sym)
                                    contract_type = "mini"
                        
                        # Extract strategy
                        if "--strategy" in cmd:
                            match = re.search(r"--strategy\s+(\w+)", cmd)
                            if match:
                                strategy = match.group(1)
                        
                        processes.append({
                            "pid": pid,
                            "command": cmd[:80] + "..." if len(cmd) > 80 else cmd,
                            "symbols": symbols,
                            "strategy": strategy,
                            "contract_type": contract_type,
                        })
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
    # Check if process is running
    result = subprocess.run(["pgrep", "-f", "IbcGateway"], capture_output=True)
    is_running = result.returncode == 0
    pid = result.stdout.decode().strip() if is_running else None
    
    # Check if port is listening
    result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
    port_listening = "4002" in result.stdout
    
    # Get version from logs
    version = ""
    try:
        log_tail = run_cmd(["journalctl", "-q", "-u", "ibgateway.service", "-n", "50", "--no-pager"])
        for line in log_tail.splitlines():
            if "Running GATEWAY" in line or "IB Gateway" in line or "version" in line.lower():
                version = line.strip()[:100]
                break
        # Also try to get from process info
        if not version and pid:
            try:
                ps_result = run_cmd(["ps", "-p", pid, "-o", "args="])
                if "gateway" in ps_result.lower():
                    # Extract version if visible
                    match = re.search(r'(\d+\.\d+\.\d+)', ps_result)
                    if match:
                        version = f"IB Gateway {match.group(1)}"
            except Exception:
                pass
    except Exception:
        pass
    
    status = "✅ Running" if (is_running and port_listening) else "❌ Not Running"
    return status, version, is_running and port_listening


def compute_sharpe_ratio(perf_df: pd.DataFrame, risk_free_rate: float = 0.0) -> float:
    """
    Compute Sharpe ratio from P&L returns.
    
    Sharpe = (Mean Return - Risk Free Rate) / Std Dev of Returns
    
    Args:
        perf_df: Performance dataframe with realized_pnl column
        risk_free_rate: Risk-free rate (default 0.0 for intraday)
    
    Returns:
        Sharpe ratio, or 0.0 if insufficient data
    """
    if perf_df.empty or "realized_pnl" not in perf_df.columns:
        return 0.0
    
    # Get realized P&L, filter out NaN
    pnl = perf_df["realized_pnl"].dropna()
    if len(pnl) < 2:
        return 0.0
    
    # Convert to returns (assuming each row is a period)
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
    """
    Compute Sortino ratio from P&L returns (downside deviation only).
    
    Sortino = (Mean Return - Risk Free Rate) / Downside Deviation
    
    Args:
        perf_df: Performance dataframe with realized_pnl column
        risk_free_rate: Risk-free rate (default 0.0 for intraday)
    
    Returns:
        Sortino ratio, or 0.0 if insufficient data
    """
    if perf_df.empty or "realized_pnl" not in perf_df.columns:
        return 0.0
    
    # Get realized P&L, filter out NaN
    pnl = perf_df["realized_pnl"].dropna()
    if len(pnl) < 2:
        return 0.0
    
    # Convert to returns
    returns = pnl.diff().dropna()
    if len(returns) < 2:
        return 0.0
    
    mean_return = returns.mean()
    
    # Downside deviation: only negative returns
    downside_returns = returns[returns < 0]
    if len(downside_returns) == 0:
        # No downside, return high ratio if positive mean
        return 10.0 if mean_return > 0 else 0.0
    
    downside_std = downside_returns.std()
    if downside_std == 0 or pd.isna(downside_std):
        return 0.0
    
    sortino = (mean_return - risk_free_rate) / downside_std
    return float(sortino) if not pd.isna(sortino) else 0.0


def compute_trade_statistics(perf_df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute comprehensive trade statistics.
    
    Returns:
        Dictionary with trade counts, win rate, hold times, largest winner/loser, etc.
    """
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
    
    # Get completed trades (have both entry and exit)
    completed_trades = perf_df.dropna(subset=["entry_time", "exit_time", "realized_pnl"])
    
    if completed_trades.empty:
        # Fallback: use all rows with realized_pnl
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
    
    # Average hold time
    avg_hold_time = 0.0
    if "entry_time" in completed_trades.columns and "exit_time" in completed_trades.columns:
        durations = (completed_trades["exit_time"] - completed_trades["entry_time"]).dt.total_seconds() / 60.0
        durations = durations.dropna()
        if len(durations) > 0:
            avg_hold_time = float(durations.mean())
    
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
    """
    Aggregate realized and unrealized P&L by symbol.
    
    Returns:
        Dictionary mapping symbol to {'realized': float, 'unrealized': float}
        Also includes 'TOTAL' key with grand totals
    """
    result: dict[str, dict[str, float]] = {}
    
    if perf_df.empty:
        return {"TOTAL": {"realized": 0.0, "unrealized": 0.0}}
    
    # Group by symbol
    if "symbol" not in perf_df.columns:
        return {"TOTAL": {"realized": 0.0, "unrealized": 0.0}}
    
    for symbol in perf_df["symbol"].unique():
        if pd.isna(symbol):
            continue
        sym_df = perf_df[perf_df["symbol"] == symbol]
        
        # Realized P&L: sum all values
        realized = sym_df["realized_pnl"].fillna(0.0).sum() if "realized_pnl" in sym_df.columns else 0.0
        
        # Unrealized P&L: use last non-null value per symbol (current position)
        unrealized = 0.0
        if "unrealized_pnl" in sym_df.columns:
            unrealized_vals = sym_df["unrealized_pnl"].dropna()
            if len(unrealized_vals) > 0:
                unrealized = float(unrealized_vals.iloc[-1])
        
        result[str(symbol)] = {
            "realized": float(realized),
            "unrealized": float(unrealized),
        }
    
    # Compute totals
    total_realized = sum(v["realized"] for v in result.values())
    total_unrealized = sum(v["unrealized"] for v in result.values())
    result["TOTAL"] = {"realized": total_realized, "unrealized": total_unrealized}
    
    return result


def parse_sr_dict_from_notes(notes: str) -> dict[str, Any]:
    """Parse SR dictionary from notes field."""
    if not notes or pd.isna(notes):
        return {}
    
    try:
        # Look for dict-like pattern: sr={'key': value, ...}
        match = re.search(r"sr\s*=\s*\{([^}]+)\}", str(notes))
        if match:
            dict_str = "{" + match.group(1) + "}"
            # Replace np.float64(...) with just the number
            dict_str = re.sub(r'np\.float64\(([^)]+)\)', r'\1', dict_str)
            # Try to evaluate as dict
            parsed = ast.literal_eval(dict_str)
            if isinstance(parsed, dict):
                # Convert numpy types to Python types
                result = {}
                for k, v in parsed.items():
                    if hasattr(v, 'item'):  # numpy scalar
                        result[k] = v.item()
                    else:
                        result[k] = v
                return result
    except Exception:
        pass
    
    return {}


def extract_signal_context(perf_df: pd.DataFrame, signals_df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract technical analysis context from performance CSV notes and merge with signals.
    
    Returns:
        DataFrame with signal context: symbol, strategy, direction, entry, stop, target, VWAP, pivots, trade_reason
    """
    if perf_df.empty:
        return pd.DataFrame()
    
    # Get latest signals per symbol (last 2-3)
    context_rows = []
    
    for symbol in perf_df["symbol"].unique():
        if pd.isna(symbol):
            continue
        
        sym_perf = perf_df[perf_df["symbol"] == symbol].sort_values("timestamp", ascending=False)
        sym_signals = signals_df[signals_df["symbol"] == symbol].sort_values("timestamp", ascending=False) if not signals_df.empty else pd.DataFrame()
        
        # Get last 3 signals
        for idx, row in sym_perf.head(3).iterrows():
            # Parse notes for SR dict
            notes = row.get("notes", "")
            sr_dict = parse_sr_dict_from_notes(notes)
            
            # Get matching signal if available
            signal_row = None
            if not sym_signals.empty:
                # Find signal closest in time
                perf_time = row.get("timestamp")
                if pd.notna(perf_time):
                    time_diffs = abs((sym_signals["timestamp"] - perf_time).dt.total_seconds())
                    if len(time_diffs) > 0:
                        closest_idx = time_diffs.idxmin()
                        if time_diffs[closest_idx] < 300:  # Within 5 minutes
                            signal_row = sym_signals.loc[closest_idx]
            
            context_row = {
                "symbol": str(symbol),
                "strategy": row.get("strategy_name", "unknown"),
                "direction": signal_row.get("direction", row.get("side", "FLAT")).upper() if signal_row is not None else row.get("side", "FLAT").upper(),
                "entry_price": row.get("entry_price"),
                "stop_price": None,  # Would need to parse from signal or compute
                "target_price": None,  # Would need to parse from signal or compute
                "vwap": sr_dict.get("vwap"),
                "support1": sr_dict.get("support1"),
                "resistance1": sr_dict.get("resistance1"),
                "pivot_levels": f"S1: {sr_dict.get('support1', 'N/A')}, R1: {sr_dict.get('resistance1', 'N/A')}" if sr_dict else "N/A",
                "trade_reason": row.get("trade_reason") or (", ".join([k for k, v in sr_dict.items() if v is not None]) if sr_dict else None),
                "confidence": None,  # Not in current data structure
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
    
    matches = sorted(dir_path.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    if matches:
        return matches[0], True
    return Path(directory) / pattern, False


def create_refresh_indicator(seconds_until_refresh: float, refresh_interval: int) -> Panel:
    """Create refresh indicator with countdown and progress bar."""
    progress = (refresh_interval - seconds_until_refresh) / refresh_interval
    progress_pct = int(progress * 100)
    seconds_left = int(seconds_until_refresh)
    
    # Create progress bar
    progress_bar = Progress(
        BarColumn(bar_width=40, style="cyan", complete_style="green", finished_style="bold green"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TextColumn("[dim]{task.description}[/dim]"),
        console=console,
    )
    
    with progress_bar:
        task = progress_bar.add_task(
            f"Next refresh in {seconds_left}s",
            total=refresh_interval,
            completed=refresh_interval - seconds_until_refresh
        )
    
    # Create text version for layout
    bar_length = 40
    filled = int(bar_length * progress)
    bar = "█" * filled + "░" * (bar_length - filled)
    
    content = Text()
    content.append("🔄 ", style="bold cyan")
    content.append(f"Refreshing in {seconds_left:2d}s ", style="bold")
    content.append(f"[{progress_pct:3d}%] ", style="dim")
    content.append(bar, style="green" if progress > 0.8 else "yellow" if progress > 0.5 else "cyan")
    
    return Panel(content, border_style="cyan", box=box.ROUNDED)


def create_header_panel(processes: list[dict[str, Any]]) -> Panel:
    """Create header panel with system name, timestamps, gateway status, and trading info."""
    now_utc = datetime.now(timezone.utc)
    now_eastern = get_us_eastern_time(now_utc)
    
    status, version, is_ready = gateway_status()
    
    content = Text()
    content.append("🎯 PearlAlgo Futures Desk — Quant-Grade Trading Dashboard\n", style="bold cyan")
    content.append(f"UTC:   {now_utc.strftime('%Y-%m-%d %H:%M:%S')}\n", style="dim")
    content.append(f"ET:    {now_eastern}\n", style="dim")
    content.append(f"\nGateway: {status}", style="bold green" if is_ready else "bold red")
    if version:
        content.append(f"\n{version[:80]}", style="dim")
    
    # Add trading process info
    if processes:
        content.append("\n\n", style="dim")
        content.append("🤖 Active Trading Processes:\n", style="bold yellow")
        all_symbols = []
        all_strategies = set()
        contract_types = set()
        
        for proc in processes:
            all_symbols.extend(proc.get("symbols", []))
            all_strategies.add(proc.get("strategy", "unknown"))
            contract_types.add(proc.get("contract_type", "unknown"))
        
        if all_symbols:
            contract_type_str = detect_contract_type(all_symbols)
            if contract_type_str == "mixed":
                content.append("Contract Type: ", style="dim")
                content.append("Mixed (Micro + Mini)\n", style="bold yellow")
            elif contract_type_str == "micro":
                content.append("Contract Type: ", style="dim")
                content.append("Micro Contracts\n", style="bold cyan")
            elif contract_type_str == "mini":
                content.append("Contract Type: ", style="dim")
                content.append("Mini/Standard Contracts\n", style="bold green")
            
            content.append("Symbols: ", style="dim")
            content.append(", ".join(sorted(set(all_symbols))), style="yellow")
            content.append("\n", style="dim")
            
            if all_strategies:
                content.append("Strategies: ", style="dim")
                content.append(", ".join(sorted(all_strategies)), style="cyan")
                content.append("\n", style="dim")
    else:
        content.append("\n\n", style="dim")
        content.append("⚠️  No active trading processes", style="bold yellow")
    
    return Panel(content, border_style="cyan", box=box.DOUBLE)


def create_risk_summary_panel(perf_df: pd.DataFrame, profile: Any, today: str) -> Panel:
    """Create comprehensive risk summary panel."""
    today_df = perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in perf_df.columns and not perf_df.empty else pd.DataFrame()
    trades_today = len(today_df) if not today_df.empty else 0
    
    # Aggregate P&L
    pnl_by_symbol = aggregate_pnl_by_symbol(today_df if not today_df.empty else perf_df)
    total_realized = pnl_by_symbol.get("TOTAL", {}).get("realized", 0.0)
    total_unrealized = pnl_by_symbol.get("TOTAL", {}).get("unrealized", 0.0)
    
    # Compute risk state
    risk_state = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=total_realized,
        unrealized_pnl=total_unrealized,
        trades_today=trades_today,
        max_trades=profile.max_trades,
        now=datetime.now(timezone.utc),
    )
    
    # Compute drawdown percentage
    drawdown_pct = 0.0
    if risk_state.daily_loss_limit > 0:
        drawdown_pct = ((risk_state.daily_loss_limit - risk_state.remaining_loss_buffer) / risk_state.daily_loss_limit) * 100.0
    
    # Determine risk state indicator
    if drawdown_pct < 50:
        risk_indicator = "✅ OK"
        risk_color = "green"
    elif drawdown_pct < 80:
        risk_indicator = "⚠️  NEAR_LIMIT"
        risk_color = "yellow"
    else:
        risk_indicator = "❌ HARD_STOP"
        risk_color = "red"
    
    # Compute Sharpe and Sortino
    sharpe = compute_sharpe_ratio(today_df if not today_df.empty else perf_df)
    sortino = compute_sortino_ratio(today_df if not today_df.empty else perf_df)
    
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Metric", style="cyan", width=20)
    table.add_column("Value", style="white", width=18)
    
    table.add_row("Risk State:", f"[bold {risk_color}]{risk_indicator} ({risk_state.status})[/]")
    table.add_row("", "")  # Spacer
    table.add_row("Remaining Drawdown:", f"${risk_state.remaining_loss_buffer:,.2f}")
    table.add_row("Daily Loss Limit:", f"${risk_state.daily_loss_limit:,.2f}")
    table.add_row("Drawdown Used:", f"{drawdown_pct:.1f}%")
    table.add_row("", "")  # Spacer
    table.add_row("Sharpe Ratio:", f"{sharpe:.2f}")
    table.add_row("Sortino Ratio:", f"{sortino:.2f}")
    table.add_row("", "")  # Spacer
    total_pnl = total_realized + total_unrealized
    pnl_color = "green" if total_pnl >= 0 else "red"
    table.add_row("Total Realized P&L:", f"[{pnl_color}]${total_realized:,.2f}[/]")
    table.add_row("Total Unrealized P&L:", f"[{pnl_color}]${total_unrealized:,.2f}[/]")
    table.add_row("Total P&L:", f"[bold {pnl_color}]${total_pnl:,.2f}[/]")
    
    return Panel(table, title="⚠️  Risk Summary", border_style=risk_color)


def create_per_symbol_table(perf_df: pd.DataFrame, profile: Any, today: str) -> Table:
    """Create per-symbol metrics table."""
    today_df = perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in perf_df.columns and not perf_df.empty else pd.DataFrame()
    
    # Get latest signals
    signals_path, _ = find_latest_file("*_signals.csv", "signals")
    signals_df = pd.read_csv(signals_path) if signals_path.exists() else pd.DataFrame()
    if not signals_df.empty and "timestamp" in signals_df.columns:
        signals_df["timestamp"] = pd.to_datetime(signals_df["timestamp"], errors="coerce")
    
    table = Table(show_header=True, box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Symbol", style="yellow", width=8, justify="center")
    table.add_column("Contract", width=10, justify="center")
    table.add_column("Last Signal", width=10, justify="center")
    table.add_column("Side", justify="center", width=8)
    table.add_column("Realized P&L", justify="right", width=14)
    table.add_column("Unrealized P&L", justify="right", width=16)
    table.add_column("Risk", justify="center", width=6)
    table.add_column("Position", justify="right", width=8)
    table.add_column("Trades", justify="right", width=7)
    table.add_column("Max", justify="right", width=6)
    
    # Aggregate by symbol
    pnl_by_symbol = aggregate_pnl_by_symbol(today_df if not today_df.empty else perf_df)
    
    symbols = sorted(set(perf_df["symbol"].dropna().unique()) if not perf_df.empty else [])
    if not symbols:
        table.add_row("[dim]No data[/dim]", "", "", "", "", "", "", "", "", "")
        return table
    
    for symbol in symbols:
        sym_perf = perf_df[perf_df["symbol"] == symbol]
        sym_today = today_df[today_df["symbol"] == symbol] if not today_df.empty else pd.DataFrame()
        
        # Get latest signal
        last_signal_time = "N/A"
        last_signal_side = "FLAT"
        if not sym_today.empty:
            last_row = sym_today.sort_values("timestamp", ascending=False).iloc[0]
            last_signal_time = last_row["timestamp"].strftime("%H:%M:%S") if pd.notna(last_row.get("timestamp")) else "N/A"
            last_signal_side = last_row.get("side", "FLAT").upper()
        elif not signals_df.empty:
            sym_signals = signals_df[signals_df["symbol"] == symbol]
            if not sym_signals.empty:
                last_sig = sym_signals.sort_values("timestamp", ascending=False).iloc[0]
                last_signal_time = last_sig["timestamp"].strftime("%H:%M:%S") if pd.notna(last_sig.get("timestamp")) else "N/A"
                last_signal_side = last_sig.get("direction", "FLAT").upper()
        
        # P&L
        realized = pnl_by_symbol.get(str(symbol), {}).get("realized", 0.0)
        unrealized = pnl_by_symbol.get(str(symbol), {}).get("unrealized", 0.0)
        realized_color = "green" if realized >= 0 else "red"
        unrealized_color = "green" if unrealized >= 0 else "red"
        
        # Risk state (simplified per symbol)
        risk_indicator = "✅"
        
        # Position size (from latest filled_size or requested_size)
        position_size = 0
        if not sym_today.empty:
            last_filled = sym_today["filled_size"].dropna()
            if len(last_filled) > 0:
                position_size = int(last_filled.iloc[-1])
        
        # Trades today
        trades_count = len(sym_today) if not sym_today.empty else 0
        
        # Max contracts
        max_contracts = profile.max_contracts_by_symbol.get(str(symbol).upper(), 0)
        
        # Contract month (not in current data, show N/A)
        contract_month = "N/A"
        
            table.add_row(
            str(symbol),
            contract_month,
            last_signal_time,
            f"[bold green]{last_signal_side}[/]" if last_signal_side in ["LONG", "BUY"] else f"[bold red]{last_signal_side}[/]" if last_signal_side in ["SHORT", "SELL"] else f"[dim]{last_signal_side}[/]",
            f"[{realized_color}]${realized:,.2f}[/]",
            f"[{unrealized_color}]${unrealized:,.2f}[/]",
            risk_indicator,
            str(position_size),
            str(trades_count),
            str(max_contracts),
        )
    
    return table


def create_signal_context_table(perf_df: pd.DataFrame, signals_df: pd.DataFrame) -> Table:
    """Create latest signal context table with technical analysis."""
    context_df = extract_signal_context(perf_df, signals_df)
    
    table = Table(show_header=True, box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Symbol", style="yellow", width=8, justify="center")
    table.add_column("Strategy", width=10, justify="center")
    table.add_column("Direction", justify="center", width=8)
    table.add_column("Entry", justify="right", width=10)
    table.add_column("Stop", justify="right", width=10)
    table.add_column("Target", justify="right", width=10)
    table.add_column("VWAP", justify="right", width=10)
    table.add_column("Pivots", width=20)
    table.add_column("Reason", width=25)
    
    if context_df.empty:
        table.add_row("[dim]No signal context available[/dim]", "", "", "", "", "", "", "", "")
        return table
    
    for _, row in context_df.head(10).iterrows():  # Show up to 10 signals
        direction = row.get("direction", "FLAT")
        dir_color = "green" if direction in ["LONG", "BUY"] else "red" if direction in ["SHORT", "SELL"] else "dim"
        
        entry = f"{row.get('entry_price', 0):.2f}" if pd.notna(row.get("entry_price")) else "N/A"
        stop = f"{row.get('stop_price', 0):.2f}" if pd.notna(row.get("stop_price")) else "N/A"
        target = f"{row.get('target_price', 0):.2f}" if pd.notna(row.get("target_price")) else "N/A"
        vwap = f"{row.get('vwap', 0):.2f}" if pd.notna(row.get("vwap")) else "N/A"
        pivots = str(row.get("pivot_levels", "N/A"))[:20]
        reason = str(row.get("trade_reason", "N/A"))[:25] if pd.notna(row.get("trade_reason")) else "N/A"
        
        table.add_row(
            str(row.get("symbol", "N/A")),
            str(row.get("strategy", "N/A")),
            f"[{dir_color}]{direction}[/]",
            entry,
            stop,
            target,
            vwap,
            pivots,
            reason,
        )
    
    return table


def create_trade_stats_panel(perf_df: pd.DataFrame, today: str) -> Panel:
    """Create trade statistics panel."""
    today_df = perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in perf_df.columns and not perf_df.empty else pd.DataFrame()
    
    stats = compute_trade_statistics(today_df if not today_df.empty else perf_df)
    
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Metric", style="cyan", width=18)
    table.add_column("Value", style="white", width=20)
    
    table.add_row("Total Trades:", f"{stats['total_trades']}")
    table.add_row("Winners:", f"[green]{stats['winners']}[/] ({stats['win_rate']:.1f}%)")
    table.add_row("Losers:", f"[red]{stats['losers']}[/] ({100 - stats['win_rate']:.1f}%)")
    table.add_row("", "")  # Spacer
    table.add_row("Avg Hold Time:", f"{stats['avg_hold_time_minutes']:.1f} min")
    table.add_row("Largest Winner:", f"[green]${stats['largest_winner']:,.2f}[/]")
    table.add_row("Largest Loser:", f"[red]${stats['largest_loser']:,.2f}[/]")
    table.add_row("Avg P&L/Trade:", f"${stats['avg_pnl_per_trade']:,.2f}")
    
    return Panel(table, title="📊 Trade Statistics", border_style="cyan")


def create_files_panel() -> Panel:
    """Create workflow files panel with full paths."""
    signals_path, signals_exists = find_latest_file("*_signals.csv", "signals")
    report_path, report_exists = find_latest_file("*_report.md", "reports")
    perf_path = DEFAULT_PERF_PATH
    perf_exists = perf_path.exists()
    
    content = Text()
    signals_status = "✅" if signals_exists else "❌"
    report_status = "✅" if report_exists else "❌"
    perf_status = "✅" if perf_exists else "❌"
    
    content.append(f"Signals:  {signals_status} ", style="bold")
    content.append(f"{signals_path}\n", style="dim")
    content.append(f"Report:   {report_status} ", style="bold")
    content.append(f"{report_path}\n", style="dim")
    content.append(f"Perf CSV: {perf_status} ", style="bold")
    content.append(f"{perf_path}", style="dim")
    
    return Panel(content, title="📁 Files & Logs", border_style="cyan")


def create_dashboard(refresh_interval: int = 60, seconds_until_refresh: float = 60.0) -> Layout:
    """Create the main quant-grade dashboard layout."""
    layout = Layout()
    
    # Load data
    perf_path = DEFAULT_PERF_PATH
    perf_df = load_performance(perf_path)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    profile = load_profile()
    
    # Load signals
    signals_path, _ = find_latest_file("*_signals.csv", "signals")
    signals_df = pd.read_csv(signals_path) if signals_path.exists() else pd.DataFrame()
    if not signals_df.empty and "timestamp" in signals_df.columns:
        signals_df["timestamp"] = pd.to_datetime(signals_df["timestamp"], errors="coerce")
    
    # Get trading processes
    processes = get_trading_processes()
    
    # Main layout structure
    layout.split_column(
        Layout(name="refresh", size=3),
        Layout(name="header", size=10),
        Layout(name="main"),
        Layout(name="footer", size=3)
    )
    
    layout["main"].split_row(
        Layout(name="left", ratio=1, minimum_size=50),
        Layout(name="right", ratio=1, minimum_size=50)
    )
    
    layout["left"].split_column(
        Layout(name="risk", size=18),
        Layout(name="per_symbol", ratio=2),
        Layout(name="files", size=8)
    )
    
    layout["right"].split_column(
        Layout(name="signals", ratio=2),
        Layout(name="stats", size=12)
    )
    
    # Populate panels
    layout["refresh"].update(create_refresh_indicator(seconds_until_refresh, refresh_interval))
    layout["header"].update(create_header_panel(processes))
    layout["risk"].update(create_risk_summary_panel(perf_df, profile, today))
    layout["per_symbol"].update(Panel(create_per_symbol_table(perf_df, profile, today), title="📈 Per-Symbol Metrics", border_style="cyan"))
    layout["signals"].update(Panel(create_signal_context_table(perf_df, signals_df), title="📋 Latest Signal Context", border_style="cyan"))
    layout["stats"].update(create_trade_stats_panel(perf_df, today))
    layout["files"].update(create_files_panel())
    
    # Footer
    footer_text = Text("Press Ctrl+C to exit | Refresh interval: " + str(refresh_interval) + "s", style="dim", justify="center")
    layout["footer"].update(Panel(footer_text, border_style="dim"))
    
    return layout


def main() -> int:
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(
        description="PearlAlgo Futures Desk — Quant-Grade Trading Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/status_dashboard.py              # Show once and exit
  python scripts/status_dashboard.py --live      # Live updating (60s default)
  python scripts/status_dashboard.py --live --refresh 30  # 30 second refresh
        """
    )
    parser.add_argument("--live", action="store_true", help="Live updating dashboard")
    parser.add_argument("--once", action="store_true", help="Show dashboard once and exit")
    parser.add_argument("--refresh", type=int, default=60, metavar="SECONDS",
                       help="Refresh interval in seconds (default: 60)")
    args = parser.parse_args()
    
    refresh_interval = max(1, args.refresh)  # Ensure at least 1 second
    
    if args.live or not args.once:
        # Live updating dashboard
        start_time = time.time()
        with Live(create_dashboard(refresh_interval, refresh_interval), refresh_per_second=2, screen=True) as live:
            try:
                while True:
                    elapsed = time.time() - start_time
                    seconds_until_refresh = refresh_interval - (elapsed % refresh_interval)
                    live.update(create_dashboard(refresh_interval, seconds_until_refresh))
                    time.sleep(0.5)  # Update every 0.5 seconds for smooth countdown
            except KeyboardInterrupt:
                console.print("\n[bold yellow]Dashboard closed[/bold yellow]\n")
    else:
        # Show once
        console.print(create_dashboard(refresh_interval, refresh_interval))
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
