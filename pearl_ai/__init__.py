"""
Pearl AI 3.0 - Data-Grounded Trading Analyst

A hybrid AI system that combines local LLM for quick responses
with Claude API for deep analysis, coaching, and data-grounded insights.

3.0 Features:
- Trade database RAG for grounded analysis
- Observability & cost tracking
- Response caching with semantic hashing
- Conversation persistence
- Streaming chat responses
- Tool use for structured queries
"""

from __future__ import annotations

# NOTE:
# This package is used in multiple contexts (runtime app, CI eval runner, tooling).
# Avoid importing optional/heavy dependencies at import time so that lightweight
# tooling (e.g., `python -m pearl_ai.eval.ci --mock`) can run without requiring
# the full LLM stack to be installed.

import importlib
from typing import TYPE_CHECKING, Any

__all__ = [
    # Core
    "PearlBrain",
    "PearlNarrator",
    "PearlMemory",
    "ResponseSource",
    # 3.0: Observability
    "MetricsCollector",
    "LLMRequest",
    "ToolCall",
    # 3.0: RAG
    "TradeDataAccess",
    # 3.0: Caching
    "ResponseCache",
    "CacheEntry",
    # 3.0: Tools
    "ToolExecutor",
    "PEARL_TOOLS",
    # 3.0: Configuration
    "PearlConfig",
    "get_config",
    # 3.0: Testing
    "MockLLM",
    "MockClaudeLLM",
]
__version__ = "3.0.0"

# For type checkers only (keeps IDE hints without runtime imports).
if TYPE_CHECKING:
    from .brain import PearlBrain, ResponseSource
    from .narrator import PearlNarrator
    from .memory import PearlMemory
    from .metrics import MetricsCollector, LLMRequest, ToolCall
    from .data_access import TradeDataAccess
    from .cache import ResponseCache, CacheEntry
    from .tools import ToolExecutor, PEARL_TOOLS
    from .config import PearlConfig, get_config
    from .llm_mock import MockLLM, MockClaudeLLM


_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    # Core
    "PearlBrain": ("brain", "PearlBrain"),
    "ResponseSource": ("brain", "ResponseSource"),
    "PearlNarrator": ("narrator", "PearlNarrator"),
    "PearlMemory": ("memory", "PearlMemory"),
    # 3.0: Observability
    "MetricsCollector": ("metrics", "MetricsCollector"),
    "LLMRequest": ("metrics", "LLMRequest"),
    "ToolCall": ("metrics", "ToolCall"),
    # 3.0: RAG
    "TradeDataAccess": ("data_access", "TradeDataAccess"),
    # 3.0: Caching
    "ResponseCache": ("cache", "ResponseCache"),
    "CacheEntry": ("cache", "CacheEntry"),
    # 3.0: Tools
    "ToolExecutor": ("tools", "ToolExecutor"),
    "PEARL_TOOLS": ("tools", "PEARL_TOOLS"),
    # 3.0: Configuration
    "PearlConfig": ("config", "PearlConfig"),
    "get_config": ("config", "get_config"),
    # 3.0: Testing
    "MockLLM": ("llm_mock", "MockLLM"),
    "MockClaudeLLM": ("llm_mock", "MockClaudeLLM"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRS.get(name)
    if not target:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, attr_name)
    # Cache in globals to avoid repeated imports/attribute lookups
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(list(globals().keys()) + list(_LAZY_ATTRS.keys())))
