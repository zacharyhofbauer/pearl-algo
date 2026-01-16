"""
Adaptive Parameter Tuner

Suggests config changes based on performance:
- Confidence threshold adjustments per signal type
- Stop loss / take profit ratio changes
- Position sizing tweaks
- Session-based parameter variations
- Enable/disable signal types based on performance

Designed for periodic (daily) analysis with manual approval.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger

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

ADAPTIVE_TUNING_SYSTEM_PROMPT = """You are a trading system optimizer for an NQ/MNQ futures intraday trading system.

Your role is to analyze performance data and suggest CONFIG CHANGES to improve results:
1. Confidence thresholds per signal type
2. Stop loss / take profit distances
3. Position sizing rules
4. Session-based adjustments
5. Signal type enable/disable recommendations

RULES:
- Be conservative - suggest small incremental changes
- Quantify expected impact where possible
- Consider sample size limitations
- Never suggest changes that break risk limits
- Each change must be reversible
- Focus on exploitable, statistically significant patterns

Config file structure reference:
- signals.min_confidence: Overall minimum confidence
- signals.min_risk_reward: Minimum R:R ratio
- strategy.enabled_signals: List of enabled signal types
- strategy.disabled_signals: List of disabled signal types
- strategy.base_contracts: Base position size
- risk.stop_loss_atr_multiplier: Stop distance multiplier
- risk.take_profit_risk_reward: Target R:R for TP

Output ONLY valid JSON:
{
  "analysis_summary": "Brief summary of findings",
  "sample_period": "Date range analyzed",
  "sample_size": 50,
  "current_performance": {
    "win_rate": 0.52,
    "avg_rr": 1.2,
    "sharpe_ratio": null
  },
  "suggestions": [
    {
      "id": "unique_id",
      "priority": "high|medium|low",
      "category": "confidence|risk|sizing|signal_type|session",
      "config_path": "signals.min_confidence",
      "current_value": 0.50,
      "suggested_value": 0.55,
      "rationale": "Why this change helps",
      "expected_impact": "Expected improvement",
      "risk_level": "low|medium|high",
      "sample_support": 30,
      "reversible": true
    }
  ],
  "signal_type_recommendations": {
    "sr_bounce": {"action": "keep|adjust|disable", "reason": "Why"},
    "momentum_long": {"action": "disable", "reason": "0% win rate in 10 trades"}
  },
  "session_recommendations": {
    "tokyo": "Consider reducing position size",
    "london": "Good performance, no changes",
    "new_york": "Primary session - maintain focus"
  },
  "warnings": ["Any concerns about the data or suggestions"],
  "next_review": "When to review again"
}"""

ADAPTIVE_TUNING_USER_TEMPLATE = """Analyze performance and suggest config optimizations:

Analysis Period: {period}
Total Trades: {total_trades}

Current Configuration:
- Min Confidence: {min_confidence}
- Min R:R: {min_rr}
- Base Contracts: {base_contracts}
- Stop ATR Mult: {stop_atr_mult}
- TP R:R Target: {tp_rr_target}

Enabled Signals: {enabled_signals}
Disabled Signals: {disabled_signals}

Overall Performance:
- Win Rate: {win_rate:.1%}
- Average R:R Achieved: {avg_rr:.2f}
- Total P&L: {total_pnl:+.1f} points

By Signal Type:
{signal_type_performance}

By Session:
{session_performance}

By Regime:
{regime_performance}

Confidence Calibration:
{confidence_calibration}

Recent Trends:
{recent_trends}

