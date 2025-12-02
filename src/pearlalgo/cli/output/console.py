"""Unified console output for trading operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeRemainingColumn,
)

from pearlalgo.cli.output.colors import Colors, Icons


class TraderConsole:
    """Unified console output for trading operations with trader-focused formatting."""

    def __init__(self, verbosity: str = "NORMAL"):
        """
        Initialize trader console.

        Args:
            verbosity: Output level - QUIET, NORMAL, VERBOSE, or DEBUG
        """
        self.console = Console()
        self.verbosity = verbosity.upper()

    def _should_print(self, level: str) -> bool:
        """Check if message should be printed at current verbosity level."""
        levels = {"QUIET": 0, "NORMAL": 1, "VERBOSE": 2, "DEBUG": 3}
        return levels.get(self.verbosity, 1) >= levels.get(level, 1)

    def status_panel(
        self,
        title: str,
        gateway_status: Optional[dict] = None,
        risk_status: Optional[dict] = None,
        performance: Optional[dict] = None,
    ) -> Panel:
        """Create a comprehensive status panel."""
        content_parts = []

        if gateway_status:
            status_icon = Icons.SUCCESS if gateway_status.get("ready") else Icons.ERROR
            content_parts.append(
                f"{status_icon} Gateway: {gateway_status.get('status', 'Unknown')}"
            )
            if gateway_status.get("pid"):
                content_parts.append(f"   PID: {gateway_status['pid']}")

        if risk_status:
            risk_icon = {
                "OK": Icons.SUCCESS,
                "NEAR_LIMIT": Icons.WARNING,
                "HARD_STOP": Icons.ERROR,
                "COOLDOWN": Icons.WARNING,
                "PAUSED": Icons.ERROR,
            }.get(risk_status.get("status", "OK"), Icons.INFO)
            content_parts.append(
                f"{risk_icon} Risk: {risk_status.get('status', 'Unknown')}"
            )
            if risk_status.get("remaining_buffer") is not None:
                content_parts.append(
                    f"   Buffer: ${risk_status['remaining_buffer']:,.2f}"
                )

        if performance:
            pnl = performance.get("total_pnl", 0.0)
            pnl_color = Colors.PNL_POSITIVE if pnl >= 0 else Colors.PNL_NEGATIVE
            content_parts.append(f"📊 P&L: [{pnl_color}]${pnl:,.2f}[/{pnl_color}]")
            if performance.get("trades_today") is not None:
                content_parts.append(f"   Trades Today: {performance['trades_today']}")

        content = "\n".join(content_parts) if content_parts else "No status data"
        return Panel(
            content, title=title, border_style=Colors.BORDER_INFO, box=box.ROUNDED
        )

    def trade_alert(
        self,
        symbol: str,
        side: str,
        size: int,
        price: float,
        reason: Optional[str] = None,
        risk_status: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> None:
        """Display a trade alert with key metrics."""
        if not self._should_print("NORMAL"):
            return

        # Determine direction icon and color
        if side.upper() == "LONG" or side.upper() == "BUY":
            direction_icon = Icons.BUY
            direction_color = Colors.BUY
            direction_text = "LONG"
        elif side.upper() == "SHORT" or side.upper() == "SELL":
            direction_icon = Icons.SELL
            direction_color = Colors.SELL
            direction_text = "SHORT"
        else:
            direction_icon = Icons.FLAT
            direction_color = Colors.FLAT
            direction_text = "FLAT"

        # Build content
        content_lines = [
            f"Direction:  [{direction_color}]{direction_text}[/{direction_color}]",
            f"Size:       {abs(size)} contract{'s' if abs(size) != 1 else ''}",
            f"Price:      ${price:,.2f}",
        ]

        if risk_status:
            risk_icon = {
                "OK": Icons.SUCCESS,
                "NEAR_LIMIT": Icons.WARNING,
                "HARD_STOP": Icons.ERROR,
            }.get(risk_status, Icons.INFO)
            content_lines.append(f"Risk:       {risk_icon} {risk_status}")

        if reason:
            content_lines.append(f"Signal:     {reason}")

        if order_id:
            content_lines.append(f"Order ID:   {order_id}")

        content_lines.append(
            f"Time:       {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
        )

        content = "\n".join(content_lines)

        self.console.print(
            Panel(
                content,
                title=f"{direction_icon} TRADE ALERT: {symbol}",
                border_style=Colors.BORDER_SUCCESS
                if risk_status == "OK"
                else Colors.BORDER_WARNING,
                box=box.ROUNDED,
            )
        )

    def analysis_table(
        self,
        symbol: str,
        signal: dict,
        price: float,
        risk_state: Optional[dict] = None,
        size: Optional[int] = None,
    ) -> None:
        """Display detailed analysis table for a trading decision."""
        if not self._should_print("VERBOSE"):
            return

        table = Table(
            title=f"{Icons.ANALYSIS} Analysis: {symbol}",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")
        table.add_column("Reasoning", style="dim")

        # Signal information
        side = signal.get("side", "flat")
        side_emoji = (
            Icons.BUY
            if side == "long"
            else Icons.SELL
            if side == "short"
            else Icons.FLAT
        )
        table.add_row(
            "Signal", f"{side_emoji} {side.upper()}", signal.get("comment", "No signal")
        )

        # Price and indicators
        table.add_row("Current Price", f"${price:,.2f}", "")

        if signal.get("vwap"):
            vwap_diff = ((price - signal["vwap"]) / signal["vwap"]) * 100
            vwap_status = "Above" if price > signal["vwap"] else "Below"
            table.add_row(
                "VWAP",
                f"${signal['vwap']:,.2f} ({vwap_status} {abs(vwap_diff):.2f}%)",
                "Price above VWAP = bullish, below = bearish",
            )

        if signal.get("fast_ma"):
            ema_diff = ((price - signal["fast_ma"]) / signal["fast_ma"]) * 100
            ema_status = "Above" if price > signal["fast_ma"] else "Below"
            table.add_row(
                "20 EMA",
                f"${signal['fast_ma']:,.2f} ({ema_status} {abs(ema_diff):.2f}%)",
                "Trend filter: long only above EMA, short only below",
            )

        if signal.get("support1"):
            sup_dist = ((price - signal["support1"]) / signal["support1"]) * 100
            table.add_row(
                "Support 1",
                f"${signal['support1']:,.2f} ({abs(sup_dist):.2f}% away)",
                "Near support = potential bounce zone",
            )

        if signal.get("resistance1"):
            res_dist = ((signal["resistance1"] - price) / price) * 100
            table.add_row(
                "Resistance 1",
                f"${signal['resistance1']:,.2f} ({abs(res_dist):.2f}% away)",
                "Near resistance = potential rejection zone",
            )

        # Risk state
        if risk_state:
            risk_status = risk_state.get("status", "UNKNOWN")
            risk_emoji = {
                "OK": Icons.SUCCESS,
                "NEAR_LIMIT": Icons.WARNING,
                "HARD_STOP": Icons.ERROR,
                "COOLDOWN": Icons.WARNING,
                "PAUSED": Icons.ERROR,
            }.get(risk_status, "❓")
            remaining = risk_state.get("remaining_loss_buffer", 0.0)
            table.add_row(
                "Risk Status",
                f"{risk_emoji} {risk_status}",
                f"Remaining buffer: ${remaining:,.2f}",
            )

        # Position sizing
        if size is not None:
            if size != 0:
                table.add_row(
                    "Position Size",
                    f"{abs(size)} contract(s)",
                    "Based on risk taper and profile limits",
                )
            else:
                table.add_row(
                    "Position Size", "0 (BLOCKED)", "Risk limits prevent trading"
                )

        self.console.print(table)
        self.console.print()

    def cycle_summary(
        self,
        cycle_num: int,
        trades_today: int,
        total_pnl: float,
        realized_pnl: float,
        unrealized_pnl: float,
        open_positions: int,
        next_interval: int,
    ) -> None:
        """Display cycle summary after processing all symbols."""
        if not self._should_print("NORMAL"):
            return

        pnl_color = Colors.PNL_POSITIVE if total_pnl >= 0 else Colors.PNL_NEGATIVE

        content = f"{Icons.SUCCESS} Cycle #{cycle_num} Complete\n"
        content += f"Trades Today: {trades_today}\n"
        content += f"Daily P&L: [{pnl_color}]${total_pnl:,.2f}[/{pnl_color}]\n"
        content += (
            f"  Realized: ${realized_pnl:,.2f} | Unrealized: ${unrealized_pnl:,.2f}\n"
        )
        content += f"Open Positions: {open_positions}\n"
        content += f"Next cycle in {next_interval}s ({next_interval / 60:.1f} minutes)"

        self.console.print(
            Panel(
                content,
                title=f"{Icons.CYCLE} Cycle Summary",
                border_style=Colors.BORDER_INFO,
                box=box.ROUNDED,
            )
        )
        self.console.print()

    def error_alert(self, error: Exception, context: Optional[str] = None) -> None:
        """Display an error alert with context."""
        if not self._should_print("QUIET"):
            return

        content = f"{Icons.ERROR} {type(error).__name__}: {str(error)}"
        if context:
            content += f"\n\nContext: {context}"

        self.console.print(
            Panel(
                content,
                title="Error",
                border_style=Colors.BORDER_ERROR,
                box=box.ROUNDED,
            )
        )

    def progress_bar(self, task_description: str, current: int, total: int) -> Progress:
        """Create a progress bar for long-running operations."""
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=self.console,
        )
        progress.add_task(task_description, total=total)
        return progress

    def info(self, message: str, icon: Optional[str] = None) -> None:
        """Print an info message."""
        if not self._should_print("NORMAL"):
            return
        icon_str = f"{icon} " if icon else ""
        self.console.print(f"[{Colors.INFO}]{icon_str}{message}[/{Colors.INFO}]")

    def success(self, message: str) -> None:
        """Print a success message."""
        if not self._should_print("NORMAL"):
            return
        self.console.print(
            f"[{Colors.SUCCESS}]{Icons.SUCCESS} {message}[/{Colors.SUCCESS}]"
        )

    def warning(self, message: str) -> None:
        """Print a warning message."""
        if not self._should_print("NORMAL"):
            return
        self.console.print(
            f"[{Colors.WARNING}]{Icons.WARNING} {message}[/{Colors.WARNING}]"
        )

    def error(self, message: str) -> None:
        """Print an error message."""
        if not self._should_print("QUIET"):
            return
        self.console.print(f"[{Colors.ERROR}]{Icons.ERROR} {message}[/{Colors.ERROR}]")
