"""
IBKR Execution Adapter (INACTIVE).

Legacy execution via Interactive Brokers Gateway. Kept for reference only.
Active execution is Tradovate-only. See execution/tradovate/ for the active adapter.
"""

from .adapter import IBKRExecutionAdapter

__all__ = ["IBKRExecutionAdapter"]






