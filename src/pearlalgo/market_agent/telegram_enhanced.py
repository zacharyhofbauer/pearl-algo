"""
Enhanced Telegram Formatting - Pearl AI style messaging with reasoning.

This module provides enhanced formatting functions for Telegram messages
that include transparent reasoning, filter explanations, and learning reports.

Features:
- Signal messages with reasoning explanations
- Filter transparency notifications
- Learning reports
- Memory-augmented context
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pearlalgo.ai.thinking import DecisionTrace, ThinkingLevel
from pearlalgo.learning.opportunity_tracker import SignalOpportunity, OpportunityDecision
from pearlalgo.learning.filter_analytics import FilterPerformanceReport, FilterAdjustmentRecommendation
from pearlalgo.utils.telegram_alerts import (
    sanitize_telegram_markdown,
    format_pnl,
    _format_currency,
    _format_percentage,
)


def format_signal_with_reasoning(
    signal: dict[str, Any],
    trace: Optional[DecisionTrace] = None,
    memory_context: Optional[str] = None,
    compact: bool = False,
) -> str:
    """
    Format a signal message with reasoning explanation.
    
    Args:
        signal: Signal dictionary with direction, entry, stop, target, etc.
        trace: Optional decision trace with full reasoning
        memory_context: Optional context from Pearl's memory
        compact: If True, use compact format for mobile
        
    Returns:
        Formatted Telegram message
    """
    direction = signal.get("direction", "UNKNOWN")
    entry = signal.get("entry_price", signal.get("entry", 0))
    stop = signal.get("stop_loss", signal.get("stop", 0))
    target = signal.get("take_profit", signal.get("target", 0))
    confidence = signal.get("confidence", 0)
    risk_reward = signal.get("risk_reward", 0)
    signal_type = signal.get("signal_type", "")
    
    # Direction emoji
    dir_emoji = "📈" if direction == "LONG" else "📉"
    
    lines = []
    
    # Header
    lines.append(f"{dir_emoji} *{direction} Signal Generated*")
    lines.append("")
    
    # Price levels
    lines.append(f"*Entry:* {entry:.2f} | *Stop:* {stop:.2f} | *Target:* {target:.2f}")
    lines.append(f"*Confidence:* {confidence:.0%} | *R:R:* {risk_reward:.1f}")
    
    if not compact:
        # Add reasoning section
        if trace:
            lines.append("")
            lines.append("*Why this signal:*")
            
            # Add key indicators
            for ind in trace.indicators[:4]:  # Top 4 indicators
                emoji = "✅" if ind.bullish else ("❌" if ind.bullish is False else "⚪")
                lines.append(f"  {emoji} {ind.name}: {ind.interpretation}")
            
            # Add any cautions
            cautions = []
            
            # Check key levels
            for kl in trace.key_levels:
                if kl.distance_pct < 0.003:  # Within 0.3%
                    level_type = "support" if kl.is_support else "resistance"
                    cautions.append(f"{kl.level_type} ({level_type}) {kl.distance_pct:.2%} away")
            
            # Check blocking filters (should be empty for allowed signals)
            blocking = trace.get_blocking_filters()
            if blocking:
                for f in blocking:
                    cautions.append(f"Filter warning: {f.name}")
            
            if cautions:
                lines.append("")
                lines.append("*Cautions:*")
                for c in cautions:
                    lines.append(f"  ⚠️ {c}")
        
        # Add memory context if available
        if memory_context:
            lines.append("")
            lines.append(f"*Memory:* {memory_context}")
    
    # Escape for Telegram Markdown
    return sanitize_telegram_markdown("\n".join(lines))


def format_filtered_signal_notification(
    opportunity: SignalOpportunity,
    compact: bool = False,
) -> str:
    """
    Format a notification about a filtered signal.
    
    This helps with transparency - shows what was filtered and why.
    
    Args:
        opportunity: The filtered signal opportunity
        compact: If True, use compact format
        
    Returns:
        Formatted Telegram message
    """
    direction = opportunity.direction
    price = opportunity.price
    blocking_filter = opportunity.blocking_filter or "unknown"
    
    # Get the blocking filter reason
    blocking_reason = "Unknown reason"
    for f in opportunity.filters_evaluated:
        if f.name == blocking_filter and not f.passed:
            blocking_reason = f.reason
            break
    
    lines = []
    
    # Header
    lines.append("🔒 *Signal Filtered* (logged for learning)")
    lines.append("")
    
    # Basic info
    lines.append(f"*{direction}* at {price:.2f} blocked by: `{blocking_filter}`")
    lines.append(f"*Reason:* {blocking_reason}")
    
    if not compact:
        lines.append("")
        lines.append("_Tracking outcome for filter effectiveness analysis._")
    
    return sanitize_telegram_markdown("\n".join(lines))


def format_daily_learning_report(
    summary: dict[str, Any],
    filter_reports: list[FilterPerformanceReport],
    recommendations: list[FilterAdjustmentRecommendation],
    period_days: int = 1,
) -> str:
    """
    Format a daily learning report for Telegram.
    
    Args:
        summary: Summary from opportunity tracker
        filter_reports: List of filter performance reports
        recommendations: List of recommendations
        period_days: Period covered
        
    Returns:
        Formatted Telegram message
    """
    lines = []
    
    # Header
    date_str = datetime.now(timezone.utc).strftime("%b %d, %Y")
    lines.append(f"📊 *Pearl Learning Report - {date_str}*")
    lines.append("")
    
    # Trading summary
    total_opportunities = summary.get("total_opportunities", 0)
    allowed = summary.get("allowed", 0)
    blocked = summary.get("blocked", 0)
    
    lines.append(f"*Opportunities:* {total_opportunities}")
    lines.append(f"  • Allowed: {allowed}")
    lines.append(f"  • Filtered: {blocked}")
    
    # Hypothetical outcomes for filtered
    if blocked > 0:
        would_have_won = summary.get("blocked_would_have_won", 0)
        would_have_lost = summary.get("blocked_would_have_lost", 0)
        hypothetical_wr = summary.get("blocked_hypothetical_win_rate", 0)
        
        lines.append("")
        lines.append("*Filtered Signals Analysis:*")
        lines.append(f"  • Would have won: {would_have_won} ({hypothetical_wr:.0%})")
        lines.append(f"  • Would have lost: {would_have_lost}")
        
        # P&L impact
        saved = summary.get("saved_pnl", 0)
        missed = summary.get("missed_pnl", 0)
        net = summary.get("net_filter_value", 0)
        
        net_emoji = "✅" if net >= 0 else "⚠️"
        lines.append(f"  • Saved P&L: ${saved:+.0f}")
        lines.append(f"  • Missed P&L: ${missed:.0f}")
        lines.append(f"  {net_emoji} *Net Filter Value:* ${net:+.0f}")
    
    # Filter performance
    if filter_reports:
        lines.append("")
        lines.append("*Filter Performance:*")
        
        # Sort by effectiveness
        sorted_reports = sorted(filter_reports, key=lambda r: r.effectiveness_score, reverse=True)
        
        for report in sorted_reports[:5]:  # Top 5
            eff_emoji = "🟢" if report.effectiveness_score > 0.5 else ("🟡" if report.effectiveness_score > 0.3 else "🔴")
            lines.append(f"  {eff_emoji} {report.filter_name}: {report.effectiveness_score:.0%} effective")
    
    # Recommendations
    if recommendations:
        lines.append("")
        lines.append("*Recommendations:*")
        
        for rec in recommendations[:3]:  # Top 3
            if rec.adjustment_type.value == "relax":
                lines.append(f"  💡 Consider relaxing `{rec.filter_name}`")
                lines.append(f"     Hypothetical WR: {rec.estimated_additional_wins / (rec.estimated_additional_wins + rec.estimated_additional_losses) * 100:.0f}%")
            elif rec.adjustment_type.value == "tighten":
                lines.append(f"  🔧 Consider tightening `{rec.filter_name}`")
    
    return sanitize_telegram_markdown("\n".join(lines))


def format_trade_analysis(
    trade: dict[str, Any],
    trace: Optional[DecisionTrace] = None,
    similar_trades: list[dict[str, Any]] = None,
) -> str:
    """
    Format a trade analysis message with context.
    
    Args:
        trade: Trade dictionary
        trace: Decision trace from when signal was generated
        similar_trades: Similar historical trades for context
        
    Returns:
        Formatted Telegram message
    """
    similar_trades = similar_trades or []
    
    direction = trade.get("direction", "UNKNOWN")
    entry = trade.get("entry_price", 0)
    exit_price = trade.get("exit_price", 0)
    pnl = trade.get("pnl", 0)
    is_win = pnl > 0
    
    result_emoji = "✅" if is_win else "❌"
    
    lines = []
    
    # Header
    lines.append(f"{result_emoji} *Trade Analysis*")
    lines.append("")
    
    # Trade details
    lines.append(f"*Direction:* {direction}")
    lines.append(f"*Entry:* {entry:.2f} → *Exit:* {exit_price:.2f}")
    lines.append(f"*P&L:* {format_pnl(pnl)}")
    
    # Add reasoning from trace
    if trace:
        lines.append("")
        lines.append("*Entry Reasoning:*")
        for step in trace.thinking_steps[:3]:
            lines.append(f"  → {step.content}")
    
    # Similar trades context
    if similar_trades:
        wins = sum(1 for t in similar_trades if t.get("pnl", 0) > 0)
        total = len(similar_trades)
        wr = wins / total if total > 0 else 0
        
        lines.append("")
        lines.append(f"*Similar Setups ({total} trades):*")
        lines.append(f"  Win rate: {wr:.0%}")
        
        if is_win:
            lines.append(f"  _This trade aligned with historical patterns._")
        else:
            lines.append(f"  _Review if conditions matched historical winners._")
    
    return sanitize_telegram_markdown("\n".join(lines))


def format_memory_context(
    recent_episodes: list[dict[str, Any]],
    relevant_knowledge: list[dict[str, Any]],
) -> str:
    """
    Format memory context for inclusion in messages.
    
    Args:
        recent_episodes: Recent relevant episodes
        relevant_knowledge: Relevant knowledge items
        
    Returns:
        Formatted context string
    """
    parts = []
    
    if relevant_knowledge:
        insights = [k.get("insight", "") for k in relevant_knowledge[:2]]
        if insights:
            parts.append(f"Known: {'; '.join(insights)}")
    
    if recent_episodes:
        # Summarize recent similar events
        wins = sum(1 for e in recent_episodes if e.get("event_type") == "trade_win")
        losses = sum(1 for e in recent_episodes if e.get("event_type") == "trade_loss")
        
        if wins + losses > 0:
            parts.append(f"Recent similar: {wins}W/{losses}L")
    
    return " | ".join(parts) if parts else ""


def format_thinking_trace_compact(trace: DecisionTrace) -> str:
    """
    Format a decision trace in compact form for Telegram.
    
    Args:
        trace: Decision trace to format
        
    Returns:
        Compact formatted string
    """
    lines = []
    
    lines.append(f"🧠 *Thinking:* {trace.direction} at {trace.price:.2f}")
    
    # Key observations
    for step in trace.thinking_steps[:3]:
        lines.append(f"  → {step.content[:50]}...")
    
    # Decision
    decision_emoji = "✅" if trace.decision == "ALLOW" else "🚫"
    lines.append(f"{decision_emoji} *Decision:* {trace.decision} ({trace.final_confidence:.0%})")
    
    return sanitize_telegram_markdown("\n".join(lines))


def create_signal_keyboard_with_details(
    signal_id: str,
    opportunity_id: Optional[str] = None,
) -> list[list[dict[str, str]]]:
    """
    Create an inline keyboard for signal messages with detail options.
    
    Args:
        signal_id: Signal ID
        opportunity_id: Optional opportunity ID for tracking
        
    Returns:
        Inline keyboard structure for Telegram
    """
    keyboard = []
    
    # First row: primary actions
    keyboard.append([
        {"text": "📊 Details", "callback_data": f"signal_detail:{signal_id}"},
        {"text": "🧠 Reasoning", "callback_data": f"signal_reasoning:{signal_id}"},
    ])
    
    # Second row: analysis
    keyboard.append([
        {"text": "📈 Similar Trades", "callback_data": f"signal_similar:{signal_id}"},
        {"text": "🔍 Filter Info", "callback_data": f"signal_filters:{signal_id}"},
    ])
    
    return keyboard


def format_filter_override_prompt(
    opportunity: SignalOpportunity,
) -> str:
    """
    Format a prompt asking if user wants to override a filter.
    
    Args:
        opportunity: The filtered opportunity
        
    Returns:
        Formatted prompt message
    """
    direction = opportunity.direction
    price = opportunity.price
    confidence = opportunity.confidence
    blocking_filter = opportunity.blocking_filter or "unknown"
    
    lines = []
    
    lines.append("⚠️ *Filter Override Request*")
    lines.append("")
    lines.append(f"Signal: *{direction}* at {price:.2f}")
    lines.append(f"Confidence: {confidence:.0%}")
    lines.append(f"Blocked by: `{blocking_filter}`")
    lines.append("")
    lines.append("_Do you want to override this filter?_")
    lines.append("_The outcome will be tracked for learning._")
    
    return sanitize_telegram_markdown("\n".join(lines))
