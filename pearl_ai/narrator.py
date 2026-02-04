"""
Pearl Narrator - Converts trading events to natural language

Provides prompts and templates for narrating trading activity.
Enhanced with rich context injection for meaningful explanations.
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

        # Session name mappings for time-of-day context
        self.session_names = {
            "pre_market": "Pre-market session",
            "morning_open": "Morning open",
            "mid_morning": "Mid-morning",
            "lunch": "Lunch hour",
            "afternoon": "Afternoon session",
            "power_hour": "Power hour",
            "after_hours": "After-hours"
        }

    def _get_session_name(self, state: Dict) -> str:
        """Get human-readable session name from state."""
        session_ctx = state.get("session_context", {})
        session_key = session_ctx.get("current_session", "")
        return self.session_names.get(session_key, session_key.replace("_", " ").title() if session_key else "market")

    def _get_pressure_description(self, state: Dict) -> str:
        """Get order flow pressure description."""
        pressure = state.get("buy_sell_pressure", {})
        bias = pressure.get("bias", "neutral")
        intensity = pressure.get("intensity", 0)

        if bias == "neutral" or intensity < 0.3:
            return "balanced flow"
        elif bias == "buyer":
            return "buyer pressure" if intensity < 0.6 else "strong buyer pressure"
        else:
            return "seller pressure" if intensity < 0.6 else "strong seller pressure"

    def _get_regime_context(self, state: Dict) -> str:
        """Get market regime context."""
        regime_info = state.get("market_regime", {})
        regime = regime_info.get("regime", "unknown")
        confidence = regime_info.get("confidence", 0)

        regime_map = {
            "trending_up": "uptrending",
            "trending_down": "downtrending",
            "ranging": "ranging",
            "volatile": "volatile",
            "unknown": "uncertain"
        }

        regime_str = regime_map.get(regime, regime.replace("_", " "))
        if confidence > 0.7:
            return f"{regime_str}"
        return f"likely {regime_str}"

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
        regime = self._get_regime_context(state)
        pressure = self._get_pressure_description(state)
        session = self._get_session_name(state)

        # Get recent trade correlation context
        recent_exits = state.get("recent_exits", [])
        recent_same_dir = [t for t in recent_exits[:5] if t.get("direction") == direction]
        same_dir_wins = sum(1 for t in recent_same_dir if t.get("pnl", 0) > 0)
        correlation_note = ""
        if len(recent_same_dir) >= 2:
            win_rate = same_dir_wins / len(recent_same_dir)
            if win_rate > 0.6:
                correlation_note = f"Recent {direction.upper()} trades have been winning ({same_dir_wins}/{len(recent_same_dir)})."
            elif win_rate < 0.4:
                correlation_note = f"Recent {direction.upper()} trades have struggled ({same_dir_wins}/{len(recent_same_dir)} wins)."

        return f"""Narrate this trade entry in EXACTLY 1 sentence (max 25 words):
{direction.upper()} at {entry_price}, {regime} market, {pressure}, ML {ml_prob * 100:.0f}%.

Output format: "Entered [DIRECTION] at [PRICE] — [one key observation]."
Example: "Entered LONG at 25530 — trending market with 72% ML confidence."
DO NOT exceed 1 sentence."""

    def _trade_exited_prompt(self, ctx: Dict, state: Dict) -> str:
        pnl = ctx.get("pnl", 0)
        direction = ctx.get("direction", "unknown")
        reason = ctx.get("exit_reason", "unknown")
        daily_pnl = state.get("daily_pnl", 0)
        regime = self._get_regime_context(state)
        pressure = self._get_pressure_description(state)

        # Calculate consecutive streak context
        consecutive_wins = state.get("consecutive_wins", 0)
        consecutive_losses = state.get("consecutive_losses", 0)
        streak_note = ""
        if pnl > 0 and consecutive_wins >= 2:
            streak_note = f"That's {consecutive_wins} wins in a row!"
        elif pnl < 0 and consecutive_losses >= 2:
            streak_note = f"That's {consecutive_losses} losses in a row - might be worth a breather."

        # Win rate context
        daily_trades = state.get("daily_trades", 0)
        daily_wins = state.get("daily_wins", 0)
        win_rate_pct = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0

        return f"""Narrate this trade exit in EXACTLY 1 sentence (max 25 words):
{direction.upper()} closed: ${pnl:+.2f} ({reason}). Daily P&L: ${daily_pnl:+.2f}.
{f'{streak_note}' if streak_note else ''}

Output format: "Closed [DIRECTION]: $[P&L] ([reason]) — [brief context]."
Example: "Closed LONG: +$45.50 (take profit) — day now at +$150."
DO NOT exceed 1 sentence. Must mention the P&L amount."""

    def _signal_generated_prompt(self, ctx: Dict, state: Dict) -> str:
        signal_type = ctx.get("signal_type", "unknown")
        ml_prob = ctx.get("ml_probability", 0)
        regime = self._get_regime_context(state)
        pressure = self._get_pressure_description(state)
        session = self._get_session_name(state)

        return f"""Briefly note this signal generation (1 sentence):
