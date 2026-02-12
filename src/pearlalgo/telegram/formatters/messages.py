"""
Clean message formatting for Telegram responses.

All messages use HTML parse mode for consistent formatting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pearlalgo.telegram.utils import escape_html


def format_pnl(pnl: float) -> str:
    """Format a P&L value with sign, currency, and emoji indicator."""
    if pnl > 0:
        return f"+${pnl:,.2f}"
    elif pnl < 0:
        return f"-${abs(pnl):,.2f}"
    return "$0.00"


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

    Expected data keys: agent_state, symbol, pnl, positions, account
    """
    account = data.get("account", {})
    badge = account.get("badge", "")
    display_name = escape_html(account.get("display_name", "Agent"))

    state = data.get("agent_state", "unknown")
    state_emoji = {"running": "🟢", "stopped": "🔴", "paused": "⏸️"}.get(state, "⚪")

    symbol = escape_html(str(data.get("symbol", "MNQ")))

    # P&L section
    pnl_data = data.get("pnl", {})
    total_pnl = pnl_data.get("total_pnl", 0.0)
    wins = pnl_data.get("wins", 0)
    losses = pnl_data.get("losses", 0)

    lines = [
        f"<b>{display_name}</b> [{badge}]",
        f"{state_emoji} {state.capitalize()} | {symbol}",
        "",
        f"<b>P&amp;L:</b> {format_pnl(total_pnl)}",
        f"<b>Win Rate:</b> {format_win_rate(wins, losses)}",
    ]

    # Open positions
    positions = data.get("positions", [])
    if positions:
        lines.append(f"\n<b>Open Positions ({len(positions)}):</b>")
        for pos in positions[:10]:  # Limit to 10
            lines.append(format_position(pos))
        if len(positions) > 10:
            lines.append(f"  ... and {len(positions) - 10} more")
    else:
        lines.append("\n<i>No open positions</i>")

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
