"""
Claude Monitor - AI-powered monitoring and assistance for PearlAlgo trading agent.

This module provides comprehensive monitoring, analysis, and optimization
capabilities using Claude AI to proactively detect issues, analyze performance,
and suggest improvements.
"""

from pearlalgo.claude_monitor.monitor_service import ClaudeMonitorService
from pearlalgo.claude_monitor.analysis_engine import AnalysisEngine
from pearlalgo.claude_monitor.alert_manager import AlertManager, Alert, AlertLevel
from pearlalgo.claude_monitor.suggestion_engine import SuggestionEngine, Suggestion
from pearlalgo.claude_monitor.monitor_state import MonitorState

__all__ = [
    "ClaudeMonitorService",
    "AnalysisEngine",
    "AlertManager",
    "Alert",
    "AlertLevel",
    "SuggestionEngine",
    "Suggestion",
    "MonitorState",
]


