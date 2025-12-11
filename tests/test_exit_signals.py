"""
Unit tests for exit signal generator.
"""

import pytest
from datetime import datetime, timezone

from pearlalgo.futures.signal_tracker import SignalTracker, TrackedSignal
from pearlalgo.futures.exit_signals import ExitSignalGenerator
from pearlalgo.agents.langgraph_state import TradingState, MarketData


@pytest.fixture
def signal_tracker():
    """Create signal tracker for testing."""
    return SignalTracker()


@pytest.fixture
def exit_generator(signal_tracker):
    """Create exit signal generator for testing."""
    return ExitSignalGenerator(signal_tracker=signal_tracker)


def test_stop_loss_check_long(exit_generator):
    """Test stop loss check for long position."""
    signal = TrackedSignal(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        direction="long",
        entry_price=4500.0,
        size=1,
        stop_loss=4490.0,
    )

    # Price below stop loss
    assert exit_generator.check_stop_loss(signal, 4485.0) is True

    # Price above stop loss
    assert exit_generator.check_stop_loss(signal, 4495.0) is False


def test_stop_loss_check_short(exit_generator):
    """Test stop loss check for short position."""
    signal = TrackedSignal(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        direction="short",
        entry_price=4500.0,
        size=1,
        stop_loss=4510.0,
    )

    # Price above stop loss
    assert exit_generator.check_stop_loss(signal, 4515.0) is True

    # Price below stop loss
    assert exit_generator.check_stop_loss(signal, 4505.0) is False


def test_take_profit_check_long(exit_generator):
    """Test take profit check for long position."""
    signal = TrackedSignal(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        direction="long",
        entry_price=4500.0,
        size=1,
        take_profit=4520.0,
    )

    # Price above take profit
    assert exit_generator.check_take_profit(signal, 4525.0) is True

    # Price below take profit
    assert exit_generator.check_take_profit(signal, 4515.0) is False


@pytest.mark.asyncio
async def test_generate_exit_signals_stop_loss(exit_generator, signal_tracker):
    """Test exit signal generation for stop loss."""
    # Add a tracked signal
    signal_tracker.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
        stop_loss=4490.0,
    )

    # Create state with price below stop loss
    state = TradingState(
        market_data={
            "ES": MarketData(
                symbol="ES",
                timestamp=datetime.now(timezone.utc),
                open=4485.0,
                high=4490.0,
                low=4480.0,
                close=4485.0,
                volume=1000,
            )
        },
        signals={},
        position_decisions={},
    )

    exit_signals = await exit_generator.generate_exit_signals(state)

    assert "ES" in exit_signals
    assert exit_signals["ES"].side == "flat"
    assert exit_signals["ES"].indicators.get("exit_type") == "stop_loss"


@pytest.mark.asyncio
async def test_generate_exit_signals_take_profit(exit_generator, signal_tracker):
    """Test exit signal generation for take profit."""
    # Add a tracked signal
    signal_tracker.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
        take_profit=4520.0,
    )

    # Create state with price above take profit
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

    exit_signals = await exit_generator.generate_exit_signals(state)

    assert "ES" in exit_signals
    assert exit_signals["ES"].side == "flat"
    assert exit_signals["ES"].indicators.get("exit_type") == "take_profit"


@pytest.mark.asyncio
async def test_generate_exit_signals_missing_market_data(exit_generator, signal_tracker):
    """Test exit signal generation when market data is missing."""
    # Add a tracked signal
    signal_tracker.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
        stop_loss=4490.0,
    )

    # Create state without market data for ES
    state = TradingState(
        market_data={},  # No market data
        signals={},
        position_decisions={},
    )

    exit_signals = await exit_generator.generate_exit_signals(state)

    # Should not generate exit signal without market data or fallback
    assert "ES" not in exit_signals


