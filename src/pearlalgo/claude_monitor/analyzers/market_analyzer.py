"""
Market Analyzer - Analyzes market conditions and regime detection.

Monitors:
- Market regime shifts (trending vs ranging)
- Volatility regime changes
- Session-specific performance (Tokyo/London/NY)
- Optimal parameters per regime
- Holiday/low-volume pattern recognition
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.utils.claude_client import ClaudeClient


# Market analysis prompt for Claude
MARKET_ANALYSIS_PROMPT = """You are a market analyst reviewing current conditions for an MNQ futures trading system.

Analyze the market data and provide insights on:
1. Current market regime (trending_bullish, trending_bearish, ranging, choppy)
2. Volatility conditions (high, normal, low)
3. Session context (which session is active, typical behavior)
4. Trading opportunities (favorable or unfavorable conditions)
5. Parameter suggestions based on current regime

Return JSON with this structure:
{
    "status": "favorable|neutral|unfavorable",
    "regime": {
        "type": "trending_bullish|trending_bearish|ranging|choppy",
        "confidence": 0.0-1.0,
        "description": "Brief description"
    },
    "volatility": {
        "level": "high|normal|low",
        "atr": null,
        "description": "Brief description"
    },
    "session": {
        "active": "tokyo|london|new_york|overnight",
        "typical_behavior": "Description of typical session behavior"
    },
    "findings": [
        {
            "type": "regime_shift|volatility_change|session_anomaly|opportunity",
            "severity": "info|medium|high",
            "title": "Brief title",
            "description": "Detailed description"
        }
    ],
    "recommendations": [
        {
            "priority": "high|medium|low",
            "title": "Recommendation title",
            "description": "What to adjust",
            "config_path": "path.to.config",
            "rationale": "Why this helps in current regime"
        }
    ],
    "summary": {
        "key_insight": "One sentence summary",
        "trading_bias": "long|short|neutral",
        "risk_adjustment": "increase|normal|decrease"
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





