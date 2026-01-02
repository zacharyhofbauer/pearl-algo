"""
Sparkline and progress bar utilities for Telegram dashboard.

Mobile-friendly Unicode-based visualizations for price charts and session progress.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple


# Unicode block elements for sparklines (8 levels)
SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def generate_sparkline(values: Sequence[float], width: int = 20) -> str:
    """
    Generate a Unicode sparkline from a sequence of values.
    
    Args:
        values: Sequence of numeric values (e.g., close prices)
        width: Target width of sparkline (will resample if needed)
        
    Returns:
        Unicode sparkline string
    """
    if not values or len(values) == 0:
        return "─" * width
    
    # Convert to list of floats
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return "─" * width
    
    # Resample if needed
    if len(vals) > width:
        # Take evenly spaced samples
        step = len(vals) / width
        vals = [vals[int(i * step)] for i in range(width)]
    elif len(vals) < width:
        # Pad with last value or keep as is
        pass  # Keep shorter sparkline
    
    # Normalize to 0-8 range
    min_val = min(vals)
    max_val = max(vals)
    val_range = max_val - min_val
    
    if val_range == 0:
        # Flat line
        return SPARK_CHARS[4] * len(vals)
    
    spark = ""
    for v in vals:
        # Normalize to 0-8
        normalized = int((v - min_val) / val_range * 8)
        normalized = max(0, min(8, normalized))
        spark += SPARK_CHARS[normalized]
    
    return spark


def generate_progress_bar(
    current: int,
    total: int,
    width: int = 10,
    filled_char: str = "█",
    empty_char: str = "░",
) -> str:
    """
    Generate a Unicode progress bar.
    
    Args:
        current: Current value
        total: Total/target value
        width: Width of progress bar
        filled_char: Character for filled portion
        empty_char: Character for empty portion
        
    Returns:
        Unicode progress bar string
    """
    if total <= 0:
        return empty_char * width
    
    ratio = min(1.0, max(0.0, current / total))
    filled = int(ratio * width)
    empty = width - filled
    
    return filled_char * filled + empty_char * empty


def format_price_change(current: float, previous: float) -> str:
    """
    Format price change with arrow and percentage.
    
    Args:
        current: Current price
        previous: Previous price (for comparison)
        
    Returns:
        Formatted string like "↑ +1.23%" or "↓ -0.45%"
    """
    if previous == 0:
        return "→ 0.00%"
    
    change_pct = ((current - previous) / previous) * 100
    
    if change_pct > 0.05:
        return f"↑ +{change_pct:.2f}%"
    elif change_pct < -0.05:
        return f"↓ {change_pct:.2f}%"
    else:
        return f"→ {change_pct:.2f}%"


def trend_arrow(slope: float, threshold: float = 0.1) -> str:
    """
    Convert a slope/trend value to a compact arrow.
    
    Args:
        slope: Trend slope (positive = up, negative = down)
        threshold: Minimum absolute slope for non-neutral
        
    Returns:
        Arrow emoji: ↑ (bullish), ↓ (bearish), → (neutral)
    """
    if slope > threshold:
        return "↑"
    elif slope < -threshold:
        return "↓"
    else:
        return "→"


def format_mtf_snapshot(
    trends: dict,
    timeframes: Optional[List[str]] = None,
) -> str:
    """
    Format multi-timeframe trend snapshot as compact arrows.
    
    Args:
        trends: Dict mapping timeframe -> slope/trend value
                e.g., {"5m": 0.5, "15m": 0.3, "1h": -0.1}
        timeframes: Order of timeframes to display (default: sorted keys)
        
    Returns:
        Formatted string like "5m↑ 15m↑ 1h→ 4h↓"
    """
    if not trends:
        return "N/A"
    
    tfs = timeframes or sorted(trends.keys(), key=lambda x: _tf_to_minutes(x))
    
    parts = []
    for tf in tfs:
        if tf in trends:
            slope = trends[tf]
            arrow = trend_arrow(slope)
            parts.append(f"{tf}{arrow}")
    
    return " ".join(parts) if parts else "N/A"


def _tf_to_minutes(tf: str) -> int:
    """Convert timeframe string to minutes for sorting."""
    tf = tf.lower().strip()
    if tf.endswith("m"):
        return int(tf[:-1])
    elif tf.endswith("h"):
        return int(tf[:-1]) * 60
    elif tf.endswith("d"):
        return int(tf[:-1]) * 1440
    else:
        return 0


def format_session_summary(
    cycles: int,
    signals_gen: int,
    signals_sent: int,
    errors: int,
    buffer_bars: int,
    buffer_target: int,
) -> str:
    """
    Format session activity summary in compact form.
    
    Args:
        cycles: Number of cycles this session
        signals_gen: Signals generated this session
        signals_sent: Signals sent this session
        errors: Error count
        buffer_bars: Current buffer size
        buffer_target: Target buffer size
        
    Returns:
        Compact summary string
    """
    # Buffer progress bar
    buf_bar = generate_progress_bar(buffer_bars, buffer_target, width=5)
    
    return (
        f"📊 {cycles:,} cycles • {signals_gen} gen/{signals_sent} sent • "
        f"{buf_bar} {buffer_bars}/{buffer_target} bars • {errors} err"
    )















