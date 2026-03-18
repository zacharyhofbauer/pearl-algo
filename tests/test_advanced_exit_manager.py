"""Tests for pearlalgo.execution.advanced_exit_manager."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from pearlalgo.execution.advanced_exit_manager import AdvancedExitManager


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
        should_exit, reason = mgr.check_quick_exit({}, 17500, datetime.now() - timedelta(minutes=30))
        assert should_exit is False

    def test_too_early(self):
        mgr = AdvancedExitManager(_make_config())
        should_exit, _ = mgr.check_quick_exit({}, 17500, datetime.now() - timedelta(minutes=5))
        assert should_exit is False

    def test_stalled_trade_exits(self):
        mgr = AdvancedExitManager(_make_config())
        pos = {"mfe_dollars": 10, "mae_dollars": 70, "unrealized_pnl": -5}
        should_exit, reason = mgr.check_quick_exit(pos, 17500, datetime.now() - timedelta(minutes=25))
        assert should_exit is True
        assert "stalled" in reason.lower()

    def test_good_mfe_no_exit(self):
        mgr = AdvancedExitManager(_make_config())
        pos = {"mfe_dollars": 50, "mae_dollars": 70, "unrealized_pnl": 30}
        should_exit, _ = mgr.check_quick_exit(pos, 17500, datetime.now() - timedelta(minutes=25))
        assert should_exit is False


class TestCheckTimeBasedExit:
    def test_disabled(self):
        mgr = AdvancedExitManager(_make_config(time_based=False))
        should_exit, _ = mgr.check_time_based_exit({}, 17500, datetime.now() - timedelta(minutes=30))
        assert should_exit is False

    def test_too_early(self):
        mgr = AdvancedExitManager(_make_config())
        should_exit, _ = mgr.check_time_based_exit({}, 17500, datetime.now() - timedelta(minutes=5))
        assert should_exit is False

    def test_declining_profit_exits(self):
        mgr = AdvancedExitManager(_make_config())
        pos = {"unrealized_pnl": 40, "mfe_dollars": 80}
        should_exit, reason = mgr.check_time_based_exit(pos, 17500, datetime.now() - timedelta(minutes=15))
        # current_pnl (40) < target_exit (80 * 0.70 = 56) -> should exit
        assert should_exit is True
        assert "declining" in reason.lower()

    def test_still_profitable_no_exit(self):
        mgr = AdvancedExitManager(_make_config())
        pos = {"unrealized_pnl": 70, "mfe_dollars": 80}
        should_exit, _ = mgr.check_time_based_exit(pos, 17500, datetime.now() - timedelta(minutes=15))
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
        should_exit, reason = mgr.should_exit(pos, 17500, datetime.now() - timedelta(minutes=25))
        assert should_exit is True
        assert "quick" in reason.lower()

    def test_time_based_when_no_quick_exit(self):
        mgr = AdvancedExitManager(_make_config(quick_exit=False))
        pos = {"unrealized_pnl": 40, "mfe_dollars": 80}
        should_exit, reason = mgr.should_exit(pos, 17500, datetime.now() - timedelta(minutes=15))
        assert should_exit is True
        assert "time" in reason.lower()

    def test_no_exit(self):
        mgr = AdvancedExitManager(_make_config(quick_exit=False, time_based=False))
        should_exit, _ = mgr.should_exit({}, 17500, datetime.now())
        assert should_exit is False
