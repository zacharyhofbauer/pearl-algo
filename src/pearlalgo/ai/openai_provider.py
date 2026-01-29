"""
OpenAI Provider - OpenAI GPT-4 AI provider.

Adapts the existing OpenAI client to the unified AI provider interface.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Optional

from pearlalgo.ai.base import (
    AIProvider,
    AIProviderAPIError,
    AIProviderNotAvailableError,
    AIProviderQuotaError,
    AIProviderRateLimitError,
)
from pearlalgo.ai.types import (
    AIMessage,
    AIResponse,
    CompletionConfig,
    MessageRole,
    StreamChunk,
    ToolCall,
)
from pearlalgo.utils.logger import logger


# Graceful optional import
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    AsyncOpenAI = None  # type: ignore
    OPENAI_AVAILABLE = False


DEFAULT_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS = 4096


class OpenAIProvider(AIProvider):
    """
    OpenAI GPT-4 AI provider.
    
    Features:
    - Tool/function calling
    - Streaming support
    - Vision support (for GPT-4V)
    
    Note: OpenAI doesn't have native thinking blocks like Claude,
    but we can simulate reasoning through system prompts.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout: float = 120.0,
    ):
        """
        Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (defaults to gpt-4o)
            max_tokens: Default max tokens
            timeout: Request timeout in seconds
        """
        if not OPENAI_AVAILABLE:
            raise AIProviderNotAvailableError(
                "openai package not installed. Install with: pip install openai"
            )
        
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise AIProviderNotAvailableError(
                "OPENAI_API_KEY not set. Add it to your .env file."
            )
        
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._max_tokens = max_tokens or int(os.getenv("OPENAI_MAX_TOKENS", DEFAULT_MAX_TOKENS))
        self._timeout = timeout
        
        self._client = AsyncOpenAI(
            api_key=self._api_key,
            timeout=self._timeout,
        )
        
        # Circuit breaker
        self._disabled_until: Optional[datetime] = None
        self._disabled_reason: Optional[str] = None
        
        logger.info(
            "OpenAI provider initialized",
            extra={"model": self._model, "max_tokens": self._max_tokens}
        )
    
    @property
    def name(self) -> str:
        return "openai"
    
    @property
    def default_model(self) -> str:
        return self._model
    
    def supports_thinking(self) -> bool:
        # OpenAI doesn't have native thinking, but we can use o1 models
        # which have internal reasoning (not exposed)
        return False
    
    def supports_tools(self) -> bool:
        return True
    
    def supports_vision(self) -> bool:
        return "gpt-4" in self._model or "gpt-4o" in self._model
    
    def _is_disabled(self) -> bool:
        if self._disabled_until is None:
            return False
        return datetime.now(timezone.utc) < self._disabled_until
    
    def _disable_for(self, seconds: int, reason: str) -> None:
        self._disabled_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        self._disabled_reason = reason[:200]
        logger.warning(f"OpenAI provider disabled for {seconds}s: {self._disabled_reason}")
    
    def _convert_messages(self, messages: list[AIMessage]) -> list[dict]:
        """Convert AIMessage list to OpenAI format."""
        openai_messages = []
        
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                openai_messages.append({
                    "role": "system",
                    "content": msg.content,
                })
            elif msg.role == MessageRole.USER:
                openai_messages.append({
                    "role": "user",
                    "content": msg.content,
                })
            elif msg.role == MessageRole.ASSISTANT:
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": msg.content or None,
                }
                if msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                openai_messages.append(assistant_msg)
            elif msg.role == MessageRole.TOOL:
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
        
        return openai_messages
    
    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert tool definitions to OpenAI format."""
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", tool.get("input_schema", {})),
                },
            })
        return openai_tools
    
    async def complete(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AIResponse:
        """Generate a completion."""
        if self._is_disabled():
            raise AIProviderAPIError(
                f"OpenAI disabled until {self._disabled_until}: {self._disabled_reason}"
            )
        
        config = config or CompletionConfig()
        openai_messages = self._convert_messages(messages)
        
        start_time = time.time()
        
        try:
            kwargs: dict = {
                "model": self._model,
                "max_tokens": config.max_tokens or self._max_tokens,
                "messages": openai_messages,
            }
            
            if config.temperature != 0.7:
                kwargs["temperature"] = config.temperature
            
            if config.top_p != 1.0:
                kwargs["top_p"] = config.top_p
            
            if config.stop_sequences:
                kwargs["stop"] = config.stop_sequences
            
            if config.tools:
                kwargs["tools"] = self._convert_tools(config.tools)
                if config.tool_choice != "auto":
                    if config.tool_choice == "none":
                        kwargs["tool_choice"] = "none"
                    elif config.tool_choice == "required":
                        kwargs["tool_choice"] = "required"
                    else:
                        kwargs["tool_choice"] = {
                            "type": "function",
                            "function": {"name": config.tool_choice},
                        }
            
            response = await self._client.chat.completions.create(**kwargs)
            
            latency_ms = (time.time() - start_time) * 1000
            
            # Parse response
            choice = response.choices[0] if response.choices else None
            content = ""
            tool_calls = []
            
            if choice:
                content = choice.message.content or ""
                if choice.message.tool_calls:
                    for tc in choice.message.tool_calls:
                        tool_calls.append(ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=json.loads(tc.function.arguments) if tc.function.arguments else {},
                            timestamp=datetime.now(timezone.utc),
                        ))
            
            return AIResponse(
                content=content,
                thinking_blocks=[],  # OpenAI doesn't have thinking
                tool_calls=tool_calls,
                provider=self.name,
                model=response.model,
                finish_reason=choice.finish_reason if choice else "",
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                latency_ms=latency_ms,
            )
        
        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg:
                logger.error(f"OpenAI rate limit: {e}")
                raise AIProviderRateLimitError(str(e)) from e
            elif "insufficient_quota" in error_msg or "billing" in error_msg:
                logger.error(f"OpenAI quota error: {e}")
                self._disable_for(6 * 3600, str(e))
                raise AIProviderQuotaError(str(e)) from e
            else:
                logger.error(f"OpenAI error: {e}")
                raise AIProviderAPIError(str(e)) from e
    
    async def stream(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion."""
        if self._is_disabled():
            raise AIProviderAPIError(
                f"OpenAI disabled until {self._disabled_until}: {self._disabled_reason}"
            )
        
        config = config or CompletionConfig()
        openai_messages = self._convert_messages(messages)
        
        try:
            kwargs: dict = {
                "model": self._model,
                "max_tokens": config.max_tokens or self._max_tokens,
                "messages": openai_messages,
                "stream": True,
            }
            
            if config.tools:
                kwargs["tools"] = self._convert_tools(config.tools)
            
            stream = await self._client.chat.completions.create(**kwargs)
            
            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield StreamChunk(content=delta.content)
                    if chunk.choices[0].finish_reason:
                        yield StreamChunk(is_final=True)
        
        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg:
                raise AIProviderRateLimitError(str(e)) from e
            raise AIProviderAPIError(str(e)) from e


def get_openai_provider() -> Optional[OpenAIProvider]:
    """
    Factory function to get an OpenAI provider instance.
    
    Returns:
        OpenAIProvider if available and configured, None otherwise.
    """
    if not OPENAI_AVAILABLE:
        logger.debug("OpenAI not available: openai package not installed")
        return None
    
    if not os.getenv("OPENAI_API_KEY"):
        logger.debug("OpenAI not available: OPENAI_API_KEY not set")
        return None
    
    try:
        return OpenAIProvider()
    except AIProviderNotAvailableError as e:
        logger.warning(f"Could not initialize OpenAI provider: {e}")
        return None
