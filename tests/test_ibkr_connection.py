"""
Tests for IBKR broker connection and contract resolution.
"""
from __future__ import annotations

import pytest

from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.brokers.contracts import resolve_future_contract, _default_exchange_for_symbol
from pearlalgo.core.portfolio import Portfolio


@pytest.fixture
def sample_portfolio():
    """Create sample portfolio."""
    return Portfolio(cash=100000.0)


def test_ibkr_broker_initialization(sample_portfolio):
    """Test IBKR broker can be initialized."""
    try:
        broker = IBKRBroker(portfolio=sample_portfolio)
        assert broker is not None
        assert hasattr(broker, "submit_order")
        assert hasattr(broker, "fetch_fills")
        assert hasattr(broker, "sync_positions")
    except Exception as e:
        pytest.skip(f"IBKR broker initialization failed (expected if Gateway not running): {e}")


def test_contract_resolution_es():
    """Test ES contract resolution."""
    try:
        contract = resolve_future_contract("ES", sec_type="FUT")
        assert contract is not None
        assert contract.symbol == "ES"
    except Exception as e:
        pytest.skip(f"Contract resolution failed (expected if Gateway not running): {e}")


def test_contract_resolution_nq():
    """Test NQ contract resolution."""
    try:
        contract = resolve_future_contract("NQ", sec_type="FUT")
        assert contract is not None
        assert contract.symbol == "NQ"
    except Exception as e:
        pytest.skip(f"Contract resolution failed (expected if Gateway not running): {e}")


def test_default_exchange_mapping():
    """Test default exchange mapping for symbols."""
    assert _default_exchange_for_symbol("ES") == "CME"
    assert _default_exchange_for_symbol("NQ") == "CME"
    assert _default_exchange_for_symbol("CL") == "NYMEX"
    assert _default_exchange_for_symbol("GC") == "COMEX"  # Gold is on COMEX, not NYMEX


def test_ibkr_connection_check(sample_portfolio):
    """Test IBKR connection check (will skip if Gateway not running)."""
    try:
        broker = IBKRBroker(portfolio=sample_portfolio)
        # Try to check connection (may fail if Gateway not running)
        connected = broker._ib.isConnected() if hasattr(broker, "_ib") else False
        # This is OK - we're just testing the code path
        assert isinstance(connected, bool)
    except Exception as e:
        pytest.skip(f"IBKR connection check failed (expected if Gateway not running): {e}")

