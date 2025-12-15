"""
Tests for NQ Agent Performance Tracker.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pearlalgo.nq_agent.performance_tracker import PerformanceTracker


@pytest.fixture
def state_dir(tmp_path):
    """Create a temporary state directory."""
    state_dir = tmp_path / "nq_agent_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


@pytest.fixture
def tracker(state_dir):
    """Create a performance tracker instance."""
    return PerformanceTracker(state_dir=state_dir)


def test_tracker_initialization(tracker, state_dir):
    """Test performance tracker initializes correctly."""
    assert tracker.state_dir == state_dir
    assert tracker.signals_file.parent == state_dir
    assert tracker.performance_file.parent == state_dir


def test_track_signal_generated(tracker):
    """Test tracking signal generation."""
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
        "stop_loss": 14900.0,
        "take_profit": 15200.0,
    }
    
    signal_id = tracker.track_signal_generated(signal)
    
    assert signal_id is not None
    assert len(signal_id) > 0
    assert "breakout" in signal_id


def test_track_entry(tracker):
    """Test tracking signal entry."""
    # First generate a signal
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
    }
    signal_id = tracker.track_signal_generated(signal)
    
    # Track entry
    tracker.track_entry(signal_id, 15001.0)
    
    # Entry should be tracked (implementation may vary)
    # This tests the method doesn't raise


def test_track_exit(tracker):
    """Test tracking signal exit and P&L calculation."""
    # Generate and enter signal
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
    }
    signal_id = tracker.track_signal_generated(signal)
    tracker.track_entry(signal_id, 15000.0)
    
    # Track exit
    performance = tracker.track_exit(
        signal_id=signal_id,
        exit_price=15100.0,
        exit_reason="take_profit",
    )
    
    assert performance is not None
    assert performance["entry_price"] == 15000.0
    assert performance["exit_price"] == 15100.0
    assert performance["pnl"] > 0  # Should be positive for long
    assert performance["is_win"] is True


def test_track_exit_loss(tracker):
    """Test tracking exit with loss."""
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
    }
    signal_id = tracker.track_signal_generated(signal)
    tracker.track_entry(signal_id, 15000.0)
    
    # Exit at lower price (loss)
    performance = tracker.track_exit(
        signal_id=signal_id,
        exit_price=14900.0,
        exit_reason="stop_loss",
    )
    
    assert performance is not None
    assert performance["pnl"] < 0  # Should be negative
    assert performance["is_win"] is False


def test_track_exit_short(tracker):
    """Test tracking exit for short position."""
    signal = {
        "type": "breakout",
        "direction": "short",
        "entry_price": 15000.0,
    }
    signal_id = tracker.track_signal_generated(signal)
    tracker.track_entry(signal_id, 15000.0)
    
    # Exit at lower price (profit for short)
    performance = tracker.track_exit(
        signal_id=signal_id,
        exit_price=14900.0,
        exit_reason="take_profit",
    )
    
    assert performance is not None
    assert performance["pnl"] > 0  # Should be positive for short
    assert performance["is_win"] is True


def test_get_performance_metrics_no_signals(tracker):
    """Test performance metrics with no signals."""
    metrics = tracker.get_performance_metrics(days=7)
    
    assert metrics["total_signals"] == 0
    assert metrics["exited_signals"] == 0
    assert metrics["wins"] == 0
    assert metrics["losses"] == 0
    assert metrics["win_rate"] == 0.0
    assert metrics["total_pnl"] == 0.0


def test_get_performance_metrics_with_trades(tracker):
    """Test performance metrics with completed trades."""
    # Create multiple signals and track exits
    for i in range(5):
        signal = {
            "type": "breakout",
            "direction": "long",
            "entry_price": 15000.0 + i * 10,
        }
        signal_id = tracker.track_signal_generated(signal)
        tracker.track_entry(signal_id, 15000.0 + i * 10)
        
        # Alternate wins and losses
        exit_price = 15000.0 + i * 10 + (20 if i % 2 == 0 else -20)
        tracker.track_exit(
            signal_id=signal_id,
            exit_price=exit_price,
            exit_reason="take_profit" if i % 2 == 0 else "stop_loss",
        )
    
    metrics = tracker.get_performance_metrics(days=7)
    
    assert metrics["exited_signals"] > 0
    assert metrics["wins"] > 0
    assert metrics["losses"] > 0
    assert 0 <= metrics["win_rate"] <= 1.0
    assert "total_pnl" in metrics
    assert "avg_pnl" in metrics


def test_get_performance_metrics_all_wins(tracker):
    """Test performance metrics when all trades are wins."""
    for i in range(3):
        signal = {
            "type": "breakout",
            "direction": "long",
            "entry_price": 15000.0,
        }
        signal_id = tracker.track_signal_generated(signal)
        tracker.track_entry(signal_id, 15000.0)
        tracker.track_exit(
            signal_id=signal_id,
            exit_price=15100.0,  # All profitable
            exit_reason="take_profit",
        )
    
    metrics = tracker.get_performance_metrics(days=7)
    
    assert metrics["wins"] == 3
    assert metrics["losses"] == 0
    assert metrics["win_rate"] == 1.0
    assert metrics["total_pnl"] > 0


def test_get_performance_metrics_all_losses(tracker):
    """Test performance metrics when all trades are losses."""
    for i in range(3):
        signal = {
            "type": "breakout",
            "direction": "long",
            "entry_price": 15000.0,
        }
        signal_id = tracker.track_signal_generated(signal)
        tracker.track_entry(signal_id, 15000.0)
        tracker.track_exit(
            signal_id=signal_id,
            exit_price=14900.0,  # All losses
            exit_reason="stop_loss",
        )
    
    metrics = tracker.get_performance_metrics(days=7)
    
    assert metrics["wins"] == 0
    assert metrics["losses"] == 3
    assert metrics["win_rate"] == 0.0
    assert metrics["total_pnl"] < 0


def test_get_performance_metrics_by_signal_type(tracker):
    """Test performance metrics grouped by signal type."""
    # Create signals of different types
    for signal_type in ["breakout", "reversal", "breakout"]:
        signal = {
            "type": signal_type,
            "direction": "long",
            "entry_price": 15000.0,
        }
        signal_id = tracker.track_signal_generated(signal)
        tracker.track_entry(signal_id, 15000.0)
        tracker.track_exit(
            signal_id=signal_id,
            exit_price=15100.0,
            exit_reason="take_profit",
        )
    
    metrics = tracker.get_performance_metrics(days=7)
    
    assert "by_signal_type" in metrics
    assert len(metrics["by_signal_type"]) > 0

