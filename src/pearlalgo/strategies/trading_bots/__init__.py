"""
Trading Bot Variants (AutoBot variants)

A collection of complete, self-contained trading bot variants.

Runtime executes **one selected AutoBot** (see `trading_bot` config). The additional
variants are intended for backtesting and future AutoBot options.
"""

from .bot_template import (
    TradingBot,
    BotConfig,
    TradeSignal,
    BotPerformance,
    IndicatorSuite,
    create_bot,
    register_bot,
)

from .trend_follower_bot import TrendFollowerBot
from .breakout_bot import BreakoutBot
from .mean_reversion_bot import MeanReversionBot
from .composite_bot import CompositeBot, PearlAutoBot
from .pearl_bot_auto import generate_signals, run_pearlbot, VirtualBroker, CONFIG

__all__ = [
    # Base classes
    "TradingBot",
    "BotConfig",
    "TradeSignal",
    "BotPerformance",
    "IndicatorSuite",
    # Factory functions
    "create_bot",
    "register_bot",
    # Bot implementations
    "TrendFollowerBot",
    "BreakoutBot",
    "MeanReversionBot",
    "CompositeBot",
    "PearlAutoBot",
    # PearlBot Auto (Pine Script-based)
    "generate_signals",
    "run_pearlbot",
    "VirtualBroker",
    "CONFIG",
]

