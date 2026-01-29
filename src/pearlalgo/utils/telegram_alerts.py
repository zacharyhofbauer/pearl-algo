"""
Telegram Alerts - Send notifications for trades and major events.
"""

from __future__ import annotations

import math
from typing import Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.sparkline import generate_progress_bar

try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:
    Bot = None
    TelegramError = Exception


TELEGRAM_TEXT_LIMIT = 4096
_TRUNC_SUFFIX = "\n\n…(truncated)"

# ---------------------------------------------------------------------------
# Mobile-first character limits (UX optimization)
# ---------------------------------------------------------------------------
# These limits ensure text fits on mobile screens without wrapping/truncation.
CHAR_LIMIT_HEADER = 40      # Dashboard headers (one line on mobile)
CHAR_LIMIT_BUTTON = 16      # Inline button labels (avoids truncation)
CHAR_LIMIT_ALERT = 60       # Alert headlines (two lines max)
CHAR_LIMIT_MENU_ITEM = 24   # Menu item text


def truncate_for_mobile(text: str, limit: int, suffix: str = "…") -> str:
    """
    Truncate text to fit mobile character limits.
    
    Args:
        text: Input text to truncate
        limit: Maximum character count
        suffix: Suffix to add when truncated (default: …)
        
    Returns:
        Truncated text with suffix if over limit, original if under
    """
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit - len(suffix)] + suffix


def format_button_label(text: str, count: int | None = None) -> str:
    """
    Format a button label to fit mobile limits (16 chars max).
    
    Args:
        text: Base button text
        count: Optional count to append (e.g., "Trades (3)")
        
    Returns:
        Formatted label under 16 chars
    """
    if count is not None and count > 0:
        # Try to fit count in parentheses
        full = f"{text} ({count})"
        if len(full) <= CHAR_LIMIT_BUTTON:
            return full
        # Truncate text to make room for count
        max_text = CHAR_LIMIT_BUTTON - len(f" ({count})") - 1
        return f"{text[:max_text]}… ({count})"
    
    return truncate_for_mobile(text, CHAR_LIMIT_BUTTON)


def format_header(text: str) -> str:
    """Format a header to fit mobile limits (40 chars)."""
    return truncate_for_mobile(text, CHAR_LIMIT_HEADER)


def format_alert_headline(text: str) -> str:
    """Format an alert headline to fit mobile limits (60 chars)."""
    return truncate_for_mobile(text, CHAR_LIMIT_ALERT)


