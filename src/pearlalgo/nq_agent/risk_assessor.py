"""
Real-Time Risk Assessor

Quick risk check before signal execution:
- Is this signal type currently working or broken?
- Are we in a losing streak for this setup?
- Is market volatility appropriate for this trade?
- Does this conflict with recent losses?
- Should position size be adjusted?

Designed for FAST response (<3s) to not delay signal processing.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.absolute_mode import ABSOLUTE_MODE_PROMPT

# Import OpenAI client (optional dependency; wrapper kept as `claude_client.py` for backward compat)
try:
    from pearlalgo.utils.claude_client import (
        ClaudeClient,
        ClaudeAPIError,
        get_claude_client,
        OPENAI_AVAILABLE,
    )
except ImportError:
    ClaudeClient = None
    ClaudeAPIError = Exception
    get_claude_client = lambda: None
    OPENAI_AVAILABLE = False

# Backward compatibility
ANTHROPIC_AVAILABLE = OPENAI_AVAILABLE


# ============================================================================
# Prompt Templates
# ============================================================================

RISK_ASSESSMENT_SYSTEM_PROMPT = (
    ABSOLUTE_MODE_PROMPT
    + """\n\nROLE: Real-time risk assessor for an NQ/MNQ futures trading system.

Task
- Assess recent signal performance
- Identify streak and volatility risks
- Flag red flags from recent trades
- Specify size adjustment if needed

Rules
- Very concise
- Data-driven
- Do not block trades unless critical
- Default to proceed unless clear red flags

Output ONLY valid JSON:
{
  "risk_level": "low|medium|high|critical",
  "proceed": true,
  "size_adjustment": 1.0,
  "reasons": ["reason1", "reason2"],
  "primary_concern": "Main risk factor or null",
  "confidence": 0.8
}"""
)

RISK_ASSESSMENT_USER_TEMPLATE = """Assess risk for this trade:

Signal: {signal_type} {direction}
Confidence: {confidence:.0%}
Entry: ${entry_price:.2f}
R:R: {risk_reward:.1f}

Recent Performance (last {lookback} trades):
- Win Rate: {recent_wr:.0%}
- This Signal Type: {signal_type_wr:.0%} ({signal_type_sample} trades)
- Current Streak: {streak}

Market State:
- Regime: {regime}
- Volatility: {volatility}
- Session: {session}

Position Info:
- Suggested Size: {suggested_size} contracts
- Current Exposure: {current_exposure}

