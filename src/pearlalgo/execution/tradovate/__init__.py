"""
Tradovate Execution Adapter

Provides execution capabilities via the Tradovate REST + WebSocket API.
Used for Tradovate Paper prop firm evaluation on Tradovate paper/demo accounts.
"""

from pearlalgo.execution.tradovate.config import TradovateConfig

__all__ = [
    "TradovateConfig",
]
