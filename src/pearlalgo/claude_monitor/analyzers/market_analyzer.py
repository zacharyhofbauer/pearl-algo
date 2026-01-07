"""
Market Analyzer - Analyzes market conditions and regime detection.

Monitors:
- Market regime shifts (trending vs ranging)
- Volatility regime changes
- Session-specific performance (Tokyo/London/NY)
- Optimal parameters per regime
- Holiday/low-volume pattern recognition
- Real-time regime transition detection
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.utils.claude_client import ClaudeClient


# ============================================================================
# Regime Transition Detection
# ============================================================================

REGIME_TRANSITION_SYSTEM_PROMPT = """You are a real-time regime transition detector for an NQ/MNQ futures trading system.

Detect SIGNIFICANT regime changes that warrant strategy adjustment:
1. Trending → Ranging (or vice versa)
2. Volatility expansion/contraction
3. Volume regime changes
4. Session transitions with impact

RULES:
- Only alert on SIGNIFICANT transitions (not normal fluctuations)
- Be fast and concise (this runs frequently)
- Quantify the change when possible
- Suggest specific strategy adjustments

Output ONLY valid JSON:
{
  "transition_detected": true|false,
  "transition_type": "regime_shift|volatility_change|volume_regime|session_impact|null",
  "from_state": "Previous state description",
  "to_state": "New state description",
  "confidence": 0.0-1.0,
  "magnitude": "minor|moderate|major",
  "suggested_adjustments": ["adjustment1", "adjustment2"],
  "alert_message": "Brief message for Telegram or null if no transition",
  "strategy_impact": "What signals/setups are affected"
}"""

REGIME_TRANSITION_USER_TEMPLATE = """Check for regime transition:

Current State:
- Regime: {current_regime}
- Volatility: {current_volatility}
- Session: {current_session}
- Trend Strength: {trend_strength:.2f}

Previous State (30 min ago):
- Regime: {prev_regime}
- Volatility: {prev_volatility}
- Trend Strength: {prev_trend_strength:.2f}

Recent Price Action:
- ATR Change: {atr_change:+.1%}
- Volume Change: {volume_change:+.1%}
- Range vs Average: {range_vs_avg:.1f}x

Key Levels:
- Price vs VWAP: {price_vs_vwap:+.2f} pts
- Distance to High: {dist_to_high:.2f} pts
- Distance to Low: {dist_to_low:.2f} pts

Check for significant regime transition as JSON:"""


@dataclass
class RegimeTransition:
    """Detected regime transition."""
    transition_detected: bool = False
    transition_type: Optional[str] = None  # regime_shift, volatility_change, volume_regime, session_impact
    from_state: str = ""
    to_state: str = ""
    confidence: float = 0.0
    magnitude: str = "minor"  # minor, moderate, major
    suggested_adjustments: List[str] = field(default_factory=list)
    alert_message: Optional[str] = None
    strategy_impact: str = ""
    
    # Metadata
    timestamp: str = ""
    latency_ms: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "transition_detected": self.transition_detected,
            "transition_type": self.transition_type,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "confidence": self.confidence,
            "magnitude": self.magnitude,
            "suggested_adjustments": self.suggested_adjustments,
            "alert_message": self.alert_message,
            "strategy_impact": self.strategy_impact,
            "timestamp": self.timestamp,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }
    
    def format_telegram(self) -> str:
        """Format for Telegram alert (only if transition detected)."""
        if not self.transition_detected or not self.alert_message:
            return ""
        
        magnitude_emoji = {
            "minor": "🔵",
            "moderate": "🟡",
            "major": "🔴",
        }.get(self.magnitude, "⚪")
        
        lines = [f"{magnitude_emoji} *Regime Transition Detected*"]
        lines.append(f"\n{self.alert_message}")
        
        if self.from_state and self.to_state:
            lines.append(f"\n_{self.from_state}_ → _{self.to_state}_")
        
        if self.suggested_adjustments:
            lines.append(f"\n*Suggested Adjustments:*")
            for adj in self.suggested_adjustments[:3]:
                lines.append(f"  • {adj}")
        
        if self.strategy_impact:
            lines.append(f"\n*Impact:* {self.strategy_impact}")
        
        return "\n".join(lines)
    
    @classmethod
    def no_transition(cls) -> "RegimeTransition":
        """Create result with no transition detected."""
        return cls(
            transition_detected=False,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    
    @classmethod
    def from_error(cls, error: str) -> "RegimeTransition":
        """Create result from error."""
        return cls(
            transition_detected=False,
            error=error,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# Market analysis prompt for Claude
MARKET_ANALYSIS_PROMPT = """You are a market analyst reviewing current MNQ futures conditions. Be DETAILED and ACTIONABLE.

