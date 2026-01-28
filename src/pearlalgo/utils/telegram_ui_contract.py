"""
Telegram UI Contract - Canonical callback_data definitions for the Telegram bot interface.

This module defines the callback contract between:
- `telegram_notifier.py` (push alerts with inline buttons)
- `telegram_command_handler.py` (interactive command/button handling)

CALLBACK DATA FORMAT:
- Menu navigation: `menu:<menu_name>`
- Actions: `action:<action_type>` or `action:<action_type>:<param>`
- Back navigation: `back`
- Confirmations: `confirm:<action>`
- Signal details: `signal_detail:<signal_id_prefix>`

LEGACY SUPPORT:
Raw callbacks (e.g., `start`, `signals`, `data_quality`) emitted by older notifier
versions are aliased to canonical routes for backward compatibility.

USAGE:
- Notifier should emit canonical callback_data using constants from this module.
- Command handler should use `resolve_callback()` to normalize legacy callbacks.
"""

from __future__ import annotations

from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Canonical callback_data prefixes
# ---------------------------------------------------------------------------
PREFIX_MENU = "menu:"
PREFIX_ACTION = "action:"
PREFIX_CONFIRM = "confirm:"
PREFIX_SIGNAL_DETAIL = "signal_detail:"
PREFIX_PATCH = "patch:"
PREFIX_AIOPS = "aiops:"
PREFIX_PEARL = "pearl:"  # Pearl JARVIS suggestions and actions

# ---------------------------------------------------------------------------
# Menu IDs (used with menu: prefix)
# ---------------------------------------------------------------------------
MENU_MAIN = "main"  # Main menu / home
MENU_ACTIVITY = "activity"  # Trades (virtual) + history + P&L
MENU_ANALYTICS = "analytics"
MENU_PERFORMANCE = "performance"
MENU_STATUS = "status"
MENU_SYSTEM = "system"
MENU_SETTINGS = "settings"
MENU_HELP = "help"
MENU_MARKETS = "markets"
MENU_BOTS = "bots"

# ---------------------------------------------------------------------------
# Action IDs (used with action: prefix)
# ---------------------------------------------------------------------------
# Status & Health
ACTION_SYSTEM_STATUS = "system_status"
ACTION_GATEWAY_STATUS = "gateway_status"
ACTION_CONNECTION_STATUS = "connection_status"
ACTION_DATA_QUALITY = "data_quality"

# Trades (virtual) + history
ACTION_TRADES_OVERVIEW = "trades_overview"
ACTION_SIGNAL_HISTORY = "signal_history"
ACTION_SIGNAL_DETAILS = "signal_details"
ACTION_CLOSE_ALL_TRADES = "close_all_trades"

# Performance
ACTION_PERFORMANCE_METRICS = "performance_metrics"
ACTION_PNL_OVERVIEW = "pnl_overview"
ACTION_DAILY_SUMMARY = "daily_summary"
ACTION_WEEKLY_SUMMARY = "weekly_summary"
ACTION_RESET_PERFORMANCE = "reset_performance"
ACTION_EXPORT_PERFORMANCE = "export_performance"

# System Control
ACTION_START_AGENT = "start_agent"
ACTION_STOP_AGENT = "stop_agent"
ACTION_RESTART_AGENT = "restart_agent"
ACTION_RESTART_GATEWAY = "restart_gateway"
ACTION_EMERGENCY_STOP = "emergency_stop"
ACTION_RESET_CHALLENGE = "reset_challenge"
ACTION_CLEAR_CACHE = "clear_cache"
ACTION_CONFIG = "config"
ACTION_LOGS = "logs"

# UI Actions
ACTION_REFRESH_DASHBOARD = "refresh_dashboard"
ACTION_TOGGLE_CHART = "toggle_chart"

# ---------------------------------------------------------------------------
# Pearl JARVIS Actions (used with pearl: prefix)
# ---------------------------------------------------------------------------
# Pearl suggestion responses
PEARL_DISMISS = "dismiss"                    # User dismissed suggestion
PEARL_RECONNECT_GATEWAY = "reconnect_gateway"  # Reconnect gateway
PEARL_CHECK_DATA = "check_data"              # Check data connection
PEARL_START_AGENT = "start_agent"            # Start agent
PEARL_SHOW_OVERNIGHT = "show_overnight"      # Show overnight summary
PEARL_SHOW_PERFORMANCE = "show_performance"  # Show performance breakdown
PEARL_SHOW_DAILY_SUMMARY = "show_daily_summary"  # Show daily summary

