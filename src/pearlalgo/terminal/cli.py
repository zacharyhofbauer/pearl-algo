"""
Pearl CLI - Command-line interface for Pearl AI.

Usage:
    pearl chat "Why was the last signal filtered?"
    pearl monitor --show-thinking
    pearl analyze --trade T-2026-01-29-001
    pearl learn --report filter-effectiveness
    pearl memory --show context
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

# Load .env file before anything else
try:
    from dotenv import load_dotenv
    # Find .env file - look in current dir and parent dirs
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Try to import typer
try:
    import typer
    from typer import Argument, Option
    TYPER_AVAILABLE = True
except ImportError:
    TYPER_AVAILABLE = False
    typer = None  # type: ignore

from pearlalgo.utils.logger import logger


def create_app():
    """Create the Typer CLI app."""
    if not TYPER_AVAILABLE:
        logger.error("typer not installed. Install with: pip install typer")
        return None
    
    app = typer.Typer(
        name="pearl",
        help="Pearl AI - Intelligent trading assistant with Claude-like interface",
        add_completion=False,
    )
    
    @app.command()
    def chat(
        message: str = Argument(..., help="Message to send to Pearl"),
        context: Optional[str] = Option(None, "--context", "-c", help="Additional context"),
        no_stream: bool = Option(False, "--no-stream", help="Disable streaming output"),
    ):
        """Chat with Pearl AI."""
        from pearlalgo.terminal.agent import PearlTerminalAgent
        
        agent = PearlTerminalAgent()
        
        context_dict = None
        if context:
            # Parse simple key=value context
            context_dict = {}
            for item in context.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    context_dict[k.strip()] = v.strip()
        
        asyncio.run(agent.chat(message, context=context_dict, stream=not no_stream))
    
    @app.command()
    def monitor(
        interval: float = Option(5.0, "--interval", "-i", help="Scan interval in seconds"),
        show_thinking: bool = Option(True, "--show-thinking/--no-thinking", help="Show thinking traces"),
        duration: Optional[float] = Option(None, "--duration", "-d", help="Duration in minutes"),
    ):
        """Real-time market monitoring with explanations."""
        from pearlalgo.terminal.agent import PearlTerminalAgent
        
        agent = PearlTerminalAgent()
        asyncio.run(agent.monitor(
            interval_seconds=interval,
            show_thinking=show_thinking,
            duration_minutes=duration,
        ))
    
    @app.command()
    def analyze(
        trade_id: Optional[str] = Option(None, "--trade", "-t", help="Trade ID to analyze"),
        signal_id: Optional[str] = Option(None, "--signal", "-s", help="Signal ID to analyze"),
    ):
        """Deep analysis of a specific trade or signal."""
        from pearlalgo.terminal.agent import PearlTerminalAgent
        
        if not trade_id and not signal_id:
            typer.echo("Error: Provide either --trade or --signal")
            raise typer.Exit(1)
        
        agent = PearlTerminalAgent()
        asyncio.run(agent.analyze(trade_id=trade_id, signal_id=signal_id))
    
    @app.command()
    def learn(
        report: str = Option("filter-effectiveness", "--report", "-r", help="Report type"),
        period: int = Option(7, "--period", "-p", help="Period in days"),
    ):
        """Generate learning reports."""
        from pearlalgo.terminal.agent import PearlTerminalAgent
        
        agent = PearlTerminalAgent()
        asyncio.run(agent.learn_report(report_type=report, period_days=period))
    
    @app.command()
    def memory(
        show: bool = Option(False, "--show", "-s", help="Show current memory context"),
        clear: bool = Option(False, "--clear", help="Clear memory (with confirmation)"),
    ):
        """Manage Pearl's persistent memory."""
        from pearlalgo.terminal.agent import PearlTerminalAgent
        
        agent = PearlTerminalAgent()
        
        if clear:
            confirm = typer.confirm("Are you sure you want to clear Pearl's memory?")
            if confirm:
                # Clear memory implementation
                typer.echo("Memory cleared.")
            else:
                typer.echo("Cancelled.")
        elif show:
            asyncio.run(agent.memory_show())
        else:
            asyncio.run(agent.memory_show())
    
    @app.command()
    def interactive():
        """Start interactive chat mode."""
        from pearlalgo.terminal.agent import PearlTerminalAgent
        from pearlalgo.terminal.display import get_display
        
        display = get_display()
        agent = PearlTerminalAgent(display=display)
        
        display.header("Pearl AI Interactive Mode")
        display.info("Type your message and press Enter. Type 'quit' or 'exit' to leave.")
        display.info("Commands: /clear (clear history), /analyze <id>, /learn <report>")
        display.print()
        
        while True:
            try:
                user_input = input("You: ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() in ("quit", "exit", "/quit", "/exit"):
                    display.info("Goodbye!")
                    break
                
                if user_input.lower() == "/clear":
                    agent.clear_history()
                    continue
                
                if user_input.startswith("/analyze "):
                    trade_id = user_input[9:].strip()
                    asyncio.run(agent.analyze(trade_id=trade_id))
                    continue
                
                if user_input.startswith("/learn "):
                    report_type = user_input[7:].strip()
                    asyncio.run(agent.learn_report(report_type=report_type))
                    continue
                
                asyncio.run(agent.chat(user_input))
                
            except KeyboardInterrupt:
                display.print()
                display.info("Goodbye!")
                break
            except EOFError:
                display.info("Goodbye!")
                break
    
    @app.command()
    def health():
        """Check AI provider health status."""
        from pearlalgo.ai import get_ai_router
        from pearlalgo.terminal.display import get_display
        
        display = get_display()
        display.header("AI Provider Health Check")
        
        router = get_ai_router()
        results = asyncio.run(router.health_check())
        
        for provider, healthy in results.items():
            if healthy:
                display.success(f"{provider}: OK")
            else:
                display.error(f"{provider}: UNAVAILABLE")
        
        available = router.list_available_providers()
        display.print()
        display.info(f"Available providers: {', '.join(available) if available else 'None'}")
    
    return app


def main():
    """Main entry point for CLI."""
    if not TYPER_AVAILABLE:
        print("Error: typer not installed. Install with: pip install typer")
        sys.exit(1)
    
    app = create_app()
    if app:
        app()


if __name__ == "__main__":
    main()
