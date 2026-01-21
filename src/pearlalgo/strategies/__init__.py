"""
Strategy implementations for the PearlAlgo trading agent.

Contains:
- nq_intraday: MNQ futures intraday strategy optimized for prop firm trading
- trading bots: AutoBot variants (backtesting/analysis)
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

]
