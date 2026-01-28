"""
Sparkline and progress bar utilities for Telegram dashboard.

Mobile-friendly Unicode-based visualizations for progress bars.
"""

from __future__ import annotations


# Unicode block elements for sparklines (8 levels)
SPARK_CHARS = " ▁▂▃▄▅▆▇█"


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
