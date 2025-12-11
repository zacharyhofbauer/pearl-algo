"""
Tests for Options Signal Tracker
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import shutil

from pearlalgo.options.signal_tracker import (
    OptionsSignalTracker,
    TrackedOptionsSignal,
    OptionsSignalLifecycleState,
)


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def tracker(temp_dir):
    """Create signal tracker with temp directory."""
    persistence_path = temp_dir / "test_signals.json"
    return OptionsSignalTracker(
        persistence_path=persistence_path,
        max_signal_age_days=30,
    )


def test_tracked_signal_creation():
    """Test creating a tracked options signal."""
    expiration = datetime.now(timezone.utc) + timedelta(days=7)
    
    signal = TrackedOptionsSignal(
        underlying_symbol="QQQ",
        timestamp=datetime.now(timezone.utc),
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=expiration,
        option_type="call",
        dte=7,
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    assert signal.underlying_symbol == "QQQ"
    assert signal.option_symbol == "QQQ240119C00400"
    assert signal.strike == 400.0
    assert signal.option_type == "call"
    assert signal.direction == "long"
    assert signal.entry_premium == 2.55
    assert not signal.is_expired()


def test_tracked_signal_expiration():
    """Test expiration checking."""
    # Expired option
    expired_signal = TrackedOptionsSignal(
        underlying_symbol="QQQ",
        timestamp=datetime.now(timezone.utc) - timedelta(days=10),
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=datetime.now(timezone.utc) - timedelta(days=1),
        option_type="call",
        dte=0,
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    assert expired_signal.is_expired()
    assert expired_signal.get_current_dte() == 0
    
    # Active option
    active_signal = TrackedOptionsSignal(
        underlying_symbol="QQQ",
        timestamp=datetime.now(timezone.utc),
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=datetime.now(timezone.utc) + timedelta(days=7),
        option_type="call",
        dte=7,
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    assert not active_signal.is_expired()
    assert active_signal.get_current_dte() > 0


def test_tracker_add_signal(tracker):
    """Test adding a signal to tracker."""
    expiration = datetime.now(timezone.utc) + timedelta(days=7)
    
    signal = tracker.add_signal(
        underlying_symbol="QQQ",
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=expiration,
        option_type="call",
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    assert signal is not None
    assert tracker.get_signal("QQQ240119C00400") == signal
    assert len(tracker.get_active_signals()) == 1


def test_tracker_update_pnl(tracker):
    """Test updating PnL for a position."""
    expiration = datetime.now(timezone.utc) + timedelta(days=7)
    
    tracker.add_signal(
        underlying_symbol="QQQ",
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=expiration,
        option_type="call",
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    # Update with higher premium (profit)
    updated = tracker.update_pnl(
        "QQQ240119C00400",
        current_premium=3.00,
        underlying_price=405.0,
    )
    
    assert updated is not None
    assert updated.unrealized_pnl > 0  # Profit
    assert updated.last_premium == 3.00
    assert updated.last_underlying_price == 405.0


def test_tracker_remove_signal(tracker):
    """Test removing a signal."""
    expiration = datetime.now(timezone.utc) + timedelta(days=7)
    
    tracker.add_signal(
        underlying_symbol="QQQ",
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=expiration,
        option_type="call",
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    removed = tracker.remove_signal("QQQ240119C00400")
    
    assert removed is not None
    assert removed.lifecycle_state == OptionsSignalLifecycleState.EXITED
    assert tracker.get_signal("QQQ240119C00400") is None
    assert len(tracker.get_active_signals()) == 0


def test_tracker_expiration_handling(tracker):
    """Test automatic expiration handling."""
    # Add expired option
    expired_expiration = datetime.now(timezone.utc) - timedelta(days=1)
    
    tracker.add_signal(
        underlying_symbol="QQQ",
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=expired_expiration,
        option_type="call",
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    # Update PnL should mark as expired
    updated = tracker.update_pnl(
        "QQQ240119C00400",
        current_premium=0.01,  # Near zero (expired)
    )
    
    assert updated is not None
    assert updated.lifecycle_state == OptionsSignalLifecycleState.EXPIRED
    assert updated.is_expired()


def test_tracker_statistics(tracker):
    """Test tracker statistics."""
    expiration = datetime.now(timezone.utc) + timedelta(days=7)
    
    # Add active signal
    tracker.add_signal(
        underlying_symbol="QQQ",
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=expiration,
        option_type="call",
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    # Update with profit
    tracker.update_pnl("QQQ240119C00400", current_premium=3.00)
    
    stats = tracker.get_statistics()
    
    assert stats["total_signals"] == 1
    assert stats["active_signals"] == 1
    assert stats["total_unrealized_pnl"] > 0


def test_tracker_persistence(tracker, temp_dir):
    """Test signal persistence."""
    expiration = datetime.now(timezone.utc) + timedelta(days=7)
    
    # Add signal
    tracker.add_signal(
        underlying_symbol="QQQ",
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=expiration,
        option_type="call",
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    # Create new tracker and load
    new_tracker = OptionsSignalTracker(
        persistence_path=tracker.persistence_path,
    )
    
    # Should have loaded the signal
    assert len(new_tracker.get_active_signals()) == 1
    loaded_signal = new_tracker.get_signal("QQQ240119C00400")
    assert loaded_signal is not None
    assert loaded_signal.strike == 400.0


def test_tracker_cleanup_old_signals(tracker):
    """Test cleanup of old signals."""
    # Add old signal
    old_expiration = datetime.now(timezone.utc) - timedelta(days=50)
    tracker.add_signal(
        underlying_symbol="QQQ",
        option_symbol="QQQ_OLD",
        strike=400.0,
        expiration=old_expiration,
        option_type="call",
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    # Manually set timestamp to old
    tracker.signals["QQQ_OLD"].timestamp = datetime.now(timezone.utc) - timedelta(days=31)
    tracker.signals["QQQ_OLD"].lifecycle_state = OptionsSignalLifecycleState.EXITED
    
    # Add active signal
    new_expiration = datetime.now(timezone.utc) + timedelta(days=7)
    tracker.add_signal(
        underlying_symbol="QQQ",
        option_symbol="QQQ_NEW",
        strike=400.0,
        expiration=new_expiration,
        option_type="call",
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    # Cleanup
    removed_count = tracker.cleanup_old_signals()
    
    assert removed_count == 1
    assert tracker.get_signal("QQQ_OLD") is None
    assert tracker.get_signal("QQQ_NEW") is not None  # Active signal kept
