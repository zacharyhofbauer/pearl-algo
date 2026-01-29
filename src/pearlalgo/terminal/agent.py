"""
Pearl Terminal Agent - Interactive terminal agent with Claude-like interface.

Provides a rich CLI experience for interacting with Pearl AI, including:
- Interactive chat with thinking display
- Real-time market monitoring
- Trade analysis
- Learning reports
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from pearlalgo.ai import (
    AIMessage,
    AITaskType,
    CompletionConfig,
    get_ai_router,
)
from pearlalgo.ai.thinking import (
    DecisionTrace,
    DecisionType,
    ThinkingLevel,
    get_thinking_engine,
)
from pearlalgo.terminal.display import PearlDisplay, get_display
from pearlalgo.utils.logger import logger


class PearlTerminalAgent:
    """
    Interactive terminal agent with Claude-like interface.
    
    Features:
    - Chat with visible thinking
    - Real-time market monitoring
    - Trade analysis with full context
    - Learning reports and insights
    
    Usage:
        agent = PearlTerminalAgent()
        
        # Interactive chat
        await agent.chat("Why was the last signal filtered?")
        
        # Monitor mode
        await agent.monitor(show_thinking=True)
        
        # Analyze a trade
        await agent.analyze("T-2026-01-29-001")
    """
    
    def __init__(
        self,
        display: Optional[PearlDisplay] = None,
        thinking_level: ThinkingLevel = ThinkingLevel.NORMAL,
    ):
        """
        Initialize the terminal agent.
        
        Args:
            display: Optional display instance
            thinking_level: Level of detail for thinking output
        """
        self._display = display or get_display()
        self._thinking_level = thinking_level
        self._router = get_ai_router()
        self._thinking_engine = get_thinking_engine()
        
        # Chat history
        self._chat_history: list[AIMessage] = []
        self._max_history = 10
        
        # System prompt for Pearl AI
        self._system_prompt = """You are Pearl, an AI trading assistant for the PearlAlgo MNQ futures trading system.

Your role:
- Analyze trading signals and market conditions
- Explain why signals were generated or filtered
- Provide insights on performance and strategy
- Help debug issues and suggest improvements

Communication style:
- Be direct and data-driven
- Show your reasoning process
- Cite specific indicators, prices, and metrics
- Use trading terminology appropriately
- Be concise but thorough

You have access to:
- Signal history and performance data
- Filter evaluation results
- Key level analysis
- Market regime detection
- Learning system insights

