"""
Safe value formatting utilities for logging and display.

These functions never raise exceptions - they return default values
when given invalid inputs. Useful for logging where you want to
display values without worrying about edge cases.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo


def fmt_price(value: Any, default: str = "N/A") -> str:
    """
    Safely format a price value for logging/display.
    
    Never raises - returns default string if value is invalid.
    
    Args:
        value: Price value (may be None, NaN, or invalid)
        default: String to return if value is invalid
        
    Returns:
        Formatted price string (e.g., "$17500.25") or default
        
    Example:
        >>> fmt_price(17500.25)
        "$17500.25"
        >>> fmt_price(None)
        "N/A"
        >>> fmt_price(float('nan'))
        "N/A"
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return default
        return f"${float_val:.2f}"
    except (ValueError, TypeError):
        return default


def fmt_int(value: Any, default: str = "N/A") -> str:
    """
    Safely format an integer value for logging/display.
    
    Never raises - returns default string if value is invalid.
    
    Args:
        value: Integer value (may be None, NaN, or invalid)
        default: String to return if value is invalid
        
    Returns:
        Formatted integer string or default
        
    Example:
        >>> fmt_int(42)
        "42"
        >>> fmt_int(42.7)
        "42"
        >>> fmt_int(None)
        "N/A"
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return default
        return str(int(float_val))
    except (ValueError, TypeError):
        return default


def fmt_percent(value: Any, decimals: int = 1, default: str = "N/A") -> str:
    """
    Safely format a percentage value for logging/display.
    
    Never raises - returns default string if value is invalid.
    
    Args:
        value: Percentage value as decimal (0.5 = 50%)
        decimals: Number of decimal places
        default: String to return if value is invalid
        
    Returns:
        Formatted percentage string (e.g., "50.0%") or default
        
    Example:
        >>> fmt_percent(0.5)
        "50.0%"
        >>> fmt_percent(0.1234, decimals=2)
        "12.34%"
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return default
        return f"{float_val * 100:.{decimals}f}%"
    except (ValueError, TypeError):
        return default


def fmt_number(value: Any, decimals: int = 2, default: str = "N/A") -> str:
    """
    Safely format a numeric value for logging/display.

    Never raises - returns default string if value is invalid.

    Args:
        value: Numeric value (may be None, NaN, or invalid)
        decimals: Number of decimal places
        default: String to return if value is invalid

    Returns:
        Formatted number string or default

    Example:
        >>> fmt_number(123.456)
        "123.46"
        >>> fmt_number(123.456, decimals=1)
        "123.5"
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return default
        return f"{float_val:.{decimals}f}"
    except (ValueError, TypeError):
        return default


# =============================================================================
# Enhanced formatting functions (with commas, signs, etc.)
# =============================================================================


def fmt_number_commas(
    value: Any,
    decimals: int = 2,
    show_sign: bool = False,
    default: str = "N/A",
) -> str:
    """
    Format number with commas and optional sign prefix.

    Args:
        value: Numeric value (may be None, NaN, or invalid)
        decimals: Number of decimal places
        show_sign: If True, prefix positive numbers with "+"
        default: String to return if value is invalid

    Returns:
        Formatted number string with commas (e.g., "1,234.56") or default

    Example:
        >>> fmt_number_commas(1234.5)
        "1,234.50"
        >>> fmt_number_commas(100, show_sign=True)
        "+100.00"
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return default
        sign = "+" if show_sign and float_val >= 0 else ""
        return f"{sign}{float_val:,.{decimals}f}"
    except (ValueError, TypeError):
        return default


def fmt_currency(
    value: Any,
    show_sign: bool = False,
    default: str = "$0.00",
) -> str:
    """
    Format currency value with dollar sign and commas.

    Args:
        value: Currency value (may be None, NaN, or invalid)
        show_sign: If True, prefix positive values with "+"
        default: String to return if value is invalid

    Returns:
        Formatted currency string (e.g., "$1,234.56") or default

    Example:
        >>> fmt_currency(1234.56)
        "$1,234.56"
        >>> fmt_currency(-50.25)
        "-$50.25"
        >>> fmt_currency(100, show_sign=True)
        "+$100.00"
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return default
        sign = "+" if show_sign and float_val >= 0 else ""
        return f"{sign}${float_val:,.2f}"
    except (ValueError, TypeError):
        return default


def fmt_pct_direct(
    value: Any,
    decimals: int = 1,
    default: str = "0%",
) -> str:
    """
    Format a percentage value (value is already in percent form).

    Unlike fmt_percent which multiplies by 100, this takes the value as-is.

    Args:
        value: Percentage value already in percent form (50.0 = 50%)
        decimals: Number of decimal places
        default: String to return if value is invalid

    Returns:
        Formatted percentage string (e.g., "50.0%") or default

    Example:
        >>> fmt_pct_direct(50.5)
        "50.5%"
        >>> fmt_pct_direct(None)
        "0%"
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return default
        return f"{float_val:.{decimals}f}%"
    except (ValueError, TypeError):
        return default


