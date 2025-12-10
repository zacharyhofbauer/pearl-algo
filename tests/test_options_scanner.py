"""
Unit tests for options scanner.
"""

import pytest
from unittest.mock import Mock, AsyncMock

from pearlalgo.options.universe import EquityUniverse
from pearlalgo.options.swing_scanner import OptionsSwingScanner
from pearlalgo.options.chain_filter import OptionsChainFilter


@pytest.fixture
def universe():
    """Create equity universe for testing."""
    return EquityUniverse(symbols=["SPY", "QQQ", "AAPL"])


@pytest.fixture
def chain_filter():
    """Create options chain filter for testing."""
    return OptionsChainFilter(
        min_volume=100,
        min_open_interest=50,
        max_dte=45,
    )


def test_universe_initialization(universe):
    """Test equity universe initialization."""
    assert universe.get_count() == 3
    assert "SPY" in universe.get_symbols()
    assert "QQQ" in universe.get_symbols()
    assert "AAPL" in universe.get_symbols()


def test_universe_add_remove(universe):
    """Test adding and removing symbols."""
    universe.add_symbol("MSFT")
    assert universe.get_count() == 4
    assert "MSFT" in universe.get_symbols()

    universe.remove_symbol("AAPL")
    assert universe.get_count() == 3
    assert "AAPL" not in universe.get_symbols()


def test_chain_filter_initialization(chain_filter):
    """Test options chain filter initialization."""
    assert chain_filter.min_volume == 100
    assert chain_filter.min_open_interest == 50
    assert chain_filter.max_dte == 45


def test_chain_filter_filtering(chain_filter):
    """Test options chain filtering."""
    from datetime import datetime, timedelta, timezone

    current_date = datetime.now(timezone.utc)
    expiration = current_date + timedelta(days=30)

    chain = [
        {
            "strike_price": 100.0,
            "option_type": "call",
            "volume": 150,
            "open_interest": 75,
            "expiration_date": expiration.isoformat(),
        },
        {
            "strike_price": 105.0,
            "option_type": "call",
            "volume": 50,  # Below threshold
            "open_interest": 75,
            "expiration_date": expiration.isoformat(),
        },
    ]

    filtered = chain_filter.filter_chain(chain, underlying_price=100.0, current_date=current_date)
    assert len(filtered) == 1  # Only first option passes volume filter


def test_chain_filter_strike_selection(chain_filter):
    """Test strike selection filtering."""
    from datetime import datetime, timedelta, timezone

    current_date = datetime.now(timezone.utc)
    expiration = current_date + timedelta(days=30)

    chain = [
        {
            "strike_price": 100.0,  # ATM
            "option_type": "call",
            "volume": 150,
            "open_interest": 75,
            "expiration_date": expiration.isoformat(),
        },
        {
            "strike_price": 110.0,  # OTM
            "option_type": "call",
            "volume": 150,
            "open_interest": 75,
            "expiration_date": expiration.isoformat(),
        },
    ]

    # Test ATM selection
    chain_filter.strike_selection = "atm"
    filtered = chain_filter.filter_chain(chain, underlying_price=100.0, current_date=current_date)
    assert len(filtered) == 1
    assert filtered[0]["strike_price"] == 100.0

    # Test OTM selection
    chain_filter.strike_selection = "otm"
    filtered = chain_filter.filter_chain(chain, underlying_price=100.0, current_date=current_date)
    assert len(filtered) == 1
    assert filtered[0]["strike_price"] == 110.0


@pytest.mark.asyncio
async def test_options_scanner_initialization(universe):
    """Test options scanner initialization."""
    scanner = OptionsSwingScanner(
        universe=universe,
        strategy="swing_momentum",
        config={},
    )

    assert scanner.universe == universe
    assert scanner.strategy == "swing_momentum"
    assert len(scanner.trader.symbols) == 3
