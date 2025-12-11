"""
Integration tests for full signal lifecycle from entry to exit.
"""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pearlalgo.futures.signal_tracker import SignalTracker, SignalLifecycleState
from pearlalgo.futures.exit_signals import ExitSignalGenerator
from pearlalgo.agents.langgraph_state import TradingState, MarketData


@pytest.fixture
def tracker_with_persistence(tmp_path):
    """Create signal tracker with persistence."""
    persistence_path = tmp_path / "signals.json"
    return SignalTracker(persistence_path=persistence_path)


@pytest.fixture
def exit_generator_with_tracker(tracker_with_persistence):
    """Create exit signal generator with tracker."""
    return ExitSignalGenerator(signal_tracker=tracker_with_persistence)


@pytest.mark.asyncio
async def test_full_signal_lifecycle(exit_generator_with_tracker, tracker_with_persistence):
    """Test complete signal lifecycle: add -> track -> exit -> cleanup."""
    # Step 1: Add signal
    success = tracker_with_persistence.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
        stop_loss=4490.0,
        take_profit=4520.0,
        strategy_name="intraday_swing",
    )
    assert success is True
    
    signal = tracker_with_persistence.get_signal("ES")
    assert signal is not None
    assert signal.lifecycle_state == SignalLifecycleState.ACTIVE
    
    # Step 2: Update PnL (price moves up)
    tracker_with_persistence.update_pnl("ES", 4505.0)
    signal = tracker_with_persistence.get_signal("ES")
    assert signal.unrealized_pnl > 0
    
    # Step 3: Generate exit signal (take profit hit)
    state = TradingState(
        market_data={
            "ES": MarketData(
                symbol="ES",
                timestamp=datetime.now(timezone.utc),
                open=4520.0,
                high=4525.0,
                low=4515.0,
                close=4525.0,
                volume=1000,
            )
        },
        signals={},
        position_decisions={},
    )
    
    exit_signals = await exit_generator_with_tracker.generate_exit_signals(state)
    assert "ES" in exit_signals
    assert exit_signals["ES"].indicators.get("exit_type") == "take_profit"
    
    # Step 4: Remove signal (mark as exited)
    removed = tracker_with_persistence.remove_signal("ES", mark_exited=True)
    assert removed is not None
    assert removed.lifecycle_state == SignalLifecycleState.EXITED
    
    # Step 5: Cleanup exited signal
    removed.exit_timestamp = datetime.now(timezone.utc) - timedelta(hours=25)
    tracker_with_persistence.active_signals["ES"] = removed  # Re-add for cleanup test
    cleaned = tracker_with_persistence.cleanup_exited_signals(grace_period_hours=24)
    assert cleaned == 1
    assert "ES" not in tracker_with_persistence.active_signals


@pytest.mark.asyncio
async def test_signal_persistence_across_restarts(tmp_path):
    """Test that signals persist across service restarts."""
    persistence_path = tmp_path / "signals.json"
    
    # First instance: add signal
    tracker1 = SignalTracker(persistence_path=persistence_path)
    tracker1.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
        stop_loss=4490.0,
    )
    
    # Second instance: load signal
    tracker2 = SignalTracker(persistence_path=persistence_path)
    assert "ES" in tracker2.active_signals
    
    signal = tracker2.get_signal("ES")
    assert signal.entry_price == 4500.0
    assert signal.stop_loss == 4490.0
    assert signal.lifecycle_state == SignalLifecycleState.ACTIVE


@pytest.mark.asyncio
async def test_multiple_signals_lifecycle(exit_generator_with_tracker, tracker_with_persistence):
    """Test lifecycle with multiple signals."""
    # Add multiple signals
    tracker_with_persistence.add_signal("ES", "long", 4500.0, 1, stop_loss=4490.0)
    tracker_with_persistence.add_signal("NQ", "short", 15000.0, 1, stop_loss=15100.0)
    
    assert len(tracker_with_persistence.active_signals) == 2
    
    # Update PnL for both
    tracker_with_persistence.update_all_pnl({"ES": 4505.0, "NQ": 14995.0})
    
    # Exit one signal
    state = TradingState(
        market_data={
            "ES": MarketData("ES", datetime.now(timezone.utc), 4485.0, 4490.0, 4480.0, 4485.0, 1000),
        },
        signals={},
        position_decisions={},
    )
    
    exit_signals = await exit_generator_with_tracker.generate_exit_signals(state)
    assert "ES" in exit_signals  # Stop loss hit
    
    # Remove exited signal
    tracker_with_persistence.remove_signal("ES")
    assert "ES" not in tracker_with_persistence.active_signals
    assert "NQ" in tracker_with_persistence.active_signals  # Still active
