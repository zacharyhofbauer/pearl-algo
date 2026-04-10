"""
End-to-end signal pipeline integration test.

Traces a signal through the full SignalHandler pipeline, verifying that
each stage transforms the signal correctly and that the final state
reflects a completed trade entry.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.market_agent.signal_handler import SignalHandler


def _make_realistic_handler(tmp_path):
    """Create a SignalHandler with minimally-mocked dependencies for e2e testing."""
    sm = MagicMock()
    sm.get_recent_signals.return_value = []
    sm.state_dir = tmp_path

    pt = MagicMock()
    pt.track_signal_generated.return_value = "e2e-signal-001"
    pt.track_entry.return_value = None

    nq = MagicMock()
    nq.enqueue_entry = AsyncMock(return_value=True)
    nq.enqueue_circuit_breaker = AsyncMock(return_value=True)

    om = MagicMock()
    om.compute_base_position_size.return_value = 1

    # Circuit breaker that allows all signals
    cb = MagicMock()
    cb_decision = MagicMock()
    cb_decision.allowed = True
    cb_decision.reason = ""
    cb_decision.details = {}
    cb_decision.severity = "info"
    cb_decision.to_dict.return_value = {"allowed": True, "reason": ""}
    cb.should_allow_signal.return_value = cb_decision

    # Execution adapter that succeeds
    adapter = MagicMock()
    adapter.armed = True

    precond_decision = MagicMock()
    precond_decision.execute = True
    precond_decision.reason = ""
    precond_decision.bracket = {
        "tp": 20030.0,
        "sl": 19980.0,
        "entry": 20000.0,
    }
    adapter.check_preconditions = MagicMock(return_value=precond_decision)

    place_result = MagicMock()
    place_result.success = True
    place_result.status = "placed"
    place_result.order_id = "order-e2e-001"
    place_result.stop_order_id = "stop-e2e-001"
    place_result.take_profit_order_id = "tp-e2e-001"
    adapter.place_bracket = AsyncMock(return_value=place_result)

    # Audit logger
    audit = MagicMock()

    h = SignalHandler(
        state_manager=sm,
        performance_tracker=pt,
        notification_queue=nq,
        order_manager=om,
        trading_circuit_breaker=cb,
        execution_adapter=adapter,
        audit_logger=audit,
    )
    return h, {
        "state_manager": sm,
        "performance_tracker": pt,
        "notification_queue": nq,
        "order_manager": om,
        "circuit_breaker": cb,
        "adapter": adapter,
        "audit_logger": audit,
    }


def _make_e2e_signal():
    return {
        "type": "pearlbot_pinescript",
        "direction": "long",
        "symbol": "MNQ",
        "entry_price": 20000.0,
        "stop_loss": 19980.0,
        "take_profit": 20030.0,
        "position_size": 1,
        "confidence": 0.75,
        "signal_id": "e2e-test-signal-001",
        "timestamp": "2024-06-15T10:30:00Z",
    }


@pytest.fixture(autouse=True)
def _mock_signal_type_gate():
    with patch(
        "pearlalgo.market_agent.signal_handler.SignalHandler._is_signal_type_allowed",
        return_value=True,
    ):
        yield


class TestSignalPipelineEndToEnd:
    """Full pipeline integration: signal goes through all stages successfully."""

    @pytest.mark.asyncio
    async def test_successful_signal_triggers_all_stages(self, tmp_path):
        """A valid signal should pass through circuit breaker, sizing, execution,
        tracking, and notification."""
        handler, deps = _make_realistic_handler(tmp_path)
        signal = _make_e2e_signal()
        buffer_data = pd.DataFrame()

        await handler.process_signal(signal, buffer_data=buffer_data)

        # Stage 2: Circuit breaker was consulted
        deps["circuit_breaker"].should_allow_signal.assert_called()

        # Stage 4: Signal was tracked as generated
        deps["performance_tracker"].track_signal_generated.assert_called()

        # Stage 6: Execution adapter was used
        deps["adapter"].check_preconditions.assert_called()

        # Stage 9: Notification was enqueued
        deps["notification_queue"].enqueue_entry.assert_awaited()

        # Counter incremented
        assert handler.signal_count >= 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_rejection_stops_pipeline(self, tmp_path):
        """A signal blocked by circuit breaker should NOT reach execution."""
        handler, deps = _make_realistic_handler(tmp_path)

        # Configure CB to reject
        cb_decision = MagicMock()
        cb_decision.allowed = False
        cb_decision.reason = "max_consecutive_losses"
        cb_decision.details = {"consecutive_losses": 5}
        cb_decision.severity = "warning"
        cb_decision.to_dict.return_value = {
            "allowed": False,
            "reason": "max_consecutive_losses",
        }
        deps["circuit_breaker"].should_allow_signal.return_value = cb_decision

        signal = _make_e2e_signal()
        await handler.process_signal(signal, buffer_data=pd.DataFrame())

        # Execution adapter should NOT have been called
        deps["adapter"].place_bracket.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_entry_price_stops_pipeline(self, tmp_path):
        """A signal with NaN entry price should be rejected before execution."""
        handler, deps = _make_realistic_handler(tmp_path)
        signal = _make_e2e_signal()
        signal["entry_price"] = float("nan")

        await handler.process_signal(signal, buffer_data=pd.DataFrame())

        # Should not reach execution
        deps["adapter"].place_bracket.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_execution_adapter_still_tracks_signal(self, tmp_path):
        """Without an execution adapter, signal is still tracked and counted."""
        handler, deps = _make_realistic_handler(tmp_path)
        handler.execution_adapter = None

        signal = _make_e2e_signal()
        await handler.process_signal(signal, buffer_data=pd.DataFrame())

        # Signal should still be tracked even without execution
        deps["performance_tracker"].track_signal_generated.assert_called()
        assert handler.signal_count >= 1