- Signal Type: {signal_type}
- ML Probability: {ml_prob * 100:.0f}%
- Market: {regime} with {pressure}
- Session: {session}

One sentence noting the signal and its context.
Example: "Spotted a LONG signal with 68% ML confidence - buyer pressure building in this ranging market."
Keep it brief."""

    def _signal_rejected_prompt(self, ctx: Dict, state: Dict) -> str:
        reason = ctx.get("reason", "unknown")
        total = ctx.get("total_today", 0)
        regime = self._get_regime_context(state)

        # Get ML filter stats if ML rejection
        ml_stats = ""
        if "ml" in reason.lower():
            ml_filter = state.get("ai_status", {}).get("ml_filter", {})
            passed = ml_filter.get("passed", 0)
            skipped = ml_filter.get("skipped", 0)
            if passed + skipped > 0:
                ml_stats = f"ML has passed {passed} and blocked {skipped} signals today."

        # Get direction gating stats
        gating_stats = ""
        if "direction" in reason.lower() or "gating" in reason.lower():
            gating = state.get("ai_status", {}).get("direction_gating", {})
            blocked_dir = gating.get("blocked_direction", "")
            if blocked_dir:
                gating_stats = f"Currently blocking {blocked_dir.upper()} due to {regime} conditions."

        return f"""Explain this signal rejection in EXACTLY 1 sentence (max 20 words):
Reason: {reason.replace('_', ' ')}. Rejections today: {total}.

Output: "Skipped [signal] — [specific reason]."
Example: "Skipped LONG signal — ML confidence 28%, below threshold."
DO NOT exceed 1 sentence."""

    def _circuit_breaker_prompt(self, ctx: Dict, state: Dict) -> str:
        reason = ctx.get("reason", "protective stop")
        cooldown = ctx.get("cooldown_seconds", 0)

        return f"""Circuit breaker alert in EXACTLY 1 sentence (max 20 words):
Reason: {reason}. Cooldown: {cooldown // 60} minutes.

Output: "Circuit breaker triggered — [reason]. Pausing [X] minutes."
Example: "Circuit breaker triggered — daily loss limit. Pausing 30 minutes."
DO NOT exceed 1 sentence."""

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

    def template_narration(self, event_type: str, context: Dict[str, Any], state: Optional[Dict[str, Any]] = None) -> str:
        """
        Fallback template-based narration when LLM is unavailable.
        Returns human-readable text without AI generation.
        Enhanced with context when state is available.
        """
        state = state or {}

        templates = {
            "trade_entered": lambda ctx: self._template_trade_entered(ctx, state),
            "trade_exited": lambda ctx: self._template_trade_exited(ctx, state),
            "signal_rejected": lambda ctx: self._template_signal_rejected(ctx, state),
            "circuit_breaker_triggered": self._template_circuit_breaker,
            "direction_blocked": self._template_direction_blocked,
        }

        template_fn = templates.get(event_type, self._template_generic)
        return template_fn(context)

    def _template_trade_entered(self, ctx: Dict, state: Dict = None) -> str:
        state = state or {}
        direction = ctx.get("direction", "").upper()
        entry_price = ctx.get("entry_price", 0)
        count = ctx.get("count", 1)

        # Add context if available
        regime = self._get_regime_context(state) if state else "market"
        pressure = self._get_pressure_description(state) if state else ""
        ml_prob = state.get("last_signal_decision", {}).get("ml_probability", 0) if state else 0

        parts = [f"Entered {direction} at {entry_price}"]
        if regime and regime != "uncertain":
            parts.append(f"in a {regime} market")
        if pressure and pressure != "balanced flow":
            parts.append(f"with {pressure}")
        if ml_prob > 0:
            parts.append(f"ML confidence {ml_prob * 100:.0f}%")

        return ". ".join([" ".join(parts[:2])] + parts[2:]) + "."

    def _template_trade_exited(self, ctx: Dict, state: Dict = None) -> str:
        state = state or {}
        pnl = ctx.get("pnl", 0)
        direction = ctx.get("direction", "").upper()
        reason = ctx.get("exit_reason", "").replace("_", " ")
        sign = "+" if pnl >= 0 else ""

        daily_pnl = state.get("daily_pnl", 0) if state else 0
        result = f"Closed {direction}: {sign}${pnl:.2f}"
        if reason:
            result += f" ({reason})"
        if state:
            result += f". Day at ${daily_pnl:+.2f}."
        return result

    def _template_signal_rejected(self, ctx: Dict, state: Dict = None) -> str:
        state = state or {}
        reason = ctx.get("reason", "").replace("_", " ").title()
        total = ctx.get("total_today", 0)

        result = f"Signal blocked by {reason}"
        if total > 1:
            result += f" ({total} rejections today)"
        return result + "."

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
