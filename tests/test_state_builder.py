"""Tests for pearlalgo.market_agent.state_builder.

Covers StateBuilder.build_state() with mock service objects, verifying
the state dict contains expected keys and handles missing/None attributes
gracefully.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

class _ConfigStub(SimpleNamespace):
    """Simple config object that supports both attribute and dict-style access."""

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


# ---------------------------------------------------------------------------
# Mock service builder
# ---------------------------------------------------------------------------

def _make_mock_service(**overrides: Any) -> MagicMock:
    """Build a MagicMock that looks like MarketAgentService for StateBuilder.

    Provides sensible defaults for every attribute that build_state() reads.
    Pass keyword arguments to override specific attributes.
    """
    svc = MagicMock()

    # Core flags
    svc.running = overrides.get("running", True)
    svc.paused = overrides.get("paused", False)
    svc.pause_reason = overrides.get("pause_reason", None)
    svc.start_time = overrides.get("start_time", datetime(2025, 1, 1, tzinfo=timezone.utc))

    # Counters (lifetime)
    svc.cycle_count = overrides.get("cycle_count", 10)
    svc.signal_count = overrides.get("signal_count", 3)
    svc.signals_sent = overrides.get("signals_sent", 2)
    svc.signals_send_failures = overrides.get("signals_send_failures", 0)
    svc.last_signal_send_error = overrides.get("last_signal_send_error", None)
    svc.last_signal_generated_at = overrides.get("last_signal_generated_at", None)
    svc.last_signal_sent_at = overrides.get("last_signal_sent_at", None)
    svc.last_signal_id_prefix = overrides.get("last_signal_id_prefix", None)

    # Session counters
    svc._cycle_count_at_start = overrides.get("_cycle_count_at_start", 0)
    svc._signal_count_at_start = overrides.get("_signal_count_at_start", 0)
    svc._signals_sent_at_start = overrides.get("_signals_sent_at_start", 0)
    svc._signals_fail_at_start = overrides.get("_signals_fail_at_start", 0)

    # Error counters
    svc.error_count = overrides.get("error_count", 0)
    svc.consecutive_errors = overrides.get("consecutive_errors", 0)
    svc.connection_failures = overrides.get("connection_failures", 0)
    svc.data_fetch_errors = overrides.get("data_fetch_errors", 0)

    # Data quality
    svc.data_fetcher = MagicMock()
    svc.data_fetcher.get_buffer_size.return_value = overrides.get("buffer_size", 100)
    svc.data_fetcher._last_market_data = overrides.get("_last_market_data", None)
    svc.buffer_size_target = overrides.get("buffer_size_target", 200)
    svc.last_successful_cycle = overrides.get("last_successful_cycle", None)

    # Data quality checker
    svc.data_quality_checker = MagicMock()
    svc.data_quality_checker.check_data_freshness.return_value = {
        "timestamp": None,
        "age_minutes": 0,
        "is_fresh": False,
    }

    # Thresholds
    svc.stale_data_threshold_minutes = overrides.get("stale_data_threshold_minutes", 5)
    svc.connection_timeout_minutes = overrides.get("connection_timeout_minutes", 15)

    # Config
    svc.config = _ConfigStub(
        symbol="MNQ",
        timeframe="5m",
        scan_interval=60,
        start_time="18:00",
        end_time="16:10",
        session={"start_time": "18:00", "end_time": "16:10"},
    )
    svc._config_warnings = overrides.get("_config_warnings", [])

    # Adaptive cadence
    svc._adaptive_cadence_enabled = overrides.get("_adaptive_cadence_enabled", False)
    svc._scan_interval_active = 60
    svc._scan_interval_idle = 120
    svc._scan_interval_market_closed = 300
    svc._scan_interval_paused = 600
    svc._effective_interval = 60
    svc.cadence_mode = "fixed"
    svc.cadence_scheduler = None

    # Telegram UI config
    svc._telegram_ui_compact_metrics_enabled = True
    svc._telegram_ui_show_progress_bars = False
    svc._telegram_ui_show_volume_metrics = True
    svc._telegram_ui_compact_metric_width = 10

    # Quiet reason / diagnostics
    svc._last_quiet_reason = overrides.get("_last_quiet_reason", None)
    svc._last_signal_diagnostics = overrides.get("_last_signal_diagnostics", None)
    svc._last_signal_diagnostics_raw = overrides.get("_last_signal_diagnostics_raw", None)
    svc._compute_quiet_period_minutes = MagicMock(return_value=overrides.get("quiet_period_minutes", 5.0))

    # Close-all metadata
    svc._last_close_all_at = None
    svc._last_close_all_reason = None
    svc._last_close_all_count = None
    svc._last_close_all_pnl = None
    svc._last_close_all_price_source = None

    # ATS adapters
    svc.execution_adapter = overrides.get("execution_adapter", None)
    svc._tradovate_account = overrides.get("_tradovate_account", None)

    # Notification queue
    svc.notification_queue = MagicMock()
    svc.notification_queue.get_stats.return_value = {"pending": 0, "sent": 0}

    # Circuit breaker
    svc.trading_circuit_breaker = overrides.get("trading_circuit_breaker", None)

    # State manager (for get_recent_signals)
    svc.state_manager = MagicMock()
    svc.state_manager.state_dir = overrides.get("state_dir", "/tmp/test")
    svc.state_manager.get_recent_signals.return_value = []

    # Volume pressure
    svc.pressure_lookback_bars = 20
    svc.pressure_baseline_bars = 100

    return svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildStateKeys:
    """build_state() must return a dict with the documented top-level keys."""

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    def test_returns_dict_with_core_keys(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        builder = StateBuilder(_make_mock_service())
        state = builder.build_state()

        assert isinstance(state, dict)

        # Verify a representative set of top-level keys
        expected_keys = {
            "running", "paused", "pause_reason", "start_time",
            "cycle_count", "signal_count", "signals_sent",
            "error_count", "consecutive_errors",
            "buffer_size", "buffer_size_target", "data_fresh",
            "config", "cadence_mode",
            "quiet_reason", "quiet_period_minutes",
            "version", "run_id", "market",
            "execution",
            "notification_queue", "trading_circuit_breaker",
        }
        missing = expected_keys - state.keys()
        assert not missing, f"Missing keys: {missing}"

        # Value type assertions for critical keys
        assert isinstance(state["running"], bool), (
            f"running should be bool, got {type(state['running']).__name__}"
        )
        assert isinstance(state["paused"], bool), (
            f"paused should be bool, got {type(state['paused']).__name__}"
        )
        assert isinstance(state["cycle_count"], int), (
            f"cycle_count should be int, got {type(state['cycle_count']).__name__}"
        )
        assert isinstance(state["signal_count"], int), (
            f"signal_count should be int, got {type(state['signal_count']).__name__}"
        )
        assert isinstance(state["signals_sent"], int), (
            f"signals_sent should be int, got {type(state['signals_sent']).__name__}"
        )
        assert isinstance(state["error_count"], int), (
            f"error_count should be int, got {type(state['error_count']).__name__}"
        )
        assert isinstance(state["consecutive_errors"], int), (
            f"consecutive_errors should be int, got {type(state['consecutive_errors']).__name__}"
        )
        assert isinstance(state["buffer_size"], int), (
            f"buffer_size should be int, got {type(state['buffer_size']).__name__}"
        )
        assert isinstance(state["buffer_size_target"], int), (
            f"buffer_size_target should be int, got {type(state['buffer_size_target']).__name__}"
        )
        assert isinstance(state["config"], dict), (
            f"config should be dict, got {type(state['config']).__name__}"
        )
        assert isinstance(state["execution"], dict), (
            f"execution should be dict, got {type(state['execution']).__name__}"
        )
        assert isinstance(state["market"], str), (
            f"market should be str, got {type(state['market']).__name__}"
        )
        # pause_reason is None or str
        assert state["pause_reason"] is None or isinstance(state["pause_reason"], str), (
            f"pause_reason should be None or str, got {type(state['pause_reason']).__name__}"
        )
        # start_time is None or an ISO timestamp str
        assert state["start_time"] is None or isinstance(state["start_time"], str), (
            f"start_time should be None or str, got {type(state['start_time']).__name__}"
        )

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    def test_config_section_has_symbol_and_timeframe(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        builder = StateBuilder(_make_mock_service())
        state = builder.build_state()

        cfg = state["config"]
        assert cfg["symbol"] == "MNQ"
        assert cfg["timeframe"] == "5m"
        assert "scan_interval" in cfg


class TestBuildStateValues:
    """build_state() should reflect service attribute values accurately."""

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    def test_running_and_paused_flags(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        svc = _make_mock_service(running=True, paused=True, pause_reason="test pause")
        state = StateBuilder(svc).build_state()

        assert state["running"] is True
        assert state["paused"] is True
        assert state["pause_reason"] == "test pause"

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    def test_session_counters(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        svc = _make_mock_service(
            cycle_count=50, _cycle_count_at_start=10,
            signal_count=20, _signal_count_at_start=5,
        )
        state = StateBuilder(svc).build_state()

        assert state["cycle_count"] == 50
        assert state["cycle_count_session"] == 40
        assert state["signal_count"] == 20
        assert state["signal_count_session"] == 15


class TestBuildStateEdgeCases:
    """Edge cases: None/missing attributes should be handled gracefully."""

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    def test_none_start_time(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        svc = _make_mock_service(start_time=None)
        state = StateBuilder(svc).build_state()
        assert state["start_time"] is None

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    def test_execution_adapter_none(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        svc = _make_mock_service(execution_adapter=None)
        state = StateBuilder(svc).build_state()

        assert state["execution"] == {"enabled": False, "armed": False, "mode": "disabled"}

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    def test_removed_policy_sections_omitted(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        svc = _make_mock_service()
        state = StateBuilder(svc).build_state()
        assert "learning" not in state

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    def test_circuit_breaker_none(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        svc = _make_mock_service(trading_circuit_breaker=None)
        state = StateBuilder(svc).build_state()
        assert state["trading_circuit_breaker"] == {"enabled": False}

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    def test_session_counter_none_at_start(self, mock_mkt_hours: MagicMock) -> None:
        """When _cycle_count_at_start is None, session counter should be None."""
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        svc = _make_mock_service(cycle_count=10, _cycle_count_at_start=None)
        state = StateBuilder(svc).build_state()
        assert state["cycle_count_session"] is None


class TestBuildStateMarketLabel:
    """market label is derived from PEARLALGO_MARKET env var."""

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    @patch.dict("os.environ", {"PEARLALGO_MARKET": "ES"}, clear=False)
    def test_market_label_from_env(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        state = StateBuilder(_make_mock_service()).build_state()
        assert state["market"] == "ES"

    @patch("pearlalgo.market_agent.state_builder.get_market_hours")
    @patch.dict("os.environ", {}, clear=False)
    def test_market_label_defaults_to_nq(self, mock_mkt_hours: MagicMock) -> None:
        mock_mkt_hours.return_value.is_market_open.return_value = True

        from pearlalgo.market_agent.state_builder import StateBuilder

        # Remove env var if present
        import os
        os.environ.pop("PEARLALGO_MARKET", None)
        state = StateBuilder(_make_mock_service()).build_state()
        assert state["market"] == "NQ"
