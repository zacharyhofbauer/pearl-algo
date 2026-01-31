"""
Telegram Message Formatters for Market Agent.

This module provides mixin methods for formatting dashboard and card messages.
These are extracted from TelegramCommandHandler to improve modularity.

Architecture Note:
------------------
This is a mixin class designed to be composed with TelegramCommandHandler.
It provides message formatting utilities while keeping the main handler class
focused on routing and orchestration.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Any

from pearlalgo.utils.logger import logger
from pearlalgo.utils.telegram_alerts import (
    sanitize_telegram_markdown,
    format_pnl,
    format_signal_direction,
    format_signal_status,
    format_signal_confidence_tier,
    format_time_ago,
    safe_label,
)
from pearlalgo.utils.paths import parse_utc_timestamp

if TYPE_CHECKING:
    pass


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
            lines.append(f"📥 Entry: ${float(entry_price):,.2f}")
        if exit_price:
            lines.append(f"📤 Exit: ${float(exit_price):,.2f}")
        if stop_loss:
            lines.append(f"🛑 Stop: ${float(stop_loss):,.2f}")
        if take_profit:
            lines.append(f"🎯 Target: ${float(take_profit):,.2f}")

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
        pnl_sign = "+" if total_pnl >= 0 else ""

        lines.append(f"Total: {total} | {wins}W/{losses}L | {win_rate:.0f}% WR")
        lines.append(f"P&L: {pnl_emoji} {pnl_sign}${abs(total_pnl):.2f}")
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
        pnl_sign = "+" if daily_pnl >= 0 else ""
        lines.append(f"*Today:* {pnl_emoji} {pnl_sign}${abs(daily_pnl):.2f}")

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
                unreal_sign = "+" if unrealized_pnl >= 0 else ""
                lines.append(f"Unrealized: {unreal_emoji} {unreal_sign}${abs(unrealized_pnl):.2f}")

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
        pnl_sign = "+" if pnl >= 0 else ""

        lines.append(f"Balance: ${balance:,.2f}")
        lines.append(f"P&L: {pnl_emoji} {pnl_sign}${abs(pnl):.2f}")
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
