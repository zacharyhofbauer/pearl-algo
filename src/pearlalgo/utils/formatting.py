"""
Safe value formatting utilities for logging and display.

These functions never raise exceptions - they return default values
when given invalid inputs. Useful for logging where you want to
display values without worrying about edge cases.
"""

from __future__ import annotations

import math
from typing import Any


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
