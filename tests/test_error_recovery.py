"""
Tests for error recovery scenarios and edge cases.
"""

import pytest
import json
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


def test_corrupted_persistence_file_recovery(tmp_path):
    """Test recovery from corrupted persistence file."""
    persistence_path = tmp_path / "signals.json"
    
    # Create corrupted JSON file
    with open(persistence_path, "w") as f:
        f.write("{ invalid json }")
    
    # Create backup
    backup_path = persistence_path.with_suffix('.json.bak')
    with open(backup_path, "w") as f:
        json.dump({
            "ES": {
                "symbol": "ES",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "direction": "long",
                "entry_price": 4500.0,
                "size": 1,
                "stop_loss": 4490.0,
                "take_profit": None,
                "strategy_name": "test",
                "reasoning": None,
                "unrealized_pnl": 0.0,
                "last_update": datetime.now(timezone.utc).isoformat(),
                "lifecycle_state": "active",
                "exit_timestamp": None,
                "exit_reason": None,
            }
        }, f)
    
    # Should recover from backup
    tracker = SignalTracker(persistence_path=persistence_path)
    assert "ES" in tracker.active_signals


def test_invalid_signal_skipped_on_load(tmp_path):
    """Test that invalid signals are skipped during load."""
    persistence_path = tmp_path / "signals.json"
    
    # Create file with valid and invalid signals
    with open(persistence_path, "w") as f:
        json.dump({
            "ES": {
                "symbol": "ES",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "direction": "long",
                "entry_price": 4500.0,
                "size": 1,
                "stop_loss": 4490.0,
                "take_profit": None,
                "strategy_name": "test",
                "reasoning": None,
                "unrealized_pnl": 0.0,
                "last_update": datetime.now(timezone.utc).isoformat(),
                "lifecycle_state": "active",
                "exit_timestamp": None,
                "exit_reason": None,
            },
            "INVALID": {
                "symbol": "INVALID",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "direction": "invalid_direction",  # Invalid
                "entry_price": -100.0,  # Invalid
                "size": 1,
                "stop_loss": None,
                "take_profit": None,
                "strategy_name": "test",
                "reasoning": None,
                "unrealized_pnl": 0.0,
                "last_update": datetime.now(timezone.utc).isoformat(),
                "lifecycle_state": "active",
                "exit_timestamp": None,
                "exit_reason": None,
            }
        }, f)
    
    tracker = SignalTracker(persistence_path=persistence_path)
    assert "ES" in tracker.active_signals
    assert "INVALID" not in tracker.active_signals


@pytest.mark.asyncio
async def test_missing_market_data_handling(exit_generator_with_tracker, tracker_with_persistence):
    """Test handling of missing market data."""
    tracker_with_persistence.add_signal("ES", "long", 4500.0, 1, stop_loss=4490.0)
    
    # State with no market data
    state = TradingState(
        market_data={},
        signals={},
        position_decisions={},
    )
    
    # Should not crash, just skip
    exit_signals = await exit_generator_with_tracker.generate_exit_signals(state)
    assert "ES" not in exit_signals


@pytest.mark.asyncio
async def test_invalid_price_handling(exit_generator_with_tracker, tracker_with_persistence):
    """Test handling of invalid prices."""
    tracker_with_persistence.add_signal("ES", "long", 4500.0, 1, stop_loss=4490.0)
    
    # Create mock MarketData with invalid price
    class InvalidMarketData:
        def __init__(self):
            self.symbol = "ES"
            self.timestamp = datetime.now(timezone.utc)
            self.close = float('nan')  # Invalid
    
    state = TradingState(
        market_data={"ES": InvalidMarketData()},
        signals={},
        position_decisions={},
    )
    
    # Should handle gracefully
    exit_signals = await exit_generator_with_tracker.generate_exit_signals(state)
    # Should skip invalid price
    assert "ES" not in exit_signals or exit_signals.get("ES") is None


def test_signal_reconciliation(tracker_with_persistence):
    """Test signal reconciliation."""
    tracker_with_persistence.add_signal("ES", "long", 4500.0, 1)
    tracker_with_persistence.add_signal("NQ", "short", 15000.0, 1)
    
    # Reconcile with expected symbols
    results = tracker_with_persistence.reconcile_signals(expected_symbols=["ES", "NQ"])
    assert results["total_signals"] == 2
    assert results["orphaned_signals"] == 0
    assert results["missing_signals"] == 0
    
    # Reconcile with missing expected
    results = tracker_with_persistence.reconcile_signals(expected_symbols=["ES"])
    assert results["orphaned_signals"] == 1  # NQ is orphaned
    assert results["missing_signals"] == 0
    
    # Reconcile with extra expected
    results = tracker_with_persistence.reconcile_signals(expected_symbols=["ES", "NQ", "CL"])
    assert results["missing_signals"] == 1  # CL is missing
