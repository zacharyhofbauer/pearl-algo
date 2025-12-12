"""Strategy interfaces and examples."""

from pearlalgo.strategies.base import (
    BaseStrategy,
    register_strategy,
    get_strategy,
    list_strategies,
    get_strategy_info,
    create_strategy_signal,
)

# Import strategies to register them (optional - only if they exist)
try:
    from pearlalgo.strategies import scalping  # noqa: F401
except ImportError:
    pass  # scalping module not available

try:
    from pearlalgo.strategies import intraday_swing  # noqa: F401
except ImportError:
    pass  # intraday_swing module not available

__all__ = [
    "BaseStrategy",
    "register_strategy",
    "get_strategy",
    "list_strategies",
    "get_strategy_info",
    "create_strategy_signal",
]