When analyzing trades:
1. Review the indicator values at the time
2. Check which filters passed/failed
3. Consider key level proximity
4. Evaluate market regime
5. Provide actionable insights"""
    
    async def chat(
        self,
        message: str,
        context: Optional[dict[str, Any]] = None,
        stream: bool = True,
    ) -> str:
        """
        Chat with Pearl AI.
        
        Args:
            message: User message
            context: Optional context to include
            stream: Whether to stream the response
            
        Returns:
            Pearl's response
        """
        self._display.chat_message("user", message)
        
        # Build messages
        messages = [AIMessage.system(self._system_prompt)]
        
        # Add context if provided
        if context:
            context_str = self._format_context(context)
            messages.append(AIMessage.system(f"Current context:\n{context_str}"))
        
        # Add history
        for msg in self._chat_history[-self._max_history:]:
            messages.append(msg)
        
        # Add current message
        messages.append(AIMessage.user(message))
        
        try:
            if stream and self._display.available:
                response_text = await self._stream_response(messages)
            else:
                response = await self._router.complete(
                    messages=messages,
                    task_type=AITaskType.CHAT,
                    config=CompletionConfig(enable_thinking=True),
                )
                response_text = response.content
                
                # Show thinking if available
                if response.thinking_blocks:
                    self._display.thinking_start("Processing your question...")
                    for block in response.thinking_blocks:
                        self._display.thinking_step(block.content, "reasoning")
                
                self._display.chat_message("assistant", response_text)
            
            # Update history
            self._chat_history.append(AIMessage.user(message))
            self._chat_history.append(AIMessage.assistant(response_text))
            
            return response_text
        
        except Exception as e:
            logger.error(f"Chat error: {e}")
            self._display.error(f"Failed to get response: {e}")
            return ""
    
    async def _stream_response(self, messages: list[AIMessage]) -> str:
        """Stream a response with real-time display."""
        from rich.live import Live
        from rich.panel import Panel
        from rich.markdown import Markdown
        
        full_response = ""
        thinking_shown = False
        
        try:
            with Live(
                Panel("...", title="[bold magenta]Pearl[/bold magenta]"),
                console=self._display._console,
                refresh_per_second=10,
            ) as live:
                async for chunk in self._router.stream(
                    messages=messages,
                    task_type=AITaskType.CHAT,
                    config=CompletionConfig(enable_thinking=True),
                ):
                    if chunk.thinking_content:
                        if not thinking_shown:
                            self._display.thinking_start("Processing...")
                            thinking_shown = True
                        # Could stream thinking here too
                    elif chunk.content:
                        full_response += chunk.content
                        live.update(Panel(
                            Markdown(full_response),
                            title="[bold magenta]Pearl[/bold magenta]",
                        ))
            
            return full_response
        
        except Exception as e:
            logger.error(f"Stream error: {e}")
            self._display.error(f"Stream failed: {e}")
            return full_response
    
    async def monitor(
        self,
        interval_seconds: float = 5.0,
        show_thinking: bool = True,
        duration_minutes: Optional[float] = None,
    ) -> None:
        """
        Real-time market monitoring with explanations.
        
        Args:
            interval_seconds: Scan interval
            show_thinking: Whether to show thinking traces
            duration_minutes: How long to monitor (None = indefinite)
        """
        self._display.header("Pearl AI Monitor")
        self._display.info(f"Monitoring every {interval_seconds}s. Press Ctrl+C to stop.")
        
        start_time = datetime.now(timezone.utc)
        
        try:
            while True:
                # Check duration
                if duration_minutes:
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
                    if elapsed >= duration_minutes:
                        self._display.info(f"Monitoring complete after {duration_minutes} minutes.")
                        break
                
                # Get current market state
                market_state = await self._get_market_state()
                
                # Display current state
                self._display_market_state(market_state)
                
                # Check for signals
                if show_thinking:
                    await self._check_signals_with_thinking(market_state)
                
                await asyncio.sleep(interval_seconds)
        
        except KeyboardInterrupt:
            self._display.info("\nMonitoring stopped.")
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            self._display.error(f"Monitor failed: {e}")
    
    async def _get_market_state(self) -> dict[str, Any]:
        """Get current market state (stub - would connect to data provider)."""
        # This would be implemented to fetch real data
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": 21450.25,
            "rsi": 58.2,
            "volume_ratio": 1.2,
            "regime": "trending_up",
            "regime_confidence": 0.75,
        }
    
    def _display_market_state(self, state: dict[str, Any]) -> None:
        """Display current market state."""
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._display.print(
            f"[dim][{timestamp}][/dim] "
            f"Price: {state['price']:.2f} | "
            f"RSI: {state['rsi']:.1f} | "
            f"Vol: {state['volume_ratio']:.1f}x | "
            f"Regime: {state['regime']}"
        )
    
    async def _check_signals_with_thinking(self, market_state: dict[str, Any]) -> None:
        """Check for signals and display thinking."""
        # This would be implemented to check actual signal conditions
        pass
    
    async def analyze(
        self,
        trade_id: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> None:
        """
        Deep analysis of a specific trade or signal.
        
        Args:
            trade_id: Trade ID to analyze
            signal_id: Signal ID to analyze
        """
        self._display.header(f"Analyzing Trade: {trade_id or signal_id}")
        
        # Get trade/signal details (stub)
        details = await self._get_trade_details(trade_id or signal_id)
        
        if not details:
            self._display.error("Trade/signal not found")
            return
        
        # Display basic info
        self._display.print(f"\n[bold]Direction:[/bold] {details.get('direction', 'N/A')}")
        self._display.print(f"[bold]Entry:[/bold] {details.get('entry_price', 0):.2f}")
        self._display.print(f"[bold]Exit:[/bold] {details.get('exit_price', 0):.2f}")
        self._display.print(f"[bold]P&L:[/bold] ${details.get('pnl', 0):+.2f}")
        
        # Get AI analysis
        analysis_prompt = f"""Analyze this trade:
- Direction: {details.get('direction')}
- Entry: {details.get('entry_price')}
- Exit: {details.get('exit_price')}
- P&L: ${details.get('pnl', 0):+.2f}
- Regime: {details.get('regime')}
- Signal type: {details.get('signal_type')}

