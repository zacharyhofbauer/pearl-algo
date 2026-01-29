"""
Pearl Display - Rich terminal display components.

Provides beautiful, informative terminal output using the `rich` library.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pearlalgo.utils.logger import logger

# Try to import rich
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.syntax import Syntax
    from rich.markdown import Markdown
    from rich.tree import Tree
    from rich.style import Style
    from rich.box import ROUNDED, SIMPLE, HEAVY
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None  # type: ignore


# Color scheme
COLORS = {
    "thinking": "cyan",
    "observation": "blue",
    "decision_allow": "green",
    "decision_block": "red",
    "warning": "yellow",
    "info": "white",
    "muted": "dim",
    "bullish": "green",
    "bearish": "red",
    "neutral": "yellow",
    "header": "bold magenta",
}


class PearlDisplay:
    """
    Rich terminal display for Pearl AI.
    
    Provides formatted output for:
    - Thinking traces
    - Signal notifications
    - Market data
    - Performance metrics
    - Interactive chat
    """
    
    def __init__(self, console: Optional["Console"] = None):
        """
        Initialize display.
        
        Args:
            console: Optional rich Console instance
        """
        if not RICH_AVAILABLE:
            logger.warning("rich not installed, using basic output")
            self._console = None
        else:
            self._console = console or Console()
    
    @property
    def available(self) -> bool:
        """Check if rich display is available."""
        return self._console is not None
    
    def print(self, *args, **kwargs) -> None:
        """Print to console."""
        if self._console:
            self._console.print(*args, **kwargs)
        else:
            print(*args)
    
    def rule(self, title: str = "", style: str = "dim") -> None:
        """Print a horizontal rule."""
        if self._console:
            self._console.rule(title, style=style)
        else:
            print("-" * 60)
            if title:
                print(f"  {title}")
                print("-" * 60)
    
    def header(self, text: str) -> None:
        """Print a header."""
        if self._console:
            self._console.print()
            self._console.print(Panel(
                Text(text, style="bold white"),
                style=COLORS["header"],
                box=ROUNDED,
            ))
        else:
            print(f"\n{'='*60}\n  {text}\n{'='*60}")
    
    def thinking_start(self, context: str = "") -> None:
        """Display start of thinking."""
        if self._console:
            self._console.print()
            self._console.print(
                f"[{COLORS['thinking']}][[THINKING]][/{COLORS['thinking']}] {context}",
            )
        else:
            print(f"\n[THINKING] {context}")
    
    def thinking_step(self, content: str, step_type: str = "observation") -> None:
        """Display a thinking step."""
        prefix = {
            "observation": "->",
            "reasoning": "=>",
            "conclusion": "=>",
            "action": "[ACTION]",
        }.get(step_type, "->")
        
        if self._console:
            color = COLORS.get(step_type, COLORS["observation"])
            self._console.print(f"  [{color}]{prefix}[/{color}] {content}")
        else:
            print(f"  {prefix} {content}")
    
    def decision(self, decision: str, confidence: float, reason: str = "") -> None:
        """Display a decision."""
        color = COLORS["decision_allow"] if decision == "ALLOW" else COLORS["decision_block"]
        
        if self._console:
            self._console.print()
            self._console.print(
                f"[bold {color}][[DECISION]][/bold {color}] "
                f"{decision} with confidence {confidence:.2f}"
            )
            if reason:
                self._console.print(f"  [dim]Reason: {reason}[/dim]")
        else:
            print(f"\n[DECISION] {decision} with confidence {confidence:.2f}")
            if reason:
                print(f"  Reason: {reason}")
    
    def indicator_table(self, indicators: list[dict[str, Any]]) -> None:
        """Display indicators in a table."""
        if not self._console:
            for ind in indicators:
                print(f"  {ind['name']}: {ind['value']:.4f} - {ind['interpretation']}")
            return
        
        table = Table(title="Indicators", box=SIMPLE, show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Value", justify="right")
        table.add_column("Interpretation")
        table.add_column("Signal", justify="center")
        
        for ind in indicators:
            bullish = ind.get("bullish")
            if bullish is True:
                signal = Text("▲", style=COLORS["bullish"])
            elif bullish is False:
                signal = Text("▼", style=COLORS["bearish"])
            else:
                signal = Text("●", style=COLORS["neutral"])
            
            table.add_row(
                ind["name"],
                f"{ind['value']:.4f}",
                ind["interpretation"],
                signal,
            )
        
        self._console.print(table)
    
    def filter_results(self, filters: list[dict[str, Any]]) -> None:
        """Display filter results."""
        if not self._console:
            for f in filters:
                status = "PASS" if f["passed"] else "BLOCK"
                print(f"  {f['name']}: {status} - {f['reason']}")
            return
        
        for f in filters:
            if f["passed"]:
                self._console.print(
                    f"  [green]✓[/green] {f['name']}: [dim]{f['reason']}[/dim]"
                )
            else:
                self._console.print(
                    f"  [red]✗[/red] {f['name']}: [red]{f['reason']}[/red]"
                )
    
    def key_levels_table(self, levels: list[dict[str, Any]]) -> None:
        """Display key levels in a table."""
        if not self._console:
            for lvl in levels:
                print(f"  {lvl['type']}: {lvl['price']:.2f} ({lvl['distance_pct']:.2%} away)")
            return
        
        table = Table(title="Key Levels", box=SIMPLE, show_header=True)
        table.add_column("Level", style="cyan")
        table.add_column("Price", justify="right")
        table.add_column("Distance", justify="right")
        table.add_column("Type", justify="center")
        
        for lvl in levels:
            level_type = lvl.get("is_support", True)
            type_text = Text("S", style=COLORS["bullish"]) if level_type else Text("R", style=COLORS["bearish"])
            
            table.add_row(
                lvl["type"],
                f"{lvl['price']:.2f}",
                f"{lvl['distance_pct']:.2%}",
                type_text,
            )
        
        self._console.print(table)
    
    def signal_card(
        self,
        direction: str,
        entry: float,
        stop: float,
        target: float,
        confidence: float,
        risk_reward: float,
        reasons: list[str],
        cautions: list[str] = None,
    ) -> None:
        """Display a signal notification card."""
        cautions = cautions or []
        
        if not self._console:
            print(f"\n{direction} Signal Generated")
            print(f"Entry: {entry:.2f} | Stop: {stop:.2f} | Target: {target:.2f}")
            print(f"Confidence: {confidence:.2f} | R:R: {risk_reward:.1f}")
            print("\nWhy this signal:")
            for r in reasons:
                print(f"  - {r}")
            if cautions:
                print("\nCautions:")
                for c in cautions:
                    print(f"  - {c}")
            return
        
        color = COLORS["bullish"] if direction == "LONG" else COLORS["bearish"]
        
        # Build content
        lines = []
        lines.append(f"[bold]Entry:[/bold] {entry:.2f} | [bold]Stop:[/bold] {stop:.2f} | [bold]Target:[/bold] {target:.2f}")
        lines.append(f"[bold]Confidence:[/bold] {confidence:.2f} | [bold]R:R:[/bold] {risk_reward:.1f}")
        lines.append("")
        lines.append("[bold]Why this signal:[/bold]")
        for r in reasons:
            lines.append(f"  [green]•[/green] {r}")
        
        if cautions:
            lines.append("")
            lines.append("[bold yellow]Cautions:[/bold yellow]")
            for c in cautions:
                lines.append(f"  [yellow]•[/yellow] {c}")
        
        panel = Panel(
            "\n".join(lines),
            title=f"[bold {color}]{direction} Signal[/bold {color}]",
            border_style=color,
            box=ROUNDED,
        )
        self._console.print(panel)
    
    def performance_summary(
        self,
        trades: int,
        wins: int,
        losses: int,
        pnl: float,
        win_rate: float,
    ) -> None:
        """Display a performance summary."""
        if not self._console:
            print(f"\nTrades: {trades} | Won: {wins} | Lost: {losses}")
            print(f"P&L: ${pnl:+.2f} | Win Rate: {win_rate:.1%}")
            return
        
        pnl_color = COLORS["bullish"] if pnl >= 0 else COLORS["bearish"]
        
        table = Table(box=SIMPLE, show_header=False)
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        
        table.add_row("Trades", str(trades))
        table.add_row("Won", Text(str(wins), style=COLORS["bullish"]))
        table.add_row("Lost", Text(str(losses), style=COLORS["bearish"]))
        table.add_row("P&L", Text(f"${pnl:+.2f}", style=pnl_color))
        table.add_row("Win Rate", f"{win_rate:.1%}")
        
        self._console.print(Panel(table, title="Performance", box=ROUNDED))
    
    def chat_message(self, role: str, content: str) -> None:
        """Display a chat message."""
        if not self._console:
            prefix = "You: " if role == "user" else "Pearl: "
            print(f"\n{prefix}{content}")
            return
        
        if role == "user":
            self._console.print()
            self._console.print(Panel(
                content,
                title="[bold blue]You[/bold blue]",
                border_style="blue",
                box=ROUNDED,
            ))
        else:
            self._console.print()
            self._console.print(Panel(
                Markdown(content),
                title="[bold magenta]Pearl[/bold magenta]",
                border_style="magenta",
                box=ROUNDED,
            ))
    
    def stream_start(self, title: str = "Pearl") -> Optional["Live"]:
        """Start a streaming output panel."""
        if not self._console:
            print(f"\n{title}:")
            return None
        
        return Live(
            Panel("...", title=f"[bold magenta]{title}[/bold magenta]", box=ROUNDED),
            console=self._console,
            refresh_per_second=10,
        )
    
    def error(self, message: str) -> None:
        """Display an error message."""
        if self._console:
            self._console.print(f"[bold red]Error:[/bold red] {message}")
        else:
            print(f"Error: {message}")
    
    def warning(self, message: str) -> None:
        """Display a warning message."""
        if self._console:
            self._console.print(f"[bold yellow]Warning:[/bold yellow] {message}")
        else:
            print(f"Warning: {message}")
    
    def success(self, message: str) -> None:
        """Display a success message."""
        if self._console:
            self._console.print(f"[bold green]✓[/bold green] {message}")
        else:
            print(f"✓ {message}")
    
    def info(self, message: str) -> None:
        """Display an info message."""
        if self._console:
            self._console.print(f"[dim]ℹ[/dim] {message}")
        else:
            print(f"ℹ {message}")


# Convenience functions
_display: Optional[PearlDisplay] = None


def get_display() -> PearlDisplay:
    """Get the global display instance."""
    global _display
    if _display is None:
        _display = PearlDisplay()
    return _display


def display_thinking(trace: "DecisionTrace") -> None:
    """Display a decision trace."""
    from pearlalgo.ai.thinking import DecisionTrace, ThinkingLevel
    
    display = get_display()
    
    display.thinking_start(f"Analyzing {trace.direction} signal at {trace.price:.2f}...")
    
    for step in trace.thinking_steps:
        display.thinking_step(step.content, step.step_type)
    
    if trace.indicators:
        display.print()
        display.indicator_table([
            {
                "name": i.name,
                "value": i.value,
                "interpretation": i.interpretation,
                "bullish": i.bullish,
            }
            for i in trace.indicators
        ])
    
    if trace.filters:
        display.print()
        display.filter_results([
            {"name": f.name, "passed": f.passed, "reason": f.reason}
            for f in trace.filters
        ])
    
    if trace.key_levels:
        display.print()
        display.key_levels_table([
            {
                "type": k.level_type,
                "price": k.level_price,
                "distance_pct": k.distance_pct,
                "is_support": k.is_support,
            }
            for k in trace.key_levels
        ])
    
    display.decision(trace.decision, trace.final_confidence, trace.decision_reason)


def display_signal(
    direction: str,
    entry: float,
    stop: float,
    target: float,
    confidence: float,
    risk_reward: float,
    reasons: list[str],
    cautions: list[str] = None,
) -> None:
    """Display a signal card."""
    display = get_display()
    display.signal_card(
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        confidence=confidence,
        risk_reward=risk_reward,
        reasons=reasons,
        cautions=cautions,
    )


def display_trace(trace: "DecisionTrace") -> None:
    """Display a full decision trace."""
    display_thinking(trace)
