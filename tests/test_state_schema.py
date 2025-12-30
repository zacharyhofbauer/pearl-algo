"""
Tests for state.json schema consistency and health evaluation logic.

Validates that:
1. State schema includes all operator-critical fields
2. Health evaluation logic handles edge cases correctly
3. Prometheus metrics are generated correctly
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "scripts" / "monitoring"))


class TestStateSchemaFields:
    """Test that state schema includes expected fields."""
    
    # Core stable fields that external tools have always depended on
    # These must exist in any valid state.json
    CORE_STABLE_FIELDS = {
        "running",
        "start_time",
        "last_updated",
        "cycle_count",
        "signal_count",
        "buffer_size",
        "config",
    }
    
    # Extended stable fields added for observability hardening (v0.2.2+)
    # These are expected in new states but may be missing in legacy state files
    EXTENDED_STABLE_FIELDS = {
        "paused",
        "pause_reason",
        "last_successful_cycle",
        "signals_sent",
        "signals_send_failures",
        "error_count",
        "consecutive_errors",
        "connection_failures",
        "data_fetch_errors",
        "buffer_size_target",
        "data_fresh",
        "latest_bar_timestamp",
        "latest_bar_age_minutes",
        "futures_market_open",
        "strategy_session_open",
        "data_stale_threshold_minutes",
        "connection_timeout_minutes",
    }
    
    # Optional fields added for "why no signals?" diagnostics (v0.3.0+)
    # These may be None but should exist in state after agent restart
    OPTIONAL_DIAGNOSTIC_FIELDS = {
        "quiet_reason",          # Why bot is quiet (e.g., NoOpportunity, Level1Unavailable)
        "signal_diagnostics",    # Compact explanation of signal filtering
    }
    
    # All stable fields (for documentation / full validation)
    REQUIRED_STABLE_FIELDS = CORE_STABLE_FIELDS | EXTENDED_STABLE_FIELDS
    
    REQUIRED_CONFIG_FIELDS = {"symbol", "timeframe", "scan_interval"}
    
    def test_state_file_exists_and_readable(self):
        """Verify state.json exists and is valid JSON."""
        state_file = project_root / "data" / "nq_agent_state" / "state.json"
        
        if not state_file.exists():
            pytest.skip("state.json not present (agent may not have run)")
        
        with open(state_file) as f:
            state = json.load(f)
        
        assert isinstance(state, dict), "state.json should be a dict"
    
    def test_state_has_core_fields(self):
        """Verify state.json includes core stable fields."""
        state_file = project_root / "data" / "nq_agent_state" / "state.json"
        
        if not state_file.exists():
            pytest.skip("state.json not present")
        
        with open(state_file) as f:
            state = json.load(f)
        
        missing = self.CORE_STABLE_FIELDS - set(state.keys())
        assert not missing, f"Missing core stable fields: {missing}"
    
    def test_state_has_extended_fields_when_fresh(self):
        """Verify fresh state.json includes extended stable fields.
        
        This test validates the schema after agent restart with new code.
        If the agent hasn't been restarted, some extended fields may be missing
        (this is expected during rolling upgrades).
        """
        state_file = project_root / "data" / "nq_agent_state" / "state.json"
        
        if not state_file.exists():
            pytest.skip("state.json not present")
        
        with open(state_file) as f:
            state = json.load(f)
        
        # Check for a marker field that only exists in new schema
        if "paused" not in state:
            pytest.skip(
                "state.json is from old agent version (missing 'paused' field). "
                "Restart agent to get new schema fields."
            )
        
        missing = self.EXTENDED_STABLE_FIELDS - set(state.keys())
        assert not missing, f"Missing extended stable fields: {missing}"
    
    def test_state_has_diagnostic_fields_when_fresh(self):
        """Verify fresh state.json includes diagnostic fields (quiet_reason, signal_diagnostics).
        
        These fields are added in v0.3.0+ for "why no signals?" observability.
        They may be None but the keys should exist after agent restart.
        """
        state_file = project_root / "data" / "nq_agent_state" / "state.json"
        
        if not state_file.exists():
            pytest.skip("state.json not present")
        
        with open(state_file) as f:
            state = json.load(f)
        
        # Check for a marker field that only exists in v0.3.0+ schema
        if "quiet_reason" not in state:
            pytest.skip(
                "state.json is from agent version < v0.3.0 (missing 'quiet_reason' field). "
                "Restart agent to get new diagnostic fields."
            )
        
        missing = self.OPTIONAL_DIAGNOSTIC_FIELDS - set(state.keys())
        assert not missing, f"Missing diagnostic fields: {missing}"
        
        # Verify quiet_reason is a valid value (or None)
        quiet_reason = state.get("quiet_reason")
        valid_reasons = {
            None, "Active", "NoOpportunity", "StrategySessionClosed",
            "FuturesMarketClosed", "StaleData", "DataGap", "NoData",
            "Level1Unavailable", "Unknown",
        }
        assert quiet_reason in valid_reasons, f"Invalid quiet_reason: {quiet_reason}"
    
    def test_config_has_required_fields(self):
        """Verify config section has required fields."""
        state_file = project_root / "data" / "nq_agent_state" / "state.json"
        
        if not state_file.exists():
            pytest.skip("state.json not present")
        
        with open(state_file) as f:
            state = json.load(f)
        
        config = state.get("config", {})
        missing = self.REQUIRED_CONFIG_FIELDS - set(config.keys())
        assert not missing, f"Missing required config fields: {missing}"
    
    def test_timestamp_fields_are_iso_format(self):
        """Verify timestamp fields are valid ISO format."""
        state_file = project_root / "data" / "nq_agent_state" / "state.json"
        
        if not state_file.exists():
            pytest.skip("state.json not present")
        
        with open(state_file) as f:
            state = json.load(f)
        
        timestamp_fields = [
            "start_time",
            "last_updated",
            "last_successful_cycle",
            "latest_bar_timestamp",
        ]
        
        for field in timestamp_fields:
            value = state.get(field)
            if value is not None:
                # Should parse without error
                try:
                    ts = value
                    if ts.endswith("Z"):
                        ts = ts[:-1] + "+00:00"
                    datetime.fromisoformat(ts)
                except ValueError:
                    pytest.fail(f"Field {field} has invalid ISO format: {value}")


class TestHealthEvaluation:
    """Test health evaluation logic from status server."""
    
    @pytest.fixture
    def mock_state_healthy(self) -> dict:
        """Create a healthy state dict."""
        now = datetime.now(timezone.utc)
        return {
            "running": True,
            "paused": False,
            "pause_reason": None,
            "last_updated": now.isoformat(),
            "last_successful_cycle": now.isoformat(),
            "futures_market_open": True,
            "strategy_session_open": True,
            "data_fresh": True,
            "consecutive_errors": 0,
            "connection_failures": 0,
            "error_count": 0,
            "buffer_size": 100,
        }
    
    @pytest.fixture
    def mock_state_stale(self) -> dict:
        """Create a state with stale data."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(minutes=10)
        return {
            "running": True,
            "paused": False,
            "pause_reason": None,
            "last_updated": old.isoformat(),
            "last_successful_cycle": old.isoformat(),
            "futures_market_open": True,
            "strategy_session_open": True,
            "data_fresh": False,
            "consecutive_errors": 0,
            "connection_failures": 0,
        }
    
    def test_healthy_state_returns_healthy(self, mock_state_healthy):
        """Healthy state should evaluate as healthy."""
        from serve_nq_agent_status import evaluate_health
        
        is_healthy, status, details = evaluate_health(mock_state_healthy)
        
        assert is_healthy is True
        assert status == "healthy"
        assert details.get("status") == "healthy"
    
    def test_stopped_state_returns_healthy(self, mock_state_healthy):
        """Stopped agent is not unhealthy (intentional stop)."""
        from serve_nq_agent_status import evaluate_health
        
        mock_state_healthy["running"] = False
        
        is_healthy, status, details = evaluate_health(mock_state_healthy)
        
        assert is_healthy is True
        assert status == "agent_stopped"
    
    def test_paused_state_returns_unhealthy(self, mock_state_healthy):
        """Paused agent should be flagged."""
        from serve_nq_agent_status import evaluate_health
        
        mock_state_healthy["paused"] = True
        mock_state_healthy["pause_reason"] = "consecutive_errors"
        
        is_healthy, status, details = evaluate_health(mock_state_healthy)
        
        assert is_healthy is False
        assert "agent_paused" in status
    
    def test_stale_state_returns_unhealthy(self, mock_state_stale):
        """Stale state should be flagged."""
        from serve_nq_agent_status import evaluate_health
        
        is_healthy, status, details = evaluate_health(mock_state_stale)
        
        assert is_healthy is False
        assert "stale" in status.lower() or "data_stale" in status
    
    def test_consecutive_errors_flagged(self, mock_state_healthy):
        """High consecutive errors should be flagged."""
        from serve_nq_agent_status import evaluate_health
        
        mock_state_healthy["consecutive_errors"] = 10
        
        is_healthy, status, details = evaluate_health(mock_state_healthy)
        
        assert is_healthy is False
        assert "consecutive_errors" in status
    
    def test_state_error_handled(self):
        """State file errors should be handled gracefully."""
        from serve_nq_agent_status import evaluate_health
        
        error_state = {"_error": "state_file_missing", "_path": "/test/path"}
        
        is_healthy, status, details = evaluate_health(error_state)
        
        assert is_healthy is False
        assert "state_error" in status
    
    def test_market_closed_tolerates_stale_cycle(self, mock_state_stale):
        """Stale cycle during closed market should not flag cycle_stale."""
        from serve_nq_agent_status import evaluate_health
        
        mock_state_stale["futures_market_open"] = False
        # Keep data_fresh as True to isolate the test
        mock_state_stale["data_fresh"] = True
        
        is_healthy, status, details = evaluate_health(mock_state_stale)
        
        # Should still flag state_stale but not cycle_stale during closed market
        # (unless state is truly old)
        issues = details.get("issues", [])
        cycle_stale_issues = [i for i in issues if "cycle_stale" in i]
        # During market closed, cycle_stale should not be flagged
        assert len(cycle_stale_issues) == 0 or not any("cycle_stale" in i for i in issues)


