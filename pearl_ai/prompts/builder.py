"""
Pearl AI Prompt Builder - Constructs prompts from templates and context.

Extracts prompt assembly logic from PearlBrain so that prompt construction
is testable independently of the orchestrator.
"""

import os
from typing import Any, Dict, List, Optional

from .loader import get_prompt_registry


def build_deep_user_prompt(
    query: str,
    context: Dict[str, Any],
    format_recent_trades_fn=None,
    format_rejections_fn=None,
) -> str:
    """
    Build the user prompt for deep (Claude) analytical responses.

    Args:
        query: The user's question.
        context: Dict with 'current_state' and optional 'trade_history'.
        format_recent_trades_fn: Optional callable to format recent trades.
        format_rejections_fn: Optional callable to format rejections.

    Returns:
        Assembled user prompt string.
    """
    state = context["current_state"]
    recent_trades = state.get("recent_exits", [])[:10]

    prompt = f"""# Current Session
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
{format_recent_trades_fn(recent_trades) if format_recent_trades_fn else _default_format_trades(recent_trades)}

# AI Status
- ML Filter: {state.get('ai_status', {}).get('ml_filter', {}).get('mode', 'off')}
- Direction Gating Blocks: {state.get('ai_status', {}).get('direction_gating', {}).get('blocks', 0)}

# Signal Rejections (24h)
{format_rejections_fn(state.get('signal_rejections_24h', {})) if format_rejections_fn else _default_format_rejections(state.get('signal_rejections_24h', {}))}"""

    # Add RAG context if available
    trade_history = context.get("trade_history", "")
    if trade_history:
        prompt += f"\n\n# Historical Trade Data\n{trade_history}"

    prompt += f"\n\n---\n\nUser Question: {query}\n\nProvide a thoughtful, data-driven response:"

    return prompt


def _default_format_trades(trades: List[Dict]) -> str:
    """Simple trade formatter when brain's formatter isn't available."""
    if not trades:
        return "No recent trades"
    lines = []
    for t in trades[:5]:
        pnl = t.get("pnl", 0)
        direction = t.get("direction", "?").upper()
        reason = t.get("exit_reason", "?")
        lines.append(f"- {direction}: ${pnl:+.2f} ({reason})")
    return "\n".join(lines)


def _default_format_rejections(rejections: Dict) -> str:
    """Simple rejections formatter."""
    if not rejections or not isinstance(rejections, dict):
        return "No rejections recorded"
    lines = []
    for reason, count in rejections.items():
        lines.append(f"- {reason}: {count}")
    return "\n".join(lines) if lines else "None"


def build_insight_prompt(state: Dict[str, Any]) -> str:
    """Build prompt for proactive insight generation."""
    return f"""Based on this trading session, provide ONE brief, actionable insight:

Daily P&L: ${state.get('daily_pnl', 0):.2f}
Trades: {state.get('daily_wins', 0)}W / {state.get('daily_losses', 0)}L
Win Rate: {state.get('daily_wins', 0) / max(state.get('daily_trades', 1), 1) * 100:.0f}%
Regime: {state.get('market_regime', {}).get('regime', 'unknown')}
Rejections: {sum(state.get('signal_rejections_24h', {}).values()) if isinstance(state.get('signal_rejections_24h'), dict) else 0}

Give a brief (1-2 sentence) observation or suggestion. Be specific and actionable."""


def build_daily_review_prompt(state: Dict[str, Any]) -> str:
    """Build prompt for end-of-day performance review."""
    return f"""Generate a brief end-of-day trading review:

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


def build_streak_coaching_prompt(
    consecutive_losses: int,
    total_loss: float,
    regime: str,
    pressure: str,
    directions: List[str],
    pattern_note: str = "",
) -> str:
    """Build prompt for losing-streak coaching."""
    return f"""A trader has {consecutive_losses} consecutive losses (${total_loss:.2f} total).
Market: {regime} regime with {pressure} pressure
Directions: {', '.join(directions)}
{f'Pattern: {pattern_note}' if pattern_note else ''}

Generate a supportive, brief coaching message (2-3 sentences):
- Acknowledge the streak without being negative or dramatic
- If there's a pattern, point it out gently
- Suggest an optional 5-minute pause
- Be supportive, not critical

Example: "Two losses in a row, both LONG in seller pressure. The market might be rotating against us. Want to step back for 5 minutes to let things settle?"
"""