Quick risk assessment as JSON:"""


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class RiskAssessment:
    """Risk assessment result for a signal."""
    risk_level: str = "medium"  # low, medium, high, critical
    proceed: bool = True
    size_adjustment: float = 1.0  # Multiplier for position size
    reasons: List[str] = field(default_factory=list)
    primary_concern: Optional[str] = None
    confidence: float = 0.8
    
    # Metadata
    signal_id: str = ""
    model: str = ""
    latency_ms: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "risk_level": self.risk_level,
            "proceed": self.proceed,
            "size_adjustment": self.size_adjustment,
            "reasons": self.reasons,
            "primary_concern": self.primary_concern,
            "confidence": self.confidence,
            "signal_id": self.signal_id,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }
    
    def format_telegram(self) -> str:
        """Format assessment for Telegram (only if notable)."""
        if self.error or self.risk_level == "low":
            return ""  # Don't clutter with low-risk assessments
        
        lines = [f"RISK ASSESSMENT: {self.risk_level.upper()}"]

        if self.primary_concern:
            lines.append(f"PRIMARY CONCERN: {self.primary_concern}")

        if self.size_adjustment != 1.0:
            adj_pct = (self.size_adjustment - 1.0) * 100
            lines.append(f"SIZE ADJUSTMENT: {adj_pct:+.0f}%")
        
        return "\n".join(lines)
    
    @classmethod
    def from_error(cls, error: str) -> "RiskAssessment":
        """Create assessment from error (default to proceed)."""
        return cls(
            risk_level="medium",
            proceed=True,  # Default to proceed on error
            error=error,
        )
    
    @classmethod
    def default_proceed(cls) -> "RiskAssessment":
        """Create default proceed assessment."""
        return cls(
            risk_level="low",
            proceed=True,
            confidence=1.0,
        )


# ============================================================================
# Risk Assessor
# ============================================================================

class RealTimeRiskAssessor:
    """
    LLM-powered real-time risk assessment.
    
    Provides fast risk checks before signal execution.
    
    Configuration:
    - enabled: Master toggle
    - model: Model to use (recommend a faster/cheaper model for low-latency)
    - timeout_seconds: Max time (must be fast, <3s ideal)
    - block_on_critical: Whether to block trades on critical risk
    - consider_recent_trades: How many recent trades to consider
    """
    
    def __init__(
        self,
        enabled: bool = True,
        model: str = "claude-sonnet-4-20250514",
        timeout_seconds: float = 3.0,
        block_on_critical: bool = False,
        consider_recent_trades: int = 20,
    ):
        """
        Initialize the risk assessor.
        
        Args:
            enabled: Whether assessment is enabled
            model: Model to use
            timeout_seconds: Timeout for assessment (keep short!)
            block_on_critical: Whether to block trades on critical risk
            consider_recent_trades: Number of recent trades to analyze
        """
        self.enabled = enabled
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.block_on_critical = block_on_critical
        self.consider_recent_trades = consider_recent_trades
        
        # Initialize OpenAI client
        self._client: Optional[ClaudeClient] = None
        if enabled and OPENAI_AVAILABLE:
            try:
                self._client = get_claude_client()
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client for risk assessment: {e}")
        
        # Recent trade cache
        self._recent_trades: List[Dict] = []
        
        # Stats
        self._total_assessments = 0
        self._high_risk_count = 0
        self._blocked_count = 0
        
        status = "enabled" if self._client else "disabled (client unavailable)"
        logger.info(f"RealTimeRiskAssessor initialized: {status}, timeout={timeout_seconds}s")
    
    @property
    def is_available(self) -> bool:
        """Check if assessment is available."""
        return self.enabled and self._client is not None
    
    def update_recent_trades(self, trades: List[Dict]) -> None:
        """
        Update the recent trades cache.
        
        Args:
            trades: List of recent completed trades
        """
        self._recent_trades = trades[-self.consider_recent_trades:]
    
    def add_completed_trade(self, trade: Dict) -> None:
        """
        Add a completed trade to the cache.
        
        Args:
            trade: Completed trade dictionary
        """
        if trade.get("_is_test", False):
            return
        
        self._recent_trades.append(trade)
        if len(self._recent_trades) > self.consider_recent_trades:
            self._recent_trades = self._recent_trades[-self.consider_recent_trades:]
    
    def assess_signal(
        self,
        signal: Dict,
        market_state: Optional[Dict] = None,
        current_exposure: str = "none",
    ) -> RiskAssessment:
        """
        Assess risk for a signal synchronously.
        
        Args:
            signal: Signal to assess
            market_state: Current market conditions
            current_exposure: Current position exposure description
            
        Returns:
            RiskAssessment with risk level and recommendations
        """
        if not self.is_available:
            return RiskAssessment.default_proceed()
        
        start_time = datetime.now(timezone.utc)
        self._total_assessments += 1
        
        try:
            # Build prompt
            user_prompt = self._build_prompt(signal, market_state, current_exposure)
            
            # Call OpenAI (with short max_tokens for speed)
            response = self._client.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=RISK_ASSESSMENT_SYSTEM_PROMPT,
                max_tokens=200,  # Keep response short for speed
            )
            
            # Parse response
            assessment = self._parse_response(response)
            assessment.signal_id = signal.get("signal_id", "")
            
            # Calculate latency
            latency_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            assessment.latency_ms = latency_ms
            assessment.model = self.model
            
            # Update stats
            if assessment.risk_level in ("high", "critical"):
                self._high_risk_count += 1
            
            if self.block_on_critical and assessment.risk_level == "critical":
                assessment.proceed = False
                self._blocked_count += 1
            
            level_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(assessment.risk_level, "⚪")
            logger.debug(f"Risk assessment {level_emoji} {assessment.risk_level} in {latency_ms}ms")
            
            return assessment
            
        except Exception as e:
            logger.debug(f"Risk assessment failed: {e}")
            return RiskAssessment.from_error(str(e))
    
    async def assess_signal_async(
        self,
        signal: Dict,
        market_state: Optional[Dict] = None,
        current_exposure: str = "none",
    ) -> RiskAssessment:
        """
        Assess risk asynchronously with timeout.
        
        Args:
            signal: Signal to assess
            market_state: Current market conditions
            current_exposure: Current position exposure
            
        Returns:
            RiskAssessment (defaults to proceed on timeout)
        """
        if not self.is_available:
            return RiskAssessment.default_proceed()
        
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self.assess_signal,
                    signal,
                    market_state,
                    current_exposure,
                ),
                timeout=self.timeout_seconds,
            )
            return result
            
        except asyncio.TimeoutError:
            logger.debug(f"Risk assessment timed out after {self.timeout_seconds}s")
            return RiskAssessment.default_proceed()  # Default to proceed on timeout
        except Exception as e:
            logger.debug(f"Async risk assessment failed: {e}")
            return RiskAssessment.from_error(str(e))
    
    def _build_prompt(
        self,
        signal: Dict,
        market_state: Optional[Dict],
        current_exposure: str,
    ) -> str:
        """Build the user prompt for risk assessment."""
        # Signal data
        signal_type = signal.get("type", "unknown")
        direction = signal.get("direction", "unknown")
        confidence = signal.get("confidence", 0.0)
        entry_price = signal.get("entry_price", 0.0)
        stop_loss = signal.get("stop_loss", 0.0)
        take_profit = signal.get("take_profit", 0.0)
        
        # Calculate R:R
        if direction == "long" and entry_price > 0 and stop_loss > 0:
            risk = entry_price - stop_loss
            reward = take_profit - entry_price if take_profit else 0
            risk_reward = reward / risk if risk > 0 else 0
        elif direction == "short" and entry_price > 0 and stop_loss > 0:
            risk = stop_loss - entry_price
            reward = entry_price - take_profit if take_profit else 0
            risk_reward = reward / risk if risk > 0 else 0
        else:
            risk_reward = 1.0
        
        # Recent performance
        wins = sum(1 for t in self._recent_trades if t.get("is_win", False))
        total = len(self._recent_trades)
        recent_wr = wins / total if total > 0 else 0.5
        
        # Signal type specific performance
        type_trades = [t for t in self._recent_trades if t.get("type") == signal_type]
        type_wins = sum(1 for t in type_trades if t.get("is_win", False))
        type_total = len(type_trades)
        signal_type_wr = type_wins / type_total if type_total > 0 else 0.5
        
        # Current streak
        streak = 0
        streak_type = None
        for trade in reversed(self._recent_trades):
            is_win = trade.get("is_win", False)
            if streak_type is None:
                streak_type = is_win
                streak = 1
            elif is_win == streak_type:
                streak += 1
            else:
                break
        
        if streak_type is None:
            streak_str = "No recent trades"
        else:
            streak_str = f"{streak} {'WIN' if streak_type else 'LOSS'} streak"
        
        # Market state
        if market_state:
            regime = market_state.get("regime", {}).get("regime", "unknown")
            volatility = market_state.get("regime", {}).get("volatility", "normal")
            session = market_state.get("regime", {}).get("session", "unknown")
        else:
            regime = signal.get("regime", {}).get("regime", "unknown")
            volatility = signal.get("regime", {}).get("volatility", "normal")
            session = signal.get("regime", {}).get("session", "unknown")
        
        # Suggested size
        suggested_size = signal.get("position_size", 5)
        
        return RISK_ASSESSMENT_USER_TEMPLATE.format(
            signal_type=signal_type,
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            risk_reward=risk_reward,
            lookback=total,
            recent_wr=recent_wr,
            signal_type_wr=signal_type_wr,
            signal_type_sample=type_total,
            streak=streak_str,
            regime=regime,
            volatility=volatility,
            session=session,
            suggested_size=suggested_size,
            current_exposure=current_exposure,
        )
    
    def _parse_response(self, response: str) -> RiskAssessment:
        """Parse the model's JSON response into RiskAssessment."""
        try:
            response = response.strip()
            
            # Handle markdown code blocks
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            
            data = json.loads(response)
            
            return RiskAssessment(
                risk_level=str(data.get("risk_level", "medium")).lower(),
                proceed=bool(data.get("proceed", True)),
                size_adjustment=float(data.get("size_adjustment", 1.0)),
                reasons=data.get("reasons", [])[:3],
                primary_concern=data.get("primary_concern"),
                confidence=float(data.get("confidence", 0.8)),
            )
            
        except json.JSONDecodeError:
            logger.debug("Failed to parse risk assessment response")
            return RiskAssessment.default_proceed()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get assessor statistics."""
        return {
            "total_assessments": self._total_assessments,
            "high_risk_count": self._high_risk_count,
            "blocked_count": self._blocked_count,
            "cached_trades": len(self._recent_trades),
            "is_available": self.is_available,
            "model": self.model,
        }


def get_risk_assessor(config: Optional[Dict] = None) -> Optional[RealTimeRiskAssessor]:
    """
    Factory function to create a risk assessor from configuration.
    
    Args:
        config: Configuration dictionary with llm_risk_assessment settings
        
    Returns:
        RealTimeRiskAssessor instance or None if disabled
    """
    if config is None:
        config = {}
    
    ra_config = config.get("llm_risk_assessment", {})
    
    if not ra_config.get("enabled", False):
        logger.debug("Real-time risk assessment disabled in config")
        return None
    
    return RealTimeRiskAssessor(
        enabled=True,
        model=ra_config.get("model", "claude-sonnet-4-20250514"),
        timeout_seconds=ra_config.get("timeout_seconds", 3.0),
        block_on_critical=ra_config.get("block_on_critical", False),
        consider_recent_trades=ra_config.get("consider_recent_trades", 20),
    )


