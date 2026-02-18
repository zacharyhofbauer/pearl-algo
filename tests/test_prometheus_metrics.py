"""
Tests for Prometheus metrics generation.

Validates that serve_agent_status.py generates correct Prometheus metrics
for all categories: agent status, trading, market, errors, circuit breaker,
challenge, ML/learning, and cadence.
"""

import pytest
import sys
from pathlib import Path

# Add scripts to path for importing
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "monitoring"))

from serve_agent_status import generate_metrics, evaluate_health
from pearlalgo.utils.health_evaluator import HealthEvaluator


class TestGenerateMetrics:
    """Test Prometheus metrics generation."""

    def test_empty_state_returns_valid_metrics(self):
        """Empty state should return valid Prometheus format with zeros."""
        metrics = generate_metrics({})
        
        assert "pearlalgo_agent_running 0" in metrics
        assert "pearlalgo_agent_paused 0" in metrics
        assert "pearlalgo_cycles_total 0" in metrics
        assert "pearlalgo_signals_generated_total 0" in metrics
        
    def test_state_error_returns_error_metric(self):
        """State with _error should set state_error=1."""
        state = {"_error": "state_file_missing"}
        metrics = generate_metrics(state)
        
        assert "pearlalgo_state_error 1" in metrics
        assert "pearlalgo_agent_running 0" in metrics
        
    def test_running_agent_metrics(self):
        """Running agent should have running=1."""
        state = {
            "running": True,
            "paused": False,
            "cycle_count": 100,
            "signal_count": 5,
        }
        metrics = generate_metrics(state)
        
        assert "pearlalgo_agent_running 1" in metrics
        assert "pearlalgo_agent_paused 0" in metrics
        assert "pearlalgo_cycles_total 100" in metrics
        assert "pearlalgo_signals_generated_total 5" in metrics

    def test_paused_agent_metrics(self):
        """Paused agent should have paused=1."""
        state = {
            "running": True,
            "paused": True,
            "pause_reason": "consecutive_errors",
        }
        metrics = generate_metrics(state)
        
        assert "pearlalgo_agent_running 1" in metrics
        assert "pearlalgo_agent_paused 1" in metrics

    def test_trading_performance_metrics(self):
        """Trading performance metrics should be correctly exposed."""
        state = {
            "daily_pnl": 250.50,
            "cumulative_pnl": 1500.75,
            "daily_trades": 10,
            "daily_wins": 6,
            "daily_losses": 4,
            "active_trades_count": 2,
            "signals_sent": 15,
            "signals_send_failures": 1,
        }
        metrics = generate_metrics(state)
        
        assert "pearlalgo_daily_pnl_dollars 250.50" in metrics
        assert "pearlalgo_cumulative_pnl_dollars 1500.75" in metrics
        assert "pearlalgo_daily_trades_total 10" in metrics
        assert "pearlalgo_daily_wins_total 6" in metrics
        assert "pearlalgo_daily_losses_total 4" in metrics
        assert "pearlalgo_daily_win_rate_percent 60.0" in metrics
        assert "pearlalgo_active_trades 2" in metrics
        assert "pearlalgo_signals_sent_total 15" in metrics
        assert "pearlalgo_signals_send_failures_total 1" in metrics

    def test_market_status_metrics(self):
        """Market status metrics should be correctly exposed."""
        state = {
            "futures_market_open": True,
            "strategy_session_open": True,
            "data_fresh": True,
            "latest_bar_age_minutes": 0.5,
            "buffer_size": 280,
            "buffer_size_target": 300,
        }
        metrics = generate_metrics(state)
        
        assert "pearlalgo_futures_market_open 1" in metrics
        assert "pearlalgo_session_open 1" in metrics
        assert "pearlalgo_data_fresh 1" in metrics
        assert "pearlalgo_data_age_seconds 30.0" in metrics  # 0.5 * 60
        assert "pearlalgo_buffer_size 280" in metrics
        assert "pearlalgo_buffer_target 300" in metrics

    def test_error_tracking_metrics(self):
        """Error tracking metrics should be correctly exposed."""
        state = {
            "error_count": 50,
            "consecutive_errors": 3,
            "connection_failures": 2,
            "data_fetch_errors": 1,
        }
        metrics = generate_metrics(state)
        
        assert "pearlalgo_errors_total 50" in metrics
        assert "pearlalgo_consecutive_errors 3" in metrics
        assert "pearlalgo_connection_failures 2" in metrics
        assert "pearlalgo_data_fetch_errors 1" in metrics

    def test_circuit_breaker_metrics(self):
        """Circuit breaker metrics should be correctly exposed."""
        state = {
            "trading_circuit_breaker": {
                "is_paused": True,
                "consecutive_losses": 4,
                "session_pnl": -200.0,
                "daily_pnl": -350.0,
                "session_filter_enabled": True,
                "session_allowed": False,
                "et_hour": 14,
            }
        }
        metrics = generate_metrics(state)
        
        assert "pearlalgo_circuit_breaker_active 1" in metrics
        assert "pearlalgo_circuit_breaker_consecutive_losses 4" in metrics
        assert "pearlalgo_circuit_breaker_session_pnl -200.00" in metrics
        assert "pearlalgo_circuit_breaker_daily_pnl -350.00" in metrics
        assert "pearlalgo_session_filter_enabled 1" in metrics
        assert "pearlalgo_session_allowed 0" in metrics
        assert "pearlalgo_current_et_hour 14" in metrics

    def test_ml_learning_metrics(self):
        """ML/Learning metrics should be correctly exposed."""
        state = {
            "ml_filter": {
                "enabled": True,
                "mode": "shadow",
                "signals_evaluated": 100,
                "signals_passed": 75,
                "signals_blocked": 25,
            },
            "bandit_policy": {
                "enabled": True,
                "mode": "shadow",
            }
        }
        metrics = generate_metrics(state)
        
        assert "pearlalgo_ml_filter_enabled 1" in metrics
        assert "pearlalgo_ml_filter_mode 1" in metrics  # shadow = 1
        assert "pearlalgo_ml_signals_evaluated_total 100" in metrics
        assert "pearlalgo_ml_signals_passed_total 75" in metrics
        assert "pearlalgo_ml_signals_blocked_total 25" in metrics
        assert "pearlalgo_bandit_policy_enabled 1" in metrics
        assert "pearlalgo_bandit_policy_mode 1" in metrics

    def test_cadence_latency_metrics(self):
        """Cadence/latency metrics should be correctly exposed."""
        state = {
            "cadence_metrics": {
                "last_cycle_duration_seconds": 2.5,
                "cycle_duration_p50_seconds": 2.0,
                "cycle_duration_p99_seconds": 5.0,
                "missed_cycles": 2,
                "current_mode": "active",
            }
        }
        metrics = generate_metrics(state)
        
        assert "pearlalgo_cycle_duration_seconds 2.500" in metrics
        assert "pearlalgo_cycle_duration_p50_seconds 2.000" in metrics
        assert "pearlalgo_cycle_duration_p99_seconds 5.000" in metrics
        assert "pearlalgo_missed_cycles_total 2" in metrics
        assert "pearlalgo_cadence_mode 2" in metrics  # active = 2

    def test_metrics_format_is_valid_prometheus(self):
        """Metrics should be valid Prometheus text format."""
        state = {"running": True, "cycle_count": 10}
        metrics = generate_metrics(state)
        
        lines = metrics.strip().split("\n")
        for line in lines:
            if line.startswith("#"):
                # Comment line - HELP or TYPE
                assert line.startswith("# HELP") or line.startswith("# TYPE")
            elif line.strip():
                # Metric line
                parts = line.split(" ")
                assert len(parts) >= 2, f"Invalid metric line: {line}"
                metric_name = parts[0]
                assert metric_name.startswith("pearlalgo_"), f"Invalid metric name: {metric_name}"


