"""
Helpers for MarketAgentService status snapshots and PEARL review messaging.

These helpers intentionally operate on explicit inputs so the service can
delegate summary-building work without changing its public behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from zoneinfo import ZoneInfo

from pearlalgo.strategies.composite_intraday import check_trading_session
from pearlalgo.utils.formatting import fmt_currency
from pearlalgo.utils.logger import logger
from pearlalgo.utils.market_hours import get_market_hours


_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PearlReviewTradeSummary:
    """Normalized review metrics derived from completed trades."""

    today_trades: list[dict[str, Any]]
    daily_pnl: float
    streak_info: str
    time_since_trade: str


def _now_utc(now_utc: Optional[datetime]) -> datetime:
    resolved = now_utc or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _now_et_naive(now_et: Optional[datetime]) -> datetime:
    if now_et is None:
        return datetime.now(_ET).replace(tzinfo=None)
    if now_et.tzinfo is not None:
        return now_et.astimezone(_ET).replace(tzinfo=None)
    return now_et


def build_market_agent_status_snapshot(
    *,
    running: bool,
    paused: bool,
    start_time: Optional[datetime],
    last_market_data: Optional[Mapping[str, Any]],
    data_quality_checker: Any,
    performance_tracker: Any,
    connection_failures: int,
    max_connection_failures: int,
    signal_count: int,
    quiet_period_minutes: Optional[float],
    config: Mapping[str, Any],
    trading_circuit_breaker: Any,
    streak_count: int = 0,
    streak_type: str = "",
    now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build the service status snapshot used by operators and PEARL suggestions."""
    resolved_now_utc = _now_utc(now_utc)

    uptime_hours = 0.0
    if start_time:
        start_dt = start_time
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        uptime_hours = (resolved_now_utc - start_dt).total_seconds() / 3600.0

    data_age_minutes = 0.0
    data_stale = False
    try:
        market_data = dict(last_market_data or {})
        freshness = data_quality_checker.check_data_freshness(
            market_data.get("latest_bar"),
            market_data.get("df"),
        )
        data_age_minutes = float(freshness.get("age_minutes", 0.0))
        data_stale = not bool(freshness.get("is_fresh", False))
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    daily_pnl = 0.0
    wins_today = 0
    losses_today = 0
    try:
        perf = performance_tracker.get_daily_performance()
        daily_pnl = perf.get("total_pnl", 0.0)
        wins_today = perf.get("wins", 0)
        losses_today = perf.get("losses", 0)
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    futures_open = False
    session_open = False
    try:
        futures_open = bool(get_market_hours().is_market_open())
        session_open = check_trading_session(resolved_now_utc, config)
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    risk_daily_pnl = 0.0
    risk_session_pnl = 0.0
    risk_would_block_total = 0
    risk_mode = "unknown"
    try:
        if trading_circuit_breaker is not None:
            cb = trading_circuit_breaker.get_status()
            risk_daily_pnl = float(cb.get("daily_pnl", 0.0) or 0.0)
            risk_session_pnl = float(cb.get("session_pnl", 0.0) or 0.0)
            risk_would_block_total = int(cb.get("would_block_total", 0) or 0)
            risk_mode = str(cb.get("mode", "unknown") or "unknown")
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    return {
        "agent_running": running and not paused,
        "gateway_running": connection_failures < max_connection_failures,
        "data_stale": data_stale,
        "data_age_minutes": data_age_minutes,
        "daily_pnl": daily_pnl,
        "wins_today": wins_today,
        "losses_today": losses_today,
        "signals_today": signal_count,
        "last_signal_minutes": quiet_period_minutes,
        "session_open": session_open,
        "futures_open": futures_open,
        "agent_uptime_hours": uptime_hours,
        "win_streak": streak_count if streak_type == "win" else 0,
        "risk_daily_pnl": risk_daily_pnl,
        "risk_session_pnl": risk_session_pnl,
        "risk_would_block_total": risk_would_block_total,
        "risk_mode": risk_mode,
    }


