"""
Health handler: agent health, connectivity, data freshness, system diagnostics.

Fetches /api/state and evaluates health signals for a quick system overview.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from pearlalgo.telegram.formatters.messages import format_error_message
from pearlalgo.telegram.formatters.keyboards import back_to_menu_keyboard
from pearlalgo.telegram.utils import escape_html, reply_html as _reply

logger = logging.getLogger(__name__)


def _ago(iso: str) -> str:
    """Return a human-readable 'X ago' string from an ISO timestamp."""
    try:
        ts = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 0:
            return "just now"
        if s < 60:
            return f"{s}s ago"
        if s < 3600:
            return f"{s // 60}m ago"
        if s < 86400:
            return f"{s // 3600}h {(s % 3600) // 60}m ago"
        return f"{s // 86400}d ago"
    except Exception:
        return "unknown"


def _dot(ok: bool) -> str:
    return "🟢" if ok else "🔴"


def _format_health(data: Dict[str, Any]) -> str:
    """Build health report from /api/state response."""
    lines = ["<b>💚 System Health</b>\n"]

    running = data.get("running", False)
    paused = data.get("paused", False)
    data_fresh = data.get("data_fresh", False)
    market_open = data.get("futures_market_open", False)
    last_updated = data.get("last_updated", "")

    if paused:
        state_str = "⏸️ Paused"
    elif running:
        state_str = "🟢 Running"
    else:
        state_str = "🔴 Stopped"

    lines.append(f"<b>Agent:</b> {state_str}")
    lines.append(f"<b>Market:</b> {_dot(market_open)} {'Open' if market_open else 'Closed'}")
    lines.append(f"<b>Data:</b> {_dot(data_fresh)} {'Fresh' if data_fresh else 'Stale'}")

    if last_updated:
        lines.append(f"<b>Updated:</b> {_ago(last_updated)}")

    # Connection health
    conn = data.get("connection_health")
    if conn and isinstance(conn, dict):
        ws_ok = conn.get("websocket_connected", False)
        api_ok = conn.get("api_reachable", True)
        lines.append("")
        lines.append(f"<b>WebSocket:</b> {_dot(ws_ok)} {'Connected' if ws_ok else 'Disconnected'}")
        lines.append(f"<b>API:</b> {_dot(api_ok)} {'Reachable' if api_ok else 'Unreachable'}")
        reconnects = conn.get("reconnect_count", 0)
        if reconnects:
            lines.append(f"<b>Reconnects:</b> {reconnects}")

    # Data quality
    dq = data.get("data_quality")
    if dq and isinstance(dq, dict):
        lines.append("")
        lines.append("<b>Data Quality:</b>")
        gaps = dq.get("gaps_detected", 0)
        staleness = dq.get("staleness_seconds", 0)
        lines.append(f"  Gaps: {gaps}")
        if staleness:
            lines.append(f"  Staleness: {staleness:.0f}s")

    # Circuit breaker
    cb = data.get("circuit_breaker")
    if cb and isinstance(cb, dict):
        tripped = cb.get("tripped", False)
        reason = cb.get("reason", "")
        lines.append("")
        if tripped:
            lines.append(f"<b>Circuit Breaker:</b> 🔴 TRIPPED — {escape_html(reason)}")
        else:
            lines.append("<b>Circuit Breaker:</b> 🟢 OK")

    # Error summary
    errs = data.get("error_summary")
    if errs and isinstance(errs, dict):
        total = errs.get("total_errors_24h", 0)
        if total > 0:
            lines.append("")
            lines.append(f"<b>Errors (24h):</b> {total}")
            by_cat = errs.get("by_category", {})
            if by_cat and isinstance(by_cat, dict):
                for cat, count in sorted(by_cat.items(), key=lambda x: -x[1])[:5]:
                    lines.append(f"  {escape_html(cat)}: {count}")

    # Gateway status
    gw = data.get("gateway_status")
    if gw and isinstance(gw, dict):
        gw_connected = gw.get("connected", False)
        lines.append("")
        lines.append(f"<b>Gateway:</b> {_dot(gw_connected)} {escape_html(gw.get('status', 'unknown'))}")

    return "\n".join(lines)


async def handle_health(update: Any, context: Any) -> None:
    """Handle /health command -- show system health dashboard."""
    try:
        api_url = context.bot_data.get("api_url", "http://localhost:8001")
        api_key = context.bot_data.get("api_key", "")

        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{api_url}/api/state",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    await _reply(update, format_error_message(f"Agent returned {resp.status}: {text[:200]}"))
                    return
                data = await resp.json()

        msg = _format_health(data)
        keyboard = back_to_menu_keyboard()
        await _reply(update, msg, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Health handler error: {e}", exc_info=True)
        await _reply(update, format_error_message(f"Unable to reach agent: {e}"))
