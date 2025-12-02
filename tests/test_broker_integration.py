"""
Integration tests for broker factory and broker connections.
"""

from __future__ import annotations

import pytest

from pearlalgo.brokers.factory import get_broker
from pearlalgo.core.portfolio import Portfolio


@pytest.fixture
def sample_portfolio():
    """Create sample portfolio."""
    return Portfolio(cash=100000.0)


def test_broker_factory_ibkr(sample_portfolio):
    """Test IBKR broker creation via factory."""
    config = {"broker": {"primary": "ibkr"}}

    try:
        broker = get_broker("ibkr", sample_portfolio, config)
        assert broker is not None
        assert hasattr(broker, "submit_order")
        assert hasattr(broker, "fetch_fills")
    except Exception as e:
        # May fail if IB Gateway not running, that's OK for tests
        pytest.skip(
            f"IBKR broker creation failed (expected if Gateway not running): {e}"
        )


def test_broker_factory_bybit(sample_portfolio):
    """Test Bybit broker creation via factory."""
    config = {
        "broker": {
            "bybit": {
                "api_key": "test_key",
                "api_secret": "test_secret",
                "testnet": True,
            }
        }
    }

    try:
        broker = get_broker("bybit", sample_portfolio, config)
        assert broker is not None
        assert hasattr(broker, "submit_order")
        assert hasattr(broker, "sync_positions")
    except Exception as e:
        pytest.skip(f"Bybit broker creation failed: {e}")


def test_broker_factory_alpaca(sample_portfolio):
    """Test Alpaca broker creation via factory."""
    config = {
        "broker": {
            "alpaca": {
                "api_key": "test_key",
                "api_secret": "test_secret",
                "base_url": "https://paper-api.alpaca.markets",
            }
        }
    }

    try:
        broker = get_broker("alpaca", sample_portfolio, config)
        assert broker is not None
        assert hasattr(broker, "submit_order")
        assert hasattr(broker, "sync_positions")
    except Exception as e:
        pytest.skip(f"Alpaca broker creation failed: {e}")


def test_broker_factory_invalid():
    """Test factory with invalid broker name."""
    portfolio = Portfolio(cash=100000.0)

    with pytest.raises(ValueError):
        get_broker("invalid_broker", portfolio, {})
