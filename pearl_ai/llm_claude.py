"""
Claude LLM Interface - Anthropic API Integration

Provides deep analysis, coaching, and complex reasoning capabilities.
Pearl AI 3.0: Added token extraction, streaming, and tool support.
"""

import asyncio
import logging
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, AsyncIterator, Callable
import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from Claude with metadata."""
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ClaudeLLM:
    """
    Interface to Claude via Anthropic API.

    Optimized for:
    - Complex "why" questions
    - Performance analysis and coaching
    - Pattern recognition
    - Strategy suggestions
    - Tool use for structured queries (3.0)
    """

    # Model options
    CLAUDE_SONNET = "claude-sonnet-4-20250514"
    CLAUDE_HAIKU = "claude-3-5-haiku-20241022"
    CLAUDE_OPUS = "claude-opus-4-20250514"

    def __init__(
        self,
        api_key: str,
        model: str = CLAUDE_SONNET,
        timeout: int = 60,
        max_retries: int = 2,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://api.anthropic.com/v1"
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with proper headers."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
        return self._session

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop_sequences: Optional[List[str]] = None,
    ) -> str:
        """
        Generate a response from Claude.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            stop_sequences: Optional stop sequences

        Returns:
            Generated text response
        """
        response = await self.generate_with_metadata(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            stop_sequences=stop_sequences,
        )
        return response.content

    async def generate_with_metadata(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop_sequences: Optional[List[str]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """
        Generate a response with full metadata including token counts.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            stop_sequences: Optional stop sequences
            tools: Optional list of tool definitions

        Returns:
            LLMResponse with content and metadata
        """
        messages = [{"role": "user", "content": prompt}]

        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }

        if system:
            payload["system"] = system

        if stop_sequences:
            payload["stop_sequences"] = stop_sequences

        if tools:
            payload["tools"] = tools

        for attempt in range(self.max_retries + 1):
            try:
                session = await self._get_session()
                async with session.post(
                    f"{self.base_url}/messages",
                    json=payload,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._parse_response(data)

                    elif resp.status == 429:
                        # Rate limited - wait and retry
                        retry_after = int(resp.headers.get("retry-after", 5))
                        logger.warning(f"Rate limited, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    elif resp.status >= 500:
                        # Server error - retry
                        logger.warning(f"Server error {resp.status}, retrying...")
                        await asyncio.sleep(2 ** attempt)
                        continue

                    else:
                        error = await resp.text()
                        logger.error(f"Claude API error {resp.status}: {error}")
                        raise RuntimeError(f"Claude API error: {resp.status}")

            except asyncio.TimeoutError:
                logger.warning(f"Request timeout, attempt {attempt + 1}")
                if attempt < self.max_retries:
                    continue
                raise

            except Exception as e:
                logger.error(f"Claude request error: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(1)
                    continue
                raise

        raise RuntimeError("Max retries exceeded")

    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        """Parse API response into LLMResponse."""
        content = ""
        tool_calls = []

        for block in data.get("content", []):
            if block.get("type") == "text":
                content = block.get("text", "").strip()
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input", {}),
                })

        # Extract usage
        usage = data.get("usage", {})

        return LLMResponse(
            content=content,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            stop_reason=data.get("stop_reason"),
            tool_calls=tool_calls if tool_calls else None,
            model=data.get("model", self.model),
        )

    async def generate_stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> AsyncIterator[str]:
        """
        Stream a response from Claude.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            on_chunk: Optional callback for each chunk

        Yields:
            Text chunks as they arrive
        """
        messages = [{"role": "user", "content": prompt}]

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        if system:
            payload["system"] = system

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/messages",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"Claude stream error: {error}")

                # Process SSE stream
                async for line in resp.content:
                    line_str = line.decode("utf-8").strip()

                    if not line_str or not line_str.startswith("data: "):
                        continue

                    json_str = line_str[6:]  # Remove "data: " prefix

                    if json_str == "[DONE]":
                        break

                    try:
                        event = json.loads(json_str)
                        event_type = event.get("type")

                        if event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    if on_chunk:
                                        on_chunk(text)
                                    yield text

                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            logger.error(f"Claude stream error: {e}")
            raise

    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tool_executor: Optional[Callable[[str, Dict], Any]] = None,
    ) -> LLMResponse:
        """
        Generate a response with tool use support.

        Args:
            prompt: The user prompt
            tools: List of tool definitions
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            tool_executor: Optional function to execute tools

        Returns:
            LLMResponse, potentially after tool execution
        """
        response = await self.generate_with_metadata(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
        )

        # If no tool calls, return directly
        if not response.tool_calls:
            return response

        # If tool executor provided, execute tools and continue conversation
        if tool_executor:
            return await self._execute_tool_loop(
                prompt=prompt,
                system=system,
                initial_response=response,
                tools=tools,
                tool_executor=tool_executor,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        return response

    async def _execute_tool_loop(
        self,
        prompt: str,
        system: Optional[str],
        initial_response: LLMResponse,
        tools: List[Dict[str, Any]],
        tool_executor: Callable[[str, Dict], Any],
        max_tokens: int,
        temperature: float,
        max_iterations: int = 3,
    ) -> LLMResponse:
        """
        Execute tool calls and continue conversation.

        Implements the tool use loop:
        1. Model requests tool use
        2. Execute tool, get result
        3. Send result back to model
        4. Model generates final response (or more tool calls)
        """
        messages = [{"role": "user", "content": prompt}]
        current_response = initial_response
        total_input_tokens = initial_response.input_tokens
        total_output_tokens = initial_response.output_tokens

        for iteration in range(max_iterations):
            if not current_response.tool_calls:
                break

            # Build assistant message with tool use
            assistant_content = []
            if current_response.content:
                assistant_content.append({
                    "type": "text",
                    "text": current_response.content,
                })

            for tool_call in current_response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tool_call["id"],
                    "name": tool_call["name"],
                    "input": tool_call["input"],
                })

            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tools and build tool_result message
            tool_results = []
            for tool_call in current_response.tool_calls:
                try:
                    result = tool_executor(tool_call["name"], tool_call["input"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call["id"],
                        "content": str(result) if not isinstance(result, str) else result,
                    })
                except Exception as e:
                    logger.error(f"Tool execution error: {e}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call["id"],
                        "content": f"Error: {e}",
                        "is_error": True,
                    })

            messages.append({"role": "user", "content": tool_results})

            # Continue conversation
            payload = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": messages,
                "temperature": temperature,
                "tools": tools,
            }

            if system:
                payload["system"] = system

            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/messages",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"Claude API error: {error}")

                data = await resp.json()
                current_response = self._parse_response(data)
                total_input_tokens += current_response.input_tokens
                total_output_tokens += current_response.output_tokens

        # Return final response with accumulated tokens
        return LLMResponse(
            content=current_response.content,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            stop_reason=current_response.stop_reason,
            tool_calls=current_response.tool_calls,
            model=current_response.model,
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        """
        Chat-style interface with message history.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated response
        """
        # Ensure messages alternate properly
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": formatted_messages,
            "temperature": temperature,
        }

        if system:
            payload["system"] = system

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/messages",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"Claude chat error: {error}")

                data = await resp.json()
                content = data.get("content", [])
                if content and content[0].get("type") == "text":
                    return content[0].get("text", "").strip()
                return ""

        except Exception as e:
            logger.error(f"Claude chat error: {e}")
            raise

    async def chat_with_metadata(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Chat with full metadata including token counts.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            LLMResponse with content and metadata
        """
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": formatted_messages,
            "temperature": temperature,
        }

        if system:
            payload["system"] = system

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/messages",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"Claude chat error: {error}")

                data = await resp.json()
                return self._parse_response(data)

        except Exception as e:
            logger.error(f"Claude chat error: {e}")
            raise

    async def analyze_trades(
        self,
        trades: List[Dict[str, Any]],
        question: Optional[str] = None,
    ) -> str:
        """
        Analyze a list of trades and provide insights.

        Args:
            trades: List of trade dictionaries
            question: Optional specific question about the trades

        Returns:
            Analysis text
        """
        system = """You are Pearl, an expert trading analyst and coach.
Analyze trading data to find patterns, mistakes, and opportunities for improvement.
Be specific with your observations. Reference actual trades when relevant.
Provide actionable suggestions, not generic advice."""

        # Format trades for analysis
        trade_summary = []
        for i, t in enumerate(trades[:20], 1):  # Limit to 20 trades
            trade_summary.append(
                f"{i}. {t.get('direction', '?').upper()} | "
                f"P&L: ${t.get('pnl', 0):+.2f} | "
                f"Exit: {t.get('exit_reason', '?')} | "
                f"ML: {t.get('ml_probability', 0) * 100:.0f}%"
            )

        prompt = f"""Analyze these recent trades:

{chr(10).join(trade_summary)}

Summary:
- Total Trades: {len(trades)}
- Winners: {sum(1 for t in trades if t.get('pnl', 0) > 0)}
- Losers: {sum(1 for t in trades if t.get('pnl', 0) < 0)}
- Total P&L: ${sum(t.get('pnl', 0) for t in trades):.2f}

{f'Specific Question: {question}' if question else 'Provide key observations and one actionable suggestion.'}"""

        return await self.generate(prompt, system=system, max_tokens=500)

    async def explain_decision(
        self,
        decision: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """
        Explain why a specific trading decision was made.

        Args:
            decision: The decision details (signal, action, reason)
            context: Market context at the time

        Returns:
            Explanation text
        """
        system = """You are Pearl, explaining trading decisions to your user.
Be clear and educational. Explain the logic, not just the outcome.
Connect the decision to the market context and trading rules."""

        prompt = f"""Explain this trading decision:

Action: {decision.get('action', 'unknown')}
Signal Type: {decision.get('signal_type', 'unknown')}
Reason: {decision.get('reason', 'none given')}
ML Probability: {decision.get('ml_probability', 0) * 100:.0f}%

Market Context:
- Regime: {context.get('regime', 'unknown')}
- Direction Allowed: {context.get('allowed_direction', 'both')}
- Recent Win Rate: {context.get('recent_win_rate', 'unknown')}

Explain in 2-3 sentences why this decision makes sense."""

        return await self.generate(prompt, system=system, max_tokens=200)

    async def generate_coaching(
        self,
        performance: Dict[str, Any],
        patterns: Dict[str, Any],
    ) -> str:
        """
        Generate personalized coaching based on performance and patterns.

        Args:
            performance: Trading performance metrics
            patterns: Observed behavioral patterns

        Returns:
            Coaching advice
        """
        system = """You are Pearl, a supportive but honest trading coach.
Acknowledge strengths while addressing weaknesses constructively.
Be specific and actionable. Reference the data provided.
Keep it brief - one main point with a clear action item."""

        prompt = f"""Generate brief coaching advice based on:

Performance:
- Win Rate: {performance.get('win_rate', 0) * 100:.0f}%
- Profit Factor: {performance.get('profit_factor', 0):.2f}
- Avg Win: ${performance.get('avg_win', 0):.2f}
- Avg Loss: ${performance.get('avg_loss', 0):.2f}
- Expectancy: ${performance.get('expectancy', 0):.2f}

Patterns Observed:
{chr(10).join(f'- {k}: {v}' for k, v in patterns.items())}

Provide ONE focused piece of coaching advice with a specific action step."""

        return await self.generate(prompt, system=system, max_tokens=200)

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
