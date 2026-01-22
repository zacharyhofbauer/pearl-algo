"""
Strategy implementations for the PearlAlgo trading agent.

Contains:
- trading_bots/pearl_bot_auto: Single-file strategy from Pine Scripts (main production bot)
"""

# Import PearlBot Auto (main strategy)
from .trading_bots.pearl_bot_auto import generate_signals, CONFIG as PEARL_BOT_CONFIG

__all__ = [
    # PearlBot Auto (main strategy)
    "generate_signals",
    "PEARL_BOT_CONFIG",
]
