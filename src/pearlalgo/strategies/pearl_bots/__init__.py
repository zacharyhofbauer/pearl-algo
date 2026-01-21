"""
PEARL Automated Trading Bots

A collection of complete, self-contained automated trading bots for the
PEARLalgo trading system. Each bot is a full trading strategy with custom
indicators, automated logic, risk management, and performance tracking.

Available Bots:
- TrendFollowerBot: Trend-following strategies with pullback entries
- BreakoutBot: Breakout trading from consolidation patterns
- MeanReversionBot: Mean reversion using oscillator analysis

Each bot can be deployed as a zero-code automated strategy within PEARLalgo,
with comprehensive backtesting and performance monitoring capabilities.
"""

from .bot_template import (
    PearlBot,
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

__all__ = [
    # Base classes
    'PearlBot',
    'BotConfig',
    'TradeSignal',
    'BotPerformance',
    'IndicatorSuite',

    # Factory functions
    'create_bot',
    'register_bot',

    # Bot implementations
    'TrendFollowerBot',
    'BreakoutBot',
    'MeanReversionBot',
    'CompositeBot',
    'PearlAutoBot',
]