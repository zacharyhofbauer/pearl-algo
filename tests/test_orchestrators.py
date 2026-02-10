"""
Tests for Orchestrator classes (Arch-2 decomposition).

Covers all public methods of:
1. SignalOrchestrator   – signal processing, ML filter config, context features
2. ExecutionOrchestrator – virtual exits, sizing, auto-flat, close requests
3. ObservabilityOrchestrator – performance, notifications, summaries, quiet period
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.market_agent.signal_orchestrator import SignalOrchestrator
from pearlalgo.market_agent.execution_orchestrator import ExecutionOrchestrator
from pearlalgo.market_agent.observability_orchestrator import ObservabilityOrchestrator


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_mock_signal_handler():
    """Create a mock SignalHandler with async process_signal."""
    sh = MagicMock()
    sh.process_signal = AsyncMock(return_value=None)
    sh.ml_signal_filter = None
    sh.ml_filter_enabled = False
    sh.ml_filter_mode = "shadow"
    return sh


def _make_mock_order_manager():
    """Create a mock OrderManager with safe defaults."""
    om = MagicMock()
    om.compute_base_position_size.return_value = 2
    om.configure_ml_sizing = MagicMock()
    return om


def _make_mock_state_manager():
    """Create a mock MarketAgentStateManager with safe defaults."""
    sm = MagicMock()
    sm.get_recent_signals.return_value = []
    sm.load_state.return_value = {}
    sm.update_state = MagicMock()
    return sm


def _make_mock_virtual_trade_manager():
    """Create a mock VirtualTradeManager with safe defaults."""
    vtm = MagicMock()
    vtm.process_exits = MagicMock()
    return vtm


def _make_mock_execution_adapter(*, connected=True, armed=False):
    """Create a mock ExecutionAdapter with configurable state."""
    ea = MagicMock()
    ea.is_connected = connected
    ea.armed = armed
    return ea


def _make_mock_performance_tracker():
    """Create a mock PerformanceTracker with deterministic return values."""
    pt = MagicMock()
    pt.record_signal = MagicMock()
    pt.get_daily_performance.return_value = {
        "total_signals": 5,
        "wins": 3,
        "losses": 2,
        "pnl": 125.50,
    }
    return pt


def _make_mock_notification_queue(*, queue_size=0):
    """Create a mock NotificationQueue."""
    nq = MagicMock()
    nq.enqueue_raw_message = AsyncMock(return_value=True)
    nq.queue_size = queue_size
    return nq


def _make_mock_telegram_notifier(*, enabled=True):
    """Create a mock MarketAgentTelegramNotifier."""
    tn = MagicMock()
    tn.enabled = enabled
    return tn


# ===========================================================================
# SignalOrchestrator fixtures
# ===========================================================================

@pytest.fixture
def signal_handler():
    return _make_mock_signal_handler()


@pytest.fixture
def order_manager():
    return _make_mock_order_manager()


@pytest.fixture
def state_manager():
    return _make_mock_state_manager()


@pytest.fixture
def signal_orchestrator(signal_handler, order_manager, state_manager):
    """SignalOrchestrator with all mock dependencies."""
    return SignalOrchestrator(
        signal_handler=signal_handler,
        order_manager=order_manager,
        state_manager=state_manager,
    )


# ===========================================================================
# ExecutionOrchestrator fixtures
# ===========================================================================

@pytest.fixture
def virtual_trade_manager():
    return _make_mock_virtual_trade_manager()


@pytest.fixture
def execution_orchestrator(virtual_trade_manager, order_manager, state_manager):
    """ExecutionOrchestrator without an execution adapter."""
    return ExecutionOrchestrator(
        virtual_trade_manager=virtual_trade_manager,
        order_manager=order_manager,
        state_manager=state_manager,
    )


@pytest.fixture
def execution_orchestrator_with_adapter(
    virtual_trade_manager, order_manager, state_manager
):
    """ExecutionOrchestrator with a live execution adapter."""
    adapter = _make_mock_execution_adapter(connected=True, armed=False)
    return ExecutionOrchestrator(
        virtual_trade_manager=virtual_trade_manager,
        order_manager=order_manager,
        state_manager=state_manager,
        execution_adapter=adapter,
    )


# ===========================================================================
# ObservabilityOrchestrator fixtures
# ===========================================================================

@pytest.fixture
def performance_tracker():
    return _make_mock_performance_tracker()


@pytest.fixture
def notification_queue():
    return _make_mock_notification_queue(queue_size=3)


@pytest.fixture
def telegram_notifier():
    return _make_mock_telegram_notifier(enabled=True)


@pytest.fixture
def observability_orchestrator(
    performance_tracker, notification_queue, telegram_notifier, state_manager
):
    """ObservabilityOrchestrator with all mock dependencies."""
    return ObservabilityOrchestrator(
        performance_tracker=performance_tracker,
        notification_queue=notification_queue,
        telegram_notifier=telegram_notifier,
        state_manager=state_manager,
    )


# ===========================================================================
# SignalOrchestrator tests
# ===========================================================================


class TestSignalOrchestrator:
    """Tests for SignalOrchestrator."""

    @pytest.mark.asyncio
    async def test_process_signals_delegates_to_handler(
        self, signal_orchestrator, signal_handler
    ):
        """Each signal is forwarded to SignalHandler.process_signal with buffer data."""
        signals = [
            {"type": "entry", "direction": "long"},
            {"type": "entry", "direction": "short"},
        ]
        df = pd.DataFrame({"Close": [100.0, 101.0]})
        market_data = {"df": df}

        processed = await signal_orchestrator.process_signals(signals, market_data)

        assert processed == 2
        assert signal_handler.process_signal.call_count == 2
        # First call receives the first signal and the buffer_data
        first_call_args = signal_handler.process_signal.call_args_list[0]
        assert first_call_args[0][0] == {"type": "entry", "direction": "long"}
        assert first_call_args[1]["buffer_data"].equals(df)

    @pytest.mark.asyncio
    async def test_process_signals_calls_sync_callback(
        self, signal_orchestrator, signal_handler
    ):
        """sync_counters_callback is invoked after each signal, even on success."""
        callback = MagicMock()
        signals = [{"type": "entry"}, {"type": "exit"}]
        market_data = {"df": pd.DataFrame()}

        await signal_orchestrator.process_signals(
            signals, market_data, sync_counters_callback=callback
        )

        assert callback.call_count == 2

    @pytest.mark.asyncio
    async def test_process_signals_handles_handler_error(
        self, signal_orchestrator, signal_handler
    ):
        """A failing signal does not abort remaining signals; count excludes failures."""
        signal_handler.process_signal.side_effect = [
            RuntimeError("boom"),  # first signal fails
            None,                  # second succeeds
        ]
        callback = MagicMock()
        signals = [{"type": "bad"}, {"type": "good"}]
        market_data = {"df": pd.DataFrame()}

        processed = await signal_orchestrator.process_signals(
            signals, market_data, sync_counters_callback=callback
        )

        assert processed == 1  # only the second signal succeeded
        assert signal_handler.process_signal.call_count == 2
        # callback still called for both (in finally block)
        assert callback.call_count == 2

    def test_configure_ml_filter_propagates_to_components(
        self, signal_orchestrator, signal_handler, order_manager
    ):
        """configure_ml_filter updates orchestrator, handler, and order manager."""
        mock_filter = MagicMock()

        signal_orchestrator.configure_ml_filter(
            mock_filter, enabled=True, mode="live"
        )

        # Orchestrator internal state
        assert signal_orchestrator._ml_signal_filter is mock_filter
        assert signal_orchestrator._ml_filter_enabled is True
        assert signal_orchestrator._ml_filter_mode == "live"
        # Propagated to signal handler
        assert signal_handler.ml_signal_filter is mock_filter
        assert signal_handler.ml_filter_enabled is True
        assert signal_handler.ml_filter_mode == "live"
        # Propagated to order manager
        order_manager.configure_ml_sizing.assert_called_once_with(mock_filter)

    def test_build_context_features_extracts_signal_data(self, signal_orchestrator):
        """build_context_features returns expected keys with correct values."""
        signal = {
            "type": "breakout",
            "confidence": 0.85,
            "direction": "long",
            "risk_reward": 2.5,
            "market_regime": "trending",
            "volume_ratio": 1.3,
        }
        df = pd.DataFrame({"Close": [100.0]})
        market_data = {"df": df}

        features = signal_orchestrator.build_context_features(signal, market_data)

        assert features["signal_type"] == "breakout"
        assert features["confidence"] == 0.85
        assert features["direction"] == "long"
        assert features["risk_reward"] == 2.5
        assert features["regime"] == "trending"
        assert features["volume_ratio"] == 1.3

    def test_build_context_features_handles_missing_data(self, signal_orchestrator):
        """build_context_features uses defaults when signal keys are absent."""
        signal = {}  # no keys at all
        market_data = {}  # no df

        features = signal_orchestrator.build_context_features(signal, market_data)

        assert features["signal_type"] == "unknown"
        assert features["confidence"] == 0.0
        assert features["direction"] == "unknown"
        assert features["risk_reward"] == 0.0
        # No df means no regime/volume_ratio keys
        assert "regime" not in features
        assert "volume_ratio" not in features


# ===========================================================================
# ExecutionOrchestrator tests
# ===========================================================================


class TestExecutionOrchestrator:
    """Tests for ExecutionOrchestrator."""

    def test_process_virtual_exits_delegates_to_manager(
        self, execution_orchestrator, virtual_trade_manager
    ):
        """process_virtual_exits delegates to VirtualTradeManager.process_exits."""
        market_data = {"df": pd.DataFrame({"Close": [100.0]})}

        execution_orchestrator.process_virtual_exits(market_data)

        virtual_trade_manager.process_exits.assert_called_once_with(market_data)

    def test_process_virtual_exits_handles_error(
        self, execution_orchestrator, virtual_trade_manager
    ):
        """VirtualTradeManager errors are caught and do not propagate."""
        virtual_trade_manager.process_exits.side_effect = RuntimeError("db fail")
        market_data = {"df": pd.DataFrame()}

        # Should not raise
        execution_orchestrator.process_virtual_exits(market_data)

        virtual_trade_manager.process_exits.assert_called_once()

    def test_compute_position_size_delegates(
        self, execution_orchestrator, order_manager
    ):
        """compute_position_size returns the value from OrderManager."""
        order_manager.compute_base_position_size.return_value = 5
        signal = {"direction": "long", "confidence": 0.9}

        size = execution_orchestrator.compute_position_size(signal)

        assert size == 5
        order_manager.compute_base_position_size.assert_called_once_with(signal)

    def test_is_execution_enabled_with_adapter(
        self, execution_orchestrator_with_adapter
    ):
        """is_execution_enabled is True when an adapter is configured."""
        assert execution_orchestrator_with_adapter.is_execution_enabled is True

    def test_is_execution_enabled_without_adapter(self, execution_orchestrator):
        """is_execution_enabled is False when no adapter is configured."""
        assert execution_orchestrator.is_execution_enabled is False

    @pytest.mark.asyncio
    async def test_get_execution_status_with_adapter(
        self, execution_orchestrator_with_adapter
    ):
        """get_execution_status returns connected/armed state when adapter exists."""
        status = await execution_orchestrator_with_adapter.get_execution_status()

        assert status["enabled"] is True
        assert status["connected"] is True
        assert status["armed"] is False

    @pytest.mark.asyncio
    async def test_get_execution_status_without_adapter(self, execution_orchestrator):
        """get_execution_status returns minimal dict when no adapter is configured."""
        status = await execution_orchestrator.get_execution_status()

        assert status == {"enabled": False}

    def test_get_active_virtual_trades_filters_entered(
        self, execution_orchestrator, state_manager
    ):
        """Only signals with status=entered are returned."""
        state_manager.get_recent_signals.return_value = [
            {"signal_id": "s1", "status": "entered"},
            {"signal_id": "s2", "status": "exited"},
            {"signal_id": "s3", "status": "entered"},
            {"signal_id": "s4", "status": "rejected"},
        ]

        active = execution_orchestrator.get_active_virtual_trades()

        assert len(active) == 2
        assert active[0]["signal_id"] == "s1"
        assert active[1]["signal_id"] == "s3"
        state_manager.get_recent_signals.assert_called_once_with(limit=300)

    def test_auto_flat_due_daily(self, execution_orchestrator):
        """Daily auto-flat triggers when local time is past daily_time."""
        # 2025-12-23 is a Tuesday (weekday=1)
        now_utc = datetime(2025, 12, 23, 22, 0, 0, tzinfo=timezone.utc)  # 17:00 ET
        cfg = {
            "enabled": True,
            "daily_enabled": True,
            "daily_time": (16, 55),
            "timezone": "America/New_York",
        }
        last_dates: dict = {}

        result = execution_orchestrator.auto_flat_due(
            now_utc, market_open=True, auto_flat_cfg=cfg, last_dates=last_dates
        )

        assert result == "daily_auto_flat"

    def test_auto_flat_due_friday(self, execution_orchestrator):
        """Friday auto-flat triggers on Friday past friday_time."""
        # 2025-12-26 is a Friday (weekday=4)
        now_utc = datetime(2025, 12, 26, 22, 0, 0, tzinfo=timezone.utc)  # 17:00 ET
        cfg = {
            "enabled": False,  # daily disabled
            "friday_enabled": True,
            "friday_time": (16, 55),
            "timezone": "America/New_York",
        }
        last_dates: dict = {}

        result = execution_orchestrator.auto_flat_due(
            now_utc, market_open=True, auto_flat_cfg=cfg, last_dates=last_dates
        )

        assert result == "friday_auto_flat"

    def test_auto_flat_due_weekend(self, execution_orchestrator):
        """Weekend auto-flat triggers on Saturday when market is closed."""
        # 2025-12-27 is a Saturday (weekday=5)
        now_utc = datetime(2025, 12, 27, 15, 0, 0, tzinfo=timezone.utc)  # 10:00 ET
        cfg = {
            "weekend_enabled": True,
            "timezone": "America/New_York",
        }
        last_dates: dict = {}

        result = execution_orchestrator.auto_flat_due(
            now_utc, market_open=False, auto_flat_cfg=cfg, last_dates=last_dates
        )

        assert result == "weekend_auto_flat"

    def test_auto_flat_due_returns_none_outside_window(self, execution_orchestrator):
        """auto_flat_due returns None when no rule matches."""
        # 2025-12-23 is a Tuesday at 10am ET — well before any auto-flat window
        now_utc = datetime(2025, 12, 23, 15, 0, 0, tzinfo=timezone.utc)  # 10:00 ET
        cfg = {
            "enabled": True,
            "daily_enabled": True,
            "daily_time": (16, 55),
            "timezone": "America/New_York",
        }
        last_dates: dict = {}

        result = execution_orchestrator.auto_flat_due(
            now_utc, market_open=True, auto_flat_cfg=cfg, last_dates=last_dates
        )

        assert result is None

    def test_get_close_signals_requested(self, execution_orchestrator, state_manager):
        """get_close_signals_requested returns signal_ids from state."""
        state_manager.load_state.return_value = {
            "close_signals_requested": ["sig-1", "sig-2"],
        }

        result = execution_orchestrator.get_close_signals_requested()

        assert result == ["sig-1", "sig-2"]
        state_manager.load_state.assert_called_once()

    def test_clear_close_signals_requested(
        self, execution_orchestrator, state_manager
    ):
        """clear_close_signals_requested writes an empty list to state."""
        execution_orchestrator.clear_close_signals_requested()

        state_manager.update_state.assert_called_once_with(
            {"close_signals_requested": []}
        )

    def test_clear_close_all_flag(self, execution_orchestrator, state_manager):
        """clear_close_all_flag resets both close_all fields in state."""
        execution_orchestrator.clear_close_all_flag()

        state_manager.update_state.assert_called_once_with({
            "close_all_requested": False,
            "close_all_requested_at": None,
        })


# ===========================================================================
# ObservabilityOrchestrator tests
# ===========================================================================


class TestObservabilityOrchestrator:
    """Tests for ObservabilityOrchestrator."""

    def test_track_performance_delegates(
        self, observability_orchestrator, performance_tracker
    ):
        """track_performance forwards the signal to PerformanceTracker.record_signal."""
        signal = {"signal_id": "s1", "pnl": 50.0}

        observability_orchestrator.track_performance(signal)

        performance_tracker.record_signal.assert_called_once_with(signal)

    def test_track_performance_handles_error(
        self, observability_orchestrator, performance_tracker
    ):
        """PerformanceTracker errors are caught and do not propagate."""
        performance_tracker.record_signal.side_effect = RuntimeError("disk full")

        # Should not raise
        observability_orchestrator.track_performance({"signal_id": "s1"})

        performance_tracker.record_signal.assert_called_once()

    def test_get_daily_performance_delegates(
        self, observability_orchestrator, performance_tracker
    ):
        """get_daily_performance returns the tracker's metrics dict."""
        result = observability_orchestrator.get_daily_performance()

        assert result == {
            "total_signals": 5,
            "wins": 3,
            "losses": 2,
            "pnl": 125.50,
        }
        performance_tracker.get_daily_performance.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_notification_enqueues(
        self, observability_orchestrator, notification_queue
    ):
        """send_notification enqueues the message via the notification queue."""
        await observability_orchestrator.send_notification(
            "Trade entered: long MNQ", priority="high"
        )

        notification_queue.enqueue_raw_message.assert_awaited_once_with(
            "Trade entered: long MNQ", priority="high"
        )

    @pytest.mark.asyncio
    async def test_send_notification_handles_error(
        self, observability_orchestrator, notification_queue
    ):
        """Enqueue failure is caught and does not propagate."""
        notification_queue.enqueue_raw_message.side_effect = RuntimeError("queue full")

        # Should not raise
        await observability_orchestrator.send_notification("test message")

        notification_queue.enqueue_raw_message.assert_awaited_once()

    def test_get_daily_summary_aggregates(
        self, observability_orchestrator, performance_tracker, notification_queue,
        telegram_notifier,
    ):
        """get_daily_summary combines performance metrics and queue stats."""
        summary = observability_orchestrator.get_daily_summary()

        assert summary["performance"] == {
            "total_signals": 5,
            "wins": 3,
            "losses": 2,
            "pnl": 125.50,
        }
        assert summary["notifications"]["queue_size"] == 3
        assert summary["notifications"]["telegram_enabled"] is True

    @pytest.mark.asyncio
    async def test_notify_error_formats_and_enqueues(
        self, observability_orchestrator, notification_queue
    ):
        """notify_error prefixes with context and enqueues at raw message level."""
        await observability_orchestrator.notify_error(
            "Connection timed out", context="DataFetcher"
        )

        notification_queue.enqueue_raw_message.assert_awaited_once_with(
            "⚠️ [DataFetcher] Connection timed out"
        )

    @pytest.mark.asyncio
    async def test_notify_error_truncates_long_messages(
        self, observability_orchestrator, notification_queue
    ):
        """Messages longer than 500 chars are truncated before enqueueing."""
        long_msg = "x" * 800

        await observability_orchestrator.notify_error(long_msg)

        call_args = notification_queue.enqueue_raw_message.call_args[0][0]
        # "⚠️ " prefix + 500 truncated chars
        assert call_args == f"⚠️ {'x' * 500}"
        assert len(call_args) < 800

    def test_compute_quiet_period_minutes(self, observability_orchestrator):
        """compute_quiet_period_minutes returns minutes since last signal."""
        last_signal = datetime.now(timezone.utc) - timedelta(minutes=15)

        result = observability_orchestrator.compute_quiet_period_minutes(last_signal)

        assert result is not None
        # Allow 1-second tolerance for test execution time
        assert 14.9 < result < 15.1

    def test_compute_quiet_period_minutes_none(self, observability_orchestrator):
        """compute_quiet_period_minutes returns None when no previous signal."""
        result = observability_orchestrator.compute_quiet_period_minutes(None)

        assert result is None
