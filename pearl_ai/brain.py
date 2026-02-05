"""
Pearl Brain - The AI Orchestrator

Routes queries between local LLM (fast) and Claude (deep),
manages context, and triggers proactive messages.

Pearl AI 3.0: Integrated metrics, RAG, caching, and tool support.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable, Literal
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .memory import PearlMemory
from .narrator import PearlNarrator
from .llm_local import LocalLLM
from .llm_claude import ClaudeLLM, LLMResponse
from .metrics import MetricsCollector, LLMRequest, ToolCall, redact_tool_arguments
from .data_access import TradeDataAccess
from .cache import ResponseCache, RequestDeduplicator
from .tools import ToolExecutor, format_tool_result_for_llm, PEARL_TOOLS
from .config import get_config, PearlConfig
from .types import SanitizationResult, TradingContextSummary, ChatResponseDict, NarrationOutputDict

logger = logging.getLogger(__name__)


class QueryComplexity(Enum):
    """Determines which LLM to use"""
    QUICK = "quick"      # Local LLM - simple narration, state summary
    DEEP = "deep"        # Claude - analysis, coaching, complex why
    AUTO = "auto"        # Let brain decide


class ResponseSource(Enum):
    """Indicates where a response came from"""
    CACHE = "cache"
    LOCAL = "local"
    CLAUDE = "claude"
    TEMPLATE = "template"


@dataclass
class PearlMessage:
    """A message from Pearl AI"""
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    message_type: Literal["narration", "insight", "alert", "coaching", "response"] = "narration"
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    related_trade_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "type": self.message_type,
            "priority": self.priority,
            "trade_id": self.related_trade_id,
            "metadata": self.metadata,
        }


class PearlBrain:
    """
    The central AI orchestrator for Pearl.

    Responsibilities:
    - Route queries to appropriate LLM (local vs Claude)
    - Maintain conversation context
    - Trigger proactive messages based on events
    - Learn user preferences over time
    - Track metrics and costs (3.0)
    - Ground responses with trade history (3.0)
    - Cache responses to reduce API calls (3.0)
    - Use tools for structured queries (3.0)
    """

    def __init__(
        self,
        claude_api_key: Optional[str] = None,
        ollama_model: Optional[str] = None,
        ollama_host: Optional[str] = None,
        enable_local: bool = True,
        enable_claude: bool = True,
        trade_db_path: Optional[str] = None,
        enable_tools: bool = True,
        enable_caching: bool = True,
        daily_cost_limit: Optional[float] = None,
    ):
        # Load configuration
        self._config = get_config()

        self.memory = PearlMemory()
        self.narrator = PearlNarrator()

        # Initialize LLMs
        self.local_llm: Optional[LocalLLM] = None
        self.claude_llm: Optional[ClaudeLLM] = None

        resolved_ollama_model = ollama_model or self._config.llm.DEFAULT_LOCAL_MODEL
        resolved_ollama_host = ollama_host or self._config.llm.DEFAULT_OLLAMA_HOST

        if enable_local:
            self.local_llm = LocalLLM(model=resolved_ollama_model, host=resolved_ollama_host)

        if enable_claude and claude_api_key:
            self.claude_llm = ClaudeLLM(api_key=claude_api_key)

        # Pearl AI 3.0: Metrics, RAG, Caching, Tools
        metrics_path = Path.home() / ".pearl" / "metrics"
        self.metrics = MetricsCollector(
            max_history=self._config.metrics.MAX_HISTORY,
            storage_path=metrics_path,
            daily_cost_limit=daily_cost_limit,
            persistence_frequency=self._config.metrics.PERSISTENCE_FREQUENCY,
            cost_warning_threshold=self._config.metrics.COST_WARNING_THRESHOLD,
        )

        self.data_access = TradeDataAccess(db_path=trade_db_path)
        self.cache = ResponseCache(max_size=self._config.cache.MAX_SIZE) if enable_caching else None

        # Tool executor
        self.enable_tools = enable_tools
        self.tool_executor = ToolExecutor(
            data_access=self.data_access,
            current_state_getter=lambda: self._current_state,
            rejection_explainer=self.explain_rejections,
        )

        # Message handlers (callbacks for sending messages to UI)
        self._message_handlers: List[Callable[[PearlMessage], None]] = []

        # Current trading context
        self._current_state: Dict[str, Any] = {}
        self._last_narration_time: Optional[datetime] = None

        # Configuration
        self.narration_cooldown = timedelta(seconds=self._config.narration.NARRATION_COOLDOWN)
        self.always_narrate_events = set(self._config.narration.ALWAYS_NARRATE_EVENTS)

        # Proactive engagement tracking
        self._last_insight_time: Optional[datetime] = None
        self._last_ml_warning_time: Optional[datetime] = None
        self._last_coaching_time: Optional[datetime] = None
        self._last_quiet_engagement_time: Optional[datetime] = None
        self._last_signal_time: Optional[datetime] = None

        # Response source tracking (P5.1)
        self._last_response_source: Optional["ResponseSource"] = None

        # Eval instrumentation - tracks details of last response for debugging/testing
        self._last_routing: str = "unknown"
        self._last_model: str = "unknown"
        self._last_tool_calls: List[Dict[str, Any]] = []
        self._last_tool_results: List[Dict[str, Any]] = []
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0
        self._last_latency_ms: float = 0.0
        self._last_cache_hit: bool = False
        self._last_fallback_used: bool = False

        # Cooldowns for proactive messages
        self.insight_cooldown = timedelta(seconds=self._config.narration.INSIGHT_COOLDOWN)
        self.ml_warning_cooldown = timedelta(seconds=self._config.narration.ML_WARNING_COOLDOWN)
        self.coaching_cooldown = timedelta(seconds=self._config.narration.COACHING_COOLDOWN)
        self.quiet_engagement_threshold = timedelta(seconds=self._config.narration.QUIET_ENGAGEMENT_THRESHOLD)

        # Request deduplication (P3.1)
        self.request_deduplicator: Optional[RequestDeduplicator] = None
        self._dedupe_key_builder: Optional[ResponseCache] = None
        if self._config.cache.DEDUP_ENABLED:
            self.request_deduplicator = RequestDeduplicator(
                window_ms=self._config.cache.DEDUP_WINDOW_MS
            )
            self._dedupe_key_builder = self.cache or ResponseCache(
                max_size=self._config.cache.MAX_SIZE
            )

        logger.info(f"Pearl Brain 3.0 initialized - Local: {enable_local}, Claude: {enable_claude}, "
                   f"Tools: {enable_tools}, Caching: {enable_caching}")

    def _sanitize_input(self, user_message: str) -> SanitizationResult:
        """
        Sanitize user input to prevent prompt injection attacks.

        Args:
            user_message: Raw user message

        Returns:
            SanitizationResult with sanitized message and warnings
        """
        config = self._config.sanitization
        warnings: List[str] = []
        was_modified = False
        sanitized = user_message

        # Enforce length limit
        if len(sanitized) > config.MAX_MESSAGE_LENGTH:
            sanitized = sanitized[:config.MAX_MESSAGE_LENGTH]
            warnings.append(f"Message truncated to {config.MAX_MESSAGE_LENGTH} characters")
            was_modified = True

        # Strip injection markers
        for pattern in config.INJECTION_PATTERNS:
            if pattern.lower() in sanitized.lower():
                # Case-insensitive replacement
                import re
                sanitized = re.sub(re.escape(pattern), "", sanitized, flags=re.IGNORECASE)
                was_modified = True
                logger.warning(f"Stripped injection pattern: {pattern}")

        # Check for suspicious patterns (log but don't remove)
        message_lower = sanitized.lower()
        for pattern in config.SUSPICIOUS_PATTERNS:
            if pattern in message_lower:
                warnings.append(f"Suspicious pattern detected: {pattern}")
                logger.warning(f"Suspicious input pattern: {pattern}")

        # Clean up excessive whitespace
        import re
        cleaned = re.sub(r'\s+', ' ', sanitized).strip()
        if cleaned != sanitized:
            sanitized = cleaned
            was_modified = True

        return SanitizationResult(
            sanitized=sanitized,
            was_modified=was_modified,
            warnings=warnings,
        )

    def add_message_handler(self, handler: Callable[[PearlMessage], None]):
        """Register a callback for when Pearl has something to say"""
        self._message_handlers.append(handler)

    async def _emit_message(self, message: PearlMessage):
        """Send message to all registered handlers"""
        for handler in self._message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.error(f"Error in message handler: {e}")

        # Store in memory
        self.memory.add_message(message)

    def update_state(self, state: Dict[str, Any]):
        """Update Pearl's knowledge of current trading state"""
        old_state = self._current_state
        self._current_state = state

        # Track signal time for quiet period detection
        if state.get("last_signal_time"):
            self._last_signal_time = datetime.now()

        # Detect significant changes and narrate
        asyncio.create_task(self._check_state_changes(old_state, state))

        # Run proactive checks
        asyncio.create_task(self._run_proactive_checks(old_state, state))

    async def _check_state_changes(self, old: Dict, new: Dict):
        """Detect and narrate significant state changes"""

        # Check for new trades
        old_trades = old.get("active_trades_count", 0)
        new_trades = new.get("active_trades_count", 0)

        if new_trades > old_trades:
            await self.narrate_event("trade_entered", {
                "count": new_trades,
                "direction": new.get("last_trade_direction"),
                "entry_price": new.get("last_entry_price"),
            })
        elif new_trades < old_trades:
            # Trade closed
            recent_exit = new.get("recent_exits", [{}])[0] if new.get("recent_exits") else {}
            await self.narrate_event("trade_exited", {
                "pnl": recent_exit.get("pnl"),
                "exit_reason": recent_exit.get("exit_reason"),
                "direction": recent_exit.get("direction"),
            })

        # Check for signal rejections
        old_rejections = old.get("signal_rejections_24h", {})
        new_rejections = new.get("signal_rejections_24h", {})

        for reason, count in new_rejections.items() if isinstance(new_rejections, dict) else []:
            old_count = old_rejections.get(reason, 0) if isinstance(old_rejections, dict) else 0
            if count > old_count:
                await self.narrate_event("signal_rejected", {
                    "reason": reason,
                    "total_today": count,
                })

        # Check circuit breaker
        old_cb = old.get("circuit_breaker", {})
        new_cb = new.get("circuit_breaker", {})

        if new_cb.get("in_cooldown") and not old_cb.get("in_cooldown"):
            await self.narrate_event("circuit_breaker_triggered", {
                "reason": new_cb.get("trip_reason"),
                "cooldown_seconds": new_cb.get("cooldown_remaining_seconds"),
            })

    async def narrate_event(self, event_type: str, context: Dict[str, Any]):
        """
        Generate a natural language narration for an event.
        Uses local LLM for speed.
        """
        # Check cooldown (unless critical event)
        if event_type not in self.always_narrate_events:
            if self._last_narration_time:
                elapsed = datetime.now() - self._last_narration_time
                if elapsed < self.narration_cooldown:
                    return

        # Generate narration
        start_time = time.time()
        narration = await self._generate_narration(event_type, context)
        latency_ms = (time.time() - start_time) * 1000

        if narration:
            # Provide expanded details for dropdown/expanded UI without affecting the 1-line headline.
            details = self.narrator.build_narration_details(event_type, context, self._current_state)
            metadata = {"event_type": event_type, **context}
            metadata["headline"] = narration
            metadata["details"] = details

            message = PearlMessage(
                content=narration,
                message_type="narration",
                priority="high" if event_type in self.always_narrate_events else "normal",
                related_trade_id=context.get("signal_id"),
                metadata=metadata,
            )
            await self._emit_message(message)
            self._last_narration_time = datetime.now()

            # Record metrics for narration
            self.metrics.record(LLMRequest(
                timestamp=datetime.now(),
                endpoint="narration",
                model=self.local_llm.model if self.local_llm else "template",
                input_tokens=len(str(context)) // 4,  # Estimate
                output_tokens=len(narration) // 4,
                latency_ms=latency_ms,
                success=True,
            ))

    async def _generate_narration(self, event_type: str, context: Dict[str, Any]) -> str:
        """Generate narration using local LLM"""

        # Build the prompt
        prompt = self.narrator.build_narration_prompt(event_type, context, self._current_state)

        # Use local LLM for speed
        if self.local_llm and await self.local_llm.is_available():
            try:
                response = await self.local_llm.generate(
                    prompt,
                    system="You are Pearl, an AI trading assistant. "
                           "CRITICAL: Output EXACTLY 1 sentence only. "
                           "Never exceed 25 words total. Be extremely concise. "
                           "State facts directly without elaboration.",
                    max_tokens=self._config.llm.MAX_NARRATION_TOKENS,
                )
                # Strip quotes if LLM wrapped the response
                response = response.strip().strip('"').strip("'")
                return self._clamp_narration(event_type, response)
            except Exception as e:
                logger.error(f"Local LLM error: {e}")

        # Fallback to template-based narration
        return self._clamp_narration(
            event_type,
            self.narrator.template_narration(event_type, context, self._current_state),
        )

    def _clamp_narration(self, event_type: str, text: str) -> str:
        """
        Enforce brevity constraints for narrations.

        Many narrator prompts specify EXACTLY 1 sentence; this post-process ensures
        we don't emit multi-sentence outputs due to model variance.
        """
        if not text:
            return text

        # Only clamp the high-frequency narration/event outputs.
        clamp_one_sentence = event_type in {
            "trade_entered",
            "trade_exited",
            "signal_generated",
            "signal_rejected",
            "circuit_breaker_triggered",
            "direction_blocked",
        }
        if not clamp_one_sentence:
            return text.strip()

        import re

        # Avoid splitting on decimal points in numbers (e.g., "$45.50").
        safe = re.sub(r"(?<=\d)\.(?=\d)", "<DECIMAL>", text.strip())
        parts = re.split(r"[.!?]+", safe)
        parts = [p.strip() for p in parts if p.strip()]
        if not parts:
            return text.strip()

        first = parts[0].replace("<DECIMAL>", ".").strip()
        # Ensure it ends like a sentence.
        if not re.search(r"[.!?]$", first):
            first += "."
        return first

    async def narrate(self, event_type: str, context: Dict[str, Any]) -> str:
        """
        Generate a narration for an event (eval-friendly wrapper).

        This is a simplified interface for the eval framework that returns
        just the narration text without emitting messages.

        Args:
            event_type: Type of event (trade_entered, trade_exited, etc.)
            context: Event context dict

        Returns:
            Generated narration text
        """
        return await self._generate_narration(event_type, context)

    async def narrate_rich(self, event_type: str, context: Dict[str, Any]) -> NarrationOutputDict:
        """
        Generate narration headline + expanded details (UI-friendly).

        Returns:
            Dict with:
            - headline: 1-sentence narration suitable for header/notification
            - details: structured + text details for expanded view
        """
        headline = await self._generate_narration(event_type, context)
        details = self.narrator.build_narration_details(event_type, context, self._current_state)
        return {"headline": headline, "details": details}

    async def chat(
        self,
        user_message: str,
        complexity: QueryComplexity = QueryComplexity.AUTO,
    ) -> str:
        """
        Handle a chat message from the user.
        Routes to appropriate LLM based on complexity.
        """
        start_time = time.time()

        # Sanitize input (P1.1: Input sanitization layer)
        sanitization_result = self._sanitize_input(user_message)
        sanitized_message = sanitization_result["sanitized"]

        if sanitization_result["warnings"]:
            logger.info(f"Input sanitization warnings: {sanitization_result['warnings']}")

        # Add to memory (use sanitized message)
        self.memory.add_user_message(sanitized_message)

        # Track response source for transparency (P5.1)
        response_source = ResponseSource.TEMPLATE

        # Reset eval instrumentation for this request
        self._last_tool_calls = []
        self._last_tool_results = []

        # Check cache first (3.0)
        if self.cache:
            cached = self.cache.get(sanitized_message, self._current_state)
            if cached:
                cache_latency = (time.time() - start_time) * 1000
                self.metrics.record(LLMRequest(
                    timestamp=datetime.now(),
                    endpoint="chat",
                    model="cache",
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=cache_latency,
                    cache_hit=True,
                    success=True,
                ))
                self.memory.add_assistant_message(cached)
                self._last_response_source = ResponseSource.CACHE
                # Update eval instrumentation for cache hit
                routed = complexity
                if routed == QueryComplexity.AUTO:
                    routed = self._classify_query(sanitized_message)
                self._last_routing = routed.value
                self._last_model = "cache"
                self._last_input_tokens = 0
                self._last_output_tokens = 0
                self._last_latency_ms = cache_latency
                self._last_cache_hit = True
                self._last_fallback_used = False
                return cached

        # Determine complexity if auto
        if complexity == QueryComplexity.AUTO:
            complexity = self._classify_query(sanitized_message)

        # Build context with RAG (3.0)
        context = self._build_chat_context(sanitized_message)

        # Get relevant trade history for RAG
        rag_context = self._get_rag_context(sanitized_message)
        if rag_context:
            context["trade_history"] = rag_context

        # Route to appropriate LLM
        response = ""
        input_tokens = 0
        output_tokens = 0
        model_used = "template"
        fallback_used = False

        if complexity == QueryComplexity.QUICK and self.local_llm:
            response = await self._quick_response(sanitized_message, context)
            model_used = self.local_llm.model
            response_source = ResponseSource.LOCAL
        elif self.claude_llm:
            async def generate_deep_response() -> tuple[str, int, int]:
                # Try with tools if enabled (3.0)
                if self.enable_tools:
                    return await self._deep_response_with_tools(sanitized_message, context)
                return await self._deep_response_with_metadata(sanitized_message, context)

            if self.request_deduplicator and self._dedupe_key_builder:
                dedupe_key = self._dedupe_key_builder.build_key(sanitized_message, self._current_state)
                shared, result = await self.request_deduplicator.dedupe(dedupe_key, generate_deep_response)
                response, input_tokens, output_tokens = result
                if shared:
                    self.metrics.record_dedupe_hit(self.claude_llm.model, input_tokens, output_tokens)
            else:
                response, input_tokens, output_tokens = await generate_deep_response()
            model_used = self.claude_llm.model
            response_source = ResponseSource.CLAUDE
        elif self.local_llm:
            response = await self._quick_response(sanitized_message, context)
            model_used = self.local_llm.model
            response_source = ResponseSource.LOCAL
            fallback_used = True
        else:
            response = "I'm having trouble connecting to my AI backend. Please check the configuration."
            response_source = ResponseSource.TEMPLATE

        latency_ms = (time.time() - start_time) * 1000

        # Store last response source for API (P5.1)
        self._last_response_source = response_source

        # Update eval instrumentation
        self._last_routing = complexity.value if complexity != QueryComplexity.AUTO else "auto"
        self._last_model = model_used
        self._last_input_tokens = input_tokens
        self._last_output_tokens = output_tokens
        self._last_latency_ms = latency_ms
        self._last_cache_hit = False
        self._last_fallback_used = fallback_used

        tool_call_metrics = self._build_tool_call_metrics()

        # Record metrics (3.0)
        self.metrics.record(LLMRequest(
            timestamp=datetime.now(),
            endpoint="chat",
            model=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cache_hit=False,
            success=bool(response),
            fallback_used=fallback_used,
            tool_calls=tool_call_metrics,
        ))

        # Cache response (3.0)
        if self.cache and response:
            self.cache.set(user_message, self._current_state, response)

        # Store response
        self.memory.add_assistant_message(response)

        # Emit as message
        await self._emit_message(PearlMessage(
            content=response,
            message_type="response",
            priority="normal",
        ))

        return response

    def get_last_debug_info(self) -> Dict[str, Any]:
        """
        Get debug information from the last chat/narration call.

        Used by eval framework to inspect what happened during response generation.

        Returns:
            Dict with routing, model, tool calls, tokens, latency, etc.
        """
        return {
            "routing": self._last_routing,
            "model_used": self._last_model,
            "tool_calls": self._last_tool_calls.copy(),
            "tool_results": self._last_tool_results.copy(),
            "input_tokens": self._last_input_tokens,
            "output_tokens": self._last_output_tokens,
            "latency_ms": self._last_latency_ms,
            "cache_hit": self._last_cache_hit,
            "fallback_used": self._last_fallback_used,
            "response_source": self._last_response_source.value if self._last_response_source else None,
        }

    def _build_tool_call_metrics(self) -> Optional[List[ToolCall]]:
        """Build redacted tool call metrics from the last tool run."""
        if not self._last_tool_calls:
            return None

        tool_calls: List[ToolCall] = []
        for index, call in enumerate(self._last_tool_calls):
            result = self._last_tool_results[index] if index < len(self._last_tool_results) else {}
            success = bool(result.get("success", False))
            error = result.get("error")
            latency_ms = float(result.get("latency_ms", 0.0))

            tool_calls.append(
                ToolCall(
                    name=call.get("name", "unknown"),
                    arguments=redact_tool_arguments(call.get("input", {})),
                    success=success,
                    latency_ms=latency_ms,
                    error=error,
                )
            )

        return tool_calls

    async def chat_with_debug(
        self,
        user_message: str,
        complexity: QueryComplexity = QueryComplexity.AUTO,
        state: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """
        Chat with debug info returned.

        Convenience method for eval framework that returns both response
        and debug info in a single call.

        Args:
            user_message: The user's message
            complexity: Query complexity hint
            state: Optional state to use (overrides current state)

        Returns:
            Tuple of (response, debug_info)
        """
        # Optionally set state for this request
        if state is not None:
            self._current_state = state

        # Get response
        response = await self.chat(user_message, complexity)

        # Return with debug info
        return response, self.get_last_debug_info()

    def _get_rag_context(self, query: str) -> str:
        """Get relevant trade data for RAG based on query."""
        if not self.data_access.is_available():
            return ""

        return self.data_access.format_for_context(query, self._current_state)

    def _classify_query(self, query: str) -> QueryComplexity:
        """Determine if query needs local (quick) or Claude (deep) response"""
        config = self._config.query_classification

        query_lower = query.lower()

        for keyword in config.DEEP_KEYWORDS:
            if keyword in query_lower:
                return QueryComplexity.DEEP

        # Quick queries
        for keyword in config.QUICK_KEYWORDS:
            if keyword in query_lower:
                return QueryComplexity.QUICK

        # Default to quick for short queries, deep for longer
        return QueryComplexity.QUICK if len(query.split()) < config.WORD_COUNT_THRESHOLD else QueryComplexity.DEEP

    def _build_chat_context(self, query: str) -> Dict[str, Any]:
        """Build context for the chat response"""
        return {
            "current_state": self._current_state,
            "recent_messages": self.memory.get_recent_messages(10),
            "user_patterns": self.memory.get_user_patterns(),
            "query": query,
        }

    async def _quick_response(self, query: str, context: Dict[str, Any]) -> str:
        """Generate quick response using local LLM"""

        system_prompt = f"""You are Pearl, an AI trading assistant for algorithmic trading.
You have access to real-time trading data. Be concise, direct, and helpful.
Answer questions about current trades, positions, and market state.
Use the provided context to give accurate information.

{self._voice_style_instructions()}"""

        user_prompt = f"""Current Trading State:
- Daily P&L: ${context['current_state'].get('daily_pnl', 0):.2f}
- Active Positions: {context['current_state'].get('active_trades_count', 0)}
- Win/Loss Today: {context['current_state'].get('daily_wins', 0)}/{context['current_state'].get('daily_losses', 0)}
- Market Regime: {context['current_state'].get('market_regime', {}).get('regime', 'unknown')}
- Agent Status: {'Running' if context['current_state'].get('running') else 'Stopped'}

User Question: {query}

Respond naturally and concisely:"""

        if self.local_llm and await self.local_llm.is_available():
            try:
                return await self.local_llm.generate(
                    user_prompt,
                    system=system_prompt,
                    max_tokens=self._config.llm.MAX_QUICK_RESPONSE_TOKENS,
                )
            except Exception as e:
                logger.error(f"Local LLM error: {e}")

        return self._fallback_response(query, context)

    async def _deep_response_with_tools(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> tuple[str, int, int]:
        """Generate deep response with tool support (3.0)"""

        system_prompt = self._build_deep_system_prompt(context)
        user_prompt = self._build_deep_user_prompt(query, context)

        if not self.claude_llm:
            response = await self._quick_response(query, context)
            return response, 0, 0

        try:
            # Get tool definitions
            tools = self.tool_executor.get_tool_definitions()

            # Define tool executor wrapper that tracks calls for eval instrumentation
            def execute_tool(name: str, args: Dict) -> str:
                # Track the tool call
                self._last_tool_calls.append({
                    "name": name,
                    "input": args,
                })
                # Execute the tool with latency tracking
                start_tool = time.time()
                result = self.tool_executor.execute(name, args)
                latency_ms = (time.time() - start_tool) * 1000
                # Track the result
                self._last_tool_results.append({
                    "name": name,
                    "success": result.success,
                    "data": result.data if result.success else None,
                    "error": result.error,
                    "latency_ms": latency_ms,
                })
                return format_tool_result_for_llm(name, result)

            # Generate with tools
            llm_response = await self.claude_llm.generate_with_tools(
                prompt=user_prompt,
                tools=tools,
                system=system_prompt,
                max_tokens=self._config.llm.MAX_DEEP_RESPONSE_TOKENS,
                tool_executor=execute_tool,
            )

            return llm_response.content, llm_response.input_tokens, llm_response.output_tokens

        except Exception as e:
            logger.error(f"Claude error with tools: {e}")

            # Fallback to without tools
            try:
                response, input_tokens, output_tokens = await self._deep_response_with_metadata(query, context)
                return response, input_tokens, output_tokens
            except Exception as e2:
                logger.error(f"Claude fallback error: {e2}")

        # Final fallback to local
        if self.local_llm and await self.local_llm.is_available():
            return await self._quick_response(query, context), 0, 0

        return self._fallback_response(query, context), 0, 0

    async def _deep_response_with_metadata(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> tuple[str, int, int]:
        """Generate deep response with metadata tracking"""

        system_prompt = self._build_deep_system_prompt(context)
        user_prompt = self._build_deep_user_prompt(query, context)

        if not self.claude_llm:
            response = await self._quick_response(query, context)
            return response, 0, 0

        try:
            llm_response = await self.claude_llm.generate_with_metadata(
                prompt=user_prompt,
                system=system_prompt,
                max_tokens=self._config.llm.MAX_DEEP_RESPONSE_TOKENS,
            )
            return llm_response.content, llm_response.input_tokens, llm_response.output_tokens

        except Exception as e:
            logger.error(f"Claude error: {e}")

        # Fallback to local if Claude unavailable
        if self.local_llm and await self.local_llm.is_available():
            return await self._quick_response(query, context), 0, 0

        return self._fallback_response(query, context), 0, 0

    def _build_deep_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build system prompt for deep responses"""
        base_prompt = """You are Pearl, an advanced AI trading coach and analyst.
You help traders understand their performance, identify patterns, and improve their strategy.

Your capabilities:
- Analyze trading patterns and performance
- Explain why specific trades were taken or rejected
- Provide coaching based on historical data
- Suggest strategy improvements
- Identify psychological patterns (overtrading, revenge trading, etc.)

Be insightful, specific, and actionable. Use data to support your observations.
Speak naturally, like a calm, capable operator and trading mentor.

Response structure:
- Start with a 1-line Status.
- Then 3-6 bullets (Observations).
- Then Next steps (1-3 bullets).
- If you are uncertain, say what’s missing and what you’d check next.
"""

        voice = self._voice_style_instructions()
        if voice:
            base_prompt += f"\n\n{voice}"

        # Add personality context if available
        personality = self.memory.get_personality_context()
        if personality:
            base_prompt += f"\n\nUser Context: {personality}"

        return base_prompt

    def _voice_style_instructions(self) -> str:
        """
        Voice/style guidance for LLM outputs.

        Jarvis-inspired = crisp, composed, lightly witty, but always accurate.
        """
        voice = (os.getenv("PEARL_AI_VOICE") or "jarvis").strip().lower()
        if voice in ("neutral", "default", "none"):
            return ""

        if voice in ("jarvis", "ops", "steward"):
            return (
                "Voice & tone:\n"
                "- Crisp, composed, quietly confident.\n"
                "- Understated wit is allowed, but never at the expense of clarity.\n"
                "- Do NOT reference Iron Man, JARVIS, Tony Stark, or movies.\n"
                "- You may address the operator as \"sir\" sparingly; avoid other pet names.\n"
                "- Prefer short paragraphs and bullet lists.\n"
                "- Never claim you executed trades or controls. You only observe and advise.\n"
                "- If you can’t verify something from data, say so plainly.\n"
            )

        custom = (os.getenv("PEARL_AI_VOICE_INSTRUCTIONS") or "").strip()
        if custom:
            return f"Voice & tone:\n{custom}"
        return ""

    def _build_deep_user_prompt(self, query: str, context: Dict[str, Any]) -> str:
        """Build user prompt for deep responses"""
        state = context['current_state']
        recent_trades = state.get('recent_exits', [])[:10]

        prompt = f"""# Current Session
- Daily P&L: ${state.get('daily_pnl', 0):.2f}
- Trades: {state.get('daily_trades', 0)} ({state.get('daily_wins', 0)}W / {state.get('daily_losses', 0)}L)
- Active Positions: {state.get('active_trades_count', 0)}
- Win Rate: {state.get('daily_wins', 0) / max(state.get('daily_trades', 1), 1) * 100:.0f}%

# Market Context
- Regime: {state.get('market_regime', {}).get('regime', 'unknown')}
- Direction Allowed: {state.get('market_regime', {}).get('allowed_direction', 'both')}

# Risk Metrics
- Expectancy: ${state.get('risk_metrics', {}).get('expectancy', 0):.2f}
- Sharpe Ratio: {state.get('risk_metrics', {}).get('sharpe_ratio', 'N/A')}
- Max Drawdown: ${state.get('risk_metrics', {}).get('max_drawdown', 0):.2f}

# Recent Trades
{self._format_recent_trades(recent_trades)}

# AI Status
- ML Filter: {state.get('ai_status', {}).get('ml_filter', {}).get('mode', 'off')}
- Direction Gating Blocks: {state.get('ai_status', {}).get('direction_gating', {}).get('blocks', 0)}

# Signal Rejections (24h)
{self._format_rejections(state.get('signal_rejections_24h', {}))}"""

        # Add RAG context if available
        trade_history = context.get('trade_history', '')
        if trade_history:
            prompt += f"\n\n# Historical Trade Data\n{trade_history}"

        prompt += f"\n\n---\n\nUser Question: {query}\n\nProvide a thoughtful, data-driven response:"

        return prompt

    async def _deep_response(self, query: str, context: Dict[str, Any]) -> str:
        """Generate deep analytical response using Claude (legacy interface)"""
        response, _, _ = await self._deep_response_with_metadata(query, context)
        return response

    def _format_recent_trades(self, trades: List[Dict]) -> str:
        """Format recent trades for context"""
        if not trades:
            return "No recent trades"

        lines = []
        for t in trades[:5]:
            pnl = t.get('pnl', 0)
            direction = t.get('direction', '?')
            reason = t.get('exit_reason', 'unknown')
            lines.append(f"- {direction.upper()}: ${pnl:+.2f} ({reason})")

        return "\n".join(lines)

    def _format_rejections(self, rejections: Dict) -> str:
        """Format signal rejections for context"""
        if not rejections or not isinstance(rejections, dict):
            return "No rejections"

        lines = []
        for reason, count in rejections.items():
            if count > 0:
                lines.append(f"- {reason.replace('_', ' ').title()}: {count}")

        return "\n".join(lines) if lines else "No rejections"

    def _fallback_response(self, query: str, context: Dict[str, Any]) -> str:
        """Template-based fallback when LLMs unavailable"""
        state = context['current_state']

        query_lower = query.lower()

        if "pnl" in query_lower or "profit" in query_lower:
            pnl = state.get('daily_pnl', 0)
            return f"Today's P&L is ${pnl:+.2f} with {state.get('daily_wins', 0)} wins and {state.get('daily_losses', 0)} losses."

        if "position" in query_lower:
            count = state.get('active_trades_count', 0)
            if count == 0:
                return "No active positions currently."
            return f"You have {count} active position(s)."

        if "status" in query_lower:
            running = state.get('running', False)
            return f"The trading agent is {'running' if running else 'stopped'}."

        return "I'm having trouble processing that request. My AI backend may be unavailable."

    async def generate_insight(self) -> Optional[PearlMessage]:
        """
        Generate a proactive insight based on current state.
        Called periodically to provide coaching/observations.
        """

        if not self.claude_llm:
            return None

        # Only generate insights occasionally
        recent_insights = self.memory.get_messages_by_type("insight", limit=5)
        if recent_insights:
            last_insight_time = recent_insights[0].timestamp
            if datetime.now() - last_insight_time < self.insight_cooldown:
                return None

        start_time = time.time()

        # Generate insight using Claude
        state = self._current_state

        prompt = f"""Based on this trading session, provide ONE brief, actionable insight:

Daily P&L: ${state.get('daily_pnl', 0):.2f}
Trades: {state.get('daily_wins', 0)}W / {state.get('daily_losses', 0)}L
Win Rate: {state.get('daily_wins', 0) / max(state.get('daily_trades', 1), 1) * 100:.0f}%
Regime: {state.get('market_regime', {}).get('regime', 'unknown')}
Rejections: {sum(state.get('signal_rejections_24h', {}).values()) if isinstance(state.get('signal_rejections_24h'), dict) else 0}

Give a brief (1-2 sentence) observation or suggestion. Be specific and actionable."""

        try:
            llm_response = await self.claude_llm.generate_with_metadata(
                prompt,
                system="You are Pearl, a trading coach. Give brief, actionable insights.",
                max_tokens=self._config.llm.MAX_INSIGHT_TOKENS,
            )
            insight = llm_response.content
            latency_ms = (time.time() - start_time) * 1000

            # Record metrics
            self.metrics.record(LLMRequest(
                timestamp=datetime.now(),
                endpoint="insight",
                model=self.claude_llm.model,
                input_tokens=llm_response.input_tokens,
                output_tokens=llm_response.output_tokens,
                latency_ms=latency_ms,
                success=True,
            ))

            if insight:
                message = PearlMessage(
                    content=insight,
                    message_type="insight",
                    priority="normal",
                )
                await self._emit_message(message)
                return message

        except Exception as e:
            logger.error(f"Error generating insight: {e}")

        return None

    async def daily_review(self) -> Optional[PearlMessage]:
        """Generate end-of-day performance review"""

        if not self.claude_llm:
            return None

        start_time = time.time()
        state = self._current_state

        prompt = f"""Generate a brief end-of-day trading review:

# Today's Results
- P&L: ${state.get('daily_pnl', 0):.2f}
- Trades: {state.get('daily_trades', 0)}
- Wins: {state.get('daily_wins', 0)}
- Losses: {state.get('daily_losses', 0)}
- Win Rate: {state.get('daily_wins', 0) / max(state.get('daily_trades', 1), 1) * 100:.0f}%

# Risk Metrics
- Expectancy: ${state.get('risk_metrics', {}).get('expectancy', 0):.2f}
- Largest Win: ${state.get('risk_metrics', {}).get('largest_win', 0):.2f}
- Largest Loss: ${state.get('risk_metrics', {}).get('largest_loss', 0):.2f}

Provide:
1. A brief summary of the day
2. One thing that went well
3. One area for improvement
4. A suggestion for tomorrow

Keep it concise (4-5 sentences total)."""

        try:
            llm_response = await self.claude_llm.generate_with_metadata(
                prompt,
                system="You are Pearl, a trading coach. Provide constructive, balanced daily reviews.",
                max_tokens=self._config.llm.MAX_DAILY_REVIEW_TOKENS,
            )
            review = llm_response.content
            latency_ms = (time.time() - start_time) * 1000

            # Record metrics
            self.metrics.record(LLMRequest(
                timestamp=datetime.now(),
                endpoint="daily_review",
                model=self.claude_llm.model,
                input_tokens=llm_response.input_tokens,
                output_tokens=llm_response.output_tokens,
                latency_ms=latency_ms,
                success=True,
            ))

            if review:
                message = PearlMessage(
                    content=review,
                    message_type="coaching",
                    priority="high",
                )
                await self._emit_message(message)
                return message

        except Exception as e:
            logger.error(f"Error generating daily review: {e}")

        return None

    # ================================================================
    # PROACTIVE ENGAGEMENT METHODS (Pearl AI 2.0)
    # ================================================================

    async def _run_proactive_checks(self, old_state: Dict, new_state: Dict):
        """Run all proactive engagement checks."""
        try:
            # Check ML filter performance warning
            ml_message = await self.check_ml_performance(new_state)
            if ml_message:
                await self._emit_message(ml_message)

            # Check for losing streak coaching
            coaching_message = await self.check_streak_coaching(new_state)
            if coaching_message:
                await self._emit_message(coaching_message)

            # Check for quiet period engagement
            quiet_message = await self.check_quiet_period(new_state)
            if quiet_message:
                await self._emit_message(quiet_message)

        except Exception as e:
            logger.error(f"Error in proactive checks: {e}")

    async def check_ml_performance(self, state: Dict[str, Any]) -> Optional[PearlMessage]:
        """
        Check if ML filter is helping or hurting performance.
        Proactively warns user when ML has negative lift.
        """
        # Check cooldown
        if self._last_ml_warning_time:
            elapsed = datetime.now() - self._last_ml_warning_time
            if elapsed < self.ml_warning_cooldown:
                return None

        ai_status = state.get("ai_status", {})
        ml_filter = ai_status.get("ml_filter", {})

        if not ml_filter.get("enabled"):
            return None

        lift = ml_filter.get("lift", {})
        if not lift:
            return None

        lift_ok = lift.get("lift_ok", True)
        win_rate_pass = lift.get("win_rate_pass", 0)
        win_rate_fail = lift.get("win_rate_fail", 0)
        lift_pct = lift.get("lift_pct", 0)

        # ML is blocking winners - this is bad!
        if not lift_ok and win_rate_fail > win_rate_pass and win_rate_fail > 0.4:
            self._last_ml_warning_time = datetime.now()

            passed = ml_filter.get("passed", 0)
            skipped = ml_filter.get("skipped", 0)

            content = (
                f"Heads up: ML filter is currently filtering OUT winners. "
                f"Blocked signals had {win_rate_fail*100:.0f}% win rate vs "
                f"{win_rate_pass*100:.0f}% for passed signals. "
                f"(ML passed {passed}, blocked {skipped}). "
                f"Consider toggling it off temporarily."
            )

            return PearlMessage(
                content=content,
                message_type="alert",
                priority="high",
                metadata={
                    "alert_type": "ml_negative_lift",
                    "win_rate_pass": win_rate_pass,
                    "win_rate_fail": win_rate_fail,
                    "lift_pct": lift_pct,
                }
            )

        # ML has poor lift (not adding value)
        elif not lift_ok and abs(lift_pct) < 5 and (passed := ml_filter.get("passed", 0)) > 10:
            # Only warn occasionally when ML is neutral
            if self._last_ml_warning_time:
                # Extra long cooldown for neutral warnings
                elapsed = datetime.now() - self._last_ml_warning_time
                if elapsed < timedelta(hours=4):
                    return None

            self._last_ml_warning_time = datetime.now()

            content = (
                f"ML filter is active but not showing significant lift yet. "
                f"Pass rate: {win_rate_pass*100:.0f}%, Block rate: {win_rate_fail*100:.0f}%. "
                f"It may need more data to calibrate."
            )

            return PearlMessage(
                content=content,
                message_type="insight",
                priority="normal",
                metadata={"alert_type": "ml_neutral_lift"}
            )

        return None

    async def check_streak_coaching(self, state: Dict[str, Any]) -> Optional[PearlMessage]:
        """
        Check for losing streaks and offer supportive coaching.
        Triggers at 2+ consecutive losses.
        """
        # Check cooldown
        if self._last_coaching_time:
            elapsed = datetime.now() - self._last_coaching_time
            if elapsed < self.coaching_cooldown:
                return None

        consecutive_losses = state.get("consecutive_losses", 0)

        if consecutive_losses < self._config.narration.LOSING_STREAK_TRIGGER:
            return None

        self._last_coaching_time = datetime.now()

        # Get recent losing trades for analysis
        recent_exits = state.get("recent_exits", [])[:consecutive_losses]
        directions = [t.get("direction", "?").upper() for t in recent_exits]
        total_loss = sum(t.get("pnl", 0) for t in recent_exits)

        # Check for patterns
        regime = state.get("market_regime", {}).get("regime", "unknown")
        pressure = state.get("buy_sell_pressure", {}).get("bias", "neutral")

        # Analyze if there's a pattern
        pattern_note = ""
        if len(set(directions)) == 1:  # All same direction
            dir_str = directions[0]
            # Check if direction is opposite to pressure
            if (dir_str == "LONG" and pressure == "seller") or (dir_str == "SHORT" and pressure == "buyer"):
                pattern_note = f"All {consecutive_losses} were {dir_str} entries against {pressure} pressure."
            else:
                pattern_note = f"All {consecutive_losses} were {dir_str} entries."

        # Use Claude for coaching if available, otherwise template
        if self.claude_llm:
            try:
                prompt = f"""A trader has {consecutive_losses} consecutive losses (${total_loss:.2f} total).
Market: {regime} regime with {pressure} pressure
Directions: {', '.join(directions)}
{f'Pattern: {pattern_note}' if pattern_note else ''}

Generate a supportive, brief coaching message (2-3 sentences):
- Acknowledge the streak without being negative or dramatic
- If there's a pattern, point it out gently
- Suggest an optional 5-minute pause
- Be supportive, not critical

Example: "Two losses in a row, both LONG in seller pressure. The market might be rotating against us. Want to step back for 5 minutes to let things settle?"
"""
                response = await self.claude_llm.generate(
                    prompt,
                    system="You are Pearl, a supportive trading coach. Be brief, constructive, and never blame the trader.",
                    max_tokens=self._config.llm.MAX_COACHING_TOKENS,
                )
                if response:
                    return PearlMessage(
                        content=response,
                        message_type="coaching",
                        priority="high",
                        metadata={
                            "coaching_type": "losing_streak",
                            "consecutive_losses": consecutive_losses,
                            "total_loss": total_loss,
                        }
                    )
            except Exception as e:
                logger.error(f"Error generating streak coaching: {e}")

        # Fallback template
        content = f"{consecutive_losses} losses in a row (${total_loss:.2f}). "
        if pattern_note:
            content += f"{pattern_note} "
        content += "Consider taking a 5-minute breather."

        return PearlMessage(
            content=content,
            message_type="coaching",
            priority="high",
            metadata={
                "coaching_type": "losing_streak",
                "consecutive_losses": consecutive_losses,
            }
        )

    async def check_quiet_period(self, state: Dict[str, Any]) -> Optional[PearlMessage]:
        """
        Engage during quiet market periods (15+ minutes with no signals).
        Provides observations, historical patterns, or coaching.
        """
        # Check cooldown
        if self._last_quiet_engagement_time:
            elapsed = datetime.now() - self._last_quiet_engagement_time
            if elapsed < self.quiet_engagement_threshold:
                return None

        # Check how long since last signal
        if self._last_signal_time:
            quiet_duration = datetime.now() - self._last_signal_time
        else:
            # Use state's quiet period if available
            quiet_minutes = state.get("quiet_period_minutes", 0)
            threshold_minutes = int(self.quiet_engagement_threshold.total_seconds() / 60)
            if quiet_minutes < threshold_minutes:
                return None
            quiet_duration = timedelta(minutes=quiet_minutes)

        if quiet_duration < self.quiet_engagement_threshold:
            return None

        self._last_quiet_engagement_time = datetime.now()
        quiet_mins = int(quiet_duration.total_seconds() / 60)

        # Get context for insight
        regime = state.get("market_regime", {}).get("regime", "unknown")
        daily_pnl = state.get("daily_pnl", 0)
        daily_wins = state.get("daily_wins", 0)
        daily_losses = state.get("daily_losses", 0)
        daily_trades = state.get("daily_trades", 0)

        # Use local LLM for quick engagement
        if self.local_llm and await self.local_llm.is_available():
            try:
                prompt = f"""Market has been quiet for {quiet_mins} minutes.
Current state: {regime} market, ${daily_pnl:.2f} P&L, {daily_wins}W/{daily_losses}L

Generate ONE brief, helpful observation or tip (1-2 sentences).
Options:
- Market observation ("Ranging market = fewer signals, but setups may be cleaner when they come")
- Quick performance note ("3 wins today with tight stops - good discipline")
- Friendly check-in ("Quiet market - good time for a stretch!")
- Pattern observation if interesting

Be conversational, not robotic. Under 2 sentences."""

                response = await self.local_llm.generate(
                    prompt,
                    system="You are Pearl, a friendly trading assistant. Keep it brief and natural.",
                    max_tokens=self._config.llm.MAX_INSIGHT_TOKENS,
                )
                if response:
                    return PearlMessage(
                        content=response,
                        message_type="insight",
                        priority="low",
                        metadata={
                            "insight_type": "quiet_period",
                            "quiet_minutes": quiet_mins,
                        }
                    )
            except Exception as e:
                logger.error(f"Error generating quiet period insight: {e}")

        # Fallback template-based engagement
        if daily_trades > 0:
            win_rate = daily_wins / daily_trades * 100
            content = f"Quiet {quiet_mins} minutes. Today so far: ${daily_pnl:.2f} P&L, {win_rate:.0f}% win rate ({daily_wins}/{daily_trades})."
        else:
            content = f"No signals in {quiet_mins} minutes. {regime.replace('_', ' ').title()} market - waiting for the right setup."

        return PearlMessage(
            content=content,
            message_type="insight",
            priority="low",
            metadata={"insight_type": "quiet_period", "quiet_minutes": quiet_mins}
        )

    def explain_rejections(self, state: Dict[str, Any]) -> str:
        """
        Explain why signals were rejected today.
        Returns a human-readable breakdown of rejection reasons.
        """
        ai_status = state.get("ai_status", {})
        ml_filter = ai_status.get("ml_filter", {})
        direction_gating = ai_status.get("direction_gating", {})
        circuit_breaker = state.get("circuit_breaker", {})
        rejections_24h = state.get("signal_rejections_24h", {})

        reasons = []

        # ML filter rejections
        ml_skips = ml_filter.get("skipped", 0)
        if ml_skips > 0:
            ml_threshold = ml_filter.get("threshold", 0.5)
            reasons.append(f"{ml_skips} below ML threshold ({ml_threshold*100:.0f}%)")

        # Direction gating blocks
        gating_blocks = direction_gating.get("blocks", 0)
        if gating_blocks > 0:
            blocked_dir = direction_gating.get("blocked_direction", "opposite")
            reasons.append(f"{gating_blocks} direction gated ({blocked_dir} blocked)")

        # Circuit breaker blocks
        cb_blocks = circuit_breaker.get("blocks", 0)
        if cb_blocks > 0:
            reasons.append(f"{cb_blocks} circuit breaker blocks")

        # Any additional rejection categories from 24h stats
        if isinstance(rejections_24h, dict):
            for reason, count in rejections_24h.items():
                # Skip if already counted above
                if count > 0 and reason not in ["ml_filter", "direction_gating", "circuit_breaker"]:
                    reason_str = reason.replace("_", " ").title()
                    if reason_str not in str(reasons):
                        reasons.append(f"{count} {reason_str}")

        if not reasons:
            return "No signals rejected today - all opportunities taken!"

        total = sum(int(r.split()[0]) for r in reasons)
        summary = f"Signals rejected today ({total} total): " + ", ".join(reasons) + "."

        return summary

    def get_trading_context_summary(self, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get a summary of current trading context for display.
        Used by frontend for context panel.
        """
        state = state or self._current_state

        daily_pnl = state.get("daily_pnl", 0)
        daily_wins = state.get("daily_wins", 0)
        daily_losses = state.get("daily_losses", 0)
        daily_trades = state.get("daily_trades", 0)
        active_positions = state.get("active_trades_count", 0)

        regime_info = state.get("market_regime", {})
        regime = regime_info.get("regime", "unknown").replace("_", " ").title()

        # Last signal time
        last_signal = None
        if self._last_signal_time:
            elapsed = datetime.now() - self._last_signal_time
            mins = int(elapsed.total_seconds() / 60)
            if mins < 1:
                last_signal = "Just now"
            elif mins < 60:
                last_signal = f"{mins}m ago"
            else:
                hours = mins // 60
                last_signal = f"{hours}h ago"

        # Active position details
        position_info = None
        if active_positions > 0:
            last_dir = state.get("last_trade_direction", "").upper()
            last_entry = state.get("last_entry_price", 0)
            if last_dir and last_entry:
                position_info = f"{last_dir} @ {last_entry}"

        return {
            "daily_pnl": daily_pnl,
            "win_count": daily_wins,
            "loss_count": daily_losses,
            "trade_count": daily_trades,
            "win_rate": (daily_wins / daily_trades * 100) if daily_trades > 0 else 0,
            "active_positions": active_positions,
            "position_info": position_info,
            "market_regime": regime,
            "last_signal_time": last_signal,
            "consecutive_wins": state.get("consecutive_wins", 0),
            "consecutive_losses": state.get("consecutive_losses", 0),
        }

    # ================================================================
    # METRICS API (Pearl AI 3.0)
    # ================================================================

    def get_metrics_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get metrics summary for API endpoint."""
        summary = self.metrics.get_summary(hours)

        # Add cache stats if available
        if self.cache:
            summary["cache"] = self.cache.get_stats()

        return summary

    def get_cost_summary(self) -> Dict[str, Any]:
        """Get cost summary for API endpoint."""
        return {
            "today_usd": round(self.metrics.get_cost_today(), 4),
            "month_usd": round(self.metrics.get_cost_this_month(), 4),
            "limit_usd": self.metrics.daily_cost_limit,
        }

    def get_last_response_source(self) -> Optional[str]:
        """
        Get the source of the last response (P5.1).

        Returns:
            Source string: "cache", "local", "claude", or "template"
        """
        if self._last_response_source:
            return self._last_response_source.value
        return None

    def get_ml_lift_metrics(self, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get ML filter lift metrics for API exposure (A2.3).

        Returns metrics about whether the ML filter is helping performance:
        - pass_win_rate: Win rate of signals that passed ML filter
        - fail_win_rate: Win rate of signals that failed ML filter
        - lift_pct: Percentage lift from ML filter
        - confidence: Statistical confidence level
        - sample_size: Number of samples used

        Args:
            state: Optional state dict. If None, uses current state.

        Returns:
            Dictionary with ML lift metrics
        """
        state = state or self._current_state
        ai_status = state.get("ai_status", {})
        ml_filter = ai_status.get("ml_filter", {})

        # Check if ML filter is enabled
        if not ml_filter.get("enabled"):
            return {
                "enabled": False,
                "pass_win_rate": None,
                "fail_win_rate": None,
                "lift_pct": None,
                "lift_ok": None,
                "confidence": None,
                "sample_size": 0,
                "mode": "off",
            }

        lift = ml_filter.get("lift", {})
        passed = ml_filter.get("passed", 0)
        skipped = ml_filter.get("skipped", 0)

        # Extract lift metrics
        win_rate_pass = lift.get("win_rate_pass", lift.get("lift_win_rate"))
        win_rate_fail = lift.get("win_rate_fail")
        lift_ok = lift.get("lift_ok", False)
        lift_pct = lift.get("lift_pct", 0)

        # Calculate confidence based on sample size
        total_samples = passed + skipped
        if total_samples < 10:
            confidence = "very_low"
        elif total_samples < 30:
            confidence = "low"
        elif total_samples < 100:
            confidence = "medium"
        else:
            confidence = "high"

        return {
            "enabled": True,
            "mode": ml_filter.get("mode", "shadow"),
            "pass_win_rate": win_rate_pass,
            "fail_win_rate": win_rate_fail,
            "lift_pct": lift_pct,
            "lift_ok": lift_ok,
            "confidence": confidence,
            "sample_size": total_samples,
            "signals_passed": passed,
            "signals_skipped": skipped,
            "threshold": ml_filter.get("threshold", 0.5),
        }

    def get_response_source_distribution(self, hours: Optional[int] = None) -> Dict[str, Any]:
        """
        Get response source distribution metrics (A2.2).

        Args:
            hours: Optional time window in hours. None for all-time.

        Returns:
            Dictionary with source distribution data
        """
        return self.metrics.get_response_source_distribution(hours)

    # ================================================================
    # SUGGESTION FEEDBACK (I3.1)
    # ================================================================

    def record_suggestion_feedback(
        self,
        suggestion_id: str,
        action: str,
        dismiss_reason: Optional[str] = None,
        dismiss_comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record user feedback on a suggestion (I3.1).

        Used to improve suggestion quality over time by tracking
        which suggestions are accepted vs dismissed, and why.

        Args:
            suggestion_id: Unique identifier for the suggestion
            action: "accept" or "dismiss"
            dismiss_reason: Reason for dismissal (if action is "dismiss")
                           Options: "not_relevant", "wrong_timing", "too_risky", "other"
            dismiss_comment: Optional additional comment for "other" reason

        Returns:
            Dictionary with feedback confirmation and updated stats
        """
        from datetime import datetime

        feedback = {
            "suggestion_id": suggestion_id,
            "action": action,
            "timestamp": datetime.now().isoformat(),
            "dismiss_reason": dismiss_reason,
            "dismiss_comment": dismiss_comment,
        }

        # Record in metrics
        self.metrics.record_feedback(feedback)

        # Log feedback for analysis
        if action == "dismiss" and dismiss_reason:
            logger.info(f"Suggestion {suggestion_id[:8]} dismissed: {dismiss_reason}")
        else:
            logger.info(f"Suggestion {suggestion_id[:8]} {action}ed")

        # Update user patterns in memory if feedback suggests preferences
        if dismiss_reason == "too_risky":
            self.memory._update_pattern("preference", "risk_averse", 0.3)
        elif dismiss_reason == "wrong_timing":
            self.memory._update_pattern("preference", "timing_sensitive", 0.3)

        return {
            "recorded": True,
            "suggestion_id": suggestion_id,
            "action": action,
            "feedback_stats": self.metrics.get_feedback_stats(),
        }

    def get_feedback_stats(self) -> Dict[str, Any]:
        """
        Get suggestion feedback statistics (I3.1).

        Returns:
            Dictionary with feedback statistics including:
            - total_accepted: Number of accepted suggestions
            - total_dismissed: Number of dismissed suggestions
            - acceptance_rate: Percentage of suggestions accepted
            - dismiss_reasons: Breakdown of dismiss reasons
        """
        return self.metrics.get_feedback_stats()
