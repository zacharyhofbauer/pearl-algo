"""
Legacy trading bot compatibility namespace.

The canonical live strategy entrypoint lives under ``pearlalgo.strategies``.
This package remains as an implementation bridge for older imports.
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
