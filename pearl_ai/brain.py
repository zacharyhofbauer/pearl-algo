"""
Pearl Brain - The AI Orchestrator

Routes queries between local LLM (fast) and Claude (deep),
manages context, and triggers proactive messages.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable, Literal
from dataclasses import dataclass, field
from enum import Enum

from .memory import PearlMemory
from .narrator import PearlNarrator
from .llm_local import LocalLLM
from .llm_claude import ClaudeLLM

logger = logging.getLogger(__name__)


class QueryComplexity(Enum):
    """Determines which LLM to use"""
    QUICK = "quick"      # Local LLM - simple narration, state summary
    DEEP = "deep"        # Claude - analysis, coaching, complex why
    AUTO = "auto"        # Let brain decide


@dataclass
class PearlMessage:
    """A message from Pearl AI"""
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    message_type: Literal["narration", "insight", "alert", "coaching", "response"] = "narration"
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    related_trade_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "type": self.message_type,
            "priority": self.priority,
            "trade_id": self.related_trade_id,
            "metadata": self.metadata,
        }


class PearlBrain:
    """
    The central AI orchestrator for Pearl.

    Responsibilities:
    - Route queries to appropriate LLM (local vs Claude)
    - Maintain conversation context
    - Trigger proactive messages based on events
    - Learn user preferences over time
    """

    def __init__(
        self,
        claude_api_key: Optional[str] = None,
        ollama_model: str = "llama3.1:8b",
        ollama_host: str = "http://localhost:11434",
        enable_local: bool = True,
        enable_claude: bool = True,
    ):
        self.memory = PearlMemory()
        self.narrator = PearlNarrator()

        # Initialize LLMs
        self.local_llm: Optional[LocalLLM] = None
        self.claude_llm: Optional[ClaudeLLM] = None

        if enable_local:
            self.local_llm = LocalLLM(model=ollama_model, host=ollama_host)

        if enable_claude and claude_api_key:
            self.claude_llm = ClaudeLLM(api_key=claude_api_key)

        # Message handlers (callbacks for sending messages to UI)
        self._message_handlers: List[Callable[[PearlMessage], None]] = []

        # Current trading context
        self._current_state: Dict[str, Any] = {}
        self._last_narration_time: Optional[datetime] = None

        # Configuration
        self.narration_cooldown = timedelta(seconds=5)  # Min time between narrations
        self.always_narrate_events = {
            "signal_generated",
            "trade_entered",
            "trade_exited",
            "circuit_breaker_triggered",
            "direction_blocked",
        }

        logger.info(f"Pearl Brain initialized - Local: {enable_local}, Claude: {enable_claude}")

    def add_message_handler(self, handler: Callable[[PearlMessage], None]):
        """Register a callback for when Pearl has something to say"""
        self._message_handlers.append(handler)

    async def _emit_message(self, message: PearlMessage):
        """Send message to all registered handlers"""
        for handler in self._message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.error(f"Error in message handler: {e}")

        # Store in memory
        self.memory.add_message(message)

    def update_state(self, state: Dict[str, Any]):
        """Update Pearl's knowledge of current trading state"""
        old_state = self._current_state
        self._current_state = state

        # Detect significant changes and narrate
        asyncio.create_task(self._check_state_changes(old_state, state))

    async def _check_state_changes(self, old: Dict, new: Dict):
        """Detect and narrate significant state changes"""

        # Check for new trades
        old_trades = old.get("active_trades_count", 0)
        new_trades = new.get("active_trades_count", 0)

        if new_trades > old_trades:
            await self.narrate_event("trade_entered", {
                "count": new_trades,
                "direction": new.get("last_trade_direction"),
                "entry_price": new.get("last_entry_price"),
            })
        elif new_trades < old_trades:
            # Trade closed
            recent_exit = new.get("recent_exits", [{}])[0] if new.get("recent_exits") else {}
            await self.narrate_event("trade_exited", {
                "pnl": recent_exit.get("pnl"),
                "exit_reason": recent_exit.get("exit_reason"),
                "direction": recent_exit.get("direction"),
            })

        # Check for signal rejections
        old_rejections = old.get("signal_rejections_24h", {})
        new_rejections = new.get("signal_rejections_24h", {})

        for reason, count in new_rejections.items() if isinstance(new_rejections, dict) else []:
            old_count = old_rejections.get(reason, 0) if isinstance(old_rejections, dict) else 0
            if count > old_count:
                await self.narrate_event("signal_rejected", {
                    "reason": reason,
                    "total_today": count,
                })

        # Check circuit breaker
        old_cb = old.get("circuit_breaker", {})
        new_cb = new.get("circuit_breaker", {})

        if new_cb.get("in_cooldown") and not old_cb.get("in_cooldown"):
            await self.narrate_event("circuit_breaker_triggered", {
                "reason": new_cb.get("trip_reason"),
                "cooldown_seconds": new_cb.get("cooldown_remaining_seconds"),
            })

    async def narrate_event(self, event_type: str, context: Dict[str, Any]):
        """
        Generate a natural language narration for an event.
        Uses local LLM for speed.
        """
        # Check cooldown (unless critical event)
        if event_type not in self.always_narrate_events:
            if self._last_narration_time:
                elapsed = datetime.now() - self._last_narration_time
                if elapsed < self.narration_cooldown:
                    return

        # Generate narration
        narration = await self._generate_narration(event_type, context)

        if narration:
            message = PearlMessage(
                content=narration,
                message_type="narration",
                priority="high" if event_type in self.always_narrate_events else "normal",
                related_trade_id=context.get("signal_id"),
                metadata={"event_type": event_type, **context},
            )
            await self._emit_message(message)
            self._last_narration_time = datetime.now()

    async def _generate_narration(self, event_type: str, context: Dict[str, Any]) -> str:
        """Generate narration using local LLM"""

        # Build the prompt
        prompt = self.narrator.build_narration_prompt(event_type, context, self._current_state)

        # Use local LLM for speed
        if self.local_llm and await self.local_llm.is_available():
            try:
                response = await self.local_llm.generate(
                    prompt,
                    system="You are Pearl, an AI trading assistant. Speak naturally and concisely. "
                           "Explain trading decisions clearly. Be direct but friendly.",
                    max_tokens=150,
                )
                return response
            except Exception as e:
                logger.error(f"Local LLM error: {e}")

        # Fallback to template-based narration
        return self.narrator.template_narration(event_type, context)

    async def chat(
        self,
        user_message: str,
        complexity: QueryComplexity = QueryComplexity.AUTO,
    ) -> str:
        """
        Handle a chat message from the user.
        Routes to appropriate LLM based on complexity.
        """

        # Add to memory
        self.memory.add_user_message(user_message)

        # Determine complexity if auto
        if complexity == QueryComplexity.AUTO:
            complexity = self._classify_query(user_message)

        # Build context
        context = self._build_chat_context(user_message)

        # Route to appropriate LLM
        if complexity == QueryComplexity.QUICK and self.local_llm:
            response = await self._quick_response(user_message, context)
        elif self.claude_llm:
            response = await self._deep_response(user_message, context)
        elif self.local_llm:
            response = await self._quick_response(user_message, context)
        else:
            response = "I'm having trouble connecting to my AI backend. Please check the configuration."

        # Store response
        self.memory.add_assistant_message(response)

        # Emit as message
        await self._emit_message(PearlMessage(
            content=response,
            message_type="response",
            priority="normal",
        ))

        return response

    def _classify_query(self, query: str) -> QueryComplexity:
        """Determine if query needs local (quick) or Claude (deep) response"""

        # Keywords that indicate deep analysis needed
        deep_keywords = [
            "why", "explain", "analyze", "should i", "what if",
            "strategy", "improve", "pattern", "trend", "review",
            "coaching", "advice", "recommend", "optimize", "backtest",
        ]

        query_lower = query.lower()

        for keyword in deep_keywords:
            if keyword in query_lower:
                return QueryComplexity.DEEP

        # Quick queries
        quick_keywords = [
            "what is", "current", "status", "how many", "last",
            "price", "position", "pnl", "today",
        ]

        for keyword in quick_keywords:
            if keyword in query_lower:
                return QueryComplexity.QUICK

        # Default to quick for short queries, deep for longer
        return QueryComplexity.QUICK if len(query.split()) < 10 else QueryComplexity.DEEP

    def _build_chat_context(self, query: str) -> Dict[str, Any]:
        """Build context for the chat response"""
        return {
            "current_state": self._current_state,
            "recent_messages": self.memory.get_recent_messages(10),
            "user_patterns": self.memory.get_user_patterns(),
            "query": query,
        }

    async def _quick_response(self, query: str, context: Dict[str, Any]) -> str:
        """Generate quick response using local LLM"""

        system_prompt = """You are Pearl, an AI trading assistant for algorithmic trading.
You have access to real-time trading data. Be concise, direct, and helpful.
Answer questions about current trades, positions, and market state.
Use the provided context to give accurate information."""

        user_prompt = f"""Current Trading State:
- Daily P&L: ${context['current_state'].get('daily_pnl', 0):.2f}
- Active Positions: {context['current_state'].get('active_trades_count', 0)}
- Win/Loss Today: {context['current_state'].get('daily_wins', 0)}/{context['current_state'].get('daily_losses', 0)}
- Market Regime: {context['current_state'].get('market_regime', {}).get('regime', 'unknown')}
- Agent Status: {'Running' if context['current_state'].get('running') else 'Stopped'}

User Question: {query}

Respond naturally and concisely:"""

        if self.local_llm and await self.local_llm.is_available():
            try:
                return await self.local_llm.generate(
                    user_prompt,
                    system=system_prompt,
                    max_tokens=300,
                )
            except Exception as e:
                logger.error(f"Local LLM error: {e}")

        return self._fallback_response(query, context)

    async def _deep_response(self, query: str, context: Dict[str, Any]) -> str:
        """Generate deep analytical response using Claude"""

        system_prompt = """You are Pearl, an advanced AI trading coach and analyst.
You help traders understand their performance, identify patterns, and improve their strategy.

Your capabilities:
- Analyze trading patterns and performance
- Explain why specific trades were taken or rejected
- Provide coaching based on historical data
- Suggest strategy improvements
- Identify psychological patterns (overtrading, revenge trading, etc.)

Be insightful, specific, and actionable. Use data to support your observations.
Speak naturally, like a knowledgeable trading mentor."""

        # Build comprehensive context for Claude
        state = context['current_state']
        recent_trades = state.get('recent_exits', [])[:10]

        user_prompt = f"""# Current Session
- Daily P&L: ${state.get('daily_pnl', 0):.2f}
- Trades: {state.get('daily_trades', 0)} ({state.get('daily_wins', 0)}W / {state.get('daily_losses', 0)}L)
- Active Positions: {state.get('active_trades_count', 0)}
- Win Rate: {state.get('daily_wins', 0) / max(state.get('daily_trades', 1), 1) * 100:.0f}%

# Market Context
- Regime: {state.get('market_regime', {}).get('regime', 'unknown')}
- Direction Allowed: {state.get('market_regime', {}).get('allowed_direction', 'both')}

# Risk Metrics
- Expectancy: ${state.get('risk_metrics', {}).get('expectancy', 0):.2f}
- Sharpe Ratio: {state.get('risk_metrics', {}).get('sharpe_ratio', 'N/A')}
- Max Drawdown: ${state.get('risk_metrics', {}).get('max_drawdown', 0):.2f}

# Recent Trades
{self._format_recent_trades(recent_trades)}

# AI Status
- ML Filter: {state.get('ai_status', {}).get('ml_filter', {}).get('mode', 'off')}
- Direction Gating Blocks: {state.get('ai_status', {}).get('direction_gating', {}).get('blocks', 0)}

# Signal Rejections (24h)
{self._format_rejections(state.get('signal_rejections_24h', {}))}

---

User Question: {query}

Provide a thoughtful, data-driven response:"""

        if self.claude_llm:
            try:
                return await self.claude_llm.generate(
                    user_prompt,
                    system=system_prompt,
                    max_tokens=1000,
                )
            except Exception as e:
                logger.error(f"Claude error: {e}")

        # Fallback to local if Claude unavailable
        if self.local_llm and await self.local_llm.is_available():
            return await self._quick_response(query, context)

        return self._fallback_response(query, context)

    def _format_recent_trades(self, trades: List[Dict]) -> str:
        """Format recent trades for context"""
        if not trades:
            return "No recent trades"

        lines = []
        for t in trades[:5]:
            pnl = t.get('pnl', 0)
            direction = t.get('direction', '?')
            reason = t.get('exit_reason', 'unknown')
            lines.append(f"- {direction.upper()}: ${pnl:+.2f} ({reason})")

        return "\n".join(lines)

    def _format_rejections(self, rejections: Dict) -> str:
        """Format signal rejections for context"""
        if not rejections or not isinstance(rejections, dict):
            return "No rejections"

        lines = []
        for reason, count in rejections.items():
            if count > 0:
                lines.append(f"- {reason.replace('_', ' ').title()}: {count}")

        return "\n".join(lines) if lines else "No rejections"

    def _fallback_response(self, query: str, context: Dict[str, Any]) -> str:
        """Template-based fallback when LLMs unavailable"""
        state = context['current_state']

        query_lower = query.lower()

        if "pnl" in query_lower or "profit" in query_lower:
            pnl = state.get('daily_pnl', 0)
            return f"Today's P&L is ${pnl:+.2f} with {state.get('daily_wins', 0)} wins and {state.get('daily_losses', 0)} losses."

        if "position" in query_lower:
            count = state.get('active_trades_count', 0)
            if count == 0:
                return "No active positions currently."
            return f"You have {count} active position(s)."

        if "status" in query_lower:
            running = state.get('running', False)
            return f"The trading agent is {'running' if running else 'stopped'}."

        return "I'm having trouble processing that request. My AI backend may be unavailable."

    async def generate_insight(self) -> Optional[PearlMessage]:
        """
        Generate a proactive insight based on current state.
        Called periodically to provide coaching/observations.
        """

        if not self.claude_llm:
            return None

        # Only generate insights occasionally
        recent_insights = self.memory.get_messages_by_type("insight", limit=5)
        if recent_insights:
            last_insight_time = recent_insights[0].timestamp
            if datetime.now() - last_insight_time < timedelta(minutes=30):
                return None

        # Generate insight using Claude
        state = self._current_state

        prompt = f"""Based on this trading session, provide ONE brief, actionable insight:

Daily P&L: ${state.get('daily_pnl', 0):.2f}
Trades: {state.get('daily_wins', 0)}W / {state.get('daily_losses', 0)}L
Win Rate: {state.get('daily_wins', 0) / max(state.get('daily_trades', 1), 1) * 100:.0f}%
Regime: {state.get('market_regime', {}).get('regime', 'unknown')}
Rejections: {sum(state.get('signal_rejections_24h', {}).values()) if isinstance(state.get('signal_rejections_24h'), dict) else 0}

Give a brief (1-2 sentence) observation or suggestion. Be specific and actionable."""

        try:
            insight = await self.claude_llm.generate(
                prompt,
                system="You are Pearl, a trading coach. Give brief, actionable insights.",
                max_tokens=100,
            )

            if insight:
                message = PearlMessage(
                    content=insight,
                    message_type="insight",
                    priority="normal",
                )
                await self._emit_message(message)
                return message

        except Exception as e:
            logger.error(f"Error generating insight: {e}")

        return None

    async def daily_review(self) -> Optional[PearlMessage]:
        """Generate end-of-day performance review"""

        if not self.claude_llm:
            return None

        state = self._current_state

        prompt = f"""Generate a brief end-of-day trading review:

# Today's Results
- P&L: ${state.get('daily_pnl', 0):.2f}
- Trades: {state.get('daily_trades', 0)}
- Wins: {state.get('daily_wins', 0)}
- Losses: {state.get('daily_losses', 0)}
- Win Rate: {state.get('daily_wins', 0) / max(state.get('daily_trades', 1), 1) * 100:.0f}%

# Risk Metrics
- Expectancy: ${state.get('risk_metrics', {}).get('expectancy', 0):.2f}
- Largest Win: ${state.get('risk_metrics', {}).get('largest_win', 0):.2f}
- Largest Loss: ${state.get('risk_metrics', {}).get('largest_loss', 0):.2f}

Provide:
1. A brief summary of the day
2. One thing that went well
3. One area for improvement
4. A suggestion for tomorrow

Keep it concise (4-5 sentences total)."""

        try:
            review = await self.claude_llm.generate(
                prompt,
                system="You are Pearl, a trading coach. Provide constructive, balanced daily reviews.",
                max_tokens=300,
            )

            if review:
                message = PearlMessage(
                    content=review,
                    message_type="coaching",
                    priority="high",
                )
                await self._emit_message(message)
                return message

        except Exception as e:
            logger.error(f"Error generating daily review: {e}")

        return None
