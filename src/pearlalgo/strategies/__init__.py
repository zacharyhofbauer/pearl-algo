"""
Strategy implementations for the PearlAlgo trading agent.

Contains:
- nq_intraday: MNQ futures intraday strategy optimized for prop firm trading
- trading bots: AutoBot variants (single-bot runtime; variants for backtests)
"""

# Import the main strategy for convenience
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig

# Import PEARL automated bots
from .trading_bots import (
    TradingBot,
    BotConfig,
    create_bot,
    TrendFollowerBot,
    BreakoutBot,
    MeanReversionBot,
    PearlAutoBot,
)

# Import integration layer
from .trading_bot_manager import get_trading_bot_manager

__all__ = [
    # Existing strategies
    "NQIntradayStrategy",
    "NQIntradayConfig",

    # Trading bots
    "TradingBot",
    "BotConfig",
    "create_bot",
    "TrendFollowerBot",
    "BreakoutBot",
    "MeanReversionBot",
    "PearlAutoBot",

    # Integration
    "get_trading_bot_manager",
]
