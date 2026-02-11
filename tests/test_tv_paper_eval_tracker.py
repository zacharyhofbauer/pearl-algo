"""
Tests for TvPaperEvaluationTracker — Tradovate Paper 50K Rapid Evaluation challenge tracker.

Covers:
- TvPaperEvalConfig creation with defaults
- Tracker initialization and state file creation
- Recording winning and losing trades (PnL, counters, daily breakdown)
- Drawdown floor calculation (fixed during evaluation)
- Consistency rule (no single day > 50% of total profit)
- Minimum trading days check
- Pass / fail detection
- State persistence (save and reload from disk)
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from pearlalgo.market_agent.mffu_eval_tracker import (
    MFFUEvalConfig as TvPaperEvalConfig,
    MFFUEvalAttempt as TvPaperEvalAttempt,
    MFFUEvaluationTracker as TvPaperEvaluationTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmp_path: Path, **config_overrides) -> TvPaperEvaluationTracker:
    """Create a tracker using tmp_path as the state directory."""
    cfg = TvPaperEvalConfig(**config_overrides)
    return TvPaperEvaluationTracker(config=cfg, state_dir=tmp_path)


# ---------------------------------------------------------------------------
# TvPaperEvalConfig
# ---------------------------------------------------------------------------

class TestTvPaperEvalConfig:
    """Tests for TvPaperEvalConfig dataclass defaults."""

    def test_default_values(self):
        cfg = TvPaperEvalConfig()
        assert cfg.enabled is True
        assert cfg.stage == "evaluation"
        assert cfg.start_balance == 50_000.0
        assert cfg.profit_target == 3_000.0
        assert cfg.max_loss_distance == 2_000.0
        assert cfg.consistency_pct == 0.50
        assert cfg.min_trading_days == 2

    def test_custom_overrides(self):
        cfg = TvPaperEvalConfig(start_balance=100_000.0, profit_target=6_000.0)
        assert cfg.start_balance == 100_000.0
        assert cfg.profit_target == 6_000.0


# ---------------------------------------------------------------------------
# Tracker initialisation
# ---------------------------------------------------------------------------

class TestTrackerInit:
    """Tests for TvPaperEvaluationTracker initialisation."""

    def test_creates_state_file_after_first_trade(self, tmp_path: Path):
        """State file is created after the first trade (save happens in record_trade)."""
        tracker = _make_tracker(tmp_path)
        # Note: init's _save_state may silently fail (current_attempt not yet assigned
        # during _load_or_create_attempt -> _create_new_attempt -> _save_state).
        # The state file is reliably created after the first record_trade call.
        tracker.record_trade(pnl=10.0, is_win=True, trade_date="2026-02-10")
        assert tracker.state_file.exists()

    def test_initial_attempt_is_active(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        assert tracker.current_attempt.outcome == "active"
        assert tracker.current_attempt.pnl == 0.0
        assert tracker.current_attempt.trades == 0

    def test_initial_drawdown_floor(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        expected_floor = 50_000.0 - 2_000.0  # start_balance - max_loss_distance
        assert tracker.current_attempt.current_drawdown_floor == expected_floor


# ---------------------------------------------------------------------------
# Recording trades
# ---------------------------------------------------------------------------

class TestRecordTrade:
    """Tests for record_trade — winning and losing trades."""

    def test_winning_trade_updates_pnl(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=150.0, is_win=True, trade_date="2026-02-10")

        assert tracker.current_attempt.pnl == 150.0
        assert tracker.current_attempt.trades == 1
        assert tracker.current_attempt.wins == 1
        assert tracker.current_attempt.losses == 0

    def test_losing_trade_updates_pnl(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=-200.0, is_win=False, trade_date="2026-02-10")

        assert tracker.current_attempt.pnl == -200.0
        assert tracker.current_attempt.trades == 1
        assert tracker.current_attempt.wins == 0
        assert tracker.current_attempt.losses == 1

    def test_daily_pnl_aggregation(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=100.0, is_win=True, trade_date="2026-02-10")
        tracker.record_trade(pnl=50.0, is_win=True, trade_date="2026-02-10")

        assert tracker.current_attempt.daily_pnl_by_date["2026-02-10"] == 150.0

    def test_unique_trading_days_tracked(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=100.0, is_win=True, trade_date="2026-02-10")
        tracker.record_trade(pnl=50.0, is_win=True, trade_date="2026-02-10")
        tracker.record_trade(pnl=75.0, is_win=True, trade_date="2026-02-11")

        assert len(tracker.current_attempt.trading_days) == 2

    def test_disabled_tracker_returns_no_trigger(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path, enabled=False)
        result = tracker.record_trade(pnl=100.0, is_win=True)
        assert result["triggered"] is False


# ---------------------------------------------------------------------------
# Drawdown floor (evaluation = fixed, not trailing)
# ---------------------------------------------------------------------------

class TestDrawdownFloor:
    """Evaluation drawdown floor stays fixed at start_balance - max_loss."""

    def test_floor_does_not_trail_during_evaluation(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        # Record profit then update EOD HWM
        tracker.record_trade(pnl=500.0, is_win=True, trade_date="2026-02-10")
        tracker.update_eod_hwm()

        # Floor should still be 48000, not trail up
        assert tracker.current_attempt.current_drawdown_floor == 48_000.0

    def test_hwm_still_tracked_during_evaluation(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=500.0, is_win=True, trade_date="2026-02-10")
        tracker.update_eod_hwm()

        assert tracker.current_attempt.eod_high_water_mark == 50_500.0

    def test_balance_below_floor_triggers_fail(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        # Lose more than max_loss_distance (2000)
        result = tracker.record_trade(pnl=-2_100.0, is_win=False, trade_date="2026-02-10")

        assert result["triggered"] is True
        assert result["outcome"] == "fail"


# ---------------------------------------------------------------------------
# Consistency rule (50%)
# ---------------------------------------------------------------------------

class TestConsistencyRule:
    """No single day > 50% of total profit."""

    def test_consistent_across_two_days(self, tmp_path: Path):
        """Two days with equal profit: 50% each. 50% is exactly the threshold (met)."""
        tracker = _make_tracker(tmp_path)
        # Use amounts below profit target so the attempt stays active
        tracker.record_trade(pnl=1_000.0, is_win=True, trade_date="2026-02-10")
        tracker.record_trade(pnl=1_000.0, is_win=True, trade_date="2026-02-11")

        result = tracker.check_consistency()
        assert result["met"] is True
        assert result["best_day_pct"] == 50.0  # exactly 50% is OK (<=)

    def test_inconsistent_single_day_dominance(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=2_500.0, is_win=True, trade_date="2026-02-10")
        tracker.record_trade(pnl=500.0, is_win=True, trade_date="2026-02-11")

        result = tracker.check_consistency()
        assert result["met"] is False
        # best day is 2500 / 3000 = 83.3%
        assert result["best_day_pct"] > 50.0

    def test_consistency_vacuously_true_when_no_profit(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=-100.0, is_win=False, trade_date="2026-02-10")

        result = tracker.check_consistency()
        assert result["met"] is True


# ---------------------------------------------------------------------------
# Minimum trading days
# ---------------------------------------------------------------------------

class TestMinTradingDays:
    """At least 2 distinct trading days required."""

    def test_not_met_with_one_day(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=3_000.0, is_win=True, trade_date="2026-02-10")

        result = tracker.check_min_days()
        assert result["met"] is False
        assert result["days_traded"] == 1

    def test_met_with_two_days(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        # Use amounts below profit target ($3000) to keep attempt active
        tracker.record_trade(pnl=500.0, is_win=True, trade_date="2026-02-10")
        tracker.record_trade(pnl=500.0, is_win=True, trade_date="2026-02-11")

        result = tracker.check_min_days()
        assert result["met"] is True
        assert result["days_traded"] == 2


# ---------------------------------------------------------------------------
# Pass / Fail detection
# ---------------------------------------------------------------------------

class TestPassFail:
    """End-to-end pass and fail scenarios."""

    def test_pass_when_all_conditions_met(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        # Day 1: $1,500 profit
        tracker.record_trade(pnl=1_500.0, is_win=True, trade_date="2026-02-10")
        # Day 2: $1,500 profit  -> total $3,000 (target), 2 days, consistent
        result = tracker.record_trade(pnl=1_500.0, is_win=True, trade_date="2026-02-11")

        assert result["triggered"] is True
        assert result["outcome"] == "pass"

    def test_no_pass_when_consistency_not_met(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        # Day 1: $2,800 profit
        tracker.record_trade(pnl=2_800.0, is_win=True, trade_date="2026-02-10")
        # Day 2: $200 profit  -> total $3,000, but day1 = 93% > 50%
        result = tracker.record_trade(pnl=200.0, is_win=True, trade_date="2026-02-11")

        assert result["triggered"] is False  # can't pass yet

    def test_no_pass_when_min_days_not_met(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        # All profit in a single day -> min_days not met
        result = tracker.record_trade(pnl=3_000.0, is_win=True, trade_date="2026-02-10")

        assert result["triggered"] is False

    def test_fail_on_drawdown_breach(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        result = tracker.record_trade(pnl=-2_100.0, is_win=False, trade_date="2026-02-10")

        assert result["triggered"] is True
        assert result["outcome"] == "fail"


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    """Save and reload state from disk."""

    def test_state_survives_reload(self, tmp_path: Path):
        # Create tracker and record trades
        tracker1 = _make_tracker(tmp_path)
        tracker1.record_trade(pnl=500.0, is_win=True, trade_date="2026-02-10")
        tracker1.record_trade(pnl=-100.0, is_win=False, trade_date="2026-02-11")

        # Create a second tracker pointing at the same directory
        tracker2 = _make_tracker(tmp_path)

        assert tracker2.current_attempt.pnl == 400.0
        assert tracker2.current_attempt.trades == 2
        assert tracker2.current_attempt.wins == 1
        assert tracker2.current_attempt.losses == 1

    def test_state_file_is_valid_json(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=250.0, is_win=True, trade_date="2026-02-10")

        with open(tracker.state_file) as f:
            data = json.load(f)

        assert "current_attempt" in data
        assert "tv_paper" in data
        assert data["current_attempt"]["pnl"] == 250.0

    def test_history_file_created_on_pass(self, tmp_path: Path):
        tracker = _make_tracker(tmp_path)
        tracker.record_trade(pnl=1_500.0, is_win=True, trade_date="2026-02-10")
        tracker.record_trade(pnl=1_500.0, is_win=True, trade_date="2026-02-11")

        assert tracker.history_file.exists()
        with open(tracker.history_file) as f:
            history = json.load(f)
        assert len(history) == 1
        assert history[0]["outcome"] == "pass"
