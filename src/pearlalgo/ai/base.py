"""
AI Provider Base - Abstract base class for AI providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from pearlalgo.ai.types import (
    AIMessage,
    AIResponse,
    CompletionConfig,
    StreamChunk,
)


class AIProvider(ABC):
    """
    Abstract base class for AI providers.
    
    All AI providers (Claude, OpenAI, local models, etc.) must implement this interface.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name (e.g., 'claude', 'openai', 'ollama')."""
        ...
    
    @property
    @abstractmethod
    def default_model(self) -> str:
        """Return the default model for this provider."""
        ...
    
    @abstractmethod
    async def complete(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AIResponse:
        """
        Generate a completion for the given messages.
        
        Args:
            messages: List of messages in the conversation
            config: Optional configuration for the completion
            
        Returns:
            AIResponse with the generated content
        """
        ...
    
    @abstractmethod
    async def stream(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Stream a completion for the given messages.
        
        Args:
            messages: List of messages in the conversation
            config: Optional configuration for the completion
            
        Yields:
            StreamChunk objects as content is generated
        """
        ...
    
    def supports_thinking(self) -> bool:
        """Return True if this provider supports native thinking/reasoning blocks."""
        return False
    
    def supports_tools(self) -> bool:
        """Return True if this provider supports tool/function calling."""
        return False
    
    def supports_streaming(self) -> bool:
        """Return True if this provider supports streaming responses."""
        return True
    
    def supports_vision(self) -> bool:
        """Return True if this provider supports vision/image inputs."""
        return False
    
    async def health_check(self) -> bool:
        """
        Check if the provider is available and working.
        
        Returns:
            True if provider is healthy, False otherwise
        """
        try:
            # Simple test completion
            response = await self.complete(
                messages=[AIMessage.user("Say 'ok'")],
                config=CompletionConfig(max_tokens=10, enable_thinking=False),
            )
            return bool(response.content)
        except Exception:
            return False


class AIProviderError(Exception):
    """Base exception for AI provider errors."""
    pass


class AIProviderNotAvailableError(AIProviderError):
    """Raised when a provider is not available (e.g., missing API key)."""
    pass


class AIProviderAPIError(AIProviderError):
    """Raised when an API call fails."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AIProviderRateLimitError(AIProviderAPIError):
    """Raised when rate limited by the provider."""
    pass


class AIProviderQuotaError(AIProviderAPIError):
    """Raised when quota/billing limit is reached."""
    pass
