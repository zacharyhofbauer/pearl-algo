"""
Doctor handler: trading diagnostics, signal rejections, risk metrics, performance rollup.

Pulls data from /api/state and formats a diagnostic report for developers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pearlalgo.telegram.formatters.messages import format_pnl, format_error_message
from pearlalgo.telegram.formatters.keyboards import back_to_menu_keyboard
from pearlalgo.telegram.utils import escape_html, reply_html as _reply

logger = logging.getLogger(__name__)


def _bar(filled: int, total: int, width: int = 10) -> str:
    """Render a simple text progress bar."""
    if total <= 0:
        return "▱" * width
    ratio = min(max(filled / total, 0), 1)
    n = round(ratio * width)
    return "▰" * n + "▱" * (width - n)


def _format_doctor(data: Dict[str, Any]) -> str:
    """Build a doctor diagnostic report from /api/state."""
    lines = ["<b>🩺 Doctor — Trading Diagnostics</b>\n"]

    # -- Signal rejections (24h) --
    rej = data.get("signal_rejections_24h")
    if rej and isinstance(rej, dict):
        total_rej = rej.get("total", 0)
        lines.append(f"<b>Signal Rejections (24h):</b> {total_rej}")
        reasons = rej.get("by_reason", {})
        if reasons and isinstance(reasons, dict):
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1])[:8]:
                lines.append(f"  {escape_html(reason)}: {count}")
        lines.append("")

    # -- Last signal decision --
    last_sig = data.get("last_signal_decision")
    if last_sig and isinstance(last_sig, dict):
        action = last_sig.get("action", "?")
        reason = last_sig.get("reason", "")
        sig_type = last_sig.get("signal_type", "")
        direction = last_sig.get("direction", "")
        icon = "✅" if action == "execute" else "❌"
        lines.append(f"<b>Last Signal:</b> {icon} {escape_html(action)}")
        if sig_type:
            lines.append(f"  Type: {escape_html(sig_type)} {escape_html(direction)}")
        if reason:
            lines.append(f"  Reason: {escape_html(reason)}")
        lines.append("")

    # -- Risk metrics --
    risk = data.get("risk_metrics")
    if risk and isinstance(risk, dict):
        lines.append("<b>Risk Metrics:</b>")
        sharpe = risk.get("sharpe")
        sortino = risk.get("sortino")
        pf = risk.get("profit_factor")
        expectancy = risk.get("expectancy")
        max_dd = risk.get("max_drawdown")
        dd_pct = risk.get("drawdown_pct")
        if sharpe is not None:
            lines.append(f"  Sharpe: {sharpe:.2f}")
        if sortino is not None:
            lines.append(f"  Sortino: {sortino:.2f}")
        if pf is not None:
            lines.append(f"  Profit Factor: {pf:.2f}")
        if expectancy is not None:
            lines.append(f"  Expectancy: ${expectancy:,.2f}")
        if max_dd is not None:
            dd_str = f"${max_dd:,.0f}"
            if dd_pct is not None:
                dd_str += f" ({dd_pct:.1f}%)"
            lines.append(f"  Max Drawdown: {dd_str}")
        avg_win = risk.get("avg_win")
        avg_loss = risk.get("avg_loss")
        if avg_win is not None and avg_loss is not None:
            lines.append(f"  Avg Win: ${avg_win:,.2f}  Avg Loss: ${avg_loss:,.2f}")
        best = risk.get("best_trade")
        worst = risk.get("worst_trade")
        if best is not None and worst is not None:
            lines.append(f"  Best: ${best:,.2f}  Worst: ${worst:,.2f}")
        streak = risk.get("current_streak")
        max_w = risk.get("max_win_streak")
        max_l = risk.get("max_loss_streak")
        if streak is not None:
            lines.append(f"  Streak: {streak}  Max W: {max_w}  Max L: {max_l}")
        lines.append("")

    # -- Performance summary --
    perf = data.get("performance")
    if perf and isinstance(perf, dict):
        lines.append("<b>Performance:</b>")
        for period in ("24h", "72h", "30d"):
            p = perf.get(period, {})
            if p and isinstance(p, dict):
                pnl = p.get("pnl", 0)
                trades = p.get("trades", 0)
                wr = p.get("win_rate", 0)
                if trades > 0:
                    lines.append(f"  {period}: {format_pnl(pnl)}  {trades} trades  {wr:.0f}% WR")
        lines.append("")

    # -- Shadow counters --
    shadow = data.get("shadow_counters")
    if shadow and isinstance(shadow, dict):
        shadow_trades = shadow.get("total", 0)
        if shadow_trades > 0:
            lines.append(f"<b>Shadow Trades:</b> {shadow_trades}")
            sw = shadow.get("wins", 0)
            sl = shadow.get("losses", 0)
            sp = shadow.get("pnl", 0)
            if sw + sl > 0:
                lines.append(f"  W/L: {sw}/{sl}  P&L: {format_pnl(sp)}")
            lines.append("")

    # -- ML filter performance --
    ml = data.get("ml_filter_performance")
    if ml and isinstance(ml, dict):
        ml_enabled = ml.get("enabled", False)
        if ml_enabled:
            lines.append("<b>ML Filter:</b>")
            mode = ml.get("mode", "?")
            predictions = ml.get("total_predictions", 0)
            accuracy = ml.get("accuracy")
            lines.append(f"  Mode: {escape_html(mode)}  Predictions: {predictions}")
            if accuracy is not None:
                lines.append(f"  Accuracy: {accuracy:.1%}")
            lines.append("")

    # -- Cadence metrics --
    cadence = data.get("cadence_metrics")
    if cadence and isinstance(cadence, dict):
        cycle_ms = cadence.get("avg_cycle_ms")
        if cycle_ms is not None:
            lines.append(f"<b>Avg Cycle:</b> {cycle_ms:.0f}ms")
        mode = cadence.get("cadence_mode", "")
        if mode:
            lines.append(f"<b>Cadence:</b> {escape_html(mode)}")

    if len(lines) <= 2:
        lines.append("<i>No diagnostic data available — agent may be stopped</i>")

    return "\n".join(lines)


async def handle_doctor(update: Any, context: Any) -> None:
    """Handle /doctor command -- show trading diagnostics."""
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

        msg = _format_doctor(data)
        keyboard = back_to_menu_keyboard()
        await _reply(update, msg, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Doctor handler error: {e}", exc_info=True)
        await _reply(update, format_error_message(f"Unable to reach agent: {e}"))
