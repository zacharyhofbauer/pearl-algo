"""
Lux Algo Chart Prime Style Automated Trading Bots

A collection of complete, self-contained automated trading bots inspired by
Lux Algo's AI Strategy Alerts system. Each bot is a full trading strategy
with indicators, logic, risk management, and automation capabilities.

Available Bots:
- TrendFollowerBot: Trend-following strategies
- BreakoutBot: Breakout trading from consolidation patterns
- MeanReversionBot: Mean reversion using oscillator analysis

Each bot can be deployed as a zero-code automated strategy, similar to
Lux Algo's premium toolkits (PAC, S&O, OSC) with AI backtesting assistance.
"""

from .bot_template import (
    LuxAlgoBot,
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

__all__ = [
    # Base classes
    'LuxAlgoBot',
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
]