@pytest.mark.asyncio
async def test_generate_exit_signals_time_exit(exit_generator, signal_tracker):
    """Test time-based exit signal generation."""
    # Add a tracked signal with intraday strategy
    signal_tracker.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
        strategy_name="intraday_swing",
    )

    # Create state (price doesn't matter for time exit)
    state = TradingState(
        market_data={
            "ES": MarketData(
                symbol="ES",
                timestamp=datetime.now(timezone.utc),
                open=4500.0,
                high=4510.0,
                low=4490.0,
                close=4505.0,
                volume=1000,
            )
        },
        signals={},
        position_decisions={},
    )

    # Note: Time exit test would need to mock time or test at specific times
    # This is a basic structure - actual time exit testing requires time mocking
    exit_signals = await exit_generator.generate_exit_signals(state)
    
    # Time exit may or may not trigger depending on current time
    # This test verifies the function doesn't crash
    assert isinstance(exit_signals, dict)


@pytest.mark.asyncio
async def test_price_validation(exit_generator):
    """Test price validation."""
    signal = TrackedSignal(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        direction="long",
        entry_price=4500.0,
        size=1,
    )

    # Valid price
    assert exit_generator._validate_price(4500.0, "ES") is True
    
    # Invalid prices
    assert exit_generator._validate_price(None, "ES") is False
    assert exit_generator._validate_price(-100.0, "ES") is False
    assert exit_generator._validate_price(0.0, "ES") is False


def test_signal_persistence_save_load(tmp_path):
    """Test signal persistence save and load."""
    import json
    from pathlib import Path
    
    persistence_path = tmp_path / "test_signals.json"
    tracker1 = SignalTracker(persistence_path=persistence_path)
    
    # Add signals
    tracker1.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
        stop_loss=4490.0,
        take_profit=4520.0,
    )
    tracker1.add_signal(
        symbol="NQ",
        direction="short",
        entry_price=15000.0,
        size=1,
        stop_loss=15100.0,
    )
    
    # Create new tracker and load
    tracker2 = SignalTracker(persistence_path=persistence_path)
    
    # Verify signals were loaded
    assert len(tracker2.active_signals) == 2
    assert "ES" in tracker2.active_signals
    assert "NQ" in tracker2.active_signals
    
    es_signal = tracker2.get_signal("ES")
    assert es_signal.direction == "long"
    assert es_signal.entry_price == 4500.0
    assert es_signal.stop_loss == 4490.0
    assert es_signal.take_profit == 4520.0


def test_signal_validation(tmp_path):
    """Test signal validation."""
    persistence_path = tmp_path / "test_signals.json"
    tracker = SignalTracker(persistence_path=persistence_path)
    
    # Valid signal
    assert tracker.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
        stop_loss=4490.0,
    ) is True
    
    # Invalid signal (negative price)
    assert tracker.add_signal(
        symbol="ES",
        direction="long",
        entry_price=-100.0,
        size=1,
    ) is False
    
    # Invalid signal (wrong direction)
    assert tracker.add_signal(
        symbol="ES",
        direction="invalid",
        entry_price=4500.0,
        size=1,
    ) is False


def test_stale_signal_cleanup(tmp_path):
    """Test stale signal cleanup."""
    from datetime import timedelta
    
    persistence_path = tmp_path / "test_signals.json"
    tracker = SignalTracker(persistence_path=persistence_path, max_signal_age_days=1)
    
    # Add signal
    tracker.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
    )
    
    # Manually set old timestamp (simulate stale signal)
    signal = tracker.get_signal("ES")
    signal.timestamp = datetime.now(timezone.utc) - timedelta(days=2)
    
    # Cleanup stale signals
    removed = tracker.cleanup_stale_signals()
    
    assert removed == 1
    assert "ES" not in tracker.active_signals


def test_exited_signal_cleanup(tmp_path):
    """Test cleanup of exited signals."""
    from datetime import timedelta
    
    persistence_path = tmp_path / "test_signals.json"
    tracker = SignalTracker(persistence_path=persistence_path)
    
    # Add and mark as exited
    tracker.add_signal(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        size=1,
    )
    tracker.mark_signal_exited("ES", "test exit")
    
    # Manually set old exit timestamp
    signal = tracker.get_signal("ES")
    signal.exit_timestamp = datetime.now(timezone.utc) - timedelta(hours=25)
    
    # Cleanup exited signals
    removed = tracker.cleanup_exited_signals(grace_period_hours=24)
    
    assert removed == 1
    assert "ES" not in tracker.active_signals
