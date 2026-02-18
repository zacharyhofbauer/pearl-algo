"""
Clean message formatting for Telegram responses.

All messages use HTML parse mode for consistent formatting.
Mirrors the web app dashboard panels for a unified experience.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pearlalgo.telegram.utils import escape_html
from pearlalgo.utils.formatting import format_pnl as _canonical_pnl


# ── Shared helpers ────────────────────────────────────────────────────────

def format_pnl(pnl: float) -> str:
    """Format a P&L value with emoji, sign, and currency."""
    emoji, text = _canonical_pnl(pnl)
    return f"{emoji} {text}"


def _pnl_plain(pnl: float) -> str:
    """P&L without emoji — just +$X or -$X."""
    sign = "+" if pnl >= 0 else "-"
    return f"{sign}${abs(pnl):,.2f}"


def _pnl_color(pnl: float) -> str:
    """P&L with color emoji prefix."""
    if pnl >= 0:
        return f"🟢 +${pnl:,.2f}"
    return f"🔴 -${abs(pnl):,.2f}"


def _ago(iso: str) -> str:
    """Human-readable time-ago from ISO timestamp."""
    try:
        ts = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        s = int((datetime.now(timezone.utc) - dt).total_seconds())
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
        return "—"


def _dot(ok: bool) -> str:
    return "🟢" if ok else "🔴"


def _bar(ratio: float, width: int = 10) -> str:
    """Text progress bar ▰▱."""
    ratio = max(0.0, min(1.0, ratio))
    n = round(ratio * width)
    return "▰" * n + "▱" * (width - n)


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


# ── /status — mirrors AccountStrip + header badges ───────────────────────

def format_status_message(data: Dict[str, Any]) -> str:
    """Full status: balance, P&L, positions, AI — mirrors the dashboard AccountStrip."""
    running = data.get("running", False)
    paused = data.get("paused", False)
    market_open = data.get("futures_market_open", False)

    if paused:
        state_str = "⏸️ Paused"
    elif running:
        state_str = "🟢 Running"
    else:
        state_str = "🔴 Stopped"

    lines = [
        "<b>📊 Tradovate Paper — MNQ</b>\n",
        f"Agent: {state_str}  ·  Market: {_dot(market_open)} {'Open' if market_open else 'Closed'}",
    ]

    # Data freshness + gateway (mirroring header badges)
    data_fresh = data.get("data_fresh", False)
    gw = data.get("gateway_status") or {}
    gw_status = gw.get("status", "")
    badges = []
    badges.append(f"Data {_dot(data_fresh)}")
    if gw_status:
        gw_ok = gw.get("connected", False)
        badges.append(f"GW {_dot(gw_ok)}")
    if badges:
        lines.append("  ".join(badges))

    # AccountStrip: Balance, Today, Total P&L, Trades, Win Rate
    challenge = data.get("challenge")
    if challenge and isinstance(challenge, dict):
        balance = challenge.get("current_balance")
        total_pnl = challenge.get("pnl")
        trades = challenge.get("trades", 0)
        wins = challenge.get("wins", 0)
        wr = challenge.get("win_rate")

        lines.append("")
        if balance is not None:
            lines.append(f"<b>Balance:</b>  ${balance:,.2f}")
        if total_pnl is not None:
            lines.append(f"<b>Total P&amp;L:</b>  {_pnl_color(total_pnl)}")
        if trades:
            wr_str = f"  ·  {wr:.1f}% WR" if wr is not None else ""
            lines.append(f"<b>Trades:</b>  {trades} ({wins}W/{trades - wins}L){wr_str}")

    # Today's session
    daily_pnl = data.get("daily_pnl")
    daily_trades = data.get("daily_trades", 0)
    daily_wins = data.get("daily_wins", 0)
    daily_losses = data.get("daily_losses", 0)
    if daily_pnl is not None:
        lines.append("")
        lines.append(f"<b>Today:</b>  {_pnl_color(daily_pnl)}")
        if daily_trades > 0:
            lines.append(f"  {daily_trades} trades ({daily_wins}W/{daily_losses}L)")

    # Open positions
    active_count = data.get("active_trades_count", 0)
    unrealized = data.get("active_trades_unrealized_pnl")
    if active_count > 0:
        upnl_str = f"  {_pnl_color(unrealized)}" if unrealized is not None else ""
        lines.append(f"\n<b>Open:</b>  {active_count} position{'s' if active_count != 1 else ''}{upnl_str}")
    else:
        lines.append("\n<i>No open positions</i>")

    # AI status headline
    ai = data.get("ai_status")
    if ai and isinstance(ai, dict):
        headline = ai.get("headline", "")
        if headline:
            lines.append(f"\n💡 <i>{escape_html(headline[:120])}</i>")

    return "\n".join(lines)


# ── /health — system health dashboard ────────────────────────────────────

def format_health_message(data: Dict[str, Any]) -> str:
    """System health: agent, market, connectivity, data, circuit breaker, errors."""
    running = data.get("running", False)
    paused = data.get("paused", False)
    data_fresh = data.get("data_fresh", False)
    market_open = data.get("futures_market_open", False)
    last_updated = data.get("last_updated", "")

    lines = ["<b>💚 System Health</b>\n"]

    # Agent & market
    if paused:
        lines.append("Agent: ⏸️ Paused")
    elif running:
        lines.append("Agent: 🟢 Running")
    else:
        lines.append("Agent: 🔴 Stopped")
    lines.append(f"Market: {_dot(market_open)} {'Open' if market_open else 'Closed'}")
    lines.append(f"Data: {_dot(data_fresh)} {'Fresh' if data_fresh else 'Stale'}")
    if last_updated:
        lines.append(f"Updated: {_ago(last_updated)}")

    # Execution state
    exec_state = data.get("execution_state")
    if exec_state and isinstance(exec_state, dict):
        armed = exec_state.get("armed", False)
        adapter = exec_state.get("adapter", "")
        lines.append("")
        lines.append(f"Execution: {_dot(armed)} {'Armed' if armed else 'Disarmed'}")
        if adapter:
            lines.append(f"  Adapter: {escape_html(adapter)}")

    # Gateway
    gw = data.get("gateway_status")
    if gw and isinstance(gw, dict):
        gw_connected = gw.get("connected", False)
        gw_status = gw.get("status", "unknown")
        lines.append("")
        lines.append(f"Gateway: {_dot(gw_connected)} {escape_html(gw_status)}")

    # Connection health
    conn = data.get("connection_health")
    if conn and isinstance(conn, dict):
        ws_ok = conn.get("websocket_connected", False)
        reconnects = conn.get("reconnect_count", 0)
        lines.append(f"WebSocket: {_dot(ws_ok)} {'Connected' if ws_ok else 'Disconnected'}")
        if reconnects:
            lines.append(f"  Reconnects: {reconnects}")

    # Data quality
    dq = data.get("data_quality")
    if dq and isinstance(dq, dict):
        gaps = dq.get("gaps_detected", 0)
        staleness = dq.get("staleness_seconds", 0)
        if gaps or staleness > 0:
            lines.append("")
            lines.append("<b>Data Quality:</b>")
            if gaps:
                lines.append(f"  Gaps: {gaps}")
            if staleness > 0:
                lines.append(f"  Staleness: {staleness:.0f}s")

    # Circuit breaker
    cb = data.get("circuit_breaker")
    if cb and isinstance(cb, dict):
        tripped = cb.get("tripped", False)
        reason = cb.get("reason", "")
        lines.append("")
        if tripped:
            lines.append(f"Circuit Breaker: 🔴 TRIPPED")
            if reason:
                lines.append(f"  {escape_html(reason)}")
        else:
            lines.append("Circuit Breaker: 🟢 OK")

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

    # Cadence
    cadence = data.get("cadence_metrics")
    if cadence and isinstance(cadence, dict):
        cycle_ms = cadence.get("avg_cycle_ms")
        mode = cadence.get("cadence_mode", "")
        if cycle_ms is not None or mode:
            lines.append("")
            if mode:
                lines.append(f"Cadence: {escape_html(mode)}")
            if cycle_ms is not None:
                lines.append(f"Avg Cycle: {cycle_ms:.0f}ms")

    return "\n".join(lines)


# ── /doctor — risk metrics + direction breakdown ─────────────────────────

def format_doctor_message(data: Dict[str, Any]) -> str:
    """Full diagnostic: risk metrics, direction breakdown, ML filter, shadow."""
    lines = ["<b>🩺 Doctor — Trading Diagnostics</b>\n"]

    # Risk metrics (mirroring Stats tab risk section)
    risk = data.get("risk_metrics")
    if risk and isinstance(risk, dict):
        lines.append("<b>Risk Metrics:</b>")

        sharpe = risk.get("sharpe_ratio") or risk.get("sharpe")
        sortino = risk.get("sortino_ratio") or risk.get("sortino")
        if sharpe is not None and sortino is not None:
            lines.append(f"  Sharpe: <b>{sharpe:.2f}</b>   Sortino: <b>{sortino:.2f}</b>")

        pf = risk.get("profit_factor")
        exp = risk.get("expectancy")
        if pf is not None and exp is not None:
            lines.append(f"  PF: <b>{pf:.2f}</b>   Expectancy: <b>${exp:,.2f}</b>")

        avg_win = risk.get("avg_win")
        avg_loss = risk.get("avg_loss")
        if avg_win is not None and avg_loss is not None:
            lines.append(f"  Avg Win: ${avg_win:,.2f}   Avg Loss: ${avg_loss:,.2f}")

        rr = risk.get("avg_rr")
        best = risk.get("largest_win") or risk.get("best_trade")
        worst = risk.get("largest_loss") or risk.get("worst_trade")
        parts = []
        if rr is not None:
            parts.append(f"R:R {rr:.2f}")
        if best is not None:
            parts.append(f"Best ${best:,.0f}")
        if worst is not None:
            parts.append(f"Worst ${worst:,.0f}")
        if parts:
            lines.append(f"  {'   '.join(parts)}")

        max_dd = risk.get("max_drawdown")
        dd_pct = risk.get("max_drawdown_pct")
        if max_dd is not None:
            dd_str = f"${max_dd:,.0f}"
            if dd_pct is not None:
                dd_str += f" ({dd_pct:.1f}%)"
            lines.append(f"  Max DD: {dd_str}")

        streak = risk.get("current_streak")
        max_w = risk.get("max_consecutive_wins") or risk.get("max_win_streak")
        max_l = risk.get("max_consecutive_losses") or risk.get("max_loss_streak")
        if streak is not None:
            s_icon = "🟢" if streak > 0 else "🔴" if streak < 0 else "⚪"
            lines.append(f"  Streak: {s_icon} {streak}   Max W: {max_w}   Max L: {max_l}")
        lines.append("")

    # Direction breakdown (mirroring Stats tab analytics)
    analytics = data.get("analytics")
    if analytics and isinstance(analytics, dict):
        dir_bd = analytics.get("direction_breakdown", {})
        if dir_bd:
            lines.append("<b>Direction Breakdown:</b>")
            for d in ("long", "short"):
                info = dir_bd.get(d, {})
                if info:
                    cnt = info.get("count", 0)
                    pnl = info.get("pnl", 0)
                    icon = "🔵" if d == "long" else "🟣"
                    lines.append(f"  {icon} {d.upper()}: {cnt} trades  {_pnl_plain(pnl)}")
            lines.append("")

    # ML filter performance
    ml = data.get("ml_filter_performance")
    if ml and isinstance(ml, dict) and ml.get("enabled", False):
        lines.append("<b>ML Filter:</b>")
        mode = ml.get("mode", "?")
        total_pred = ml.get("total_predictions", 0)
        wr_pass = ml.get("win_rate_pass")
        lift_ok = ml.get("lift_ok")
        lines.append(f"  Mode: {escape_html(mode)}   Predictions: {total_pred}")
        if wr_pass is not None:
            lines.append(f"  Pass WR: {wr_pass:.1f}%")
        if lift_ok is not None:
            lines.append(f"  Lift: {'✅' if lift_ok else '❌'}")
        lines.append("")

    # Shadow counters
    shadow = data.get("shadow_counters")
    if shadow and isinstance(shadow, dict):
        total = shadow.get("would_block_total", 0) or shadow.get("total", 0)
        if total > 0:
            net_saved = shadow.get("net_saved", 0)
            lines.append("<b>Shadow Mode:</b>")
            lines.append(f"  Blocked: {total}   Net Saved: {_pnl_plain(net_saved)}")
            lines.append("")

    # Market regime
    regime = data.get("market_regime")
    if regime and isinstance(regime, dict):
        regime_type = regime.get("regime", "")
        if regime_type:
            lines.append(f"<b>Regime:</b> {escape_html(regime_type)}")

    if len(lines) <= 2:
        lines.append("<i>No diagnostic data — agent may be stopped</i>")

    return "\n".join(lines)


# ── /signals — signal rejections + last decision ─────────────────────────

def format_signals_message(data: Dict[str, Any]) -> str:
    """Signal intelligence: rejections (24h) and last decision."""
    lines = ["<b>🧠 Signal Intelligence</b>\n"]

    # Signal rejections (24h)
    rej = data.get("signal_rejections_24h")
    if rej and isinstance(rej, dict):
        total_rej = rej.get("total", 0)
        lines.append(f"<b>Rejections (24h):</b> {total_rej}")

        reason_map = {
            "direction_gating": "Direction Gating",
            "ml_filter": "ML Filter",
            "circuit_breaker": "Circuit Breaker",
            "session_filter": "Session Filter",
            "max_positions": "Max Positions",
        }
        for key, label in reason_map.items():
            count = rej.get(key, 0)
            if count > 0:
                lines.append(f"  {label}: {count}")

        by_reason = rej.get("by_reason", {})
        if by_reason and isinstance(by_reason, dict):
            for reason, count in sorted(by_reason.items(), key=lambda x: -x[1])[:8]:
                if reason not in reason_map and count > 0:
                    lines.append(f"  {escape_html(reason)}: {count}")
        lines.append("")

    # Last signal decision
    last_sig = data.get("last_signal_decision")
    if last_sig and isinstance(last_sig, dict):
        action = last_sig.get("action", "?")
        reason = last_sig.get("reason", "")
        sig_type = last_sig.get("signal_type", "")
        direction = last_sig.get("direction", "")
        ml_prob = last_sig.get("ml_probability")
        ts = last_sig.get("timestamp", "")

        icon = "✅" if action == "execute" else "❌"
        lines.append(f"<b>Last Decision:</b>  {icon} {escape_html(action.upper())}")
        if sig_type:
            parts = [escape_html(sig_type)]
            if direction:
                parts.append(escape_html(direction.upper()))
            lines.append(f"  Signal: {' '.join(parts)}")
        if ml_prob is not None:
            lines.append(f"  ML Prob: {ml_prob:.1%}")
        if reason:
            lines.append(f"  Reason: {escape_html(reason)}")
        if ts:
            lines.append(f"  Time: {_ago(ts)}")
    else:
        lines.append("<i>No signal decisions recorded</i>")

    return "\n".join(lines)


# ── /stats — performance periods (mirrors Stats tab) ─────────────────────

def format_stats_message(data: Dict[str, Any]) -> str:
    """Performance by period: Today through All Time — mirrors the Stats tab pills."""
    lines = ["<b>📈 Performance Summary</b>\n"]

    # Try the new performanceSummary format (td/yday/wtd/mtd/ytd/all)
    # or fall back to the old performance format (24h/72h/30d)
    perf = data.get("performance")
    challenge = data.get("challenge") or {}

    # Today from daily_pnl
    daily_pnl = data.get("daily_pnl")
    daily_trades = data.get("daily_trades", 0)
    daily_wins = data.get("daily_wins", 0)
    daily_losses = data.get("daily_losses", 0)

    if daily_pnl is not None:
        wr = f"{daily_wins / daily_trades * 100:.0f}%" if daily_trades > 0 else "—"
        lines.append(f"<b>TODAY:</b>  {_pnl_color(daily_pnl)}")
        lines.append(f"  {daily_trades} trades  ·  {wr} WR")
        lines.append("")

    # Performance periods
    if perf and isinstance(perf, dict):
        period_labels = [("24h", "24H"), ("72h", "72H"), ("30d", "30D")]
        for key, label in period_labels:
            p = perf.get(key, {})
            if p and isinstance(p, dict):
                p_pnl = p.get("pnl", 0)
                p_trades = p.get("trades", 0)
                p_wr = p.get("win_rate", 0)
                if p_trades > 0:
                    lines.append(f"<b>{label}:</b>  {_pnl_color(p_pnl)}")
                    lines.append(f"  {p_trades} trades  ·  {p_wr:.0f}% WR")
                    lines.append("")

    # All-time from challenge
    if challenge:
        total_pnl = challenge.get("pnl")
        total_trades = challenge.get("trades", 0)
        total_wins = challenge.get("wins", 0)
        total_wr = challenge.get("win_rate")
        if total_pnl is not None and total_trades > 0:
            wr_str = f"{total_wr:.1f}%" if total_wr is not None else f"{total_wins / total_trades * 100:.0f}%"
            lines.append(f"<b>ALL TIME:</b>  {_pnl_color(total_pnl)}")
            lines.append(f"  {total_trades} trades  ·  {wr_str} WR")

    if len(lines) <= 2:
        lines.append("<i>No performance data available</i>")

    return "\n".join(lines)


# ── /trades — recent trade history ───────────────────────────────────────

def format_trades_message(trades: List[Dict[str, Any]], limit: int = 15) -> str:
    """Recent trades with P&L, duration, and exit reason."""
    if not trades:
        return "<i>No recent trades</i>"

    lines = [f"<b>📋 Recent Trades ({min(len(trades), limit)}):</b>\n"]

    for trade in trades[:limit]:
        direction = str(trade.get("direction", "?")).upper()
        entry = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        pnl = trade.get("pnl", 0)
        is_win = trade.get("is_win", False)
        reason = str(trade.get("exit_reason", "")).replace("_", " ")
        size = trade.get("position_size", 1)

        # Duration
        dur_str = ""
        dur_sec = trade.get("duration_seconds")
        if dur_sec and isinstance(dur_sec, (int, float)):
            if dur_sec < 60:
                dur_str = f" {int(dur_sec)}s"
            elif dur_sec < 3600:
                dur_str = f" {int(dur_sec // 60)}m"
            else:
                dur_str = f" {int(dur_sec // 3600)}h{int((dur_sec % 3600) // 60)}m"

        icon = "✅" if is_win else "❌"
        pnl_str = _pnl_plain(pnl)
        dir_icon = "🔵" if direction == "LONG" else "🟣"

        lines.append(
            f"{icon} {dir_icon} {direction} {size}x  {pnl_str}{dur_str}"
        )
        if reason:
            lines.append(f"  <i>{escape_html(reason)}</i>")

    return "\n".join(lines)


# ── Shared formatters ────────────────────────────────────────────────────

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
