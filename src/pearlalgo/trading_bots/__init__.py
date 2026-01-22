"""
Trading Bot - PearlBot Auto

Single-file, self-contained trading strategy derived from Pine Script indicators.
Virtual broker mode: Only generates signals, no real execution.
Perfect for testing live without using real money.
"""

from .pearl_bot_auto import generate_signals, run_pearlbot, VirtualBroker, CONFIG

# Alias for backward compatibility
PEARL_BOT_CONFIG = CONFIG

__all__ = [
    # Main strategy functions
    "generate_signals",
    "run_pearlbot",
    "VirtualBroker",
    # Configuration
    "CONFIG",
    "PEARL_BOT_CONFIG",
]
