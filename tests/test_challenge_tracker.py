"""
Tests for ChallengeTracker - 50k Challenge tracking.

Tests cover:
- Challenge configuration
- Trade recording and PnL tracking
- Pass/fail threshold detection
- Auto-reset behavior
- State persistence
- History tracking
- Metrics and display formatting
"""

from __future__ import annotations

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from pearlalgo.market_agent.challenge_tracker import (
    ChallengeTracker,
    ChallengeConfig,
    ChallengeAttempt,
)


class TestChallengeConfig:
    """Tests for ChallengeConfig dataclass."""

    def test_challenge_config_defaults_to_50k_balance_settings(self):
        """Should have standard 50k challenge defaults."""
        config = ChallengeConfig()
        
        assert config.enabled is True
        assert config.start_balance == 50_000.0
        assert config.max_drawdown == 2_000.0
        assert config.profit_target == 3_000.0
        assert config.auto_reset_on_pass is True
        assert config.auto_reset_on_fail is True

    def test_custom_values(self):
        """Should accept custom values."""
        config = ChallengeConfig(
            enabled=False,
            start_balance=100_000.0,
            max_drawdown=5_000.0,
            profit_target=10_000.0,
        )
        
        assert config.enabled is False
        assert config.start_balance == 100_000.0
        assert config.max_drawdown == 5_000.0
        assert config.profit_target == 10_000.0


class TestChallengeAttempt:
    """Tests for ChallengeAttempt dataclass."""

    def test_challenge_attempt_initializes_as_active_with_zero_pnl(self):
        """Should have sensible defaults."""
        attempt = ChallengeAttempt(
            attempt_id=1,
            started_at="2024-01-01T00:00:00Z",
        )
        
        assert attempt.attempt_id == 1
        assert attempt.outcome == "active"
        assert attempt.pnl == 0.0
        assert attempt.trades == 0
        assert attempt.wins == 0
        assert attempt.losses == 0
        assert attempt.ended_at is None

    def test_to_dict(self):
        """Should convert to dictionary."""
        attempt = ChallengeAttempt(
            attempt_id=1,
            started_at="2024-01-01T00:00:00Z",
            pnl=500.0,
            trades=10,
            wins=6,
            losses=4,
        )
        
        data = attempt.to_dict()
        
        assert data["attempt_id"] == 1
        assert data["pnl"] == 500.0
        assert data["trades"] == 10
        assert data["win_rate"] == 60.0

    def test_from_dict(self):
        """Should create from dictionary."""
        data = {
            "attempt_id": 2,
            "started_at": "2024-01-01T00:00:00Z",
            "pnl": 1000.0,
            "trades": 20,
            "wins": 12,
            "losses": 8,
            "outcome": "active",
        }
        
        attempt = ChallengeAttempt.from_dict(data)
        
        assert attempt.attempt_id == 2
        assert attempt.pnl == 1000.0
        assert attempt.trades == 20
        assert attempt.wins == 12

    def test_win_rate_calculation(self):
        """Should calculate win rate correctly."""
        attempt = ChallengeAttempt(
            attempt_id=1,
            started_at="2024-01-01T00:00:00Z",
            trades=10,
            wins=7,
            losses=3,
        )
        
        data = attempt.to_dict()
        assert data["win_rate"] == 70.0

    def test_win_rate_with_no_trades(self):
        """Should handle zero trades gracefully."""
        attempt = ChallengeAttempt(
            attempt_id=1,
            started_at="2024-01-01T00:00:00Z",
        )
        
        data = attempt.to_dict()
        assert data["win_rate"] == 0.0


