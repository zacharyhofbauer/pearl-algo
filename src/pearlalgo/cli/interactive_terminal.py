"""
Interactive Python SDK-style Trading Terminal
A programmatic, interactive terminal for trading operations.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import pandas as pd

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.prompt import Prompt

from pearlalgo.futures.performance import load_performance, DEFAULT_PERF_PATH
from pearlalgo.futures.config import load_profile
from pearlalgo.futures.risk import compute_risk_state
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.core.portfolio import Portfolio

console = Console()


class TradingSDK:
    """
    Python SDK-style trading interface.
    Use this programmatically or interactively.
    """

    def __init__(self):
        self.console = Console()
        self.portfolio: Optional[Portfolio] = None
        self.broker: Optional[IBKRBroker] = None

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions."""
        positions_dict: Dict[str, Dict[str, Any]] = {}
        perf_path = DEFAULT_PERF_PATH

        if perf_path.exists():
            try:
                perf_df = load_performance(perf_path)
                if perf_df.empty or "timestamp" not in perf_df.columns:
                    return []

                if perf_df["timestamp"].dtype == "object":
                    perf_df["timestamp"] = pd.to_datetime(
                        perf_df["timestamp"], errors="coerce"
                    )

                today = datetime.now(timezone.utc).strftime("%Y%m%d")
                today_df = (
                    perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
                    if not perf_df.empty
                    else pd.DataFrame()
                )

                if "exit_time" not in today_df.columns:
                    return []

                open_trades = today_df[
                    today_df["exit_time"].isna() | (today_df["exit_time"] == "")
                ]

                for _, row in open_trades.iterrows():
                    symbol = str(row.get("symbol", ""))
                    if not symbol:
                        continue

                    side = str(row.get("side", "")).upper()
                    size = abs(float(row.get("filled_size", 0) or 0))
                    entry = float(row.get("entry_price", 0) or 0)
                    unrealized = float(row.get("unrealized_pnl", 0) or 0)
                    strategy = str(row.get("strategy_name", "unknown"))

                    if size > 0 and entry > 0:
                        key = f"{symbol}_{side}"
                        if key in positions_dict:
                            existing = positions_dict[key]
                            existing["size"] += size
                            existing["pnl"] += unrealized
                            total_size = existing["size"]
                            existing["entry"] = (
                                (
                                    (existing["entry"] * (total_size - size))
                                    + (entry * size)
                                )
                                / total_size
                                if total_size > 0
                                else entry
                            )
                            existing["pnl_pct"] = (
                                (
                                    existing["pnl"]
                                    / (existing["entry"] * existing["size"])
                                    * 100
                                )
                                if existing["entry"] * existing["size"] > 0
                                else 0
                            )
                            strategies = existing.get("_strategies", set())
                            strategies.add(strategy)
                            existing["_strategies"] = strategies
                            unique_strategies = list(strategies)
                            existing["strategy"] = (
                                unique_strategies[0]
                                if len(unique_strategies) == 1
                                else f"{unique_strategies[0]}, +{len(unique_strategies) - 1}"
                            )
                        else:
                            positions_dict[key] = {
                                "symbol": symbol,
                                "side": side,
                                "size": size,
                                "entry": entry,
                                "mark": entry,
                                "pnl": unrealized,
                                "pnl_pct": (unrealized / (entry * size) * 100)
                                if entry * size > 0
                                else 0,
                                "strategy": strategy,
                                "_strategies": {strategy}
                                if strategy != "unknown"
                                else set(),
                            }
            except Exception as e:
                self.console.print(f"[red]Error loading positions: {e}[/red]")
                return []

        return list(positions_dict.values())

    def get_performance(self) -> Dict[str, Any]:
        """Get performance metrics."""
        perf_path = DEFAULT_PERF_PATH
        today = datetime.now(timezone.utc).strftime("%Y%m%d")

        try:
            perf_df = load_performance(perf_path)
            if perf_df.empty or "timestamp" not in perf_df.columns:
                return {"error": "No data"}

            if perf_df["timestamp"].dtype == "object":
                perf_df["timestamp"] = pd.to_datetime(
                    perf_df["timestamp"], errors="coerce"
                )

            today_df = (
                perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
                if not perf_df.empty
                else pd.DataFrame()
            )

            profile = load_profile()
            realized_pnl = (
                today_df["realized_pnl"].fillna(0).sum()
                if not today_df.empty and "realized_pnl" in today_df.columns
                else 0.0
            )
            unrealized_pnl = (
                today_df["unrealized_pnl"].fillna(0).sum()
                if not today_df.empty and "unrealized_pnl" in today_df.columns
                else 0.0
            )
            total_pnl = realized_pnl + unrealized_pnl

            trades_today = len(today_df) if not today_df.empty else 0
            winning_trades = (
                len(today_df[today_df["realized_pnl"] > 0])
                if not today_df.empty and "realized_pnl" in today_df.columns
                else 0
            )
            win_rate = (
                (winning_trades / trades_today * 100) if trades_today > 0 else 0.0
            )

            risk_state = compute_risk_state(
                profile,
                day_start_equity=profile.starting_balance,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                trades_today=trades_today,
                max_trades=profile.max_trades,
                now=datetime.now(timezone.utc),
            )

            return {
                "daily_pnl": total_pnl,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "trades_today": trades_today,
                "win_rate": win_rate,
                "risk_status": risk_state.status,
                "buffer": risk_state.remaining_loss_buffer,
            }
        except Exception as e:
            return {"error": str(e)}

    def get_trades_today(self) -> pd.DataFrame:
        """Get all trades from today."""
        perf_path = DEFAULT_PERF_PATH
        today = datetime.now(timezone.utc).strftime("%Y%m%d")

        try:
            perf_df = load_performance(perf_path)
            if perf_df.empty or "timestamp" not in perf_df.columns:
                return pd.DataFrame()

            if perf_df["timestamp"].dtype == "object":
                perf_df["timestamp"] = pd.to_datetime(
                    perf_df["timestamp"], errors="coerce"
                )

            today_df = (
                perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
                if not perf_df.empty
                else pd.DataFrame()
            )
            return today_df
        except Exception:
            return pd.DataFrame()

    def print_positions(self):
        """Print positions table."""
        positions = self.get_positions()

        table = Table(
            title=f"💰 Open Positions ({len(positions)})",
            box=box.ROUNDED,
            show_header=True,
        )
        table.add_column("Symbol", style="cyan")
        table.add_column("Side", width=8)
        table.add_column("Size", justify="right")
        table.add_column("Entry", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("P&L %", justify="right")
        table.add_column("Strategy", style="dim")

        if not positions:
            table.add_row("[dim]No open positions[/dim]", "", "", "", "", "", "")
        else:
            for pos in positions:
                pnl = pos.get("pnl", 0)
                pnl_color = "green" if pnl >= 0 else "red"
                side_color = "green" if pos.get("side") == "LONG" else "red"

                table.add_row(
                    pos.get("symbol", ""),
                    f"[{side_color}]{pos.get('side', '')}[/]",
                    str(int(pos.get("size", 0))),
                    f"${pos.get('entry', 0):,.2f}",
                    f"[{pnl_color}]${pnl:,.2f}[/]",
                    f"[{pnl_color}]{pos.get('pnl_pct', 0):.2f}%[/]",
                    pos.get("strategy", "unknown"),
                )

        self.console.print(table)

    def print_performance(self):
        """Print performance metrics."""
        perf = self.get_performance()

        if "error" in perf:
            self.console.print(f"[red]Error: {perf['error']}[/red]")
            return

        table = Table(title="📊 Performance", box=box.ROUNDED, show_header=False)
        pnl_color = "green" if perf.get("daily_pnl", 0) >= 0 else "red"

        table.add_row("Daily P&L:", f"[{pnl_color}]${perf.get('daily_pnl', 0):,.2f}[/]")
        table.add_row("  Realized:", f"${perf.get('realized_pnl', 0):,.2f}")
        table.add_row("  Unrealized:", f"${perf.get('unrealized_pnl', 0):,.2f}")
        table.add_row("", "")
        table.add_row("Win Rate:", f"{perf.get('win_rate', 0):.1f}%")
        table.add_row("Trades:", f"{perf.get('trades_today', 0)}")
        table.add_row("", "")
        risk_color = (
            "green"
            if perf.get("risk_status") == "OK"
            else "yellow"
            if "NEAR" in str(perf.get("risk_status", ""))
            else "red"
        )
        table.add_row(
            "Risk Status:", f"[{risk_color}]{perf.get('risk_status', 'UNKNOWN')}[/]"
        )
        table.add_row("Buffer:", f"${perf.get('buffer', 0):,.2f}")

        self.console.print(table)

    def print_recent_trades(self, limit: int = 10):
        """Print recent trades."""
        trades = self.get_trades_today()

        if trades.empty:
            self.console.print("[dim]No trades today[/dim]")
            return

        table = Table(
            title=f"📋 Recent Trades (Last {min(limit, len(trades))})",
            box=box.ROUNDED,
            show_header=True,
        )
        table.add_column("Time", style="dim")
        table.add_column("Symbol", style="cyan")
        table.add_column("Side", width=8)
        table.add_column("Size", justify="right")
        table.add_column("Entry", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Strategy", style="dim")

        for _, row in trades.tail(limit).iterrows():
            timestamp = row.get("timestamp", "")
            time_str = (
                str(timestamp)[:19] if len(str(timestamp)) > 19 else str(timestamp)
            )
            side = str(row.get("side", "")).upper()
            side_color = "green" if side == "LONG" else "red"
            pnl = float(row.get("realized_pnl", 0) or 0)
            pnl_color = "green" if pnl >= 0 else "red"

            table.add_row(
                time_str,
                str(row.get("symbol", "")),
                f"[{side_color}]{side}[/]",
                str(int(row.get("filled_size", 0) or 0)),
                f"${row.get('entry_price', 0):,.2f}",
                f"[{pnl_color}]${pnl:,.2f}[/]",
                str(row.get("strategy_name", "unknown")),
            )

        self.console.print(table)

    def dashboard(self, refresh: float = 2.0):
        """Show live updating dashboard."""
        self.console.print("\n[bold cyan]📊 Live Trading Dashboard[/bold cyan]")
        self.console.print(f"[dim]Refresh: {refresh}s | Press Ctrl+C to exit[/dim]\n")

        try:
            while True:
                # Clear and show dashboard
                self.console.clear()
                self.console.print(
                    Panel.fit(
                        f"[bold]PEARLALGO TRADING DASHBOARD[/bold] | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                        border_style="cyan",
                    )
                )
                self.console.print()
                self.print_positions()
                self.console.print()
                self.print_performance()
                self.console.print()
                self.print_recent_trades(5)
                self.console.print()
                self.console.print(f"[dim]Next update in {refresh}s...[/dim]")
                time.sleep(refresh)
        except KeyboardInterrupt:
            self.console.print("\n[bold yellow]Dashboard closed[/bold yellow]\n")

    def interactive(self):
        """Interactive command mode."""
        self.console.print(
            "\n[bold cyan]🐍 Python Trading SDK - Interactive Mode[/bold cyan]\n"
        )
        self.console.print("[dim]Type 'help' for commands, 'exit' to quit[/dim]\n")

        while True:
            try:
                cmd = Prompt.ask("[bold cyan]trading[/bold cyan]").strip().lower()

                if cmd == "exit" or cmd == "quit":
                    break
                elif cmd == "help":
                    self.console.print("""
[bold]Commands:[/bold]
  positions    - Show open positions
  performance  - Show performance metrics
  trades       - Show recent trades
  dashboard    - Show live dashboard
  clear        - Clear screen
  help         - Show this help
  exit         - Exit interactive mode
                    """)
                elif cmd == "positions":
                    self.print_positions()
                elif cmd == "performance":
                    self.print_performance()
                elif cmd == "trades":
                    self.print_recent_trades()
                elif cmd == "dashboard":
                    self.dashboard()
                elif cmd == "clear":
                    self.console.clear()
                elif cmd == "":
                    continue
                else:
                    self.console.print(f"[yellow]Unknown command: {cmd}[/yellow]")
                    self.console.print("[dim]Type 'help' for available commands[/dim]")
            except KeyboardInterrupt:
                break
            except EOFError:
                break

        self.console.print("\n[bold yellow]Goodbye![/bold yellow]\n")


def main():
    """Main entry point for interactive terminal."""
    sdk = TradingSDK()
    sdk.interactive()


if __name__ == "__main__":
    main()
