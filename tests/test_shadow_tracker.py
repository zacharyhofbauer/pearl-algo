"""
Tests for PearlShadowTracker - AI suggestion outcome tracking.

Tests cover:
- Suggestion recording
- Outcome tracking (followed, dismissed, expired)
- Hypothetical impact calculation
- State persistence
- Metrics aggregation
"""

from __future__ import annotations

import json
import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from pearlalgo.ai.shadow_tracker import (
    PearlShadowTracker,
    TrackedSuggestion,
    ShadowMetrics,
    SuggestionType,
    SuggestionOutcome,
    get_shadow_tracker,
)


class TestSuggestionType:
    """Tests for SuggestionType enum."""

    def test_enum_values(self):
        """Should have expected suggestion types."""
        assert SuggestionType.RISK_ALERT.value == "risk_alert"
        assert SuggestionType.PATTERN_INSIGHT.value == "pattern_insight"
        assert SuggestionType.DIRECTION_BIAS.value == "direction_bias"
        assert SuggestionType.SIZE_REDUCTION.value == "size_reduction"
        assert SuggestionType.PAUSE_TRADING.value == "pause_trading"
        assert SuggestionType.OPPORTUNITY.value == "opportunity"
        assert SuggestionType.SESSION_ADVICE.value == "session_advice"


class TestSuggestionOutcome:
    """Tests for SuggestionOutcome enum."""

    def test_enum_values(self):
        """Should have expected outcome values."""
        assert SuggestionOutcome.PENDING.value == "pending"
        assert SuggestionOutcome.FOLLOWED.value == "followed"
        assert SuggestionOutcome.DISMISSED.value == "dismissed"
        assert SuggestionOutcome.EXPIRED.value == "expired"


class TestTrackedSuggestion:
    """Tests for TrackedSuggestion dataclass."""

    def test_tracked_suggestion_initializes_with_pending_outcome(self):
        """Should have sensible defaults."""
        suggestion = TrackedSuggestion(
            id="test_1",
            timestamp="2024-01-01T00:00:00Z",
            suggestion_type="risk_alert",
            message="Test message",
            action="Pause trading",
        )
        
        assert suggestion.outcome == SuggestionOutcome.PENDING.value
        assert suggestion.pnl_at_suggestion == 0.0
        assert suggestion.wins_at_suggestion == 0
        assert suggestion.losses_at_suggestion == 0
        assert suggestion.resolved_at is None
        assert suggestion.would_have_saved is None
        assert suggestion.would_have_made is None

    def test_with_context_values(self):
        """Should accept context values."""
        suggestion = TrackedSuggestion(
            id="test_2",
            timestamp="2024-01-01T00:00:00Z",
            suggestion_type="pattern_insight",
            message="Pattern detected",
            action="Consider long bias",
            pnl_at_suggestion=150.0,
            wins_at_suggestion=5,
            losses_at_suggestion=2,
            active_positions=1,
        )
        
        assert suggestion.pnl_at_suggestion == 150.0
        assert suggestion.wins_at_suggestion == 5
        assert suggestion.losses_at_suggestion == 2
        assert suggestion.active_positions == 1


class TestShadowMetrics:
    """Tests for ShadowMetrics dataclass."""

    def test_shadow_metrics_initializes_with_zero_counters(self):
        """Should have zero defaults."""
        metrics = ShadowMetrics()
        
        assert metrics.total_suggestions == 0
        assert metrics.suggestions_followed == 0
        assert metrics.suggestions_dismissed == 0
        assert metrics.suggestions_expired == 0
        assert metrics.total_would_have_saved == 0.0
        assert metrics.total_would_have_made == 0.0
        assert metrics.net_shadow_impact == 0.0
        assert metrics.accuracy_rate == 0.0
        assert metrics.by_type == {}
        assert metrics.recent_suggestions == []
        assert metrics.active_suggestion is None


