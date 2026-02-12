"""
Integration tests for the PearlAlgo trading agent.

These tests exercise real internal logic across module boundaries while
mocking only external dependencies (IBKR, Telegram, network).

Tests:
    1. test_signal_pipeline   - generation -> tracking -> state update
    2. test_state_persist_and_reload - save, recreate manager, verify
    3. test_config_to_service_init   - real config.yaml -> service init
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_realistic_ohlcv(
    n=200,
    base_price=17500.0,
    timeframe_minutes=5,
    seed=42,
):
    """Build a realistic OHLCV DataFrame with n bars."""
    rng = np.random.RandomState(seed)
    returns = rng.randn(n) * 0.001
    close = base_price * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.randn(n) * 0.0005))
    low = close * (1 - np.abs(rng.randn(n) * 0.0005))
    open_price = close * (1 + rng.randn(n) * 0.0002)
    volume = rng.randint(500, 15000, n).astype(float)
    timestamps = pd.date_range(
        start="2024-06-10 09:30:00",
        periods=n,
        freq=f"{timeframe_minutes}min",
    )
    return pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "timestamp": timestamps,
    })


def _make_signal_dict(**overrides):
    """Build a minimal valid signal dict for testing."""
    sig = {
        "type": "momentum_ema_cross",
        "direction": "long",
        "entry_price": 17500.0,
        "stop_loss": 17480.0,
        "take_profit": 17540.0,
        "confidence": 0.75,
        "symbol": "MNQ",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    sig.update(overrides)
    return sig


# =========================================================================
# 1. Signal Pipeline Integration
# =========================================================================


class TestSignalPipeline:
    """End-to-end: generation -> tracking -> state update.

    Uses real generate_signals(), PerformanceTracker, StateManager.
    Mocks NotificationQueue / Telegram (no network).
    """

    @pytest.fixture
    def pipeline_env(self, tmp_path):
        """Set up an isolated signal pipeline environment."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager
        from pearlalgo.market_agent.performance_tracker import PerformanceTracker
        from pearlalgo.market_agent.signal_handler import SignalHandler
        from pearlalgo.market_agent.order_manager import OrderManager

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        service_config = {
            "storage": {"sqlite_enabled": False},
            "signals": {
                "duplicate_window_seconds": 120,
                "duplicate_price_threshold_pct": 0.5,
            },
        }
        state_manager = MarketAgentStateManager(
            state_dir=state_dir,
            service_config=service_config,
        )
        perf_tracker = PerformanceTracker(
            state_dir=state_dir,
            state_manager=state_manager,
        )
        mock_notifier = MagicMock()
        mock_notifier.enabled = False
        mock_nq = MagicMock()

        async def _mock_enqueue(*a, **kw):
            return True

        mock_nq.enqueue_entry = _mock_enqueue
        order_manager = OrderManager(
            risk_settings={"min_position_size": 1, "max_position_size": 10},
        )
        signal_handler = SignalHandler(
            state_manager=state_manager,
            performance_tracker=perf_tracker,
            notification_queue=mock_nq,
            order_manager=order_manager,
            telegram_notifier=mock_notifier,
        )
        return {
            "state_manager": state_manager,
            "perf_tracker": perf_tracker,
            "signal_handler": signal_handler,
            "notification_queue": mock_nq,
            "state_dir": state_dir,
        }

    def test_signal_generation_produces_valid_output(self):
        """generate_signals() with realistic data returns well-formed signals."""
        from pearlalgo.trading_bots.pearl_bot_auto import generate_signals

        df = _build_realistic_ohlcv(n=200)
        trading_time = datetime(2024, 6, 10, 15, 0, 0, tzinfo=timezone.utc)
        signals = generate_signals(df, current_time=trading_time)

        assert isinstance(signals, list)
        for sig in signals:
            assert isinstance(sig, dict)
            assert "direction" in sig
            assert "entry_price" in sig
            assert "confidence" in sig
            assert sig["direction"] in ("long", "short")
            assert sig["entry_price"] > 0
            assert 0 < sig["confidence"] <= 1.0

    def test_tracking_persists_signal_to_disk(self, pipeline_env):
        """PerformanceTracker.track_signal_generated() writes to signals.jsonl."""
        perf = pipeline_env["perf_tracker"]
        sm = pipeline_env["state_manager"]

        signal = _make_signal_dict()
        signal_id = perf.track_signal_generated(signal)
        assert signal_id, "track_signal_generated should return a signal_id"

        recent = sm.get_recent_signals(limit=10)
        assert len(recent) >= 1, "At least one signal should be persisted"
        last = recent[-1]
        assert last["signal_id"] == signal_id
        assert last["status"] == "generated"

    def test_state_update_after_signal(self, pipeline_env):
        """State round-trips before and after signal tracking."""
        sm = pipeline_env["state_manager"]
        perf = pipeline_env["perf_tracker"]

        initial_state = {"running": True, "cycle_count": 5, "signal_count": 0}
        sm.save_state(initial_state)

        signal = _make_signal_dict()
        perf.track_signal_generated(signal)

        updated_state = sm.load_state()
        updated_state["signal_count"] = 1
        sm.save_state(updated_state)

        reloaded = sm.load_state()
        assert reloaded["running"] is True
        assert reloaded["signal_count"] == 1
        assert "last_updated" in reloaded

        signals = sm.get_recent_signals(limit=10)
        assert len(signals) >= 1

    def test_multiple_signals_tracked_sequentially(self, pipeline_env):
        """Multiple signals are all persisted and retrievable."""
        perf = pipeline_env["perf_tracker"]
        sm = pipeline_env["state_manager"]

        ids = []
        for i in range(5):
            sig = _make_signal_dict(
                entry_price=17500.0 + i * 100,
                confidence=0.6 + i * 0.05,
            )
            sid = perf.track_signal_generated(sig)
            ids.append(sid)

        recent = sm.get_recent_signals(limit=20)
        persisted_ids = {r["signal_id"] for r in recent}
        for sid in ids:
            assert sid in persisted_ids, (
                f"Signal {sid} not found in persisted signals"
            )


