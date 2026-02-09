"""
Local LLM Interface - Ollama Integration

Provides fast, local inference for quick narrations and simple queries.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
import aiohttp

logger = logging.getLogger(__name__)


class LocalLLM:
    """
    Interface to local LLM via Ollama.

    Optimized for:
    - Quick trade narrations
    - Simple state queries
    - Real-time event descriptions
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        host: str = "http://localhost:11434",
        timeout: int = 30,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None
        self._available: Optional[bool] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def is_available(self) -> bool:
        """Check if Ollama is running and model is available."""
        if self._available is not None:
            return self._available

        try:
            session = await self._get_session()
            async with session.get(f"{self.host}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    # Check if our model (or a variant) is available
                    model_base = self.model.split(":")[0]
                    self._available = any(model_base in m for m in models)

                    if not self._available:
                        logger.warning(f"Model {self.model} not found. Available: {models}")
                    return self._available

        except Exception as e:
            logger.debug(f"Ollama not available: {e}")
            self._available = False

        return False

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        stop: Optional[List[str]] = None,
    ) -> str:
        """
        Generate a response from the local LLM.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            stop: Stop sequences

        Returns:
            Generated text response
        """
        if not await self.is_available():
            raise RuntimeError("Ollama is not available")

        # Build the request
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        if system:
            payload["system"] = system

        if stop:
            payload["options"]["stop"] = stop

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.host}/api/generate",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"Ollama error: {error}")
                    raise RuntimeError(f"Ollama returned {resp.status}")

                data = await resp.json()
                response = data.get("response", "").strip()

                logger.debug(f"Local LLM generated {len(response)} chars in {data.get('total_duration', 0) / 1e9:.2f}s")
                return response

        except asyncio.TimeoutError:
            logger.error("Local LLM request timed out")
            raise
        except Exception as e:
            logger.error(f"Local LLM error: {e}")
            raise

    async def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 256,
        temperature: float = 0.7,
    ) -> str:
        """
        Chat-style interface with message history.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated response
        """
        if not await self.is_available():
            raise RuntimeError("Ollama is not available")

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.host}/api/chat",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"Ollama chat error: {error}")

                data = await resp.json()
                return data.get("message", {}).get("content", "").strip()

        except Exception as e:
            logger.error(f"Local LLM chat error: {e}")
            raise

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def __del__(self):
        """Cleanup on deletion."""
        if self._session and not self._session.closed:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._session.close())
                else:
                    loop.run_until_complete(self._session.close())
            except Exception:
                pass


class LocalLLMPool:
    """
    Pool of local LLM instances for concurrent requests.
    Useful for high-frequency narration.
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        host: str = "http://localhost:11434",
        pool_size: int = 3,
    ):
        self.instances = [
            LocalLLM(model=model, host=host)
            for _ in range(pool_size)
        ]
        self._current = 0

    def get_instance(self) -> LocalLLM:
        """Get next available instance (round-robin)."""
        instance = self.instances[self._current]
        self._current = (self._current + 1) % len(self.instances)
        return instance

    async def generate(self, *args, **kwargs) -> str:
        """Generate using next available instance."""
        instance = self.get_instance()
        return await instance.generate(*args, **kwargs)

    async def close_all(self):
        """Close all instances."""
        for instance in self.instances:
            await instance.close()
