"""
Telegram Alerts - Send notifications for trades and major events.
"""

from __future__ import annotations

from typing import Optional

from pearlalgo.utils.logger import logger

try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:
    Bot = None
    TelegramError = Exception


TELEGRAM_TEXT_LIMIT = 4096
_TRUNC_SUFFIX = "\n\n…(truncated)"


def _truncate_telegram_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> str:
    """Ensure text is within Telegram message size limits."""
    if len(text) <= limit:
        return text
    keep = max(0, limit - len(_TRUNC_SUFFIX))
    return text[:keep] + _TRUNC_SUFFIX


def _format_separator(length: int = 25) -> str:
    """Create a visual separator line (mobile-friendly)."""
    # Use blank line instead of long separator for mobile compatibility
    return ""


def _format_uptime(uptime: dict) -> str:
    """Format uptime compactly."""
    hours = uptime.get('hours', 0)
    minutes = uptime.get('minutes', 0)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_number(value: float, decimals: int = 2, show_sign: bool = False) -> str:
    """Format number with commas and optional sign."""
    if value is None:
        return "N/A"
    sign = "+" if show_sign and value >= 0 else ""
    return f"{sign}{value:,.{decimals}f}"


def _format_currency(value: float, show_sign: bool = False) -> str:
    """Format currency value."""
    if value is None:
        return "$0.00"
    sign = "+" if show_sign and value >= 0 else ""
    return f"{sign}${value:,.2f}"


def _format_percentage(value: float, decimals: int = 1) -> str:
    """Format percentage."""
    if value is None:
        return "0%"
    return f"{value:.{decimals}f}%"


# ---------------------------------------------------------------------------
# Shared signal status semantics
# ---------------------------------------------------------------------------
# Canonical status values: generated, entered, exited, expired
# These helpers ensure consistent emoji/label usage across all Telegram views.

SIGNAL_STATUS_EMOJI = {
    "generated": "🆕",
    "entered": "🎯",
    "exited": "🏁",
    "expired": "⏰",
}

SIGNAL_STATUS_LABEL = {
    "generated": "Pending",
    "entered": "In Trade",
    "exited": "Closed",
    "expired": "Expired",
}


def format_signal_status(status: str, is_win: bool | None = None) -> tuple[str, str]:
    """
    Return (emoji, label) for a signal status.

    For exited signals, is_win overrides the default emoji with ✅/❌.
    """
    status_lower = (status or "").lower()
    if status_lower == "exited" and is_win is not None:
        emoji = "✅" if is_win else "❌"
        label = "Win" if is_win else "Loss"
        return emoji, label
    emoji = SIGNAL_STATUS_EMOJI.get(status_lower, "⚪")
    label = SIGNAL_STATUS_LABEL.get(status_lower, status.title() if status else "Unknown")
    return emoji, label


def format_signal_direction(direction: str) -> tuple[str, str]:
    """Return (emoji, label) for a signal direction."""
    direction_lower = (direction or "").lower()
    if direction_lower == "long":
        return "🟢", "LONG"
    elif direction_lower == "short":
        return "🔴", "SHORT"
    return "⚪", direction.upper() if direction else "N/A"


def format_signal_confidence_tier(confidence: float) -> tuple[str, str]:
    """Return (emoji, tier_label) for a confidence value (0-1)."""
    if confidence >= 0.70:
        return "🟢", "High"
    elif confidence >= 0.55:
        return "🟡", "Moderate"
    else:
        return "🔴", "Low"


def format_pnl(pnl: float) -> tuple[str, str]:
    """Return (emoji, formatted_string) for a P&L value."""
    if pnl >= 0:
        return "🟢", f"+${pnl:,.2f}"
    else:
        return "🔴", f"-${abs(pnl):,.2f}"


def format_time_ago(timestamp_str: str | None) -> str:
    """
    Format a timestamp as a human-readable 'time ago' string.

    Returns e.g. '5m ago', '2h ago', '1d ago', or '' if parsing fails.
    """
    if not timestamp_str:
        return ""
    try:
        from datetime import datetime, timezone
        from pearlalgo.utils.paths import parse_utc_timestamp

        ts = parse_utc_timestamp(str(timestamp_str))
        if ts is None:
            return ""
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - ts
        seconds = delta.total_seconds()
        if seconds < 0:
            return ""
        if seconds < 60:
            return f"{int(seconds)}s ago"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        elif seconds < 86400:
            return f"{int(seconds // 3600)}h ago"
        else:
            return f"{int(seconds // 86400)}d ago"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Markdown-safe rendering helpers
# ---------------------------------------------------------------------------

