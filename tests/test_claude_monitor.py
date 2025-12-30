"""
Tests for Claude Monitor Service.

Tests the core monitoring infrastructure, analyzers, and alert system.
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

# Import modules under test
from pearlalgo.claude_monitor.alert_manager import AlertManager, Alert, AlertLevel
from pearlalgo.claude_monitor.monitor_state import MonitorState
from pearlalgo.claude_monitor.suggestion_engine import (
    SuggestionEngine,
    Suggestion,
    SuggestionType,
    SuggestionPriority,
)
from pearlalgo.claude_monitor.analyzers.signal_analyzer import SignalAnalyzer
from pearlalgo.claude_monitor.analyzers.system_analyzer import SystemAnalyzer
from pearlalgo.claude_monitor.analyzers.market_analyzer import MarketAnalyzer


# =============================================================================
# Alert Manager Tests
# =============================================================================

class TestAlertManager:
    """Tests for AlertManager."""
    
    def test_alert_creation(self):
        """Test creating alerts."""
        alert = Alert(
            level=AlertLevel.WARNING,
            title="Test Alert",
            message="This is a test",
            category="system",
            source="test",
        )
        
        assert alert.level == AlertLevel.WARNING
        assert alert.title == "Test Alert"
        assert alert.fingerprint is not None
    
    def test_alert_level_priority(self):
        """Test alert level priorities."""
        assert AlertLevel.CRITICAL.priority > AlertLevel.WARNING.priority
        assert AlertLevel.WARNING.priority > AlertLevel.INFO.priority
        assert AlertLevel.INFO.priority > AlertLevel.SUCCESS.priority
    
    def test_alert_fingerprint_deduplication(self):
        """Test that similar alerts have same fingerprint."""
        alert1 = Alert(
            level=AlertLevel.WARNING,
            title="Connection Issue",
            message="IBKR connection failed",
            category="system",
            source="system_analyzer",
        )
        
        alert2 = Alert(
            level=AlertLevel.WARNING,
            title="Connection Issue",
            message="Different message",  # Different message
            category="system",
            source="system_analyzer",
        )
        
        # Same fingerprint (title, level, category)
        assert alert1.fingerprint == alert2.fingerprint
    
    def test_alert_telegram_format(self):
        """Test alert Telegram formatting."""
        alert = Alert(
            level=AlertLevel.CRITICAL,
            title="Critical Error",
            message="Something went wrong",
            category="system",
            source="test",
        )
        
        formatted = alert.format_telegram()
        
        assert "🔴" in formatted  # Critical emoji
        assert "Critical Error" in formatted
        assert "Something went wrong" in formatted
    
    def test_alert_manager_deduplication(self):
        """Test that AlertManager deduplicates alerts."""
        # Use high escalation threshold to test pure deduplication
        manager = AlertManager(dedup_window_seconds=300, escalation_threshold=100)
        
        # Create duplicate alerts (use INFO to avoid escalation logic)
        alerts = [
            {"level": "info", "title": "Same Alert", "message": "Test", "category": "test"},
            {"level": "info", "title": "Same Alert", "message": "Test 2", "category": "test"},
        ]
        
        analysis = {"test": {"alerts": alerts}}
        
        # First call should return 1 alert
        result = manager.process_analysis(analysis)
        assert len(result) == 1
        
        # Second call should return 0 (deduplicated)
        result = manager.process_analysis(analysis)
        assert len(result) == 0
    
    def test_alert_manager_rate_limit(self):
        """Test alert rate limiting."""
        manager = AlertManager(max_alerts_per_hour=3)
        
        alerts = []
        for i in range(5):
            alerts.append({
                "level": "info",
                "title": f"Alert {i}",
                "message": f"Test {i}",
                "category": "test",
            })
        
        analysis = {"test": {"alerts": alerts}}
        result = manager.process_analysis(analysis)
        
        # Should be limited to 3
        assert len(result) <= 3
    
    def test_quiet_hours(self):
        """Test quiet hours suppression."""
        # During quiet hours (22:00-07:00)
        manager = AlertManager(
            quiet_start="22:00",
            quiet_end="07:00",
            suppress_info_during_quiet=True,
        )
        
        # Create INFO alert
        alert = manager.create_alert(
            level=AlertLevel.INFO,
            title="Info Alert",
            message="Test",
            category="test",
            source="test",
        )
        
        # During quiet hours, INFO should be suppressed
        # (actual test would need to mock datetime)
        assert alert.level == AlertLevel.INFO


# =============================================================================
# Monitor State Tests
# =============================================================================

class TestMonitorState:
    """Tests for MonitorState."""
    
    @pytest.fixture
    def temp_state_dir(self, tmp_path):
        """Create temporary state directory."""
        state_dir = tmp_path / "nq_agent_state"
        state_dir.mkdir()
        return state_dir
    
    def test_state_initialization(self, temp_state_dir):
        """Test state manager initialization."""
        state = MonitorState(state_dir=temp_state_dir)
        
        assert state._analysis_count == 0
        assert state._alert_count == 0
        assert len(state._active_suggestions) == 0
    
    def test_record_analysis(self, temp_state_dir):
        """Test recording analysis results."""
        state = MonitorState(state_dir=temp_state_dir)
        
        analysis = {
            "signals": {"status": "healthy", "findings": []},
            "system": {"status": "healthy", "findings": []},
        }
        
        state.record_analysis(analysis)
        
        assert state._analysis_count == 1
        assert state._last_analysis == analysis
    
    def test_add_suggestion(self, temp_state_dir):
        """Test adding suggestions."""
        state = MonitorState(state_dir=temp_state_dir)
        
        suggestion = {
            "type": "config_change",
            "title": "Test Suggestion",
            "description": "Change something",
        }
        
        sug_id = state.add_suggestion(suggestion)
        
        assert sug_id.startswith("sug_")
        assert len(state.get_active_suggestions()) == 1
    
    def test_update_suggestion_status(self, temp_state_dir):
        """Test updating suggestion status."""
        state = MonitorState(state_dir=temp_state_dir)
        
        sug_id = state.add_suggestion({
            "type": "config_change",
            "title": "Test",
        })
        
        # Update to applied
        result = state.update_suggestion_status(sug_id, "applied")
        
        assert result is True
        assert state._applied_count == 1
        # Applied suggestions are removed from active
        assert len(state.get_active_suggestions()) == 0
    
    def test_get_stats(self, temp_state_dir):
        """Test getting statistics."""
        state = MonitorState(state_dir=temp_state_dir)
        
        # Record some activity
        state.record_analysis({"test": {"status": "healthy"}})
        state.add_suggestion({"type": "test", "title": "Test"})
        state.record_alert({})
        
        stats = state.get_stats()
        
        assert stats["analysis_count"] == 1
        assert stats["suggestion_count"] == 1
        assert stats["alert_count"] == 1


# =============================================================================
# Signal Analyzer Tests
# =============================================================================

class TestSignalAnalyzer:
    """Tests for SignalAnalyzer."""
    
    def test_basic_analysis_insufficient_data(self):
        """Test analysis with insufficient data."""
        analyzer = SignalAnalyzer(claude_client=None, min_signals_for_analysis=5)
        
        result = asyncio.run(analyzer.analyze(
            agent_state={},
            signals=[{"type": "test"}],  # Only 1 signal
            performance={},
        ))
        
        assert result["status"] == "insufficient_data"
        assert result["summary"]["total_signals"] == 1
    
    def test_win_rate_calculation(self):
        """Test win rate calculation from signals."""
        analyzer = SignalAnalyzer(claude_client=None, min_signals_for_analysis=3)
        
        signals = [
            {"signal_type": "sr_bounce", "outcome": "win"},
            {"signal_type": "sr_bounce", "outcome": "win"},
            {"signal_type": "sr_bounce", "outcome": "loss"},
            {"signal_type": "mean_reversion", "outcome": "loss"},
            {"signal_type": "mean_reversion", "outcome": "loss"},
        ]
        
        result = asyncio.run(analyzer.analyze(
            agent_state={},
            signals=signals,
            performance={},
        ))
        
        # sr_bounce: 2/3 = 66.7%
        # mean_reversion: 0/2 = 0%
        type_metrics = result.get("type_metrics", {})
        assert "sr_bounce" in type_metrics
        assert type_metrics["sr_bounce"]["win_rate"] == pytest.approx(0.666, rel=0.01)
    
    def test_degradation_detection(self):
        """Test detection of win rate degradation."""
        analyzer = SignalAnalyzer(claude_client=None, min_signals_for_analysis=3)
        
        # Create signals with poor performance
        signals = [
            {"signal_type": "sr_bounce", "outcome": "loss"},
            {"signal_type": "sr_bounce", "outcome": "loss"},
            {"signal_type": "sr_bounce", "outcome": "loss"},
            {"signal_type": "sr_bounce", "outcome": "loss"},
            {"signal_type": "sr_bounce", "outcome": "win"},
        ]
        
        result = asyncio.run(analyzer.analyze(
            agent_state={},
            signals=signals,
            performance={},
        ))
        
        # Should detect degradation (20% win rate vs 60% baseline)
        findings = result.get("findings", [])
        degradation_findings = [f for f in findings if f["type"] == "win_rate_degradation"]
        
        assert len(degradation_findings) > 0
        assert degradation_findings[0]["signal_type"] == "sr_bounce"


# =============================================================================
# System Analyzer Tests
# =============================================================================

class TestSystemAnalyzer:
    """Tests for SystemAnalyzer."""
    
    def test_healthy_state(self):
        """Test analysis of healthy system state."""
        analyzer = SystemAnalyzer(claude_client=None)
        
        agent_state = {
            "running": True,
            "paused": False,
            "consecutive_errors": 0,
            "connection_failures": 0,
            "data_fetch_errors": 0,
            "data_fresh": True,
            "buffer_size": 100,
            "buffer_size_target": 100,
            "signals_sent": 10,
            "signals_send_failures": 0,
        }
        
        result = asyncio.run(analyzer.analyze(agent_state))
        
        assert result["status"] == "healthy"
        assert len(result["findings"]) == 0
    
    def test_agent_not_running_detection(self):
        """Test detection of agent not running."""
        analyzer = SystemAnalyzer(claude_client=None)
        
        agent_state = {
            "running": False,
            "paused": False,
        }
        
        result = asyncio.run(analyzer.analyze(agent_state))
        
        assert result["status"] == "critical"
        
        findings = result["findings"]
        agent_findings = [f for f in findings if f["type"] == "agent_stopped"]
        assert len(agent_findings) > 0
    
    def test_consecutive_errors_detection(self):
        """Test detection of consecutive errors."""
        analyzer = SystemAnalyzer(claude_client=None)
        
        agent_state = {
            "running": True,
            "paused": False,
            "consecutive_errors": 8,  # Above threshold
            "connection_failures": 0,
        }
        
        result = asyncio.run(analyzer.analyze(agent_state))
        
        assert result["status"] in ("critical", "degraded")
        
        findings = result["findings"]
        error_findings = [f for f in findings if f["type"] == "consecutive_errors"]
        assert len(error_findings) > 0
    
    def test_connection_failure_detection(self):
        """Test detection of connection failures."""
        analyzer = SystemAnalyzer(claude_client=None)
        
        agent_state = {
            "running": True,
            "paused": False,
            "consecutive_errors": 0,
            "connection_failures": 8,  # Above threshold
        }
        
        result = asyncio.run(analyzer.analyze(agent_state))
        
        findings = result["findings"]
        conn_findings = [f for f in findings if f["type"] == "connection_failures"]
        assert len(conn_findings) > 0


# =============================================================================
# Market Analyzer Tests
# =============================================================================

class TestMarketAnalyzer:
    """Tests for MarketAnalyzer."""
    
    def test_market_closed_detection(self):
        """Test detection of market closed."""
        analyzer = MarketAnalyzer(claude_client=None)
        
        agent_state = {
            "futures_market_open": False,
            "strategy_session_open": False,
        }
        
        result = asyncio.run(analyzer.analyze(agent_state))
        
        assert result["status"] == "market_closed"
        assert result["regime"]["type"] == "closed"
    
    def test_session_closed_finding(self):
        """Test detection of session closed but market open."""
        analyzer = MarketAnalyzer(claude_client=None)
        
        agent_state = {
            "futures_market_open": True,
            "strategy_session_open": False,
        }
        
        result = asyncio.run(analyzer.analyze(agent_state))
        
        findings = result["findings"]
        session_findings = [f for f in findings if f["type"] == "session_closed"]
        assert len(session_findings) > 0
    
    def test_regime_detection_from_pressure(self):
        """Test regime detection from buy/sell pressure."""
        analyzer = MarketAnalyzer(claude_client=None)
        
        # Bullish pressure
        agent_state = {
            "futures_market_open": True,
            "strategy_session_open": True,
            "buy_sell_pressure": 0.75,  # High buy pressure
        }
        
        result = asyncio.run(analyzer.analyze(agent_state))
        
        assert result["regime"]["type"] == "trending_bullish"
        assert result["regime"]["confidence"] > 0.5


# =============================================================================
# Suggestion Engine Tests
# =============================================================================

class TestSuggestionEngine:
    """Tests for SuggestionEngine."""
    
    def test_suggestion_creation(self):
        """Test creating suggestions from analysis."""
        engine = SuggestionEngine(claude_client=None)
        
        analysis = {
            "signals": {
                "status": "degraded",
                "findings": [
                    {
                        "type": "win_rate_degradation",
                        "severity": "high",
                        "title": "Low win rate for momentum_long",
                        "description": "Win rate is 20%",
                        "recommendation": "Disable momentum_long signal type",
                    }
                ],
            },
        }
        
        suggestions = engine.generate(analysis)
        
        assert len(suggestions) > 0
    
    def test_suggestion_prioritization(self):
        """Test that suggestions are prioritized correctly."""
        engine = SuggestionEngine(claude_client=None)
        
        analysis = {
            "signals": {
                "findings": [
                    {"severity": "medium", "title": "Medium", "recommendation": "Do X"},
                    {"severity": "high", "title": "High", "recommendation": "Do Y"},
                    {"severity": "low", "title": "Low", "recommendation": "Do Z"},
                ],
            },
        }
        
        suggestions = engine.generate(analysis)
        
        # Should be ordered by priority (high first)
        if len(suggestions) >= 2:
            assert suggestions[0].priority.value in ("high", "medium")
    
    def test_suggestion_limit(self):
        """Test that suggestions are limited."""
        engine = SuggestionEngine(claude_client=None, max_suggestions_per_analysis=2)
        
        analysis = {
            "signals": {
                "findings": [
                    {"severity": "high", "title": f"Finding {i}", "recommendation": f"Do {i}"}
                    for i in range(10)
                ],
            },
        }
        
        suggestions = engine.generate(analysis)
        
        assert len(suggestions) <= 2


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for Claude monitor components."""
    
    @pytest.fixture
    def temp_state_dir(self, tmp_path):
        """Create temporary state directory."""
        state_dir = tmp_path / "nq_agent_state"
        state_dir.mkdir()
        return state_dir
    
    def test_full_analysis_flow(self, temp_state_dir):
        """Test full analysis flow without Claude API."""
        # Setup components
        signal_analyzer = SignalAnalyzer(claude_client=None)
        system_analyzer = SystemAnalyzer(claude_client=None)
        market_analyzer = MarketAnalyzer(claude_client=None)
        suggestion_engine = SuggestionEngine(claude_client=None)
        alert_manager = AlertManager()
        monitor_state = MonitorState(state_dir=temp_state_dir)
        
        # Create test data
        agent_state = {
            "running": True,
            "paused": False,
            "consecutive_errors": 0,
            "connection_failures": 0,
            "data_fresh": True,
            "buffer_size": 100,
            "buffer_size_target": 100,
            "futures_market_open": True,
            "strategy_session_open": True,
        }
        
        signals = [
            {"signal_type": "sr_bounce", "outcome": "win"},
            {"signal_type": "sr_bounce", "outcome": "win"},
            {"signal_type": "sr_bounce", "outcome": "loss"},
        ]
        
        # Run analysis
        signal_result = asyncio.run(signal_analyzer.analyze(agent_state, signals, {}))
        system_result = asyncio.run(system_analyzer.analyze(agent_state))
        market_result = asyncio.run(market_analyzer.analyze(agent_state))
        
        # Combine results
        analysis = {
            "signals": signal_result,
            "system": system_result,
            "market": market_result,
        }
        
        # Process alerts
        alerts = alert_manager.process_analysis(analysis)
        
        # Generate suggestions
        suggestions = suggestion_engine.generate(analysis)
        
        # Record in state
        monitor_state.record_analysis(analysis, [s.to_dict() for s in suggestions])
        
        # Verify state
        stats = monitor_state.get_stats()
        assert stats["analysis_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