# ---------------------------------------------------------------------------
# Connection status helpers
# ---------------------------------------------------------------------------


def connection_status_to_label(raw_conn) -> tuple[str, str]:
    """
    Map raw connection_status value to (label, emoji).
    
    Args:
        raw_conn: Raw connection status from state (True, False, None, or string).
        
    Returns:
        Tuple of (label, emoji) e.g., ("CONNECTED", "🟢")
        
    Examples:
        >>> connection_status_to_label(True)
        ('CONNECTED', '🟢')
        >>> connection_status_to_label("disconnected")
        ('DISCONNECTED', '🔴')
        >>> connection_status_to_label(None)
        ('UNKNOWN', '⚪')
    """
    if raw_conn in (True, "connected", "CONNECTED", "ok", "OK"):
        return ("CONNECTED", "🟢")
    elif raw_conn in (False, "disconnected", "DISCONNECTED", "down", "DOWN"):
        return ("DISCONNECTED", "🔴")
    elif raw_conn is None:
        return ("UNKNOWN", "⚪")
    else:
        # Unknown string value - show as-is
        return (str(raw_conn).upper(), "⚪")


# ---------------------------------------------------------------------------
# Legacy callback aliases (raw callbacks -> canonical routes)
# ---------------------------------------------------------------------------
# These map old/raw callback_data values to canonical routes.
# Used for backward compatibility with messages already sent by the notifier.
LEGACY_CALLBACK_ALIASES: dict[str, str] = {
    # Navigation shortcuts (legacy raw callbacks)
    "start": "menu:main",
    # Signals/Virtual were unified into Activity/Trades. Keep legacy callbacks working.
    "signals": "menu:activity",
    "status": "menu:status",
    "activity": "menu:activity",
    "menu": "menu:main",
    
    # Action shortcuts (legacy raw callbacks without prefix)
    "data_quality": "action:data_quality",
    "gateway_status": "action:gateway_status",
    "connection_status": "action:connection_status",
    "system_status": "action:system_status",
    "active_trades": "action:trades_overview",
    "recent_signals": "action:trades_overview",
    
    # Restart actions (legacy without confirm: prefix)
    "restart_agent": "confirm:restart_agent",
    "restart_gateway": "confirm:restart_gateway",
}


def resolve_callback(callback_data: str) -> str:
    """
    Resolve a callback_data string to its canonical form.
    
    Args:
        callback_data: Raw callback_data from button press
        
    Returns:
        Canonical callback_data (may be the same if already canonical)
        
    Examples:
        >>> resolve_callback("start")
        'menu:main'
        >>> resolve_callback("data_quality")
        'action:data_quality'
        >>> resolve_callback("signals")  # legacy alias
        'menu:activity'
        >>> resolve_callback("signal_detail_abc123")
        'signal_detail:abc123'
    """
    if not callback_data:
        return callback_data
    
    # Check for legacy alias
    if callback_data in LEGACY_CALLBACK_ALIASES:
        return LEGACY_CALLBACK_ALIASES[callback_data]

    # Canonical backwards compatibility: unify old menu/actions into the new routes.
    # Old messages cannot be edited, so we normalize at callback resolution time.
    if callback_data == "menu:signals":
        return "menu:activity"
    if callback_data in {"action:active_trades", "action:recent_signals"}:
        return "action:trades_overview"
    
    # Handle signal_detail_<id> format (legacy uses underscore, canonical uses colon)
    if callback_data.startswith("signal_detail_"):
        signal_id = callback_data[14:]  # Remove "signal_detail_" prefix
        return f"{PREFIX_SIGNAL_DETAIL}{signal_id}"
    
    # Already canonical or unrecognized - return as-is
    return callback_data


