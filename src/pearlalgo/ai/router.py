"""
AI Router - Intelligent routing of AI tasks to the best provider.

Routes different types of tasks to the most appropriate AI provider:
- Reasoning tasks -> Claude (native thinking support)
- Code generation -> Claude or GPT-4
- Quick lookups -> Local models (fast, free)
- Signal scoring -> ML models (specialized)
"""

from __future__ import annotations

import os
from typing import AsyncIterator, Optional

from pearlalgo.ai.base import AIProvider, AIProviderNotAvailableError
from pearlalgo.ai.types import (
    AIMessage,
    AIResponse,
    AITaskType,
    CompletionConfig,
    StreamChunk,
)
from pearlalgo.utils.logger import logger


# Lazy imports to avoid circular dependencies
def _get_claude_provider():
    from pearlalgo.ai.claude_provider import get_claude_provider
    return get_claude_provider()

def _get_openai_provider():
    from pearlalgo.ai.openai_provider import get_openai_provider
    return get_openai_provider()

def _get_local_provider():
    from pearlalgo.ai.local_provider import get_local_provider
    return get_local_provider()

def _get_ml_provider():
    from pearlalgo.ai.ml_provider import get_ml_provider
    return get_ml_provider()


# Default routing configuration
DEFAULT_ROUTING = {
    AITaskType.REASONING: "openai",
    AITaskType.CODE_GEN: "openai",
    AITaskType.QUICK: "local",
    AITaskType.SIGNAL_SCORING: "ml",
    AITaskType.CHAT: "openai",
    AITaskType.ANALYSIS: "openai",
}

# Fallback order when preferred provider is not available
FALLBACK_ORDER = ["openai", "claude", "local"]


