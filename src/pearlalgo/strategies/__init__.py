"""
Strategy implementations for the PearlAlgo trading agent.

Contains:
- pearl_bot_auto: Single-file strategy from Pine Scripts (main production bot)
- trading bots: AutoBot variants (backtesting/analysis)
"""

# Import PearlBot Auto (replaces nq_intraday)
from pearlalgo.strategies.trading_bots.pearl_bot_auto import generate_signals, CONFIG as PEARL_BOT_CONFIG

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
    # PearlBot Auto (replaces nq_intraday)
    "generate_signals",
    "PEARL_BOT_CONFIG",

    # Trading bots
    "TradingBot",
    "BotConfig",
    "create_bot",
    "TrendFollowerBot",
    "BreakoutBot",
    "MeanReversionBot",
    "PearlAutoBot",

]