Suggest config optimizations as JSON:"""


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ConfigSuggestion:
    """A suggested configuration change."""
    id: str
    priority: str  # high, medium, low
    category: str  # confidence, risk, sizing, signal_type, session
    config_path: str
    current_value: Any
    suggested_value: Any
    rationale: str
    expected_impact: str
    risk_level: str = "low"
    sample_support: int = 0
    reversible: bool = True


@dataclass
class TuningReport:
    """Complete tuning analysis report."""
    analysis_summary: str = ""
    sample_period: str = ""
    sample_size: int = 0
    current_performance: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[ConfigSuggestion] = field(default_factory=list)
    signal_type_recommendations: Dict[str, Dict] = field(default_factory=dict)
    session_recommendations: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    next_review: str = ""
    
    # Metadata
    model: str = ""
    latency_ms: int = 0
    error: Optional[str] = None
    timestamp: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "analysis_summary": self.analysis_summary,
            "sample_period": self.sample_period,
            "sample_size": self.sample_size,
            "current_performance": self.current_performance,
            "suggestions": [
                {
                    "id": s.id,
                    "priority": s.priority,
                    "category": s.category,
                    "config_path": s.config_path,
                    "current_value": s.current_value,
                    "suggested_value": s.suggested_value,
                    "rationale": s.rationale,
                    "expected_impact": s.expected_impact,
                    "risk_level": s.risk_level,
                    "sample_support": s.sample_support,
                    "reversible": s.reversible,
                }
                for s in self.suggestions
            ],
            "signal_type_recommendations": self.signal_type_recommendations,
            "session_recommendations": self.session_recommendations,
            "warnings": self.warnings,
            "next_review": self.next_review,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "timestamp": self.timestamp,
        }
    
    def format_telegram(self) -> str:
        """Format report for Telegram message."""
        if self.error:
            return f"❌ Tuning analysis error: {self.error}"
        
        lines = []
        
        # Header
        lines.append(f"🔧 *Adaptive Tuning Report*")
        lines.append(f"📊 {self.sample_size} trades analyzed")
        
        # Summary
        if self.analysis_summary:
            lines.append(f"\n{self.analysis_summary}")
        
        # Current performance
        perf = self.current_performance
        if perf:
            wr = perf.get("win_rate", 0)
            rr = perf.get("avg_rr", 0)
            lines.append(f"\n*Current:* {wr:.0%} WR, {rr:.1f} R:R")
        
        # Top suggestions (max 3)
        high_priority = [s for s in self.suggestions if s.priority == "high"]
        if high_priority:
            lines.append(f"\n*High Priority Suggestions:*")
            for sug in high_priority[:3]:
                lines.append(f"  🔴 `{sug.config_path}`")
                lines.append(f"     {sug.current_value} → {sug.suggested_value}")
                lines.append(f"     _{sug.rationale}_")
        
        medium_priority = [s for s in self.suggestions if s.priority == "medium"]
        if medium_priority:
            lines.append(f"\n*Medium Priority:*")
            for sug in medium_priority[:2]:
                lines.append(f"  🟡 `{sug.config_path}`: {sug.current_value} → {sug.suggested_value}")
        
        # Signal type recommendations (only actionable)
        disable_signals = [
            (k, v) for k, v in self.signal_type_recommendations.items()
            if v.get("action") == "disable"
        ]
        if disable_signals:
            lines.append(f"\n*Consider Disabling:*")
            for sig, rec in disable_signals[:2]:
                lines.append(f"  ⛔ {sig}: {rec.get('reason', '')}")
        
        # Warnings
        if self.warnings:
            lines.append(f"\n*⚠️ Warnings:*")
            for warning in self.warnings[:2]:
                lines.append(f"  • {warning}")
        
        # Next review
        if self.next_review:
            lines.append(f"\n📅 Next review: {self.next_review}")
        
        return "\n".join(lines)
    
    @classmethod
    def from_error(cls, error: str) -> "TuningReport":
        """Create report from error."""
        return cls(error=error, timestamp=datetime.now(timezone.utc).isoformat())


# ============================================================================
# Adaptive Parameter Tuner
# ============================================================================

class AdaptiveParameterTuner:
    """
    LLM-powered adaptive parameter tuning.
    
    Analyzes performance and suggests config optimizations.
    
    Configuration:
    - enabled: Master toggle
    - model: Model to use
    - analysis_interval_hours: How often to analyze (default: 24h)
    - auto_apply: Whether to auto-apply suggestions (default: False)
    - min_sample_size: Minimum trades before suggesting changes
    - conservative_mode: Only suggest small incremental changes
    """
    
    def __init__(
        self,
        enabled: bool = True,
        model: str = "claude-sonnet-4-20250514",
        timeout_seconds: float = 60.0,
        analysis_interval_hours: int = 24,
        auto_apply: bool = False,
        min_sample_size: int = 30,
        conservative_mode: bool = True,
    ):
        """
        Initialize the adaptive tuner.
        
        Args:
            enabled: Whether tuning is enabled
            model: Model to use
            timeout_seconds: Timeout for analysis
            analysis_interval_hours: How often to run analysis
            auto_apply: Whether to auto-apply suggestions
            min_sample_size: Minimum trades before suggestions
            conservative_mode: Limit to small incremental changes
        """
        self.enabled = enabled
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.analysis_interval_hours = analysis_interval_hours
        self.auto_apply = auto_apply
        self.min_sample_size = min_sample_size
        self.conservative_mode = conservative_mode
        
        # Initialize OpenAI client
        self._client: Optional[ClaudeClient] = None
        if enabled and OPENAI_AVAILABLE:
            try:
                self._client = get_claude_client()
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client for adaptive tuning: {e}")
        
        # Track when last analysis was run
        self._last_analysis: Optional[datetime] = None
        self._last_report: Optional[TuningReport] = None
        
        # Stats
        self._total_analyses = 0
        self._suggestions_generated = 0
        self._suggestions_applied = 0
        
        status = "enabled" if self._client else "disabled (client unavailable)"
        logger.info(f"AdaptiveParameterTuner initialized: {status}, interval={analysis_interval_hours}h")
    
    @property
    def is_available(self) -> bool:
        """Check if tuning is available."""
        return self.enabled and self._client is not None
    
    def should_run_analysis(self) -> bool:
        """Check if it's time to run analysis."""
        if not self.is_available:
            return False
        
        if self._last_analysis is None:
            return True
        
        hours_since = (datetime.now(timezone.utc) - self._last_analysis).total_seconds() / 3600
        return hours_since >= self.analysis_interval_hours
    
    def analyze_and_suggest(
        self,
        trades: List[Dict],
        current_config: Dict,
    ) -> TuningReport:
        """
        Analyze performance and suggest config changes synchronously.
        
        Args:
            trades: List of completed trades
            current_config: Current configuration dictionary
            
        Returns:
            TuningReport with suggestions
        """
        if not self.is_available:
            return TuningReport.from_error("Tuner not available")
        
        if len(trades) < self.min_sample_size:
            return TuningReport.from_error(
                f"Insufficient data: {len(trades)} trades (need {self.min_sample_size})"
            )
        
        start_time = datetime.now(timezone.utc)
        self._total_analyses += 1
        self._last_analysis = start_time
        
        try:
            # Pre-compute performance stats
            stats = self._compute_performance_stats(trades)
            
            # Build prompt
            user_prompt = self._build_prompt(trades, current_config, stats)
            
            # Call OpenAI
            response = self._client.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=ADAPTIVE_TUNING_SYSTEM_PROMPT,
            )
            
            # Parse response
            report = self._parse_response(response)
            
            # Calculate latency
            latency_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            report.latency_ms = latency_ms
            report.model = self.model
            report.timestamp = datetime.now(timezone.utc).isoformat()
            
            self._suggestions_generated += len(report.suggestions)
            self._last_report = report
            
            logger.info(
                f"Adaptive tuning completed in {latency_ms}ms: "
                f"{len(report.suggestions)} suggestions"
            )
            return report
            
        except Exception as e:
            logger.warning(f"Adaptive tuning failed: {e}")
            return TuningReport.from_error(str(e))
    
    async def analyze_and_suggest_async(
        self,
        trades: List[Dict],
        current_config: Dict,
    ) -> TuningReport:
        """
        Analyze performance asynchronously with timeout.
        
        Args:
            trades: List of completed trades
            current_config: Current configuration
            
        Returns:
            TuningReport with suggestions
        """
        if not self.is_available:
            return TuningReport.from_error("Tuner not available")
        
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self.analyze_and_suggest,
                    trades,
                    current_config,
                ),
                timeout=self.timeout_seconds,
            )
            return result
            
        except asyncio.TimeoutError:
            logger.debug(f"Adaptive tuning timed out after {self.timeout_seconds}s")
            return TuningReport.from_error(f"Timeout ({self.timeout_seconds}s)")
        except Exception as e:
            logger.warning(f"Async adaptive tuning failed: {e}")
            return TuningReport.from_error(str(e))
    
    def _compute_performance_stats(self, trades: List[Dict]) -> Dict[str, Any]:
        """Pre-compute performance statistics."""
        from collections import defaultdict
        
        stats = {
            "total": len(trades),
            "wins": 0,
            "total_pnl": 0.0,
            "rr_sum": 0.0,
            "rr_count": 0,
            "by_signal_type": defaultdict(lambda: {
                "wins": 0, "losses": 0, "pnl": 0.0, "rr_sum": 0.0, "rr_count": 0,
                "conf_wins": [], "conf_losses": [],
            }),
            "by_session": defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0}),
            "by_regime": defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0}),
            "confidence_buckets": defaultdict(lambda: {"wins": 0, "losses": 0}),
        }
        
        for trade in trades:
            is_win = trade.get("is_win", trade.get("pnl_points", 0) > 0)
            pnl = trade.get("pnl_points", 0)
            signal_type = trade.get("type", "unknown")
            session = trade.get("regime", {}).get("session", "unknown")
            regime = trade.get("regime", {}).get("regime", "unknown")
            confidence = trade.get("confidence", 0.5)
            actual_rr = trade.get("actual_rr", 0)
            
            if is_win:
                stats["wins"] += 1
            stats["total_pnl"] += pnl
            
            if actual_rr > 0:
                stats["rr_sum"] += actual_rr
                stats["rr_count"] += 1
            
            # By signal type
            st = stats["by_signal_type"][signal_type]
            if is_win:
                st["wins"] += 1
                st["conf_wins"].append(confidence)
            else:
                st["losses"] += 1
                st["conf_losses"].append(confidence)
            st["pnl"] += pnl
            if actual_rr > 0:
                st["rr_sum"] += actual_rr
                st["rr_count"] += 1
            
            # By session
            if is_win:
                stats["by_session"][session]["wins"] += 1
            else:
                stats["by_session"][session]["losses"] += 1
            stats["by_session"][session]["pnl"] += pnl
            
            # By regime
            if is_win:
                stats["by_regime"][regime]["wins"] += 1
            else:
                stats["by_regime"][regime]["losses"] += 1
            stats["by_regime"][regime]["pnl"] += pnl
            
            # Confidence buckets
            bucket = f"{int(confidence * 10) * 10}-{int(confidence * 10) * 10 + 10}%"
            if is_win:
                stats["confidence_buckets"][bucket]["wins"] += 1
            else:
                stats["confidence_buckets"][bucket]["losses"] += 1
        
        return stats
    
    def _build_prompt(
        self,
        trades: List[Dict],
        current_config: Dict,
        stats: Dict[str, Any],
    ) -> str:
        """Build the user prompt for tuning analysis."""
        # Time period
        if trades:
            first_ts = trades[0].get("timestamp", "")
            last_ts = trades[-1].get("timestamp", "")
            period = f"{first_ts[:10]} to {last_ts[:10]}" if first_ts and last_ts else "recent"
        else:
            period = "unknown"
        
        # Current config values
        signals_config = current_config.get("signals", {})
        strategy_config = current_config.get("strategy", {})
        risk_config = current_config.get("risk", {})
        
        min_confidence = signals_config.get("min_confidence", 0.5)
        min_rr = signals_config.get("min_risk_reward", 1.2)
        base_contracts = strategy_config.get("base_contracts", 5)
        stop_atr_mult = risk_config.get("stop_loss_atr_multiplier", 1.5)
        tp_rr_target = risk_config.get("take_profit_risk_reward", 1.5)
        enabled_signals = strategy_config.get("enabled_signals", [])
        disabled_signals = strategy_config.get("disabled_signals", [])
        
        # Overall performance
        win_rate = stats["wins"] / stats["total"] if stats["total"] > 0 else 0
        avg_rr = stats["rr_sum"] / stats["rr_count"] if stats["rr_count"] > 0 else 0
        
        # Signal type performance
        sig_lines = []
        for sig_type, data in sorted(stats["by_signal_type"].items()):
            total = data["wins"] + data["losses"]
            wr = data["wins"] / total if total > 0 else 0
            st_rr = data["rr_sum"] / data["rr_count"] if data["rr_count"] > 0 else 0
            avg_win_conf = sum(data["conf_wins"]) / len(data["conf_wins"]) if data["conf_wins"] else 0
            avg_loss_conf = sum(data["conf_losses"]) / len(data["conf_losses"]) if data["conf_losses"] else 0
            sig_lines.append(
                f"  - {sig_type}: {wr:.0%} WR ({data['wins']}W/{data['losses']}L), "
                f"R:R={st_rr:.1f}, P&L={data['pnl']:+.1f}pts, "
                f"Avg Conf: win={avg_win_conf:.0%} loss={avg_loss_conf:.0%}"
            )
        signal_type_performance = "\n".join(sig_lines) if sig_lines else "  (no data)"
        
        # Session performance
        sess_lines = []
        for session, data in sorted(stats["by_session"].items()):
            total = data["wins"] + data["losses"]
            wr = data["wins"] / total if total > 0 else 0
            sess_lines.append(
                f"  - {session}: {wr:.0%} WR ({data['wins']}W/{data['losses']}L), P&L={data['pnl']:+.1f}pts"
            )
        session_performance = "\n".join(sess_lines) if sess_lines else "  (no data)"
        
        # Regime performance
        reg_lines = []
        for regime, data in sorted(stats["by_regime"].items()):
            total = data["wins"] + data["losses"]
            wr = data["wins"] / total if total > 0 else 0
            reg_lines.append(
                f"  - {regime}: {wr:.0%} WR ({data['wins']}W/{data['losses']}L), P&L={data['pnl']:+.1f}pts"
            )
        regime_performance = "\n".join(reg_lines) if reg_lines else "  (no data)"
        
        # Confidence calibration
        conf_lines = []
        for bucket, data in sorted(stats["confidence_buckets"].items()):
            total = data["wins"] + data["losses"]
            wr = data["wins"] / total if total > 0 else 0
            conf_lines.append(f"  - {bucket}: {wr:.0%} WR ({total} trades)")
        confidence_calibration = "\n".join(conf_lines) if conf_lines else "  (no data)"
        
        # Recent trends (last 10 vs previous 10)
        if len(trades) >= 20:
            recent_10 = trades[-10:]
            prev_10 = trades[-20:-10]
            recent_wr = sum(1 for t in recent_10 if t.get("is_win", False)) / 10
            prev_wr = sum(1 for t in prev_10 if t.get("is_win", False)) / 10
            trend = "improving" if recent_wr > prev_wr else ("declining" if recent_wr < prev_wr else "stable")
            recent_trends = f"Win rate trend: {trend} (recent {recent_wr:.0%} vs prior {prev_wr:.0%})"
        else:
            recent_trends = "Insufficient data for trend analysis"
        
        return ADAPTIVE_TUNING_USER_TEMPLATE.format(
            period=period,
            total_trades=stats["total"],
            min_confidence=min_confidence,
            min_rr=min_rr,
            base_contracts=base_contracts,
            stop_atr_mult=stop_atr_mult,
            tp_rr_target=tp_rr_target,
            enabled_signals=", ".join(enabled_signals) or "(none)",
            disabled_signals=", ".join(disabled_signals) or "(none)",
            win_rate=win_rate,
            avg_rr=avg_rr,
            total_pnl=stats["total_pnl"],
            signal_type_performance=signal_type_performance,
            session_performance=session_performance,
            regime_performance=regime_performance,
            confidence_calibration=confidence_calibration,
            recent_trends=recent_trends,
        )
    
    def _parse_response(self, response: str) -> TuningReport:
        """Parse the model's JSON response into TuningReport."""
        try:
            response = response.strip()
            
            # Handle markdown code blocks
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            
            data = json.loads(response)
            
            # Parse suggestions
            suggestions = []
            for s_data in data.get("suggestions", []):
                suggestions.append(ConfigSuggestion(
                    id=str(s_data.get("id", "")),
                    priority=str(s_data.get("priority", "medium")),
                    category=str(s_data.get("category", "other")),
                    config_path=str(s_data.get("config_path", "")),
                    current_value=s_data.get("current_value"),
                    suggested_value=s_data.get("suggested_value"),
                    rationale=str(s_data.get("rationale", "")),
                    expected_impact=str(s_data.get("expected_impact", "")),
                    risk_level=str(s_data.get("risk_level", "low")),
                    sample_support=int(s_data.get("sample_support", 0)),
                    reversible=bool(s_data.get("reversible", True)),
                ))
            
            return TuningReport(
                analysis_summary=str(data.get("analysis_summary", "")),
                sample_period=str(data.get("sample_period", "")),
                sample_size=int(data.get("sample_size", 0)),
                current_performance=data.get("current_performance", {}),
                suggestions=suggestions,
                signal_type_recommendations=data.get("signal_type_recommendations", {}),
                session_recommendations=data.get("session_recommendations", {}),
                warnings=data.get("warnings", []),
                next_review=str(data.get("next_review", "")),
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tuning response: {e}")
            return TuningReport.from_error("Invalid response format")
    
    def get_last_report(self) -> Optional[TuningReport]:
        """Get the most recent tuning report."""
        return self._last_report
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tuner statistics."""
        return {
            "total_analyses": self._total_analyses,
            "suggestions_generated": self._suggestions_generated,
            "suggestions_applied": self._suggestions_applied,
            "last_analysis": self._last_analysis.isoformat() if self._last_analysis else None,
            "is_available": self.is_available,
            "model": self.model,
        }


def get_adaptive_tuner(config: Optional[Dict] = None) -> Optional[AdaptiveParameterTuner]:
    """
    Factory function to create an adaptive tuner from configuration.
    
    Args:
        config: Configuration dictionary with llm_adaptive_tuning settings
        
    Returns:
        AdaptiveParameterTuner instance or None if disabled
    """
    if config is None:
        config = {}
    
    at_config = config.get("llm_adaptive_tuning", {})
    
    if not at_config.get("enabled", False):
        logger.debug("Adaptive tuning disabled in config")
        return None
    
    return AdaptiveParameterTuner(
        enabled=True,
        model=at_config.get("model", "claude-sonnet-4-20250514"),
        timeout_seconds=at_config.get("timeout_seconds", 60.0),
        analysis_interval_hours=at_config.get("analysis_interval_hours", 24),
        auto_apply=at_config.get("auto_apply", False),
        min_sample_size=at_config.get("min_sample_size", 30),
        conservative_mode=at_config.get("conservative_mode", True),
    )


