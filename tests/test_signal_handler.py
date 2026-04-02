"""
Tests for SignalHandler

Tests:
- Constructor initialization with required and optional dependencies
- get_stats method
- Signal processing happy path (circuit breaker, execution, notification)
- Signal rejection by circuit breaker (enforce vs warn-only modes)
- Execution gating, placement
- Virtual entry tracking
- Error handling and graceful degradation
- Notification queue full / priority escalation
- Edge cases (empty signals, missing fields, multiple signals)
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.market_agent.notification_queue import Priority
from pearlalgo.market_agent.signal_handler import SignalHandler



@pytest.fixture(autouse=True)
def _mock_config_for_signal_type_gate():
    """Ensure signal type gate allows test signal types (sr_bounce etc.)."""
    fake_cfg = {"signals": {"enabled_signal_types": None}}  # None = allow all
    with patch(
        "pearlalgo.market_agent.signal_handler.SignalHandler._is_signal_type_allowed",
        return_value=True,
    ):
        yield

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def make_mock_state_manager(tmp_path=None):
    """Create a mock MarketAgentStateManager with safe defaults.

    When *tmp_path* is provided, ``state_dir`` is set to a real directory
    so that ``state_dir / "filename"`` returns a real Path instead of a
    MagicMock string — which would otherwise be used as a literal filename
    and pollute the repo root with junk files.
    """
    sm = MagicMock()
    sm.get_recent_signals.return_value = []
    if tmp_path is not None:
        sm.state_dir = tmp_path
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
    """Create a mock OrderManager with safe defaults."""
    om = MagicMock()
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
def state_manager(tmp_path):
    """Mock state manager fixture with real state_dir path."""
    return make_mock_state_manager(tmp_path)


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
        ea = MagicMock()
        tn = MagicMock()

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
            trading_circuit_breaker=cb,
            execution_adapter=ea,
            telegram_notifier=tn,
        )

        assert h.trading_circuit_breaker is cb
        assert h.execution_adapter is ea
        assert h.telegram_notifier is tn



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
        """A valid signal should traverse every stage: CB check -> tracking
        -> virtual entry -> execution -> notification."""
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
# Tests: Execution
# ===========================================================================

class TestExecution:
    """Tests for _execute_signal."""

    @pytest.mark.asyncio
    async def test_no_adapter_marks_not_attempted(self, handler, valid_signal):
        """Without an execution adapter, status should be 'not_attempted'."""
        await handler._execute_signal(valid_signal, policy_decision=None)

        assert valid_signal["_execution_status"] == "not_attempted"

    @pytest.mark.asyncio
    async def test_precondition_skip(self, handler, valid_signal):
        """When preconditions fail, execution should be skipped with the reason."""
        mock_decision = MagicMock()
        mock_decision.execute = False
        mock_decision.reason = "symbol_not_whitelisted"

        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_decision

        handler.execution_adapter = mock_adapter
        await handler._execute_signal(valid_signal, policy_decision=None)

        assert valid_signal["_execution_status"] == "skipped:symbol_not_whitelisted"

    @pytest.mark.asyncio
    async def test_successful_placement(self, handler, valid_signal):
        """Successful order placement should set status='placed' and record the order ID."""
        mock_precond = MagicMock(execute=True)
        mock_result = MagicMock(success=True, parent_order_id="order_12345")

        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_precond
        mock_adapter.place_bracket = AsyncMock(return_value=mock_result)

        handler.execution_adapter = mock_adapter
        await handler._execute_signal(valid_signal, policy_decision=None)

        assert valid_signal["_execution_status"] == "placed"
        assert valid_signal["_execution_order_id"] == "order_12345"

    @pytest.mark.asyncio
    async def test_placement_failure(self, handler, valid_signal):
        """Failed order placement should record the error in status."""
        mock_precond = MagicMock(execute=True)
        mock_result = MagicMock(success=False, error_message="insufficient_margin", parent_order_id=None)

        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_precond
        mock_adapter.place_bracket = AsyncMock(return_value=mock_result)

        handler.execution_adapter = mock_adapter
        await handler._execute_signal(valid_signal, policy_decision=None)

        assert valid_signal["_execution_status"] == "place_failed:insufficient_margin"

    @pytest.mark.asyncio
    async def test_execution_error_caught(self, handler, valid_signal):
        """Exception in execution adapter should be caught and recorded."""
        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.side_effect = ConnectionError("broker disconnect")

        handler.execution_adapter = mock_adapter
        await handler._execute_signal(valid_signal, policy_decision=None)

        assert "error:" in valid_signal["_execution_status"]
        assert "broker disconnect" in valid_signal["_execution_status"]



# ===========================================================================
# Tests: Pipeline regression for position_size (5C / 11A)
# ===========================================================================

@pytest.mark.asyncio
class TestPositionSizePipelineRegression:
    """Pipeline tests: signal without position_size gets it set before execution adapter."""

    async def test_process_signal_sets_position_size_before_execution(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """process_signal: signal without position_size reaches adapter with position_size > 0."""
        signal = make_valid_signal()
        signal.pop("position_size", None)

        order_manager.compute_base_position_size.return_value = 2

        mock_precond = MagicMock(execute=True)
        mock_result = MagicMock(success=True, parent_order_id="ord-1")
        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_precond
        mock_adapter.place_bracket = AsyncMock(return_value=mock_result)

        cb = MagicMock()
        cb.should_allow_signal.return_value = make_cb_decision(allowed=True)

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
            trading_circuit_breaker=cb,
            execution_adapter=mock_adapter,
        )

        await h.process_signal(signal)

        passed_signal = mock_adapter.check_preconditions.call_args[0][0]
        assert passed_signal.get("position_size", 0) > 0
        passed_signal_place = mock_adapter.place_bracket.call_args[0][0]
        assert passed_signal_place.get("position_size", 0) > 0

    async def test_follower_execute_sets_position_size_before_execution(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """follower_execute: signal without position_size reaches adapter with position_size > 0."""
        signal = make_valid_signal()
        signal.pop("position_size", None)

        order_manager.compute_base_position_size.return_value = 2

        mock_precond = MagicMock(execute=True)
        mock_result = MagicMock(success=True, parent_order_id="ord-1")
        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = mock_precond
        mock_adapter.place_bracket = AsyncMock(return_value=mock_result)

        cb = MagicMock()
        cb.should_allow_signal.return_value = make_cb_decision(allowed=True)

        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
            trading_circuit_breaker=cb,
            execution_adapter=mock_adapter,
        )

        await h.follower_execute(signal)

        passed_signal = mock_adapter.check_preconditions.call_args[0][0]
        assert passed_signal.get("position_size", 0) > 0
        passed_signal_place = mock_adapter.place_bracket.call_args[0][0]
        assert passed_signal_place.get("position_size", 0) > 0


# ===========================================================================
# Tests: _ensure_position_size (9A)
# ===========================================================================

class TestEnsurePositionSize:
    """Unit tests for _ensure_position_size."""

    def test_no_position_size_computes_from_order_manager(self, handler):
        """Signal with no position_size key should get size from order_manager."""
        signal = make_valid_signal()
        signal.pop("position_size", None)
        handler.order_manager.compute_base_position_size.return_value = 3

        handler._ensure_position_size(signal)

        assert signal["position_size"] == 3
        handler.order_manager.compute_base_position_size.assert_called_once_with(signal)

    def test_position_size_zero_recomputes(self, handler):
        """Signal with position_size=0 should trigger recompute."""
        signal = make_valid_signal()
        signal["position_size"] = 0
        handler.order_manager.compute_base_position_size.return_value = 2

        handler._ensure_position_size(signal)

        assert signal["position_size"] == 2
        handler.order_manager.compute_base_position_size.assert_called_once_with(signal)

    def test_valid_position_size_preserved(self, handler):
        """Signal with position_size=5 should be left unchanged."""
        signal = make_valid_signal()
        signal["position_size"] = 5

        handler._ensure_position_size(signal)

        assert signal["position_size"] == 5
        handler.order_manager.compute_base_position_size.assert_not_called()

    def test_non_int_type_logs_warning_and_recomputes(self, handler):
        """Signal with position_size='3' (non-int) should recompute (warning is implementation detail)."""
        signal = make_valid_signal()
        signal["position_size"] = "3"
        handler.order_manager.compute_base_position_size.return_value = 2

        handler._ensure_position_size(signal)

        assert signal["position_size"] == 2
        handler.order_manager.compute_base_position_size.assert_called_once_with(signal)

    def test_order_manager_exception_sets_zero(self, handler):
        """When compute_base_position_size raises, signal should get position_size=0 (fail closed)."""
        signal = make_valid_signal()
        signal.pop("position_size", None)
        handler.order_manager.compute_base_position_size.side_effect = RuntimeError("sizing error")

        handler._ensure_position_size(signal)

        assert signal["position_size"] == 0

    def test_negative_position_size_recomputes(self, handler):
        """Signal with position_size=-1 should trigger recompute."""
        signal = make_valid_signal()
        signal["position_size"] = -1
        handler.order_manager.compute_base_position_size.return_value = 1

        handler._ensure_position_size(signal)

        assert signal["position_size"] == 1
        handler.order_manager.compute_base_position_size.assert_called_once_with(signal)


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



# ===========================================================================
# Tests: Edge Cases
# ===========================================================================

@pytest.mark.asyncio
class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    async def test_empty_signal_dict(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Empty signal dict should be rejected (no entry_price) without crashing."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        await h.process_signal({})

        # Empty signal has no entry_price, so the guard rejects it
        assert h.signal_count == 0
        assert h.error_count == 0

    async def test_none_entry_price(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Signal with entry_price=None should be rejected by guard clause."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        signal = make_valid_signal()
        signal["entry_price"] = None

        await h.process_signal(signal)

        # Guard rejects None entry_price
        assert h.signal_count == 0

    async def test_zero_entry_price_rejected(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Signal with entry_price=0 should be rejected by _validate_entry_price guard."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        signal = make_valid_signal()
        signal["entry_price"] = 0

        await h.process_signal(signal)

        # Guard rejects entry_price <= 0
        assert h.signal_count == 0

    async def test_negative_entry_price_rejected(
        self, state_manager, performance_tracker, notification_queue, order_manager
    ):
        """Signal with entry_price=-100 should be rejected by _validate_entry_price guard."""
        h = SignalHandler(
            state_manager=state_manager,
            performance_tracker=performance_tracker,
            notification_queue=notification_queue,
            order_manager=order_manager,
        )

        signal = make_valid_signal()
        signal["entry_price"] = -100.0

        await h.process_signal(signal)

        # Guard rejects negative entry_price
        assert h.signal_count == 0

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


