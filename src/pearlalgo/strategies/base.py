from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable
import pandas as pd

from pearlalgo.futures.signals import generate_signal

# Strategy registry
_STRATEGY_REGISTRY: dict[str, dict[str, Any]]] = {}


def register_strategy(
    name: str,
    description: str = "",
    default_params: dict[str, Any] | None = None,
) -> Callable:
    """
    Decorator to register a strategy.
    
    Usage:
        @register_strategy("my_strategy", "My strategy description", {"param1": 10})
        def my_strategy_func(symbol, df, **params):
            ...
    """
    def decorator(func: Callable) -> Callable:
        _STRATEGY_REGISTRY[name] = {
            "name": name,
            "function": func,
            "description": description,
            "default_params": default_params or {},
        }
        return func
    return decorator


def get_strategy(name: str) -> dict[str, Any] | None:
    """Get strategy information from registry."""
    return _STRATEGY_REGISTRY.get(name)


def list_strategies() -> list[str]:
    """List all registered strategy names."""
    return list(_STRATEGY_REGISTRY.keys())


def get_strategy_info(name: str) -> dict[str, Any] | None:
    """Get detailed information about a strategy."""
    strategy = _STRATEGY_REGISTRY.get(name)
    if strategy:
        return {
            "name": strategy["name"],
            "description": strategy["description"],
            "default_params": strategy["default_params"],
        }
    return None


def create_strategy_signal(
    name: str,
    symbol: str,
    df: pd.DataFrame,
    **params: Any,
) -> dict[str, Any]:
    """
    Factory function to create a signal using a registered strategy.
    
    Args:
        name: Strategy name (must be registered)
        symbol: Trading symbol
        df: OHLCV DataFrame
        **params: Strategy-specific parameters
    
    Returns:
        Signal dictionary with side, indicators, confidence, etc.
    """
    # First try registered strategies
    if name in _STRATEGY_REGISTRY:
        strategy = _STRATEGY_REGISTRY[name]
        func = strategy["function"]
        # Merge default params with provided params
        merged_params = {**strategy["default_params"], **params}
        return func(symbol, df, **merged_params)
    
    # Fall back to signals.generate_signal for built-in strategies
    return generate_signal(symbol, df, strategy_name=name, **params)


class BaseStrategy(ABC):
    """Base class for strategy implementations."""
    name: str = "base"
    description: str = ""
    default_params: dict[str, Any] = {}

    @abstractmethod
    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return signals/positions given OHLCV data."""
    
    def get_signal(self, symbol: str, df: pd.DataFrame, **params: Any) -> dict[str, Any]:
        """Generate a signal using this strategy."""
        merged_params = {**self.default_params, **params}
        return create_strategy_signal(self.name, symbol, df, **merged_params)
