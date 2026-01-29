"""
Time parsing utility functions.

Provides canonical implementations for time string parsing.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple


def parse_hhmm(value: str) -> Optional[Tuple[int, int]]:
    """
    Parse a time string in HH:MM format into (hour, minute) tuple.
    
    Args:
        value: Time string in "HH:MM" format (e.g., "09:30", "16:00")
        
    Returns:
        Tuple of (hour, minute) if valid, None otherwise
        
    Example:
        >>> parse_hhmm("09:30")
        (9, 30)
        >>> parse_hhmm("invalid")
        None
    """
    try:
        parts = value.strip().split(":")
        if len(parts) != 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour, minute
    except Exception:
        return None


def parse_hhmm_with_default(
    value: Any, 
    *, 
    default: Tuple[int, int]
) -> Tuple[int, int]:
    """
    Parse a time string in HH:MM format with a fallback default.
    
    Args:
        value: Time string in "HH:MM" format, or any other value
        default: Default (hour, minute) tuple to return if parsing fails
        
    Returns:
        Tuple of (hour, minute), or default if parsing fails
        
    Example:
        >>> parse_hhmm_with_default("09:30", default=(8, 0))
        (9, 30)
        >>> parse_hhmm_with_default(None, default=(8, 0))
        (8, 0)
    """
    if isinstance(value, str):
        result = parse_hhmm(value)
        if result is not None:
            return result
    return default


def parse_hhmm_compact(hhmm: str) -> Tuple[int, int]:
    """
    Parse a time string in compact HHMM format (no colon).
    
    This is used by chart_generator for session time parsing.
    
    Args:
        hhmm: Time string in "HHMM" format (e.g., "0930", "1600")
        
    Returns:
        Tuple of (hour, minute)
        
    Raises:
        ValueError: If the string is not a valid 4-digit HHMM format
        
    Example:
        >>> parse_hhmm_compact("0930")
        (9, 30)
        >>> parse_hhmm_compact("1600")
        (16, 0)
    """
    s = str(hhmm or "").strip()
    if len(s) != 4 or not s.isdigit():
        raise ValueError(f"Invalid HHMM: {hhmm!r}")
    hour = int(s[:2])
    minute = int(s[2:])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time values in HHMM: {hhmm!r}")
    return hour, minute
