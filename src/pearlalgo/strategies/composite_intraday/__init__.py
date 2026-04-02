"""
Composite intraday strategy bundle.
"""

from __future__ import annotations

from pearlalgo.strategies.composite_intraday.engine import CompositeIntradayStrategy
from pearlalgo.strategies.composite_intraday.pinescript_core import (
    StrategyParams,
    calculate_atr,
    check_trading_session,
    default_config,
    detect_market_regime,
    generate_signals,
)

__all__ = [
    "CompositeIntradayStrategy",
    "StrategyParams",
    "calculate_atr",
    "check_trading_session",
    "default_config",
    "detect_market_regime",
    "generate_signals",
]
