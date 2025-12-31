"""
PearlAlgo Execution Layer

Provides execution adapters for placing orders with various brokers.
Currently supports IBKR with bracket orders, arm/disarm controls, and safety guardrails.
"""

from pearlalgo.execution.base import (
    ExecutionAdapter,
    ExecutionConfig,
    ExecutionDecision,
    ExecutionResult,
    OrderStatus,
    Position,
)

__all__ = [
    "ExecutionAdapter",
    "ExecutionConfig",
    "ExecutionDecision",
    "ExecutionResult",
    "OrderStatus",
    "Position",
]