Provide insights on:
1. Was this a good setup?
2. What worked or didn't work?
3. What can be learned from this trade?"""
        
        await self.chat(analysis_prompt, context=details)
    
    async def _get_trade_details(self, trade_id: str) -> Optional[dict[str, Any]]:
        """Get trade details (stub)."""
        # This would fetch from database
        return {
            "trade_id": trade_id,
            "direction": "LONG",
            "entry_price": 21450.25,
            "exit_price": 21480.50,
            "pnl": 121.00,
            "regime": "trending_up",
            "signal_type": "unified_strategy",
        }
    
    async def learn_report(
        self,
        report_type: str = "filter-effectiveness",
        period_days: int = 7,
    ) -> None:
        """
        Generate a learning report.
        
        Args:
            report_type: Type of report to generate
            period_days: Period to analyze
        """
        self._display.header(f"Learning Report: {report_type}")
        
        if report_type == "filter-effectiveness":
            await self._filter_effectiveness_report(period_days)
        elif report_type == "performance":
            await self._performance_report(period_days)
        elif report_type == "opportunities":
            await self._opportunities_report(period_days)
        else:
            self._display.error(f"Unknown report type: {report_type}")
    
    async def _filter_effectiveness_report(self, period_days: int) -> None:
        """Generate filter effectiveness report."""
        self._display.info(f"Analyzing filter effectiveness over {period_days} days...")
        
        # This would fetch real data
        report_data = {
            "total_signals": 150,
            "filtered_signals": 45,
            "filters": {
                "session_filter": {"blocked": 20, "would_have_won": 6, "saved_pnl": 180},
                "key_level": {"blocked": 15, "would_have_won": 4, "saved_pnl": 240},
                "volatility": {"blocked": 10, "would_have_won": 3, "saved_pnl": 160},
            },
        }
        
        self._display.print(f"\n[bold]Total signals:[/bold] {report_data['total_signals']}")
        self._display.print(f"[bold]Filtered:[/bold] {report_data['filtered_signals']}")
        
        self._display.print("\n[bold]Filter Performance:[/bold]")
        for name, stats in report_data["filters"].items():
            win_rate = stats["would_have_won"] / stats["blocked"] * 100 if stats["blocked"] > 0 else 0
            self._display.print(
                f"  {name}: Blocked {stats['blocked']}, "
                f"Would-have-won: {stats['would_have_won']} ({win_rate:.0f}%), "
                f"Saved: ${stats['saved_pnl']:+.0f}"
            )
    
    async def _performance_report(self, period_days: int) -> None:
        """Generate performance report."""
        self._display.info(f"Analyzing performance over {period_days} days...")
        
        # Stub data
        self._display.performance_summary(
            trades=45,
            wins=27,
            losses=18,
            pnl=1250.00,
            win_rate=0.60,
        )
    
    async def _opportunities_report(self, period_days: int) -> None:
        """Generate opportunities report."""
        self._display.info(f"Analyzing missed opportunities over {period_days} days...")
        
        # Stub data
        self._display.print("\n[bold]Filtered signals that would have won:[/bold]")
        self._display.print("  - 12 signals with 67% hypothetical win rate")
        self._display.print("  - Estimated missed P&L: $450")
        self._display.print("\n[bold]Recommendations:[/bold]")
        self._display.print("  - Consider relaxing session_filter for 'afternoon' (62% WR)")
    
    def _format_context(self, context: dict[str, Any]) -> str:
        """Format context dictionary for prompt."""
        lines = []
        for key, value in context.items():
            if isinstance(value, dict):
                lines.append(f"{key}:")
                for k, v in value.items():
                    lines.append(f"  {k}: {v}")
            else:
                lines.append(f"{key}: {value}")
        return "\n".join(lines)
    
    def clear_history(self) -> None:
        """Clear chat history."""
        self._chat_history.clear()
        self._display.info("Chat history cleared.")
    
    async def memory_show(self) -> None:
        """Show current memory context."""
        self._display.header("Pearl Memory")
        self._display.info("Memory system provides persistent context across sessions.")
        
        # This would show actual memory contents
        self._display.print("\n[bold]Recent Episodes:[/bold]")
        self._display.print("  - No episodes stored yet")
        
        self._display.print("\n[bold]Learned Knowledge:[/bold]")
        self._display.print("  - No knowledge accumulated yet")
