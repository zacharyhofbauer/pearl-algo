"""
Claude Provider - Anthropic Claude AI provider with native thinking support.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
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
    ThinkingBlock,
    ToolCall,
)
from pearlalgo.utils.logger import logger


# Graceful optional import
try:
    import anthropic
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None  # type: ignore
    AsyncAnthropic = None  # type: ignore
    ANTHROPIC_AVAILABLE = False


DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 16000  # Must be > thinking_budget when thinking enabled
DEFAULT_THINKING_BUDGET = 8192


class ClaudeProvider(AIProvider):
    """
    Anthropic Claude AI provider.
    
    Features:
    - Native thinking/reasoning blocks (extended thinking)
    - Tool/function calling
    - Streaming support
    - Vision support
    
    Usage:
        provider = ClaudeProvider()
        response = await provider.complete(
            messages=[AIMessage.user("Analyze this trade")],
            config=CompletionConfig(enable_thinking=True)
        )
        print(response.get_thinking_text())  # See the reasoning
        print(response.content)  # See the answer
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout: float = 120.0,
    ):
        """
        Initialize Claude provider.
        
        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Model to use (defaults to claude-sonnet-4-20250514)
            max_tokens: Default max tokens (defaults to 4096)
            timeout: Request timeout in seconds
        """
        if not ANTHROPIC_AVAILABLE:
            raise AIProviderNotAvailableError(
                "anthropic package not installed. Install with: pip install anthropic"
            )
        
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise AIProviderNotAvailableError(
                "ANTHROPIC_API_KEY not set. Add it to your .env file."
            )
        
        self._model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self._max_tokens = max_tokens or int(os.getenv("ANTHROPIC_MAX_TOKENS", DEFAULT_MAX_TOKENS))
        self._timeout = timeout
        
        self._client = AsyncAnthropic(
            api_key=self._api_key,
            timeout=self._timeout,
        )
        
        # Circuit breaker for billing/quota issues
        self._disabled_until: Optional[datetime] = None
        self._disabled_reason: Optional[str] = None
        
        logger.info(
            "Claude provider initialized",
            extra={"model": self._model, "max_tokens": self._max_tokens}
        )
    
    @property
    def name(self) -> str:
        return "claude"
    
    @property
    def default_model(self) -> str:
        return self._model
    
    def supports_thinking(self) -> bool:
        return True
    
    def supports_tools(self) -> bool:
        return True
    
    def supports_vision(self) -> bool:
        return True
    
    def _is_disabled(self) -> bool:
        """Check if circuit breaker is active."""
        if self._disabled_until is None:
            return False
        return datetime.now(timezone.utc) < self._disabled_until
    
    def _disable_for(self, seconds: int, reason: str) -> None:
        """Activate circuit breaker."""
        self._disabled_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        self._disabled_reason = reason[:200]
        logger.warning(f"Claude provider disabled for {seconds}s: {self._disabled_reason}")
    
    def _convert_messages(self, messages: list[AIMessage]) -> tuple[str, list[dict]]:
        """
        Convert AIMessage list to Anthropic format.
        
        Returns:
            Tuple of (system_prompt, messages_list)
        """
        system_prompt = ""
        anthropic_messages = []
        
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                # Anthropic handles system separately
                system_prompt = msg.content
            elif msg.role == MessageRole.USER:
                anthropic_messages.append({
                    "role": "user",
                    "content": msg.content,
                })
            elif msg.role == MessageRole.ASSISTANT:
                content = msg.content
                if msg.tool_calls:
                    # Include tool use in assistant message
                    content_blocks = []
                    if msg.content:
                        content_blocks.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        })
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": content_blocks,
                    })
                else:
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": content,
                    })
            elif msg.role == MessageRole.TOOL:
                # Tool results
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }],
                })
        
        return system_prompt, anthropic_messages
    
    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert tool definitions to Anthropic format."""
        anthropic_tools = []
        for tool in tools:
            anthropic_tools.append({
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "input_schema": tool.get("parameters", tool.get("input_schema", {})),
            })
        return anthropic_tools
    
    async def complete(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AIResponse:
        """Generate a completion with optional thinking."""
        if self._is_disabled():
            raise AIProviderAPIError(
                f"Claude disabled until {self._disabled_until}: {self._disabled_reason}"
            )
        
        config = config or CompletionConfig()
        system_prompt, anthropic_messages = self._convert_messages(messages)
        
        start_time = time.time()
        
        try:
            # Build request kwargs
            kwargs: dict = {
                "model": self._model,
                "max_tokens": config.max_tokens or self._max_tokens,
                "messages": anthropic_messages,
            }
            
            if system_prompt:
                kwargs["system"] = system_prompt
            
            if config.temperature != 0.7:  # Only set if non-default
                kwargs["temperature"] = config.temperature
            
            if config.stop_sequences:
                kwargs["stop_sequences"] = config.stop_sequences
            
            # Enable extended thinking if requested
            if config.enable_thinking:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": config.thinking_budget or DEFAULT_THINKING_BUDGET,
                }
            
            # Add tools if provided
            if config.tools:
                kwargs["tools"] = self._convert_tools(config.tools)
                if config.tool_choice != "auto":
                    if config.tool_choice == "none":
                        kwargs["tool_choice"] = {"type": "none"}
                    elif config.tool_choice == "required":
                        kwargs["tool_choice"] = {"type": "any"}
                    else:
                        kwargs["tool_choice"] = {"type": "tool", "name": config.tool_choice}
            
            # Make the API call
            response = await self._client.messages.create(**kwargs)
            
            latency_ms = (time.time() - start_time) * 1000
            
            # Parse response
            content = ""
            thinking_blocks = []
            tool_calls = []
            
            for block in response.content:
                if block.type == "text":
                    content = block.text
                elif block.type == "thinking":
                    thinking_blocks.append(ThinkingBlock(
                        content=block.thinking,
                        timestamp=datetime.now(timezone.utc),
                    ))
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                        timestamp=datetime.now(timezone.utc),
                    ))
            
            return AIResponse(
                content=content,
                thinking_blocks=thinking_blocks,
                tool_calls=tool_calls,
                provider=self.name,
                model=response.model,
                finish_reason=response.stop_reason or "",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                thinking_tokens=getattr(response.usage, "thinking_tokens", 0),
                latency_ms=latency_ms,
            )
        
        except anthropic.RateLimitError as e:
            logger.error(f"Claude rate limit: {e}")
            raise AIProviderRateLimitError(str(e)) from e

        except anthropic.APIStatusError as e:
            error_msg = str(e).lower()
            if "insufficient" in error_msg or "billing" in error_msg or "quota" in error_msg:
                logger.error(f"Claude quota error: {e}")
                self._disable_for(6 * 3600, str(e))
                raise AIProviderQuotaError(str(e)) from e
            logger.error(f"Claude API error: {e}")
            raise AIProviderAPIError(str(e), getattr(e, "status_code", None)) from e

        except Exception as e:
            logger.error(f"Unexpected Claude error: {e}")
            raise AIProviderAPIError(str(e)) from e
    
    async def stream(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion with real-time output."""
        if self._is_disabled():
            raise AIProviderAPIError(
                f"Claude disabled until {self._disabled_until}: {self._disabled_reason}"
            )
        
        config = config or CompletionConfig()
        system_prompt, anthropic_messages = self._convert_messages(messages)
        
        try:
            kwargs: dict = {
                "model": self._model,
                "max_tokens": config.max_tokens or self._max_tokens,
                "messages": anthropic_messages,
            }
            
            if system_prompt:
                kwargs["system"] = system_prompt
            
            if config.enable_thinking:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": config.thinking_budget or DEFAULT_THINKING_BUDGET,
                }
            
            if config.tools:
                kwargs["tools"] = self._convert_tools(config.tools)
            
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "text"):
                            yield StreamChunk(content=delta.text)
                        elif hasattr(delta, "thinking"):
                            yield StreamChunk(thinking_content=delta.thinking)
                    elif event.type == "message_stop":
                        yield StreamChunk(is_final=True)
        
        except anthropic.RateLimitError as e:
            logger.error(f"Claude rate limit during stream: {e}")
            raise AIProviderRateLimitError(str(e)) from e

        except Exception as e:
            logger.error(f"Claude stream error: {e}")
            raise AIProviderAPIError(str(e)) from e


def get_claude_provider() -> Optional[ClaudeProvider]:
    """
    Factory function to get a Claude provider instance.
    
    Returns:
        ClaudeProvider if available and configured, None otherwise.
    """
    if not ANTHROPIC_AVAILABLE:
        logger.debug("Claude not available: anthropic package not installed")
        return None
    
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.debug("Claude not available: ANTHROPIC_API_KEY not set")
        return None
    
    try:
        return ClaudeProvider()
    except AIProviderNotAvailableError as e:
        logger.warning(f"Could not initialize Claude provider: {e}")
        return None
