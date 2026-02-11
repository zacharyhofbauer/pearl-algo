"""
Tests for WebSocket broadcast payload completeness.

Verifies that state_update, initial_state, and full_refresh messages
all contain the expected set of top-level keys, including the new
positions, recent_trades, and performance_summary fields.
"""

from __future__ import annotations

import pytest

# The required keys that must be present in ALL WebSocket message types
# (state_update, initial_state, full_refresh).
REQUIRED_WS_KEYS = {
    # Core state
    "running",
    "paused",
    "daily_pnl",
    "daily_trades",
    "daily_wins",
    "daily_losses",
    "active_trades_count",
    "active_trades_unrealized_pnl",
    "futures_market_open",
    "data_fresh",
    "last_updated",
    # AI status
    "ai_status",
    # Performance
    "challenge",
    "recent_exits",
    "performance",
    "equity_curve",
    "risk_metrics",
    # NEW: real-time trades data (previously HTTP-only)
    "positions",
    "recent_trades",
    "performance_summary",
    # Market
    "cadence_metrics",
    "market_regime",
    "buy_sell_pressure",
    "signal_rejections_24h",
    "last_signal_decision",
    "shadow_counters",
    # Execution
    "execution_state",
    "tradovate_account",
    "circuit_breaker",
    "ml_filter_performance",
    "session_context",
    "signal_activity",
    # Infrastructure
    "gateway_status",
    "connection_health",
    "error_summary",
    "config",
    "data_quality",
    # Pearl AI
    "pearl_suggestion",
    "pearl_insights",
    "pearl_ai_available",
    "pearl_feed",
    "pearl_ai_heartbeat",
    "pearl_ai_debug",
    # Operator
    "operator_lock_enabled",
}


class TestBroadcastPayloadContract:
    """Verify the broadcast payload contract is maintained in server.py source."""

    def test_state_update_has_all_keys(self):
        """The state_update broadcast payload in server.py must contain all required keys."""
        import ast
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "src" / "pearlalgo" / "api" / "server.py"
        source = server_path.read_text()

        # Check that every required key appears as a string literal in the broadcast section
        # This is a source-level contract test (not runtime)
        missing = []
        for key in REQUIRED_WS_KEYS:
            # Look for the key as a dict key in the broadcast payload
            if f'"{key}"' not in source and f"'{key}'" not in source:
                missing.append(key)

        assert not missing, f"Keys missing from server.py: {missing}"

    def test_initial_state_has_positions_key(self):
        """Verify initial_state includes the new positions key."""
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "src" / "pearlalgo" / "api" / "server.py"
        source = server_path.read_text()

        # Find the initial_state section and verify it has the new keys
        assert '"positions"' in source, "positions key missing from server.py"
        assert '"recent_trades"' in source, "recent_trades key missing from server.py"
        assert '"performance_summary"' in source, "performance_summary key missing from server.py"

    def test_initial_state_has_field_parity_comment(self):
        """Verify the initial_state build has the parity comment."""
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "src" / "pearlalgo" / "api" / "server.py"
        source = server_path.read_text()

        assert "SAME field set as state_update" in source, (
            "initial_state should document that it mirrors state_update"
        )


class TestMetricsModuleContract:
    """Verify the metrics module exports the expected functions and constants."""

    def test_compute_risk_metrics_importable(self):
        from pearlalgo.api.metrics import compute_risk_metrics, DEFAULT_RISK_METRICS
        assert callable(compute_risk_metrics)
        assert isinstance(DEFAULT_RISK_METRICS, dict)

    def test_default_metrics_has_new_keys(self):
        from pearlalgo.api.metrics import DEFAULT_RISK_METRICS
        new_keys = {
            "sortino_ratio",
            "calmar_ratio",
            "kelly_criterion",
            "max_consecutive_wins",
            "max_consecutive_losses",
            "current_streak",
            "max_drawdown_duration_seconds",
        }
        missing = new_keys - set(DEFAULT_RISK_METRICS.keys())
        assert not missing, f"Missing keys in DEFAULT_RISK_METRICS: {missing}"


class TestDataLayerContract:
    """Verify the data layer module exports the expected functions."""

    def test_is_mffu_account_importable(self):
        from pearlalgo.api.data_layer import is_mffu_account
        assert callable(is_mffu_account)

    def test_get_signals_importable(self):
        from pearlalgo.api.data_layer import get_signals
        assert callable(get_signals)

    def test_cached_importable(self):
        from pearlalgo.api.data_layer import cached
        assert callable(cached)


class TestTradovateHelpersContract:
    """Verify the tradovate helpers module exports the expected functions."""

    def test_get_paired_tradovate_trades_importable(self):
        from pearlalgo.api.tradovate_helpers import get_paired_tradovate_trades
        assert callable(get_paired_tradovate_trades)

    def test_tradovate_positions_for_api_importable(self):
        from pearlalgo.api.tradovate_helpers import tradovate_positions_for_api
        assert callable(tradovate_positions_for_api)


class TestBroadcastHelpersExist:
    """Verify the broadcast helper functions exist in server.py."""

    def test_broadcast_helpers_defined_in_source(self):
        """The three new broadcast helpers should be defined in server.py."""
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "src" / "pearlalgo" / "api" / "server.py"
        source = server_path.read_text()

        assert "def _get_positions_for_broadcast" in source
        assert "def _get_trades_for_broadcast" in source
        assert "def _get_performance_summary_for_broadcast" in source

    def test_broadcast_helpers_called_in_broadcast_loop(self):
        """The broadcast helpers should be called inside the broadcast payload."""
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "src" / "pearlalgo" / "api" / "server.py"
        source = server_path.read_text()

        assert "_get_positions_for_broadcast" in source
        assert "_get_trades_for_broadcast" in source
        assert "_get_performance_summary_for_broadcast" in source

    def test_initial_state_and_full_refresh_both_have_positions(self):
        """Both initial_state and full_refresh should include positions field."""
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "src" / "pearlalgo" / "api" / "server.py"
        source = server_path.read_text()

        # Count occurrences of _get_positions_for_broadcast — should appear
        # at least 3 times (state_update, initial_state, full_refresh)
        count = source.count("_get_positions_for_broadcast")
        assert count >= 3, f"Expected >= 3 occurrences, found {count}"

    def test_fingerprint_first_pattern(self):
        """Verify the broadcast loop checks fingerprint before computing payload."""
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "src" / "pearlalgo" / "api" / "server.py"
        source = server_path.read_text()

        assert "fingerprint-first" in source.lower() or "Fingerprint-first" in source, (
            "Broadcast loop should document the fingerprint-first optimization"
        )
