"""
Strategy implementations for the PearlAlgo trading agent.

Contains:
- nq_intraday: MNQ futures intraday strategy optimized for prop firm trading
- pearl_bots: PEARL automated trading bots (formerly lux_algo_bots)
"""

# Import the main strategy for convenience
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig

# Import PEARL automated bots
from .pearl_bots import (
    PearlBot,
    BotConfig,
    create_bot,
    TrendFollowerBot,
    BreakoutBot,
    MeanReversionBot,
)

# Import integration layer
from .pearl_bots_integration import get_pearl_bot_manager

__all__ = [
    # Existing strategies
    "NQIntradayStrategy",
    "NQIntradayConfig",

    # PEARL automated bots
    "PearlBot",
    "BotConfig",
    "create_bot",
    "TrendFollowerBot",
    "BreakoutBot",
    "MeanReversionBot",

    # Integration
    "get_pearl_bot_manager",
]
