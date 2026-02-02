"""
Pearl Narrator - Converts trading events to natural language

Provides prompts and templates for narrating trading activity.
"""

from typing import Dict, Any, Optional
from datetime import datetime


class PearlNarrator:
    """Converts trading events and states into natural language."""

    def __init__(self):
        self.personality_traits = [
            "concise but informative",
            "confident but not arrogant",
            "focused on actionable information",
            "uses trading terminology naturally",
        ]

    def build_narration_prompt(
        self,
        event_type: str,
        context: Dict[str, Any],
        current_state: Dict[str, Any],
    ) -> str:
        """Build a prompt for the LLM to generate a narration."""

        prompts = {
            "trade_entered": self._trade_entered_prompt,
            "trade_exited": self._trade_exited_prompt,
            "signal_generated": self._signal_generated_prompt,
            "signal_rejected": self._signal_rejected_prompt,
            "circuit_breaker_triggered": self._circuit_breaker_prompt,
            "direction_blocked": self._direction_blocked_prompt,
            "regime_changed": self._regime_changed_prompt,
            "session_started": self._session_started_prompt,
            "session_ended": self._session_ended_prompt,
        }

        builder = prompts.get(event_type, self._generic_prompt)
        return builder(context, current_state)

    def _trade_entered_prompt(self, ctx: Dict, state: Dict) -> str:
        direction = ctx.get("direction", "unknown")
        entry_price = ctx.get("entry_price", 0)
        ml_prob = state.get("last_signal_decision", {}).get("ml_probability", 0)
        regime = state.get("market_regime", {}).get("regime", "unknown")

        return f"""Narrate this trade entry in 1-2 sentences:
- Direction: {direction.upper()}
- Entry Price: {entry_price}
- ML Confidence: {ml_prob * 100:.0f}%
- Market Regime: {regime}
- Active Positions After: {ctx.get('count', 1)}

Be direct and mention the key setup factors."""

    def _trade_exited_prompt(self, ctx: Dict, state: Dict) -> str:
        pnl = ctx.get("pnl", 0)
        direction = ctx.get("direction", "unknown")
        reason = ctx.get("exit_reason", "unknown")
        daily_pnl = state.get("daily_pnl", 0)

        return f"""Narrate this trade exit in 1-2 sentences:
- Direction: {direction.upper()}
- P&L: ${pnl:+.2f}
- Exit Reason: {reason}
- Daily P&L Now: ${daily_pnl:+.2f}

{'Celebrate briefly if profitable.' if pnl > 0 else 'Acknowledge the loss constructively.'} Mention the exit reason."""

    def _signal_generated_prompt(self, ctx: Dict, state: Dict) -> str:
        signal_type = ctx.get("signal_type", "unknown")
        ml_prob = ctx.get("ml_probability", 0)

        return f"""Briefly note this signal generation:
- Signal Type: {signal_type}
- ML Probability: {ml_prob * 100:.0f}%

One sentence about the signal spotted."""

    def _signal_rejected_prompt(self, ctx: Dict, state: Dict) -> str:
        reason = ctx.get("reason", "unknown")
        total = ctx.get("total_today", 0)

        return f"""Briefly explain this signal rejection:
- Reason: {reason.replace('_', ' ')}
- Total Rejections Today: {total}

One sentence explaining why we passed on this signal."""

    def _circuit_breaker_prompt(self, ctx: Dict, state: Dict) -> str:
        reason = ctx.get("reason", "protective stop")
        cooldown = ctx.get("cooldown_seconds", 0)

        return f"""Alert about circuit breaker activation:
- Trigger Reason: {reason}
- Cooldown Duration: {cooldown // 60} minutes

Explain briefly and reassure this is protective."""

    def _direction_blocked_prompt(self, ctx: Dict, state: Dict) -> str:
        blocked = ctx.get("blocked_direction", "unknown")
        regime = state.get("market_regime", {}).get("regime", "unknown")

        return f"""Note direction restriction:
- Blocked Direction: {blocked}
- Market Regime: {regime}

One sentence about why this direction is restricted."""

    def _regime_changed_prompt(self, ctx: Dict, state: Dict) -> str:
        old_regime = ctx.get("old_regime", "unknown")
        new_regime = ctx.get("new_regime", "unknown")
        confidence = ctx.get("confidence", 0)

        return f"""Note market regime change:
- Previous: {old_regime}
- Current: {new_regime}
- Confidence: {confidence * 100:.0f}%

One sentence about what this means for trading."""

    def _session_started_prompt(self, ctx: Dict, state: Dict) -> str:
        session = ctx.get("session", "trading")
        return f"Briefly announce the start of the {session} session."

    def _session_ended_prompt(self, ctx: Dict, state: Dict) -> str:
        pnl = state.get("daily_pnl", 0)
        trades = state.get("daily_trades", 0)
        wins = state.get("daily_wins", 0)

        return f"""Summarize session end:
- Session P&L: ${pnl:+.2f}
- Trades: {trades} ({wins} wins)

Two sentences summarizing the session."""

    def _generic_prompt(self, ctx: Dict, state: Dict) -> str:
        return f"Briefly describe this trading event: {ctx}"

    def template_narration(self, event_type: str, context: Dict[str, Any]) -> str:
        """
        Fallback template-based narration when LLM is unavailable.
        Returns human-readable text without AI generation.
        """

        templates = {
            "trade_entered": self._template_trade_entered,
            "trade_exited": self._template_trade_exited,
            "signal_rejected": self._template_signal_rejected,
            "circuit_breaker_triggered": self._template_circuit_breaker,
            "direction_blocked": self._template_direction_blocked,
        }

        template_fn = templates.get(event_type, self._template_generic)
        return template_fn(context)

    def _template_trade_entered(self, ctx: Dict) -> str:
        direction = ctx.get("direction", "").upper()
        count = ctx.get("count", 1)
        return f"Entered {direction} position. {count} active position(s)."

    def _template_trade_exited(self, ctx: Dict) -> str:
        pnl = ctx.get("pnl", 0)
        reason = ctx.get("exit_reason", "").replace("_", " ")
        emoji = "+" if pnl >= 0 else ""
        return f"Closed position: {emoji}${pnl:.2f} ({reason})"

    def _template_signal_rejected(self, ctx: Dict) -> str:
        reason = ctx.get("reason", "").replace("_", " ").title()
        return f"Signal blocked by {reason}."

    def _template_circuit_breaker(self, ctx: Dict) -> str:
        cooldown = ctx.get("cooldown_seconds", 0)
        minutes = cooldown // 60
        return f"Circuit breaker activated. Pausing for {minutes} minutes."

    def _template_direction_blocked(self, ctx: Dict) -> str:
        direction = ctx.get("blocked_direction", "").upper()
        return f"{direction} direction currently restricted by market regime."

    def _template_generic(self, ctx: Dict) -> str:
        return f"Trading event: {ctx.get('event_type', 'update')}"


class NarrationStyle:
    """Different narration styles for different contexts."""

    CONCISE = "concise"  # Short, to the point
    DETAILED = "detailed"  # More explanation
    COACHING = "coaching"  # Educational, teaching
    ALERT = "alert"  # Urgent, attention-grabbing

    @staticmethod
    def get_style_prompt(style: str) -> str:
        prompts = {
            "concise": "Be brief - one sentence max. Just the key facts.",
            "detailed": "Provide context and explanation in 2-3 sentences.",
            "coaching": "Explain the reasoning and teach the concept in 3-4 sentences.",
            "alert": "This is important - be clear and direct about the urgency.",
        }
        return prompts.get(style, prompts["concise"])
