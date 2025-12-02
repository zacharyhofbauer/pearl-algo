"""Strategy interfaces and examples."""

from pearlalgo.strategies.base import (
    BaseStrategy,
    register_strategy,
    get_strategy,
    list_strategies,
    get_strategy_info,
    create_strategy_signal,
)

# Import strategies to register them
from pearlalgo.strategies import scalping  # noqa: F401
from pearlalgo.strategies import intraday_swing  # noqa: F401

__all__ = [
    "BaseStrategy",
    "register_strategy",
    "get_strategy",
    "list_strategies",
    "get_strategy_info",
    "create_strategy_signal",
]
