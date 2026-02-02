"""
Mock LLM for Development and Testing (P3.1)

Provides deterministic responses for local development and CI testing
without requiring API keys or running Ollama.
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List, AsyncIterator, Callable

logger = logging.getLogger(__name__)


@dataclass
class MockLLMResponse:
    """Response from Mock LLM with metadata."""
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: Optional[str] = "end_turn"
    tool_calls: Optional[List[Dict[str, Any]]] = None
    model: str = "mock-llm"

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class MockResponse:
    """A canned response with pattern matching."""
    pattern: str  # Regex pattern to match
    response: str
    is_tool_call: bool = False
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None


class MockLLM:
    """
    Mock LLM for local development and testing.

    Features:
    - Deterministic responses based on pattern matching
    - Configurable canned responses
    - Simulated latency for realistic testing
    - Tool call simulation
    - No external dependencies

    Usage:
        mock = MockLLM()
        mock.add_response("pnl|profit", "Your current P&L is $150.00")
        response = await mock.generate("What's my PnL?")
    """

    # Default canned responses for common queries
    DEFAULT_RESPONSES: List[MockResponse] = [
        # Status queries
        MockResponse(
            pattern=r"status|running|active",
            response="The trading agent is currently running. No active positions."
        ),
        MockResponse(
            pattern=r"pnl|profit|loss|how.*doing",
            response="Today's P&L is $125.50 with 3 wins and 1 loss (75% win rate)."
        ),
        MockResponse(
            pattern=r"position|trade",
            response="No active positions currently. The last trade was a winning LONG exited at target."
        ),

        # Analysis queries
        MockResponse(
            pattern=r"why|explain|reason",
            response="The system rejected this signal due to unfavorable market regime. "
                    "We're currently in a ranging market with seller pressure, "
                    "which typically has lower win rates for LONG entries."
        ),
        MockResponse(
            pattern=r"performance|stats|metrics",
            response="Last 7 days: 15 trades with 60% win rate. "
                    "Total P&L: $425.00. Best hour: 10:00-11:00 AM."
        ),
        MockResponse(
            pattern=r"regime|market.*condition",
            response="Current market regime is 'ranging' with low volatility. "
                    "The system is favoring neutral to short setups."
        ),

        # Coaching queries
        MockResponse(
            pattern=r"advice|suggest|recommend|should",
            response="Based on your recent performance, I'd recommend waiting for "
                    "cleaner setups. You've been trading against the market flow "
                    "in the mornings - consider being more selective during that time."
        ),
        MockResponse(
            pattern=r"streak|consecutive",
            response="You're currently on a 2-trade winning streak. "
                    "Your longest streak this week was 4 wins."
        ),

        # Default fallback
        MockResponse(
            pattern=r".*",
            response="I'm Pearl, your trading assistant. I can help you understand "
                    "your trading performance, explain decisions, and provide coaching. "
                    "What would you like to know?"
        ),
    ]

    def __init__(
        self,
        model: str = "mock-llm",
        latency_ms: float = 50.0,
        latency_variance: float = 20.0,
        fail_rate: float = 0.0,
        custom_responses: Optional[List[MockResponse]] = None,
    ):
        """
        Initialize MockLLM.

        Args:
            model: Model name to report
            latency_ms: Base simulated latency in milliseconds
            latency_variance: Random variance added to latency
            fail_rate: Probability of simulated failures (0.0-1.0)
            custom_responses: Additional custom responses
        """
        self.model = model
        self.latency_ms = latency_ms
        self.latency_variance = latency_variance
        self.fail_rate = fail_rate
        self._available = True

        # Build response list (custom first, then defaults)
        self.responses: List[MockResponse] = []
        if custom_responses:
            self.responses.extend(custom_responses)
        self.responses.extend(self.DEFAULT_RESPONSES)

        # Request tracking for testing
        self.request_history: List[Dict[str, Any]] = []

    def add_response(
        self,
        pattern: str,
        response: str,
        is_tool_call: bool = False,
        tool_name: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a canned response with pattern matching."""
        self.responses.insert(0, MockResponse(
            pattern=pattern,
            response=response,
            is_tool_call=is_tool_call,
            tool_name=tool_name,
            tool_args=tool_args,
        ))

    def set_available(self, available: bool) -> None:
        """Set availability (for testing failure scenarios)."""
        self._available = available

    async def is_available(self) -> bool:
        """Check if mock is available."""
        return self._available

    async def _simulate_latency(self) -> None:
        """Simulate API latency."""
        latency = self.latency_ms + random.uniform(-self.latency_variance, self.latency_variance)
        await asyncio.sleep(max(0, latency) / 1000.0)

    def _find_response(self, prompt: str) -> MockResponse:
        """Find matching canned response."""
        prompt_lower = prompt.lower()
        for resp in self.responses:
            if re.search(resp.pattern, prompt_lower, re.IGNORECASE):
                return resp
        return self.responses[-1]  # Default fallback

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars per token)."""
        return len(text) // 4

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        stop: Optional[List[str]] = None,
    ) -> str:
        """Generate a mock response."""
        response = await self.generate_with_metadata(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.content

    async def generate_with_metadata(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> MockLLMResponse:
        """Generate a mock response with metadata."""
        # Track request
        self.request_history.append({
            "timestamp": datetime.now().isoformat(),
            "prompt": prompt,
            "system": system,
            "max_tokens": max_tokens,
        })

        # Simulate latency
        await self._simulate_latency()

        # Check for failures
        if not self._available:
            raise RuntimeError("MockLLM is unavailable")

        if random.random() < self.fail_rate:
            raise RuntimeError("Simulated random failure")

        # Find and return response
        matched = self._find_response(prompt)

        # Handle tool calls
        tool_calls = None
        if matched.is_tool_call and matched.tool_name:
            tool_calls = [{
                "id": f"tool_{random.randint(1000, 9999)}",
                "name": matched.tool_name,
                "input": matched.tool_args or {},
            }]

        return MockLLMResponse(
            content=matched.response,
            input_tokens=self._estimate_tokens(prompt + (system or "")),
            output_tokens=self._estimate_tokens(matched.response),
            tool_calls=tool_calls,
            model=self.model,
        )

    async def generate_stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> AsyncIterator[str]:
        """Stream a mock response word by word."""
        # Track request
        self.request_history.append({
            "timestamp": datetime.now().isoformat(),
            "prompt": prompt,
            "system": system,
            "streaming": True,
        })

        if not self._available:
            raise RuntimeError("MockLLM is unavailable")

        # Find response
        matched = self._find_response(prompt)
        words = matched.response.split()

        # Yield word by word
        for i, word in enumerate(words):
            # Add space between words
            chunk = word if i == 0 else " " + word
            await asyncio.sleep(0.01)  # Small delay between words

            if on_chunk:
                on_chunk(chunk)
            yield chunk

    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tool_executor: Optional[Callable[[str, Dict], Any]] = None,
    ) -> MockLLMResponse:
        """Generate with tool support."""
        response = await self.generate_with_metadata(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            tools=tools,
        )

        # Execute tools if provided
        if response.tool_calls and tool_executor:
            for tool_call in response.tool_calls:
                tool_executor(tool_call["name"], tool_call["input"])

        return response

    async def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 256,
        temperature: float = 0.7,
    ) -> str:
        """Chat interface - uses last user message."""
        last_user_msg = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        if last_user_msg:
            return await self.generate(last_user_msg, max_tokens=max_tokens)
        return "I didn't receive a message."

    def get_request_count(self) -> int:
        """Get total request count for testing."""
        return len(self.request_history)

    def get_last_request(self) -> Optional[Dict[str, Any]]:
        """Get the last request for testing."""
        if self.request_history:
            return self.request_history[-1]
        return None

    def clear_history(self) -> None:
        """Clear request history."""
        self.request_history.clear()

    async def close(self):
        """No-op for API compatibility."""
        pass


class MockClaudeLLM(MockLLM):
    """
    Claude-specific mock with tool-heavy responses.

    Useful for testing tool execution flows.
    """

    CLAUDE_RESPONSES: List[MockResponse] = [
        # Tool-calling responses
        MockResponse(
            pattern=r"performance.*regime|regime.*performance",
            response="Let me check your performance in that regime.",
            is_tool_call=True,
            tool_name="get_regime_performance",
            tool_args={"regime": "trending", "days": 30},
        ),
        MockResponse(
            pattern=r"similar.*trade|trade.*like",
            response="I'll find similar trades for you.",
            is_tool_call=True,
            tool_name="get_similar_trades",
            tool_args={"direction": "long", "limit": 5},
        ),
        MockResponse(
            pattern=r"hourly|time.*day|best.*time",
            response="Let me analyze your hourly performance.",
            is_tool_call=True,
            tool_name="get_hourly_performance",
            tool_args={"days": 30},
        ),
        MockResponse(
            pattern=r"reject|skip|block|why.*not",
            response="I'll explain the rejections.",
            is_tool_call=True,
            tool_name="explain_rejection",
            tool_args={},
        ),
    ]

    def __init__(self, **kwargs):
        super().__init__(model="mock-claude", **kwargs)
        # Add Claude-specific responses at the start
        self.responses = self.CLAUDE_RESPONSES + self.responses
