"""
Pattern Recognition Engine

Identifies recurring patterns across trades:
- Winning/losing signal types by market regime
- Time-of-day performance patterns
- Streak analysis and causes
- Entry price optimization patterns
- Indicator combination effectiveness

Designed for batch analysis to find statistically significant patterns.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
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

PATTERN_RECOGNITION_SYSTEM_PROMPT = (
    ABSOLUTE_MODE_PROMPT
    + """\n\nROLE: Trading pattern analyst for an NQ/MNQ futures intraday system.

Task
- Analyze a batch of recent trades
- Identify statistically significant patterns
- Provide actionable recommendations

Rules
- Report only significant patterns
- Quantify patterns with numbers
- Consider sample size limits

Output ONLY valid JSON with this structure:
{
  "overall_assessment": "Brief summary of pattern quality",
  "sample_size": 50,
  "win_rate": 0.52,
  "patterns": [
    {
      "type": "signal_type|time_of_day|regime|entry_timing|indicator_combo|streak",
      "name": "Pattern Name",
      "description": "What the pattern shows",
      "data": {
        "win_rate": 0.65,
        "sample_size": 20,
        "expected_value": 15.5
      },
      "confidence": "high|medium|low",
      "actionable": true,
      "recommendation": "What to do about this pattern"
    }
  ],
  "signal_type_breakdown": {
    "sr_bounce": {"wins": 10, "losses": 5, "win_rate": 0.67, "avg_rr": 1.5},
    "momentum_short": {"wins": 3, "losses": 8, "win_rate": 0.27, "avg_rr": 0.8}
  },
  "session_breakdown": {
    "tokyo": {"wins": 5, "losses": 10, "win_rate": 0.33},
    "london": {"wins": 8, "losses": 7, "win_rate": 0.53},
    "new_york": {"wins": 12, "losses": 8, "win_rate": 0.60}
  },
  "recommendations": [
    {
      "priority": "high|medium|low",
      "action": "What to change",
      "rationale": "Why this helps",
      "expected_impact": "Expected improvement"
    }
  ],
  "warnings": ["Any concerning patterns to watch"]
}"""
)

PATTERN_RECOGNITION_USER_TEMPLATE = """Analyze these {trade_count} recent trades for patterns:

Overall Stats:
- Total Trades: {trade_count}
- Wins: {wins} ({win_rate:.1%})
- Losses: {losses}
- Average R:R: {avg_rr:.2f}
- Total P&L: {total_pnl:+.2f} pts

Signal Type Distribution:
{signal_type_stats}

Session Distribution:
{session_stats}

Regime Distribution:
{regime_stats}

Recent Streak: {streak_description}

Individual Trades (newest first):
{trade_details}

Custom Indicator Performance:
{indicator_stats}

