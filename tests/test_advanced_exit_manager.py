"""Tests for pearlalgo.execution.advanced_exit_manager."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytz
import pytest

from pearlalgo.execution.advanced_exit_manager import (
    AdvancedExitManager,
    PartialRunnerManager,
    PartialRunnerState,
    RunnerPhase,
)

_ET = pytz.timezone("America/New_York")


def _now_et():
    """Naive ET datetime for test consistency with production code."""
    return datetime.now(_ET).replace(tzinfo=None)


def _make_config(
    quick_exit=True,
    time_based=True,
    stop_opt=True,
):
    return {
        "quick_exit": {
            "enabled": quick_exit,
            "min_duration_minutes": 20,
            "max_mfe_threshold": 20,
            "min_mae_threshold": 60,
        },
        "time_based_exit": {
            "enabled": time_based,
            "min_duration_minutes": 10,
            "min_profit_threshold": 30,
            "take_percentage": 0.70,
        },
        "stop_optimization": {
            "enabled": stop_opt,
            "mae_percentile": 75,
        },
    }


class TestInit:
    def test_all_enabled(self):
        mgr = AdvancedExitManager(_make_config())
        assert mgr.quick_exit_enabled
        assert mgr.time_exit_enabled
        assert mgr.stop_opt_enabled

    def test_all_disabled(self):
        mgr = AdvancedExitManager(_make_config(False, False, False))
        assert not mgr.quick_exit_enabled
        assert not mgr.time_exit_enabled
        assert not mgr.stop_opt_enabled

    def test_empty_config(self):
        mgr = AdvancedExitManager({})
        assert not mgr.quick_exit_enabled


class TestCheckQuickExit:
    def test_disabled(self):
        mgr = AdvancedExitManager(_make_config(quick_exit=False))
        should_exit, reason = mgr.check_quick_exit({}, 17500, _now_et() - timedelta(minutes=30))
        assert should_exit is False

    def test_too_early(self):
        mgr = AdvancedExitManager(_make_config())
        should_exit, _ = mgr.check_quick_exit({}, 17500, _now_et() - timedelta(minutes=5))
        assert should_exit is False

    def test_stalled_trade_exits(self):
        mgr = AdvancedExitManager(_make_config())
        pos = {"mfe_dollars": 10, "mae_dollars": 70, "unrealized_pnl": -5}
        should_exit, reason = mgr.check_quick_exit(pos, 17500, _now_et() - timedelta(minutes=25))
        assert should_exit is True
        assert "stalled" in reason.lower()

    def test_good_mfe_no_exit(self):
        mgr = AdvancedExitManager(_make_config())
        pos = {"mfe_dollars": 50, "mae_dollars": 70, "unrealized_pnl": 30}
        should_exit, _ = mgr.check_quick_exit(pos, 17500, _now_et() - timedelta(minutes=25))
        assert should_exit is False


class TestCheckTimeBasedExit:
    def test_disabled(self):
        mgr = AdvancedExitManager(_make_config(time_based=False))
        should_exit, _ = mgr.check_time_based_exit({}, 17500, _now_et() - timedelta(minutes=30))
        assert should_exit is False

    def test_too_early(self):
        mgr = AdvancedExitManager(_make_config())
        should_exit, _ = mgr.check_time_based_exit({}, 17500, _now_et() - timedelta(minutes=5))
        assert should_exit is False

    def test_declining_profit_exits(self):
        mgr = AdvancedExitManager(_make_config())
        pos = {"unrealized_pnl": 40, "mfe_dollars": 80}
        should_exit, reason = mgr.check_time_based_exit(pos, 17500, _now_et() - timedelta(minutes=15))
        # current_pnl (40) < target_exit (80 * 0.70 = 56) -> should exit
        assert should_exit is True
        assert "declining" in reason.lower()

    def test_still_profitable_no_exit(self):
        mgr = AdvancedExitManager(_make_config())
        pos = {"unrealized_pnl": 70, "mfe_dollars": 80}
        should_exit, _ = mgr.check_time_based_exit(pos, 17500, _now_et() - timedelta(minutes=15))
        # current_pnl (70) > target_exit (56) -> no exit
        assert should_exit is False


class TestGetOptimizedStop:
    def test_disabled(self):
        mgr = AdvancedExitManager(_make_config(stop_opt=False))
        result = mgr.get_optimized_stop(5.0, [10, 20, 30])
        assert result == pytest.approx(20.0)  # 4 ATR default

    def test_empty_data(self):
        mgr = AdvancedExitManager(_make_config())
        result = mgr.get_optimized_stop(5.0, [])
        assert result == pytest.approx(20.0)  # 4 ATR default

    def test_percentile_based(self):
        mgr = AdvancedExitManager(_make_config())
        mae_data = list(range(10, 30))  # 10 to 29
        result = mgr.get_optimized_stop(5.0, mae_data)
        # Clamped between 2*ATR=10 and 5*ATR=25
        assert 10.0 <= result <= 25.0

    def test_clamp_to_min(self):
        mgr = AdvancedExitManager(_make_config())
        result = mgr.get_optimized_stop(10.0, [1, 2, 3, 4, 5])
        # Min stop is 2*ATR=20, all MAE values are below that
        assert result == pytest.approx(20.0)


class TestShouldExit:
    def test_quick_exit_takes_priority(self):
        mgr = AdvancedExitManager(_make_config())
        pos = {"mfe_dollars": 10, "mae_dollars": 70, "unrealized_pnl": -5}
        should_exit, reason = mgr.should_exit(pos, 17500, _now_et() - timedelta(minutes=25))
        assert should_exit is True
        assert "quick" in reason.lower()

    def test_time_based_when_no_quick_exit(self):
        mgr = AdvancedExitManager(_make_config(quick_exit=False))
        pos = {"unrealized_pnl": 40, "mfe_dollars": 80}
        should_exit, reason = mgr.should_exit(pos, 17500, _now_et() - timedelta(minutes=15))
        assert should_exit is True
        assert "time" in reason.lower()

    def test_no_exit(self):
        mgr = AdvancedExitManager(_make_config(quick_exit=False, time_based=False))
        should_exit, _ = mgr.should_exit({}, 17500, _now_et())
        assert should_exit is False

    def test_max_hold_takes_highest_priority(self):
        """Max hold exit should fire before quick exit or time-based."""
        cfg = _make_config()
        cfg["max_hold_exit"] = {"enabled": True, "max_duration_minutes": 10}
        mgr = AdvancedExitManager(cfg)
        pos = {"mfe_dollars": 10, "mae_dollars": 70, "unrealized_pnl": -5}
        should_exit, reason = mgr.should_exit(pos, 17500, _now_et() - timedelta(minutes=25))
        assert should_exit is True
        assert "max hold" in reason.lower()


# ============================================================================
# PartialRunnerState
# ============================================================================


class TestPartialRunnerState:
    def test_init_sets_defaults(self):
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=5.0)
        assert state.entry_price == 100.0
        assert state.direction == "long"
        assert state.atr == 5.0
        assert state.breakeven_trigger_atr == 1.5
        assert state.tight_trail_trigger_atr == 2.5
        assert state.tight_trail_distance_atr == 1.0
        assert state.breakeven_offset == 0.25
        assert state.phase == RunnerPhase.INITIAL
        assert state.best_price == 100.0
        assert state.tp_cancelled is False

    def test_init_custom_params(self):
        state = PartialRunnerState(
            entry_price=200.0,
            direction="short",
            atr=10.0,
            breakeven_trigger_atr=2.0,
            tight_trail_trigger_atr=3.0,
            tight_trail_distance_atr=0.5,
            breakeven_offset=0.5,
        )
        assert state.direction == "short"
        assert state.breakeven_trigger_atr == 2.0
        assert state.tight_trail_trigger_atr == 3.0
        assert state.tight_trail_distance_atr == 0.5
        assert state.breakeven_offset == 0.5

    def test_favorable_move_long(self):
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=5.0)
        state.best_price = 110.0
        assert state.favorable_move == pytest.approx(2.0)

    def test_favorable_move_short(self):
        state = PartialRunnerState(entry_price=100.0, direction="short", atr=5.0)
        state.best_price = 90.0
        assert state.favorable_move == pytest.approx(2.0)

    def test_favorable_move_zero_atr(self):
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=0.0)
        state.best_price = 110.0
        assert state.favorable_move == 0.0

        state_short = PartialRunnerState(entry_price=100.0, direction="short", atr=0.0)
        state_short.best_price = 90.0
        assert state_short.favorable_move == 0.0


class TestPartialRunnerStateUpdate:
    """Tests for PartialRunnerState.update() — full phase transition logic."""

    def test_initial_no_transition(self):
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=10.0)
        action, new_stop, cancel_tp = state.update(105.0)
        assert action is None
        assert new_stop is None
        assert cancel_tp is False
        assert state.phase == RunnerPhase.INITIAL

    def test_long_breakeven_transition(self):
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=10.0)
        # Push price to 1.5x ATR above entry -> 115.0
        action, new_stop, cancel_tp = state.update(115.0)
        assert action == "move_to_breakeven"
        assert new_stop == pytest.approx(100.25)  # entry + 0.25 offset
        assert cancel_tp is True
        assert state.phase == RunnerPhase.BREAKEVEN
        assert state.tp_cancelled is True

    def test_short_breakeven_transition(self):
        state = PartialRunnerState(entry_price=100.0, direction="short", atr=10.0)
        # Push price to 1.5x ATR below entry -> 85.0
        action, new_stop, cancel_tp = state.update(85.0)
        assert action == "move_to_breakeven"
        assert new_stop == pytest.approx(99.75)  # entry - 0.25 offset
        assert cancel_tp is True
        assert state.phase == RunnerPhase.BREAKEVEN

    def test_long_tight_trail_transition(self):
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=10.0)
        # First get to breakeven (1.5x ATR = 115)
        state.update(115.0)
        assert state.phase == RunnerPhase.BREAKEVEN

        # Now push to 2.5x ATR = 125
        action, new_stop, cancel_tp = state.update(125.0)
        assert action == "tighten_trail"
        assert state.phase == RunnerPhase.TIGHT_TRAIL
        # trail_dist = 10.0 * 1.0 = 10.0; stop = 125 - 10 = 115
        assert new_stop == pytest.approx(115.0)
        assert cancel_tp is False

    def test_short_tight_trail_transition(self):
        state = PartialRunnerState(entry_price=100.0, direction="short", atr=10.0)
        # Breakeven at 85
        state.update(85.0)
        # Tight trail at 75 (2.5x ATR)
        action, new_stop, cancel_tp = state.update(75.0)
        assert action == "tighten_trail"
        assert state.phase == RunnerPhase.TIGHT_TRAIL
        # trail_dist = 10; stop = 75 + 10 = 85
        assert new_stop == pytest.approx(85.0)

    def test_long_tight_trail_continues_tightening(self):
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=10.0)
        state.update(115.0)  # breakeven
        state.update(125.0)  # tight trail
        assert state.phase == RunnerPhase.TIGHT_TRAIL

        # Price continues up to 130
        action, new_stop, cancel_tp = state.update(130.0)
        assert action == "tighten_trail"
        assert new_stop == pytest.approx(120.0)  # 130 - 10

    def test_short_tight_trail_continues_tightening(self):
        state = PartialRunnerState(entry_price=100.0, direction="short", atr=10.0)
        state.update(85.0)   # breakeven
        state.update(75.0)   # tight trail
        assert state.phase == RunnerPhase.TIGHT_TRAIL

        # Price continues down to 70
        action, new_stop, cancel_tp = state.update(70.0)
        assert action == "tighten_trail"
        assert new_stop == pytest.approx(80.0)  # 70 + 10

    def test_best_price_tracks_long(self):
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=10.0)
        state.update(110.0)
        assert state.best_price == 110.0
        # Price retraces — best_price should NOT decrease
        state.update(105.0)
        assert state.best_price == 110.0

    def test_best_price_tracks_short(self):
        state = PartialRunnerState(entry_price=100.0, direction="short", atr=10.0)
        state.update(90.0)
        assert state.best_price == 90.0
        # Price retraces up — best_price should NOT increase
        state.update(95.0)
        assert state.best_price == 90.0

    def test_breakeven_cancel_tp_only_once(self):
        """cancel_tp should only be True on the first breakeven transition."""
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=10.0)
        _, _, cancel_tp = state.update(115.0)
        assert cancel_tp is True
        assert state.tp_cancelled is True

        # Calling update again at breakeven phase should not cancel again
        # (phase is already BREAKEVEN, no new transition)
        _, _, cancel_tp2 = state.update(116.0)
        assert cancel_tp2 is False

    def test_jump_from_initial_to_tight_trail(self):
        """A large price move can skip from INITIAL through BREAKEVEN to TIGHT_TRAIL."""
        state = PartialRunnerState(entry_price=100.0, direction="long", atr=10.0)
        # Price jumps to 3x ATR in one update
        action, new_stop, cancel_tp = state.update(130.0)
        # Both transitions fire in sequence: INITIAL->BREAKEVEN->TIGHT_TRAIL
        assert state.phase == RunnerPhase.TIGHT_TRAIL
        assert action == "tighten_trail"
        # cancel_tp should be True from breakeven transition
        assert cancel_tp is True
        # stop should be tight trail: 130 - 10 = 120
        assert new_stop == pytest.approx(120.0)


# ============================================================================
# PartialRunnerManager
# ============================================================================


def _runner_config(enabled=True):
    return {
        "runner_mode": {
            "enabled": enabled,
            "breakeven_trigger_atr": 1.5,
            "runner_trigger_atr": 2.5,
            "runner_trail_distance_atr": 1.0,
            "breakeven_offset_points": 0.25,
            "remove_fixed_tp": True,
        }
    }


class TestPartialRunnerManager:
    def test_init_enabled(self):
        mgr = PartialRunnerManager(_runner_config(enabled=True))
        assert mgr.enabled is True
        assert mgr.breakeven_trigger_atr == 1.5
        assert mgr.tight_trail_trigger_atr == 2.5
        assert mgr.tight_trail_distance_atr == 1.0
        assert mgr.breakeven_offset == 0.25

    def test_init_disabled(self):
        mgr = PartialRunnerManager(_runner_config(enabled=False))
        assert mgr.enabled is False

    def test_init_legacy_config_keys(self):
        cfg = {
            "partial_runner": {
                "enabled": True,
                "breakeven_trigger_atr": 1.0,
                "tight_trail_trigger_atr": 2.0,
                "tight_trail_distance_atr": 0.8,
                "breakeven_offset": 0.5,
            }
        }
        mgr = PartialRunnerManager(cfg)
        assert mgr.enabled is True
        assert mgr.breakeven_trigger_atr == 1.0
        assert mgr.tight_trail_trigger_atr == 2.0
        assert mgr.tight_trail_distance_atr == 0.8
        assert mgr.breakeven_offset == 0.5

    def test_register_position_enabled(self):
        mgr = PartialRunnerManager(_runner_config())
        mgr.register_position("pos1", 100.0, "long", 5.0)
        assert "pos1" in mgr._states
        assert mgr._states["pos1"].entry_price == 100.0
        assert mgr._states["pos1"].direction == "long"

    def test_register_position_disabled(self):
        mgr = PartialRunnerManager(_runner_config(enabled=False))
        mgr.register_position("pos1", 100.0, "long", 5.0)
        assert "pos1" not in mgr._states

    def test_update_position_enabled(self):
        mgr = PartialRunnerManager(_runner_config())
        mgr.register_position("pos1", 100.0, "long", 10.0)
        action, new_stop, cancel_tp = mgr.update_position("pos1", 115.0)
        assert action == "move_to_breakeven"
        assert new_stop is not None

    def test_update_position_disabled(self):
        mgr = PartialRunnerManager(_runner_config(enabled=False))
        action, new_stop, cancel_tp = mgr.update_position("pos1", 115.0)
        assert action is None
        assert new_stop is None
        assert cancel_tp is False

    def test_update_position_unknown_id(self):
        mgr = PartialRunnerManager(_runner_config())
        action, new_stop, cancel_tp = mgr.update_position("unknown", 115.0)
        assert action is None
        assert new_stop is None
        assert cancel_tp is False

    def test_remove_position(self):
        mgr = PartialRunnerManager(_runner_config())
        mgr.register_position("pos1", 100.0, "long", 10.0)
        assert "pos1" in mgr._states
        mgr.remove_position("pos1")
        assert "pos1" not in mgr._states

    def test_remove_position_nonexistent(self):
        """Removing a missing position should not raise."""
        mgr = PartialRunnerManager(_runner_config())
        mgr.remove_position("nope")  # no error

    def test_get_phase(self):
        mgr = PartialRunnerManager(_runner_config())
        mgr.register_position("pos1", 100.0, "long", 10.0)
        assert mgr.get_phase("pos1") == "initial"

    def test_get_phase_unknown(self):
        mgr = PartialRunnerManager(_runner_config())
        assert mgr.get_phase("unknown") is None

    def test_get_all_states(self):
        mgr = PartialRunnerManager(_runner_config())
        mgr.register_position("pos1", 100.0, "long", 10.0)
        mgr.register_position("pos2", 200.0, "short", 5.0)
        states = mgr.get_all_states()
        assert len(states) == 2
        assert states["pos1"]["phase"] == "initial"
        assert states["pos1"]["entry_price"] == 100.0
        assert states["pos1"]["direction"] == "long"
        assert states["pos1"]["tp_cancelled"] is False
        assert states["pos2"]["direction"] == "short"

    def test_get_all_states_empty(self):
        mgr = PartialRunnerManager(_runner_config())
        assert mgr.get_all_states() == {}


# ============================================================================
# AdvancedExitManager — max hold exit & runner promotion
# ============================================================================


class TestCheckMaxHoldExit:
    def test_disabled(self):
        cfg = _make_config()
        cfg["max_hold_exit"] = {"enabled": False}
        mgr = AdvancedExitManager(cfg)
        should_exit, reason = mgr.check_max_hold_exit({}, _now_et() - timedelta(minutes=999))
        assert should_exit is False

    def test_within_limit(self):
        cfg = _make_config()
        cfg["max_hold_exit"] = {"enabled": True, "max_duration_minutes": 180}
        mgr = AdvancedExitManager(cfg)
        should_exit, _ = mgr.check_max_hold_exit({}, _now_et() - timedelta(minutes=60))
        assert should_exit is False

    def test_exceeds_limit(self):
        cfg = _make_config()
        cfg["max_hold_exit"] = {"enabled": True, "max_duration_minutes": 180}
        mgr = AdvancedExitManager(cfg)
        should_exit, reason = mgr.check_max_hold_exit({}, _now_et() - timedelta(minutes=200))
        assert should_exit is True
        assert "max hold" in reason.lower()


class TestCheckRunnerPromotion:
    def test_delegates_to_runner(self):
        cfg = _make_config()
        cfg.update(_runner_config())
        mgr = AdvancedExitManager(cfg)
        mgr.runner.register_position("pos1", 100.0, "long", 10.0)
        action, new_stop, cancel_tp = mgr.check_runner_promotion("pos1", 115.0)
        assert action == "move_to_breakeven"

    def test_untracked_position(self):
        cfg = _make_config()
        cfg.update(_runner_config())
        mgr = AdvancedExitManager(cfg)
        action, new_stop, cancel_tp = mgr.check_runner_promotion("unknown", 115.0)
        assert action is None
