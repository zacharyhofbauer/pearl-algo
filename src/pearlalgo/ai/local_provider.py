"""
Local Provider - Ollama/local model AI provider for fast, cheap tasks.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import AsyncIterator, Optional

from pearlalgo.ai.base import (
    AIProvider,
    AIProviderAPIError,
    AIProviderNotAvailableError,
)
from pearlalgo.ai.types import (
    AIMessage,
    AIResponse,
    CompletionConfig,
    MessageRole,
    StreamChunk,
)
from pearlalgo.utils.logger import logger


# Graceful optional import
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None  # type: ignore
    HTTPX_AVAILABLE = False


DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"


class LocalProvider(AIProvider):
    """
    Local model provider using Ollama API.
    
    Optimized for:
    - Fast, cheap inference
    - Quick status checks
    - Simple lookups
    - Offline operation
    
    Note: Local models don't support advanced features like
    tool calling or thinking blocks, but they're fast and free.
    """
    
    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize local provider.
        
        Args:
            endpoint: Ollama API endpoint (defaults to http://localhost:11434)
            model: Model to use (defaults to llama3.2)
            timeout: Request timeout in seconds
        """
        if not HTTPX_AVAILABLE:
            raise AIProviderNotAvailableError(
                "httpx package not installed. Install with: pip install httpx"
            )
        
        self._endpoint = endpoint or os.getenv("OLLAMA_ENDPOINT", DEFAULT_ENDPOINT)
        self._model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
        self._timeout = timeout
        
        self._client = httpx.AsyncClient(timeout=self._timeout)
        
        logger.info(
            "Local provider initialized",
            extra={"endpoint": self._endpoint, "model": self._model}
        )
    
    @property
    def name(self) -> str:
        return "local"
    
    @property
    def default_model(self) -> str:
        return self._model
    
    def supports_thinking(self) -> bool:
        return False
    
    def supports_tools(self) -> bool:
        return False  # Could be enabled for some models
    
    def supports_vision(self) -> bool:
        return False  # Could be enabled for llava models
    
    def _convert_messages(self, messages: list[AIMessage]) -> list[dict]:
        """Convert AIMessage list to Ollama format."""
        ollama_messages = []
        
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                ollama_messages.append({
                    "role": "system",
                    "content": msg.content,
                })
            elif msg.role == MessageRole.USER:
                ollama_messages.append({
                    "role": "user",
                    "content": msg.content,
                })
            elif msg.role == MessageRole.ASSISTANT:
                ollama_messages.append({
                    "role": "assistant",
                    "content": msg.content,
                })
        
        return ollama_messages
    
    async def complete(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AIResponse:
        """Generate a completion using local model."""
        config = config or CompletionConfig()
        ollama_messages = self._convert_messages(messages)
        
        start_time = time.time()
        
        try:
            response = await self._client.post(
                f"{self._endpoint}/api/chat",
                json={
                    "model": self._model,
                    "messages": ollama_messages,
                    "stream": False,
                    "options": {
                        "num_predict": config.max_tokens,
                        "temperature": config.temperature,
                    },
                },
            )
            response.raise_for_status()
            
            latency_ms = (time.time() - start_time) * 1000
            data = response.json()
            
            return AIResponse(
                content=data.get("message", {}).get("content", ""),
                thinking_blocks=[],
                tool_calls=[],
                provider=self.name,
                model=self._model,
                finish_reason="stop",
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
                latency_ms=latency_ms,
            )
        
        except httpx.ConnectError:
            raise AIProviderNotAvailableError(
                f"Cannot connect to Ollama at {self._endpoint}. Is it running?"
            )
        
        except httpx.HTTPStatusError as e:
            raise AIProviderAPIError(f"Ollama error: {e}", e.response.status_code)
        
        except Exception as e:
            raise AIProviderAPIError(f"Local model error: {e}")
    
    async def stream(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion from local model."""
        config = config or CompletionConfig()
        ollama_messages = self._convert_messages(messages)
        
        try:
            async with self._client.stream(
                "POST",
                f"{self._endpoint}/api/chat",
                json={
                    "model": self._model,
                    "messages": ollama_messages,
                    "stream": True,
                    "options": {
                        "num_predict": config.max_tokens,
                        "temperature": config.temperature,
                    },
                },
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    import json
                    data = json.loads(line)
                    
                    if data.get("done"):
                        yield StreamChunk(is_final=True)
                    elif data.get("message", {}).get("content"):
                        yield StreamChunk(content=data["message"]["content"])
        
        except httpx.ConnectError:
            raise AIProviderNotAvailableError(
                f"Cannot connect to Ollama at {self._endpoint}"
            )
        
        except Exception as e:
            raise AIProviderAPIError(f"Local model stream error: {e}")
    
    async def health_check(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            response = await self._client.get(f"{self._endpoint}/api/tags")
            response.raise_for_status()
            
            data = response.json()
            models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
            
            if self._model.split(":")[0] not in models:
                logger.warning(f"Model {self._model} not found in Ollama. Available: {models}")
                return False
            
            return True
        
        except Exception as e:
            logger.debug(f"Local provider health check failed: {e}")
            return False
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


def get_local_provider() -> Optional[LocalProvider]:
    """
    Factory function to get a local provider instance.
    
    Returns:
        LocalProvider if available, None otherwise.
    """
    if not HTTPX_AVAILABLE:
        logger.debug("Local provider not available: httpx not installed")
        return None
    
    try:
        return LocalProvider()
    except AIProviderNotAvailableError as e:
        logger.debug(f"Could not initialize local provider: {e}")
        return None
