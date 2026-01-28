"""
Sparkline and progress bar utilities for Telegram dashboard.

Mobile-friendly Unicode-based visualizations for progress bars.
"""

from __future__ import annotations


# Unicode block elements for sparklines (8 levels)
SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def generate_sparkline(values: list[float], width: int | None = None) -> str:
    """
    Generate a sparkline for a series of values.

    Args:
        values: Sequence of numeric values.
        width: Target sparkline width (resamples input when needed).

    Returns:
        Unicode sparkline string.
    """
    if width is None:
        width = len(values) if values else 20
    if width <= 0:
        return ""
    if not values:
        return "─" * width

    if len(values) != width:
        if width == 1:
            sampled = [values[0]]
        else:
            sampled = [
                values[int(i * (len(values) - 1) / (width - 1))] for i in range(width)
            ]
    else:
        sampled = values

    min_val = min(sampled)
    max_val = max(sampled)
    if min_val == max_val:
        mid = SPARK_CHARS[len(SPARK_CHARS) // 2]
        return mid * len(sampled)

    span = max_val - min_val
    chars = []
    for value in sampled:
        idx = int((value - min_val) / span * (len(SPARK_CHARS) - 1))
        idx = max(0, min(idx, len(SPARK_CHARS) - 1))
        chars.append(SPARK_CHARS[idx])
    return "".join(chars)


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
    """Format price change with direction arrow and percent."""
    if previous == 0:
        return "→ 0.00%"
    delta = current - previous
    pct = (delta / previous) * 100
    arrow = "→"
    sign = ""
    if pct > 0:
        arrow = "↑"
        sign = "+"
    elif pct < 0:
        arrow = "↓"
    return f"{arrow} {sign}{pct:.2f}%"


def trend_arrow(value: float, threshold: float = 0.1) -> str:
    """Return an arrow indicating trend direction."""
    if value >= threshold:
        return "↑"
    if value <= -threshold:
        return "↓"
    return "→"


def format_mtf_snapshot(trends: dict[str, float], timeframes: list[str] | None = None) -> str:
    """Format multi-timeframe trend snapshot."""
    if not trends:
        return "N/A"
    order = timeframes or sorted(trends.keys())
    parts = []
    for tf in order:
        if tf not in trends:
            continue
        parts.append(f"{tf}{trend_arrow(trends[tf])}")
    return " ".join(parts) if parts else "N/A"


def format_session_summary(
    cycles: int,
    signals_gen: int,
    signals_sent: int,
    errors: int,
    buffer_bars: int,
    buffer_target: int,
) -> str:
    """Format a compact session summary for dashboards."""
    bar = generate_progress_bar(buffer_bars, buffer_target, width=10)
    return (
        f"{cycles} cycles | {signals_gen} gen/{signals_sent} sent | {errors} err | "
        f"{buffer_bars}/{buffer_target} {bar}"
    )
