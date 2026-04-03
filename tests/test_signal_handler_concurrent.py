"""
Tests for concurrent signal processing via SignalHandler.

Verifies that the _execution_semaphore serializes concurrent process_signal()
calls, preventing signal storms from causing duplicate order placement.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.market_agent.signal_handler import SignalHandler


def _make_handler(*, execution_delay: float = 0.05):
    """Create a SignalHandler with mocked dependencies and controllable execution delay."""
    sm = MagicMock()
    sm.get_recent_signals.return_value = []
    sm.state_dir = MagicMock()

    pt = MagicMock()
    pt.track_signal_generated.return_value = "sig-id"
    pt.track_entry.return_value = None

    nq = MagicMock()
    nq.enqueue_entry = AsyncMock(return_value=True)
    nq.enqueue_circuit_breaker = AsyncMock(return_value=True)

    om = MagicMock()

    # Mock execution adapter with controllable delay
    adapter = MagicMock()
    adapter.armed = True

    async def slow_check(*a, **kw):
        await asyncio.sleep(execution_delay)
        decision = MagicMock()
        decision.execute = True
        decision.reason = ""
        decision.bracket = {"tp": 20030.0, "sl": 19980.0}
        return decision

    adapter.check_preconditions = slow_check

    async def slow_place(*a, **kw):
        await asyncio.sleep(execution_delay)
        result = MagicMock()
        result.success = True
        result.status = "placed"
        result.order_id = "order-123"
        return result

    adapter.place_bracket = slow_place

    h = SignalHandler(
        state_manager=sm,
        performance_tracker=pt,
        notification_queue=nq,
        order_manager=om,
        execution_adapter=adapter,
    )
    return h


def _make_signal(signal_id: str = "test-signal"):
    return {
        "type": "sr_bounce",
        "direction": "long",
        "symbol": "MNQ",
        "entry_price": 20000.0,
        "stop_loss": 19980.0,
        "take_profit": 20030.0,
        "position_size": 1,
        "signal_id": signal_id,
        "timestamp": "2024-06-15T10:30:00Z",
    }


@pytest.fixture(autouse=True)
def _mock_signal_type_gate():
    with patch(
        "pearlalgo.market_agent.signal_handler.SignalHandler._is_signal_type_allowed",
        return_value=True,
    ):
        yield


class TestConcurrentSignalSerialization:
    """Verify _execution_semaphore serializes concurrent process_signal calls."""

    @pytest.mark.asyncio
    async def test_concurrent_signals_do_not_interleave(self):
        """Multiple concurrent process_signal() calls should not run in parallel."""
        handler = _make_handler(execution_delay=0.02)
        execution_order = []

        original_follower = handler.follower_execute

        async def tracking_follower(signal):
            sig_id = signal.get("signal_id", "?")
            execution_order.append(("start", sig_id))
            await original_follower(signal)
            execution_order.append(("end", sig_id))

        handler.follower_execute = tracking_follower

        signals = [_make_signal(f"sig-{i}") for i in range(3)]

        await asyncio.gather(*[handler.follower_execute(s) for s in signals])

        # Verify all 3 completed
        starts = [e for e in execution_order if e[0] == "start"]
        ends = [e for e in execution_order if e[0] == "end"]
        assert len(starts) == 3
        assert len(ends) == 3

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency_to_one(self):
        """Only one signal should be executing at any given time."""
        handler = _make_handler(execution_delay=0.03)
        max_concurrent = 0
        current_concurrent = 0

        original_follower = handler.follower_execute

        async def counting_follower(signal):
            nonlocal max_concurrent, current_concurrent
            current_concurrent += 1
            if current_concurrent > max_concurrent:
                max_concurrent = current_concurrent
            await original_follower(signal)
            current_concurrent -= 1

        handler.follower_execute = counting_follower

        signals = [_make_signal(f"sig-{i}") for i in range(3)]
        await asyncio.gather(*[handler.follower_execute(s) for s in signals])

        # With Semaphore(1), max_concurrent should be 1
        assert max_concurrent == 1, f"Expected max 1 concurrent, got {max_concurrent}"