class AIRouter:
    """
    Intelligent router for AI tasks.
    
    Routes tasks to the most appropriate AI provider based on:
    - Task type (reasoning, code gen, quick lookup, etc.)
    - Provider availability
    - Configuration preferences
    
    Usage:
        router = AIRouter()
        
        # For reasoning tasks (uses Claude with thinking)
        response = await router.complete(
            messages=[AIMessage.user("Analyze this trade setup")],
            task_type=AITaskType.REASONING
        )
        
        # For quick lookups (uses local model)
        response = await router.complete(
            messages=[AIMessage.user("What's the RSI value?")],
            task_type=AITaskType.QUICK
        )
    """
    
    def __init__(
        self,
        routing: Optional[dict[AITaskType, str]] = None,
        default_provider: Optional[str] = None,
    ):
        """
        Initialize the AI router.
        
        Args:
            routing: Optional custom routing configuration
            default_provider: Default provider when routing doesn't match
        """
        self._routing = routing or DEFAULT_ROUTING.copy()
        self._default_provider = default_provider or os.getenv("AI_DEFAULT_PROVIDER", "claude")
        
        # Provider instances (lazy loaded)
        self._providers: dict[str, Optional[AIProvider]] = {
            "claude": None,
            "openai": None,
            "local": None,
            "ml": None,
        }
        self._providers_initialized = False
        
        logger.info(
            "AI Router initialized",
            extra={"default_provider": self._default_provider, "routing": {k.value: v for k, v in self._routing.items()}}
        )
    
    def _init_providers(self) -> None:
        """Lazily initialize all providers."""
        if self._providers_initialized:
            return
        
        self._providers["claude"] = _get_claude_provider()
        self._providers["openai"] = _get_openai_provider()
        self._providers["local"] = _get_local_provider()
        self._providers["ml"] = _get_ml_provider()
        
        available = [name for name, p in self._providers.items() if p is not None]
        logger.info(f"AI providers available: {available}")
        
        self._providers_initialized = True
    
    def _get_provider(self, name: str) -> Optional[AIProvider]:
        """Get a provider by name, initializing if needed."""
        self._init_providers()
        return self._providers.get(name)
    
    def _select_provider(self, task_type: AITaskType) -> AIProvider:
        """
        Select the best provider for a task type.
        
        Args:
            task_type: The type of task to perform
            
        Returns:
            The selected AIProvider
            
        Raises:
            AIProviderNotAvailableError: If no provider is available
        """
        self._init_providers()
        
        # Get preferred provider for this task type
        preferred = self._routing.get(task_type, self._default_provider)
        
        # Try preferred provider
        provider = self._providers.get(preferred)
        if provider is not None:
            logger.debug(f"Using {preferred} for {task_type.value}")
            return provider
        
        # Try fallbacks
        for fallback in FALLBACK_ORDER:
            if fallback != preferred:
                provider = self._providers.get(fallback)
                if provider is not None:
                    logger.info(f"Falling back to {fallback} for {task_type.value} (preferred {preferred} unavailable)")
                    return provider
        
        raise AIProviderNotAvailableError(
            f"No AI provider available for task type {task_type.value}. "
            f"Tried: {preferred}, {', '.join(FALLBACK_ORDER)}"
        )
    
    async def complete(
        self,
        messages: list[AIMessage],
        task_type: AITaskType = AITaskType.CHAT,
        config: Optional[CompletionConfig] = None,
    ) -> AIResponse:
        """
        Generate a completion using the best provider for the task.
        
        Args:
            messages: List of messages in the conversation
            task_type: Type of task (affects provider selection)
            config: Optional completion configuration
            
        Returns:
            AIResponse from the selected provider
        """
        provider = self._select_provider(task_type)
        
        # Adjust config based on task type
        config = config or CompletionConfig()
        
        if task_type == AITaskType.REASONING and provider.supports_thinking():
            config.enable_thinking = True
        elif task_type == AITaskType.QUICK:
            config.enable_thinking = False
            config.max_tokens = min(config.max_tokens, 1024)
        
        return await provider.complete(messages, config)
    
    async def stream(
        self,
        messages: list[AIMessage],
        task_type: AITaskType = AITaskType.CHAT,
        config: Optional[CompletionConfig] = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Stream a completion using the best provider for the task.
        
        Args:
            messages: List of messages in the conversation
            task_type: Type of task
            config: Optional completion configuration
            
        Yields:
            StreamChunk objects as content is generated
        """
        provider = self._select_provider(task_type)
        
        config = config or CompletionConfig()
        config.stream = True
        
        if task_type == AITaskType.REASONING and provider.supports_thinking():
            config.enable_thinking = True
        
        async for chunk in provider.stream(messages, config):
            yield chunk
    
    def get_provider(self, name: str) -> Optional[AIProvider]:
        """
        Get a specific provider by name.
        
        Args:
            name: Provider name ('claude', 'openai', 'local', 'ml')
            
        Returns:
            The provider if available, None otherwise
        """
        return self._get_provider(name)
    
    def list_available_providers(self) -> list[str]:
        """List all available provider names."""
        self._init_providers()
        return [name for name, p in self._providers.items() if p is not None]
    
    def set_routing(self, task_type: AITaskType, provider: str) -> None:
        """
        Update the routing for a task type.
        
        Args:
            task_type: The task type to update
            provider: The provider name to use
        """
        self._routing[task_type] = provider
        logger.info(f"Updated routing: {task_type.value} -> {provider}")
    
    async def health_check(self) -> dict[str, bool]:
        """
        Check the health of all providers.
        
        Returns:
            Dictionary of provider name -> health status
        """
        self._init_providers()
        
        results = {}
        for name, provider in self._providers.items():
            if provider is None:
                results[name] = False
            else:
                try:
                    results[name] = await provider.health_check()
                except Exception:
                    results[name] = False
        
        return results


# Global router instance
_router: Optional[AIRouter] = None


def get_ai_router() -> AIRouter:
    """
    Get the global AI router instance.
    
    Creates the router on first call.
    
    Returns:
        The global AIRouter instance
    """
    global _router
    if _router is None:
        _router = AIRouter()
    return _router


def reset_ai_router() -> None:
    """Reset the global router (useful for testing)."""
    global _router
    _router = None
