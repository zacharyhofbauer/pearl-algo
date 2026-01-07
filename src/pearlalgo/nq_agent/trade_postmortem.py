"""
Trade Post-Mortem Analyzer

Analyzes completed trades to identify lessons learned:
- What went right/wrong with the entry
- Whether indicators were accurate
- Comparison of expected vs actual R:R
- Actionable suggestions for improvement

Designed to be:
- Non-blocking (async with timeout)
- Gracefully degrading (failures don't affect core operations)
- Cost-efficient (batch analysis for pattern detection)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger

# Import Claude client (optional dependency)
try:
    from pearlalgo.utils.claude_client import (
        ClaudeClient,
        ClaudeAPIError,
        get_claude_client,
        ANTHROPIC_AVAILABLE,
    )
except ImportError:
    ClaudeClient = None
    ClaudeAPIError = Exception
    get_claude_client = lambda: None
    ANTHROPIC_AVAILABLE = False


# ============================================================================
# Prompt Templates
# ============================================================================

POSTMORTEM_SYSTEM_PROMPT = """You are a trading post-mortem analyst for an NQ/MNQ futures intraday trading system.

Your role is to analyze COMPLETED trades and provide actionable lessons:
1. Entry Quality: Was the entry well-timed? Better price available?
2. Indicator Accuracy: Did the signals/indicators predict correctly?
3. Risk Management: Was stop/target appropriate?
4. Lessons: What can be improved for future similar setups?

RULES:
- Be objective and data-driven
- Focus on actionable improvements, not hindsight bias
- Consider market context at entry time
- Keep analysis concise but insightful
- Never blame randomness - extract learnable patterns

Output ONLY valid JSON with these fields:
{
  "outcome_analysis": "2-3 sentence analysis of why this trade won/lost",
  "entry_quality": {
    "score": 1-5,
    "comment": "Brief assessment of entry timing"
  },
  "indicator_accuracy": {
    "correct_indicators": ["indicator1"],
    "incorrect_indicators": ["indicator2"],
    "comment": "How indicators performed"
  },
  "risk_management": {
    "stop_assessment": "appropriate|too_tight|too_wide",
    "target_assessment": "appropriate|too_aggressive|too_conservative",
    "comment": "Risk management assessment"
  },
  "lessons": ["lesson1", "lesson2"],
  "similar_setup_advice": "What to do differently next time",
  "confidence_calibration": "Was confidence score accurate? overconfident|accurate|underconfident"
}"""

POSTMORTEM_USER_TEMPLATE = """Analyze this completed trade:

Signal Type: {signal_type}
Direction: {direction}
Outcome: {outcome} ({pnl_points:+.2f} points, {pnl_dollars:+.2f} USD)

Entry:
- Price: ${entry_price:.2f}
- Time: {entry_time}
- Confidence: {confidence:.1%}

Exit:
- Price: ${exit_price:.2f}
- Time: {exit_time}
- Reason: {exit_reason}
- Hold Duration: {hold_duration}

Risk/Reward:
- Stop Loss: ${stop_loss:.2f} ({stop_distance:.2f} pts)
- Take Profit: ${take_profit:.2f} ({target_distance:.2f} pts)
- Expected R:R: {expected_rr:.2f}
- Actual R:R: {actual_rr:.2f}

Market Context at Entry:
- Regime: {regime_type} ({volatility} volatility)
- Session: {session}
- RSI: {rsi:.1f}
- ATR: {atr:.2f}

Price Action After Entry:
- Max Favorable Excursion: {mfe:.2f} pts (${mfe_dollars:.2f})
- Max Adverse Excursion: {mae:.2f} pts (${mae_dollars:.2f})
- Best possible exit: ${best_exit:.2f}

Custom Indicators at Entry:
{custom_indicators}