def escape_markdown(text: str) -> str:
    """
    Escape characters that have special meaning in Telegram Markdown.

    Escapes: _ * [ ] ( ) ~ ` > # + - = | { } . !
    For Markdown mode (not MarkdownV2), primarily _ and * matter.
    """
    if not text:
        return ""
    # For Telegram Markdown (not V2), escape underscores and asterisks
    result = str(text)
    result = result.replace("_", "\\_")
    result = result.replace("*", "\\*")
    result = result.replace("`", "\\`")
    result = result.replace("[", "\\[")
    return result


def safe_label(text: str) -> str:
    """
    Make a dynamic string safe for Telegram Markdown labels.

    Replaces underscores with spaces (more readable than escaping).
    """
    if not text:
        return ""
    return str(text).replace("_", " ")


# ---------------------------------------------------------------------------
# Activity and timing helpers (UX improvement v2)
# ---------------------------------------------------------------------------

def format_activity_pulse(
    last_cycle_seconds: float | None,
    is_paused: bool = False,
) -> tuple[str, str]:
    """
    Format activity pulse indicator showing time since last cycle.
    
    Returns (emoji, text) tuple.
    
    Args:
        last_cycle_seconds: Seconds since last cycle completed
        is_paused: Whether the agent is paused
        
    Returns:
        Tuple of (emoji, description) e.g. ("🟢", "Active (30s ago)")
    """
    if is_paused:
        return "⏸️", "Paused"
    
    if last_cycle_seconds is None:
        return "⚪", "Unknown"
    
    if last_cycle_seconds < 0:
        return "⚪", "Unknown"
    
    # Convert to readable format
    if last_cycle_seconds < 60:
        time_str = f"{int(last_cycle_seconds)}s ago"
    elif last_cycle_seconds < 3600:
        mins = int(last_cycle_seconds // 60)
        time_str = f"{mins}m ago"
    else:
        hours = int(last_cycle_seconds // 3600)
        mins = int((last_cycle_seconds % 3600) // 60)
        time_str = f"{hours}h {mins}m ago"
    
    # Determine health based on age
    if last_cycle_seconds <= 120:  # < 2 minutes
        return "🟢", f"Active ({time_str})"
    elif last_cycle_seconds <= 300:  # 2-5 minutes
        return "🟡", f"Slow ({time_str})"
    else:  # > 5 minutes
        return "🔴", f"Stale ({time_str})"


def format_next_session_time() -> str:
    """
    Get the next strategy session opening time (09:30 ET on next trading day).
    
    Returns formatted string like "Next session: 9:30 AM ET (Monday)"
    """
    try:
        from datetime import datetime, timezone, timedelta
        import pytz
        
        et_tz = pytz.timezone('US/Eastern')
        now = datetime.now(et_tz)
        
        # Strategy session is 09:30 - 16:00 ET
        session_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        
        # If we're before 09:30 today, next session is today
        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            next_open = session_open
        else:
            # Next session is tomorrow (or Monday if weekend)
            next_open = session_open + timedelta(days=1)
        
        # Skip weekends
        while next_open.weekday() >= 5:  # 5=Sat, 6=Sun
            next_open += timedelta(days=1)
        
        day_name = next_open.strftime("%A")
        time_str = next_open.strftime("%I:%M %p ET")
        
        if next_open.date() == now.date():
            return f"Opens today at {time_str}"
        elif next_open.date() == (now + timedelta(days=1)).date():
            return f"Opens tomorrow at {time_str}"
        else:
            return f"Opens {day_name} at {time_str}"
    except Exception:
        return "Next session: Check market calendar"


def format_signal_action_cue(
    signal_status: str,
    signal_direction: str,
) -> str:
    """
    Format an action cue for a signal based on its status.
    
    Args:
        signal_status: Current signal status (generated, entered, exited, expired)
        signal_direction: Signal direction (long, short)
        
    Returns:
        Action cue string like "Monitor for entry" or "Position active"
    """
    status_lower = (signal_status or "").lower()
    dir_lower = (signal_direction or "long").lower()
    dir_action = "BUY" if dir_lower == "long" else "SELL"
    
    if status_lower == "generated":
        return f"⏳ Monitor for {dir_action} entry at target price"
    elif status_lower == "entered":
        return f"🎯 Position ACTIVE - Watch stop/TP levels"
    elif status_lower == "exited":
        return "✅ Trade completed - Review performance"
    elif status_lower == "expired":
        return "⏰ Signal expired - No action needed"
    else:
        return ""


def format_signal_timing(
    timestamp_str: str | None,
    include_relative: bool = True,
) -> str:
    """
    Format signal timestamp for display.
    
    Args:
        timestamp_str: ISO timestamp string
        include_relative: Whether to include relative time (e.g., "5m ago")
        
    Returns:
        Formatted string like "10:15 AM ET (5m ago)"
    """
    if not timestamp_str:
        return ""
    
    try:
        from datetime import datetime, timezone
        import pytz
        from pearlalgo.utils.paths import parse_utc_timestamp
        
        ts = parse_utc_timestamp(str(timestamp_str))
        if ts is None:
            return ""
        
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        
        # Convert to ET
        et_tz = pytz.timezone('US/Eastern')
        et_time = ts.astimezone(et_tz)
        time_str = et_time.strftime("%I:%M %p ET")
        
        if include_relative:
            age = format_time_ago(timestamp_str)
            if age:
                return f"{time_str} ({age})"
        
        return time_str
    except Exception:
        return ""


def format_performance_trend(
    current_pnl: float,
    previous_pnl: float | None,
) -> str:
    """
    Format performance trend comparison.
    
    Args:
        current_pnl: Current period P&L
        previous_pnl: Previous period P&L (e.g., yesterday)
        
    Returns:
        Trend string like "↗️ +$50.00 vs yesterday"
    """
    if previous_pnl is None:
        return ""
    
    diff = current_pnl - previous_pnl
    
    if diff > 0:
        emoji = "↗️"
        sign = "+"
    elif diff < 0:
        emoji = "↘️"
        sign = ""  # negative sign included in value
    else:
        emoji = "➡️"
        sign = ""
    
    return f"{emoji} {sign}${diff:,.2f} vs prev"


# ---------------------------------------------------------------------------
# Home Card layout helpers (unified status/dashboard spec)
# ---------------------------------------------------------------------------

def format_gate_status(
    futures_market_open: bool | None,
    strategy_session_open: bool | None,
) -> str:
    """
    Format market gates line for Home Card.

    Returns a compact line like: 🟢 Futures: OPEN  •  🟢 Session: OPEN
    """
    futures_emoji = "🟢" if futures_market_open is True else "🔴" if futures_market_open is False else "⚪"
    futures_text = "OPEN" if futures_market_open is True else "CLOSED" if futures_market_open is False else "?"
    strat_emoji = "🟢" if strategy_session_open is True else "🔴" if strategy_session_open is False else "⚪"
    strat_text = "OPEN" if strategy_session_open is True else "CLOSED" if strategy_session_open is False else "?"
    return f"{futures_emoji} Futures: {futures_text}  •  {strat_emoji} Session: {strat_text}"


def format_service_status(
    agent_running: bool,
    gateway_running: bool,
    paused: bool = False,
) -> str:
    """
    Format service status line for Home Card.

    Returns a compact line like: 🟢 Agent: RUNNING  •  🟢 Gateway: RUNNING
    """
    agent_emoji = "🟢" if agent_running and not paused else "⏸️" if paused else "🔴"
    agent_text = "PAUSED" if paused else ("RUNNING" if agent_running else "STOPPED")
    gateway_emoji = "🟢" if gateway_running else "🔴"
    gateway_text = "RUNNING" if gateway_running else "STOPPED"
    return f"{agent_emoji} Agent: {agent_text}  •  {gateway_emoji} Gateway: {gateway_text}"


def format_activity_line(
    cycles_session: int | None,
    cycles_total: int,
    signals_generated: int,
    signals_sent: int,
    errors: int,
    buffer_size: int,
    buffer_target: int | None = None,
) -> str:
    """
    Format activity summary line for Home Card.

    Returns compact metrics like: 📊 42 cycles • 3/2 signals • 85/100 bars • 0 errors
    """
    # Cycles
    if cycles_session is not None:
        cycles_part = f"{cycles_session:,}/{cycles_total:,} cycles"
    else:
        cycles_part = f"{cycles_total:,} cycles"

    # Signals: generated/sent
    signals_part = f"{signals_generated}/{signals_sent} signals"

    # Buffer
    if buffer_target is not None:
        buffer_part = f"{buffer_size}/{buffer_target} bars"
    else:
        buffer_part = f"{buffer_size} bars"

    # Errors
    errors_part = f"{errors} errors"

    return f"📊 {cycles_part} • {signals_part} • {buffer_part} • {errors_part}"


def format_performance_line(
    wins: int,
    losses: int,
    win_rate: float,
    total_pnl: float,
) -> str:
    """
    Format 7-day performance summary for Home Card.

    Returns compact line like: 📈 5W/2L • 71% WR • 🟢 +$350.00
    """
    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
    return f"📈 {wins}W/{losses}L • {win_rate:.0f}% WR • {pnl_emoji} {_format_currency(total_pnl)}"


def format_home_card(
    symbol: str,
    time_str: str,
    agent_running: bool,
    gateway_running: bool,
    futures_market_open: bool | None,
    strategy_session_open: bool | None,
    paused: bool = False,
    pause_reason: str | None = None,
    cycles_session: int | None = None,
    cycles_total: int = 0,
    signals_generated: int = 0,
    signals_sent: int = 0,
    errors: int = 0,
    buffer_size: int = 0,
    buffer_target: int | None = None,
    latest_price: float | None = None,
    performance: dict | None = None,
    sparkline: str | None = None,
    price_change_str: str | None = None,
    last_signal_age: str | None = None,
    # New fields for enhanced confidence/clarity (v2 spec)
    state_age_seconds: float | None = None,
    state_stale_threshold: float = 120.0,  # seconds; show warning if older
    signal_send_failures: int = 0,
    gateway_unknown: bool = False,  # True if gateway status couldn't be determined
    # New fields for UX improvements (v3)
    last_cycle_seconds: float | None = None,  # For activity pulse
    previous_pnl: float | None = None,  # For performance trend
) -> str:
    """
    Build unified Home Card message for status/dashboard (balanced verbosity).

    This is the canonical layout used by both interactive /status and push dashboard.

    ══════════════════════════════════════════════════════════════════════════════
    HOME CARD SPEC v2 - Clarity, Confidence, Action
    ══════════════════════════════════════════════════════════════════════════════

    DESIGN PRINCIPLES:
    1. Healthy state stays CALM - no extra noise when everything is working.
    2. Degraded state gets EXPLANATIONS - surface what's wrong and what to do.
    3. Progressive disclosure - details live in Data Quality / Health views.

    REQUIRED LINES (always shown):
    - Header: Symbol + Time
    - Service status: Agent + Gateway state
    - Gates: Futures + Session open/closed
    - Activity: cycles, signals, buffer, errors

    CONDITIONAL CALLOUTS (only when relevant):
    - Freshness warning: when state_age_seconds > state_stale_threshold
    - Gate expectation: when session closed, explain "signals suppressed"
    - Pause reason: when paused, show reason + action cue if circuit-breaker
    - Action cue: when stopped, show "Start agent to begin"
    - Error cue: when signal_send_failures > 0 or errors > 0

    RULES FOR CONDITIONAL LINES:
    - Never show freshness cue in healthy state (state_age < threshold).
    - Never show gate explanation when session is open.
    - Action cue only for stopped/paused states requiring intervention.
    - Keep total message under 1500 chars for mobile readability.
    ══════════════════════════════════════════════════════════════════════════════

    Args:
        symbol: Trading symbol (e.g., "MNQ")
        time_str: Current time string (e.g., "10:30 AM ET")
        agent_running: Whether agent service is running
        gateway_running: Whether gateway is running
        futures_market_open: Futures market gate status
        strategy_session_open: Strategy session gate status
        paused: Whether agent is paused
        pause_reason: Reason for pause (if paused)
        cycles_session: Cycles this session
        cycles_total: Total cycles
        signals_generated: Signals generated count
        signals_sent: Signals successfully sent count
        errors: Error count
        buffer_size: Current buffer size
        buffer_target: Target buffer size
        latest_price: Latest price (optional)
        performance: Performance dict with wins, losses, win_rate, total_pnl (optional)
        sparkline: Price sparkline string (optional)
        price_change_str: Price change string like "+0.25%" (optional)
        last_signal_age: Age of last signal like "5m ago" (optional)
        state_age_seconds: Age of state file in seconds (for freshness cue)
        state_stale_threshold: Threshold in seconds for showing stale warning
        signal_send_failures: Number of signal send failures (for error cue)
        gateway_unknown: True if gateway status couldn't be determined
        last_cycle_seconds: Seconds since last cycle (for activity pulse)
        previous_pnl: Previous period P&L for trend comparison

    Returns:
        Formatted Home Card message string
    """
    lines = []

    # Header: Symbol + Time + Price
    header = f"📊 *{symbol}*"
    if time_str:
        header += f" • {time_str}"
    lines.append(header)

    # Price line (if available)
    if latest_price is not None:
        price_line = f"💰 *${latest_price:,.2f}*"
        if price_change_str:
            price_line += f" {price_change_str}"
        lines.append(price_line)
        if sparkline:
            lines.append(f"`{sparkline}`")

    lines.append("")  # Blank line separator

    # Service status line (with gateway_unknown handling)
    if gateway_unknown:
        # Show gateway as unknown rather than asserting running/stopped
        agent_emoji = "🟢" if agent_running and not paused else "⏸️" if paused else "🔴"
        agent_text = "PAUSED" if paused else ("RUNNING" if agent_running else "STOPPED")
        lines.append(f"{agent_emoji} Agent: {agent_text}  •  ⚪ Gateway: ?")
    else:
        lines.append(format_service_status(agent_running, gateway_running, paused))

    # CONDITIONAL: Pause reason (if paused)
    if paused and pause_reason:
        reason_safe = safe_label(pause_reason)
        lines.append(f"   ⚠️ Reason: {reason_safe}")
        # Add action cue for circuit-breaker style pauses
        if "circuit" in pause_reason.lower() or "error" in pause_reason.lower():
            lines.append(f"   💡 Manual intervention required")

    # CONDITIONAL: Activity pulse (when running and we have cycle data)
    if agent_running and not paused and last_cycle_seconds is not None:
        pulse_emoji, pulse_text = format_activity_pulse(last_cycle_seconds, is_paused=paused)
        lines.append(f"{pulse_emoji} {pulse_text}")

    # CONDITIONAL: Freshness warning (only when stale)
    is_stale = (
        state_age_seconds is not None
        and state_age_seconds > state_stale_threshold
    )
    if is_stale:
        age_mins = state_age_seconds / 60.0
        lines.append(f"⚠️ State {age_mins:.1f}m old (may be outdated)")

    # Gates line
    lines.append(format_gate_status(futures_market_open, strategy_session_open))

    # CONDITIONAL: Gate expectation explanation (only when session closed)
    if strategy_session_open is False:
        next_session = format_next_session_time()
        lines.append(f"   ℹ️ Signals suppressed • {next_session}")
    elif futures_market_open is False and strategy_session_open is not False:
        lines.append("   ℹ️ Data may be delayed (market closed)")

    lines.append("")  # Blank line separator

    # Activity line
    lines.append(format_activity_line(
        cycles_session=cycles_session,
        cycles_total=cycles_total,
        signals_generated=signals_generated,
        signals_sent=signals_sent,
        errors=errors,
        buffer_size=buffer_size,
        buffer_target=buffer_target,
    ))

    # CONDITIONAL: Error/failure cue (only when non-zero)
    if signal_send_failures > 0:
        lines.append(f"⚠️ {signal_send_failures} signal send failures")

    # Last signal age (if available)
    if last_signal_age:
        lines.append(f"🔔 Last signal: {last_signal_age}")

    # Performance (if available and has trades)
    if performance:
        exited = performance.get("exited_signals", 0)
        if exited > 0:
            wins = performance.get("wins", 0)
            losses = performance.get("losses", 0)
            win_rate = performance.get("win_rate", 0.0) * 100
            total_pnl = performance.get("total_pnl", 0.0)
            lines.append("")  # Blank line
            lines.append(f"*7d Performance:*")
            lines.append(format_performance_line(wins, losses, win_rate, total_pnl))
            # Add trend comparison if previous_pnl is available
            if previous_pnl is not None:
                trend_str = format_performance_trend(total_pnl, previous_pnl)
                if trend_str:
                    lines.append(trend_str)

    # CONDITIONAL: Action cue (only for stopped state)
    if not agent_running and not paused:
        lines.append("")
        lines.append("💡 *Start agent to begin*")

    return "\n".join(lines)


class TelegramAlerts:
    """Telegram alert sender for trading notifications."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self.last_error: Optional[str] = None

        self.bot = None
        if enabled and Bot:
            try:
                self.bot = Bot(token=bot_token)
                logger.info("Telegram alerts initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Telegram bot: {e}")
                self.last_error = str(e)
                self.enabled = False
        elif enabled and not Bot:
            logger.warning(
                "python-telegram-bot not installed, Telegram alerts disabled"
            )
            self.last_error = "python-telegram-bot not installed"
            self.enabled = False

    async def send_message(
        self,
        message: str,
        parse_mode: str | None = "Markdown",
        max_retries: int = 3,
        reply_markup=None,
        dedupe: bool = True,
    ) -> bool:
        """
        Send a message to Telegram with retry logic and deduplication.

        Args:
            message: Message text
            parse_mode: Telegram parse mode (default: Markdown)
            max_retries: Maximum retry attempts (default: 3)
            reply_markup: Optional Telegram reply markup (inline buttons)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled or not self.bot:
            self.last_error = "Telegram disabled or bot not initialized"
            return False

        import asyncio
        import hashlib
        import time

        # Enforce Telegram size limit early. This prevents silent non-delivery for oversized messages.
        original_len = len(message)
        message = _truncate_telegram_text(message)
        if len(message) != original_len:
            logger.warning(
                f"Telegram message truncated (len={original_len} -> {len(message)})"
            )

        # Enhanced deduplication: track last message hash and timestamp
        # Prevent sending same or very similar messages within 120 seconds (2 minutes)
        # Normalize message for better duplicate detection (remove variable timestamps/ages)
        import re
        normalized_message = message
        # Normalize variable parts that might differ slightly but are essentially the same message
        # Remove age values in both "X.X minutes old" format and "*Age:* X.X minutes" format
        normalized_message = re.sub(r'\d+\.\d+ minutes old', 'X.X minutes old', normalized_message)
        normalized_message = re.sub(r'\*Age:\* \d+\.\d+ minutes', '*Age:* X.X minutes', normalized_message)
        # Remove time stamps (e.g., "01:42:20 PM ET" -> "XX:XX:XX XM ET")
        normalized_message = re.sub(r'\d+:\d+:\d+ [AP]M ET', 'XX:XX:XX XM ET', normalized_message)
        # Remove percentages
        normalized_message = re.sub(r'\d+\.\d+%', 'X.X%', normalized_message)
        # Remove price values in stale data alerts
        normalized_message = re.sub(r'\$\d+,\d+\.\d+', '$X,XXX.XX', normalized_message)
        
        message_hash = hashlib.md5(normalized_message.encode()).hexdigest()
        current_time = time.time()
        
        if not hasattr(self, '_last_message_hash'):
            self._last_message_hash = None
            self._last_message_time = 0
        
        # Skip if same/similar message sent within last 120 seconds (2 minutes)
        if dedupe:
            if (self._last_message_hash == message_hash and 
                current_time - self._last_message_time < 120.0):
                logger.debug(f"Skipping duplicate message (sent {current_time - self._last_message_time:.1f}s ago)")
                self.last_error = None
                return True  # Return True since message was already sent

        for attempt in range(max_retries):
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
                # Mark as sent successfully
                self._last_message_hash = message_hash
                self._last_message_time = current_time
                self.last_error = None
                return True
            except TelegramError as e:
                error_msg = str(e)
                self.last_error = error_msg
                # "Not Found" usually means invalid chat_id or bot not started
                if "Not Found" in error_msg or "404" in error_msg:
                    logger.error(
                        f"Telegram chat not found. This usually means:\n"
                        f"  1. Chat ID is incorrect: {self.chat_id}\n"
                        f"  2. Bot hasn't been started (send /start to your bot first)\n"
                        f"  3. Bot doesn't have permission to send to this chat\n"
                        f"  Error: {e}"
                    )
                    # Don't retry on 404 - it won't work
                    return False

                # Markdown parsing errors - try sending as plain text immediately
                if "parse entities" in error_msg.lower() or "can't parse" in error_msg.lower():
                    logger.warning(f"Markdown parsing error, retrying as plain text: {e}")
                    # Try sending as plain text on next attempt
                    if attempt < max_retries - 1:
                        try:
                            await self.bot.send_message(
                                chat_id=self.chat_id,
                                text=message,
                                parse_mode=None,  # Plain text
                                reply_markup=reply_markup,
                            )
                            self.last_error = None
                            return True
                        except Exception as e2:
                            logger.debug(f"Plain text send also failed: {e2}")
                            self.last_error = str(e2)
                            # Continue to retry loop
                    elif attempt == max_retries - 1:
                        # Last attempt - try without Markdown
                        try:
                            await self.bot.send_message(
                                chat_id=self.chat_id,
                                text=message.replace('*', '').replace('_', '').replace('`', ''),
                                parse_mode=None,
                                reply_markup=reply_markup,
                            )
                            self.last_error = None
                            return True
                        except Exception as plain_error:
                            logger.error(f"Failed to send as plain text: {plain_error}")
                            self.last_error = str(plain_error)
                            return False

                if attempt < max_retries - 1:
                    # Exponential backoff
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"Telegram send failed (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {wait_time}s: {e}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Failed to send Telegram message after {max_retries} attempts: {e}")
                    return False
            except Exception as e:
                logger.error(f"Unexpected error sending Telegram message: {e}")
                self.last_error = str(e)
                return False

        return False

    async def notify_trade(
        self,
        symbol: str,
        side: str,
        size: int,
        price: float,
        order_id: Optional[str] = None,
    ) -> None:
        """Notify about a trade execution."""
        message = (
            f"🔔 *Trade Executed*\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {side.upper()}\n"
            f"Size: {size} contracts\n"
            f"Price: ${price:.2f}\n"
        )
        if order_id:
            message += f"Order ID: {order_id}"

        await self.send_message(message)

    async def notify_risk_warning(
        self,
        message: str,
        risk_status: Optional[str] = None,
    ) -> None:
        """
        Notify about a risk warning (mobile-friendly).
        
        Args:
            message: Alert message (should already be formatted with emoji and title)
            risk_status: Optional status string (e.g., "DATA_QUALITY", "CRITICAL")
        """
        # Message should already be formatted, just add Risk Warning header if not present
        if "Risk Warning" not in message and "*Risk Warning*" not in message:
            alert = f"⚠️ *Risk Warning*\n\n{message}"
        else:
            alert = message
        
        if risk_status:
            alert += f"\n*Status:* {risk_status}"
        
        await self.send_message(alert)

    async def notify_daily_summary(
        self,
        daily_pnl: float,
        total_trades: int,
        win_rate: Optional[float] = None,
    ) -> None:
        """Send daily trading summary (mobile-friendly)."""
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        trend_emoji = "↗️" if daily_pnl >= 0 else "↘️"
        trend_text = "Profitable" if daily_pnl >= 0 else "Loss"

        message = f"{pnl_emoji} *Daily Summary*\n\n"
        message += f"💰 *P&L:* {_format_currency(daily_pnl)}\n"

        if win_rate is not None:
            message += f"📊 *Trades:* {total_trades} ({_format_percentage(win_rate * 100)} WR)\n"
        else:
            message += f"📊 *Trades:* {total_trades}\n"

        message += f"📈 *Trend:* {trend_emoji} {trend_text}\n"

        await self.send_message(message)

    async def notify_kill_switch(self, reason: str) -> None:
        """Notify about kill-switch activation."""
        message = f"🛑 *KILL-SWITCH ACTIVATED*\n\n{reason}"
        await self.send_message(message)

    async def notify_signal(
        self,
        symbol: str,
        side: str,
        price: float,
        strategy: str,
        confidence: Optional[float] = None,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reasoning: Optional[str] = None,
        # Options-specific parameters
        option_symbol: Optional[str] = None,
        strike: Optional[float] = None,
        expiration: Optional[str] = None,
        option_type: Optional[str] = None,  # "call" or "put"
        underlying_price: Optional[float] = None,
        delta: Optional[float] = None,
        gamma: Optional[float] = None,
        theta: Optional[float] = None,
        dte: Optional[int] = None,
    ) -> None:
        """
        Notify about a new trading signal with rich formatting.
        Supports both stock/futures and options signals.

        Args:
            symbol: Trading symbol (underlying for options)
            side: "long" or "short"
            price: Current market price (option premium for options)
            strategy: Strategy name
            confidence: Signal confidence (0-1)
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            reasoning: LLM reasoning (optional)
            option_symbol: Option contract symbol (e.g., "QQQ240119C00450")
            strike: Strike price
            expiration: Expiration date (YYYY-MM-DD)
            option_type: "call" or "put"
            underlying_price: Current underlying price
            delta: Option delta (if available)
            gamma: Option gamma (if available)
            theta: Option theta (if available)
            dte: Days to expiration
        """
        side_emoji = "🟢" if side.lower() == "long" else "🔴"
        side_text = side.upper()
        sep = _format_separator(25)

        # Check if this is an options signal
        is_options = option_symbol is not None or option_type is not None

        # Header (mobile-friendly, no long separators)
        if is_options:
            message = f"{side_emoji} *NEW OPTIONS SIGNAL*\n*{symbol} {side_text}*\n\n"
        else:
            message = f"{side_emoji} *NEW SIGNAL*\n*{symbol} {side_text}*\n\n"

        # Entry/Stop/Target section with better alignment
        entry = entry_price if entry_price else price
        if entry:
            # Calculate all values first for alignment
            stop_pct_str = ""
            tp_pct_str = ""
            rr_ratio = None

            if stop_loss and entry:
                if side.lower() == "long":
                    stop_pct = ((stop_loss - entry) / entry) * 100
                else:
                    stop_pct = ((entry - stop_loss) / entry) * 100
                stop_pct_str = f" ({stop_pct:+.2f}%)"

            if take_profit and entry:
                if side.lower() == "long":
                    tp_pct = ((take_profit - entry) / entry) * 100
                else:
                    tp_pct = ((entry - take_profit) / entry) * 100
                tp_pct_str = f" ({tp_pct:+.2f}%)"

            # Calculate R:R if we have both stop and target
            if stop_loss and take_profit and entry:
                if side.lower() == "long":
                    risk = abs(entry - stop_loss)
                    reward = abs(take_profit - entry)
                else:
                    risk = abs(entry - stop_loss)
                    reward = abs(entry - take_profit)
                if risk > 0:
                    rr_ratio = reward / risk

            # Format with consistent alignment
            message += f"Entry:    {_format_currency(entry)}\n"
            if stop_loss:
                message += f"Stop:     {_format_currency(stop_loss)}{stop_pct_str}\n"
            if take_profit:
                # Include R:R on target line if available
                if rr_ratio is not None:
                    message += f"Target:   {_format_currency(take_profit)}{tp_pct_str}  R:R {rr_ratio:.1f}:1\n"
                else:
                    message += f"Target:   {_format_currency(take_profit)}{tp_pct_str}\n"

        # Confidence bar
        if confidence is not None:
            confidence_pct = confidence * 100
            confidence_bar = "█" * int(confidence_pct / 10) + "░" * (10 - int(confidence_pct / 10))
            message += f"\n*Confidence:* {confidence_pct:.0f}% {confidence_bar}\n"

        # Strategy and reasoning
        message += f"\n*Strategy:* {strategy}\n"

        if reasoning:
            # Truncate reasoning intelligently for mobile
            if len(reasoning) > 120:
                reasoning = reasoning[:117] + "..."
            message += f"\n*Reason:*\n{reasoning}\n"

        # Options-specific info
        if is_options:
            if option_symbol:
                message += f"\nContract: `{option_symbol}`\n"
            if option_type:
                option_emoji = "📞" if option_type.lower() == "call" else "📉"
                message += f"Type: {option_emoji} {option_type.upper()}\n"
            if strike:
                message += f"Strike: {_format_currency(strike)}\n"
            if expiration:
                message += f"Expiry: {expiration}\n"
            if dte is not None:
                message += f"DTE: {dte} days\n"
            if delta is not None:
                message += f"Delta: {delta:.3f}\n"

        await self.send_message(message)

    async def notify_signal_logged(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        unrealized_pnl: Optional[float] = None,
        risk_amount: Optional[float] = None,
    ) -> None:
        """
        Notify about a signal being logged with P&L.

        Args:
            symbol: Trading symbol
            side: "long" or "short"
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            unrealized_pnl: Unrealized P&L
            risk_amount: Risk amount in dollars
        """
        side_emoji = "📈" if side.lower() == "long" else "📉"
        pnl_emoji = "💰" if unrealized_pnl and unrealized_pnl >= 0 else "💸"

        message = f"{side_emoji} *Signal Logged*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Side:* {side.upper()}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"

        if stop_loss:
            message += f"*Stop Loss:* ${stop_loss:,.2f}\n"

        if take_profit:
            message += f"*Take Profit:* ${take_profit:,.2f}\n"

        if unrealized_pnl is not None:
            message += f"\n{pnl_emoji} *Unrealized P&L:* ${unrealized_pnl:,.2f}\n"

        if risk_amount:
            message += f"*Risk:* ${risk_amount:,.2f}\n"

        await self.send_message(message)

    async def notify_exit(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        size: int,
        realized_pnl: float,
        hold_duration: Optional[str] = None,
        exit_reason: Optional[str] = None,
    ) -> None:
        """
        Notify about a position exit with P&L.

        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            entry_price: Entry price
            exit_price: Exit price
            size: Position size
            realized_pnl: Realized profit/loss
            hold_duration: How long position was held (optional)
            exit_reason: Reason for exit (optional)
        """
        pnl_emoji = "💰" if realized_pnl >= 0 else "💸"
        direction_emoji = "📈" if direction.lower() == "long" else "📉"

        message = f"{pnl_emoji} *Position Exited*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Direction:* {direction.upper()} {direction_emoji}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"
        message += f"*Exit:* ${exit_price:,.2f}\n"
        message += f"*Size:* {size} contracts\n"

        if hold_duration:
            message += f"*Hold Duration:* {hold_duration}\n"

        message += f"\n*Realized P&L:* ${realized_pnl:,.2f}\n"

        if exit_reason:
            message += f"\n*Exit Reason:* {exit_reason}\n"

        await self.send_message(message)

    async def notify_stop_loss(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_price: float,
        size: int,
        realized_pnl: float,
    ) -> None:
        """
        Notify about a stop loss hit.

        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            entry_price: Entry price
            stop_price: Stop loss price
            size: Position size
            realized_pnl: Realized loss
        """
        loss_pct = abs((stop_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        message = f"🛑 *Stop Loss Hit*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Direction:* {direction.upper()}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"
        message += f"*Stop:* ${stop_price:,.2f} ({loss_pct:.2f}%)\n"
        message += f"*Size:* {size} contracts\n"
        message += f"\n*Realized Loss:* ${realized_pnl:,.2f}\n"

        await self.send_message(message)

    async def notify_take_profit(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        target_price: float,
        size: int,
        realized_pnl: float,
    ) -> None:
        """
        Notify about a take profit hit.

        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            entry_price: Entry price
            target_price: Take profit price
            size: Position size
            realized_pnl: Realized profit
        """
        profit_pct = abs((target_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        message = f"🎯 *Take Profit Hit*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Direction:* {direction.upper()}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"
        message += f"*Target:* ${target_price:,.2f} ({profit_pct:.2f}%)\n"
        message += f"*Size:* {size} contracts\n"
        message += f"\n*Realized Profit:* ${realized_pnl:,.2f}\n"

        await self.send_message(message)

    async def notify_position_update(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        current_price: float,
        size: int,
        unrealized_pnl: float,
    ) -> None:
        """
        Notify about a position update (mark-to-market).

        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            entry_price: Entry price
            current_price: Current market price
            size: Position size
            unrealized_pnl: Unrealized profit/loss
        """
        pnl_emoji = "📈" if unrealized_pnl >= 0 else "📉"
        pnl_pct = abs((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        message = f"{pnl_emoji} *Position Update*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Direction:* {direction.upper()}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"
        message += f"*Current:* ${current_price:,.2f} ({pnl_pct:.2f}%)\n"
        message += f"*Size:* {size} contracts\n"
        message += f"\n*Unrealized P&L:* ${unrealized_pnl:,.2f}\n"

        await self.send_message(message)
