"""
Tests for SignalHandler

Tests:
- Constructor initialization with required and optional dependencies
- configure_ml_filter method
- get_stats method
- Signal processing happy path (ML filter, circuit breaker, execution, notification)
- Signal rejection by circuit breaker (enforce vs warn-only modes)
- ML filter application (shadow mode, threshold gating, disabled, errors)
- Bandit policy decisions and error handling
- Contextual policy decisions and error handling
- Execution gating, placement, policy-based blocking, size multipliers
- Virtual entry tracking
- Error handling and graceful degradation
- Notification queue full / priority escalation
- Edge cases (empty signals, missing fields, multiple signals)
- Context feature building (time buckets, session, regime)
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.market_agent.notification_queue import Priority
from pearlalgo.market_agent.signal_handler import SignalHandler


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def make_mock_state_manager():
    """Create a mock MarketAgentStateManager with safe defaults."""
    sm = MagicMock()
    sm.get_recent_signals.return_value = []
    return sm


def make_mock_performance_tracker():
    """Create a mock PerformanceTracker with deterministic signal ID."""
    pt = MagicMock()
    pt.track_signal_generated.return_value = "signal-abc123-def456-ghi789"
    pt.track_entry.return_value = None
    return pt


def make_mock_notification_queue():
    """Create a mock NotificationQueue that accepts all entries."""
    nq = MagicMock()
    nq.enqueue_entry = AsyncMock(return_value=True)
    nq.enqueue_circuit_breaker = AsyncMock(return_value=True)
    return nq


def make_mock_order_manager():
    """Create a mock OrderManager with no-op ML sizing."""
    om = MagicMock()
    om.apply_ml_opportunity_sizing.return_value = None
    return om


def make_valid_signal():
    """Create a well-formed signal dict suitable for the full pipeline."""
    return {
        "type": "sr_bounce",
        "direction": "long",
        "symbol": "MNQ",
        "entry_price": 20000.0,
        "stop_loss": 19980.0,
        "take_profit": 20030.0,
        "position_size": 1,
        "signal_id": "test-signal-001",
        "timestamp": "2024-06-15T10:30:00Z",
    }


def make_cb_decision(*, allowed=True, reason="", details=None, severity="warning"):
    """Create a mock circuit breaker decision."""
    d = MagicMock()
    d.allowed = allowed
    d.reason = reason
    d.details = details or {}
    d.severity = severity
    d.to_dict.return_value = {"allowed": allowed, "reason": reason}
    return d


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state_manager():
    """Mock state manager fixture."""
    return make_mock_state_manager()


@pytest.fixture
def performance_tracker():
    """Mock performance tracker fixture."""
    return make_mock_performance_tracker()


@pytest.fixture
def notification_queue():
    """Mock notification queue fixture."""
    return make_mock_notification_queue()


@pytest.fixture
def order_manager():
    """Mock order manager fixture."""
    return make_mock_order_manager()


@pytest.fixture
def handler(state_manager, performance_tracker, notification_queue, order_manager):
    """Create a basic SignalHandler with required dependencies only."""
    return SignalHandler(
        state_manager=state_manager,
        performance_tracker=performance_tracker,
        notification_queue=notification_queue,
        order_manager=order_manager,
    )


@pytest.fixture
def valid_signal():
    """Return a well-formed signal dict."""
    return make_valid_signal()


# ===========================================================================
# Tests: Constructor / Initialization
# ===========================================================================

class TestSignalHandlerInit:
    """Tests for SignalHandler constructor and initialization."""

    def test_init_stores_required_dependencies(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Constructor should store all four required positional dependencies."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        assert h.state_manager is state_manager
        assert h.performance_tracker is performance_tracker
        assert h.notification_queue is notification_queue
        assert h.order_manager is order_manager

    def test_init_optional_dependencies_default_to_none(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """All optional keyword dependencies should default to None or safe values."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        assert h.trading_circuit_breaker is None
        assert h.bandit_policy is None
        assert h._bandit_config is None
        assert h.contextual_policy is None
        assert h._ml_signal_filter is None
        assert h._ml_filter_enabled is False
        assert h._ml_filter_mode == "shadow"
        assert h._ml_shadow_threshold is None
        assert h.execution_adapter is None
        assert h.telegram_notifier is None

    def test_init_tracking_counters_start_at_zero(self, handler):
        """All tracking counters should be initialized to zero / None."""
        assert handler.signal_count == 0
        assert handler.signals_sent == 0
        assert handler.signals_send_failures == 0
        assert handler.error_count == 0
        assert handler.last_signal_generated_at is None
        assert handler.last_signal_sent_at is None
        assert handler.last_signal_send_error is None
        assert handler.last_signal_id_prefix is None

    def test_init_with_all_optional_dependencies(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Constructor should accept and store every optional keyword argument."""
        cb = MagicMock()
        bp = MagicMock()
        bc = MagicMock()
        cp = MagicMock()
        mf = MagicMock()
        ea = MagicMock()
        tn = MagicMock()

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
            trading_circuit_breaker=cb,
            bandit_policy=bp,
            bandit_config=bc,
            contextual_policy=cp,
            ml_signal_filter=mf,
            ml_filter_enabled=True,
            ml_filter_mode="live",
            ml_shadow_threshold=0.6,
            execution_adapter=ea,
            telegram_notifier=tn,
        )

        assert h.trading_circuit_breaker is cb
        assert h.bandit_policy is bp
        assert h._bandit_config is bc
        assert h.contextual_policy is cp
        assert h._ml_signal_filter is mf
        assert h._ml_filter_enabled is True
        assert h._ml_filter_mode == "live"
        assert h._ml_shadow_threshold == 0.6
        assert h.execution_adapter is ea
        assert h.telegram_notifier is tn


# ===========================================================================
# Tests: configure_ml_filter
# ===========================================================================

class TestConfigureMLFilter:
    """Tests for the configure_ml_filter method."""

    def test_configure_ml_filter_sets_all_values(self, handler):
        """configure_ml_filter should update all four ML filter settings."""
        mock_filter = MagicMock()
        handler.configure_ml_filter(
            ml_signal_filter=mock_filter,
            enabled=True,
            mode="live",
            shadow_threshold=0.65,
        )

        assert handler._ml_signal_filter is mock_filter
        assert handler._ml_filter_enabled is True
        assert handler._ml_filter_mode == "live"
        assert handler._ml_shadow_threshold == 0.65

    def test_configure_ml_filter_defaults_disable(self, handler):
        """configure_ml_filter with defaults should leave filter disabled."""
        handler.configure_ml_filter(ml_signal_filter=None)

        assert handler._ml_signal_filter is None
        assert handler._ml_filter_enabled is False
        assert handler._ml_filter_mode == "shadow"
        assert handler._ml_shadow_threshold is None


# ===========================================================================
# Tests: get_stats
# ===========================================================================

class TestGetStats:
    """Tests for the get_stats method."""

    def test_get_stats_returns_all_expected_keys(self, handler):
        """get_stats should return a dict with exactly the expected keys."""
        stats = handler.get_stats()

        expected_keys = {
            "signal_count",
            "signals_sent",
            "signals_send_failures",
            "error_count",
            "last_signal_generated_at",
            "last_signal_sent_at",
            "last_signal_send_error",
            "last_signal_id_prefix",
        }
        assert set(stats.keys()) == expected_keys

    def test_get_stats_reflects_current_counters(self, handler):
        """get_stats values should reflect mutations to tracking counters."""
        handler.signal_count = 5
        handler.signals_sent = 4
        handler.signals_send_failures = 1
        handler.error_count = 2
        handler.last_signal_generated_at = "2024-06-15T10:30:00Z"
        handler.last_signal_id_prefix = "abc123def456ghij"

        stats = handler.get_stats()

        assert stats["signal_count"] == 5
        assert stats["signals_sent"] == 4
        assert stats["signals_send_failures"] == 1
        assert stats["error_count"] == 2
        assert stats["last_signal_generated_at"] == "2024-06-15T10:30:00Z"
        assert stats["last_signal_id_prefix"] == "abc123def456ghij"


# ===========================================================================
# Tests: process_signal happy path
# ===========================================================================

@pytest.mark.asyncio
class TestProcessSignalHappyPath:
    """Tests for the happy-path signal processing pipeline."""

    async def test_full_pipeline_calls_all_stages(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """A valid signal should traverse every stage: CB check -> ML filter
        -> ML sizing -> tracking -> virtual entry -> policy -> execution -> notification."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        signal = make_valid_signal()
        await h.process_signal(signal)

        performance_tracker.track_signal_generated.assert_called_once_with(signal)
        performance_tracker.track_entry.assert_called_once()
        order_manager.apply_ml_opportunity_sizing.assert_called_once_with(signal)
        notification_queue.enqueue_entry.assert_awaited_once()
        assert h.signal_count == 1

    async def test_timestamps_set_after_processing(self, handler, valid_signal):
        """Processing should populate last_signal_generated_at and last_signal_id_prefix."""
        await handler.process_signal(valid_signal)

        assert handler.last_signal_generated_at is not None
        # Prefix is first 16 chars of the mock signal ID
        assert handler.last_signal_id_prefix == "signal-abc123-de"

    async def test_signals_sent_incremented_on_queue_success(self, handler, valid_signal):
        """When the notification queue accepts the entry, signals_sent increments."""
        handler.notification_queue.enqueue_entry = AsyncMock(return_value=True)

        await handler.process_signal(valid_signal)

        assert handler.signals_sent == 1
        assert handler.signals_send_failures == 0
        assert handler.last_signal_send_error is None


# ===========================================================================
# Tests: Circuit Breaker
# ===========================================================================

@pytest.mark.asyncio
class TestCircuitBreaker:
    """Tests for circuit breaker checks during signal processing."""

    async def test_no_circuit_breaker_allows_signal(self, handler, valid_signal):
        """Without a circuit breaker, all signals should pass through."""
        assert handler.trading_circuit_breaker is None

        await handler.process_signal(valid_signal)

        assert handler.signal_count == 1

    async def test_circuit_breaker_allowed_passes(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """A circuit breaker that returns allowed=True should let the signal through."""
        cb = MagicMock()
        cb.should_allow_signal.return_value = make_cb_decision(allowed=True)

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
            trading_circuit_breaker=cb,
        )

        await h.process_signal(make_valid_signal())
        assert h.signal_count == 1

    async def test_circuit_breaker_enforce_blocks_signal(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Circuit breaker in enforce mode should block a disallowed signal entirely."""
        cb = MagicMock()
        cb.should_allow_signal.return_value = make_cb_decision(
            allowed=False,
            reason="max_positions_reached",
            details={"current": 3, "limit": 3},
            severity="warning",
        )
        cb.config.mode = "enforce"

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
            trading_circuit_breaker=cb,
        )

        await h.process_signal(make_valid_signal())

        assert h.signal_count == 0
        performance_tracker.track_signal_generated.assert_not_called()

    async def test_circuit_breaker_enforce_critical_queues_notification(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Enforce + critical severity should fire a circuit-breaker notification task."""
        cb = MagicMock()
        cb.should_allow_signal.return_value = make_cb_decision(
            allowed=False,
            reason="daily_drawdown_exceeded",
            details={"drawdown": -1200, "limit": -1000},
            severity="critical",
        )
        cb.config.mode = "enforce"

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
            trading_circuit_breaker=cb,
        )

        await h.process_signal(make_valid_signal())
        # Give the fire-and-forget task a chance to run
        await asyncio.sleep(0)

        assert h.signal_count == 0
        notification_queue.enqueue_circuit_breaker.assert_awaited_once()

    async def test_circuit_breaker_warn_only_allows_signal(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Warn-only mode should allow the signal and record a would-block event."""
        cb = MagicMock()
        cb.should_allow_signal.return_value = make_cb_decision(
            allowed=False,
            reason="position_clustering_risk",
            details={"cluster_count": 4},
            severity="warning",
        )
        cb.config.mode = "warn_only"

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
            trading_circuit_breaker=cb,
        )

        await h.process_signal(make_valid_signal())

        assert h.signal_count == 1
        cb.record_would_block.assert_called_once_with("position_clustering_risk")

    async def test_circuit_breaker_receives_active_positions(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Circuit breaker should receive only 'entered' positions from state manager."""
        entered = {"status": "entered", "signal_id": "pos-1"}
        exited = {"status": "exited", "signal_id": "pos-2"}
        state_manager.get_recent_signals.return_value = [entered, exited]

        cb = MagicMock()
        cb.should_allow_signal.return_value = make_cb_decision(allowed=True)

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
            trading_circuit_breaker=cb,
        )

        await h.process_signal(make_valid_signal())

        call_kwargs = cb.should_allow_signal.call_args.kwargs
        active_positions = call_kwargs["active_positions"]
        assert len(active_positions) == 1
        assert active_positions[0]["signal_id"] == "pos-1"


# ===========================================================================
# Tests: ML Filter
# ===========================================================================

class TestMLFilter:
    """Tests for _apply_ml_filter."""

    def test_disabled_filter_skips(self, handler, valid_signal):
        """Disabled ML filter should not modify the signal at all."""
        handler._ml_filter_enabled = False

        handler._apply_ml_filter(valid_signal)

        assert "_ml_prediction" not in valid_signal

    def test_none_filter_skips_even_if_enabled(self, handler, valid_signal):
        """Enabled flag with None filter object should skip without error."""
        handler._ml_filter_enabled = True
        handler._ml_signal_filter = None

        handler._apply_ml_filter(valid_signal)

        assert "_ml_prediction" not in valid_signal

    def test_filter_attaches_prediction_in_shadow_mode(self, handler, valid_signal):
        """Enabled ML filter should attach _ml_prediction and _ml_shadow_pass_filter."""
        mock_pred = MagicMock()
        mock_pred.to_dict.return_value = {"win_probability": 0.72, "model": "xgb_v3"}
        mock_pred.win_probability = 0.72

        mock_filter = MagicMock()
        mock_filter.should_execute.return_value = (True, mock_pred)

        handler._ml_filter_enabled = True
        handler._ml_signal_filter = mock_filter
        handler._ml_filter_mode = "shadow"

        handler._apply_ml_filter(valid_signal)

        assert valid_signal["_ml_prediction"] == {"win_probability": 0.72, "model": "xgb_v3"}
        assert valid_signal["_ml_shadow_pass_filter"] is True

    def test_shadow_threshold_gates_pass_filter(self, handler, valid_signal):
        """When shadow threshold is set, _ml_shadow_pass_filter should reflect the gate."""
        mock_pred = MagicMock()
        mock_pred.to_dict.return_value = {"win_probability": 0.45}
        mock_pred.win_probability = 0.45

        mock_filter = MagicMock()
        mock_filter.should_execute.return_value = (True, mock_pred)

        handler._ml_filter_enabled = True
        handler._ml_signal_filter = mock_filter
        handler._ml_filter_mode = "shadow"
        handler._ml_shadow_threshold = 0.60  # Above the prediction

        handler._apply_ml_filter(valid_signal)

        # 0.45 < 0.60 => should NOT pass the shadow filter
        assert valid_signal["_ml_shadow_pass_filter"] is False
        assert valid_signal["_ml_shadow_threshold"] == 0.60

    def test_filter_error_handled_gracefully(self, handler, valid_signal):
        """ML filter error should not propagate; signal stays processable."""
        mock_filter = MagicMock()
        mock_filter.should_execute.side_effect = RuntimeError("model load failed")

        handler._ml_filter_enabled = True
        handler._ml_signal_filter = mock_filter

        # Must not raise
        handler._apply_ml_filter(valid_signal)

        assert "_ml_prediction" not in valid_signal

    def test_filter_extracts_regime_context(self, handler):
        """ML filter should build regime/volatility/session context from signal."""
        signal = make_valid_signal()
        signal["market_regime"] = {
            "regime": "trending",
            "volatility_ratio": 0.5,   # < 0.8 => "low"
            "session": "US_regular",
        }

        mock_pred = MagicMock()
        mock_pred.to_dict.return_value = {"win_probability": 0.8}
        mock_pred.win_probability = 0.8

        mock_filter = MagicMock()
        mock_filter.should_execute.return_value = (True, mock_pred)

        handler._ml_filter_enabled = True
        handler._ml_signal_filter = mock_filter

        handler._apply_ml_filter(signal)

        ctx = mock_filter.should_execute.call_args[0][1]  # 2nd positional arg
        assert ctx["regime"]["regime"] == "trending"
        assert ctx["regime"]["volatility"] == "low"
        assert ctx["regime"]["session"] == "US_regular"

    def test_filter_high_volatility_bucket(self, handler):
        """Volatility ratio > 1.5 should map to 'high' bucket."""
        signal = make_valid_signal()
        signal["market_regime"] = {"regime": "volatile", "volatility_ratio": 2.0, "session": ""}

        mock_pred = MagicMock()
        mock_pred.to_dict.return_value = {"win_probability": 0.5}
        mock_pred.win_probability = 0.5

        mock_filter = MagicMock()
        mock_filter.should_execute.return_value = (True, mock_pred)

        handler._ml_filter_enabled = True
        handler._ml_signal_filter = mock_filter

        handler._apply_ml_filter(signal)

        ctx = mock_filter.should_execute.call_args[0][1]
        assert ctx["regime"]["volatility"] == "high"


# ===========================================================================
# Tests: Bandit Policy
# ===========================================================================

class TestBanditPolicy:
    """Tests for _apply_bandit_policy."""

    def test_no_policy_sets_not_evaluated(self, handler, valid_signal):
        """Without a bandit policy, status should be 'not_evaluated'."""
        result = handler._apply_bandit_policy(valid_signal)

        assert result is None
        assert valid_signal["_policy_status"] == "not_evaluated"

    def test_policy_decision_attached_to_signal(self, handler, valid_signal):
        """Bandit decision metadata should be written into the signal dict."""
        mock_decision = MagicMock()
        mock_decision.execute = True
        mock_decision.sampled_score = 0.85
        mock_decision.mode = "thompson"
        mock_decision.reason = "explore"
        mock_decision.size_multiplier = 1.2
        mock_decision.to_dict.return_value = {"execute": True, "mode": "thompson", "score": 0.85}

        mock_policy = MagicMock()
        mock_policy.decide.return_value = mock_decision

        handler.bandit_policy = mock_policy
        result = handler._apply_bandit_policy(valid_signal)

        assert result is mock_decision
        assert valid_signal["_policy_status"] == "thompson:explore"
        assert valid_signal["_policy_execute"] is True
        assert valid_signal["_policy_score"] == 0.85
        assert valid_signal["_policy_size_multiplier"] == 1.2
        assert valid_signal["_policy"] == {"execute": True, "mode": "thompson", "score": 0.85}

    def test_policy_error_captured_in_status(self, handler, valid_signal):
        """Bandit policy error should be caught and recorded, not re-raised."""
        mock_policy = MagicMock()
        mock_policy.decide.side_effect = ValueError("arm index out of range")

        handler.bandit_policy = mock_policy
        result = handler._apply_bandit_policy(valid_signal)

        assert result is None
        assert "error:" in valid_signal["_policy_status"]
        assert "arm index out of range" in valid_signal["_policy_status"]


# ===========================================================================
# Tests: Contextual Policy
# ===========================================================================

class TestContextualPolicy:
    """Tests for _apply_contextual_policy."""

    def test_skipped_when_none(self, handler, valid_signal):
        """No contextual policy should leave signal untouched."""
        handler.contextual_policy = None

        handler._apply_contextual_policy(valid_signal)

        assert "_policy_ctx" not in valid_signal

    def test_decision_attached_to_signal(self, handler, valid_signal):
        """Contextual policy decision and features should be stored on the signal."""
        mock_ctx_features = MagicMock()
        mock_ctx_features.to_dict.return_value = {
            "session": "US_regular",
            "regime": "trending",
            "time_bucket": "midday",
        }

        mock_ctx_decision = MagicMock()
        mock_ctx_decision.to_dict.return_value = {"execute": True, "score": 0.9}

        mock_ctx_policy = MagicMock()
        mock_ctx_policy.decide.return_value = mock_ctx_decision

        handler.contextual_policy = mock_ctx_policy
        handler._context_features_class = MagicMock(return_value=mock_ctx_features)

        handler._apply_contextual_policy(valid_signal)

        assert valid_signal["_context_features"] == {
            "session": "US_regular",
            "regime": "trending",
            "time_bucket": "midday",
        }
        assert valid_signal["_policy_ctx"] == {"execute": True, "score": 0.9}

    def test_error_captured_in_signal(self, handler, valid_signal):
        """Contextual policy error should be captured, not re-raised."""
        mock_ctx_policy = MagicMock()
        mock_ctx_policy.decide.side_effect = RuntimeError("context build failed")

        handler.contextual_policy = mock_ctx_policy
        handler._context_features_class = MagicMock(return_value=MagicMock())

        handler._apply_contextual_policy(valid_signal)

        assert "error" in valid_signal["_policy_ctx"]
        assert "context build failed" in valid_signal["_policy_ctx"]["error"]


# ===========================================================================
# Tests: Execution
# ===========================================================================

class TestExecution:
    """Tests for _execute_signal."""

    def test_no_adapter_marks_not_attempted(self, handler, valid_signal):
        """Without an execution adapter, status should be 'not_attempted'."""
        handler._execute_signal(valid_signal, policy_decision=None)

        assert valid_signal["_execution_status"] == "not_attempted"

    def test_precondition_skip(self, handler, valid_signal):
        """When preconditions fail, execution should be skipped with the reason."""
        mock_decision = MagicMock()
        mock_decision.execute = False
        mock_decision.reason = "symbol_not_whitelisted"

        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_decision

        handler.execution_adapter = mock_adapter
        handler._execute_signal(valid_signal, policy_decision=None)

        assert valid_signal["_execution_status"] == "skipped:symbol_not_whitelisted"

    def test_successful_placement(self, handler, valid_signal):
        """Successful order placement should set status='placed' and record the order ID."""
        mock_precond = MagicMock(execute=True)
        mock_result = MagicMock(success=True, parent_order_id="order_12345")

        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_precond

        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = mock_result

        handler.execution_adapter = mock_adapter

        with patch("asyncio.get_event_loop", return_value=mock_loop):
            handler._execute_signal(valid_signal, policy_decision=None)

        assert valid_signal["_execution_status"] == "placed"
        assert valid_signal["_execution_order_id"] == "order_12345"

    def test_placement_failure(self, handler, valid_signal):
        """Failed order placement should record the error in status."""
        mock_precond = MagicMock(execute=True)
        mock_result = MagicMock(success=False, error_message="insufficient_margin", parent_order_id=None)

        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_precond

        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = mock_result

        handler.execution_adapter = mock_adapter

        with patch("asyncio.get_event_loop", return_value=mock_loop):
            handler._execute_signal(valid_signal, policy_decision=None)

        assert valid_signal["_execution_status"] == "place_failed:insufficient_margin"

    def test_execution_error_caught(self, handler, valid_signal):
        """Exception in execution adapter should be caught and recorded."""
        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.side_effect = ConnectionError("broker disconnect")

        handler.execution_adapter = mock_adapter
        handler._execute_signal(valid_signal, policy_decision=None)

        assert "error:" in valid_signal["_execution_status"]
        assert "broker disconnect" in valid_signal["_execution_status"]

    def test_live_policy_blocks_execution(self, handler, valid_signal):
        """In live mode, policy.execute=False should skip execution entirely."""
        mock_policy = MagicMock(execute=False, reason="low_score")
        mock_bandit_config = MagicMock(mode="live")

        handler._bandit_config = mock_bandit_config
        handler.execution_adapter = MagicMock()

        handler._execute_signal(valid_signal, policy_decision=mock_policy)

        assert valid_signal["_execution_status"] == "policy_skip:low_score"
        handler.execution_adapter.check_preconditions.assert_not_called()

    def test_live_policy_applies_size_multiplier(self, handler, valid_signal):
        """In live mode, position_size should be scaled by the policy multiplier."""
        valid_signal["position_size"] = 4

        mock_policy = MagicMock(execute=True, size_multiplier=0.5, reason="exploit")
        mock_bandit_config = MagicMock(mode="live")

        mock_precond = MagicMock(execute=True)
        mock_result = MagicMock(success=True, parent_order_id="order_789")

        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_precond

        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = mock_result

        handler._bandit_config = mock_bandit_config
        handler.execution_adapter = mock_adapter

        with patch("asyncio.get_event_loop", return_value=mock_loop):
            handler._execute_signal(valid_signal, policy_decision=mock_policy)

        # 4 * 0.5 = 2.0, int(2.0) = 2, max(1, 2) = 2
        assert valid_signal["position_size"] == 2
        assert valid_signal["_execution_status"] == "placed"

    def test_size_multiplier_minimum_clamp(self, handler, valid_signal):
        """Position size should never be reduced below 1 by the multiplier."""
        valid_signal["position_size"] = 1

        mock_policy = MagicMock(execute=True, size_multiplier=0.01, reason="explore")
        mock_bandit_config = MagicMock(mode="live")

        mock_precond = MagicMock(execute=True)
        mock_result = MagicMock(success=True, parent_order_id="order_min")

        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_precond

        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = mock_result

        handler._bandit_config = mock_bandit_config
        handler.execution_adapter = mock_adapter

        with patch("asyncio.get_event_loop", return_value=mock_loop):
            handler._execute_signal(valid_signal, policy_decision=mock_policy)

        # 1 * 0.01 = 0.01, int(0.01) = 0, max(1, 0) = 1
        assert valid_signal["position_size"] == 1


# ===========================================================================
# Tests: Virtual Entry Tracking
# ===========================================================================

class TestVirtualEntry:
    """Tests for _track_virtual_entry."""

    def test_valid_price_tracked(self, handler, valid_signal):
        """A positive entry price should be tracked and returned."""
        valid_signal["entry_price"] = 20000.0

        result = handler._track_virtual_entry(valid_signal, "signal-abc123")

        assert result == 20000.0
        handler.performance_tracker.track_entry.assert_called_once()
        call_kwargs = handler.performance_tracker.track_entry.call_args.kwargs
        assert call_kwargs["signal_id"] == "signal-abc123"
        assert call_kwargs["entry_price"] == 20000.0
        assert isinstance(call_kwargs["entry_time"], datetime)

    def test_missing_price_defaults_to_zero(self, handler, valid_signal):
        """Missing entry_price should default to 0.0 and skip track_entry."""
        valid_signal.pop("entry_price", None)

        result = handler._track_virtual_entry(valid_signal, "signal-xyz")

        assert result == 0.0
        handler.performance_tracker.track_entry.assert_not_called()

    def test_zero_price_skips_tracking(self, handler, valid_signal):
        """Zero entry price should return 0.0 and not call track_entry."""
        valid_signal["entry_price"] = 0.0

        result = handler._track_virtual_entry(valid_signal, "signal-zero")

        assert result == 0.0
        handler.performance_tracker.track_entry.assert_not_called()


# ===========================================================================
# Tests: Error Handling in process_signal
# ===========================================================================

@pytest.mark.asyncio
class TestProcessSignalErrorHandling:
    """Tests for error handling and graceful degradation."""

    async def test_pipeline_error_increments_error_count(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Unhandled error mid-pipeline should increment error_count, not crash."""
        performance_tracker.track_signal_generated.side_effect = RuntimeError("DB write failed")

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        await h.process_signal(make_valid_signal())

        assert h.error_count == 1
        assert h.signal_count == 0  # Did not complete

    async def test_ml_sizing_failure_is_non_fatal(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """ML opportunity sizing failure should NOT stop signal processing."""
        order_manager.apply_ml_opportunity_sizing.side_effect = ValueError("bad feature vector")

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        await h.process_signal(make_valid_signal())

        assert h.signal_count == 1
        assert h.error_count == 0

    async def test_notification_queue_full_records_failure(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """When notification queue returns False, send-failure should be recorded."""
        notification_queue.enqueue_entry = AsyncMock(return_value=False)

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        await h.process_signal(make_valid_signal())

        assert h.signals_send_failures == 1
        assert h.signals_sent == 0
        assert h.last_signal_send_error == "Notification queue full - entry dropped"


# ===========================================================================
# Tests: Notification Priority
# ===========================================================================

@pytest.mark.asyncio
class TestNotificationPriority:
    """Tests for entry notification priority selection."""

    async def test_default_priority_is_high(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Default entry notification priority should be Priority.HIGH."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        await h.process_signal(make_valid_signal())

        call_kwargs = notification_queue.enqueue_entry.call_args.kwargs
        assert call_kwargs["priority"] == Priority.HIGH

    async def test_ml_critical_elevates_to_critical_priority(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Signal with _ml_priority='critical' should escalate to Priority.CRITICAL."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        signal = make_valid_signal()
        signal["_ml_priority"] = "critical"

        await h.process_signal(signal)

        call_kwargs = notification_queue.enqueue_entry.call_args.kwargs
        assert call_kwargs["priority"] == Priority.CRITICAL


# ===========================================================================
# Tests: Edge Cases
# ===========================================================================

@pytest.mark.asyncio
class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    async def test_empty_signal_dict(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Empty signal dict should process without crashing."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        await h.process_signal({})

        assert h.signal_count == 1
        assert h.error_count == 0

    async def test_none_entry_price(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Signal with entry_price=None should default to 0.0 and still process."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        signal = make_valid_signal()
        signal["entry_price"] = None

        await h.process_signal(signal)

        assert h.signal_count == 1

    async def test_multiple_signals_accumulate_counters(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Processing N signals should increment counters N times."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        for i in range(3):
            signal = make_valid_signal()
            signal["signal_id"] = f"signal-{i:03d}"
            await h.process_signal(signal)

        assert h.signal_count == 3
        assert h.signals_sent == 3
        assert performance_tracker.track_signal_generated.call_count == 3

    async def test_signal_with_high_vol_regime(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Signal carrying a high-volatility market_regime should process normally."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        signal = make_valid_signal()
        signal["market_regime"] = {
            "regime": "volatile",
            "volatility_ratio": 2.0,
            "session": "US_extended",
        }

        await h.process_signal(signal)

        assert h.signal_count == 1
        assert h.error_count == 0

    async def test_buffer_data_none_passes(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Explicitly passing buffer_data=None should not cause errors."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        await h.process_signal(make_valid_signal(), buffer_data=None)

        assert h.signal_count == 1


# ===========================================================================
# Tests: Build Context Features
# ===========================================================================

class TestBuildContextFeatures:
    """Tests for _build_context_features_for_signal."""

    def test_no_context_class_returns_none(self, handler, valid_signal):
        """Without a context features class, the builder should return None."""
        handler._context_features_class = None

        result = handler._build_context_features_for_signal(valid_signal)

        assert result is None

    def test_morning_time_bucket(self, handler):
        """Timestamp with hour < 10 should yield 'morning' time bucket."""
        mock_ctx_class = MagicMock()
        handler._context_features_class = mock_ctx_class

        signal = make_valid_signal()
        signal["timestamp"] = "2024-06-15T08:30:00Z"

        handler._build_context_features_for_signal(signal)

        assert mock_ctx_class.call_args.kwargs["time_bucket"] == "morning"

    def test_midday_time_bucket(self, handler):
        """Timestamp with 10 <= hour < 14 should yield 'midday' time bucket."""
        mock_ctx_class = MagicMock()
        handler._context_features_class = mock_ctx_class

        signal = make_valid_signal()
        signal["timestamp"] = "2024-06-15T12:00:00Z"

        handler._build_context_features_for_signal(signal)

        assert mock_ctx_class.call_args.kwargs["time_bucket"] == "midday"

    def test_afternoon_time_bucket(self, handler):
        """Timestamp with hour >= 14 should yield 'afternoon' time bucket."""
        mock_ctx_class = MagicMock()
        handler._context_features_class = mock_ctx_class

        signal = make_valid_signal()
        signal["timestamp"] = "2024-06-15T15:30:00Z"

        handler._build_context_features_for_signal(signal)

        assert mock_ctx_class.call_args.kwargs["time_bucket"] == "afternoon"

    def test_session_extracted_from_underscore_key(self, handler):
        """Session should be read from signal['_session'] first."""
        mock_ctx_class = MagicMock()
        handler._context_features_class = mock_ctx_class

        signal = make_valid_signal()
        signal["_session"] = "US_regular"

        handler._build_context_features_for_signal(signal)

        assert mock_ctx_class.call_args.kwargs["session"] == "US_regular"

    def test_regime_extracted_from_market_regime(self, handler):
        """Regime should be read from signal['market_regime']['regime']."""
        mock_ctx_class = MagicMock()
        handler._context_features_class = mock_ctx_class

        signal = make_valid_signal()
        signal["market_regime"] = {"regime": "range_bound"}

        handler._build_context_features_for_signal(signal)

        assert mock_ctx_class.call_args.kwargs["regime"] == "range_bound"

    def test_defaults_when_no_context_in_signal(self, handler):
        """Missing session / regime / timestamp should all default to 'unknown'."""
        mock_ctx_class = MagicMock()
        handler._context_features_class = mock_ctx_class

        signal = {}  # No session, no market_regime, no timestamp

        handler._build_context_features_for_signal(signal)

        kwargs = mock_ctx_class.call_args.kwargs
        assert kwargs["session"] == "unknown"
        assert kwargs["regime"] == "unknown"
        assert kwargs["time_bucket"] == "unknown"