Provide your post-mortem analysis as JSON."""


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class EntryQuality:
    """Entry timing assessment."""
    score: int = 3  # 1-5 scale
    comment: str = ""


@dataclass
class IndicatorAccuracy:
    """Indicator performance assessment."""
    correct_indicators: List[str] = field(default_factory=list)
    incorrect_indicators: List[str] = field(default_factory=list)
    comment: str = ""


@dataclass
class RiskManagement:
    """Risk management assessment."""
    stop_assessment: str = "appropriate"
    target_assessment: str = "appropriate"
    comment: str = ""


@dataclass
class PostMortemReport:
    """Complete post-mortem analysis of a trade."""
    signal_id: str = ""
    outcome_analysis: str = ""
    entry_quality: EntryQuality = field(default_factory=EntryQuality)
    indicator_accuracy: IndicatorAccuracy = field(default_factory=IndicatorAccuracy)
    risk_management: RiskManagement = field(default_factory=RiskManagement)
    lessons: List[str] = field(default_factory=list)
    similar_setup_advice: str = ""
    confidence_calibration: str = "accurate"
    
    # Metadata
    model: str = ""
    latency_ms: int = 0
    error: Optional[str] = None
    timestamp: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "signal_id": self.signal_id,
            "outcome_analysis": self.outcome_analysis,
            "entry_quality": {
                "score": self.entry_quality.score,
                "comment": self.entry_quality.comment,
            },
            "indicator_accuracy": {
                "correct_indicators": self.indicator_accuracy.correct_indicators,
                "incorrect_indicators": self.indicator_accuracy.incorrect_indicators,
                "comment": self.indicator_accuracy.comment,
            },
            "risk_management": {
                "stop_assessment": self.risk_management.stop_assessment,
                "target_assessment": self.risk_management.target_assessment,
                "comment": self.risk_management.comment,
            },
            "lessons": self.lessons,
            "similar_setup_advice": self.similar_setup_advice,
            "confidence_calibration": self.confidence_calibration,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "timestamp": self.timestamp,
        }
    
    def format_telegram(self) -> str:
        """Format post-mortem for Telegram message."""
        if self.error:
            return ""
        
        lines = []
        
        # Header with outcome
        lines.append(f"📊 *Trade Post-Mortem*")
        lines.append(f"\n{self.outcome_analysis}")
        
        # Entry quality
        stars = "⭐" * self.entry_quality.score + "☆" * (5 - self.entry_quality.score)
        lines.append(f"\n*Entry:* {stars}")
        if self.entry_quality.comment:
            lines.append(f"  {self.entry_quality.comment}")
        
        # Risk assessment
        lines.append(f"\n*Risk Management:*")
        lines.append(f"  Stop: {self.risk_management.stop_assessment}")
        lines.append(f"  Target: {self.risk_management.target_assessment}")
        
        # Lessons
        if self.lessons:
            lines.append(f"\n*Lessons:*")
            for lesson in self.lessons[:3]:
                lines.append(f"  • {lesson}")
        
        # Advice for similar setups
        if self.similar_setup_advice:
            lines.append(f"\n*Next time:* {self.similar_setup_advice}")
        
        return "\n".join(lines)
    
    def format_compact(self) -> str:
        """Format compact summary for logging."""
        if self.error:
            return f"PostMortem Error: {self.error}"
        
        entry_stars = self.entry_quality.score
        calibration_emoji = {
            "overconfident": "📈",
            "accurate": "✅",
            "underconfident": "📉",
        }.get(self.confidence_calibration, "❓")
        
        return (
            f"Entry: {entry_stars}/5 | "
            f"Stop: {self.risk_management.stop_assessment} | "
            f"Calibration: {calibration_emoji} | "
            f"Lessons: {len(self.lessons)}"
        )
    
    @classmethod
    def from_error(cls, error: str) -> "PostMortemReport":
        """Create report from error."""
        return cls(error=error, timestamp=datetime.now(timezone.utc).isoformat())


# ============================================================================
# Trade Post-Mortem Analyzer
# ============================================================================

class TradePostMortemAnalyzer:
    """
    LLM-powered trade post-mortem analysis.
    
    Analyzes completed trades to identify lessons and improvements.
    
    Configuration:
    - enabled: Master toggle
    - model: Claude model to use
    - timeout_seconds: Max time for analysis
    - min_pnl_threshold: Minimum P&L to trigger analysis (avoid noise)
    - send_to_telegram: Whether to send reports via Telegram
    - batch_analysis_count: Batch trades for pattern analysis
    """
    
    def __init__(
        self,
        enabled: bool = True,
        model: str = "claude-sonnet-4-20250514",
        timeout_seconds: float = 10.0,
        min_pnl_threshold: float = 50.0,
        send_to_telegram: bool = False,
        batch_analysis_count: int = 10,
        contracts: int = 5,
        tick_value: float = 2.0,  # MNQ default
    ):
        """
        Initialize the trade post-mortem analyzer.
        
        Args:
            enabled: Whether analysis is enabled
            model: Claude model to use
            timeout_seconds: Timeout for analysis requests
            min_pnl_threshold: Minimum absolute P&L in dollars to trigger analysis
            send_to_telegram: Whether to send results to Telegram
            batch_analysis_count: Number of trades to batch for pattern analysis
            contracts: Default contract count for P&L calculation
            tick_value: Dollar value per point (2.0 for MNQ)
        """
        self.enabled = enabled
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.min_pnl_threshold = min_pnl_threshold
        self.send_to_telegram = send_to_telegram
        self.batch_analysis_count = batch_analysis_count
        self.contracts = contracts
        self.tick_value = tick_value
        
        # Initialize Claude client
        self._client: Optional[ClaudeClient] = None
        if enabled and ANTHROPIC_AVAILABLE:
            try:
                self._client = get_claude_client()
            except Exception as e:
                logger.warning(f"Failed to initialize Claude client for post-mortems: {e}")
        
        # Batch buffer for pattern analysis
        self._pending_trades: List[Dict] = []
        
        # Stats
        self._total_analyses = 0
        self._successful_analyses = 0
        
        status = "enabled" if self._client else "disabled (client unavailable)"
        logger.info(f"TradePostMortemAnalyzer initialized: {status}, model={model}")
    
    @property
    def is_available(self) -> bool:
        """Check if analysis is available."""
        return self.enabled and self._client is not None
    
    def should_analyze(self, trade: Dict) -> bool:
        """
        Check if a trade should be analyzed.
        
        Args:
            trade: Trade dictionary with exit data
            
        Returns:
            True if trade meets analysis criteria
        """
        if not self.is_available:
            return False
        
        # Skip test trades
        if trade.get("_is_test", False):
            return False
        
        # Check P&L threshold
        pnl_points = abs(trade.get("pnl_points", 0))
        pnl_dollars = pnl_points * self.contracts * self.tick_value
        
        return pnl_dollars >= self.min_pnl_threshold
    
    def analyze_trade(
        self,
        signal: Dict,
        exit_data: Dict,
        market_data: Optional[Dict] = None,
    ) -> PostMortemReport:
        """
        Analyze a completed trade synchronously.
        
        Args:
            signal: Original signal dictionary
            exit_data: Exit information (price, time, reason, pnl)
            market_data: Optional additional market context
            
        Returns:
            PostMortemReport with analysis results
        """
        if not self.is_available:
            return PostMortemReport.from_error("Analyzer not available")
        
        start_time = datetime.now(timezone.utc)
        self._total_analyses += 1
        
        try:
            # Build prompt
            user_prompt = self._build_prompt(signal, exit_data, market_data)
            
            # Call Claude
            response = self._client.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=POSTMORTEM_SYSTEM_PROMPT,
            )
            
            # Parse response
            report = self._parse_response(response)
            report.signal_id = signal.get("signal_id", "")
            
            # Calculate latency
            latency_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            report.latency_ms = latency_ms
            report.model = self.model
            report.timestamp = datetime.now(timezone.utc).isoformat()
            
            self._successful_analyses += 1
            
            logger.info(f"Trade post-mortem completed in {latency_ms}ms: {report.format_compact()}")
            return report
            
        except Exception as e:
            logger.warning(f"Trade post-mortem failed: {e}")
            return PostMortemReport.from_error(str(e))
    
    async def analyze_trade_async(
        self,
        signal: Dict,
        exit_data: Dict,
        market_data: Optional[Dict] = None,
    ) -> PostMortemReport:
        """
        Analyze a completed trade asynchronously with timeout.
        
        Args:
            signal: Original signal dictionary
            exit_data: Exit information
            market_data: Optional additional market context
            
        Returns:
            PostMortemReport with analysis results
        """
        if not self.is_available:
            return PostMortemReport.from_error("Analyzer not available")
        
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self.analyze_trade,
                    signal,
                    exit_data,
                    market_data,
                ),
                timeout=self.timeout_seconds,
            )
            return result
            
        except asyncio.TimeoutError:
            logger.debug(f"Trade post-mortem timed out after {self.timeout_seconds}s")
            return PostMortemReport.from_error(f"Timeout ({self.timeout_seconds}s)")
        except Exception as e:
            logger.warning(f"Async post-mortem failed: {e}")
            return PostMortemReport.from_error(str(e))
    
    def add_to_batch(self, trade: Dict) -> Optional[List[Dict]]:
        """
        Add a trade to the batch buffer.
        
        Returns the batch when full, otherwise None.
        
        Args:
            trade: Completed trade dictionary
            
        Returns:
            List of trades if batch is full, None otherwise
        """
        self._pending_trades.append(trade)
        
        if len(self._pending_trades) >= self.batch_analysis_count:
            batch = self._pending_trades.copy()
            self._pending_trades = []
            return batch
        
        return None
    
    def _build_prompt(
        self,
        signal: Dict,
        exit_data: Dict,
        market_data: Optional[Dict],
    ) -> str:
        """Build the user prompt for post-mortem analysis."""
        # Signal data
        signal_type = signal.get("type", "unknown")
        direction = signal.get("direction", "unknown")
        confidence = signal.get("confidence", 0.0)
        entry_price = signal.get("entry_price", 0.0)
        stop_loss = signal.get("stop_loss", 0.0)
        take_profit = signal.get("take_profit", 0.0)
        entry_time = signal.get("timestamp", "unknown")
        
        # Exit data
        exit_price = exit_data.get("exit_price", entry_price)
        exit_time = exit_data.get("exit_time", "unknown")
        exit_reason = exit_data.get("exit_reason", "unknown")
        pnl_points = exit_data.get("pnl_points", 0.0)
        is_win = exit_data.get("is_win", pnl_points > 0)
        
        # Calculate P&L
        pnl_dollars = pnl_points * self.contracts * self.tick_value
        outcome = "WIN" if is_win else "LOSS"
        
        # Calculate distances
        if direction == "long":
            stop_distance = entry_price - stop_loss if stop_loss else 0
            target_distance = take_profit - entry_price if take_profit else 0
        else:
            stop_distance = stop_loss - entry_price if stop_loss else 0
            target_distance = entry_price - take_profit if take_profit else 0
        
        # Expected vs actual R:R
        expected_rr = target_distance / stop_distance if stop_distance > 0 else 0
        actual_rr = abs(pnl_points) / stop_distance if stop_distance > 0 and is_win else 0
        
        # Hold duration
        hold_duration = exit_data.get("hold_duration", "unknown")
        
        # Max favorable/adverse excursion
        mfe = exit_data.get("max_favorable_excursion", 0)
        mae = exit_data.get("max_adverse_excursion", 0)
        mfe_dollars = mfe * self.contracts * self.tick_value
        mae_dollars = mae * self.contracts * self.tick_value
        best_exit = exit_data.get("best_exit_price", exit_price)
        
        # Regime data
        regime = signal.get("regime", {})
        regime_type = regime.get("regime", "unknown")
        volatility = regime.get("volatility", "normal")
        session = regime.get("session", "unknown")
        
        # Indicators
        indicators = signal.get("indicators", {})
        rsi = indicators.get("rsi", 50.0) or 50.0
        atr = indicators.get("atr", 0.0) or 0.0
        
        # Custom indicators
        custom_features = signal.get("custom_features", {})
        custom_lines = []
        if custom_features:
            for key, value in list(custom_features.items())[:10]:
                if isinstance(value, float):
                    custom_lines.append(f"  - {key}: {value:.3f}")
                else:
                    custom_lines.append(f"  - {key}: {value}")
        custom_indicators = "\n".join(custom_lines) if custom_lines else "  (none)"
        
        return POSTMORTEM_USER_TEMPLATE.format(
            signal_type=signal_type,
            direction=direction,
            outcome=outcome,
            pnl_points=pnl_points,
            pnl_dollars=pnl_dollars,
            entry_price=entry_price,
            entry_time=entry_time,
            confidence=confidence,
            exit_price=exit_price,
            exit_time=exit_time,
            exit_reason=exit_reason,
            hold_duration=hold_duration,
            stop_loss=stop_loss,
            stop_distance=stop_distance,
            take_profit=take_profit,
            target_distance=target_distance,
            expected_rr=expected_rr,
            actual_rr=actual_rr,
            regime_type=regime_type,
            volatility=volatility,
            session=session,
            rsi=rsi,
            atr=atr,
            mfe=mfe,
            mae=mae,
            mfe_dollars=mfe_dollars,
            mae_dollars=mae_dollars,
            best_exit=best_exit,
            custom_indicators=custom_indicators,
        )
    
    def _parse_response(self, response: str) -> PostMortemReport:
        """Parse Claude's JSON response into PostMortemReport."""
        try:
            response = response.strip()
            
            # Handle markdown code blocks
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            
            data = json.loads(response)
            
            # Parse entry quality
            eq_data = data.get("entry_quality", {})
            entry_quality = EntryQuality(
                score=int(eq_data.get("score", 3)),
                comment=str(eq_data.get("comment", "")),
            )
            
            # Parse indicator accuracy
            ia_data = data.get("indicator_accuracy", {})
            indicator_accuracy = IndicatorAccuracy(
                correct_indicators=ia_data.get("correct_indicators", [])[:5],
                incorrect_indicators=ia_data.get("incorrect_indicators", [])[:5],
                comment=str(ia_data.get("comment", "")),
            )
            
            # Parse risk management
            rm_data = data.get("risk_management", {})
            risk_management = RiskManagement(
                stop_assessment=str(rm_data.get("stop_assessment", "appropriate")),
                target_assessment=str(rm_data.get("target_assessment", "appropriate")),
                comment=str(rm_data.get("comment", "")),
            )
            
            return PostMortemReport(
                outcome_analysis=str(data.get("outcome_analysis", "")),
                entry_quality=entry_quality,
                indicator_accuracy=indicator_accuracy,
                risk_management=risk_management,
                lessons=data.get("lessons", [])[:5],
                similar_setup_advice=str(data.get("similar_setup_advice", "")),
                confidence_calibration=str(data.get("confidence_calibration", "accurate")),
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse post-mortem response: {e}")
            if response:
                return PostMortemReport(
                    outcome_analysis=response[:300] if len(response) > 300 else response,
                )
            return PostMortemReport.from_error("Invalid response format")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get analyzer statistics."""
        success_rate = (
            self._successful_analyses / self._total_analyses
            if self._total_analyses > 0
            else 0
        )
        
        return {
            "total_analyses": self._total_analyses,
            "successful_analyses": self._successful_analyses,
            "success_rate": success_rate,
            "pending_batch_size": len(self._pending_trades),
            "is_available": self.is_available,
            "model": self.model,
        }


def get_postmortem_analyzer(config: Optional[Dict] = None) -> Optional[TradePostMortemAnalyzer]:
    """
    Factory function to create a post-mortem analyzer from configuration.
    
    Args:
        config: Configuration dictionary with llm_trade_postmortem settings
        
    Returns:
        TradePostMortemAnalyzer instance or None if disabled
    """
    if config is None:
        config = {}
    
    pm_config = config.get("llm_trade_postmortem", {})
    
    if not pm_config.get("enabled", False):
        logger.debug("Trade post-mortem analysis disabled in config")
        return None
    
    # Get contract/tick settings from prop_firm or defaults
    prop_firm = config.get("prop_firm", {})
    tick_value = prop_firm.get("mnq_tick_value", 2.0)
    
    return TradePostMortemAnalyzer(
        enabled=True,
        model=pm_config.get("model", "claude-sonnet-4-20250514"),
        timeout_seconds=pm_config.get("timeout_seconds", 10.0),
        min_pnl_threshold=pm_config.get("min_pnl_threshold", 50.0),
        send_to_telegram=pm_config.get("send_to_telegram", False),
        batch_analysis_count=pm_config.get("batch_analysis_count", 10),
        tick_value=tick_value,
    )