class TestPrometheusMetrics:
    """Test Prometheus metrics generation."""
    
    def test_metrics_output_is_valid_prometheus_format(self):
        """Generated metrics should be valid Prometheus text format."""
        from serve_nq_agent_status import generate_metrics
        
        state = {
            "running": True,
            "paused": False,
            "cycle_count": 100,
            "signal_count": 5,
            "error_count": 2,
            "buffer_size": 50,
            "data_fresh": True,
            "version": "0.2.1",
            "run_id": "abc123",
        }
        
        metrics = generate_metrics(state)
        
        # Should contain HELP and TYPE comments
        assert "# HELP" in metrics
        assert "# TYPE" in metrics
        
        # Should contain expected metrics
        assert "pearlalgo_agent_running" in metrics
        assert "pearlalgo_cycles_total" in metrics
        assert "pearlalgo_signals_generated_total" in metrics
        assert "pearlalgo_errors_total" in metrics
        
        # Each metric line should be valid format
        for line in metrics.strip().split("\n"):
            if line.startswith("#"):
                continue
            # Should have metric_name value format
            parts = line.split()
            assert len(parts) >= 2, f"Invalid metric line: {line}"
    
    def test_metrics_handles_missing_fields(self):
        """Metrics generation should handle missing fields gracefully."""
        from serve_nq_agent_status import generate_metrics
        
        minimal_state = {"running": True}
        
        metrics = generate_metrics(minimal_state)
        
        # Should not raise error
        assert "pearlalgo_agent_running 1" in metrics
    
    def test_metrics_handles_state_error(self):
        """Metrics generation should handle state errors."""
        from serve_nq_agent_status import generate_metrics
        
        error_state = {"_error": "state_file_missing"}
        
        metrics = generate_metrics(error_state)
        
        assert "pearlalgo_state_error 1" in metrics


