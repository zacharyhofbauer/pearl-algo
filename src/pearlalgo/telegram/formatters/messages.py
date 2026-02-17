"""
Clean message formatting for Telegram responses.

All messages use HTML parse mode for consistent formatting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pearlalgo.telegram.utils import escape_html
from pearlalgo.utils.formatting import format_pnl as _canonical_pnl


def format_pnl(pnl: float) -> str:
    """Format a P&L value with emoji, sign, and currency."""
    emoji, text = _canonical_pnl(pnl)
    return f"{emoji} {text}"


def format_win_rate(wins: int, losses: int) -> str:
    """Format win rate as percentage."""
    total = wins + losses
    if total == 0:
        return "N/A"
    rate = wins / total
    return f"{rate:.0%} ({wins}W/{losses}L)"


def format_position(pos: Dict[str, Any]) -> str:
    """Format a single open position as an HTML line."""
    direction = escape_html(str(pos.get("direction", "?")).upper())
    entry = pos.get("entry_price", 0)
    size = pos.get("position_size", 1)
    signal_id = escape_html(str(pos.get("signal_id", "?"))[:12])

    return (
        f"  {direction} {size}x @ {entry:,.2f}"
        f"  <i>({signal_id})</i>"
    )


def format_status_message(data: Dict[str, Any]) -> str:
    """Format a full status response into an HTML message.

    Pulls from /api/state which has challenge, daily_pnl, performance, etc.
    """
    running = data.get("running", False)
    paused = data.get("paused", False)
    market_open = data.get("futures_market_open", False)

    if paused:
        state_str = "⏸️ Paused"
    elif running:
        state_str = "🟢 Running"
    else:
        state_str = "🔴 Stopped"

    market_str = "🟢 Open" if market_open else "🔴 Closed"

    lines = [
        "<b>📊 Tradovate Paper</b>\n",
        f"<b>Agent:</b> {state_str}",
        f"<b>Market:</b> {market_str}",
    ]

    # Challenge / balance data
    challenge = data.get("challenge")
    if challenge and isinstance(challenge, dict):
        balance = challenge.get("current_balance")
        total_pnl = challenge.get("pnl")
        trades = challenge.get("trades", 0)
        wins = challenge.get("wins", 0)
        wr = challenge.get("win_rate")

        if balance is not None:
            lines.append(f"\n<b>Balance:</b> ${balance:,.2f}")
        if total_pnl is not None:
            lines.append(f"<b>Total P&amp;L:</b> {format_pnl(total_pnl)}")
        if trades:
            wr_str = f"  ({wr:.1f}%)" if wr is not None else ""
            lines.append(f"<b>Trades:</b> {trades} ({wins}W/{trades - wins}L){wr_str}")

    # Today's P&L
    daily_pnl = data.get("daily_pnl")
    daily_trades = data.get("daily_trades", 0)
    daily_wins = data.get("daily_wins", 0)
    daily_losses = data.get("daily_losses", 0)
    if daily_pnl is not None:
        lines.append(f"\n<b>Today:</b> {format_pnl(daily_pnl)}")
        if daily_trades > 0:
            lines.append(f"  {daily_trades} trades ({daily_wins}W/{daily_losses}L)")

    # Active positions
    active_count = data.get("active_trades_count", 0)
    unrealized = data.get("active_trades_unrealized_pnl")
    if active_count > 0:
        upnl_str = f"  {format_pnl(unrealized)}" if unrealized is not None else ""
        lines.append(f"\n<b>Open Positions:</b> {active_count}{upnl_str}")
    else:
        lines.append("\n<i>No open positions</i>")

    # AI status
    ai = data.get("ai_status")
    if ai and isinstance(ai, dict):
        ai_mode = ai.get("mode", "")
        ai_headline = ai.get("headline", "")
        if ai_mode:
            lines.append(f"\n<b>AI:</b> {escape_html(ai_mode)}")
        if ai_headline:
            lines.append(f"  {escape_html(ai_headline[:100])}")

    return "\n".join(lines)


def format_trades_message(trades: List[Dict[str, Any]], limit: int = 20) -> str:
    """Format recent trades into an HTML message."""
    if not trades:
        return "<i>No recent trades</i>"

    lines = [f"<b>Recent Trades ({min(len(trades), limit)}):</b>\n"]

    for trade in trades[:limit]:
        direction = str(trade.get("direction", "?")).upper()
        entry = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        pnl = trade.get("pnl", 0)
        is_win = trade.get("is_win", False)
        reason = escape_html(str(trade.get("exit_reason", "?")))

        icon = "✅" if is_win else "❌"
        pnl_str = format_pnl(pnl)

        lines.append(
            f"{icon} {direction} {entry:,.2f} → {exit_price:,.2f}"
            f"  {pnl_str}  ({reason})"
        )

    return "\n".join(lines)


def format_error_message(error: str) -> str:
    """Format an error message for the user."""
    return f"⚠️ <b>Error:</b> {escape_html(error)}"


def format_control_response(action: str, success: bool, detail: str = "") -> str:
    """Format a control action response."""
    icon = "✅" if success else "❌"
    msg = f"{icon} <b>{escape_html(action.replace('_', ' ').title())}</b>"
    if detail:
        msg += f"\n{escape_html(detail)}"
    return msg