class TestEvaluateHealth:
    """Test health evaluation logic."""

    def test_healthy_running_agent(self):
        """Running agent with no issues should be healthy."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        
        state = {
            "running": True,
            "paused": False,
            "last_updated": now,
            "last_successful_cycle": now,
            "futures_market_open": True,
            "data_fresh": True,
            "consecutive_errors": 0,
            "connection_failures": 0,
        }
        healthy, status, details = evaluate_health(state)
        
        assert healthy is True
        assert status == "healthy"
        assert details["status"] == "healthy"

    def test_stopped_agent_is_healthy(self):
        """Intentionally stopped agent should be considered healthy."""
        state = {"running": False}
        healthy, status, details = evaluate_health(state)
        
        assert healthy is True
        assert status == "agent_stopped"
        assert details["status"] == "agent_stopped"

    def test_paused_agent_is_unhealthy(self):
        """Paused agent should be unhealthy."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        
        state = {
            "running": True,
            "paused": True,
            "pause_reason": "consecutive_errors",
            "last_updated": now,
            "last_successful_cycle": now,
        }
        healthy, status, details = evaluate_health(state)
        
        assert healthy is False
        assert "agent_paused" in status
        assert "agent_paused" in details.get("issues", [])

    def test_stale_data_is_unhealthy(self):
        """Stale data while market open should be unhealthy."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        
        state = {
            "running": True,
            "paused": False,
            "last_updated": now,
            "last_successful_cycle": now,
            "futures_market_open": True,
            "data_fresh": False,
        }
        healthy, status, details = evaluate_health(state)
        
        assert healthy is False
        assert "data_stale" in status

    def test_high_consecutive_errors_is_unhealthy(self):
        """10+ consecutive errors should be unhealthy."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        
        state = {
            "running": True,
            "paused": False,
            "last_updated": now,
            "last_successful_cycle": now,
            "consecutive_errors": 10,
        }
        healthy, status, details = evaluate_health(state)
        
        assert healthy is False
        assert "consecutive_errors" in status

    def test_state_error_is_unhealthy(self):
        """State file error should be unhealthy."""
        state = {"_error": "state_file_missing", "_path": "/some/path"}
        healthy, status, details = evaluate_health(state)
        
        assert healthy is False
        assert "state_error" in status


