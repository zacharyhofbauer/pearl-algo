"""
Pearl AI Chat - Conversational AI for Telegram bot.

Provides context-aware responses about trading performance, signals, and system status.
Uses OpenAI GPT-4o-mini for cost-effective, fast responses.

Features:
- Rate limiting (5 messages/min by default)
- Trading context injection for relevant responses
- Concise mobile-friendly responses (280 char max)
- Graceful degradation when API unavailable
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger

# OpenAI client (lazy import)
_openai_client = None


def _get_openai_client():
    """Lazily initialize OpenAI client."""
    global _openai_client
    if _openai_client is None:
        try:
            from openai import OpenAI
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set - AI chat disabled")
                return None
            _openai_client = OpenAI(api_key=api_key)
        except ImportError:
            logger.warning("openai package not installed - AI chat disabled")
            return None
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI client: {e}")
            return None
    return _openai_client


@dataclass
class RateLimiter:
    """Simple sliding window rate limiter."""

    max_requests: int = 5
    window_seconds: float = 60.0
    timestamps: List[float] = field(default_factory=list)

    def is_allowed(self) -> bool:
        """Check if request is allowed under rate limit."""
        now = time.time()
        # Remove timestamps outside window
        self.timestamps = [t for t in self.timestamps if now - t < self.window_seconds]
        return len(self.timestamps) < self.max_requests

    def record(self) -> None:
        """Record a request timestamp."""
        self.timestamps.append(time.time())

    def time_until_allowed(self) -> float:
        """Return seconds until next request is allowed."""
        if self.is_allowed():
            return 0.0
        now = time.time()
        oldest = min(self.timestamps)
        return max(0.0, self.window_seconds - (now - oldest))


@dataclass
class AIConfig:
    """Configuration for AI chat."""

    enabled: bool = True
    model: str = "gpt-4o-mini"
    max_response_length: int = 280
    rate_limit_per_minute: int = 5
    temperature: float = 0.7
    system_prompt: str = ""

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "AIConfig":
        """Create config from dictionary."""
        return cls(
            enabled=bool(config.get("enabled", True)),
            model=str(config.get("model", "gpt-4o-mini")),
            max_response_length=int(config.get("max_response_length", 280)),
            rate_limit_per_minute=int(config.get("rate_limit_per_minute", 5)),
            temperature=float(config.get("temperature", 0.7)),
            system_prompt=str(config.get("system_prompt", "")),
        )


class PearlAIChat:
    """
    Conversational AI for Pearl trading assistant.

    Provides context-aware responses about trading performance and system status.
    Designed for mobile-friendly Telegram interactions.
    """

    DEFAULT_SYSTEM_PROMPT = """You are Pearl, a friendly and knowledgeable trading assistant for a futures day-trading system.

Your personality:
- Concise and direct (like a smart trading buddy texting you)
- Use trading lingo naturally
- Supportive but honest about performance
- Never give financial advice, just report facts and observations
- Proactive about system status and potential issues

Response rules:
- Keep responses under 280 characters (Twitter-length)
- Use $ for money amounts, % for percentages
- Use plain text, minimal formatting
- Be specific with numbers when available
- If you don't have data, say so briefly

