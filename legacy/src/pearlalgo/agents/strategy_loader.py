from __future__ import annotations

from typing import Callable, Dict

from pearlalgo.strategies.examples import (
    ESBreakoutStrategy,
    EquityMomentumStrategy,
    FuturesTrendStrategy,
    OptionsPremiumSellStrategy,
)
from pearlalgo.strategies.base import BaseStrategy

StrategyFactory = Callable[[], BaseStrategy]

REGISTRY: Dict[str, StrategyFactory] = {
    ESBreakoutStrategy.name: lambda: ESBreakoutStrategy(),
    EquityMomentumStrategy.name: lambda: EquityMomentumStrategy(),
    FuturesTrendStrategy.name: lambda: FuturesTrendStrategy(),
    OptionsPremiumSellStrategy.name: lambda: OptionsPremiumSellStrategy(),
}


def get_strategy(name: str) -> BaseStrategy:
    try:
        return REGISTRY[name]()
    except KeyError as exc:
        raise ValueError(f"Unknown strategy: {name}") from exc


def list_strategies() -> list[str]:
    return list(REGISTRY.keys())
