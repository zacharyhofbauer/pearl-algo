"""Tests for pearlalgo.execution.tradovate.trailing_stop."""

from __future__ import annotations

import pytest

from pearlalgo.execution.tradovate.trailing_stop import (
    TrailingPhase,
    TrailingState,
    TrailingStopManager,
)


def _make_config(enabled=True, min_move=0.50, phases=None):
    if phases is None:
        phases = [
            {"name": "breakeven", "activation_atr": 1.0, "trail_atr": 0.0},
            {"name": "lock_profit", "activation_atr": 2.0, "trail_atr": 1.5},
            {"name": "tight_trail", "activation_atr": 3.0, "trail_atr": 1.0},
        ]
    return {
        "trailing_stop": {
            "enabled": enabled,
            "min_move_points": min_move,
            "phases": phases,
        }
    }


class TestTrailingStopManagerInit:
    def test_disabled(self):
        mgr = TrailingStopManager(_make_config(enabled=False))
        assert not mgr.enabled

    def test_enabled(self):
        mgr = TrailingStopManager(_make_config())
        assert mgr.enabled
        assert len(mgr.phases) == 3

    def test_phases_sorted_descending(self):
        mgr = TrailingStopManager(_make_config())
        atr_vals = [p.activation_atr for p in mgr.phases]
        assert atr_vals == sorted(atr_vals, reverse=True)

    def test_empty_config(self):
        mgr = TrailingStopManager({})
        assert not mgr.enabled
        assert len(mgr.phases) == 0


class TestRegisterAndRemove:
    def test_register_position(self):
        mgr = TrailingStopManager(_make_config())
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        assert mgr.active_positions == 1

    def test_remove_position(self):
        mgr = TrailingStopManager(_make_config())
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        mgr.remove_position("pos1")
        assert mgr.active_positions == 0

    def test_remove_nonexistent(self):
        mgr = TrailingStopManager(_make_config())
        mgr.remove_position("nonexistent")  # Should not raise


class TestGetState:
    def test_existing(self):
        mgr = TrailingStopManager(_make_config())
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        state = mgr.get_state("pos1")
        assert state is not None
        assert state["entry_price"] == 17500.0
        assert state["direction"] == "long"

    def test_nonexistent(self):
        mgr = TrailingStopManager(_make_config())
        assert mgr.get_state("nonexistent") is None


class TestCheckAndUpdateLong:
    def test_disabled_returns_none(self):
        mgr = TrailingStopManager(_make_config(enabled=False))
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        assert mgr.check_and_update("pos1", 17510.0, 5.0) is None

    def test_no_phases(self):
        mgr = TrailingStopManager(_make_config(phases=[]))
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        assert mgr.check_and_update("pos1", 17510.0, 5.0) is None

    def test_unknown_position(self):
        mgr = TrailingStopManager(_make_config())
        assert mgr.check_and_update("missing", 17510.0, 5.0) is None

    def test_zero_atr(self):
        mgr = TrailingStopManager(_make_config())
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        assert mgr.check_and_update("pos1", 17510.0, 0.0) is None

    def test_no_favorable_move(self):
        mgr = TrailingStopManager(_make_config())
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        assert mgr.check_and_update("pos1", 17499.0, 5.0) is None

    def test_breakeven_phase(self):
        mgr = TrailingStopManager(_make_config(min_move=0.10))
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        # Move 1.0 ATR favorable with ATR=5.0 -> 5 pts
        result = mgr.check_and_update("pos1", 17505.0, 5.0)
        assert result is not None
        # Breakeven = entry + tick (0.25)
        assert result == pytest.approx(17500.25)

    def test_lock_profit_phase(self):
        mgr = TrailingStopManager(_make_config(min_move=0.10))
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        # Move 2.0 ATR favorable with ATR=5.0 -> 10 pts
        result = mgr.check_and_update("pos1", 17510.0, 5.0)
        assert result is not None
        # Trail 1.5 ATR behind best: 17510 - 7.5 = 17502.5
        assert result == pytest.approx(17502.5)

    def test_tight_trail_phase(self):
        mgr = TrailingStopManager(_make_config(min_move=0.10))
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        # Move 3.0 ATR favorable with ATR=5.0 -> 15 pts
        result = mgr.check_and_update("pos1", 17515.0, 5.0)
        assert result is not None
        # Trail 1.0 ATR behind best: 17515 - 5.0 = 17510.0
        assert result == pytest.approx(17510.0)

    def test_ratchet_never_loosens(self):
        mgr = TrailingStopManager(_make_config(min_move=0.10))
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        # First update: trigger breakeven
        mgr.check_and_update("pos1", 17505.0, 5.0)
        # Try to update with lower price -> should not loosen
        result = mgr.check_and_update("pos1", 17505.0, 10.0)
        # With ATR=10, 5pt move = 0.5 ATR, below all phases -> None
        assert result is None

    def test_min_move_filter(self):
        mgr = TrailingStopManager(_make_config(min_move=5.0))
        mgr.register_position("pos1", 17500.0, "long", 17480.0)
        # Breakeven would be 17500.25 — distance from initial stop 17480 = 20.25 pts
        # But min_move is 5.0, and move from last_modified is 17500.25 - 17480 = 20.25 -> passes
        result = mgr.check_and_update("pos1", 17505.0, 5.0)
        assert result is not None


class TestCheckAndUpdateShort:
    def test_breakeven_short(self):
        mgr = TrailingStopManager(_make_config(min_move=0.10))
        mgr.register_position("pos1", 17500.0, "short", 17520.0)
        # Move 1.0 ATR favorable (price drops) with ATR=5.0
        result = mgr.check_and_update("pos1", 17495.0, 5.0)
        assert result is not None
        # Breakeven = entry - tick = 17499.75
        assert result == pytest.approx(17499.75)

    def test_lock_profit_short(self):
        mgr = TrailingStopManager(_make_config(min_move=0.10))
        mgr.register_position("pos1", 17500.0, "short", 17520.0)
        # Move 2.0 ATR favorable (price drops 10)
        result = mgr.check_and_update("pos1", 17490.0, 5.0)
        assert result is not None
        # Trail 1.5 ATR behind best: 17490 + 7.5 = 17497.5
        assert result == pytest.approx(17497.5)

    def test_ratchet_never_loosens_short(self):
        mgr = TrailingStopManager(_make_config(min_move=0.10))
        mgr.register_position("pos1", 17500.0, "short", 17520.0)
        # Trigger lock_profit phase
        first = mgr.check_and_update("pos1", 17490.0, 5.0)
        assert first is not None
        # Now price rises — stop should not move up
        second = mgr.check_and_update("pos1", 17495.0, 5.0)
        assert second is None


class TestTrailingPhaseDataclass:
    def test_fields(self):
        p = TrailingPhase("test", 1.0, 0.5)
        assert p.name == "test"
        assert p.activation_atr == 1.0
        assert p.trail_atr == 0.5