Trading knowledge:
- System trades MNQ futures with virtual P&L tracking
- Sessions: overnight (6PM-4AM), premarket, morning, midday, afternoon, close
- User prefers all sessions enabled, no direction gating
- Circuit breaker in warn_only mode (logs but doesn't block)
- Web app at localhost:3001, API at localhost:8000

You have access to the trader's current state including P&L, positions, recent trades, and system status.
When asked about performance, be specific and analytical.
When asked about what's working or not working, identify patterns in the data.
When asked about config or setup, reference the user's preferences for open trading."""

    def __init__(
        self,
        config: Optional[AIConfig] = None,
        state_dir: Optional[str] = None,
    ):
        """
        Initialize Pearl AI Chat.

        Args:
            config: AI configuration (uses defaults if not provided)
            state_dir: Optional state directory for persistence
        """
        self.config = config or AIConfig()
        self.state_dir = state_dir
        self.rate_limiter = RateLimiter(
            max_requests=self.config.rate_limit_per_minute,
            window_seconds=60.0,
        )
        self._last_error: Optional[str] = None

    @property
    def enabled(self) -> bool:
        """Check if AI chat is enabled and available."""
        if not self.config.enabled:
            return False
        client = _get_openai_client()
        return client is not None

    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build system prompt with trading context."""
        base = self.config.system_prompt or self.DEFAULT_SYSTEM_PROMPT

        # Add current trading context
        context_parts = [base, "\n\nCurrent trading context:"]

        # P&L info
        daily_pnl = context.get("daily_pnl", 0)
        if daily_pnl != 0:
            sign = "+" if daily_pnl >= 0 else ""
            context_parts.append(f"- Daily P&L: {sign}${daily_pnl:.2f}")

        # Trade counts
        wins = context.get("wins_today", 0)
        losses = context.get("losses_today", 0)
        total_trades = wins + losses
        if total_trades > 0:
            wr = (wins / total_trades) * 100
            context_parts.append(f"- Today's trades: {total_trades} ({wins}W/{losses}L, {wr:.0f}% WR)")

        # Win/loss streak
        streak = context.get("win_streak", 0)
        streak_type = context.get("streak_type", "")
        if streak >= 2:
            context_parts.append(f"- Current streak: {streak} {streak_type}s in a row")

        # Active positions
        active = context.get("active_positions", 0)
        if active > 0:
            context_parts.append(f"- Active positions: {active}")

        # Session info
        if context.get("session_open"):
            context_parts.append("- Trading session: OPEN")
        elif context.get("session_open") is False:
            context_parts.append("- Trading session: CLOSED")

        # Best/worst signal types
        best_type = context.get("best_signal_type")
        if best_type:
            context_parts.append(f"- Best performer today: {best_type}")

        worst_type = context.get("worst_signal_type")
        if worst_type:
            context_parts.append(f"- Underperformer today: {worst_type}")

        # Time context
        try:
            from zoneinfo import ZoneInfo
            et_tz = ZoneInfo("America/New_York")
            now_et = datetime.now(et_tz)
            context_parts.append(f"- Current time: {now_et.strftime('%I:%M %p ET')}")
        except Exception:
            pass

        # Recent trades summary
        recent_trades = context.get("recent_trades", [])
        if recent_trades:
            trade_summary = []
            for t in recent_trades[:5]:
                direction = t.get("direction", "?")
                pnl = t.get("pnl", 0)
                sign = "+" if pnl >= 0 else ""
                trade_summary.append(f"{direction} {sign}${pnl:.0f}")
            context_parts.append(f"- Recent trades: {', '.join(trade_summary)}")

        return "\n".join(context_parts)

    async def chat(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Send a message to Pearl AI and get a response.

        Args:
            message: User's message/question
            context: Trading context dictionary with current state

        Returns:
            AI response string (or error message if unavailable)
        """
        # Check if enabled
        if not self.config.enabled:
            return "AI chat is disabled in config."

        # Check rate limit
        if not self.rate_limiter.is_allowed():
            wait_time = self.rate_limiter.time_until_allowed()
            return f"Easy there! Try again in {wait_time:.0f}s."

        # Get OpenAI client
        client = _get_openai_client()
        if client is None:
            return "AI unavailable - check OPENAI_API_KEY."

        # Build context-aware system prompt
        context = context or {}
        system_prompt = self._build_system_prompt(context)

        try:
            # Record the request for rate limiting
            self.rate_limiter.record()

            # Make API call
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                max_tokens=150,  # Keep responses concise
                temperature=self.config.temperature,
            )

            # Extract response text
            reply = response.choices[0].message.content.strip()

            # Truncate if needed (should rarely happen with max_tokens)
            if len(reply) > self.config.max_response_length:
                reply = reply[:self.config.max_response_length - 3] + "..."

            self._last_error = None
            return reply

        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"AI chat error: {e}")
            return "AI hiccup - try again in a sec."

    async def generate_insight(
        self,
        insight_type: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """
        Generate a specific type of insight (for briefings and suggestions).

        Args:
            insight_type: Type of insight to generate
                - "morning_briefing": Market prep summary
                - "eod_summary": End of day analysis
                - "pattern_insight": Pattern recognition
                - "risk_alert": Risk warning
            context: Trading context dictionary

        Returns:
            Generated insight string, or None if generation fails
        """
        if not self.enabled:
            return None

        prompts = {
            "morning_briefing": (
                "Generate a brief morning market prep for a futures day trader. "
                "Include: overnight session recap if any trades, current P&L status, "
                "and one actionable observation. Keep it under 200 chars."
            ),
            "eod_summary": (
                "Generate a brief end-of-day summary. Include: "
                "what worked well, what didn't work, and one specific actionable insight "
                "for tomorrow. Be specific about patterns you see. Keep it under 250 chars."
            ),
            "pattern_insight": (
                "Identify the most notable pattern in recent trading performance. "
                "Could be time-of-day patterns, direction bias, streak patterns, etc. "
                "Be specific and actionable. Keep it under 200 chars."
            ),
            "risk_alert": (
                "Generate a brief risk awareness message based on current drawdown or "
                "loss streak. Be supportive but direct. Suggest a specific action. "
                "Keep it under 180 chars."
            ),
        }

        prompt = prompts.get(insight_type)
        if not prompt:
            logger.warning(f"Unknown insight type: {insight_type}")
            return None

        try:
            return await self.chat(prompt, context)
        except Exception as e:
            logger.debug(f"Failed to generate {insight_type} insight: {e}")
            return None


# Singleton instance (lazily initialized)
_chat_instance: Optional[PearlAIChat] = None


def get_ai_chat(
    config: Optional[Dict[str, Any]] = None,
    state_dir: Optional[str] = None,
) -> PearlAIChat:
    """
    Get or create the global AI chat instance.

    Args:
        config: Optional configuration dictionary
        state_dir: Optional state directory

    Returns:
        PearlAIChat instance
    """
    global _chat_instance
    if _chat_instance is None:
        ai_config = AIConfig.from_dict(config or {})
        _chat_instance = PearlAIChat(config=ai_config, state_dir=state_dir)
    return _chat_instance
