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

from .brain import PearlBrain, ResponseSource
from .narrator import PearlNarrator
from .memory import PearlMemory
from .metrics import MetricsCollector, LLMRequest, ToolCall
from .data_access import TradeDataAccess
from .cache import ResponseCache, CacheEntry
from .tools import ToolExecutor, PEARL_TOOLS
from .config import PearlConfig, get_config
from .llm_mock import MockLLM, MockClaudeLLM

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
