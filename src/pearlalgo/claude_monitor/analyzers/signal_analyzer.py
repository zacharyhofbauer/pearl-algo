"""
Signal Analyzer - Analyzes signal quality and trading performance.

Uses Claude to:
- Detect win rate degradation per signal type
- Analyze R:R ratio vs historical baseline
- Identify entry timing quality issues
- Calibrate confidence thresholds
- Detect duplicate signal patterns
- Correlate volume/volatility with signal performance
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.utils.claude_client import ClaudeClient


# System prompt for signal analysis
SIGNAL_ANALYSIS_PROMPT = """You are an expert trading analyst reviewing signal quality for an automated MNQ futures trading system.

Analyze the provided signals and performance data. Focus on:
1. Win rate by signal type (identify underperformers)
2. R:R ratio effectiveness (actual vs expected)
3. Entry timing patterns (which setups work best)
4. Confidence calibration (high confidence = high win rate?)
5. Market condition correlation (trending vs ranging)

Provide actionable insights and specific parameter recommendations.

Return JSON with this structure:
{
    "status": "healthy|degraded|critical",
    "findings": [
        {
            "type": "win_rate_degradation|rr_issue|timing_pattern|confidence_calibration|regime_mismatch",
            "severity": "critical|high|medium|low|info",
            "title": "Brief title",
            "description": "Detailed description",
            "signal_type": "affected signal type or null",
            "data": {"metric": "value"},
            "recommendation": "What to do about it"
        }
    ],
    "recommendations": [
        {
            "priority": "high|medium|low",
            "title": "Recommendation title",
            "description": "What to change",
            "config_path": "signals.min_confidence",
            "old_value": 0.5,
            "new_value": 0.6,
            "rationale": "Why this helps",
            "expected_impact": "Expected improvement"
        }
    ],
    "summary": {
        "total_signals": 0,
        "overall_win_rate": 0.0,
        "best_signal_type": "type",
        "worst_signal_type": "type",
        "key_insight": "One sentence summary"
    }
}"""


class SignalAnalyzer:
    """
    Analyzes signal quality and trading performance.
    
    Detects:
    - Win rate degradation per signal type
    - R:R ratio issues
    - Entry timing patterns
    - Confidence calibration problems
    - Duplicate signal patterns
    - Volume/volatility correlations
    """
    
    def __init__(
        self,
        claude_client: Optional["ClaudeClient"] = None,
        lookback_hours: int = 24,
        min_signals_for_analysis: int = 5,
    ):
        """
        Initialize signal analyzer.
        
        Args:
            claude_client: Claude API client for AI analysis
            lookback_hours: Default lookback period for analysis
            min_signals_for_analysis: Minimum signals needed for meaningful analysis
        """
        self._claude = claude_client
        self.lookback_hours = lookback_hours
        self.min_signals = min_signals_for_analysis
        
        # Baselines for comparison
        self._baseline_win_rates: Dict[str, float] = {
            "sr_bounce": 0.60,
            "mean_reversion_long": 0.55,
            "mean_reversion_short": 0.55,
            "momentum_short": 0.50,
            "breakout_long": 0.45,
            "breakout_short": 0.45,
            "vwap_reversion": 0.50,
        }
        
        self._baseline_rr = 1.5  # Expected R:R ratio
    
    async def analyze(
        self,
        agent_state: Dict[str, Any],
        signals: Optional[List[Dict[str, Any]]] = None,
        performance: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze signal quality.
        
        Args:
            agent_state: Current agent state
            signals: Recent signals to analyze
            performance: Performance metrics
            
        Returns:
            Analysis results with findings and recommendations
        """
        signals = signals or []
        performance = performance or {}
        
        # If not enough signals, return basic analysis
        if len(signals) < self.min_signals:
            return self._basic_analysis(signals, agent_state)
        
        # Calculate metrics locally first
        local_analysis = self._calculate_metrics(signals, performance)
        
        # If Claude available, enhance with AI analysis
        if self._claude:
            try:
                ai_analysis = await self._claude_analysis(signals, performance, agent_state, local_analysis)
                return self._merge_analysis(local_analysis, ai_analysis)
            except Exception as e:
                logger.warning(f"Claude analysis failed, using local analysis: {e}")
        
        return local_analysis
    
    def _basic_analysis(
        self,
        signals: List[Dict[str, Any]],
        agent_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return basic analysis when not enough data."""
        return {
            "status": "insufficient_data",
            "timestamp": get_utc_timestamp(),
            "findings": [],
            "recommendations": [],
            "summary": {
                "total_signals": len(signals),
                "overall_win_rate": None,
                "key_insight": f"Need at least {self.min_signals} signals for analysis"
            },
        }
    
    def _calculate_metrics(
        self,
        signals: List[Dict[str, Any]],
        performance: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate signal metrics locally."""
        findings = []
        recommendations = []
        
        # Group signals by type
        by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for sig in signals:
            sig_type = sig.get("signal_type") or sig.get("type") or "unknown"
            by_type[sig_type].append(sig)
        
        # Calculate metrics per type
        type_metrics: Dict[str, Dict[str, Any]] = {}
        total_wins = 0
        total_losses = 0
        
        for sig_type, type_signals in by_type.items():
            wins = sum(1 for s in type_signals if s.get("outcome") == "win" or s.get("result") == "win")
            losses = sum(1 for s in type_signals if s.get("outcome") == "loss" or s.get("result") == "loss")
            total = wins + losses
            
            total_wins += wins
            total_losses += losses
            
            if total > 0:
                win_rate = wins / total
                type_metrics[sig_type] = {
                    "count": len(type_signals),
                    "wins": wins,
                    "losses": losses,
                    "win_rate": win_rate,
                }
                
                # Check against baseline
                baseline = self._baseline_win_rates.get(sig_type, 0.5)
                if total >= 5 and win_rate < baseline - 0.1:
                    findings.append({
                        "type": "win_rate_degradation",
                        "severity": "high" if win_rate < baseline - 0.2 else "medium",
                        "title": f"Low win rate for {sig_type}",
                        "description": f"{sig_type} win rate ({win_rate:.1%}) is below baseline ({baseline:.1%})",
                        "signal_type": sig_type,
                        "data": {"win_rate": win_rate, "baseline": baseline, "sample_size": total},
                        "recommendation": f"Consider disabling {sig_type} or adjusting parameters",
                    })
        
        # Calculate overall metrics
        total_resolved = total_wins + total_losses
        overall_win_rate = total_wins / total_resolved if total_resolved > 0 else None
        
        # Determine best/worst types
        best_type = None
        worst_type = None
        best_rate = 0
        worst_rate = 1
        
        for sig_type, metrics in type_metrics.items():
            if metrics["wins"] + metrics["losses"] >= 3:  # Min sample
                if metrics["win_rate"] > best_rate:
                    best_rate = metrics["win_rate"]
                    best_type = sig_type
                if metrics["win_rate"] < worst_rate:
                    worst_rate = metrics["win_rate"]
                    worst_type = sig_type
        
        # Check confidence calibration
        high_conf_signals = [s for s in signals if (s.get("confidence") or 0) >= 0.8]
        low_conf_signals = [s for s in signals if 0.5 <= (s.get("confidence") or 0) < 0.7]
        
        if len(high_conf_signals) >= 3 and len(low_conf_signals) >= 3:
            high_wins = sum(1 for s in high_conf_signals if s.get("outcome") == "win" or s.get("result") == "win")
            high_total = sum(1 for s in high_conf_signals if s.get("outcome") or s.get("result"))
            low_wins = sum(1 for s in low_conf_signals if s.get("outcome") == "win" or s.get("result") == "win")
            low_total = sum(1 for s in low_conf_signals if s.get("outcome") or s.get("result"))
            
            if high_total > 0 and low_total > 0:
                high_rate = high_wins / high_total
                low_rate = low_wins / low_total
                
                if high_rate <= low_rate:
                    findings.append({
                        "type": "confidence_calibration",
                        "severity": "medium",
                        "title": "Confidence not predictive",
                        "description": f"High confidence signals ({high_rate:.1%}) don't outperform low confidence ({low_rate:.1%})",
                        "signal_type": None,
                        "data": {"high_conf_rate": high_rate, "low_conf_rate": low_rate},
                        "recommendation": "Review confidence calculation algorithm",
                    })
        
        # Generate recommendations
        if worst_type and worst_rate < 0.4:
            recommendations.append({
                "priority": "high",
                "title": f"Disable {worst_type}",
                "description": f"Signal type {worst_type} has {worst_rate:.1%} win rate",
                "config_path": f"strategy.disabled_signals",
                "old_value": None,
                "new_value": [worst_type],
                "rationale": "Removing consistently losing signal type improves overall performance",
                "expected_impact": "Fewer losing trades, higher overall win rate",
            })
        
        # Determine overall status
        status = "healthy"
        if any(f["severity"] == "critical" for f in findings):
            status = "critical"
        elif any(f["severity"] == "high" for f in findings):
            status = "degraded"
        
        return {
            "status": status,
            "timestamp": get_utc_timestamp(),
            "findings": findings,
            "recommendations": recommendations,
            "type_metrics": type_metrics,
            "summary": {
                "total_signals": len(signals),
                "overall_win_rate": overall_win_rate,
                "best_signal_type": best_type,
                "worst_signal_type": worst_type,
                "key_insight": self._generate_insight(overall_win_rate, best_type, worst_type, findings),
            },
        }
    
    def _generate_insight(
        self,
        win_rate: Optional[float],
        best_type: Optional[str],
        worst_type: Optional[str],
        findings: List[Dict[str, Any]],
    ) -> str:
        """Generate a key insight summary."""
        if not win_rate:
            return "Insufficient data for comprehensive analysis"
        
        if win_rate >= 0.6:
            return f"Strong performance ({win_rate:.1%} win rate)"
        elif win_rate >= 0.5:
            if best_type:
                return f"Acceptable performance. {best_type} is strongest signal type"
            return f"Acceptable performance ({win_rate:.1%} win rate)"
        else:
            if worst_type:
                return f"Below target. Consider disabling {worst_type}"
            return f"Performance needs attention ({win_rate:.1%} win rate)"
    
    async def _claude_analysis(
        self,
        signals: List[Dict[str, Any]],
        performance: Dict[str, Any],
        agent_state: Dict[str, Any],
        local_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Use Claude for enhanced analysis."""
        # Prepare signal data (limit to prevent token overflow)
        signal_summary = []
        for sig in signals[-50:]:  # Last 50 signals
            signal_summary.append({
                "type": sig.get("signal_type") or sig.get("type"),
                "direction": sig.get("direction"),
                "confidence": sig.get("confidence"),
                "outcome": sig.get("outcome") or sig.get("result"),
                "rr_ratio": sig.get("risk_reward_ratio") or sig.get("rr"),
                "timestamp": sig.get("timestamp") or sig.get("generated_at"),
            })
        
        # Build context
        context = {
            "signals": signal_summary,
            "performance": {
                "win_rate": performance.get("win_rate"),
                "total_trades": performance.get("total_trades"),
                "total_pnl": performance.get("total_pnl"),
            },
            "local_analysis": {
                "type_metrics": local_analysis.get("type_metrics"),
                "findings_count": len(local_analysis.get("findings", [])),
            },
            "market_state": {
                "session_open": agent_state.get("strategy_session_open"),
                "data_fresh": agent_state.get("data_fresh"),
            },
        }
        
        prompt = f"""Analyze these trading signals and provide insights:

{json.dumps(context, indent=2)}

{SIGNAL_ANALYSIS_PROMPT}"""
        
        response = self._claude.chat([{"role": "user", "content": prompt}])
        
        # Parse JSON response
        try:
            # Extract JSON from response (may have markdown)
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            
            return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Could not parse Claude response as JSON")
            return {}
    
    def _merge_analysis(
        self,
        local: Dict[str, Any],
        ai: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge local and AI analysis."""
        if not ai:
            return local
        
        # Start with local analysis
        merged = dict(local)
        
        # Add AI findings (deduplicate by type)
        local_finding_types = {f.get("type") for f in merged.get("findings", [])}
        for finding in ai.get("findings", []):
            if finding.get("type") not in local_finding_types:
                merged.setdefault("findings", []).append(finding)
        
        # Add AI recommendations (deduplicate by config_path)
        local_paths = {r.get("config_path") for r in merged.get("recommendations", [])}
        for rec in ai.get("recommendations", []):
            if rec.get("config_path") not in local_paths:
                merged.setdefault("recommendations", []).append(rec)
        
        # Update summary with AI insight if available
        if ai.get("summary", {}).get("key_insight"):
            merged.setdefault("summary", {})["ai_insight"] = ai["summary"]["key_insight"]
        
        # Update status if AI found worse conditions
        status_priority = {"critical": 3, "degraded": 2, "healthy": 1, "insufficient_data": 0}
        ai_status = ai.get("status", "healthy")
        local_status = merged.get("status", "healthy")
        
        if status_priority.get(ai_status, 0) > status_priority.get(local_status, 0):
            merged["status"] = ai_status
        
        merged["ai_enhanced"] = True
        
        return merged





