"""
Telegram Message Formatters for Market Agent.

This module provides:
1. Pure formatting functions for PnL, percentages, status labels, emoji mapping,
   and metric formatting. These are stateless helpers with no side effects.
2. A mixin class (TelegramFormattersMixin) for composing with TelegramCommandHandler.

Architecture Note:
------------------
Pure functions live at module level and can be imported independently.
The mixin class is designed to be composed with TelegramCommandHandler,
providing message formatting utilities while keeping the main handler class
focused on routing and orchestration.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional, Any, Tuple

from pearlalgo.utils.formatting import fmt_currency
from pearlalgo.utils.logger import logger
from pearlalgo.utils.telegram_alerts import (
    sanitize_telegram_markdown,
    format_pnl,
    format_signal_direction,
    format_signal_status,
    format_signal_confidence_tier,
    format_time_ago,
    safe_label,
    _format_currency,
    _format_percentage,
)
from pearlalgo.utils.paths import parse_utc_timestamp

if TYPE_CHECKING:
    pass


# =============================================================================
# Pure Formatting Functions (no side effects, no API calls)
# =============================================================================


def pnl_emoji(value: float) -> str:
    """Return a colored emoji for a PnL value.

    Args:
        value: Profit/loss amount.

    Returns:
        '🟢' for non-negative, '🔴' for negative.
    """
    return "🟢" if value >= 0 else "🔴"


def format_pnl_line(pnl: float, *, show_sign: bool = True) -> str:
    """Format a PnL value as a human-readable string with emoji prefix.

    Args:
        pnl: Profit/loss amount.
        show_sign: Whether to include +/- sign.

    Returns:
        e.g. '🟢 +$125.50' or '🔴 -$42.00'
    """
    emoji = pnl_emoji(pnl)
    return f"{emoji} {fmt_currency(pnl, show_sign=show_sign)}"


def format_win_loss_line(
    wins: int,
    losses: int,
    *,
    include_rate: bool = True,
) -> str:
    """Format a win/loss summary line.

    Args:
        wins: Number of winning trades.
        losses: Number of losing trades.
        include_rate: Whether to append win-rate percentage.

    Returns:
        e.g. '3W/1L • 75% WR'
    """
    total = wins + losses
    line = f"{wins}W/{losses}L"
    if include_rate and total > 0:
        win_rate = wins / total * 100
        line += f" • {win_rate:.0f}% WR"
    return line


def format_streak(streak_count: int, streak_type: str | None) -> str:
    """Format a win/loss streak indicator.

    Args:
        streak_count: Number of consecutive results.
        streak_type: 'win' or 'loss' (or None).

    Returns:
        e.g. '🔥3W' or '❄️2L' or '' if no meaningful streak.
    """
    if streak_count < 3 or not streak_type:
        return ""
    emoji = "🔥" if streak_type == "win" else "❄️"
    suffix = "W" if streak_type == "win" else "L"
    return f"{emoji}{streak_count}{suffix}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """Format a percentage value.

    Thin wrapper around ``_format_percentage`` for a cleaner public API.

    Args:
        value: Percentage value (e.g. 75.0 for 75%).
        decimals: Decimal places.

    Returns:
        Formatted string like '75.0%'.
    """
    return _format_percentage(value, decimals=decimals)


def format_currency(value: float, *, show_sign: bool = False) -> str:
    """Format a currency value.

    Thin wrapper around ``_format_currency`` for a cleaner public API.

    Args:
        value: Dollar amount.
        show_sign: Whether to show +/- sign.

    Returns:
        Formatted string like '$1,234.56' or '+$50.00'.
    """
    return _format_currency(value, show_sign=show_sign)


# ---------------------------------------------------------------------------
# Status / Emoji Mapping Helpers
# ---------------------------------------------------------------------------

CONNECTION_STATUS_EMOJI: Dict[str, str] = {
    "connected": "🟢",
    "disconnected": "🔴",
    "reconnecting": "🟡",
    "connection_lost": "🔴",
    "recovered": "✅",
}

GATE_STATUS_EMOJI_TRUE = "🟢"
GATE_STATUS_EMOJI_FALSE = "🔴"
GATE_STATUS_EMOJI_UNKNOWN = "⚪"

DATA_LEVEL_SHORT: Dict[str, str] = {
    "level1": "L1",
    "level2": "L2",
    "historical": "HIST",
    "historical_fallback": "HIST",
    "error": "ERR",
    "unknown": "?",
}


def connection_status_emoji(status: str) -> str:
    """Return emoji for a connection status string.

    Args:
        status: One of 'connected', 'disconnected', 'reconnecting',
                'connection_lost', 'recovered'.

    Returns:
        Corresponding emoji, defaulting to '⚪'.
    """
    return CONNECTION_STATUS_EMOJI.get(status.lower(), "⚪")


def gate_emoji(value: bool | None) -> str:
    """Return a traffic-light emoji for a boolean gate.

    Args:
        value: True/False/None.

    Returns:
        '🟢', '🔴', or '⚪'.
    """
    if value is True:
        return GATE_STATUS_EMOJI_TRUE
    if value is False:
        return GATE_STATUS_EMOJI_FALSE
    return GATE_STATUS_EMOJI_UNKNOWN


def gate_label(value: bool | None, *, true_label: str = "OPEN", false_label: str = "CLOSED") -> str:
    """Return a human label for a boolean gate.

    Args:
        value: True/False/None.
        true_label: Label when True.
        false_label: Label when False.

    Returns:
        true_label, false_label, or 'UNKNOWN'.
    """
    if value is True:
        return true_label
    if value is False:
        return false_label
    return "UNKNOWN"


def data_level_short(level: str | None) -> str:
    """Abbreviate a data-level string for the support footer.

    Args:
        level: e.g. 'level1', 'level2', 'historical'.

    Returns:
        Short abbreviation like 'L1', 'L2', 'HIST', or '?'.
    """
    return DATA_LEVEL_SHORT.get(str(level or "").strip().lower(), "?")


# ---------------------------------------------------------------------------
# Duration / Time Formatting
# ---------------------------------------------------------------------------

def format_duration_short(seconds: float | None) -> str:
    """Format a duration in seconds to a compact human-readable form.

    Args:
        seconds: Duration in seconds (or None).

    Returns:
        e.g. '45s', '12m', '3h15m', or '?' if None.
    """
    if seconds is None:
        return "?"
    try:
        s = float(seconds)
    except (ValueError, TypeError):
        return "?"
    if s < 0:
        return "?"
    if s < 60:
        return f"{int(s)}s"
    if s < 3600:
        return f"{int(s // 60)}m"
    hours = int(s // 3600)
    mins = int((s % 3600) // 60)
    if mins > 0:
        return f"{hours}h{mins}m"
    return f"{hours}h"


def format_hold_duration(minutes: float) -> str:
    """Format a hold-duration in minutes to human-readable form.

    Args:
        minutes: Hold time in minutes.

    Returns:
        e.g. '45m' or '2h 15m'.
    """
    if minutes < 60:
        return f"{int(minutes)}m"
    return f"{int(minutes / 60)}h {int(minutes % 60)}m"


# ---------------------------------------------------------------------------
# Metric / Performance Formatting
# ---------------------------------------------------------------------------

def format_performance_block(
    pnl: float,
    wins: int,
    losses: int,
    *,
    label: str = "24h",
    streak_count: int = 0,
    streak_type: str | None = None,
) -> str:
    """Format a performance summary block for a time window.

    Args:
        pnl: Total P&L for the period.
        wins: Win count.
        losses: Loss count.
        label: Period label (e.g. '24h', '72h', '30d').
        streak_count: Current streak length.
        streak_type: 'win' or 'loss'.

    Returns:
        Multi-line formatted block, e.g.::

            *24h:*
            🟢 +$125.50 (3W/1L • 75% WR) 🔥3W
    """
    total = wins + losses
    emoji = pnl_emoji(pnl)
    win_rate = (wins / total * 100) if total > 0 else 0.0
    streak_str = format_streak(streak_count, streak_type)
    if streak_str:
        streak_str = f" • {streak_str}"

    header = f"*{label}:*"
    detail = f"{emoji} {fmt_currency(pnl, show_sign=True)} ({wins}W/{losses}L • {win_rate:.0f}% WR){streak_str}"
    return f"{header}\n{detail}"


def format_recent_exit_line(trade: Dict) -> str:
    """Format a single recent-exit line.

    Args:
        trade: Trade dict with 'pnl', 'direction', 'type', 'exit_reason'.

    Returns:
        e.g. '🟢 *+$50.00* • 🟢 LONG • Breakout • TP'
    """
    try:
        pnl_val = float(trade.get("pnl") or 0.0)
    except (ValueError, TypeError):
        pnl_val = 0.0
    p_emoji, p_str = format_pnl(pnl_val)
    dir_emoji, dir_label = format_signal_direction(trade.get("direction", "long"))
    sig_type = safe_label(str(trade.get("type") or "unknown"))
    reason = safe_label(str(trade.get("exit_reason") or "")).strip()
    line = f"{p_emoji} *{p_str}* • {dir_emoji} {dir_label} • {sig_type}"
    if reason:
        line += f" • {reason}"
    return line


def format_compact_signal(
    signal: Dict,
    *,
    account_label: str | None = None,
) -> str:
    """Format a signal as a calm-minimal, decision-first push alert.

    This is a pure-function equivalent of
    ``MarketAgentTelegramNotifier._format_compact_signal``.

    Layout:
        1. Direction + symbol + entry
        2. SL / TP / R:R
        3. Size + confidence + type
        4. Session context (optional)

    Args:
        signal: Signal dictionary with full context.
        account_label: Optional account prefix (e.g. 'MFFU').

    Returns:
        Formatted message string (< ~1000 chars).
    """
    symbol = str(signal.get("symbol") or "MNQ")
    signal_type = str(signal.get("type") or "unknown").replace("_", " ").title()

    def _safe_float(key: str) -> float:
        try:
            return float(signal.get(key) or 0.0)
        except (ValueError, TypeError):
            return 0.0

    entry_price = _safe_float("entry_price")
    stop_loss = _safe_float("stop_loss")
    take_profit = _safe_float("take_profit")
    confidence = _safe_float("confidence")

    is_test = signal.get("_is_test", False) or str(signal.get("reason", "")).lower().startswith("test")
    test_label = "🧪 *[TEST - NOT TRACKED]*\n" if is_test else ""

    dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))
    conf_emoji, _conf_tier = format_signal_confidence_tier(confidence)

    # Risk/reward
    rr = 0.0
    if entry_price > 0 and stop_loss > 0 and take_profit > 0:
        if dir_label == "LONG":
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
        else:
            risk = stop_loss - entry_price
            reward = entry_price - take_profit
        if risk > 0:
            rr = reward / risk

    acct_prefix = f"[{account_label}] " if account_label else ""
    message = f"{test_label}{acct_prefix}{dir_emoji} *{dir_label} {symbol}* {fmt_currency(entry_price)}\n"

    if stop_loss > 0 and take_profit > 0:
        message += f"SL {fmt_currency(stop_loss)} | TP {fmt_currency(take_profit)} | R:R {rr:.1f}\n"

    position_size = signal.get("position_size") or 1
    message += f"Size {position_size} | {conf_emoji} {confidence:.0%} | {signal_type}\n"

    regime = signal.get("regime", {}) or {}
    ctx_parts = []
    if regime.get("session"):
        ctx_parts.append(str(regime["session"]).replace("_", " ").title())
    if regime.get("regime"):
        ctx_parts.append(str(regime["regime"]).replace("_", " ").title())
    if ctx_parts:
        message += " | ".join(ctx_parts)

    return message


def format_signal_message(
    signal: Dict,
    *,
    account_label: str | None = None,
) -> str:
    """Format a signal as a concise Telegram message.

    Pure-function equivalent of
    ``MarketAgentTelegramNotifier._format_signal_message``.

    Args:
        signal: Signal dictionary.
        account_label: Optional account prefix.

    Returns:
        Formatted message string.
    """
    signal_type = signal.get("type", "unknown")
    direction = signal.get("direction", "").upper()
    entry_price = signal.get("entry_price", 0)
    stop_loss = signal.get("stop_loss", 0)
    take_profit = signal.get("take_profit", 0)
    confidence = signal.get("confidence", 0)
    reason = signal.get("reason", "")

    if direction == "LONG" and stop_loss > 0 and take_profit > 0:
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        risk_reward = reward / risk if risk > 0 else 0
    else:
        risk_reward = 0

    acct_tag = f"[{account_label}] " if account_label else ""
    dir_short = direction if direction else "?"
    message = (
        f"{acct_tag}{dir_short} MNQ {fmt_currency(entry_price)}\n"
        f"SL {fmt_currency(stop_loss)} | TP {fmt_currency(take_profit)} | R:R {risk_reward:.1f}\n"
        f"{confidence:.0%} | {signal_type} | {reason}"
    )
    return message.strip()


def format_status_message(status: Dict) -> str:
    """Format a status update as a Telegram message.

    Pure-function equivalent of
    ``MarketAgentTelegramNotifier._format_status_message``.

    Args:
        status: Status dictionary.

    Returns:
        Formatted message string.
    """
    return f"📊 *NQ Agent Status*\n\n{status.get('message', 'No status available')}"


def format_support_footer_line(
    *,
    market_label: str = "NQ",
    symbol: str = "MNQ",
    version: str | None = None,
    agent_running: bool = False,
    gateway_running: bool | None = None,
    data_level: str | None = None,
    data_age_seconds: float | None = None,
    data_stale_threshold_minutes: float = 10.0,
    is_data_stale: bool = False,
    last_cycle_seconds: float | None = None,
    run_id: str | None = None,
) -> str:
    """Build the compact ``🩺`` support-footer line for dashboards.

    Args:
        market_label: Market identifier (e.g. 'NQ').
        symbol: Trading symbol (e.g. 'MNQ').
        version: Package version string.
        agent_running: Whether the agent process is running.
        gateway_running: Gateway health (True/False/None).
        data_level: Data quality level.
        data_age_seconds: Age of last data bar in seconds.
        data_stale_threshold_minutes: Threshold for stale data.
        is_data_stale: Whether data is considered stale.
        last_cycle_seconds: Seconds since last successful cycle.
        run_id: Current run ID.

    Returns:
        Monospace support-footer string wrapped in backticks.
    """
    age_str = format_duration_short(data_age_seconds)
    thr_str = f"{float(data_stale_threshold_minutes):.0f}m"
    cycle_str = format_duration_short(last_cycle_seconds)
    gw = "OK" if gateway_running is True else "OFF" if gateway_running is False else "?"
    a = "ON" if agent_running else "OFF"
    v = f" v{version}" if version else ""
    rid = str(run_id or "?").strip()
    lvl = data_level_short(data_level)
    stale_flag = "!" if is_data_stale else ""
    return f"`🩺 {market_label}/{symbol}{v} | A:{a} | G:{gw} | D:{lvl} {age_str}/{thr_str}{stale_flag} | C:{cycle_str} | run:{rid}`"


def format_exit_notification(
    signal: Dict,
    *,
    account_label: str | None = None,
) -> str:
    """Format an exit notification message line.

    This builds the text portion of an exit notification, without sending it.

    Args:
        signal: Signal/trade dictionary with exit info.
        account_label: Optional account prefix.

    Returns:
        Formatted exit notification string.
    """
    symbol = str(signal.get("symbol") or "MNQ")
    pnl = float(signal.get("pnl") or 0.0)
    is_win = signal.get("is_win")
    entry_price = float(signal.get("entry_price") or 0.0)
    exit_price = float(signal.get("exit_price") or 0.0)
    exit_reason = str(signal.get("exit_reason") or "unknown")

    status_emoji, status_label = format_signal_status("exited", is_win)
    pnl_em, pnl_str = format_pnl(pnl)
    dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))

    acct_prefix = f"[{account_label}] " if account_label else ""
    message = f"{acct_prefix}{status_emoji} *EXIT {symbol} {dir_label}* {pnl_str}\n"

    exit_icons = {
        "stop_loss": "SL",
        "take_profit": "TP",
        "manual": "Manual",
        "expired": "Expired",
        "trailing_stop": "Trail",
    }
    reason_short = exit_icons.get(exit_reason.lower(), exit_reason.replace("_", " ").title())
    message += f"{fmt_currency(entry_price)} -> {fmt_currency(exit_price)} | {reason_short}"
    return message


class TelegramFormattersMixin:
    """
    Mixin providing message formatting utilities for Telegram bot.

    This mixin is designed to be used with TelegramCommandHandler and provides:
    - Dashboard message building
    - Support footer generation
    - Signal detail formatting
    - Status indicator formatting

    Usage:
        class TelegramCommandHandler(TelegramFormattersMixin, ...):
            ...

    Required attributes on the composing class:
        - state_dir: Path to the state directory
        - active_market: Current market identifier
    """

    def _format_support_duration(self, seconds: float | None) -> str:
        """Format a duration in seconds to human-readable form."""
        if seconds is None or seconds < 0:
            return "?"
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds / 60)}m"
        if seconds < 86400:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            if minutes > 0:
                return f"{hours}h {minutes}m"
            return f"{hours}h"
        days = int(seconds / 86400)
        hours = int((seconds % 86400) / 3600)
        if hours > 0:
            return f"{days}d {hours}h"
        return f"{days}d"

    def _get_chart_url(self) -> str | None:
        """Get the Live Chart URL from environment or None if not configured."""
        url = os.getenv("PEARL_LIVE_CHART_URL", "").strip()
        if not url:
            return None
        # Only return if it looks like a valid URL
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return None

    def _build_support_footer(self, state: dict | None = None) -> str:
        """
        Build a compact support footer for diagnostic purposes.

        This footer provides key system info that helps with troubleshooting
        when screenshots are shared.
        """
        lines = []

        # Time
        now = datetime.now(timezone.utc)
        try:
            import pytz
            et_tz = pytz.timezone('US/Eastern')
            et_time = now.astimezone(et_tz)
            time_str = et_time.strftime("%I:%M %p ET").lstrip('0')
        except Exception:
            time_str = now.strftime("%H:%M UTC")

        # Market
        market = getattr(self, "active_market", "?")

        # Agent status
        agent_running = False
        try:
            agent_running = self._is_agent_process_running()
        except Exception:
            pass
        agent_status = "ON" if agent_running else "OFF"

        # Gateway status
        gateway_status = "?"
        try:
            gw = self._get_gateway_status()
            if gw.get("is_healthy"):
                gateway_status = "ON"
            elif gw.get("process_running") or gw.get("port_listening"):
                gateway_status = "PARTIAL"
            else:
                gateway_status = "OFF"
        except Exception:
            pass

        # Data age
        data_age_str = "?"
        if state:
            try:
                age_min = self._extract_data_age_minutes(state)
                if age_min is not None:
                    if age_min < 1:
                        data_age_str = "<1m"
                    else:
                        data_age_str = f"{int(age_min)}m"
            except Exception:
                pass

        # Build footer
        lines.append(f"───")
        lines.append(f"🕐 {time_str} | 🌐 {market} | 🤖 {agent_status} | 🔌 {gateway_status} | 📡 {data_age_str}")

        # Uptime if available
        if state:
            try:
                start_ts = state.get("start_time")
                if agent_running and start_ts:
                    dt = parse_utc_timestamp(str(start_ts))
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt:
                        uptime_sec = (datetime.now(timezone.utc) - dt).total_seconds()
                        uptime_str = self._format_support_duration(uptime_sec)
                        lines.append(f"⏱️ Uptime: {uptime_str}")
            except Exception:
                pass

        return "\n".join(lines)

    def _with_support_footer(
        self,
        text: str,
        *,
        state: dict | None = None,
        max_chars: int = 4096,
        include_chart_link: bool = True,
    ) -> str:
        """
        Append support footer to text if it fits within character limit.

        Args:
            text: Original message text
            state: Optional state dict for additional context
            max_chars: Maximum characters allowed (Telegram limits)
            include_chart_link: Whether to include chart URL if available

        Returns:
            Text with footer appended if it fits
        """
        footer = self._build_support_footer(state)

        # Add chart link if available and requested
        if include_chart_link:
            chart_url = self._get_chart_url()
            if chart_url:
                footer += f"\n📊 [Live Chart]({chart_url})"

        combined = f"{text}\n\n{footer}"

        # Check if it fits
        if len(combined) <= max_chars:
            return combined

        # Try without chart link
        if include_chart_link:
            footer_no_chart = self._build_support_footer(state)
            combined_no_chart = f"{text}\n\n{footer_no_chart}"
            if len(combined_no_chart) <= max_chars:
                return combined_no_chart

        # Return original if footer doesn't fit
        return text

    def _format_signal_detail(self, signal: dict) -> str:
        """
        Format a signal record as detailed text for display.

        Args:
            signal: Signal record from signals.jsonl

        Returns:
            Formatted markdown string with signal details
        """
        lines = []

        # Signal ID and type
        signal_id = signal.get("signal_id", "?")
        sig_type = signal.get("type", "unknown")
        direction = signal.get("direction", "?")
        status = signal.get("status", "unknown")

        lines.append(f"📋 *Signal Detail*")
        lines.append("")
        lines.append(f"ID: `{safe_label(str(signal_id)[:20])}`")
        lines.append(f"Type: {safe_label(sig_type)} | Direction: {format_signal_direction(direction)}")
        lines.append(f"Status: {format_signal_status(status)}")

        # Entry/exit prices
        entry_price = signal.get("entry_price")
        exit_price = signal.get("exit_price")
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        lines.append("")
        if entry_price:
            lines.append(f"📥 Entry: {fmt_currency(entry_price)}")
        if exit_price:
            lines.append(f"📤 Exit: {fmt_currency(exit_price)}")
        if stop_loss:
            lines.append(f"🛑 Stop: {fmt_currency(stop_loss)}")
        if take_profit:
            lines.append(f"🎯 Target: {fmt_currency(take_profit)}")

        # P&L if exited
        pnl = signal.get("pnl")
        if pnl is not None:
            pnl_val = float(pnl)
            pnl_str = format_pnl(pnl_val)
            lines.append("")
            lines.append(f"💰 P&L: {pnl_str}")

            # Win/loss indicator
            is_win = signal.get("is_win")
            if is_win is not None:
                outcome = "✅ WIN" if is_win else "❌ LOSS"
                lines.append(f"Outcome: {outcome}")

        # Confidence/score
        confidence = signal.get("confidence")
        if confidence is not None:
            conf_tier = format_signal_confidence_tier(float(confidence))
            lines.append("")
            lines.append(f"Confidence: {conf_tier} ({float(confidence) * 100:.0f}%)")

        # Risk/reward
        risk_reward = signal.get("risk_reward")
        if risk_reward is not None:
            lines.append(f"Risk/Reward: {float(risk_reward):.2f}")

        # Timestamps
        lines.append("")
        entry_time = signal.get("entry_time")
        exit_time = signal.get("exit_time")
        timestamp = signal.get("timestamp")

        if timestamp:
            lines.append(f"Generated: {format_time_ago(str(timestamp))}")
        if entry_time:
            lines.append(f"Entered: {format_time_ago(str(entry_time))}")
        if exit_time:
            lines.append(f"Exited: {format_time_ago(str(exit_time))}")

        # Hold duration
        hold_mins = signal.get("hold_duration_minutes")
        if hold_mins is not None:
            if hold_mins < 60:
                dur_str = f"{int(hold_mins)}m"
            else:
                dur_str = f"{int(hold_mins / 60)}h {int(hold_mins % 60)}m"
            lines.append(f"Hold time: {dur_str}")

        # Reason
        reason = signal.get("reason")
        if reason:
            lines.append("")
            lines.append(f"💡 Reason: _{safe_label(str(reason)[:100])}_")

        return "\n".join(lines)

    def _format_trades_summary(self, trades: list, title: str = "Trades") -> str:
        """
        Format a list of trades as a summary.

        Args:
            trades: List of trade records
            title: Title for the summary

        Returns:
            Formatted markdown string
        """
        if not trades:
            return f"📊 *{title}*\n\nNo trades found."

        lines = [f"📊 *{title}*", ""]

        # Summary stats
        total = len(trades)
        wins = sum(1 for t in trades if t.get("is_win"))
        losses = total - wins
        total_pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
        win_rate = (wins / total * 100) if total > 0 else 0

        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

        lines.append(f"Total: {total} | {wins}W/{losses}L | {win_rate:.0f}% WR")
        lines.append(f"P&L: {pnl_emoji} {fmt_currency(total_pnl, show_sign=True)}")
        lines.append("")

        # Recent trades (last 5)
        lines.append("*Recent:*")
        for trade in trades[-5:]:
            direction = trade.get("direction", "?")[0].upper()
            pnl = float(trade.get("pnl", 0) or 0)
            is_win = trade.get("is_win")
            outcome = "✅" if is_win else "❌"
            pnl_str = f"+${pnl:.0f}" if pnl >= 0 else f"-${abs(pnl):.0f}"
            sig_id = str(trade.get("signal_id", ""))[:8]
            lines.append(f"• {outcome} {direction} {pnl_str} ({sig_id})")

        return "\n".join(lines)

    def _format_activity_card(
        self,
        daily_pnl: float = 0.0,
        daily_trades: int = 0,
        daily_wins: int = 0,
        daily_losses: int = 0,
        open_positions: int = 0,
        unrealized_pnl: float = 0.0,
    ) -> str:
        """
        Format an activity summary card.

        Args:
            daily_pnl: Today's realized P&L
            daily_trades: Number of trades today
            daily_wins: Number of winning trades today
            daily_losses: Number of losing trades today
            open_positions: Current open positions
            unrealized_pnl: Unrealized P&L from open positions

        Returns:
            Formatted markdown string
        """
        lines = ["📊 *Activity Summary*", ""]

        # Daily P&L
        pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
        lines.append(f"*Today:* {pnl_emoji} {fmt_currency(daily_pnl, show_sign=True)}")

        # Trades
        if daily_trades > 0:
            win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0
            lines.append(f"Trades: {daily_trades} ({daily_wins}W/{daily_losses}L)")
            lines.append(f"Win Rate: {win_rate:.0f}%")

        # Open positions
        if open_positions > 0:
            lines.append("")
            lines.append(f"📈 Open: {open_positions} position(s)")
            if unrealized_pnl != 0:
                unreal_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                lines.append(f"Unrealized: {unreal_emoji} {fmt_currency(unrealized_pnl, show_sign=True)}")

        return "\n".join(lines)

    def _format_system_status_card(
        self,
        agent_running: bool,
        gateway_healthy: bool,
        data_fresh: bool,
        market: str,
        symbol: str,
    ) -> str:
        """
        Format a system status card.

        Args:
            agent_running: Whether agent is running
            gateway_healthy: Whether gateway is healthy
            data_fresh: Whether data is fresh
            market: Current market
            symbol: Current symbol

        Returns:
            Formatted markdown string
        """
        lines = ["🎛️ *System Status*", ""]

        # Market info
        lines.append(f"Market: *{safe_label(market)}* | Symbol: *{safe_label(symbol)}*")
        lines.append("")

        # Service status
        agent_status = "🟢 RUNNING" if agent_running else "🔴 STOPPED"
        gw_status = "🟢 ONLINE" if gateway_healthy else "🔴 OFFLINE"
        data_status = "🟢 FRESH" if data_fresh else "🔴 STALE"

        lines.append(f"🤖 Agent: {agent_status}")
        lines.append(f"🔌 Gateway: {gw_status}")
        lines.append(f"📡 Data: {data_status}")

        return "\n".join(lines)

    def _format_health_indicators(
        self,
        gateway_ok: bool | None = None,
        connection_ok: bool | None = None,
        data_ok: bool | None = None,
    ) -> str:
        """
        Format health indicators as a single line.

        Args:
            gateway_ok: Gateway status (True/False/None for unknown)
            connection_ok: Connection status
            data_ok: Data freshness status

        Returns:
            Formatted string like "Gateway: 🟢 | Connection: 🔴 | Data: 🟢"
        """

        def _status_emoji(val: bool | None) -> str:
            if val is True:
                return "🟢"
            elif val is False:
                return "🔴"
            else:
                return "⚪"

        gw = _status_emoji(gateway_ok)
        conn = _status_emoji(connection_ok)
        data = _status_emoji(data_ok)

        return f"Gateway: {gw} | Connection: {conn} | Data: {data}"

    def _format_challenge_status(
        self,
        balance: float,
        starting_balance: float,
        profit_target: float,
        max_drawdown: float,
        trades: int = 0,
        wins: int = 0,
    ) -> str:
        """
        Format challenge status card.

        Args:
            balance: Current balance
            starting_balance: Starting balance
            profit_target: Profit target
            max_drawdown: Maximum allowed drawdown
            trades: Total trades taken
            wins: Winning trades

        Returns:
            Formatted markdown string
        """
        lines = ["🏆 *Challenge Status*", ""]

        # Balance and progress
        pnl = balance - starting_balance
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"

        lines.append(f"Balance: {fmt_currency(balance)}")
        lines.append(f"P&L: {pnl_emoji} {fmt_currency(pnl, show_sign=True)}")
        lines.append("")

        # Targets
        lines.append(f"🎯 Profit Target: +${profit_target:,.0f}")
        lines.append(f"🛑 Max Drawdown: -${max_drawdown:,.0f}")
        lines.append("")

        # Progress
        if pnl > 0:
            progress = (pnl / profit_target) * 100
            lines.append(f"Progress: {progress:.1f}% to target")
        elif pnl < 0:
            drawdown_used = (abs(pnl) / max_drawdown) * 100
            lines.append(f"Drawdown: {drawdown_used:.1f}% used")

        # Stats
        if trades > 0:
            win_rate = (wins / trades * 100) if trades > 0 else 0
            lines.append("")
            lines.append(f"Trades: {trades} | Win Rate: {win_rate:.0f}%")

        return "\n".join(lines)

    def _format_onoff(self, value: bool) -> str:
        """Format a boolean as ON/OFF with emoji."""
        return "🟢 ON" if value else "🔴 OFF"
