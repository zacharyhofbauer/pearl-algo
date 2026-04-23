"""Issue 10-A — behavioral e2e test for ``SignalHandler.process_signal``.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 3.

The existing ``tests/test_signal_pipeline_e2e.py`` is a plumbing trace
(every boundary is a ``MagicMock`` preset to succeed). It exercises the
Python ordering of ``SignalHandler.process_signal`` calls but will
silently pass through real behavioral regressions. This new suite runs
a REAL ``TradingCircuitBreaker`` and a *recording* execution adapter so
the test can assert:

  * The bracket the adapter saw matches the signal's entry/stop/tp.
  * CB decisions actually affect dispatch (block when rules trigger,
    allow when they don't).
  * SignalHandler honors the ``execute=False`` decision from the
    adapter's precondition gate.

Other collaborators (state_manager, performance_tracker, order_manager,
notification_queue, audit_logger) stay as minimal stubs because they
don't participate in the behavioral invariants this test pins.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from pearlalgo.market_agent.circuit_breaker_types import (
    CircuitBreakerDecision,
    TradingCircuitBreakerConfig,
)
from pearlalgo.market_agent.signal_handler import SignalHandler
from pearlalgo.market_agent.trading_circuit_breaker import TradingCircuitBreaker


# ---------------------------------------------------------------------------
# Recording adapter — captures every bracket placement for assertion
# ---------------------------------------------------------------------------


@dataclass
class _RecordedBracket:
    signal_id: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float


@dataclass
class _PreDecision:
    execute: bool
    reason: str = ""
    bracket: Dict[str, float] = field(default_factory=dict)


class _PlaceResult:
    def __init__(
        self,
        *,
        success: bool,
        signal_id: str,
        order_id: str = "order-rec-001",
        status: str = "placed",
        error: Optional[str] = None,
    ) -> None:
        self.success = success
        self.status = status
        self.signal_id = signal_id
        self.order_id = order_id
        self.parent_order_id = order_id  # SignalHandler reads this name.
        self.stop_order_id = "stop-rec-001"
        self.take_profit_order_id = "tp-rec-001"
        self.error_message = error


class RecordingAdapter:
    """Captures every place_bracket call and exposes the submitted bracket."""

    def __init__(self, *, armed: bool = True) -> None:
        self.armed = armed
        self.recorded: List[_RecordedBracket] = []
        self._precond_default = _PreDecision(
            execute=True, reason="", bracket={}
        )
        self._block_preconditions = False
        self._place_returns_failure = False

    def block_preconditions(self) -> None:
        self._block_preconditions = True

    def fail_next_place(self) -> None:
        self._place_returns_failure = True

    def check_preconditions(self, signal: Dict[str, Any]) -> _PreDecision:
        if self._block_preconditions:
            return _PreDecision(execute=False, reason="adapter_blocked")
        return _PreDecision(
            execute=True,
            reason="",
            bracket={
                "entry": float(signal["entry_price"]),
                "sl": float(signal["stop_loss"]),
                "tp": float(signal["take_profit"]),
            },
        )

    async def place_bracket(self, signal: Dict[str, Any]) -> _PlaceResult:
        self.recorded.append(
            _RecordedBracket(
                signal_id=str(signal.get("signal_id", "")),
                direction=str(signal.get("direction", "")),
                entry_price=float(signal["entry_price"]),
                stop_loss=float(signal["stop_loss"]),
                take_profit=float(signal["take_profit"]),
            )
        )
        if self._place_returns_failure:
            return _PlaceResult(
                success=False,
                signal_id=str(signal.get("signal_id", "")),
                status="error",
                error="recorded_failure",
            )
        return _PlaceResult(
            success=True,
            signal_id=str(signal.get("signal_id", "")),
        )


# ---------------------------------------------------------------------------
# Minimal stubs for collaborators that don't contribute to assertions
# ---------------------------------------------------------------------------


def _stub_state_manager() -> MagicMock:
    sm = MagicMock()
    sm.get_recent_signals.return_value = []
    sm.state_dir = "/tmp/pearl-algo-test"
    return sm


def _stub_performance_tracker() -> MagicMock:
    pt = MagicMock()
    pt.track_signal_generated.return_value = "sig-behavioral-001"
    pt.track_entry.return_value = None
    return pt


def _stub_notification_queue() -> MagicMock:
    nq = MagicMock()

    async def _ok(*_a, **_k):
        return True

    nq.enqueue_entry = _ok
    nq.enqueue_circuit_breaker = _ok
    nq.enqueue_raw_message = _ok
    return nq


def _stub_order_manager() -> MagicMock:
    om = MagicMock()
    om.compute_base_position_size.return_value = 1
    return om


def _make_signal(
    *,
    signal_id: str = "sig-behavioral-001",
    direction: str = "long",
    entry: float = 20000.0,
    stop: float = 19980.0,
    take: float = 20050.0,
    confidence: float = 0.75,
) -> Dict[str, Any]:
    return {
        "signal_id": signal_id,
        "type": "pearlbot_pinescript",
        "signal_type": "pearlbot_pinescript",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": take,
        "confidence": confidence,
        "entry_trigger": "ema_cross",
        "active_indicators": ["EMA_CROSS"],
        "timestamp": "2026-04-23T14:00:00Z",
        "symbol": "MNQ",
    }


def _make_handler(
    *,
    cb: TradingCircuitBreaker,
    adapter: RecordingAdapter,
) -> SignalHandler:
    return SignalHandler(
        state_manager=_stub_state_manager(),
        performance_tracker=_stub_performance_tracker(),
        notification_queue=_stub_notification_queue(),
        order_manager=_stub_order_manager(),
        trading_circuit_breaker=cb,
        execution_adapter=adapter,
        audit_logger=None,
    )


# ---------------------------------------------------------------------------
# Behavioral tests
# ---------------------------------------------------------------------------


def test_circuit_breaker_default_allows_long_signal_and_adapter_sees_exact_bracket():
    """Given a default-config CB and an armed adapter, a valid long signal
    must reach place_bracket with the signal's entry/sl/tp intact."""
    cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
    adapter = RecordingAdapter()
    handler = _make_handler(cb=cb, adapter=adapter)
    signal = _make_signal(entry=20000.0, stop=19980.0, take=20060.0)

    asyncio.run(handler.process_signal(signal))

    assert len(adapter.recorded) == 1
    rec = adapter.recorded[0]
    assert rec.direction == "long"
    assert rec.entry_price == 20000.0
    assert rec.stop_loss == 19980.0
    assert rec.take_profit == 20060.0


