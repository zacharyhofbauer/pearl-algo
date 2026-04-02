"""
Strategy registry for live runtime construction.
"""

from __future__ import annotations

from typing import Any, Mapping

from pearlalgo.strategies.composite_intraday import CompositeIntradayStrategy, StrategyParams


ACTIVE_STRATEGY = "composite_intraday"


def resolve_active_strategy(config: Mapping[str, Any] | None = None) -> str:
    strategy_cfg = {}
    if isinstance(config, Mapping):
        raw = config.get("strategy", {}) or {}
        if isinstance(raw, Mapping):
            strategy_cfg = raw
    active = str(strategy_cfg.get("active", ACTIVE_STRATEGY) or ACTIVE_STRATEGY).strip()
    return active or ACTIVE_STRATEGY


def create_strategy(config: Mapping[str, Any]) -> CompositeIntradayStrategy:
    active = resolve_active_strategy(config)
    if active != ACTIVE_STRATEGY:
        raise ValueError(f"Unknown active strategy bundle: {active}")
    return CompositeIntradayStrategy(config=config)


def get_strategy_param_fields() -> set[str]:
    return set(StrategyParams.model_fields.keys())


def get_strategy_defaults() -> dict[str, Any]:
    strategy = CompositeIntradayStrategy(config={})
    return dict(strategy.default_config())