def summarize_pearl_review_trades(
    perf_trades: list[dict[str, Any]],
    *,
    now_et: Optional[datetime] = None,
) -> PearlReviewTradeSummary:
    """Build the derived trade summary used in periodic PEARL check-ins."""
    resolved_now_et = _now_et_naive(now_et)
    today_str = resolved_now_et.strftime("%Y-%m-%d")
    today_trades = [t for t in perf_trades if today_str in str(t.get("exit_time", "") or "")]

    try:
        by_id: dict[str, dict[str, Any]] = {}
        no_id: list[dict[str, Any]] = []
        for trade in today_trades:
            signal_id = str(trade.get("signal_id") or "").strip() if isinstance(trade, dict) else ""
            if not signal_id:
                no_id.append(trade)
                continue
            by_id[signal_id] = trade
        if by_id:
            today_trades = list(by_id.values()) + no_id
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    daily_pnl = 0.0
    if today_trades:
        daily_pnl = sum(float(t.get("pnl", 0) or 0) for t in today_trades)

    streak_info = ""
    if today_trades:
        sorted_trades = sorted(
            today_trades,
            key=lambda t: str(t.get("exit_time", "") or ""),
            reverse=True,
        )
        streak = 0
        streak_type = None
        for trade in sorted_trades:
            is_win = trade.get("is_win", False)
            if streak_type is None:
                streak_type = "W" if is_win else "L"
                streak = 1
            elif (is_win and streak_type == "W") or (not is_win and streak_type == "L"):
                streak += 1
            else:
                break
        if streak >= 2:
            streak_icon = "🔥" if streak_type == "W" else "❄️"
            streak_word = "wins" if streak_type == "W" else "losses"
            streak_info = f"{streak_icon} Streak: {streak} {streak_word} in a row"

    time_since_trade = ""
    if perf_trades:
        last_trade = max(
            perf_trades,
            key=lambda t: str(t.get("exit_time", "") or ""),
            default=None,
        )
        if last_trade and last_trade.get("exit_time"):
            try:
                last_exit = datetime.fromisoformat(str(last_trade["exit_time"]).replace("Z", "+00:00"))
                if last_exit.tzinfo is not None:
                    last_exit = last_exit.astimezone(_ET).replace(tzinfo=None)
                mins_ago = (resolved_now_et - last_exit).total_seconds() / 60
                if mins_ago > 60:
                    time_since_trade = f"⏰ Last Trade: {int(mins_ago / 60)}h ago"
                else:
                    time_since_trade = f"⏰ Last Trade: {int(mins_ago)}m ago"
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

    return PearlReviewTradeSummary(
        today_trades=today_trades,
        daily_pnl=daily_pnl,
        streak_info=streak_info,
        time_since_trade=time_since_trade,
    )


def generate_pearl_insight(
    *,
    is_running: bool,
    is_session_open: bool,
    is_futures_open: bool,
    daily_pnl: float,
    today_trades: list[dict[str, Any]],
) -> str:
    """Generate a contextual PEARL insight based on current state."""
    try:
        trades_count = len(today_trades)
        wins = sum(1 for t in today_trades if t.get("is_win"))
        losses = trades_count - wins

        if not is_futures_open:
            return "Markets are closed. Rest up for the next session!"

        if not is_session_open:
            return "Strategy session is paused. I'm watching but not trading."

        if not is_running:
            return "I'm currently stopped. Start me when you're ready to trade."

        if trades_count == 0:
            return "No trades yet today. Waiting for the right setup..."

        wr = (wins / trades_count * 100) if trades_count > 0 else 0

        if daily_pnl > 100:
            return f"Great day! Up ${daily_pnl:,.0f}. Consider protecting these gains."
        if daily_pnl < -100:
            return f"Tough day, down ${abs(daily_pnl):,.0f}. Stay disciplined."
        if wr >= 70 and trades_count >= 3:
            return f"Strong {wr:.0f}% win rate today. Execution is sharp!"
        if wr < 40 and trades_count >= 3:
            return f"{wr:.0f}% WR so far. Market may be choppy."
        if losses >= 3 and wins == 0:
            return "Multiple losses in a row. Consider taking a break."
        return "All systems normal. Scanning for opportunities..."
    except Exception as e:
        logger.debug(f"Non-critical: {e}")
        return "All systems normal."


def build_pearl_review_message(
    state: Mapping[str, Any],
    *,
    perf_trades: list[dict[str, Any]],
    now_et: Optional[datetime] = None,
) -> str:
    """Build the plain-text PEARL check-in body."""
    is_running = state.get("agent_running")
    is_session_open = state.get("session_open")
    is_futures_open = state.get("futures_open")

    trade_summary = summarize_pearl_review_trades(perf_trades, now_et=now_et)
    insight = generate_pearl_insight(
        is_running=bool(is_running),
        is_session_open=bool(is_session_open),
        is_futures_open=bool(is_futures_open),
        daily_pnl=trade_summary.daily_pnl,
        today_trades=trade_summary.today_trades,
    )

    status_parts: list[str] = []
    if is_running:
        status_parts.append("🟢 Running")
    else:
        status_parts.append("🔴 Stopped")
    if is_session_open and is_futures_open:
        status_parts.append("📊 Markets Open")
    elif not is_futures_open:
        status_parts.append("🌙 Futures Closed")
    else:
        status_parts.append("⏸️ Session Closed")

    status_line = " • ".join(status_parts)

    pnl_icon = "📈" if trade_summary.daily_pnl > 0 else ("📉" if trade_summary.daily_pnl < 0 else "➖")
    trades_today = len(trade_summary.today_trades)
    wins_today = sum(1 for t in trade_summary.today_trades if t.get("is_win"))
    wr_today = (wins_today / trades_today * 100) if trades_today > 0 else 0

    lines = [status_line]
    if trades_today > 0:
        trades_word = "trade" if trades_today == 1 else "trades"
        lines.append("")
        lines.append(
            f"{pnl_icon} Today: {fmt_currency(trade_summary.daily_pnl, show_sign=True)} "
            f"({trades_today} {trades_word}, {wr_today:.0f}% WR)"
        )

    if trade_summary.streak_info:
        lines.append(trade_summary.streak_info)

    if trade_summary.time_since_trade:
        lines.append(trade_summary.time_since_trade)

    if insight:
        lines.append("")
        lines.append(f"💬 {insight}")

    return "\n".join(lines)