Provide your pattern analysis as JSON."""


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class Pattern:
    """A detected trading pattern."""
    type: str  # signal_type, time_of_day, regime, entry_timing, indicator_combo, streak
    name: str
    description: str
    data: Dict[str, Any] = field(default_factory=dict)
    confidence: str = "medium"
    actionable: bool = True
    recommendation: str = ""


@dataclass
class Recommendation:
    """Actionable recommendation from pattern analysis."""
    priority: str  # high, medium, low
    action: str
    rationale: str
    expected_impact: str


@dataclass
class PatternReport:
    """Complete pattern recognition report."""
    overall_assessment: str = ""
    sample_size: int = 0
    win_rate: float = 0.0
    patterns: List[Pattern] = field(default_factory=list)
    signal_type_breakdown: Dict[str, Dict] = field(default_factory=dict)
    session_breakdown: Dict[str, Dict] = field(default_factory=dict)
    recommendations: List[Recommendation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Metadata
    model: str = ""
    latency_ms: int = 0
    error: Optional[str] = None
    timestamp: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "overall_assessment": self.overall_assessment,
            "sample_size": self.sample_size,
            "win_rate": self.win_rate,
            "patterns": [
                {
                    "type": p.type,
                    "name": p.name,
                    "description": p.description,
                    "data": p.data,
                    "confidence": p.confidence,
                    "actionable": p.actionable,
                    "recommendation": p.recommendation,
                }
                for p in self.patterns
            ],
            "signal_type_breakdown": self.signal_type_breakdown,
            "session_breakdown": self.session_breakdown,
            "recommendations": [
                {
                    "priority": r.priority,
                    "action": r.action,
                    "rationale": r.rationale,
                    "expected_impact": r.expected_impact,
                }
                for r in self.recommendations
            ],
            "warnings": self.warnings,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "timestamp": self.timestamp,
        }
    
    def format_telegram(self) -> str:
        """Format report for Telegram message."""
        if self.error:
            return f"PATTERN ANALYSIS ERROR: {self.error}"
        
        lines = []
        
        # Header
        lines.append(f"PATTERN ANALYSIS ({self.sample_size} trades)")
        lines.append(f"{self.overall_assessment}")

        # Win rate summary
        lines.append(f"\nWIN RATE: {self.win_rate:.1%}")

        # Top patterns (max 3)
        high_conf_patterns = [p for p in self.patterns if p.confidence == "high" and p.actionable]
        if high_conf_patterns:
            lines.append("\nKEY PATTERNS")
            for pattern in high_conf_patterns[:3]:
                lines.append(f"- {pattern.name}: {pattern.description}")
                if pattern.recommendation:
                    lines.append(f"  ACTION: {pattern.recommendation}")

        # Signal type breakdown (top 3)
        if self.signal_type_breakdown:
            lines.append("\nBY SIGNAL TYPE")
            sorted_types = sorted(
                self.signal_type_breakdown.items(),
                key=lambda x: x[1].get("win_rate", 0),
                reverse=True,
            )
            for sig_type, data in sorted_types[:3]:
                wr = data.get("win_rate", 0)
                lines.append(f"- {sig_type}: {wr:.0%} ({data.get('wins', 0)}W/{data.get('losses', 0)}L)")

        # Top recommendations
        if self.recommendations:
            lines.append("\nRECOMMENDATIONS")
            for rec in self.recommendations[:2]:
                lines.append(f"- {rec.priority.upper()}: {rec.action}")

        # Warnings
        if self.warnings:
            lines.append("\nWARNINGS")
            for warning in self.warnings[:2]:
                lines.append(f"- {warning}")
        
        return "\n".join(lines)
    
    @classmethod
    def from_error(cls, error: str) -> "PatternReport":
        """Create report from error."""
        return cls(error=error, timestamp=datetime.now(timezone.utc).isoformat())


# ============================================================================
# Pattern Recognizer
# ============================================================================

class PatternRecognizer:
    """
    LLM-powered pattern recognition across trades.
    
    Analyzes batches of trades to identify statistically significant patterns.
    
    Configuration:
    - enabled: Master toggle
    - model: Model to use
    - batch_size: Trades per batch analysis
    - lookback_trades: How many trades to consider
    - min_pattern_confidence: Threshold for reporting patterns
    """
    
    def __init__(
        self,
        enabled: bool = True,
        model: str = "claude-sonnet-4-20250514",
        timeout_seconds: float = 30.0,
        batch_size: int = 10,
        lookback_trades: int = 50,
        min_pattern_confidence: float = 0.7,
        send_to_telegram: bool = True,
    ):
        """
        Initialize the pattern recognizer.
        
        Args:
            enabled: Whether recognition is enabled
            model: Model to use
            timeout_seconds: Timeout for analysis
            batch_size: Trades per batch (triggers analysis)
            lookback_trades: Total trades to consider
            min_pattern_confidence: Minimum confidence to report patterns
            send_to_telegram: Whether to send results to Telegram
        """
        self.enabled = enabled
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size
        self.lookback_trades = lookback_trades
        self.min_pattern_confidence = min_pattern_confidence
        self.send_to_telegram = send_to_telegram
        
        # Initialize OpenAI client
        self._client: Optional[ClaudeClient] = None
        if enabled and OPENAI_AVAILABLE:
            try:
                self._client = get_claude_client()
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client for pattern recognition: {e}")
        
        # Trade buffer
        self._trade_buffer: List[Dict] = []
        self._trades_since_last_analysis = 0
        
        # Stats
        self._total_analyses = 0
        self._patterns_found = 0
        
        status = "enabled" if self._client else "disabled (client unavailable)"
        logger.info(f"PatternRecognizer initialized: {status}, batch_size={batch_size}")
    
    @property
    def is_available(self) -> bool:
        """Check if recognition is available."""
        return self.enabled and self._client is not None
    
    def add_trade(self, trade: Dict) -> bool:
        """
        Add a completed trade to the buffer.
        
        Args:
            trade: Completed trade dictionary
            
        Returns:
            True if batch analysis should be triggered
        """
        if not self.is_available:
            return False
        
        # Skip test trades
        if trade.get("_is_test", False):
            return False
        
        self._trade_buffer.append(trade)
        self._trades_since_last_analysis += 1
        
        # Trim buffer to lookback size
        if len(self._trade_buffer) > self.lookback_trades:
            self._trade_buffer = self._trade_buffer[-self.lookback_trades:]
        
        return self._trades_since_last_analysis >= self.batch_size
    
    def analyze_patterns(self, trades: Optional[List[Dict]] = None) -> PatternReport:
        """
        Analyze patterns in trades synchronously.
        
        Args:
            trades: List of trades to analyze (uses buffer if None)
            
        Returns:
            PatternReport with identified patterns
        """
        if not self.is_available:
            return PatternReport.from_error("Recognizer not available")
        
        if trades is None:
            trades = self._trade_buffer
        
        if not trades:
            return PatternReport.from_error("No trades to analyze")
        
        start_time = datetime.now(timezone.utc)
        self._total_analyses += 1
        self._trades_since_last_analysis = 0
        
        try:
            # Pre-compute statistics
            stats = self._compute_trade_stats(trades)
            
            # Build prompt
            user_prompt = self._build_prompt(trades, stats)
            
            # Call OpenAI
            response = self._client.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=PATTERN_RECOGNITION_SYSTEM_PROMPT,
            )
            
            # Parse response
            report = self._parse_response(response)
            
            # Calculate latency
            latency_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            report.latency_ms = latency_ms
            report.model = self.model
            report.timestamp = datetime.now(timezone.utc).isoformat()
            
            self._patterns_found += len(report.patterns)
            
            logger.info(
                f"Pattern analysis completed in {latency_ms}ms: "
                f"{len(report.patterns)} patterns, {len(report.recommendations)} recommendations"
            )
            return report
            
        except Exception as e:
            logger.warning(f"Pattern analysis failed: {e}")
            return PatternReport.from_error(str(e))
    
    async def analyze_patterns_async(
        self,
        trades: Optional[List[Dict]] = None,
    ) -> PatternReport:
        """
        Analyze patterns asynchronously with timeout.
        
        Args:
            trades: List of trades to analyze
            
        Returns:
            PatternReport with identified patterns
        """
        if not self.is_available:
            return PatternReport.from_error("Recognizer not available")
        
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self.analyze_patterns, trades),
                timeout=self.timeout_seconds,
            )
            return result
            
        except asyncio.TimeoutError:
            logger.debug(f"Pattern analysis timed out after {self.timeout_seconds}s")
            return PatternReport.from_error(f"Timeout ({self.timeout_seconds}s)")
        except Exception as e:
            logger.warning(f"Async pattern analysis failed: {e}")
            return PatternReport.from_error(str(e))
    
    def _compute_trade_stats(self, trades: List[Dict]) -> Dict[str, Any]:
        """Pre-compute trade statistics for the prompt."""
        stats = {
            "total": len(trades),
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "by_signal_type": defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0}),
            "by_session": defaultdict(lambda: {"wins": 0, "losses": 0}),
            "by_regime": defaultdict(lambda: {"wins": 0, "losses": 0}),
            "streak": [],
            "indicator_stats": defaultdict(lambda: {"wins": 0, "losses": 0}),
        }
        
        for trade in trades:
            is_win = trade.get("is_win", trade.get("pnl_points", 0) > 0)
            pnl = trade.get("pnl_points", 0)
            signal_type = trade.get("type", "unknown")
            session = trade.get("regime", {}).get("session", "unknown")
            regime = trade.get("regime", {}).get("regime", "unknown")
            
            if is_win:
                stats["wins"] += 1
            else:
                stats["losses"] += 1
            
            stats["total_pnl"] += pnl
            
            # By signal type
            if is_win:
                stats["by_signal_type"][signal_type]["wins"] += 1
            else:
                stats["by_signal_type"][signal_type]["losses"] += 1
            stats["by_signal_type"][signal_type]["pnl"] += pnl
            
            # By session
            if is_win:
                stats["by_session"][session]["wins"] += 1
            else:
                stats["by_session"][session]["losses"] += 1
            
            # By regime
            if is_win:
                stats["by_regime"][regime]["wins"] += 1
            else:
                stats["by_regime"][regime]["losses"] += 1
            
            # Track streak
            stats["streak"].append("W" if is_win else "L")
            
            # Indicator stats
            custom_features = trade.get("custom_features", {})
            for key, value in custom_features.items():
                if isinstance(value, (int, float)) and value > 0:
                    if is_win:
                        stats["indicator_stats"][key]["wins"] += 1
                    else:
                        stats["indicator_stats"][key]["losses"] += 1
        
        return stats
    
    def _build_prompt(self, trades: List[Dict], stats: Dict[str, Any]) -> str:
        """Build the user prompt for pattern analysis."""
        # Overall stats
        win_rate = stats["wins"] / stats["total"] if stats["total"] > 0 else 0
        avg_rr = 0
        rr_count = 0
        for trade in trades:
            rr = trade.get("actual_rr", 0)
            if rr > 0:
                avg_rr += rr
                rr_count += 1
        avg_rr = avg_rr / rr_count if rr_count > 0 else 0
        
        # Signal type stats
        signal_lines = []
        for sig_type, data in sorted(stats["by_signal_type"].items()):
            total = data["wins"] + data["losses"]
            wr = data["wins"] / total if total > 0 else 0
            signal_lines.append(f"  - {sig_type}: {data['wins']}W/{data['losses']}L ({wr:.0%}), P&L: {data['pnl']:+.1f} pts")
        signal_type_stats = "\n".join(signal_lines) if signal_lines else "  (no data)"
        
        # Session stats
        session_lines = []
        for session, data in sorted(stats["by_session"].items()):
            total = data["wins"] + data["losses"]
            wr = data["wins"] / total if total > 0 else 0
            session_lines.append(f"  - {session}: {data['wins']}W/{data['losses']}L ({wr:.0%})")
        session_stats = "\n".join(session_lines) if session_lines else "  (no data)"
        
        # Regime stats
        regime_lines = []
        for regime, data in sorted(stats["by_regime"].items()):
            total = data["wins"] + data["losses"]
            wr = data["wins"] / total if total > 0 else 0
            regime_lines.append(f"  - {regime}: {data['wins']}W/{data['losses']}L ({wr:.0%})")
        regime_stats = "\n".join(regime_lines) if regime_lines else "  (no data)"
        
        # Streak description
        streak_str = "".join(stats["streak"][-20:])  # Last 20
        current_streak = 0
        streak_type = None
        for outcome in reversed(stats["streak"]):
            if streak_type is None:
                streak_type = outcome
                current_streak = 1
            elif outcome == streak_type:
                current_streak += 1
            else:
                break
        streak_description = f"{current_streak} {'WIN' if streak_type == 'W' else 'LOSS'} streak (recent: {streak_str})"
        
        # Trade details (last 20)
        trade_lines = []
        for i, trade in enumerate(reversed(trades[:20])):
            is_win = trade.get("is_win", trade.get("pnl_points", 0) > 0)
            outcome = "WIN" if is_win else "LOSS"
            pnl = trade.get("pnl_points", 0)
            sig_type = trade.get("type", "unknown")
            session = trade.get("regime", {}).get("session", "?")
            regime = trade.get("regime", {}).get("regime", "?")
            conf = trade.get("confidence", 0)
            trade_lines.append(
                f"  {i+1}. {outcome} {pnl:+.1f}pts | {sig_type} | {session}/{regime} | conf:{conf:.0%}"
            )
        trade_details = "\n".join(trade_lines)
        
        # Indicator stats
        indicator_lines = []
        for ind, data in sorted(stats["indicator_stats"].items(), key=lambda x: x[1]["wins"] + x[1]["losses"], reverse=True)[:10]:
            total = data["wins"] + data["losses"]
            wr = data["wins"] / total if total > 0 else 0
            indicator_lines.append(f"  - {ind}: {data['wins']}W/{data['losses']}L ({wr:.0%})")
        indicator_stats = "\n".join(indicator_lines) if indicator_lines else "  (no indicator data)"
        
        return PATTERN_RECOGNITION_USER_TEMPLATE.format(
            trade_count=stats["total"],
            wins=stats["wins"],
            win_rate=win_rate,
            losses=stats["losses"],
            avg_rr=avg_rr,
            total_pnl=stats["total_pnl"],
            signal_type_stats=signal_type_stats,
            session_stats=session_stats,
            regime_stats=regime_stats,
            streak_description=streak_description,
            trade_details=trade_details,
            indicator_stats=indicator_stats,
        )
    
    def _parse_response(self, response: str) -> PatternReport:
        """Parse the model's JSON response into PatternReport."""
        try:
            response = response.strip()
            
            # Handle markdown code blocks
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            
            data = json.loads(response)
            
            # Parse patterns
            patterns = []
            for p_data in data.get("patterns", []):
                confidence = str(p_data.get("confidence", "medium"))
                # Filter by confidence threshold
                conf_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
                if conf_map.get(confidence, 0.5) >= self.min_pattern_confidence:
                    patterns.append(Pattern(
                        type=str(p_data.get("type", "unknown")),
                        name=str(p_data.get("name", "")),
                        description=str(p_data.get("description", "")),
                        data=p_data.get("data", {}),
                        confidence=confidence,
                        actionable=bool(p_data.get("actionable", True)),
                        recommendation=str(p_data.get("recommendation", "")),
                    ))
            
            # Parse recommendations
            recommendations = []
            for r_data in data.get("recommendations", []):
                recommendations.append(Recommendation(
                    priority=str(r_data.get("priority", "medium")),
                    action=str(r_data.get("action", "")),
                    rationale=str(r_data.get("rationale", "")),
                    expected_impact=str(r_data.get("expected_impact", "")),
                ))
            
            return PatternReport(
                overall_assessment=str(data.get("overall_assessment", "")),
                sample_size=int(data.get("sample_size", 0)),
                win_rate=float(data.get("win_rate", 0)),
                patterns=patterns,
                signal_type_breakdown=data.get("signal_type_breakdown", {}),
                session_breakdown=data.get("session_breakdown", {}),
                recommendations=recommendations,
                warnings=data.get("warnings", []),
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse pattern analysis response: {e}")
            return PatternReport.from_error("Invalid response format")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get recognizer statistics."""
        return {
            "total_analyses": self._total_analyses,
            "patterns_found": self._patterns_found,
            "buffer_size": len(self._trade_buffer),
            "trades_since_last": self._trades_since_last_analysis,
            "is_available": self.is_available,
            "model": self.model,
        }


def get_pattern_recognizer(config: Optional[Dict] = None) -> Optional[PatternRecognizer]:
    """
    Factory function to create a pattern recognizer from configuration.
    
    Args:
        config: Configuration dictionary with llm_pattern_recognition settings
        
    Returns:
        PatternRecognizer instance or None if disabled
    """
    if config is None:
        config = {}
    
    pr_config = config.get("llm_pattern_recognition", {})
    
    if not pr_config.get("enabled", False):
        logger.debug("Pattern recognition disabled in config")
        return None
    
    return PatternRecognizer(
        enabled=True,
        model=pr_config.get("model", "claude-sonnet-4-20250514"),
        timeout_seconds=pr_config.get("timeout_seconds", 30.0),
        batch_size=pr_config.get("batch_size", 10),
        lookback_trades=pr_config.get("lookback_trades", 50),
        min_pattern_confidence=pr_config.get("min_pattern_confidence", 0.7),
        send_to_telegram=pr_config.get("send_to_telegram", True),
    )