class TestParseTimestamp:
    """Test timestamp parsing via HealthEvaluator."""

    def test_parse_iso_format(self):
        """Should parse ISO format timestamps."""
        ts = HealthEvaluator.parse_timestamp("2025-01-27T12:00:00+00:00")
        assert ts is not None
        assert ts.year == 2025
        assert ts.month == 1
        assert ts.day == 27

    def test_parse_z_suffix(self):
        """Should parse timestamps with Z suffix."""
        ts = HealthEvaluator.parse_timestamp("2025-01-27T12:00:00Z")
        assert ts is not None
        assert ts.year == 2025

    def test_parse_none_returns_none(self):
        """None input should return None."""
        assert HealthEvaluator.parse_timestamp(None) is None

    def test_parse_invalid_returns_none(self):
        """Invalid timestamp should return None."""
        assert HealthEvaluator.parse_timestamp("not-a-timestamp") is None


class TestLoadState:
    """Test state file loading via HealthEvaluator."""

    def test_missing_file_returns_error(self, tmp_path):
        """Missing state file should return error dict."""
        missing_file = tmp_path / "nonexistent" / "state.json"
        state = HealthEvaluator.load_state(missing_file)
        
        assert "_error" in state
        assert state["_error"] == "state_file_missing"

    def test_corrupt_file_returns_error(self, tmp_path):
        """Corrupt JSON should return error dict."""
        corrupt_file = tmp_path / "state.json"
        corrupt_file.write_text("not valid json {{{")
        state = HealthEvaluator.load_state(corrupt_file)
        
        assert "_error" in state
        assert state["_error"] == "state_file_corrupt"

    def test_valid_file_returns_state(self, tmp_path):
        """Valid state file should return parsed state."""
        import json
        state_file = tmp_path / "state.json"
        expected_state = {"running": True, "cycle_count": 42}
        state_file.write_text(json.dumps(expected_state))
        
        state = HealthEvaluator.load_state(state_file)
        
        assert state == expected_state
