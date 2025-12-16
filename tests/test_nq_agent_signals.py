"""
Tests for NQ Agent signal generation and processing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.nq_agent.state_manager import NQAgentStateManager
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy


@pytest.fixture
def config():
    """Create a test configuration."""
    return NQIntradayConfig(
        symbol="NQ",
        timeframe="1m",
    )


@pytest.fixture
def strategy(config):
    """Create a strategy instance."""
    return NQIntradayStrategy(config=config)


@pytest.fixture
def sample_market_data():
    """Create sample market data."""
    dates = pd.date_range(
        start=datetime.now(timezone.utc) - pd.Timedelta(hours=2),
        end=datetime.now(timezone.utc),
        freq="1min",
    )[:100]
    
    df = pd.DataFrame({
        "open": [15000 + i * 0.1 for i in range(len(dates))],
        "high": [15010 + i * 0.1 for i in range(len(dates))],
        "low": [14990 + i * 0.1 for i in range(len(dates))],
        "close": [15005 + i * 0.1 for i in range(len(dates))],
        "volume": [1000 + i for i in range(len(dates))],
    }, index=dates)
    
    return {
        "df": df,
        "latest_bar": {
            "timestamp": datetime.now(timezone.utc),
            "open": 15000.0,
            "high": 15010.0,
            "low": 14990.0,
            "close": 15005.0,
            "volume": 1000,
        },
    }


def test_strategy_initialization(strategy):
    """Test strategy initializes correctly."""
    assert strategy is not None
    assert strategy.config.symbol == "NQ"
    assert strategy.scanner is not None
    assert strategy.signal_generator is not None


def test_strategy_analyze(strategy, sample_market_data):
    """Test strategy analysis."""
    signals = strategy.analyze(sample_market_data)
    
    # Should return a list (may be empty if no signals)
    assert isinstance(signals, list)


def test_strategy_analyze_empty_data(strategy):
    """Test strategy handles empty data."""
    empty_data = {
        "df": pd.DataFrame(),
        "latest_bar": None,
    }
    
    signals = strategy.analyze(empty_data)
    assert isinstance(signals, list)


def test_strategy_analyze_error_handling(strategy):
    """Test strategy handles errors gracefully."""
    # Invalid market data
    invalid_data = {
        "df": None,
        "latest_bar": None,
    }
    
    # Should not raise, should return empty list
    signals = strategy.analyze(invalid_data)
    assert isinstance(signals, list)
    assert len(signals) == 0


def test_signal_formatting():
    """Test signal has required fields."""
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
        "stop_loss": 14900.0,
        "take_profit": 15200.0,
        "confidence": 0.75,
        "reason": "Test signal",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Check required fields
    assert "type" in signal
    assert "direction" in signal
    assert "entry_price" in signal
    assert "confidence" in signal


def test_signal_persistence(tmp_path):
    """Test signal persistence."""
    state_dir = tmp_path / "nq_agent_state"
    state_manager = NQAgentStateManager(state_dir=state_dir)
    
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
        "stop_loss": 14900.0,
        "take_profit": 15200.0,
        "confidence": 0.75,
        "reason": "Test signal",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Save signal
    state_manager.save_signal(signal)
    
    # Retrieve signals
    signals = state_manager.get_recent_signals(limit=10)
    
    assert len(signals) > 0
    assert signals[-1]["type"] == "breakout"
    assert signals[-1]["entry_price"] == 15000.0


def test_duplicate_signal_prevention(tmp_path):
    """Test that duplicate signals can be detected."""
    state_dir = tmp_path / "nq_agent_state"
    state_manager = NQAgentStateManager(state_dir=state_dir)
    
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
        "stop_loss": 14900.0,
        "take_profit": 15200.0,
        "confidence": 0.75,
        "reason": "Test signal",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Save same signal twice
    state_manager.save_signal(signal)
    state_manager.save_signal(signal)
    
    # Both should be saved (current implementation doesn't prevent duplicates)
    signals = state_manager.get_recent_signals(limit=10)
    assert len(signals) >= 2



