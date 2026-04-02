"""
Legacy trading bot compatibility namespace.

The canonical live strategy entrypoint lives under ``pearlalgo.strategies``.
This package remains as an implementation bridge for older imports and wrapper
modules that have not been fully retired yet.

Do not add new strategy entrypoints or product logic here.
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