def test_circuit_breaker_blocks_after_max_consecutive_losses_tripped():
    """Feed the CB enough losing trades to trip max_consecutive_losses;
    the next signal must NOT reach the adapter."""
    cfg = TradingCircuitBreakerConfig(max_consecutive_losses=3)
    cb = TradingCircuitBreaker(cfg)
    adapter = RecordingAdapter()
    handler = _make_handler(cb=cb, adapter=adapter)

    # Simulate 3 losing trades to trip the gate.
    for i in range(3):
        cb.record_trade_result({
            "is_win": False,
            "pnl": -10.0,
            "exit_time": "2026-04-23T13:00:00",
        })

    signal = _make_signal()
    asyncio.run(handler.process_signal(signal))
    assert len(adapter.recorded) == 0, (
        "circuit breaker should have blocked the signal after max consecutive "
        "losses; adapter.place_bracket was called anyway"
    )


def test_adapter_precondition_block_short_circuits_dispatch():
    """Even with CB allowing, an adapter precondition failure must prevent
    place_bracket from being invoked."""
    cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
    adapter = RecordingAdapter()
    adapter.block_preconditions()

    handler = _make_handler(cb=cb, adapter=adapter)
    asyncio.run(handler.process_signal(_make_signal()))

    assert len(adapter.recorded) == 0


def test_short_signal_bracket_recorded_with_direction_short():
    """With direction_gating disabled, shorts must reach the adapter."""
    cfg = TradingCircuitBreakerConfig(enable_direction_gating=False)
    cb = TradingCircuitBreaker(cfg)
    adapter = RecordingAdapter()
    handler = _make_handler(cb=cb, adapter=adapter)

    signal = _make_signal(direction="short", entry=20000.0, stop=20025.0, take=19950.0)
    asyncio.run(handler.process_signal(signal))

    assert len(adapter.recorded) == 1
    rec = adapter.recorded[0]
    assert rec.direction == "short"
    assert rec.stop_loss == 20025.0
    assert rec.take_profit == 19950.0


def test_adapter_place_failure_does_not_propagate_as_exception():
    """SignalHandler must swallow a failed place_bracket gracefully — the
    service continues to the next cycle; the failure shows up in the
    signal record rather than raising."""
    cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
    adapter = RecordingAdapter()
    adapter.fail_next_place()
    handler = _make_handler(cb=cb, adapter=adapter)

    # Must not raise.
    asyncio.run(handler.process_signal(_make_signal()))
    # place_bracket WAS called once with the signal's bracket, even though
    # it returned failure.
    assert len(adapter.recorded) == 1


def test_cb_allowed_decision_dispatches_bracket():
    """Positive control: the most-basic happy path must work so the
    failure-path assertions above are trustworthy."""
    cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
    adapter = RecordingAdapter()
    handler = _make_handler(cb=cb, adapter=adapter)

    signal = _make_signal(signal_id="positive-control")
    asyncio.run(handler.process_signal(signal))

    assert len(adapter.recorded) == 1
    assert adapter.recorded[0].signal_id == "positive-control"


# ---------------------------------------------------------------------------
# Self-check: the real TradingCircuitBreaker is actually the class under test
# ---------------------------------------------------------------------------


def test_cb_used_is_real_not_a_mock():
    cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
    assert isinstance(cb, TradingCircuitBreaker)
    decision = cb.should_allow_signal(_make_signal())
    assert isinstance(decision, CircuitBreakerDecision)
