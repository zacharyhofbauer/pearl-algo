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

    exit_signals = exit_generator.generate_exit_signals(state)

    assert "ES" in exit_signals
    assert exit_signals["ES"].side == "flat"
    assert "stop_loss" in exit_signals["ES"].indicators.get("exit_type", "")


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

    exit_signals = exit_generator.generate_exit_signals(state)

    assert "ES" in exit_signals
    assert exit_signals["ES"].side == "flat"
    assert "take_profit" in exit_signals["ES"].indicators.get("exit_type", "")