# =============================================================================
# PnL formatting
# =============================================================================


def pnl_emoji(value: float) -> str:
    """Return a colored emoji for a PnL value.

    Args:
        value: Profit/loss amount.

    Returns:
        '🟢' for non-negative, '🔴' for negative.
    """
    return "🟢" if value >= 0 else "🔴"


def format_pnl(pnl: float) -> tuple[str, str]:
    """Return (emoji, formatted_string) for a P&L value.

    Args:
        pnl: Profit/loss amount.

    Returns:
        Tuple of (emoji, formatted_string), e.g. ('🟢', '+$125.50')
    """
    if pnl >= 0:
        return "🟢", f"+${pnl:,.2f}"
    else:
        return "🔴", f"-${abs(pnl):,.2f}"


# =============================================================================
# Time formatting
# =============================================================================


def format_duration(seconds: float | None, suffix: str = "", compact: bool = False) -> str:
    """Format a duration in seconds to a human-readable form.

    Args:
        seconds: Duration in seconds (or None).
        suffix: Optional suffix to append (e.g., " ago").
        compact: If True, use compact format like "3h15m"; if False, use "3h 15m".

    Returns:
        e.g. '45s', '12m', '3h15m' (compact) or '3h 15m' (spaced), or '?' if None.
    """
    if seconds is None:
        return "?" + suffix
    try:
        s = float(seconds)
    except (ValueError, TypeError):
        return "?" + suffix
    if s < 0:
        return "?" + suffix
    if s < 60:
        return f"{int(s)}s{suffix}"
    if s < 3600:
        return f"{int(s // 60)}m{suffix}"
    if s < 86400:
        hours = int(s // 3600)
        mins = int((s % 3600) // 60)
        sep = "" if compact else " "
        if mins > 0:
            return f"{hours}h{sep}{mins}m{suffix}"
        return f"{hours}h{suffix}"
    days = int(s // 86400)
    hours = int((s % 86400) // 3600)
    sep = "" if compact else " "
    if hours > 0:
        return f"{days}d{sep}{hours}h{suffix}"
    return f"{days}d{suffix}"


def format_duration_short(seconds: float | None) -> str:
    """Format a duration in seconds to a compact human-readable form.

    Args:
        seconds: Duration in seconds (or None).

    Returns:
        e.g. '45s', '12m', '3h15m', or '?' if None.
    """
    return format_duration(seconds, compact=True)


def format_hold_duration(minutes: float) -> str:
    """Format a hold-duration in minutes to human-readable form.

    Args:
        minutes: Hold time in minutes.

    Returns:
        e.g. '45m' or '2h 15m'.
    """
    return format_duration(minutes * 60, compact=False)


def format_time_ago(timestamp_str: str | None) -> str:
    """Format a timestamp as a human-readable 'time ago' string.

    Returns e.g. '5m ago', '2h ago', '1d ago', or '' if parsing fails.
    """
    if not timestamp_str:
        return ""
    try:
        from datetime import timezone as _tz
        from pearlalgo.utils.paths import parse_utc_timestamp

        ts = parse_utc_timestamp(str(timestamp_str))
        if ts is None:
            return ""
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_tz.utc)
        now = datetime.now(_tz.utc)
        delta = now - ts
        seconds = delta.total_seconds()
        if seconds < 0:
            return ""
        return format_duration(seconds, suffix=" ago", compact=True)
    except Exception:
        return ""


def format_uptime(uptime: dict) -> str:
    """Format an uptime dict (with 'hours' and 'minutes' keys) compactly.

    Args:
        uptime: Dict with 'hours' and/or 'minutes' keys.

    Returns:
        e.g. '3h15m' or '45m'.
    """
    hours = uptime.get("hours", 0)
    minutes = uptime.get("minutes", 0)
    total_seconds = hours * 3600 + minutes * 60
    return format_duration(total_seconds, compact=True)


def fmt_time_et(dt: Optional[datetime], fallback: str = "N/A") -> str:
    """Format a datetime as Eastern Time (e.g., '10:35 AM ET').

    Falls back to UTC format if timezone conversion fails,
    then to *fallback* if all formatting fails.

    Args:
        dt: A datetime object (may be None or timezone-naive/aware)
        fallback: String to return if *dt* is None or formatting fails

    Returns:
        Formatted time string (e.g., "10:35 AM ET") or fallback

    Example:
        >>> from datetime import datetime, timezone
        >>> fmt_time_et(datetime(2024, 1, 15, 15, 35, tzinfo=timezone.utc))
        '10:35 AM ET'
        >>> fmt_time_et(None)
        'N/A'
    """
    if dt is None:
        return fallback
    try:
        et_tz = ZoneInfo("US/Eastern")
        et_time = dt.astimezone(et_tz)
        return et_time.strftime("%I:%M %p ET")
    except Exception:
        try:
            if hasattr(dt, "strftime"):
                return dt.strftime("%H:%M UTC")
        except Exception:
            pass
    return fallback
