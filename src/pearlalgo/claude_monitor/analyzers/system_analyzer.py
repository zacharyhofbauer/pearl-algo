"""
System Analyzer - Analyzes system health, errors, and reliability.

Monitors:
- Error patterns (recurring vs transient)
- Connection stability trends
- Data quality issues (staleness, gaps)
- Circuit breaker triggers (root cause analysis)
- Resource usage patterns
- Telegram delivery failures
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.utils.claude_client import ClaudeClient


# Thresholds for health checks
THRESHOLDS = {
    "consecutive_errors_warning": 3,
    "consecutive_errors_critical": 7,
    "connection_failures_warning": 3,
    "connection_failures_critical": 7,
    "data_stale_minutes_warning": 5,
    "data_stale_minutes_critical": 15,
    "buffer_low_pct": 0.5,  # Below 50% of target
    "telegram_failure_rate_warning": 0.1,  # 10% failures
    "telegram_failure_rate_critical": 0.3,  # 30% failures
}


class SystemAnalyzer:
    """
    Analyzes system health and reliability.
    
    Detects:
    - Error pattern recognition
    - Connection stability issues
    - Data quality problems
    - Circuit breaker triggers
    - Telegram delivery failures
    """
    
    def __init__(
        self,
        claude_client: Optional["ClaudeClient"] = None,
    ):
        """
        Initialize system analyzer.
        
        Args:
            claude_client: Claude API client for AI-enhanced analysis
        """
        self._claude = claude_client
        
        # Track historical state for trend analysis
        self._error_history: List[Dict[str, Any]] = []
        self._connection_history: List[Dict[str, Any]] = []
    
    async def analyze(
        self,
        agent_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Analyze system health.
        
        Args:
            agent_state: Current agent state from state.json
            
        Returns:
            Analysis results with findings and recommendations
        """
        findings = []
        recommendations = []
        alerts = []
        
        # Extract state values
        running = agent_state.get("running", False)
        paused = agent_state.get("paused", False)
        pause_reason = agent_state.get("pause_reason")
        
        consecutive_errors = agent_state.get("consecutive_errors", 0)
        error_count = agent_state.get("error_count", 0)
        connection_failures = agent_state.get("connection_failures", 0)
        data_fetch_errors = agent_state.get("data_fetch_errors", 0)
        
        data_fresh = agent_state.get("data_fresh")
        latest_bar_age = agent_state.get("latest_bar_age_minutes")
        buffer_size = agent_state.get("buffer_size", 0)
        buffer_target = agent_state.get("buffer_size_target", 100)
        
        signals_sent = agent_state.get("signals_sent", 0)
        signals_failures = agent_state.get("signals_send_failures", 0)
        
        # Check running status
        if not running:
            alerts.append({
                "level": "critical",
                "title": "Agent Not Running",
                "message": "The trading agent is not running",
                "category": "system",
            })
            findings.append({
                "type": "agent_stopped",
                "severity": "critical",
                "title": "Agent not running",
                "description": "The trading agent process is not running",
                "recommendation": "Start the agent with /start_agent or check for startup errors",
            })
        elif paused:
            alerts.append({
                "level": "warning",
                "title": "Agent Paused",
                "message": f"Agent is paused: {pause_reason or 'unknown reason'}",
                "category": "system",
            })
            findings.append({
                "type": "agent_paused",
                "severity": "high",
                "title": f"Agent paused: {pause_reason}",
                "description": f"The agent has been paused due to: {pause_reason}",
                "recommendation": "Investigate the pause reason and restart when resolved",
            })
        
        # Check consecutive errors
        if consecutive_errors >= THRESHOLDS["consecutive_errors_critical"]:
            alerts.append({
                "level": "critical",
                "title": "High Error Rate",
                "message": f"{consecutive_errors} consecutive errors - circuit breaker likely triggered",
                "category": "system",
            })
            findings.append({
                "type": "consecutive_errors",
                "severity": "critical",
                "title": f"{consecutive_errors} consecutive errors",
                "description": "Multiple consecutive errors indicate a persistent problem",
                "data": {"count": consecutive_errors, "threshold": THRESHOLDS["consecutive_errors_critical"]},
                "recommendation": "Check logs for error patterns and restart after fixing root cause",
            })
        elif consecutive_errors >= THRESHOLDS["consecutive_errors_warning"]:
            findings.append({
                "type": "consecutive_errors",
                "severity": "medium",
                "title": f"{consecutive_errors} consecutive errors",
                "description": "Multiple errors may indicate an emerging issue",
                "data": {"count": consecutive_errors},
                "recommendation": "Monitor closely and investigate if errors continue",
            })
        
        # Check connection failures
        if connection_failures >= THRESHOLDS["connection_failures_critical"]:
            alerts.append({
                "level": "critical",
                "title": "Connection Issues",
                "message": f"{connection_failures} connection failures - IBKR Gateway may be down",
                "category": "system",
            })
            findings.append({
                "type": "connection_failures",
                "severity": "critical",
                "title": "IBKR connection unstable",
                "description": f"{connection_failures} connection failures detected",
                "data": {"count": connection_failures},
                "recommendation": "Check IBKR Gateway status with /gateway_status",
            })
        elif connection_failures >= THRESHOLDS["connection_failures_warning"]:
            findings.append({
                "type": "connection_failures",
                "severity": "medium",
                "title": "Connection issues detected",
                "description": f"{connection_failures} connection failures",
                "data": {"count": connection_failures},
                "recommendation": "Monitor Gateway health",
            })
        
        # Check data freshness
        if data_fresh is False:
            severity = "critical" if (latest_bar_age or 0) > THRESHOLDS["data_stale_minutes_critical"] else "high"
            alerts.append({
                "level": "warning" if severity == "high" else "critical",
                "title": "Stale Market Data",
                "message": f"Data is {latest_bar_age:.1f} minutes old" if latest_bar_age else "Market data is stale",
                "category": "system",
            })
            findings.append({
                "type": "data_stale",
                "severity": severity,
                "title": "Market data is stale",
                "description": f"Latest bar is {latest_bar_age:.1f} minutes old" if latest_bar_age else "Data freshness check failed",
                "data": {"age_minutes": latest_bar_age},
                "recommendation": "Check market hours and IBKR data subscription",
            })
        
        # Check buffer health
        if buffer_target > 0:
            buffer_pct = buffer_size / buffer_target
            if buffer_pct < THRESHOLDS["buffer_low_pct"]:
                findings.append({
                    "type": "buffer_low",
                    "severity": "medium",
                    "title": "Data buffer below target",
                    "description": f"Buffer at {buffer_size}/{buffer_target} ({buffer_pct:.0%})",
                    "data": {"current": buffer_size, "target": buffer_target, "percent": buffer_pct},
                    "recommendation": "Wait for buffer to fill or increase historical_hours config",
                })
        
        # Check Telegram delivery
        total_signals = signals_sent + signals_failures
        if total_signals > 0:
            failure_rate = signals_failures / total_signals
            if failure_rate >= THRESHOLDS["telegram_failure_rate_critical"]:
                alerts.append({
                    "level": "warning",
                    "title": "Telegram Delivery Issues",
                    "message": f"{failure_rate:.0%} of signals failed to send",
                    "category": "system",
                })
                findings.append({
                    "type": "telegram_failures",
                    "severity": "high",
                    "title": "High Telegram failure rate",
                    "description": f"{signals_failures} of {total_signals} signals failed to send ({failure_rate:.0%})",
                    "data": {"sent": signals_sent, "failed": signals_failures, "rate": failure_rate},
                    "recommendation": "Check Telegram bot token and chat ID configuration",
                })
            elif failure_rate >= THRESHOLDS["telegram_failure_rate_warning"]:
                findings.append({
                    "type": "telegram_failures",
                    "severity": "medium",
                    "title": "Some Telegram failures",
                    "description": f"{signals_failures} signals failed to send",
                    "data": {"sent": signals_sent, "failed": signals_failures, "rate": failure_rate},
                    "recommendation": "Monitor Telegram delivery",
                })
        
        # Check data fetch errors
        if data_fetch_errors >= 5:
            findings.append({
                "type": "data_fetch_errors",
                "severity": "medium",
                "title": f"{data_fetch_errors} data fetch errors",
                "description": "Multiple data fetch failures may indicate subscription or connectivity issues",
                "data": {"count": data_fetch_errors},
                "recommendation": "Check IBKR market data subscription status",
            })
        
        # Generate recommendations based on findings
        if any(f["type"] == "connection_failures" for f in findings):
            recommendations.append({
                "priority": "high",
                "title": "Check IBKR Gateway",
                "description": "Verify Gateway is running and API is ready",
                "action": "gateway_status",
                "rationale": "Connection failures indicate Gateway issues",
            })
        
        if any(f["type"] == "consecutive_errors" and f["severity"] == "critical" for f in findings):
            recommendations.append({
                "priority": "high",
                "title": "Restart Agent",
                "description": "Restart the agent after investigating errors",
                "action": "restart_agent",
                "rationale": "Too many consecutive errors - fresh start may help",
            })
        
        # Determine overall status
        status = "healthy"
        if any(f["severity"] == "critical" for f in findings):
            status = "critical"
        elif any(f["severity"] == "high" for f in findings):
            status = "degraded"
        elif any(f["severity"] == "medium" for f in findings):
            status = "warning"
        
        return {
            "status": status,
            "timestamp": get_utc_timestamp(),
            "findings": findings,
            "recommendations": recommendations,
            "alerts": alerts,
            "metrics": {
                "running": running,
                "paused": paused,
                "consecutive_errors": consecutive_errors,
                "connection_failures": connection_failures,
                "data_fetch_errors": data_fetch_errors,
                "data_fresh": data_fresh,
                "buffer_fill_pct": buffer_size / buffer_target if buffer_target > 0 else None,
                "telegram_failure_rate": signals_failures / total_signals if total_signals > 0 else 0,
            },
            "summary": {
                "overall_health": status,
                "issues_count": len(findings),
                "critical_count": sum(1 for f in findings if f["severity"] == "critical"),
                "key_insight": self._generate_insight(status, findings),
            },
        }
    
    def _generate_insight(
        self,
        status: str,
        findings: List[Dict[str, Any]],
    ) -> str:
        """Generate a key insight summary."""
        if status == "healthy":
            return "All systems operating normally"
        
        critical = [f for f in findings if f["severity"] == "critical"]
        if critical:
            return f"Critical: {critical[0]['title']}"
        
        high = [f for f in findings if f["severity"] == "high"]
        if high:
            return f"Attention needed: {high[0]['title']}"
        
        return f"{len(findings)} minor issues detected"