class TestLoggingConfigKnownExtraFields:
    """Test that logging config includes expected extra fields."""
    
    def test_known_extra_fields_defined(self):
        """Verify KNOWN_EXTRA_FIELDS is defined and non-empty."""
        from pearlalgo.utils.logging_config import KNOWN_EXTRA_FIELDS
        
        assert isinstance(KNOWN_EXTRA_FIELDS, (set, frozenset))
        assert len(KNOWN_EXTRA_FIELDS) > 0
    
    def test_known_extra_fields_includes_service_fields(self):
        """Verify common service fields are included."""
        from pearlalgo.utils.logging_config import KNOWN_EXTRA_FIELDS
        
        expected = {"cycle", "signals", "data_fresh", "buffer_size", "error_count"}
        missing = expected - KNOWN_EXTRA_FIELDS
        assert not missing, f"Missing expected extra fields: {missing}"
    
    def test_structured_formatter_safe_serialization(self):
        """Verify StructuredFormatter handles non-serializable objects."""
        from pearlalgo.utils.logging_config import StructuredFormatter
        import logging
        
        formatter = StructuredFormatter()
        
        # Create a log record with non-serializable extra
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        
        # Add a non-serializable object (datetime without isoformat handling would fail)
        record.custom_datetime = datetime.now(timezone.utc)
        
        # Should not raise
        output = formatter.format(record)
        
        # Should be valid JSON
        parsed = json.loads(output)
        assert parsed["message"] == "Test message"