# =========================================================================
# 2. State Persistence and Reload
# =========================================================================


class TestStatePersistAndReload:
    """MarketAgentStateManager survives destroy-and-recreate cycle."""

    @staticmethod
    def _make_state_manager(state_dir):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        return MarketAgentStateManager(
            state_dir=state_dir,
            service_config={
                "storage": {"sqlite_enabled": False},
                "signals": {},
            },
        )

    def test_state_round_trip(self, tmp_path):
        """save_state -> new manager -> load_state returns same values."""
        state_dir = tmp_path / "state_rt"
        state_dir.mkdir()

        sm1 = self._make_state_manager(state_dir)
        original_state = {
            "running": True,
            "paused": False,
            "cycle_count": 42,
            "signal_count": 7,
            "error_count": 0,
            "consecutive_errors": 0,
            "config": {"symbol": "MNQ", "timeframe": "5m"},
            "custom_nested": {"key": [1, 2, 3]},
        }
        sm1.save_state(original_state)

        del sm1
        sm2 = self._make_state_manager(state_dir)
        reloaded = sm2.load_state()

        for key in original_state:
            assert key in reloaded, f"Key '{key}' missing after reload"
            assert reloaded[key] == original_state[key], (
                f"Value mismatch for '{key}': "
                f"{reloaded[key]!r} != {original_state[key]!r}"
            )
        assert "last_updated" in reloaded

    def test_signals_survive_reload(self, tmp_path):
        """Signals persisted by manager 1 are readable by manager 2."""
        state_dir = tmp_path / "state_sig"
        state_dir.mkdir()

        sm1 = self._make_state_manager(state_dir)
        for i in range(3):
            sm1.save_signal({
                "type": "test_signal",
                "direction": "long" if i % 2 == 0 else "short",
                "entry_price": 17500.0 + i * 50,
                "confidence": 0.7,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        del sm1
        sm2 = self._make_state_manager(state_dir)
        signals = sm2.get_recent_signals(limit=10)

        assert len(signals) == 3
        for sig in signals:
            assert "signal_id" in sig
            assert sig["status"] == "generated"

    def test_events_survive_reload(self, tmp_path):
        """Events appended by manager 1 are readable by manager 2."""
        state_dir = tmp_path / "state_evt"
        state_dir.mkdir()

        sm1 = self._make_state_manager(state_dir)
        sm1.append_event("agent_started", {"version": "1.0"})
        sm1.append_event("signal_generated", {"signal_id": "test123"})

        del sm1
        sm2 = self._make_state_manager(state_dir)
        events = sm2.get_recent_events(limit=10)

        assert len(events) >= 2
        event_types = [e["type"] for e in events]
        assert "agent_started" in event_types
        assert "signal_generated" in event_types

    def test_empty_state_returns_empty_dict(self, tmp_path):
        """A fresh state dir with no state.json returns empty dict."""
        state_dir = tmp_path / "state_empty"
        state_dir.mkdir()

        sm = self._make_state_manager(state_dir)
        state = sm.load_state()
        assert state == {}

    def test_signal_count_is_consistent(self, tmp_path):
        """get_signal_count() matches the number of written signals."""
        state_dir = tmp_path / "state_count"
        state_dir.mkdir()

        sm = self._make_state_manager(state_dir)
        for i in range(7):
            sm.save_signal({
                "type": "count_test",
                "direction": "long",
                "entry_price": 17500.0,
                "confidence": 0.8,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        sm._signal_store._signal_count = None
        assert sm.get_signal_count() == 7


# =========================================================================
# 3. Config to Service Initialization
# =========================================================================


class TestConfigToServiceInit:
    """Load real config.yaml and construct MarketAgentService.

    Verifies init without error and key attributes are set correctly.
    Mocks only external dependencies (IBKR, Telegram).
    """

    @pytest.fixture
    def service_instance(self, tmp_path):
        """Build a MarketAgentService from real config without running."""
        from tests.mock_data_provider import MockDataProvider
        from pearlalgo.market_agent.service import MarketAgentService

        mock_dp = MockDataProvider(
            base_price=17500.0,
            volatility=25.0,
            trend=0.0,
            simulate_delayed_data=False,
            simulate_timeouts=False,
            simulate_connection_issues=False,
        )
        state_dir = tmp_path / "service_state"
        state_dir.mkdir()

        svc = MarketAgentService(
            data_provider=mock_dp,
            state_dir=state_dir,
            telegram_bot_token=None,
            telegram_chat_id=None,
        )
        return svc

    def test_service_initializes_without_error(self, service_instance):
        """MarketAgentService.__init__ completes without raising."""
        assert service_instance is not None

    def test_service_has_config_attributes(self, service_instance):
        """Service exposes expected config-derived attributes."""
        svc = service_instance
        assert hasattr(svc, "symbol")
        assert isinstance(svc.symbol, str)
        assert len(svc.symbol) > 0

        assert hasattr(svc, "timeframe")
        assert isinstance(svc.timeframe, str)

        assert hasattr(svc, "scan_interval")
        assert isinstance(svc.scan_interval, (int, float))
        assert svc.scan_interval > 0

    def test_service_has_core_components(self, service_instance):
        """Service has all core sub-components wired up."""
        svc = service_instance

        assert svc.state_manager is not None
        assert hasattr(svc.state_manager, "save_state")
        assert hasattr(svc.state_manager, "load_state")
        assert hasattr(svc.state_manager, "save_signal")

        assert svc.performance_tracker is not None
        assert hasattr(svc.performance_tracker, "track_signal_generated")

        assert svc.data_fetcher is not None

        assert svc.strategy is not None
        assert hasattr(svc.strategy, "analyze")

    def test_service_config_matches_yaml(self, service_instance):
        """Service config values should match config.yaml."""
        svc = service_instance
        assert svc.symbol == "MNQ"
        assert svc.timeframe in ("1m", "5m")

    def test_service_state_dir_is_writable(self, service_instance):
        """The service state_manager can write and read state."""
        svc = service_instance
        test_state = {"running": True, "test_key": "test_value"}
        svc.state_manager.save_state(test_state)

        reloaded = svc.state_manager.load_state()
        assert reloaded["running"] is True
        assert reloaded["test_key"] == "test_value"

    def test_service_telegram_disabled_without_credentials(self, service_instance):
        """Without bot_token/chat_id, Telegram notifier is disabled."""
        svc = service_instance
        assert hasattr(svc, "telegram_notifier")
        assert not svc.telegram_notifier.enabled

    def test_service_notification_queue_exists(self, service_instance):
        """Notification queue should be initialized."""
        svc = service_instance
        assert svc.notification_queue is not None

    def test_service_health_monitor_exists(self, service_instance):
        """Health monitor should be initialized."""
        svc = service_instance
        assert svc.health_monitor is not None


# =========================================================================
# 4. Real-Wiring: get_status() without internal mocks
# =========================================================================


class TestRealWiringServiceStatus:
    """MarketAgentService with real internals — only data provider mocked."""

    def test_get_status_returns_valid_dict_with_real_components(
        self,
        tmp_state_dir,
        mock_data_provider,
    ):
        """Construct a real service and call get_status() end-to-end.

        No internal components are mocked — the only fake is the data
        provider (MockDataProvider), which replaces a live IBKR connection.
        Verifies that get_status() returns a well-formed status dict with
        all expected top-level keys populated.
        """
        from pearlalgo.market_agent.service import MarketAgentService

        svc = MarketAgentService(
            data_provider=mock_data_provider,
            state_dir=tmp_state_dir,
        )

        status = svc.get_status()

        # Basic structure
        assert isinstance(status, dict)

        # Core status fields must be present
        assert "running" in status
        assert "signal_count" in status
        assert "cycle_count" in status
        assert "error_count" in status
        assert "config" in status

        # Service should be stopped (never started)
        assert status["running"] is False
        assert status["signal_count"] >= 0
        assert status["cycle_count"] >= 0

        # Performance and health sections should be populated (not None)
        assert "performance" in status
        assert isinstance(status["performance"], dict)

        # Config section should reflect the real defaults
        assert isinstance(status["config"], dict)
        assert status["config"]["symbol"] == "MNQ"