class TestChallengeTracker:
    """Tests for ChallengeTracker class."""

    @pytest.fixture
    def temp_state_dir(self):
        """Create temporary state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_initialization_creates_first_attempt(self, temp_state_dir):
        """Should create first attempt on initialization."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        assert tracker.current_attempt is not None
        assert tracker.current_attempt.attempt_id == 1
        assert tracker.current_attempt.outcome == "active"
        assert tracker.current_attempt.pnl == 0.0

    def test_initialization_with_custom_config(self, temp_state_dir):
        """Should use custom configuration."""
        config = ChallengeConfig(
            start_balance=100_000.0,
            max_drawdown=5_000.0,
            profit_target=10_000.0,
        )
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        assert tracker.config.start_balance == 100_000.0
        assert tracker.config.max_drawdown == 5_000.0
        assert tracker.config.profit_target == 10_000.0

    def test_record_trade_updates_pnl(self, temp_state_dir):
        """Should update PnL when recording trades."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        result = tracker.record_trade(pnl=100.0, is_win=True)
        
        assert tracker.current_attempt.pnl == 100.0
        assert tracker.current_attempt.trades == 1
        assert tracker.current_attempt.wins == 1
        assert result["triggered"] is False

    def test_record_trade_tracks_wins_and_losses(self, temp_state_dir):
        """Should track wins and losses separately."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        tracker.record_trade(pnl=100.0, is_win=True)
        tracker.record_trade(pnl=50.0, is_win=True)
        tracker.record_trade(pnl=-75.0, is_win=False)
        
        assert tracker.current_attempt.trades == 3
        assert tracker.current_attempt.wins == 2
        assert tracker.current_attempt.losses == 1
        assert tracker.current_attempt.pnl == 75.0

    def test_record_trade_tracks_profit_peak(self, temp_state_dir):
        """Should track highest PnL achieved."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        tracker.record_trade(pnl=500.0, is_win=True)
        tracker.record_trade(pnl=500.0, is_win=True)  # Total: 1000
        tracker.record_trade(pnl=-200.0, is_win=False)  # Total: 800
        
        assert tracker.current_attempt.profit_peak == 1000.0
        assert tracker.current_attempt.pnl == 800.0

    def test_record_trade_tracks_max_drawdown(self, temp_state_dir):
        """Should track deepest drawdown."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        tracker.record_trade(pnl=-100.0, is_win=False)
        tracker.record_trade(pnl=-200.0, is_win=False)  # Total: -300
        tracker.record_trade(pnl=100.0, is_win=True)  # Total: -200
        
        assert tracker.current_attempt.max_drawdown_hit == -300.0

    def test_triggers_fail_on_max_drawdown(self, temp_state_dir):
        """Should trigger FAIL when max drawdown is reached."""
        config = ChallengeConfig(max_drawdown=1000.0)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        # Record losses to exceed max drawdown
        result = tracker.record_trade(pnl=-500.0, is_win=False)
        assert result["triggered"] is False
        
        result = tracker.record_trade(pnl=-600.0, is_win=False)  # Total: -1100
        
        assert result["triggered"] is True
        assert result["outcome"] == "fail"

    def test_triggers_pass_on_profit_target(self, temp_state_dir):
        """Should trigger PASS when profit target is reached."""
        config = ChallengeConfig(profit_target=1000.0)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        # Record wins to exceed profit target
        result = tracker.record_trade(pnl=500.0, is_win=True)
        assert result["triggered"] is False
        
        result = tracker.record_trade(pnl=600.0, is_win=True)  # Total: 1100
        
        assert result["triggered"] is True
        assert result["outcome"] == "pass"

    def test_auto_reset_on_fail(self, temp_state_dir):
        """Should auto-reset after FAIL if configured."""
        config = ChallengeConfig(max_drawdown=1000.0, auto_reset_on_fail=True)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        original_attempt_id = tracker.current_attempt.attempt_id
        
        # Trigger fail
        tracker.record_trade(pnl=-1100.0, is_win=False)
        
        # Should have new attempt
        assert tracker.current_attempt.attempt_id == original_attempt_id + 1
        assert tracker.current_attempt.outcome == "active"
        assert tracker.current_attempt.pnl == 0.0

    def test_auto_reset_on_pass(self, temp_state_dir):
        """Should auto-reset after PASS if configured."""
        config = ChallengeConfig(profit_target=1000.0, auto_reset_on_pass=True)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        original_attempt_id = tracker.current_attempt.attempt_id
        
        # Trigger pass
        tracker.record_trade(pnl=1100.0, is_win=True)
        
        # Should have new attempt
        assert tracker.current_attempt.attempt_id == original_attempt_id + 1
        assert tracker.current_attempt.outcome == "active"

    def test_no_auto_reset_when_disabled(self, temp_state_dir):
        """Should not auto-reset when disabled."""
        config = ChallengeConfig(
            profit_target=1000.0,
            auto_reset_on_pass=False,
        )
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        original_attempt_id = tracker.current_attempt.attempt_id
        
        # Trigger pass
        tracker.record_trade(pnl=1100.0, is_win=True)
        
        # Same attempt, but ended
        assert tracker.current_attempt.attempt_id == original_attempt_id
        assert tracker.current_attempt.outcome == "pass"

    def test_manual_reset(self, temp_state_dir):
        """Should allow manual reset."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        # Record some trades
        tracker.record_trade(pnl=500.0, is_win=True)
        
        # Manual reset
        new_attempt = tracker.manual_reset(reason="test")
        
        assert new_attempt.attempt_id == 2
        assert new_attempt.pnl == 0.0
        assert new_attempt.outcome == "active"

    def test_disabled_tracker_returns_no_trigger(self, temp_state_dir):
        """Should not trigger when disabled."""
        config = ChallengeConfig(enabled=False, max_drawdown=100.0)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        # This would trigger fail if enabled
        result = tracker.record_trade(pnl=-200.0, is_win=False)
        
        assert result["triggered"] is False
        assert result["outcome"] is None


class TestChallengeTrackerPersistence:
    """Tests for state persistence."""

    @pytest.fixture
    def temp_state_dir(self):
        """Create temporary state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_saves_state_after_trade(self, temp_state_dir):
        """Should save state after each trade."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        tracker.record_trade(pnl=100.0, is_win=True)
        
        state_file = temp_state_dir / "challenge_state.json"
        assert state_file.exists()
        
        with open(state_file) as f:
            data = json.load(f)
        
        assert data["current_attempt"]["pnl"] == 100.0

    def test_loads_state_on_init(self, temp_state_dir):
        """Should load existing state on initialization."""
        # Create first tracker and record trades
        tracker1 = ChallengeTracker(state_dir=temp_state_dir)
        tracker1.record_trade(pnl=500.0, is_win=True)
        tracker1.record_trade(pnl=200.0, is_win=True)
        
        # Create second tracker - should load state
        tracker2 = ChallengeTracker(state_dir=temp_state_dir)
        
        assert tracker2.current_attempt.pnl == 700.0
        assert tracker2.current_attempt.trades == 2
        assert tracker2.current_attempt.wins == 2

    def test_saves_history_on_attempt_end(self, temp_state_dir):
        """Should save completed attempts to history."""
        config = ChallengeConfig(profit_target=1000.0)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        # Trigger pass
        tracker.record_trade(pnl=1100.0, is_win=True)
        
        history_file = temp_state_dir / "challenge_history.json"
        assert history_file.exists()
        
        with open(history_file) as f:
            history = json.load(f)
        
        assert len(history) == 1
        assert history[0]["outcome"] == "pass"
        assert history[0]["pnl"] == 1100.0

    def test_get_history(self, temp_state_dir):
        """Should return attempt history."""
        config = ChallengeConfig(profit_target=500.0, max_drawdown=500.0)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        # Create a few attempts
        tracker.record_trade(pnl=600.0, is_win=True)  # Pass
        tracker.record_trade(pnl=-600.0, is_win=False)  # Fail
        
        history = tracker.get_history()
        
        assert len(history) == 2
        # Most recent first
        assert history[0]["outcome"] == "fail"
        assert history[1]["outcome"] == "pass"


class TestChallengeTrackerMetrics:
    """Tests for metrics and display functions."""

    @pytest.fixture
    def temp_state_dir(self):
        """Create temporary state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_get_attempt_performance(self, temp_state_dir):
        """Should return attempt performance metrics."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        tracker.record_trade(pnl=500.0, is_win=True)
        tracker.record_trade(pnl=-100.0, is_win=False)
        tracker.record_trade(pnl=200.0, is_win=True)
        
        perf = tracker.get_attempt_performance()
        
        assert perf["wins"] == 2
        assert perf["losses"] == 1
        assert perf["total_pnl"] == 600.0
        assert perf["exited_signals"] == 3
        assert perf["attempt_id"] == 1
        assert perf["attempt_outcome"] == "active"

    def test_get_attempt_performance_with_unrealized(self, temp_state_dir):
        """Should include unrealized PnL in total."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        tracker.record_trade(pnl=500.0, is_win=True)
        
        perf = tracker.get_attempt_performance(unrealized_pnl=250.0)
        
        assert perf["total_pnl"] == 750.0
        assert perf["realized_pnl"] == 500.0
        assert perf["unrealized_pnl"] == 250.0

    def test_progress_percentage(self, temp_state_dir):
        """Should calculate progress towards target."""
        config = ChallengeConfig(profit_target=1000.0)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        tracker.record_trade(pnl=500.0, is_win=True)  # 50% progress
        
        perf = tracker.get_attempt_performance()
        
        assert perf["progress_pct"] == 50.0

    def test_drawdown_risk_percentage(self, temp_state_dir):
        """Should calculate drawdown risk percentage."""
        config = ChallengeConfig(max_drawdown=1000.0)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        tracker.record_trade(pnl=-500.0, is_win=False)  # 50% of max drawdown
        
        perf = tracker.get_attempt_performance()
        
        assert perf["drawdown_risk_pct"] == 50.0

    def test_get_outcome_counts(self, temp_state_dir):
        """Should count pass/fail outcomes."""
        config = ChallengeConfig(profit_target=500.0, max_drawdown=500.0)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        # Pass
        tracker.record_trade(pnl=600.0, is_win=True)
        # Fail
        tracker.record_trade(pnl=-600.0, is_win=False)
        # Pass again
        tracker.record_trade(pnl=600.0, is_win=True)
        
        counts = tracker.get_outcome_counts()
        
        assert counts["passed"] == 2
        assert counts["failed"] == 1

    def test_get_status_summary(self, temp_state_dir):
        """Should return formatted status string."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        tracker.record_trade(pnl=500.0, is_win=True)
        tracker.record_trade(pnl=200.0, is_win=True)
        tracker.record_trade(pnl=-100.0, is_win=False)
        
        summary = tracker.get_status_summary()
        
        assert "50k Challenge" in summary
        assert "$600.00" in summary or "+$600.00" in summary
        assert "Trades: 3" in summary
        assert "WR: 67%" in summary

    def test_get_display_attempt_id(self, temp_state_dir):
        """Should return display-friendly attempt number."""
        config = ChallengeConfig(profit_target=500.0)
        tracker = ChallengeTracker(config=config, state_dir=temp_state_dir)
        
        # First active attempt
        assert tracker.get_display_attempt_id() == 1
        
        # Pass first attempt
        tracker.record_trade(pnl=600.0, is_win=True)
        
        # Second active attempt
        assert tracker.get_display_attempt_id() == 2


class TestChallengeTrackerRefresh:
    """Tests for state refresh functionality."""

    @pytest.fixture
    def temp_state_dir(self):
        """Create temporary state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_refresh_loads_updated_state(self, temp_state_dir):
        """Should refresh state from disk when file changes."""
        # Create two tracker instances
        tracker1 = ChallengeTracker(state_dir=temp_state_dir)
        tracker2 = ChallengeTracker(state_dir=temp_state_dir)
        
        # Modify state via tracker1
        tracker1.record_trade(pnl=500.0, is_win=True)
        
        # tracker2 should not have update yet
        assert tracker2.current_attempt.pnl == 0.0
        
        # Refresh tracker2
        tracker2.refresh()
        
        # Now should have updated state
        assert tracker2.current_attempt.pnl == 500.0

    def test_refresh_handles_missing_file(self, temp_state_dir):
        """Should handle missing state file gracefully."""
        tracker = ChallengeTracker(state_dir=temp_state_dir)
        
        # Delete state file
        state_file = temp_state_dir / "challenge_state.json"
        if state_file.exists():
            state_file.unlink()
        
        # Refresh should not crash
        tracker.refresh()
        
        # Should still have current attempt
        assert tracker.current_attempt is not None
