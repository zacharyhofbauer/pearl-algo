"""
Canonical strategy package for PEARL.
"""

from __future__ import annotations

from pearlalgo.strategies.registry import (
    ACTIVE_STRATEGY,
    create_strategy,
    get_strategy_defaults,
    get_strategy_param_fields,
    resolve_active_strategy,
)

__all__ = [
    "ACTIVE_STRATEGY",
    "create_strategy",
    "get_strategy_defaults",
    "get_strategy_param_fields",
    "resolve_active_strategy",
]