class TestPearlShadowTracker:
    """Tests for PearlShadowTracker class."""

    def test_initialization_without_state_dir(self):
        """Should initialize without state directory."""
        tracker = PearlShadowTracker(state_dir=None)
        
        assert tracker.state_dir is None
        assert tracker._suggestions == []
        assert tracker._active_suggestion is None
        assert tracker._metrics.total_suggestions == 0

    def test_initialization_with_state_dir(self):
        """Should initialize with state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = PearlShadowTracker(state_dir=Path(tmpdir))
            
            assert tracker.state_dir == Path(tmpdir)

    def test_record_suggestion(self):
        """Should record a new suggestion."""
        tracker = PearlShadowTracker()
        
        context = {
            "daily_pnl": 100.0,
            "wins_today": 3,
            "losses_today": 1,
            "active_positions": 0,
        }
        
        suggestion_id = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="Consider reducing risk",
            action="Pause trading",
            context=context,
        )
        
        assert suggestion_id.startswith("pearl_")
        assert tracker._metrics.total_suggestions == 1
        assert tracker._active_suggestion is not None
        assert tracker._active_suggestion.suggestion_type == "risk_alert"
        assert tracker._active_suggestion.pnl_at_suggestion == 100.0

    def test_record_suggestion_expires_previous(self):
        """Should expire previous active suggestion when recording new one."""
        tracker = PearlShadowTracker()
        context = {"daily_pnl": 100.0}
        
        # Record first suggestion
        first_id = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="First suggestion",
            action="Action 1",
            context=context,
        )
        
        # Record second suggestion - should expire first
        second_id = tracker.record_suggestion(
            suggestion_type=SuggestionType.PATTERN_INSIGHT.value,
            message="Second suggestion",
            action="Action 2",
            context=context,
        )
        
        # First should be expired
        first_suggestion = next(s for s in tracker._suggestions if s.id == first_id)
        assert first_suggestion.outcome == SuggestionOutcome.EXPIRED.value
        
        # Second should be active
        assert tracker._active_suggestion.id == second_id

    def test_mark_followed(self):
        """Should mark suggestion as followed."""
        tracker = PearlShadowTracker()
        context = {"daily_pnl": 100.0}
        
        suggestion_id = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="Test",
            action="Action",
            context=context,
        )
        
        # Mark as followed
        tracker.mark_followed(suggestion_id, {"daily_pnl": 100.0})
        
        suggestion = next(s for s in tracker._suggestions if s.id == suggestion_id)
        assert suggestion.outcome == SuggestionOutcome.FOLLOWED.value
        assert tracker._metrics.suggestions_followed == 1
        assert tracker._active_suggestion is None

    def test_mark_dismissed(self):
        """Should mark suggestion as dismissed."""
        tracker = PearlShadowTracker()
        context = {"daily_pnl": 100.0}
        
        suggestion_id = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="Test",
            action="Action",
            context=context,
        )
        
        # Mark as dismissed
        tracker.mark_dismissed(suggestion_id, {"daily_pnl": 50.0})  # Lost $50
        
        suggestion = next(s for s in tracker._suggestions if s.id == suggestion_id)
        assert suggestion.outcome == SuggestionOutcome.DISMISSED.value
        assert suggestion.actual_pnl_change == -50.0
        assert tracker._metrics.suggestions_dismissed == 1

    def test_would_have_saved_on_risk_alert_dismissed(self):
        """Should calculate would_have_saved when risk alert was dismissed and loss occurred."""
        tracker = PearlShadowTracker()
        
        # Record risk alert at $100 P&L
        suggestion_id = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="High risk detected",
            action="Pause trading",
            context={"daily_pnl": 100.0, "wins_today": 3, "losses_today": 1},
        )
        
        # Dismiss and then lose $75
        tracker.mark_dismissed(
            suggestion_id,
            {"daily_pnl": 25.0, "wins_today": 3, "losses_today": 3},
        )
        
        suggestion = next(s for s in tracker._suggestions if s.id == suggestion_id)
        assert suggestion.actual_pnl_change == -75.0
        assert suggestion.would_have_saved == 75.0  # Would have saved $75 by pausing

    def test_size_reduction_hypothetical(self):
        """Should calculate 50% savings for size reduction suggestions."""
        tracker = PearlShadowTracker()
        
        suggestion_id = tracker.record_suggestion(
            suggestion_type=SuggestionType.SIZE_REDUCTION.value,
            message="Reduce position size",
            action="Cut size in half",
            context={"daily_pnl": 100.0},
        )
        
        # Lose $100 after dismissing
        tracker.mark_dismissed(
            suggestion_id,
            {"daily_pnl": 0.0},
        )
        
        suggestion = next(s for s in tracker._suggestions if s.id == suggestion_id)
        assert suggestion.actual_pnl_change == -100.0
        assert suggestion.would_have_saved == 50.0  # 50% of loss
        assert suggestion.hypothetical_pnl_change == -50.0

    def test_update_by_type_metrics(self):
        """Should track metrics by suggestion type."""
        tracker = PearlShadowTracker()
        context = {"daily_pnl": 100.0}
        
        # Record first risk alert and mark as followed
        id1 = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="Alert 1",
            action="Action",
            context=context,
        )
        tracker.mark_followed(id1, context)
        
        # Small delay to ensure unique timestamp
        time.sleep(0.002)
        
        # Record second risk alert and mark as dismissed
        id2 = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="Alert 2",
            action="Action",
            context=context,
        )
        
        # Ensure we have different IDs
        assert id1 != id2, f"Suggestion IDs should be different: {id1} vs {id2}"
        
        tracker.mark_dismissed(id2, context)
        
        by_type = tracker._metrics.by_type
        assert "risk_alert" in by_type
        assert by_type["risk_alert"]["count"] == 2
        assert by_type["risk_alert"]["followed"] == 1
        assert by_type["risk_alert"]["dismissed"] == 1

    def test_get_metrics(self):
        """Should return metrics dictionary."""
        tracker = PearlShadowTracker()
        
        # Record and resolve some suggestions
        context = {"daily_pnl": 100.0}
        tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="Test",
            action="Action",
            context=context,
        )
        tracker.mark_followed(tracker._active_suggestion.id, {"daily_pnl": 120.0})
        
        metrics = tracker.get_metrics()
        
        assert "total_suggestions" in metrics
        assert "suggestions_followed" in metrics
        assert "suggestions_dismissed" in metrics
        assert "total_would_have_saved" in metrics
        assert "total_would_have_made" in metrics
        assert "net_shadow_impact" in metrics
        assert "accuracy_rate" in metrics
        assert "by_type" in metrics
        assert "recent_suggestions" in metrics
        assert "active_suggestion" in metrics
        assert metrics["mode"] == "shadow"

    def test_get_active_suggestion(self):
        """Should return active suggestion or None."""
        tracker = PearlShadowTracker()
        
        # No active suggestion initially
        assert tracker.get_active_suggestion() is None
        
        # Record suggestion
        tracker.record_suggestion(
            suggestion_type=SuggestionType.OPPORTUNITY.value,
            message="Good setup",
            action="Consider long",
            context={"daily_pnl": 0.0},
        )
        
        active = tracker.get_active_suggestion()
        assert active is not None
        assert active["type"] == "opportunity"
        assert active["message"] == "Good setup"

    def test_update_context_tracks_state(self):
        """Should update tracking with latest context."""
        tracker = PearlShadowTracker()
        
        tracker.update_context({
            "daily_pnl": 200.0,
            "wins_today": 5,
            "losses_today": 2,
        })
        
        assert tracker._last_pnl == 200.0
        assert tracker._last_wins == 5
        assert tracker._last_losses == 2


class TestShadowTrackerPersistence:
    """Tests for state persistence."""

    def test_save_and_load_state(self):
        """Should persist and restore state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            
            # Create tracker and record suggestions
            tracker1 = PearlShadowTracker(state_dir=state_dir)
            suggestion_id = tracker1.record_suggestion(
                suggestion_type=SuggestionType.RISK_ALERT.value,
                message="Test persistence",
                action="Test action",
                context={"daily_pnl": 100.0, "wins_today": 2, "losses_today": 1},
            )
            tracker1.mark_followed(suggestion_id, {"daily_pnl": 150.0})
            
            # Create new tracker - should load state
            tracker2 = PearlShadowTracker(state_dir=state_dir)
            
            assert tracker2._metrics.total_suggestions == 1
            assert tracker2._metrics.suggestions_followed == 1
            assert len(tracker2._suggestions) == 1

    def test_state_file_location(self):
        """Should use correct state file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            tracker = PearlShadowTracker(state_dir=state_dir)
            
            state_file = tracker._get_state_file()
            assert state_file == state_dir / "pearl_shadow_state.json"

    def test_handles_missing_state_file(self):
        """Should handle missing state file gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            
            # No state file exists
            tracker = PearlShadowTracker(state_dir=state_dir)
            
            # Should have empty state
            assert tracker._metrics.total_suggestions == 0
            assert tracker._suggestions == []