## Analysis Requirements
1. **Market regime** - trending/ranging/choppy with WHY (structure, momentum, volume)
2. **Volatility assessment** - ATR as % of price, compare to 20-day average
3. **Session context** - Tokyo/London/NY with typical vs current behavior
4. **Buy/sell pressure** - order flow imbalance and directional bias
5. **Range analysis** - current range vs average, compression/expansion

## Key Context for MNQ
- MNQ trades 23/5, most volume during NY session (9:30am-4pm ET)
- Tokyo = lower vol ranging, London = breakout potential, NY = momentum
- ATR ~30-50pts normal, <20pts compressed, >60pts volatile
- Session position scaling: 50% Tokyo/London, 100% NY (when enabled)

## Output Requirements
Be specific about:
- **WHY** conditions are what they are (support/resistance, volume, time of day)
- **WHAT** parameter changes suit current conditions
- **WHERE** to find relevant config (`config/config.yaml` sections)
- **HOW LONG** to wait before reassessing

Return JSON:
{
    "status": "favorable|neutral|unfavorable",
    "regime": {
        "type": "trending_bullish|trending_bearish|ranging|choppy|compressed",
        "confidence": 0.0-1.0,
        "description": "2-3 sentences explaining WHY this regime, what evidence",
        "range_pts": "current trading range in points",
        "range_vs_avg": "compressed|normal|expanded"
    },
    "volatility": {
        "level": "high|normal|low|compressed",
        "atr_pts": "ATR in points",
        "atr_pct": "ATR as % of price",
        "vs_20d_avg": "above|at|below average",
        "description": "What this means for trading"
    },
    "session": {
        "active": "tokyo|london|new_york|overnight",
        "time_remaining": "hours until next session",
        "current_behavior": "How this session is behaving vs typical",
        "next_catalyst": "What to watch for (e.g., 'US open in 2h may increase vol')"
    },
    "buy_sell_pressure": {
        "bias": "buyer|seller|neutral",
        "strength": "weak|moderate|strong",
        "description": "Order flow analysis"
    },
    "findings": [
        {
            "type": "regime_shift|volatility_change|session_anomaly|opportunity|risk",
            "severity": "info|medium|high",
            "title": "Brief title",
            "description": "2-3 sentences with WHY and WHAT it means",
            "evidence": "Specific data points supporting this"
        }
    ],
    "recommendations": [
        {
            "priority": "high|medium|low",
            "title": "Recommendation title",
            "description": "Specific action to take",
            "config_path": "signals.adaptive_volatility_filter.enabled",
            "current_value": "current setting",
            "suggested_value": "new setting",
            "rationale": "WHY this helps in current conditions",
            "duration": "How long to keep this setting"
        }
    ],
    "next_24h": {
        "outlook": "bullish|bearish|neutral|uncertain",
        "key_levels": "Important S/R levels to watch",
        "catalysts": "Economic events, session opens to watch",
        "recommended_stance": "aggressive|normal|defensive"
    },
    "summary": {
        "key_insight": "2-3 sentence summary with specific action to take NOW",
        "trading_bias": "long|short|neutral",
        "risk_adjustment": "increase|normal|decrease",
        "wait_for": "What catalyst/condition before re-engaging (if defensive)"
    }
}"""


class MarketAnalyzer:
    """
    Analyzes market conditions and regime.
    
    Detects:
    - Market regime (trending, ranging, choppy)
    - Volatility conditions
    - Session characteristics
    - Optimal parameters per regime
    """
    
    def __init__(
        self,
        claude_client: Optional["ClaudeClient"] = None,
    ):
        """
        Initialize market analyzer.
        
        Args:
            claude_client: Claude API client for AI analysis
        """
        self._claude = claude_client
        
        # Session definitions (ET times)
        self._sessions = {
            "tokyo": {"start": 19, "end": 4},      # 7pm-4am ET
            "london": {"start": 3, "end": 12},     # 3am-12pm ET
            "new_york": {"start": 9, "end": 16},   # 9am-4pm ET
        }
        
        # Track regime history
        self._regime_history: List[Dict[str, Any]] = []
    
    async def analyze(
        self,
        agent_state: Dict[str, Any],
        market_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze market conditions.
        
        Args:
            agent_state: Current agent state
            market_data: Current market data
            
        Returns:
            Analysis results with regime and recommendations
        """
        findings = []
        recommendations = []
        
        market_data = market_data or {}
        
        # Extract market state
        futures_open = agent_state.get("futures_market_open")
        session_open = agent_state.get("strategy_session_open")
        latest_bar = market_data.get("latest_bar") or agent_state.get("latest_bar")
        pressure = market_data.get("buy_sell_pressure") or agent_state.get("buy_sell_pressure")
        
        # Determine current session
        current_session = self._get_current_session()
        
        # Market closed check
        if futures_open is False:
            return {
                "status": "market_closed",
                "timestamp": get_utc_timestamp(),
                "findings": [{
                    "type": "market_closed",
                    "severity": "info",
                    "title": "Futures market is closed",
                    "description": "CME futures market is currently closed (weekend or maintenance)",
                }],
                "recommendations": [],
                "regime": {"type": "closed", "confidence": 1.0},
                "session": {"active": "closed"},
                "summary": {
                    "key_insight": "Market is closed",
                    "trading_bias": "neutral",
                },
            }
        
        # Session closed check
        if session_open is False and futures_open is True:
            findings.append({
                "type": "session_closed",
                "severity": "info",
                "title": "Trading session closed",
                "description": "Strategy session is closed but futures are trading",
            })
        
        # Analyze buy/sell pressure
        regime_type = "unknown"
        regime_confidence = 0.5
        
        if pressure:
            pressure_value = pressure if isinstance(pressure, (int, float)) else None
            if pressure_value is not None:
                if pressure_value > 0.6:
                    regime_type = "trending_bullish"
                    regime_confidence = min(pressure_value, 0.9)
                elif pressure_value < 0.4:
                    regime_type = "trending_bearish"
                    regime_confidence = min(1 - pressure_value, 0.9)
                else:
                    regime_type = "ranging"
                    regime_confidence = 0.5 + abs(0.5 - pressure_value)
        
        # Analyze latest bar if available
        volatility_level = "normal"
        if latest_bar and isinstance(latest_bar, dict):
            high = latest_bar.get("high", 0)
            low = latest_bar.get("low", 0)
            close = latest_bar.get("close", 0)
            
            if high > 0 and low > 0 and close > 0:
                bar_range = (high - low) / close
                if bar_range > 0.003:  # >0.3% range
                    volatility_level = "high"
                elif bar_range < 0.001:  # <0.1% range
                    volatility_level = "low"
        
        # Add regime-based findings
        if regime_type == "trending_bullish" and regime_confidence > 0.7:
            findings.append({
                "type": "regime_trending",
                "severity": "info",
                "title": "Bullish trend detected",
                "description": f"Market showing bullish momentum (confidence: {regime_confidence:.0%})",
            })
            recommendations.append({
                "priority": "medium",
                "title": "Favor long signals",
                "description": "Current trend favors long entries",
                "rationale": "Trend-following in bullish regime",
            })
        elif regime_type == "trending_bearish" and regime_confidence > 0.7:
            findings.append({
                "type": "regime_trending",
                "severity": "info",
                "title": "Bearish trend detected",
                "description": f"Market showing bearish momentum (confidence: {regime_confidence:.0%})",
            })
            recommendations.append({
                "priority": "medium",
                "title": "Favor short signals",
                "description": "Current trend favors short entries",
                "rationale": "Trend-following in bearish regime",
            })
        elif regime_type == "ranging":
            findings.append({
                "type": "regime_ranging",
                "severity": "info",
                "title": "Ranging market detected",
                "description": "Market showing sideways action",
            })
            recommendations.append({
                "priority": "low",
                "title": "Mean reversion setups",
                "description": "Ranging markets favor mean reversion strategies",
                "rationale": "Range-bound price action",
            })
        
        # Volatility-based findings
        if volatility_level == "high":
            findings.append({
                "type": "volatility_high",
                "severity": "medium",
                "title": "High volatility",
                "description": "Market showing elevated volatility - wider stops may be needed",
            })
            recommendations.append({
                "priority": "medium",
                "title": "Widen stops",
                "description": "Consider increasing ATR multiplier for stops",
                "config_path": "risk.stop_loss_atr_multiplier",
                "rationale": "Higher volatility requires wider stops",
            })
        elif volatility_level == "low":
            findings.append({
                "type": "volatility_low",
                "severity": "info",
                "title": "Low volatility",
                "description": "Market is quiet - may see fewer signals",
            })
        
        # Session-specific insights
        session_info = {
            "active": current_session,
            "typical_behavior": self._get_session_description(current_session),
        }
        
        # If Claude available, enhance analysis
        if self._claude and latest_bar:
            try:
                ai_analysis = await self._claude_analysis(
                    agent_state, market_data, regime_type, volatility_level, current_session
                )
                return self._merge_analysis(
                    findings, recommendations, regime_type, regime_confidence,
                    volatility_level, session_info, ai_analysis
                )
            except Exception as e:
                logger.warning(f"Claude market analysis failed: {e}")
        
        # Determine overall status
        status = "favorable" if regime_confidence > 0.6 else "neutral"
        if volatility_level == "high":
            status = "cautious"
        
        return {
            "status": status,
            "timestamp": get_utc_timestamp(),
            "findings": findings,
            "recommendations": recommendations,
            "regime": {
                "type": regime_type,
                "confidence": regime_confidence,
                "description": f"{regime_type.replace('_', ' ').title()} regime",
            },
            "volatility": {
                "level": volatility_level,
                "description": f"{volatility_level.title()} volatility conditions",
            },
            "session": session_info,
            "summary": {
                "key_insight": self._generate_insight(regime_type, volatility_level, session_open),
                "trading_bias": "long" if regime_type == "trending_bullish" else "short" if regime_type == "trending_bearish" else "neutral",
                "risk_adjustment": "decrease" if volatility_level == "high" else "normal",
            },
        }
    
    def _get_current_session(self) -> str:
        """Determine current trading session based on ET time."""
        # Get current hour in ET (approximate - proper impl would use pytz)
        utc_now = datetime.now(timezone.utc)
        et_offset = -5  # EST (would be -4 for EDT)
        et_hour = (utc_now.hour + et_offset) % 24
        
        for session_name, times in self._sessions.items():
            start = times["start"]
            end = times["end"]
            
            if start <= end:
                if start <= et_hour < end:
                    return session_name
            else:
                # Overnight session
                if et_hour >= start or et_hour < end:
                    return session_name
        
        return "overnight"
    
    def _get_session_description(self, session: str) -> str:
        """Get description of typical session behavior."""
        descriptions = {
            "tokyo": "Asian session - typically lower volume, ranging behavior",
            "london": "European session - increased volatility, trend initiation",
            "new_york": "US session - highest volume, strong momentum moves",
            "overnight": "Overnight - mixed conditions, lower liquidity",
        }
        return descriptions.get(session, "Session behavior varies")
    
    def _generate_insight(
        self,
        regime: str,
        volatility: str,
        session_open: Optional[bool],
    ) -> str:
        """Generate key insight summary."""
        if session_open is False:
            return "Strategy session closed - no signals will be generated"
        
        regime_text = regime.replace("_", " ")
        
        if volatility == "high":
            return f"{regime_text.title()} regime with high volatility - trade cautiously"
        elif volatility == "low":
            return f"{regime_text.title()} regime with low volatility - patience needed"
        else:
            return f"{regime_text.title()} regime with normal volatility"
    
    async def _claude_analysis(
        self,
        agent_state: Dict[str, Any],
        market_data: Dict[str, Any],
        regime_type: str,
        volatility_level: str,
        current_session: str,
    ) -> Dict[str, Any]:
        """Use Claude for enhanced market analysis."""
        context = {
            "current_analysis": {
                "regime": regime_type,
                "volatility": volatility_level,
                "session": current_session,
            },
            "latest_bar": market_data.get("latest_bar"),
            "buy_sell_pressure": market_data.get("buy_sell_pressure"),
            "session_open": agent_state.get("strategy_session_open"),
        }
        
        prompt = f"""Analyze current market conditions:

{json.dumps(context, indent=2)}

{MARKET_ANALYSIS_PROMPT}"""
        
        response = self._claude.chat([{"role": "user", "content": prompt}])
        
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            
            return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Could not parse Claude market response")
            return {}
    
    def _merge_analysis(
        self,
        findings: List[Dict[str, Any]],
        recommendations: List[Dict[str, Any]],
        regime_type: str,
        regime_confidence: float,
        volatility_level: str,
        session_info: Dict[str, Any],
        ai_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge local and AI analysis."""
        if not ai_analysis:
            return {
                "status": "neutral",
                "timestamp": get_utc_timestamp(),
                "findings": findings,
                "recommendations": recommendations,
                "regime": {"type": regime_type, "confidence": regime_confidence},
                "volatility": {"level": volatility_level},
                "session": session_info,
                "summary": {"key_insight": "Analysis completed"},
            }
        
        # Use AI regime if more confident
        ai_regime = ai_analysis.get("regime", {})
        if ai_regime.get("confidence", 0) > regime_confidence:
            regime_type = ai_regime.get("type", regime_type)
            regime_confidence = ai_regime.get("confidence", regime_confidence)
        
        # Merge findings
        all_findings = findings + ai_analysis.get("findings", [])
        all_recommendations = recommendations + ai_analysis.get("recommendations", [])
        
        return {
            "status": ai_analysis.get("status", "neutral"),
            "timestamp": get_utc_timestamp(),
            "findings": all_findings,
            "recommendations": all_recommendations,
            "regime": {
                "type": regime_type,
                "confidence": regime_confidence,
                "description": ai_regime.get("description", f"{regime_type} regime"),
            },
            "volatility": ai_analysis.get("volatility", {"level": volatility_level}),
            "session": ai_analysis.get("session", session_info),
            "summary": ai_analysis.get("summary", {"key_insight": "Analysis completed"}),
            "ai_enhanced": True,
        }
    
    # ========================================================================
    # Regime Transition Detection
    # ========================================================================
    
    def detect_regime_transition(
        self,
        current_data: Dict[str, Any],
        previous_data: Optional[Dict[str, Any]] = None,
        indicators: Optional[Dict[str, Any]] = None,
    ) -> RegimeTransition:
        """
        Detect significant regime transitions.
        
        This method checks for meaningful state changes that warrant
        strategy adjustments, such as:
        - Trending → Ranging (or vice versa)
        - Volatility expansion/contraction
        - Volume regime changes
        - Session transitions with impact
        
        Args:
            current_data: Current market state
            previous_data: Previous market state (30 min ago typically)
            indicators: Current indicator values
            
        Returns:
            RegimeTransition with detection results
        """
        if not self._claude:
            # Fallback to rule-based detection
            return self._detect_transition_rules(current_data, previous_data, indicators)
        
        start_time = datetime.now(timezone.utc)
        
        try:
            user_prompt = self._build_transition_prompt(current_data, previous_data, indicators)
            
            response = self._claude.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=REGIME_TRANSITION_SYSTEM_PROMPT,
                max_tokens=300,  # Keep response short
            )
            
            result = self._parse_transition_response(response)
            result.latency_ms = int(
                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            )
            result.timestamp = datetime.now(timezone.utc).isoformat()
            
            # Track in regime history
            if result.transition_detected:
                self._regime_history.append({
                    "timestamp": result.timestamp,
                    "type": result.transition_type,
                    "from": result.from_state,
                    "to": result.to_state,
                })
                # Keep history bounded
                if len(self._regime_history) > 100:
                    self._regime_history = self._regime_history[-100:]
                
                logger.info(
                    f"Regime transition detected: {result.from_state} → {result.to_state} "
                    f"({result.magnitude})"
                )
            
            return result
            
        except Exception as e:
            logger.warning(f"Regime transition detection failed: {e}")
            return RegimeTransition.from_error(str(e))
    
    async def detect_regime_transition_async(
        self,
        current_data: Dict[str, Any],
        previous_data: Optional[Dict[str, Any]] = None,
        indicators: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 5.0,
    ) -> RegimeTransition:
        """
        Detect regime transitions asynchronously with timeout.
        
        Args:
            current_data: Current market state
            previous_data: Previous state for comparison
            indicators: Current indicator values
            timeout_seconds: Maximum time for detection
            
        Returns:
            RegimeTransition result
        """
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self.detect_regime_transition,
                    current_data,
                    previous_data,
                    indicators,
                ),
                timeout=timeout_seconds,
            )
            return result
        except asyncio.TimeoutError:
            return RegimeTransition.no_transition()
        except Exception as e:
            return RegimeTransition.from_error(str(e))
    
    def _detect_transition_rules(
        self,
        current_data: Dict[str, Any],
        previous_data: Optional[Dict[str, Any]],
        indicators: Optional[Dict[str, Any]],
    ) -> RegimeTransition:
        """Rule-based fallback for transition detection (no LLM)."""
        if not previous_data:
            return RegimeTransition.no_transition()
        
        current_regime = current_data.get("regime", {}).get("regime", "unknown")
        prev_regime = previous_data.get("regime", {}).get("regime", "unknown")
        current_vol = current_data.get("regime", {}).get("volatility", "normal")
        prev_vol = previous_data.get("regime", {}).get("volatility", "normal")
        
        # Check for regime change
        if current_regime != prev_regime and current_regime != "unknown" and prev_regime != "unknown":
            return RegimeTransition(
                transition_detected=True,
                transition_type="regime_shift",
                from_state=prev_regime.replace("_", " ").title(),
                to_state=current_regime.replace("_", " ").title(),
                confidence=0.7,
                magnitude="moderate",
                suggested_adjustments=[
                    f"Review {current_regime} strategy settings",
                    "Consider signal type adjustments",
                ],
                alert_message=f"Market regime changed from {prev_regime} to {current_regime}",
                strategy_impact="Signal type performance may change",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        # Check for volatility change
        vol_map = {"low": 1, "normal": 2, "high": 3}
        current_vol_num = vol_map.get(current_vol, 2)
        prev_vol_num = vol_map.get(prev_vol, 2)
        
        if abs(current_vol_num - prev_vol_num) >= 2:  # Significant change
            direction = "expanding" if current_vol_num > prev_vol_num else "contracting"
            return RegimeTransition(
                transition_detected=True,
                transition_type="volatility_change",
                from_state=f"{prev_vol} volatility",
                to_state=f"{current_vol} volatility",
                confidence=0.6,
                magnitude="moderate" if abs(current_vol_num - prev_vol_num) == 2 else "minor",
                suggested_adjustments=[
                    "Adjust stop loss distances",
                    "Review position sizing",
                ],
                alert_message=f"Volatility {direction}: {prev_vol} → {current_vol}",
                strategy_impact="Stop and target distances may need adjustment",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        return RegimeTransition.no_transition()
    
    def _build_transition_prompt(
        self,
        current_data: Dict[str, Any],
        previous_data: Optional[Dict[str, Any]],
        indicators: Optional[Dict[str, Any]],
    ) -> str:
        """Build prompt for transition detection."""
        # Current state
        current_regime = current_data.get("regime", {})
        regime_type = current_regime.get("regime", "unknown")
        volatility = current_regime.get("volatility", "normal")
        session = current_regime.get("session", self._get_current_session())
        trend_strength = current_regime.get("trend_strength", 0.5)
        
        # Previous state
        if previous_data:
            prev_regime = previous_data.get("regime", {})
            prev_regime_type = prev_regime.get("regime", "unknown")
            prev_volatility = prev_regime.get("volatility", "normal")
            prev_trend = prev_regime.get("trend_strength", 0.5)
        else:
            prev_regime_type = regime_type
            prev_volatility = volatility
            prev_trend = trend_strength
        
        # Indicator changes
        ind = indicators or {}
        atr = ind.get("atr", 30)
        prev_atr = previous_data.get("indicators", {}).get("atr", atr) if previous_data else atr
        atr_change = (atr - prev_atr) / prev_atr if prev_atr > 0 else 0
        
        volume = ind.get("volume", 1000)
        prev_volume = previous_data.get("indicators", {}).get("volume", volume) if previous_data else volume
        volume_change = (volume - prev_volume) / prev_volume if prev_volume > 0 else 0
        
        # Price levels
        price = current_data.get("latest_bar", {}).get("close", 0)
        vwap = ind.get("vwap", price)
        high = ind.get("recent_high", price + 10)
        low = ind.get("recent_low", price - 10)
        avg_range = ind.get("avg_range", high - low)
        current_range = high - low
        range_vs_avg = current_range / avg_range if avg_range > 0 else 1.0
        
        return REGIME_TRANSITION_USER_TEMPLATE.format(
            current_regime=regime_type,
            current_volatility=volatility,
            current_session=session,
            trend_strength=trend_strength,
            prev_regime=prev_regime_type,
            prev_volatility=prev_volatility,
            prev_trend_strength=prev_trend,
            atr_change=atr_change,
            volume_change=volume_change,
            range_vs_avg=range_vs_avg,
            price_vs_vwap=price - vwap if price and vwap else 0,
            dist_to_high=high - price if high and price else 0,
            dist_to_low=price - low if price and low else 0,
        )
    
    def _parse_transition_response(self, response: str) -> RegimeTransition:
        """Parse Claude's response for transition detection."""
        try:
            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            
            data = json.loads(response)
            
            return RegimeTransition(
                transition_detected=bool(data.get("transition_detected", False)),
                transition_type=data.get("transition_type"),
                from_state=str(data.get("from_state", "")),
                to_state=str(data.get("to_state", "")),
                confidence=float(data.get("confidence", 0.5)),
                magnitude=str(data.get("magnitude", "minor")),
                suggested_adjustments=data.get("suggested_adjustments", [])[:5],
                alert_message=data.get("alert_message"),
                strategy_impact=str(data.get("strategy_impact", "")),
            )
        except json.JSONDecodeError:
            return RegimeTransition.no_transition()
    
    def get_regime_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent regime transition history."""
        return self._regime_history[-limit:]

