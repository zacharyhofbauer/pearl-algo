"""
Tests for NQ Agent State Manager.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pearlalgo.nq_agent.state_manager import NQAgentStateManager


@pytest.fixture
def state_dir(tmp_path):
    """Create a temporary state directory."""
    state_dir = tmp_path / "nq_agent_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


@pytest.fixture
def state_manager(state_dir):
    """Create a state manager instance."""
    return NQAgentStateManager(state_dir=state_dir)


def test_state_manager_initialization(state_manager, state_dir):
    """Test state manager initializes correctly."""
    assert state_manager.state_dir == state_dir
    assert state_manager.signals_file.exists() or state_dir.exists()
    assert state_manager.state_file.parent == state_dir


def test_save_signal(state_manager):
    """Test saving a signal."""
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    state_manager.save_signal(signal)
    
    # Check file exists and contains signal
    assert state_manager.signals_file.exists()
    
    with open(state_manager.signals_file) as f:
        lines = f.readlines()
        assert len(lines) > 0
        
        # Last line should contain our signal
        last_signal = json.loads(lines[-1])
        assert last_signal["type"] == "breakout"


def test_get_recent_signals(state_manager):
    """Test retrieving recent signals."""
    # Save multiple signals
    for i in range(5):
        signal = {
            "type": "breakout",
            "direction": "long",
            "entry_price": 15000.0 + i,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        state_manager.save_signal(signal)
    
    # Get recent signals
    signals = state_manager.get_recent_signals(limit=3)
    
    assert len(signals) == 3
    assert signals[-1]["entry_price"] == 15004.0  # Last signal


def test_get_recent_signals_empty(state_manager):
    """Test retrieving signals when none exist."""
    signals = state_manager.get_recent_signals(limit=10)
    
    assert isinstance(signals, list)
    assert len(signals) == 0


def test_save_state(state_manager):
    """Test saving service state."""
    state = {
        "running": True,
        "cycle_count": 100,
        "signal_count": 5,
    }
    
    state_manager.save_state(state)
    
    # Check file exists
    assert state_manager.state_file.exists()
    
    # Load and verify
    loaded_state = state_manager.load_state()
    assert loaded_state["running"] is True
    assert loaded_state["cycle_count"] == 100
    assert "last_updated" in loaded_state


def test_load_state(state_manager):
    """Test loading service state."""
    # Save state first
    state = {
        "running": True,
        "cycle_count": 50,
    }
    state_manager.save_state(state)
    
    # Load state
    loaded_state = state_manager.load_state()
    
    assert loaded_state["running"] is True
    assert loaded_state["cycle_count"] == 50


def test_load_state_nonexistent(state_manager):
    """Test loading state when file doesn't exist."""
    # Remove state file if it exists
    if state_manager.state_file.exists():
        state_manager.state_file.unlink()
    
    # Should return empty dict
    state = state_manager.load_state()
    assert state == {}


def test_signal_file_corruption_handling(state_manager):
    """Test handling of corrupted signal file."""
    # Write invalid JSON
    with open(state_manager.signals_file, "w") as f:
        f.write("invalid json\n")
        f.write('{"valid": "json"}\n')
        f.write("more invalid\n")
    
    # Should skip invalid lines
    signals = state_manager.get_recent_signals(limit=10)
    
    # Should have at least the valid signal
    assert len(signals) >= 1
    assert signals[0]["valid"] == "json"


def test_concurrent_access_simulation(state_manager):
    """Test that multiple signals can be saved sequentially."""
    # Simulate concurrent access by saving multiple signals quickly
    signals = []
    for i in range(10):
        signal = {
            "type": "breakout",
            "direction": "long",
            "entry_price": 15000.0 + i,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        state_manager.save_signal(signal)
        signals.append(signal)
    
    # All should be saved
    saved_signals = state_manager.get_recent_signals(limit=20)
    assert len(saved_signals) >= 10