class TestAutoExpiration:
    """Tests for automatic suggestion expiration."""

    def test_auto_expire_old_suggestion(self):
        """Should auto-expire suggestions older than TTL."""
        tracker = PearlShadowTracker()
        
        # Record suggestion
        suggestion_id = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="Test",
            action="Action",
            context={"daily_pnl": 100.0},
        )
        
        # Manually set old timestamp
        tracker._active_suggestion.timestamp = "2020-01-01T00:00:00+00:00"
        
        # Update context should trigger expiration
        tracker.update_context({"daily_pnl": 100.0})
        
        # Suggestion should be expired
        suggestion = next(s for s in tracker._suggestions if s.id == suggestion_id)
        assert suggestion.outcome == SuggestionOutcome.EXPIRED.value
        assert tracker._active_suggestion is None


class TestGetShadowTracker:
    """Tests for singleton function."""

    def test_creates_instance(self):
        """Should create tracker instance."""
        import pearlalgo.ai.shadow_tracker as module
        
        # Reset singleton
        module._tracker = None
        
        tracker = get_shadow_tracker()
        
        assert tracker is not None
        assert isinstance(tracker, PearlShadowTracker)

    def test_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        import pearlalgo.ai.shadow_tracker as module
        
        # Reset singleton
        module._tracker = None
        
        tracker1 = get_shadow_tracker()
        tracker2 = get_shadow_tracker()
        
        assert tracker1 is tracker2

    def test_with_state_dir(self):
        """Should use provided state directory."""
        import pearlalgo.ai.shadow_tracker as module
        
        # Reset singleton
        module._tracker = None
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = get_shadow_tracker(state_dir=Path(tmpdir))
            assert tracker.state_dir == Path(tmpdir)