def parse_callback(callback_data: str) -> Tuple[str, str, Optional[str]]:
    """
    Parse a canonical callback_data into (type, action, param).
    
    Args:
        callback_data: Canonical callback_data string
        
    Returns:
        Tuple of (callback_type, action, optional_param)
        - callback_type: One of "menu", "action", "confirm", "signal_detail", "back", "other"
        - action: The action/menu name
        - param: Optional parameter (e.g., signal ID, preference key)
        
    Examples:
        >>> parse_callback("menu:activity")
        ('menu', 'activity', None)
        >>> parse_callback("action:toggle_pref:auto_chart_on_signal")
        ('action', 'toggle_pref', 'auto_chart_on_signal')
        >>> parse_callback("signal_detail:abc123")
        ('signal_detail', 'abc123', None)
        >>> parse_callback("back")
        ('back', '', None)
    """
    if not callback_data:
        return ("other", "", None)
    
    if callback_data == "back":
        return ("back", "", None)
    
    if callback_data.startswith(PREFIX_MENU):
        action = callback_data[len(PREFIX_MENU):]
        return ("menu", action, None)
    
    if callback_data.startswith(PREFIX_ACTION):
        rest = callback_data[len(PREFIX_ACTION):]
        # Check for nested param (e.g., toggle_pref:key or set_market:NQ)
        if ":" in rest:
            action, param = rest.split(":", 1)
            return ("action", action, param)
        return ("action", rest, None)
    
    if callback_data.startswith(PREFIX_CONFIRM):
        action = callback_data[len(PREFIX_CONFIRM):]
        return ("confirm", action, None)
    
    if callback_data.startswith(PREFIX_SIGNAL_DETAIL):
        signal_id = callback_data[len(PREFIX_SIGNAL_DETAIL):]
        return ("signal_detail", signal_id, None)
    
    if callback_data.startswith(PREFIX_PATCH):
        rest = callback_data[len(PREFIX_PATCH):]
        return ("patch", rest, None)
    
    if callback_data.startswith(PREFIX_AIOPS):
        rest = callback_data[len(PREFIX_AIOPS):]
        return ("aiops", rest, None)
    
    if callback_data.startswith(PREFIX_PEARL):
        rest = callback_data[len(PREFIX_PEARL):]
        return ("pearl", rest, None)
    
    # Unrecognized format
    return ("other", callback_data, None)


def build_callback(callback_type: str, action: str, param: Optional[str] = None) -> str:
    """
    Build a canonical callback_data string.
    
    Args:
        callback_type: One of "menu", "action", "confirm", "signal_detail", "back"
        action: The action/menu name
        param: Optional parameter
        
    Returns:
        Canonical callback_data string
        
    Examples:
        >>> build_callback("menu", "activity")
        'menu:activity'
        >>> build_callback("action", "toggle_pref", "auto_chart_on_signal")
        'action:toggle_pref:auto_chart_on_signal'
        >>> build_callback("signal_detail", "abc123")
        'signal_detail:abc123'
    """
    if callback_type == "back":
        return "back"
    
    if callback_type == "menu":
        return f"{PREFIX_MENU}{action}"
    
    if callback_type == "action":
        if param:
            return f"{PREFIX_ACTION}{action}:{param}"
        return f"{PREFIX_ACTION}{action}"
    
    if callback_type == "confirm":
        return f"{PREFIX_CONFIRM}{action}"
    
    if callback_type == "signal_detail":
        return f"{PREFIX_SIGNAL_DETAIL}{action}"
    
    # Default: return as-is
    return action


# ---------------------------------------------------------------------------
# Canonical callback builders (for notifier use)
# ---------------------------------------------------------------------------
def callback_menu(menu_id: str) -> str:
    """Build a menu navigation callback."""
    return build_callback("menu", menu_id)


def callback_action(action_id: str, param: Optional[str] = None) -> str:
    """Build an action callback."""
    return build_callback("action", action_id, param)


def callback_signal_detail(signal_id_prefix: str) -> str:
    """Build a signal detail callback."""
    return build_callback("signal_detail", signal_id_prefix)


def callback_confirm(action_id: str) -> str:
    """Build a confirmation callback."""
    return build_callback("confirm", action_id)


def callback_back() -> str:
    """Build a back navigation callback."""
    return "back"


def callback_pearl(action: str) -> str:
    """Build a Pearl JARVIS action callback."""
    return f"{PREFIX_PEARL}{action}"


def callback_pearl_dismiss() -> str:
    """Build the Pearl dismiss callback."""
    return f"{PREFIX_PEARL}{PEARL_DISMISS}"
