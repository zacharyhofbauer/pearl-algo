"""
Pearl AI - Multi-Provider AI Abstraction Layer

This module provides a unified interface for interacting with multiple AI providers:
- Claude (Anthropic) - For reasoning tasks with native thinking support
- OpenAI GPT-4 - For code generation and general tasks
- Local models (Ollama) - For fast, cheap tasks
- Custom ML models - For signal scoring and predictions

Usage:
    from pearlalgo.ai import get_ai_router, AITaskType
    
    router = get_ai_router()
    response = await router.complete(
        messages=[{"role": "user", "content": "Analyze this trade setup"}],
        task_type=AITaskType.REASONING
    )
    
    # For decision tracing:
    from pearlalgo.ai import get_thinking_engine, DecisionType
    
    engine = get_thinking_engine()
    with engine.trace(DecisionType.SIGNAL_GENERATION, "sig-001") as trace:
        trace.add_indicator("RSI", 58.2, "Neutral zone", bullish=None)
        trace.set_decision("ALLOW", "Conditions met", 0.72)
    
    print(trace.format_thinking())
"""

from pearlalgo.ai.types import (
    AIMessage,
    AIResponse,
    AITaskType,
    CompletionConfig,
    ThinkingBlock,
    ToolCall,
    ToolResult,
)
from pearlalgo.ai.base import AIProvider
from pearlalgo.ai.router import AIRouter, get_ai_router
from pearlalgo.ai.thinking import (
    DecisionTrace,
    DecisionType,
    ThinkingEngine,
    ThinkingLevel,
    ThinkingStep,
    IndicatorCheck,
    FilterResult,
    KeyLevelCheck,
    ConfidenceFactor,
    get_thinking_engine,
    set_thinking_stream_callback,
)

__all__ = [
    # Types
    "AIMessage",
    "AIResponse",
    "AITaskType",
    "CompletionConfig",
    "ThinkingBlock",
    "ToolCall",
    "ToolResult",
    # Base
    "AIProvider",
    # Router
    "AIRouter",
    "get_ai_router",
    # Thinking Engine
    "DecisionTrace",
    "DecisionType",
    "ThinkingEngine",
    "ThinkingLevel",
    "ThinkingStep",
    "IndicatorCheck",
    "FilterResult",
    "KeyLevelCheck",
    "ConfidenceFactor",
    "get_thinking_engine",
    "set_thinking_stream_callback",
]