class TestAccuracyTracking:
    """Tests for accuracy tracking."""

    def test_correct_suggestion_increments_accuracy(self):
        """Should track correct suggestions."""
        tracker = PearlShadowTracker()
        
        # Risk alert that would have saved money
        suggestion_id = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="High risk",
            action="Pause",
            context={"daily_pnl": 100.0},
        )
        
        # Dismiss and lose money
        tracker.mark_dismissed(suggestion_id, {"daily_pnl": 0.0})
        
        assert tracker._metrics.correct_suggestions == 1
        assert tracker._metrics.accuracy_rate > 0

    def test_accuracy_rate_calculation(self):
        """Should calculate accuracy rate correctly."""
        tracker = PearlShadowTracker()
        
        # First: correct (would have saved money)
        id1 = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="Test 1",
            action="Action",
            context={"daily_pnl": 100.0},
        )
        tracker.mark_dismissed(id1, {"daily_pnl": 50.0})  # Lost $50 - suggestion was correct
        
        # Small delay to ensure unique timestamp for second suggestion
        time.sleep(0.002)
        
        # Second: incorrect (user made money ignoring it)
        id2 = tracker.record_suggestion(
            suggestion_type=SuggestionType.PAUSE_TRADING.value,
            message="Test 2",
            action="Action",
            context={"daily_pnl": 50.0},
        )
        
        # Ensure we have different IDs
        assert id1 != id2, f"Suggestion IDs should be different: {id1} vs {id2}"
        
        tracker.mark_dismissed(id2, {"daily_pnl": 200.0})  # Made $150 - suggestion was wrong
        
        # Accuracy should be 50% (1 correct out of 2)
        assert tracker._metrics.correct_suggestions == 1
        assert tracker._metrics.incorrect_suggestions == 1
        assert abs(tracker._metrics.accuracy_rate - 0.5) < 0.01


class TestNetShadowImpact:
    """Tests for net shadow impact calculation."""

    def test_net_impact_from_saved_and_made(self):
        """Should sum would_have_saved and would_have_made."""
        tracker = PearlShadowTracker()
        
        # Risk alert that would have saved $100
        id1 = tracker.record_suggestion(
            suggestion_type=SuggestionType.RISK_ALERT.value,
            message="Test 1",
            action="Action",
            context={"daily_pnl": 100.0},
        )
        tracker.mark_dismissed(id1, {"daily_pnl": 0.0})  # Lost $100
        
        assert tracker._metrics.total_would_have_saved == 100.0
        assert tracker._metrics.net_shadow_impact == 100.0
