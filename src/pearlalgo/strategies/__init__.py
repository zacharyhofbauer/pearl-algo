"""
Strategy implementations for the PearlAlgo trading agent.

Contains:
- nq_intraday: MNQ futures intraday strategy optimized for prop firm trading
- lux_algo_bots: Lux Algo Chart Prime style automated trading bots
"""

# Import the main strategy for convenience
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig

# Import Lux Algo bots
from .lux_algo_bots import (
    LuxAlgoBot,
    BotConfig,
    create_bot,
    TrendFollowerBot,
    BreakoutBot,
    MeanReversionBot,
)

# Import integration layer
from .lux_algo_integration import get_lux_algo_manager

__all__ = [
    # Existing strategies
    "NQIntradayStrategy",
    "NQIntradayConfig",

    # Lux Algo bots
    "LuxAlgoBot",
    "BotConfig",
    "create_bot",
    "TrendFollowerBot",
    "BreakoutBot",
    "MeanReversionBot",

    # Integration
    "get_lux_algo_manager",
]
