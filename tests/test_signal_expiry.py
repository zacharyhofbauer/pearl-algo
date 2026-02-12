"""
Tests for signal expiry behavior.

Validates:
- track_signal_expired() correctly sets status to "expired"
- Expiry reason is recorded in the signal record
- Expired signals are retrievable and have expected fields
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pearlalgo.market_agent.performance_tracker import PerformanceTracker
from pearlalgo.market_agent.state_manager import MarketAgentStateManager


class TestSignalExpiry:
    """Tests for track_signal_expired behavior."""

    def test_signal_expires_with_reason(self, tmp_path: Path) -> None:
        """Expired signal should have status='expired' and reason recorded."""
        manager = MarketAgentStateManager(state_dir=tmp_path)
        tracker = PerformanceTracker(state_dir=tmp_path, state_manager=manager)

        # Generate a signal
        signal = {
            "type": "momentum_long",
            "direction": "long",
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17550.0,
            "confidence": 0.75,
            "symbol": "MNQ",
        }
        signal_id = tracker.track_signal_generated(signal)

        # Track entry
        tracker.track_entry(signal_id, entry_price=17500.0)

        # Expire the signal
        tracker.track_signal_expired(signal_id, reason="hold_time_exceeded")

        # Verify status (append-only may have multiple rows per signal_id; latest wins)
        signals = manager.get_recent_signals(limit=10)
        by_id = {r.get("signal_id"): r for r in signals if r.get("signal_id")}
        assert len(by_id) >= 1, "Should have at least one signal"
        record = by_id.get(signal_id) or signals[-1]
        assert record["status"] == "expired", f"Expected status='expired', got '{record.get('status')}'"
        assert record.get("reason") == "hold_time_exceeded", (
            f"Expected reason='hold_time_exceeded', got '{record.get('reason')}'"
        )

    def test_signal_expires_without_entry(self, tmp_path: Path) -> None:
        """Signal can expire without ever being entered (e.g., price never reached)."""
        manager = MarketAgentStateManager(state_dir=tmp_path)
        tracker = PerformanceTracker(state_dir=tmp_path, state_manager=manager)

        signal = {
            "type": "breakout",
            "direction": "long",
            "entry_price": 17600.0,
            "stop_loss": 17580.0,
            "take_profit": 17650.0,
            "confidence": 0.60,
            "symbol": "MNQ",
        }
        signal_id = tracker.track_signal_generated(signal)

        # Expire without entry (price never reached)
        tracker.track_signal_expired(signal_id, reason="entry_price_not_reached")

        signals = manager.get_recent_signals(limit=10)
        by_id = {r.get("signal_id"): r for r in signals if r.get("signal_id")}
        assert len(by_id) >= 1
        record = by_id.get(signal_id) or signals[-1]
        assert record["status"] == "expired"
        assert record.get("reason") == "entry_price_not_reached"
        # Should not have entry_time since we never entered
        assert record.get("entry_time") is None

    def test_expired_signal_preserves_original_data(self, tmp_path: Path) -> None:
        """Expiring a signal should preserve original signal data."""
        manager = MarketAgentStateManager(state_dir=tmp_path)
        tracker = PerformanceTracker(state_dir=tmp_path, state_manager=manager)

        signal = {
            "type": "mean_reversion",
            "direction": "short",
            "entry_price": 17500.0,
            "stop_loss": 17520.0,
            "take_profit": 17450.0,
            "confidence": 0.65,
            "symbol": "MNQ",
        }
        signal_id = tracker.track_signal_generated(signal)
        tracker.track_signal_expired(signal_id, reason="session_ended")

        signals = manager.get_recent_signals(limit=10)
        record = signals[0]
        
        # Verify original signal data is preserved
        inner_signal = record.get("signal", {})
        assert inner_signal.get("type") == "mean_reversion"
        assert inner_signal.get("direction") == "short"
        assert inner_signal.get("entry_price") == 17500.0
        assert inner_signal.get("stop_loss") == 17520.0
        assert inner_signal.get("take_profit") == 17450.0

    def test_multiple_signals_with_different_expiry_reasons(self, tmp_path: Path) -> None:
        """Multiple signals can have different expiry reasons."""
        manager = MarketAgentStateManager(state_dir=tmp_path)
        tracker = PerformanceTracker(state_dir=tmp_path, state_manager=manager)

        # Create and expire multiple signals
        reasons = ["hold_time_exceeded", "session_ended", "manual_cancel"]
        signal_ids = []
        
        for i, reason in enumerate(reasons):
            signal = {
                "type": f"test_type_{i}",
                "direction": "long",
                "entry_price": 17500.0 + i * 10,
                "stop_loss": 17480.0,
                "take_profit": 17550.0,
                "confidence": 0.70,
                "symbol": "MNQ",
            }
            signal_id = tracker.track_signal_generated(signal)
            signal_ids.append(signal_id)
            tracker.track_signal_expired(signal_id, reason=reason)

        signals = manager.get_recent_signals(limit=10)
        by_id = {r.get("signal_id"): r for r in signals if r.get("signal_id")}
        assert len(by_id) == 3, f"Expected 3 distinct signals, got {len(by_id)}"

        # Verify each has correct reason
        for record in by_id.values():
            assert record["status"] == "expired"
            assert record.get("reason") in reasons

    def test_default_expiry_reason(self, tmp_path: Path) -> None:
        """When no reason is provided, default reason should be 'expired'."""
        manager = MarketAgentStateManager(state_dir=tmp_path)
        tracker = PerformanceTracker(state_dir=tmp_path, state_manager=manager)

        signal = {
            "type": "momentum_long",
            "direction": "long",
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17550.0,
            "confidence": 0.72,
            "symbol": "MNQ",
        }
        signal_id = tracker.track_signal_generated(signal)
        
        # Expire with default reason
        tracker.track_signal_expired(signal_id)

        signals = manager.get_recent_signals(limit=10)
        by_id = {r.get("signal_id"): r for r in signals if r.get("signal_id")}
        record = by_id.get(signal_id) or signals[-1]
        assert record["status"] == "expired"
        assert record.get("reason") == "expired"  # Default reason

    def test_expired_signal_not_counted_as_exited(self, tmp_path: Path) -> None:
        """Expired signals should not appear in exited_signals metrics."""
        manager = MarketAgentStateManager(state_dir=tmp_path)
        tracker = PerformanceTracker(state_dir=tmp_path, state_manager=manager)

        # Create one expired signal
        signal1 = {
            "type": "test_expired",
            "direction": "long",
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17550.0,
            "confidence": 0.70,
            "symbol": "MNQ",
        }
        signal_id1 = tracker.track_signal_generated(signal1)
        tracker.track_signal_expired(signal_id1, reason="timeout")

        # Create one exited signal (for comparison)
        signal2 = {
            "type": "test_exited",
            "direction": "long",
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17550.0,
            "confidence": 0.70,
            "symbol": "MNQ",
        }
        signal_id2 = tracker.track_signal_generated(signal2)
        tracker.track_entry(signal_id2, entry_price=17500.0)
        tracker.track_exit(signal_id2, exit_price=17550.0, exit_reason="take_profit")

        # Get performance metrics
        metrics = tracker.get_performance_metrics(days=7)
        
        # Should have 2 logical signals; only 1 exited (the other expired)
        assert metrics["total_signals"] >= 2, f"Expected at least 2 signals, got {metrics['total_signals']}"
        assert metrics["exited_signals"] == 1, f"Expected 1 exited (expired not counted), got {metrics['exited_signals']}"








