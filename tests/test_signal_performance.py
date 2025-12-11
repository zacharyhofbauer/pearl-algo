"""
Performance tests for signal operations.
"""

import pytest
import time
from datetime import datetime, timezone
from pathlib import Path

from pearlalgo.futures.signal_tracker import SignalTracker
from pearlalgo.futures.exit_signals import ExitSignalGenerator
from pearlalgo.agents.langgraph_state import TradingState, MarketData


@pytest.fixture
def tracker_with_persistence(tmp_path):
    """Create signal tracker with persistence."""
    persistence_path = tmp_path / "signals.json"
    return SignalTracker(persistence_path=persistence_path)


def test_signal_add_performance(tracker_with_persistence):
    """Test performance of adding signals."""
    start = time.time()
    
    for i in range(100):
        tracker_with_persistence.add_signal(
            symbol=f"SYM{i}",
            direction="long",
            entry_price=4500.0 + i,
            size=1,
        )
    
    elapsed = time.time() - start
    assert elapsed < 5.0  # Should complete in under 5 seconds
    assert len(tracker_with_persistence.active_signals) == 100


def test_signal_pnl_update_performance(tracker_with_persistence):
    """Test performance of PnL updates."""
    # Add signals
    for i in range(50):
        tracker_with_persistence.add_signal(
            symbol=f"SYM{i}",
            direction="long",
            entry_price=4500.0,
            size=1,
        )
    
    # Update PnL for all
    prices = {f"SYM{i}": 4505.0 for i in range(50)}
    
    start = time.time()
    tracker_with_persistence.update_all_pnl(prices)
    elapsed = time.time() - start
    
    assert elapsed < 1.0  # Should complete in under 1 second


@pytest.mark.asyncio
async def test_exit_signal_generation_performance(tracker_with_persistence):
    """Test performance of exit signal generation."""
    exit_generator = ExitSignalGenerator(signal_tracker=tracker_with_persistence)
    
    # Add signals
    for i in range(20):
        tracker_with_persistence.add_signal(
            symbol=f"SYM{i}",
            direction="long",
            entry_price=4500.0,
            size=1,
            stop_loss=4490.0,
        )
    
    # Create state with market data
    state = TradingState(
        market_data={
            f"SYM{i}": MarketData(
                symbol=f"SYM{i}",
                timestamp=datetime.now(timezone.utc),
                open=4485.0,
                high=4490.0,
                low=4480.0,
                close=4485.0,
                volume=1000,
            )
            for i in range(20)
        },
        signals={},
        position_decisions={},
    )
    
    start = time.time()
    exit_signals = await exit_generator.generate_exit_signals(state)
    elapsed = time.time() - start
    
    assert elapsed < 2.0  # Should complete in under 2 seconds
    assert len(exit_signals) == 20  # All should hit stop loss


def test_persistence_write_performance(tracker_with_persistence):
    """Test performance of persistence writes."""
    # Add signals
    for i in range(50):
        tracker_with_persistence.add_signal(
            symbol=f"SYM{i}",
            direction="long",
            entry_price=4500.0,
            size=1,
        )
    
    # Measure save time
    start = time.time()
    tracker_with_persistence._save_signals()
    elapsed = time.time() - start
    
    assert elapsed < 1.0  # Should save in under 1 second


def test_persistence_load_performance(tmp_path):
    """Test performance of persistence loads."""
    persistence_path = tmp_path / "signals.json"
    
    # Create tracker with many signals
    tracker1 = SignalTracker(persistence_path=persistence_path)
    for i in range(100):
        tracker1.add_signal(
            symbol=f"SYM{i}",
            direction="long",
            entry_price=4500.0,
            size=1,
        )
    
    # Measure load time
    start = time.time()
    tracker2 = SignalTracker(persistence_path=persistence_path)
    elapsed = time.time() - start
    
    assert elapsed < 2.0  # Should load in under 2 seconds
    assert len(tracker2.active_signals) == 100