def format_transparency_footer(
    agent_uptime_seconds: float | None = None,
    gateway_ok: bool | None = None,
    data_age_seconds: float | None = None,
    *,
    agent_running: bool | None = None,
    data_stale: bool | None = None,
) -> str:
    """
    Format always-visible system state footer for dashboard.
    
    Shows: Agent uptime | Gateway status | Data age
    
    Args:
        agent_uptime_seconds: Agent service uptime in seconds
        gateway_ok: Whether gateway is responding
        data_age_seconds: Age of market data in seconds
        
    Returns:
        Formatted footer string like "Agent: 3h | Gateway: OK | Data: 2s"
    """
    parts = []
    
    # Agent uptime / state
    if agent_running is True:
        if agent_uptime_seconds is not None:
            if agent_uptime_seconds < 60:
                uptime_str = f"{int(agent_uptime_seconds)}s"
            elif agent_uptime_seconds < 3600:
                uptime_str = f"{int(agent_uptime_seconds // 60)}m"
            else:
                hours = int(agent_uptime_seconds // 3600)
                mins = int((agent_uptime_seconds % 3600) // 60)
                uptime_str = f"{hours}h{mins}m"
            parts.append(f"Agent: {uptime_str}")
        else:
            parts.append("Agent: ON")
    elif agent_running is False:
        parts.append("Agent: OFF")
    else:
        # Unknown. If we still have an uptime value, show it; otherwise be explicit.
        if agent_uptime_seconds is not None:
            if agent_uptime_seconds < 60:
                uptime_str = f"{int(agent_uptime_seconds)}s"
            elif agent_uptime_seconds < 3600:
                uptime_str = f"{int(agent_uptime_seconds // 60)}m"
            else:
                hours = int(agent_uptime_seconds // 3600)
                mins = int((agent_uptime_seconds % 3600) // 60)
                uptime_str = f"{hours}h{mins}m"
            parts.append(f"Agent: {uptime_str}")
        else:
            parts.append("Agent: ?")
    
    # Gateway status
    if gateway_ok is True:
        parts.append("Gateway: OK")
    elif gateway_ok is False:
        parts.append("Gateway: DOWN")
    else:
        parts.append("Gateway: ?")
    
    # Data freshness
    if data_age_seconds is not None:
        if data_age_seconds < 60:
            age_str = f"{int(data_age_seconds)}s"
        elif data_age_seconds < 3600:
            age_str = f"{int(data_age_seconds // 60)}m"
        else:
            age_str = f"{int(data_age_seconds // 3600)}h"
        if data_stale is True:
            parts.append(f"Data: {EMOJI_ERROR} {age_str}")
        else:
            parts.append(f"Data: {age_str}")
    else:
        parts.append("Data: N/A")
    
    return " | ".join(parts)

# Visual formatting constants (Telegram clients can render multiple leading spaces inconsistently)
_BULLET_SEP = " • "
_SUBLINE_PREFIX = "↳ "


# ---------------------------------------------------------------------------
# Standardized Terminology Map (canonical labels for UI consistency)
# ---------------------------------------------------------------------------
# Use these constants across all Telegram views to ensure consistent wording.
#
# SERVICES:
#   Agent    = NQ Agent service (the autonomous trading system)
#   Gateway  = IBKR Gateway (the broker connection)
#
# ACTIVITY:
#   Scans    = Per-cycle processing iterations (each scan may generate signals)
#   Signals  = Trading opportunities generated by the strategy
#   Buffer   = Rolling bar data held in memory
#
# MARKET GATES:
#   Futures  = CME futures market open/closed (ETH + maintenance)
#   Session  = Strategy session window (when signals are allowed)
#
# POSITIONS:
#   Active Trades = Currently open positions (signals with status="entered")
#
# STATUS:
#   RUNNING / STOPPED / PAUSED = service states
#   OPEN / CLOSED = gate states
#   Active / Slow / Stale = activity pulse states

# ---------------------------------------------------------------------------
# Standardized Emoji System (UI consistency)
# ---------------------------------------------------------------------------
# Use these constants for consistent visual language across all Telegram UI.
#
# STATUS INDICATORS (traffic-light pattern):
EMOJI_OK = "🟢"       # Online, running, healthy, positive
EMOJI_ERROR = "🔴"    # Offline, stopped, error, negative
EMOJI_WARN = "🟡"     # Warning, degraded, pending
EMOJI_UNKNOWN = "⚪"  # Unknown, N/A, neutral

# DIRECTION INDICATORS:
EMOJI_LONG = "📈"     # Long position, price up
EMOJI_SHORT = "📉"    # Short position, price down
EMOJI_UP = "↗️"       # Trend up
EMOJI_DOWN = "↘️"     # Trend down

# CATEGORY ICONS (menu items):
EMOJI_ACTIVITY = "📊"   # Activity, trades, performance
EMOJI_SYSTEM = "🎛️"    # System controls
EMOJI_HEALTH = "🛡"     # Health, status, monitoring
EMOJI_MARKETS = "🌐"    # Markets
EMOJI_BOTS = "🤖"       # Trading bots
EMOJI_SETTINGS = "⚙️"   # Settings
EMOJI_REFRESH = "🔄"    # Refresh
EMOJI_BACK = "🏠"       # Back to menu/home

# ACTION ICONS:
EMOJI_START = "🚀"    # Start action
EMOJI_STOP = "🛑"     # Stop action
EMOJI_ALERT = "⚠️"    # Alert, warning
EMOJI_ERROR_X = "❌"  # Error, failure
EMOJI_SUCCESS = "✅"  # Success, confirmed
EMOJI_INFO = "ℹ️"     # Information

# FINANCIAL ICONS:
EMOJI_MONEY = "💰"    # Price, money
EMOJI_PROFIT = "🟢"   # Profit (same as OK)
EMOJI_LOSS = "🔴"     # Loss (same as ERROR)
EMOJI_TARGET = "🎯"   # Target, active trade

# Service labels
LABEL_AGENT = "Agent"
LABEL_GATEWAY = "Gateway"

# Service states
STATE_RUNNING = "RUNNING"
STATE_STOPPED = "STOPPED"
STATE_PAUSED = "PAUSED"

# Gate labels
LABEL_FUTURES = "Futures"
LABEL_SESSION = "Session"

# Gate states
GATE_OPEN = "OPEN"
GATE_CLOSED = "CLOSED"
GATE_UNKNOWN = "?"

# Activity labels
LABEL_SCANS = "scans"
LABEL_SIGNALS = "signals"
LABEL_BUFFER = "bars"
LABEL_ERRORS = "errors"

# Position labels
LABEL_ACTIVE_TRADES = "Active Trades"

# Activity pulse states
PULSE_ACTIVE = "Active"
PULSE_SLOW = "Slow"
PULSE_STALE = "Stale"
PULSE_PAUSED = "Paused"
PULSE_UNKNOWN = "Unknown"


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
    direction_str = str(direction) if direction else ""
    direction_lower = direction_str.lower()
    if direction_lower == "long":
        return "🟢", "LONG"
    elif direction_lower == "short":
        return "🔴", "SHORT"
    return "⚪", direction_str.upper() if direction_str else "N/A"


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

def _escape_markdown_underscores_in_words(text: str) -> str:
    """
    Escape underscores that commonly appear in filenames/identifiers (e.g. `foo_bar.py`)
    while preserving intentional Markdown formatting like `_italic_`.
    """
    if not text:
        return ""
    import re
    # Only escape underscores that are *inside* words (i.e., surrounded by word chars).
    # This avoids breaking intended Markdown like `_italic_` which is usually delimited by whitespace/punctuation.
    return re.sub(r"(?<=\\w)_(?=\\w)", r"\\_", str(text))


def sanitize_telegram_markdown(text: str) -> str:
    """
    Sanitize a message intended for Telegram's legacy Markdown parse_mode.

    Primary goal: avoid parse errors from unescaped underscores in filenames/identifiers,
    while keeping existing `*bold*`, `_italic_`, and `` `code` `` formatting intact.

    Strategy:
    - Split around backtick code spans and only escape underscores-in-words in non-code segments.
    """
    if not text:
        return ""

    s = str(text)
    if "_" not in s:
        return s

    out: list[str] = []
    in_code = False
    i = 0
    n = len(s)

    while i < n:
        ch = s[i]
        if ch == "`":
            # Treat any run of backticks as a single delimiter to better handle ``` blocks.
            j = i
            while j < n and s[j] == "`":
                j += 1
            out.append(s[i:j])
            in_code = not in_code
            i = j
            continue

        # Copy up to next backtick
        j = i
        while j < n and s[j] != "`":
            j += 1
        seg = s[i:j]
        if not in_code:
            seg = _escape_markdown_underscores_in_words(seg)
        out.append(seg)
        i = j

    return "".join(out)


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


def format_bot_name(bot_id: str) -> str:
    """
    Format a bot ID into a display name.
    
    Examples:
        "pearl_bot_auto" -> "Pearl Bot Auto"
        "scanner" -> "Scanner"
        "my_custom_bot" -> "My Custom Bot"
    """
    if not bot_id:
        return "Scanner"
    # Replace underscores with spaces and title case
    return str(bot_id).replace("_", " ").title()


def escape_subprocess_output(text: str) -> str:
    """
    Escape subprocess/shell output for safe inclusion in Telegram Markdown messages.
    
    This is more aggressive than escape_markdown() since subprocess output can contain
    arbitrary characters including file paths (agent_NQ.pid), shell escape sequences, etc.
    
    For reliability, we strip ANSI escape sequences and escape Markdown-sensitive chars.
    """
    if not text:
        return ""
    
    import re
    
    result = str(text)
    
    # Strip ANSI escape sequences (colors, cursor movements, etc.)
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    result = ansi_escape.sub('', result)
    
    # Escape Markdown-sensitive characters
    result = result.replace("\\", "\\\\")  # Escape backslashes first
    result = result.replace("_", "\\_")
    result = result.replace("*", "\\*")
    result = result.replace("`", "\\`")
    result = result.replace("[", "\\[")
    result = result.replace("]", "\\]")
    
    return result


# ---------------------------------------------------------------------------
# Activity and timing helpers (UX improvement v2)
# ---------------------------------------------------------------------------

def format_activity_pulse(
    last_cycle_seconds: float | None,
    is_paused: bool = False,
) -> tuple[str, str]:
    """
    Format activity pulse indicator showing time since last scan cycle.
    
    Returns (emoji, text) tuple using standardized terminology.
    
    Args:
        last_cycle_seconds: Seconds since last scan cycle completed
        is_paused: Whether the agent is paused
        
    Returns:
        Tuple of (emoji, description) e.g. ("🟢", "Active (30s ago)")
    """
    if is_paused:
        return "⏸️", PULSE_PAUSED
    
    if last_cycle_seconds is None:
        return "⚪", PULSE_UNKNOWN
    
    if last_cycle_seconds < 0:
        return "⚪", PULSE_UNKNOWN
    
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
    
    # Determine health based on age (thresholds: 2min active, 5min slow)
    if last_cycle_seconds <= 120:  # < 2 minutes
        return "🟢", f"{PULSE_ACTIVE} ({time_str})"
    elif last_cycle_seconds <= 300:  # 2-5 minutes
        return "🟡", f"{PULSE_SLOW} ({time_str})"
    else:  # > 5 minutes
        return "🔴", f"{PULSE_STALE} ({time_str})"


def format_next_session_time(
    session_start: str | None = None,
    session_end: str | None = None,
) -> str:
    """
    Get the next strategy session opening time based on configured session times.
    
    Args:
        session_start: Session start time in HH:MM format (e.g., "09:30" or "18:00")
        session_end: Session end time in HH:MM format (e.g., "16:00" or "16:10")
        
    Returns:
        Formatted string like "Opens today at 09:30 AM ET" or safe fallback.
        
    Note:
        If session_start is not provided, returns a safe fallback message
        that directs users to /config rather than showing hardcoded times.
    """
    # Safe fallback when session times aren't provided
    if not session_start:
        return "Menu → Settings → Config"
    
    try:
        from datetime import datetime, timedelta
        import pytz
        
        et_tz = pytz.timezone('US/Eastern')
        now = datetime.now(et_tz)
        
        # Parse session start time (HH:MM format)
        try:
            start_parts = session_start.split(":")
            start_hour = int(start_parts[0])
            start_minute = int(start_parts[1]) if len(start_parts) > 1 else 0
        except (ValueError, IndexError):
            return "Menu → Settings → Config"
        
        # Parse session end time if provided (for cross-midnight detection)
        end_hour = None
        end_minute = None
        if session_end:
            try:
                end_parts = session_end.split(":")
                end_hour = int(end_parts[0])
                end_minute = int(end_parts[1]) if len(end_parts) > 1 else 0
            except (ValueError, IndexError):
                pass
        
        # Detect cross-midnight session (e.g., 18:00 - 16:10)
        # Cross-midnight means start_hour > end_hour (evening to afternoon next day)
        is_cross_midnight = False
        if end_hour is not None and start_hour > end_hour:
            is_cross_midnight = True
        
        session_open = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        
        if is_cross_midnight:
            # For cross-midnight sessions (e.g., 18:00 start):
            # - If before start time today, next session is today at start_hour
            # - If after start time, we're likely IN the session or past end, next is tomorrow
            current_time_minutes = now.hour * 60 + now.minute
            start_time_minutes = start_hour * 60 + start_minute
            end_time_minutes = end_hour * 60 + end_minute if end_hour is not None else 0
            
            # We're "before session" if:
            # - After end_time (afternoon) and before start_time (evening)
            if end_time_minutes < current_time_minutes < start_time_minutes:
                # Session opens later today
                next_open = session_open
            else:
                # We're either in session or past it, next session is tomorrow
                next_open = session_open + timedelta(days=1)
        else:
            # Standard same-day session (e.g., 09:30 - 16:00)
            if now.hour < start_hour or (now.hour == start_hour and now.minute < start_minute):
                next_open = session_open
            else:
                # Next session is tomorrow
                next_open = session_open + timedelta(days=1)
        
        # Skip weekends (futures typically closed Sat/Sun)
        while next_open.weekday() >= 5:  # 5=Sat, 6=Sun
            next_open += timedelta(days=1)
        
        day_name = next_open.strftime("%A")
        time_str = next_open.strftime("%I:%M %p ET").lstrip("0")  # Remove leading zero
        
        if next_open.date() == now.date():
            return f"Opens today at {time_str}"
        elif next_open.date() == (now + timedelta(days=1)).date():
            return f"Opens tomorrow at {time_str}"
        else:
            return f"Opens {day_name} at {time_str}"
    except Exception:
        return "Menu → Settings → Config"


def format_session_window(
    session_start: str | None = None,
    session_end: str | None = None,
) -> str:
    """
    Format the configured session window for display.
    
    Args:
        session_start: Session start time in HH:MM format (e.g., "09:30" or "18:00")
        session_end: Session end time in HH:MM format (e.g., "16:00" or "16:10")
        
    Returns:
        Formatted string like "18:00–16:10 ET" or safe fallback.
    """
    if not session_start or not session_end:
        return "Menu → Settings → Config"
    
    try:
        # Format times for display (keep HH:MM format, add ET)
        return f"{session_start}–{session_end} ET"
    except Exception:
        return "Menu → Settings → Config"


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
        return f"⏳ Monitor for {dir_action} entry at entry price"
    elif status_lower == "entered":
        return "🎯 Position ACTIVE - Watch stop/TP levels"
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
        from datetime import timezone
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
    Format market gates line for Home Card using standardized terminology.

    Returns a compact line like: 🟢 Futures: OPEN • 🟢 Session: OPEN
    """
    futures_emoji = "🟢" if futures_market_open is True else "🔴" if futures_market_open is False else "⚪"
    futures_text = GATE_OPEN if futures_market_open is True else GATE_CLOSED if futures_market_open is False else GATE_UNKNOWN
    strat_emoji = "🟢" if strategy_session_open is True else "🔴" if strategy_session_open is False else "⚪"
    strat_text = GATE_OPEN if strategy_session_open is True else GATE_CLOSED if strategy_session_open is False else GATE_UNKNOWN
    return f"{futures_emoji} {LABEL_FUTURES}: {futures_text}{_BULLET_SEP}{strat_emoji} {LABEL_SESSION}: {strat_text}"


def format_service_status(
    agent_running: bool,
    gateway_running: bool,
    paused: bool = False,
) -> str:
    """
    Format service status line for Home Card using standardized terminology.

    Returns a compact line like: 🟢 Agent: RUNNING • 🟢 Gateway: RUNNING
    """
    agent_emoji = "🟢" if agent_running and not paused else "⏸️" if paused else "🔴"
    agent_text = STATE_PAUSED if paused else (STATE_RUNNING if agent_running else STATE_STOPPED)
    gateway_emoji = "🟢" if gateway_running else "🔴"
    gateway_text = STATE_RUNNING if gateway_running else STATE_STOPPED
    return f"{agent_emoji} {LABEL_AGENT}: {agent_text}{_BULLET_SEP}{gateway_emoji} {LABEL_GATEWAY}: {gateway_text}"


def format_activity_line(
    cycles_session: int | None,
    cycles_total: int,
    signals_generated: int,
    signals_sent: int,
    errors: int,
    buffer_size: int,
    buffer_target: int | None = None,
    signal_send_failures: int = 0,
    volume_ratio: float | None = None,
    pressure_badge: str | None = None,
    delta_pct: float | None = None,
    compact_metrics_enabled: bool = True,
    show_progress_bars: bool = False,
    show_volume_metrics: bool = True,
    compact_metric_width: int = 10,
) -> str:
    """
    Format activity summary line for Home Card using standardized terminology.

    Returns labeled metrics like:
    📊 145 scans (session) / 1,595 total • 2 gen / 0 sent • 25/100 bars • 0 errors

    V2 spec: All ratios are now self-explanatory with explicit labels.
    """
    # Scans: labeled with (session) / total
    if cycles_session is not None:
        scans_part = f"{cycles_session:,} {LABEL_SCANS} (session) / {cycles_total:,} total"
    else:
        scans_part = f"{cycles_total:,} {LABEL_SCANS}"

    # Signals: labeled gen/sent (add fail only if non-zero)
    if signal_send_failures > 0:
        signals_part = f"{signals_generated} gen / {signals_sent} sent / {signal_send_failures} fail"
    else:
        signals_part = f"{signals_generated} gen / {signals_sent} sent"

    # Buffer: default is numeric only (the ████ bar is usually redundant)
    if buffer_target is not None:
        buffer_part_numeric = f"{int(buffer_size)}/{int(buffer_target)} {LABEL_BUFFER}"
    else:
        buffer_part_numeric = f"{int(buffer_size)} {LABEL_BUFFER}"

    if compact_metrics_enabled and show_progress_bars:
        buffer_part = format_compact_ratio(
            buffer_size,
            buffer_target,
            LABEL_BUFFER,
            show_bar=True,
            width=int(compact_metric_width or 10),
        )
    else:
        buffer_part = buffer_part_numeric

    # Optional: compact volume cues (keep short for mobile)
    extra_parts: list[str] = []
    if compact_metrics_enabled and show_volume_metrics:
        if volume_ratio is not None:
            s = format_compact_metric(volume_ratio, 1.0, "vol", unit="x")
            if s:
                extra_parts.append(s)
        if delta_pct is not None:
            try:
                dp = float(delta_pct)
                # Hide tiny deltas to reduce noise
                if math.isfinite(dp) and abs(dp) >= 1.0:
                    s = format_compact_metric(dp, 1.0, "Δ", unit="%")
                    if s:
                        extra_parts.append(s)
            except Exception:
                pass
        if pressure_badge:
            badge = str(pressure_badge).strip()
            if badge:
                extra_parts.append(badge)

    # Errors
    errors_part = f"{int(errors)} {LABEL_ERRORS}"

    parts: list[str] = [f"📊 {scans_part}", signals_part, buffer_part]
    if extra_parts:
        parts.extend(extra_parts)
    parts.append(errors_part)
    return " • ".join(parts)


def _format_pressure_badge(bias: str | None, strength: str | None) -> str | None:
    """Ultra-compact pressure badge for the activity line (mobile-friendly)."""
    b = (bias or "").strip().lower()
    s = (strength or "").strip().lower()

    if b == "buyers":
        emoji = "🟢"
        label = "BUYERS"
        arrow_up = True
    elif b == "sellers":
        emoji = "🔴"
        label = "SELLERS"
        arrow_up = False
    elif b == "mixed":
        emoji = "⚪"
        label = "MIXED"
        arrow_up = True
    else:
        return None

    arrows = ""
    if s == "light":
        arrows = "▲" if arrow_up else "▼"
    elif s == "moderate":
        arrows = "▲▲" if arrow_up else "▼▼"
    elif s == "strong":
        arrows = "▲▲▲" if arrow_up else "▼▼▼"

    return f"{emoji} {label}{' ' + arrows if arrows else ''}"


def format_compact_status(
    value: float | None,
    thresholds: tuple[float, float] = (0.8, 0.5),
    *,
    higher_is_better: bool = True,
) -> str:
    """
    Return a simple traffic-light emoji for a value.

    thresholds = (good, warn) in normalized units (0..1) by default.
    """
    if value is None:
        return "⚪"
    try:
        v = float(value)
    except Exception:
        return "⚪"
    if not math.isfinite(v):
        return "⚪"

    good, warn = thresholds
    if higher_is_better:
        if v >= good:
            return "🟢"
        if v >= warn:
            return "🟡"
        return "🔴"
    # Lower is better (invert comparisons)
    if v <= good:
        return "🟢"
    if v <= warn:
        return "🟡"
    return "🔴"


def format_compact_ratio(
    current: int | float,
    target: int | float | None,
    label: str,
    show_bar: bool = True,
    *,
    width: int = 10,
    thresholds: tuple[float, float] = (0.8, 0.5),
) -> str:
    """
    Compact ratio like:
      '🟢 [██████░░░░] 80/100 bars'
    """
    try:
        cur = float(current)
    except Exception:
        cur = 0.0

    if target is None:
        return f"{int(cur)} {label}"
    try:
        tgt = float(target)
    except Exception:
        tgt = 0.0
    if tgt <= 0:
        return f"{int(cur)} {label}"

    ratio = cur / tgt if tgt > 0 else 0.0
    ratio = max(0.0, min(1.0, ratio))
    emoji = format_compact_status(ratio, thresholds)
    if not show_bar:
        return f"{emoji} {int(cur)}/{int(tgt)} {label}"

    bar = generate_progress_bar(int(cur), int(tgt), width=int(width))
    return f"{emoji} [{bar}] {int(cur)}/{int(tgt)} {label}"


def format_compact_metric(
    value: float | None,
    baseline: float | None,
    label: str,
    unit: str = "",
) -> str | None:
    """
    Compact metric formats used in activity lines:
      - Multiplier: '1.3x vol'
      - Percent: '+15% Δ'
    """
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return None
    if not math.isfinite(v):
        return None

    u = (unit or "").strip()
    lbl = (label or "").strip()

    if u == "x":
        # Treat v as already a ratio when baseline is None/1.0.
        if baseline is not None:
            try:
                b = float(baseline)
            except Exception:
                b = 1.0
            if b not in (0.0,) and math.isfinite(b) and b != 1.0:
                v = v / b
        return f"{v:.1f}x {lbl}".strip()

    if u == "%":
        return f"{v:+.0f}% {lbl}".strip()

    # Fallback: raw value with optional unit
    return f"{v:.2f}{u} {lbl}".strip()


def format_stale_callout(
    data_age_minutes: float,
    impact: str = "signals paused",
    *,
    threshold_minutes: float | None = None,
) -> str:
    """
    Format a staleness callout with age, impact, and next action.

    V2 spec: When data is stale, provide a single actionable line.

    Args:
        data_age_minutes: Age of data in minutes
        impact: Impact description (e.g., "signals paused")

    Returns:
        Formatted staleness callout like:
        ⏰ Data stale (11m) • signals paused • Menu → Health → Data
    """
    age_str = f"{data_age_minutes:.0f}m" if data_age_minutes < 60 else f"{data_age_minutes / 60:.1f}h"
    if threshold_minutes is not None:
        try:
            thr = float(threshold_minutes)
        except Exception:
            thr = 0.0
        if thr > 0:
            thr_str = f"{thr:.0f}m" if thr < 60 else f"{thr / 60:.1f}h"
            return f"⏰ Data stale ({age_str}/{thr_str}) • {impact} • Menu → Health → Data"
    return f"⏰ Data stale ({age_str}) • {impact} • Menu → Health → Data"


def _format_execution_status(
    execution_enabled: bool,
    execution_armed: bool,
    execution_mode: str | None,
) -> str:
    """
    Format execution status line for Home Card.

    Makes trading state immediately obvious to operator:
    - OFF = no orders will be placed even if signals generate
    - DRY_RUN (ARMED) = "would trade" entries logged but no orders
    - PAPER (ARMED) = paper trading orders placed
    - LIVE (ARMED) = real orders placed
    """
    if not execution_enabled:
        return "🚫 *Execution:* OFF"

    mode_str = (execution_mode or "dry_run").lower()
    mode_display = {
        "dry_run": "DRY\\_RUN",
        "paper": "PAPER",
        "live": "LIVE",
    }.get(mode_str, mode_str.upper())

    if execution_armed:
        emoji = "✅" if mode_str == "live" else "🟡" if mode_str == "paper" else "📝"
        return f"{emoji} *Execution:* {mode_display} (ARMED)"
    else:
        return f"⏸️ *Execution:* {mode_display} (DISARMED)"


def _format_data_quality_line(
    *,
    data_level: str | None,
    data_age_minutes: float | None,
    data_stale_threshold_minutes: float,
    buffer_size: int,
    buffer_target: int | None,
    show_when_healthy: bool = False,
    compact_metrics_enabled: bool = True,
    show_progress_bars: bool = False,
    bar_width: int = 10,
) -> str | None:
    """
    Compact data quality line (source + freshness + rough quality score).

    Designed to be shown only when something is degraded unless show_when_healthy=True.
    """
    lvl = (data_level or "").strip().lower()

    # Source
    if lvl in ("historical", "historical_fallback"):
        src = "📜 Hist"
        src_penalty = 40
    elif lvl == "error":
        src = "❌ Err"
        src_penalty = 70
    elif lvl == "unknown":
        src = "❓ ?"
        src_penalty = 25
    elif lvl == "level2":
        src = "📊 L2"
        src_penalty = 0
    else:
        # Treat missing/level1 as the healthy baseline.
        src = "📡 L1"
        src_penalty = 0

    # Freshness
    try:
        age = float(data_age_minutes) if data_age_minutes is not None else None
    except Exception:
        age = None
    try:
        thr = float(data_stale_threshold_minutes)
    except Exception:
        thr = 0.0

    freshness_penalty = 0.0
    freshness_emoji = "⚪"
    age_str = "?"
    thr_str = "?"
    if age is not None and math.isfinite(age) and age >= 0:
        age_str = f"{age:.0f}m" if age < 60 else f"{age / 60:.1f}h"
    if thr > 0 and math.isfinite(thr):
        thr_str = f"{thr:.0f}m" if thr < 60 else f"{thr / 60:.1f}h"
    if age is None or not (age is not None and math.isfinite(age)):
        freshness_penalty = 15.0
        freshness_emoji = "⚪"
    elif thr > 0:
        if age <= thr:
            freshness_emoji = "🟢"
            # Slight caution when near the threshold
            if age >= thr * 0.8:
                freshness_emoji = "🟡"
        else:
            freshness_emoji = "🔴"
            # Degrade up to 35 points based on how far past the threshold we are.
            freshness_penalty = min(35.0, ((age - thr) / thr) * 35.0)
    else:
        # No threshold configured; treat as unknown-ish.
        freshness_penalty = 10.0
        freshness_emoji = "⚪"

    # Buffer contribution (rolling fill)
    buffer_penalty = 0.0
    buf_ratio = None
    if buffer_target is not None:
        try:
            bt = float(buffer_target)
        except Exception:
            bt = 0.0
        if bt > 0:
            try:
                buf_ratio = float(buffer_size) / bt
            except Exception:
                buf_ratio = 0.0
            buf_ratio = max(0.0, min(1.0, buf_ratio))
            buffer_penalty = (1.0 - buf_ratio) * 25.0

    quality = 100.0 - float(src_penalty) - float(freshness_penalty) - float(buffer_penalty)
    quality = max(0.0, min(100.0, quality))
    q_int = int(round(quality))
    if compact_metrics_enabled and show_progress_bars:
        w = max(5, min(20, int(bar_width or 10)))
        q_bar = generate_progress_bar(q_int, 100, width=w)
        quality_part = f"[{q_bar}] {q_int}%"
    else:
        quality_part = f"{q_int}%"

    is_data_stale = (age is not None and thr > 0 and age > thr)
    is_source_degraded = lvl not in ("", "level1", "level2")
    is_buffer_low = buf_ratio is not None and buf_ratio < 0.8
    should_show = show_when_healthy or is_data_stale or is_source_degraded or is_buffer_low
    if not should_show:
        return None

    return f"📡 *Data:* {src}{_BULLET_SEP}{freshness_emoji} {age_str}/{thr_str}{_BULLET_SEP}{quality_part}"


def format_performance_line(
    wins: int,
    losses: int,
    win_rate: float,
    total_pnl: float,
    *,
    compact_metrics_enabled: bool = True,
    show_progress_bars: bool = False,
    bar_width: int = 10,
) -> str:
    """
    Format 7-day performance summary for Home Card.

    Returns compact line like: 📈 5W/2L • 71% WR • 🟢 +$350.00
    """
    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

    # Win-rate progress bar (keep compact for mobile)
    try:
        wr = float(win_rate)
    except Exception:
        wr = 0.0
    wr = max(0.0, min(100.0, wr))
    if compact_metrics_enabled and show_progress_bars:
        w = max(5, min(20, int(bar_width or 10)))
        wr_bar = generate_progress_bar(int(round(wr)), 100, width=w)
        wr_part = f"[{wr_bar}] {wr:.0f}% WR"
    else:
        wr_part = f"{wr:.0f}% WR"

    return f"📈 {int(wins)}W/{int(losses)}L • {wr_part} • {pnl_emoji} {_format_currency(total_pnl)}"


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
    # New field for quiet reason (v4)
    quiet_reason: str | None = None,  # Why agent is quiet (e.g., "StrategySessionClosed")
    # Signal diagnostics (when no signals)
    signal_diagnostics: str | None = None,  # Compact summary like "Raw: 3 → Valid: 0 | Filtered: 2 conf, 1 R:R"
    # Buy/Sell pressure (volume-based proxy)
    buy_sell_pressure: str | None = None,  # e.g. "🟢 Pressure: BUYERS ▲▲ (Δ +18%, Vol 1.3x, 2h)"
    buy_sell_pressure_raw: dict | None = None,  # e.g. {"bias":"buyers","strength":"moderate","score_pct":18,"volume_ratio":1.3}
    # Active trades (v5 calm-minimal)
    active_trades_count: int = 0,  # Number of currently active positions
    active_trades_unrealized_pnl: float | None = None,  # Total unrealized PnL across active trades (USD)
    active_trades_price_source: str | None = None,  # e.g., "level1", "historical"
    open_positions_count: int | None = None,  # Broker-backed open positions count (optional)
    # Data level indicator (v9 - IBKR data quality visibility)
    data_level: str | None = None,  # e.g., "level1", "historical", "unknown"
    # Data staleness (v6 - separate from state staleness)
    data_age_minutes: float | None = None,  # Age of market data in minutes
    data_stale_threshold_minutes: float = 10.0,  # Minutes; show warning if older
    # Session window config (v7 - config-driven session messaging)
    session_start: str | None = None,  # Session start time in HH:MM format (e.g., "18:00")
    session_end: str | None = None,  # Session end time in HH:MM format (e.g., "16:10")
    # Execution status (v10 - make trading state obvious)
    execution_enabled: bool = False,  # Whether execution adapter is enabled
    execution_armed: bool = False,  # Whether execution is armed (ready to place orders)
    execution_mode: str | None = None,  # "dry_run", "paper", or "live"
    # Telegram UI formatting (config-driven)
    compact_metrics_enabled: bool = True,
    show_progress_bars: bool = False,
    show_volume_metrics: bool = True,
    compact_metric_width: int = 10,
    *,
    legacy: bool = False,
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
        quiet_reason: Why agent is quiet (e.g., "StrategySessionClosed", "NoOpportunity")
        buy_sell_pressure: Buy/Sell pressure proxy string (volume-based)
        active_trades_count: Number of currently active positions (shown when > 0)
        open_positions_count: Broker-backed open positions (preferred for display when set)
        data_level: Data level indicator ("level1", "historical", "unknown") for IBKR visibility
        data_age_minutes: Age of market data in minutes (for v2 staleness callout)
        data_stale_threshold_minutes: Threshold in minutes for showing stale warning (default: 10)
        session_start: Session start time in HH:MM format (e.g., "18:00") for config-driven messaging
        session_end: Session end time in HH:MM format (e.g., "16:10") for config-driven messaging

    Returns:
        Formatted Home Card message string

    V2 SPEC CHANGES:
    - Activity metrics are now labeled (e.g., "145 scans (session) / 1,595 total")
    - Staleness callout includes age + impact + next action
    - Derived context (pressure, diagnostics) suppressed when data is stale
    """
    # -----------------------------------------------------------------------
    # IMPORTANT (2026-01): Legacy Home Card is deprecated.
    #
    # The canonical dashboard layout is now the /start-style glanceable card
    # (used by the Telegram command handler + push dashboards).
    #
    # This function remains only for backward compatibility; by default it
    # returns the glanceable card to prevent UI drift / old layouts “slipping in”.
    #
    # To force the legacy Home Card layout (tests/dev only), pass legacy=True.
    # -----------------------------------------------------------------------
    if not legacy:
        # Best-effort derive staleness state for the glanceable card dots.
        data_age_seconds = None
        try:
            if data_age_minutes is not None:
                data_age_seconds = float(data_age_minutes) * 60.0
        except Exception:
            data_age_seconds = None

        data_stale: bool | None = None
        try:
            if data_age_seconds is None:
                data_stale = None
            elif not agent_running or paused:
                data_stale = None
            elif futures_market_open is False and strategy_session_open is False:
                # Off-hours: stale data is expected.
                data_stale = None
            else:
                data_stale = (float(data_age_seconds) / 60.0) > float(data_stale_threshold_minutes)
        except Exception:
            data_stale = None

        # When callers can’t determine gateway status, avoid asserting green.
        gateway_status: bool | None = None if gateway_unknown else bool(gateway_running)

        # Use the calm-minimal /start layout.
        return format_glanceable_card(
            symbol=str(symbol),
            time_str=str(time_str or ""),
            agent_running=bool(agent_running),
            gateway_running=gateway_status,
            latest_price=latest_price,
            daily_pnl=None,
            active_trades_count=int(active_trades_count or 0),
            futures_market_open=futures_market_open,
            strategy_session_open=strategy_session_open,
            market=None,
            trading_bot="scanner",
            ai_ready=False,
            agent_uptime_seconds=None,
            data_age_seconds=data_age_seconds,
            agent_healthy=None,
            data_stale=data_stale,
        )

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

    # Compute staleness flags early (used by data line + later conditional sections)
    is_state_stale = (
        state_age_seconds is not None
        and state_age_seconds > state_stale_threshold
    )
    is_data_stale = (
        data_age_minutes is not None
        and data_age_minutes > data_stale_threshold_minutes
    )

    # Data quality line (source + freshness + rough quality score)
    if compact_metrics_enabled:
        data_quality_line = _format_data_quality_line(
            data_level=data_level,
            data_age_minutes=data_age_minutes,
            data_stale_threshold_minutes=data_stale_threshold_minutes,
            buffer_size=buffer_size,
            buffer_target=buffer_target,
            compact_metrics_enabled=compact_metrics_enabled,
            show_progress_bars=show_progress_bars,
            bar_width=int(compact_metric_width or 10),
        )
        if data_quality_line:
            lines.append(data_quality_line)
    else:
        # Legacy, minimal indicator: show degraded data source only.
        lvl = (data_level or "").strip().lower()
        if lvl in ("historical", "historical_fallback"):
            lines.append("📜 *Data:* Historical fallback")
        elif lvl == "error":
            lines.append("❌ *Data:* Fetch error")
        elif lvl == "unknown":
            lines.append("❓ *Data:* Unknown source")

    lines.append("")  # Blank line separator

    # Service status line (with gateway_unknown handling)
    if gateway_unknown:
        # Show gateway as unknown rather than asserting running/stopped
        agent_emoji = "🟢" if agent_running and not paused else "⏸️" if paused else "🔴"
        agent_text = STATE_PAUSED if paused else (STATE_RUNNING if agent_running else STATE_STOPPED)
        lines.append(f"{agent_emoji} {LABEL_AGENT}: {agent_text}{_BULLET_SEP}⚪ {LABEL_GATEWAY}: {GATE_UNKNOWN}")
    else:
        lines.append(format_service_status(agent_running, gateway_running, paused))

    # Execution status line (always show - critical for operator awareness)
    exec_line = _format_execution_status(execution_enabled, execution_armed, execution_mode)
    if exec_line:
        lines.append(exec_line)

    # CONDITIONAL: Pause reason (if paused)
    if paused and pause_reason:
        reason_safe = safe_label(pause_reason)
        lines.append(f"{_SUBLINE_PREFIX}⚠️ Reason: {reason_safe}")
        # Add action cue for circuit-breaker style pauses
        if "circuit" in pause_reason.lower() or "error" in pause_reason.lower():
            lines.append(f"{_SUBLINE_PREFIX}💡 Manual intervention required")

    # CONDITIONAL: Activity pulse (when running and we have cycle data)
    if agent_running and not paused and last_cycle_seconds is not None:
        pulse_emoji, pulse_text = format_activity_pulse(last_cycle_seconds, is_paused=paused)
        lines.append(f"{pulse_emoji} {pulse_text}")

    # CONDITIONAL: Data staleness callout (v2 spec: age + impact + action)
    # This takes precedence over state staleness for clarity
    if is_data_stale and data_age_minutes is not None:
        lines.append(
            format_stale_callout(
                data_age_minutes,
                impact="signals paused",
                threshold_minutes=data_stale_threshold_minutes,
            )
        )
    elif is_state_stale:
        # Fallback to state staleness if no data age info
        age_mins = state_age_seconds / 60.0 if state_age_seconds else 0
        lines.append(f"⚠️ State {age_mins:.1f}m old (may be outdated)")

    # Gates line
    lines.append(format_gate_status(futures_market_open, strategy_session_open))

    # CONDITIONAL: Gate expectation explanation (only when session closed)
    if strategy_session_open is False:
        # Use config-driven session window if available
        if session_start and session_end:
            session_window = format_session_window(session_start, session_end)
            next_session = format_next_session_time(session_start, session_end)
            lines.append(f"{_SUBLINE_PREFIX}ℹ️ Signals suppressed{_BULLET_SEP}Session: {session_window}")
            lines.append(f"{_SUBLINE_PREFIX}📅 {next_session}")
        else:
            # Safe fallback when session config not available
            lines.append(f"{_SUBLINE_PREFIX}ℹ️ Signals suppressed{_BULLET_SEP}Menu → Settings → Config")
    elif futures_market_open is False and strategy_session_open is not False:
        lines.append(f"{_SUBLINE_PREFIX}ℹ️ Data may be delayed (market closed)")
    
    # CONDITIONAL: Quiet reason (when agent is quiet but running)
    if quiet_reason and agent_running and not paused:
        # Map reason codes to user-friendly display
        reason_display = {
            "StrategySessionClosed": "📴 Session closed",
            "FuturesMarketClosed": "🌙 Market closed",
            "StaleData": "⏰ Data stale",
            "DataGap": "📉 Data gap detected",
            "NoData": "📭 Waiting for data",
            "NoOpportunity": "👀 Scanning (no setups)",
            "Level1Unavailable": "📡 Bars feed active (no bid/ask)",
            "Active": None,  # Don't show when active
            "Unknown": "❓ Status unknown",
        }.get(quiet_reason, f"ℹ️ {quiet_reason}")
        if reason_display:
            lines.append(f"{_SUBLINE_PREFIX}{reason_display}")
        # Actionable cue for StaleData
        if quiet_reason == "StaleData":
            lines.append(f"{_SUBLINE_PREFIX}💡 Menu → Health → Data")
        # Actionable cue for Level1Unavailable (feed classification)
        if quiet_reason == "Level1Unavailable":
            lines.append(f"{_SUBLINE_PREFIX}💡 See Menu → Health → Data for feed details")
    
    # CONDITIONAL: Signal diagnostics (when quiet reason is NoOpportunity and we have details)
    # V2 spec: Suppress when data is stale to avoid misleading derived context
    if signal_diagnostics and agent_running and not paused and not is_data_stale:
        # Only show if not a simple "no patterns" or "session closed" message
        if signal_diagnostics not in ("Session closed", "No patterns detected"):
            # Keep derived diagnostics Markdown-safe (these often contain underscores/ratios).
            diag_safe = escape_markdown(safe_label(str(signal_diagnostics)))
            lines.append(f"{_SUBLINE_PREFIX}🔍 {diag_safe}")

    # CONDITIONAL: Buy/Sell pressure (show only when agent running and not paused)
    # V2 spec: Suppress when data is stale to avoid misleading derived context
    if buy_sell_pressure and agent_running and not paused and not is_data_stale:
        lines.append(f"{_SUBLINE_PREFIX}{buy_sell_pressure}")

    lines.append("")  # Blank line separator

    # Activity line (v2 spec: includes signal_send_failures in the labeled format)
    vol_ratio = None
    delta_pct = None
    pressure_badge = None
    if (
        compact_metrics_enabled
        and show_volume_metrics
        and agent_running
        and not paused
        and not is_data_stale
        and isinstance(buy_sell_pressure_raw, dict)
    ):
        vol_ratio = buy_sell_pressure_raw.get("volume_ratio")
        delta_pct = buy_sell_pressure_raw.get("score_pct")
        pressure_badge = _format_pressure_badge(
            buy_sell_pressure_raw.get("bias"),
            buy_sell_pressure_raw.get("strength"),
        )
    lines.append(format_activity_line(
        cycles_session=cycles_session,
        cycles_total=cycles_total,
        signals_generated=signals_generated,
        signals_sent=signals_sent,
        errors=errors,
        buffer_size=buffer_size,
        buffer_target=buffer_target,
        signal_send_failures=signal_send_failures,
        volume_ratio=vol_ratio,
        delta_pct=delta_pct,
        pressure_badge=pressure_badge,
        compact_metrics_enabled=compact_metrics_enabled,
        show_progress_bars=show_progress_bars,
        show_volume_metrics=show_volume_metrics,
        compact_metric_width=int(compact_metric_width or 10),
    ))

    # CONDITIONAL: Active trades / open positions (only when > 0, calm-minimal)
    positions_count = active_trades_count if open_positions_count is None else int(open_positions_count or 0)
    if positions_count > 0:
        # Optionally append unrealized PnL (total) when provided.
        suffix = ""
        if active_trades_unrealized_pnl is not None:
            try:
                pnl_emoji, pnl_str = format_pnl(float(active_trades_unrealized_pnl))
                suffix = f"{_BULLET_SEP}{pnl_emoji} {pnl_str}"
                src = (active_trades_price_source or "").lower()
                if src in ("historical", "historical_fallback"):
                    suffix += " (delayed)"
            except Exception:
                suffix = ""

        noun = "active trade" if open_positions_count is None else "open position"
        lines.append(f"🎯 *{positions_count} {noun}{'s' if positions_count != 1 else ''}*{suffix}")

    # Last signal age (if available)
    if last_signal_age:
        lines.append(f"🔔 Last signal: {last_signal_age}")

    # Performance (if available and has trades)
    # Skip "7d Performance" section if challenge is active (7d all-time shown separately before challenge)
    is_challenge_mode = performance and performance.get("attempt_id") is not None
    if performance and not is_challenge_mode:
        exited = performance.get("exited_signals", 0)
        if exited > 0:
            wins = performance.get("wins", 0)
            losses = performance.get("losses", 0)
            win_rate = performance.get("win_rate", 0.0) * 100
            total_pnl = performance.get("total_pnl", 0.0)
            lines.append("")  # Blank line
            lines.append("*7d Performance:*")
            lines.append(
                format_performance_line(
                    wins,
                    losses,
                    win_rate,
                    total_pnl,
                    compact_metrics_enabled=compact_metrics_enabled,
                    show_progress_bars=show_progress_bars,
                    bar_width=int(compact_metric_width or 10),
                )
            )
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


def format_glanceable_card(
    symbol: str,
    time_str: str,
    agent_running: bool,
    gateway_running: bool | None,
    latest_price: float | None = None,
    daily_pnl: float | None = None,
    active_trades_count: int = 0,
    futures_market_open: bool | None = None,
    strategy_session_open: bool | None = None,
    market: str | None = None,
    trading_bot: str | None = None,
    ai_ready: bool = True,
    agent_uptime_seconds: float | None = None,
    data_age_seconds: float | None = None,
    agent_healthy: bool | None = None,
    data_stale: bool | None = None,
) -> str:
    """
    Build ultra-compact glanceable dashboard (5-7 lines max).
    
    DESIGN: Mobile-first, one-screen-no-scroll format.
    
    Layout:
    ```
    MNQ • 6:17 AM ET | 📈 Symbol: MNQ
    🤖 Trading Bot: pearl_bot_auto | 🧠 AI: Ready
    
    🔴 Agent: STOPPED • 🟢 Gateway: RUNNING
    🚫 Execution: OFF
    ⚪ Futures: ? • ⚪ Session: ?
    
    📊 0 scans • 0 gen / 0 sent • 0 bars • 0 errors
    
    💡 Start agent to begin
    ```
    
    Args:
        symbol: Trading symbol (e.g., "MNQ")
        time_str: Current time string (e.g., "6:17 AM ET")
        agent_running: Whether agent service is running
        gateway_running: Whether gateway is running
        latest_price: Latest price (optional)
        daily_pnl: Today's P&L (optional)
        active_trades_count: Number of active trades
        futures_market_open: Futures market gate status
        strategy_session_open: Strategy session gate status
        market: Market code (e.g., "NQ")
        trading_bot: Trading bot name (e.g., "pearl_bot_auto")
        ai_ready: Whether AI/model is ready
        
    Returns:
        Formatted glanceable card message string
    """
    lines = []
    bot_display = format_bot_name(trading_bot or "scanner")
    
    # PEARL branded header
    lines.append("🐚 *PEARL* - pearlalgo.io")
    lines.append(f"*{symbol}* • {time_str}")
    
    # Status line: Bot + Services
    if not agent_running:
        agent_dot = EMOJI_ERROR
    elif agent_healthy is False:
        agent_dot = EMOJI_WARN
    elif agent_healthy is None:
        agent_dot = EMOJI_WARN
    else:
        agent_dot = EMOJI_OK

    if gateway_running is True:
        gw_dot = EMOJI_OK
    elif gateway_running is False:
        gw_dot = EMOJI_ERROR
    else:
        gw_dot = EMOJI_UNKNOWN
    if data_stale is True:
        data_dot = EMOJI_ERROR
    elif data_stale is False:
        data_dot = EMOJI_OK
    else:
        data_dot = EMOJI_UNKNOWN

    lines.append(f"{EMOJI_BOTS} {bot_display} | Agent {agent_dot} | Gateway {gw_dot} | Data {data_dot}")
    
    # Gates line
    futures_dot = EMOJI_OK if futures_market_open else EMOJI_ERROR if futures_market_open is False else EMOJI_UNKNOWN
    session_dot = EMOJI_OK if strategy_session_open else EMOJI_ERROR if strategy_session_open is False else EMOJI_UNKNOWN
    lines.append(f"Futures {futures_dot} | Session {session_dot}")
    
    # Active trades with P&L (if any)
    if active_trades_count > 0:
        pnl_part = ""
        if daily_pnl is not None:
            pnl_emoji = EMOJI_PROFIT if daily_pnl >= 0 else EMOJI_LOSS
            pnl_sign = "+" if daily_pnl >= 0 else ""
            pnl_part = f" | {pnl_emoji}{pnl_sign}${abs(daily_pnl):.2f}"
        lines.append(f"{EMOJI_TARGET} *{active_trades_count} Active*{pnl_part}")
    
    # Footer: system state
    footer = format_transparency_footer(
        agent_uptime_seconds=agent_uptime_seconds,
        gateway_ok=gateway_running,
        data_age_seconds=data_age_seconds,
        agent_running=agent_running,
        data_stale=data_stale,
    )
    lines.append(f"`{footer}`")
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TelegramPrefs: Persistent UI preferences for Telegram bot
# ---------------------------------------------------------------------------

class TelegramPrefs:
    """
    Persistent UI preferences for Telegram bot.
    
    Stored as JSON in the state directory. All settings default to current
    calm-minimal behavior so existing users see no change until they opt-in.
    """
    
    # Default values
    #
    # Design policy (operator UX):
    # - Keep navigation buttons ON by default so operators can always jump back to Menu/Health.
    # - Keep pinned/edit-in-place dashboards OFF by default (optional; reduces chat spam).
    # - Pearl suggestions are ON by default (Pearl-style proactive help).
    DEFAULTS = {
        "dashboard_buttons": True,          # Show inline buttons on push dashboards + trade alerts
        "dashboard_edit_in_place": False,   # Keep a single dashboard message updated (optional)
        "dashboard_message_id": None,       # Internal: message_id used for edit-in-place dashboards
        "last_dashboard_sent_at": None,     # Internal: ISO timestamp of last dashboard delivery
        "signal_detail_expanded": False,    # Show expanded context in signal details
        "auto_chart_on_signal": False,      # Automatically generate chart with signal push
        "snooze_noncritical_alerts": False, # Temporarily suppress non-critical data alerts
        "snooze_until": None,               # ISO timestamp when snooze expires (if snoozed)
        "interval_notifications": True,     # Enable hourly interval notifications (chart + status)
        # Pearl preferences
        "pearl_suggestions_enabled": True,        # Master toggle for proactive suggestions
        "pearl_suggestion_cooldown_minutes": 30,  # Min time between similar suggestions
        "pearl_greeting_enabled": True,           # Morning/evening greetings
        "pearl_review_enabled": True,             # Periodic PEARL-style reviews
        "pearl_review_interval_minutes": 60,      # Min minutes between reviews (hourly)
        "pearl_review_last_sent_at": None,        # Internal: ISO timestamp of last review
    }
    
    # Human-readable labels for settings UI
    LABELS = {
        "dashboard_buttons": "Dashboard Buttons",
        "dashboard_edit_in_place": "Pinned Dashboard (Edit-in-Place)",
        "signal_detail_expanded": "Expanded Signal Details",
        "auto_chart_on_signal": "Auto-Chart on Signal",
        "snooze_noncritical_alerts": "Snooze Non-Critical Alerts",
        "interval_notifications": "Interval Notifications",
        "pearl_suggestions_enabled": "Pearl Suggestions",
        "pearl_greeting_enabled": "Pearl Greetings",
        "pearl_review_enabled": "PEARL Reviews",
    }
    
    # Descriptions for settings UI
    DESCRIPTIONS = {
        "dashboard_buttons": "Always show Menu navigation buttons on dashboards & alerts",
        "dashboard_edit_in_place": "Reduce chat spam by updating one dashboard message instead of sending new ones",
        "signal_detail_expanded": "Show full context (regime, MTF, VWAP) in signal details by default",
        "auto_chart_on_signal": "Automatically generate and send chart with each signal alert",
        "snooze_noncritical_alerts": "Temporarily suppress non-critical data quality alerts (1 hour)",
        "interval_notifications": "Hourly chart + status notifications (toggle off to disable)",
        "pearl_suggestions_enabled": "Pearl proactively offers help on dashboard (dismissible)",
        "pearl_greeting_enabled": "Pearl greets you in the morning with overnight summary",
        "pearl_review_enabled": "PEARL sends hourly check-ins with insights",
    }
    
    def __init__(self, state_dir=None):
        """
        Initialize preferences.
        
        Args:
            state_dir: Path to state directory (defaults to standard location)
        """
        from pathlib import Path
        
        if state_dir is None:
            try:
                from pearlalgo.utils.paths import ensure_state_dir
                state_dir = ensure_state_dir()
            except ImportError:
                state_dir = Path("data/agent_state/NQ")
        
        self._prefs_file = Path(state_dir) / "telegram_prefs.json"
        self._prefs = dict(self.DEFAULTS)
        self._load()
    
    def _load(self):
        """Load preferences from file."""
        import json
        
        if self._prefs_file.exists():
            try:
                with open(self._prefs_file, "r") as f:
                    stored = json.load(f)
                # Merge with defaults (handles new settings gracefully)
                for key in self.DEFAULTS:
                    if key in stored:
                        self._prefs[key] = stored[key]
            except Exception as e:
                logger.warning(f"Could not load Telegram prefs: {e}")

        # Operator policy: navigation buttons must always be available.
        # Enforce this even if older prefs files explicitly disabled them.
        try:
            if self._prefs.get("dashboard_buttons") is not True:
                self._prefs["dashboard_buttons"] = True
                self._save()
        except Exception:
            pass
    
    def _save(self):
        """Save preferences to file."""
        import json
        
        try:
            self._prefs_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._prefs_file, "w") as f:
                json.dump(self._prefs, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Could not save Telegram prefs: {e}")
    
    def get(self, key: str, default=None):
        """Get a preference value."""
        return self._prefs.get(key, default if default is not None else self.DEFAULTS.get(key))
    
    def set(self, key: str, value) -> bool:
        """Set a preference value and save."""
        if key not in self.DEFAULTS:
            return False
        self._prefs[key] = value
        self._save()
        return True
    
    def toggle(self, key: str) -> bool:
        """Toggle a boolean preference and return new value."""
        if key not in self.DEFAULTS:
            return False
        current = self._prefs.get(key, self.DEFAULTS.get(key))
        if isinstance(current, bool):
            self._prefs[key] = not current
            self._save()
            return self._prefs[key]
        return False
    
    def reset(self):
        """Reset all preferences to defaults."""
        self._prefs = dict(self.DEFAULTS)
        self._save()
    
    def all(self) -> dict:
        """Get all preferences as a dictionary."""
        return dict(self._prefs)
    
    # Convenience properties for common checks
    @property
    def dashboard_buttons(self) -> bool:
        return self._prefs.get("dashboard_buttons", True)

    @property
    def dashboard_edit_in_place(self) -> bool:
        return self._prefs.get("dashboard_edit_in_place", False)
    
    @property
    def signal_detail_expanded(self) -> bool:
        return self._prefs.get("signal_detail_expanded", False)
    
    @property
    def auto_chart_on_signal(self) -> bool:
        return self._prefs.get("auto_chart_on_signal", False)
    
    @property
    def snooze_noncritical_alerts(self) -> bool:
        """Check if non-critical alerts are snoozed (and snooze hasn't expired)."""
        if not self._prefs.get("snooze_noncritical_alerts", False):
            return False
        
        # Check if snooze has expired
        snooze_until = self._prefs.get("snooze_until")
        if snooze_until:
            try:
                from datetime import datetime, timezone
                expiry = datetime.fromisoformat(str(snooze_until).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expiry:
                    # Snooze expired - auto-disable
                    self._prefs["snooze_noncritical_alerts"] = False
                    self._prefs["snooze_until"] = None
                    self._save()
                    return False
            except Exception:
                pass
        return True
    
    def enable_snooze(self, hours: float = 1.0):
        """Enable snooze for non-critical alerts."""
        from datetime import datetime, timezone, timedelta
        
        expiry = datetime.now(timezone.utc) + timedelta(hours=hours)
        self._prefs["snooze_noncritical_alerts"] = True
        self._prefs["snooze_until"] = expiry.isoformat()
        self._save()
    
    def disable_snooze(self):
        """Disable snooze for non-critical alerts."""
        self._prefs["snooze_noncritical_alerts"] = False
        self._prefs["snooze_until"] = None
        self._save()
    
    # Pearl preferences
    @property
    def pearl_suggestions_enabled(self) -> bool:
        """Whether Pearl shows proactive suggestions on dashboard."""
        return self._prefs.get("pearl_suggestions_enabled", True)
    
    @property
    def pearl_suggestion_cooldown_minutes(self) -> int:
        """Minimum minutes between similar suggestions."""
        return self._prefs.get("pearl_suggestion_cooldown_minutes", 30)
    
    @property
    def pearl_greeting_enabled(self) -> bool:
        """Whether Pearl shows morning greetings."""
        return self._prefs.get("pearl_greeting_enabled", True)
    
    def get_pearl_prefs(self) -> dict:
        """Get all Pearl-related preferences as a dict."""
        return {
            "pearl_suggestions_enabled": self.pearl_suggestions_enabled,
            "pearl_suggestion_cooldown_minutes": self.pearl_suggestion_cooldown_minutes,
            "pearl_greeting_enabled": self.pearl_greeting_enabled,
        }


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

        # Prepare text variants (Markdown vs plain) and enforce Telegram size limit early.
        message_raw = message
        message_markdown = message_raw
        if parse_mode and str(parse_mode).lower() == "markdown":
            message_markdown = sanitize_telegram_markdown(message_markdown)

        original_len = len(message_markdown)
        message_markdown = _truncate_telegram_text(message_markdown)
        if len(message_markdown) != original_len:
            logger.warning(
                f"Telegram message truncated (len={original_len} -> {len(message_markdown)})"
            )

        # Enhanced deduplication: track last message hash and timestamp
        # Prevent sending same or very similar messages within 120 seconds (2 minutes)
        # Normalize message for better duplicate detection (remove variable timestamps/ages)
        import re
        normalized_message = message_markdown
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
                    text=message_markdown,
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
                    logger.debug(f"Markdown parsing error, retrying as plain text: {e}")
                    # Try sending as plain text on next attempt
                    if attempt < max_retries - 1:
                        try:
                            message_plain = _truncate_telegram_text(message_raw)
                            await self.bot.send_message(
                                chat_id=self.chat_id,
                                text=message_plain,
                                parse_mode=None,  # Plain text
                                reply_markup=reply_markup,
                            )
                            # Treat as sent for dedupe purposes
                            self._last_message_hash = message_hash
                            self._last_message_time = current_time
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
                                text=_truncate_telegram_text(
                                    message_raw.replace('*', '').replace('_', '').replace('`', '')
                                ),
                                parse_mode=None,
                                reply_markup=reply_markup,
                            )
                            # Treat as sent for dedupe purposes
                            self._last_message_hash = message_hash
                            self._last_message_time = current_time
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

        message = "🛑 *Stop Loss Hit*\n\n"
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

        message = "🎯 *Take Profit Hit*\n\n"
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
