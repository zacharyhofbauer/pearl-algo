"""
Thinking Engine - Transparent reasoning that shows its work.

This module implements Claude-like thinking/reasoning traces for Pearl AI,
making all decisions transparent and explainable.

Features:
- Decision traces for every signal decision
- Reasoning chains with multi-step analysis
- Streaming output for real-time display
- Confidence breakdowns by factor
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional


class ThinkingLevel(Enum):
    """Level of detail for thinking output."""
    MINIMAL = "minimal"      # Just the decision
    NORMAL = "normal"        # Key factors and decision
    DETAILED = "detailed"    # Full reasoning chain
    DEBUG = "debug"          # Everything including raw data


class DecisionType(Enum):
    """Types of decisions that can be traced."""
    SIGNAL_GENERATION = "signal_generation"
    SIGNAL_FILTERING = "signal_filtering"
    POSITION_SIZING = "position_sizing"
    RISK_ASSESSMENT = "risk_assessment"
    ENTRY_TIMING = "entry_timing"
    EXIT_DECISION = "exit_decision"
    FILTER_EVALUATION = "filter_evaluation"
    GENERAL = "general"


@dataclass
class ThinkingStep:
    """A single step in a reasoning chain."""
    content: str
    step_type: str = "observation"  # observation, reasoning, conclusion, action
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        prefix = {
            "observation": "->",
            "reasoning": "=>",
            "conclusion": "=>",
            "action": "[ACTION]",
        }.get(self.step_type, "->")
        return f"{prefix} {self.content}"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "step_type": self.step_type,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class IndicatorCheck:
    """Record of an indicator value check."""
    name: str
    value: float
    interpretation: str
    bullish: Optional[bool] = None  # True=bullish, False=bearish, None=neutral
    weight: float = 0.0  # Contribution to confidence
    
    def __str__(self) -> str:
        signal = ""
        if self.bullish is True:
            signal = " (bullish)"
        elif self.bullish is False:
            signal = " (bearish)"
        return f"{self.name}: {self.value:.4f} - {self.interpretation}{signal}"


@dataclass
class FilterResult:
    """Result of a filter evaluation."""
    name: str
    passed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        status = "PASS" if self.passed else "BLOCK"
        return f"{self.name}: {status} - {self.reason}"


@dataclass
class KeyLevelCheck:
    """Record of a key level proximity check."""
    level_type: str  # PDH, PWH, DO, etc.
    level_price: float
    current_price: float
    distance_pct: float
    significance: str
    is_support: bool
    
    def __str__(self) -> str:
        direction = "support" if self.is_support else "resistance"
        return f"{self.level_type} ({self.level_price:.2f}): {self.distance_pct:.2%} away - {direction}, {self.significance}"


@dataclass
class ConfidenceFactor:
    """A factor contributing to confidence score."""
    name: str
    value: float
    weight: float
    contribution: float
    explanation: str
    
    def __str__(self) -> str:
        sign = "+" if self.contribution >= 0 else ""
        return f"{self.name}: {sign}{self.contribution:.2f} ({self.explanation})"


@dataclass
class DecisionTrace:
    """
    Complete trace of a decision-making process.
    
    This captures everything that went into a decision:
    - What indicators were checked
    - What filters were evaluated
    - What key levels are nearby
    - How confidence was calculated
    - The final decision and reasoning
    """
    decision_type: DecisionType
    decision_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Input context
    symbol: str = ""
    price: float = 0.0
    direction: str = ""  # LONG or SHORT
    
    # Thinking process
    thinking_steps: list[ThinkingStep] = field(default_factory=list)
    
    # Indicator analysis
    indicators: list[IndicatorCheck] = field(default_factory=list)
    
    # Filter evaluation
    filters: list[FilterResult] = field(default_factory=list)
    
    # Key level analysis
    key_levels: list[KeyLevelCheck] = field(default_factory=list)
    
    # Confidence breakdown
    confidence_factors: list[ConfidenceFactor] = field(default_factory=list)
    final_confidence: float = 0.0
    
    # Decision
    decision: str = ""  # ALLOW, BLOCK, SKIP, etc.
    decision_reason: str = ""
    
    # Timing
    duration_ms: float = 0.0
    
    def add_step(self, content: str, step_type: str = "observation", **metadata) -> None:
        """Add a thinking step to the trace."""
        self.thinking_steps.append(ThinkingStep(
            content=content,
            step_type=step_type,
            metadata=metadata,
        ))
    
    def add_indicator(
        self,
        name: str,
        value: float,
        interpretation: str,
        bullish: Optional[bool] = None,
        weight: float = 0.0,
    ) -> None:
        """Add an indicator check to the trace."""
        self.indicators.append(IndicatorCheck(
            name=name,
            value=value,
            interpretation=interpretation,
            bullish=bullish,
            weight=weight,
        ))
    
    def add_filter(
        self,
        name: str,
        passed: bool,
        reason: str,
        **details,
    ) -> None:
        """Add a filter result to the trace."""
        self.filters.append(FilterResult(
            name=name,
            passed=passed,
            reason=reason,
            details=details,
        ))
    
    def add_key_level(
        self,
        level_type: str,
        level_price: float,
        current_price: float,
        distance_pct: float,
        significance: str,
        is_support: bool,
    ) -> None:
        """Add a key level check to the trace."""
        self.key_levels.append(KeyLevelCheck(
            level_type=level_type,
            level_price=level_price,
            current_price=current_price,
            distance_pct=distance_pct,
            significance=significance,
            is_support=is_support,
        ))
    
    def add_confidence_factor(
        self,
        name: str,
        value: float,
        weight: float,
        contribution: float,
        explanation: str,
    ) -> None:
        """Add a confidence factor to the trace."""
        self.confidence_factors.append(ConfidenceFactor(
            name=name,
            value=value,
            weight=weight,
            contribution=contribution,
            explanation=explanation,
        ))
    
    def set_decision(self, decision: str, reason: str, confidence: float) -> None:
        """Set the final decision."""
        self.decision = decision
        self.decision_reason = reason
        self.final_confidence = confidence
    
    def get_blocking_filters(self) -> list[FilterResult]:
        """Get all filters that blocked the signal."""
        return [f for f in self.filters if not f.passed]
    
    def format_thinking(self, level: ThinkingLevel = ThinkingLevel.NORMAL) -> str:
        """
        Format the thinking trace for display.
        
        Args:
            level: Level of detail to include
            
        Returns:
            Formatted string representation
        """
        lines = []
        
        # Header
        lines.append(f"[THINKING] Analyzing {self.direction} signal at {self.price:.2f}...")
        
        if level in (ThinkingLevel.DETAILED, ThinkingLevel.DEBUG):
            # Indicator analysis
            if self.indicators:
                lines.append("")
                lines.append("Indicators:")
                for ind in self.indicators:
                    lines.append(f"  {ind}")
        
        if level != ThinkingLevel.MINIMAL:
            # Key thinking steps
            if self.thinking_steps:
                lines.append("")
                for step in self.thinking_steps:
                    lines.append(f"  {step}")
        
        if level in (ThinkingLevel.DETAILED, ThinkingLevel.DEBUG):
            # Key levels
            if self.key_levels:
                lines.append("")
                lines.append("Key Levels:")
                for kl in self.key_levels:
                    lines.append(f"  {kl}")
        
        # Filter results (always show blocking filters)
        blocking = self.get_blocking_filters()
        if blocking:
            lines.append("")
            lines.append("Blocked by:")
            for f in blocking:
                lines.append(f"  - {f}")
        elif level != ThinkingLevel.MINIMAL:
            # Show passing filters in detailed mode
            passing = [f for f in self.filters if f.passed]
            if passing and level == ThinkingLevel.DEBUG:
                lines.append("")
                lines.append("Filters passed:")
                for f in passing:
                    lines.append(f"  - {f.name}")
        
        # Confidence breakdown (detailed only)
        if level in (ThinkingLevel.DETAILED, ThinkingLevel.DEBUG) and self.confidence_factors:
            lines.append("")
            lines.append("Confidence factors:")
            for cf in self.confidence_factors:
                lines.append(f"  {cf}")
        
        # Decision
        lines.append("")
        lines.append(f"[DECISION] {self.decision} with confidence {self.final_confidence:.2f}")
        if self.decision_reason:
            lines.append(f"  Reason: {self.decision_reason}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "decision_type": self.decision_type.value,
            "decision_id": self.decision_id,
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "price": self.price,
            "direction": self.direction,
            "thinking_steps": [s.to_dict() for s in self.thinking_steps],
            "indicators": [
                {"name": i.name, "value": i.value, "interpretation": i.interpretation, "bullish": i.bullish}
                for i in self.indicators
            ],
            "filters": [
                {"name": f.name, "passed": f.passed, "reason": f.reason, "details": f.details}
                for f in self.filters
            ],
            "key_levels": [
                {"type": k.level_type, "price": k.level_price, "distance_pct": k.distance_pct}
                for k in self.key_levels
            ],
            "confidence_factors": [
                {"name": c.name, "contribution": c.contribution, "explanation": c.explanation}
                for c in self.confidence_factors
            ],
            "final_confidence": self.final_confidence,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "duration_ms": self.duration_ms,
        }


class ThinkingEngine:
    """
    Engine for generating and managing thinking traces.
    
    Usage:
        engine = ThinkingEngine()
        
        # Create a trace for a signal decision
        with engine.trace(DecisionType.SIGNAL_GENERATION, "sig-001") as trace:
            trace.add_step("Checking EMA crossover...", "observation")
            trace.add_indicator("EMA9", 21450.5, "Above EMA21", bullish=True)
            trace.add_filter("session_filter", True, "Overnight session allowed")
            trace.set_decision("ALLOW", "All conditions met", 0.72)
        
        # Get formatted output
        print(trace.format_thinking())
    """
    
    def __init__(
        self,
        default_level: ThinkingLevel = ThinkingLevel.NORMAL,
        stream_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize thinking engine.
        
        Args:
            default_level: Default level of detail for output
            stream_callback: Optional callback for streaming output
        """
        self._default_level = default_level
        self._stream_callback = stream_callback
        self._current_trace: Optional[DecisionTrace] = None
        self._traces: list[DecisionTrace] = []
        self._max_traces = 1000
    
    def trace(
        self,
        decision_type: DecisionType,
        decision_id: str,
        symbol: str = "",
        price: float = 0.0,
        direction: str = "",
    ) -> "ThinkingContext":
        """
        Create a new decision trace context.
        
        Usage:
            with engine.trace(DecisionType.SIGNAL_GENERATION, "sig-001") as trace:
                # Add observations, indicators, filters, etc.
                trace.set_decision("ALLOW", "Conditions met", 0.72)
        """
        return ThinkingContext(
            engine=self,
            decision_type=decision_type,
            decision_id=decision_id,
            symbol=symbol,
            price=price,
            direction=direction,
        )
    
    def _start_trace(self, trace: DecisionTrace) -> None:
        """Start a new trace."""
        self._current_trace = trace
        if self._stream_callback:
            self._stream_callback(f"[THINKING] Starting {trace.decision_type.value}...")
    
    def _end_trace(self, trace: DecisionTrace) -> None:
        """End a trace and store it."""
        self._current_trace = None
        self._traces.append(trace)
        
        # Trim old traces
        if len(self._traces) > self._max_traces:
            self._traces = self._traces[-self._max_traces:]
        
        if self._stream_callback:
            self._stream_callback(f"[DECISION] {trace.decision}")
    
    def stream_step(self, content: str) -> None:
        """Stream a thinking step."""
        if self._stream_callback:
            self._stream_callback(f"  -> {content}")
    
    def get_recent_traces(self, count: int = 10) -> list[DecisionTrace]:
        """Get the most recent traces."""
        return self._traces[-count:]
    
    def get_trace_by_id(self, decision_id: str) -> Optional[DecisionTrace]:
        """Get a trace by its decision ID."""
        for trace in reversed(self._traces):
            if trace.decision_id == decision_id:
                return trace
        return None
    
    async def stream_trace(
        self,
        trace: DecisionTrace,
        level: ThinkingLevel = ThinkingLevel.NORMAL,
    ) -> AsyncIterator[str]:
        """
        Stream a trace's thinking for real-time display.
        
        Yields formatted lines with small delays for visual effect.
        """
        # Header
        yield f"[THINKING] Analyzing {trace.direction} signal at {trace.price:.2f}..."
        await asyncio.sleep(0.1)
        
        # Thinking steps
        for step in trace.thinking_steps:
            yield f"  {step}"
            await asyncio.sleep(0.05)
        
        # Indicators (in detailed mode)
        if level in (ThinkingLevel.DETAILED, ThinkingLevel.DEBUG) and trace.indicators:
            yield ""
            yield "Indicators:"
            for ind in trace.indicators:
                yield f"  {ind}"
                await asyncio.sleep(0.03)
        
        # Key levels (in detailed mode)
        if level in (ThinkingLevel.DETAILED, ThinkingLevel.DEBUG) and trace.key_levels:
            yield ""
            yield "Key Levels:"
            for kl in trace.key_levels:
                yield f"  {kl}"
                await asyncio.sleep(0.03)
        
        # Blocking filters
        blocking = trace.get_blocking_filters()
        if blocking:
            yield ""
            yield "Blocked by:"
            for f in blocking:
                yield f"  - {f}"
                await asyncio.sleep(0.05)
        
        # Confidence breakdown (detailed only)
        if level in (ThinkingLevel.DETAILED, ThinkingLevel.DEBUG) and trace.confidence_factors:
            yield ""
            yield "Confidence factors:"
            for cf in trace.confidence_factors:
                yield f"  {cf}"
                await asyncio.sleep(0.03)
        
        # Decision
        await asyncio.sleep(0.1)
        yield ""
        yield f"[DECISION] {trace.decision} with confidence {trace.final_confidence:.2f}"
        if trace.decision_reason:
            yield f"  Reason: {trace.decision_reason}"


class ThinkingContext:
    """Context manager for creating decision traces."""
    
    def __init__(
        self,
        engine: ThinkingEngine,
        decision_type: DecisionType,
        decision_id: str,
        symbol: str,
        price: float,
        direction: str,
    ):
        self._engine = engine
        self._trace = DecisionTrace(
            decision_type=decision_type,
            decision_id=decision_id,
            symbol=symbol,
            price=price,
            direction=direction,
        )
        self._start_time = datetime.now(timezone.utc)
    
    def __enter__(self) -> DecisionTrace:
        self._engine._start_trace(self._trace)
        return self._trace
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._trace.duration_ms = (
            datetime.now(timezone.utc) - self._start_time
        ).total_seconds() * 1000
        self._engine._end_trace(self._trace)


# Global thinking engine instance
_thinking_engine: Optional[ThinkingEngine] = None


def get_thinking_engine() -> ThinkingEngine:
    """Get the global thinking engine instance."""
    global _thinking_engine
    if _thinking_engine is None:
        _thinking_engine = ThinkingEngine()
    return _thinking_engine


def set_thinking_stream_callback(callback: Callable[[str], None]) -> None:
    """Set the stream callback for the global thinking engine."""
    engine = get_thinking_engine()
    engine._stream_callback = callback
