"""
Integration tests for multi-asset scanning (futures + options).
"""

import pytest
from unittest.mock import Mock, AsyncMock

from pearlalgo.futures.intraday_scanner import FuturesIntradayScanner
from pearlalgo.options.swing_scanner import OptionsSwingScanner
from pearlalgo.options.universe import EquityUniverse
from pearlalgo.core.signal_router import SignalRouter


@pytest.mark.asyncio
async def test_futures_and_options_together():
    """Test that futures and options scanners can run together."""
    # Create futures scanner
    futures_scanner = FuturesIntradayScanner(
        symbols=["ES", "NQ"],
        strategy="intraday_swing",
    )

    # Create options scanner
    universe = EquityUniverse(symbols=["SPY", "QQQ"])
    options_scanner = OptionsSwingScanner(
        universe=universe,
        strategy="swing_momentum",
    )

    # Both should initialize without errors
    assert futures_scanner.symbols == ["ES", "NQ"]
    assert options_scanner.universe.get_count() == 2


def test_signal_router_futures_vs_options():
    """Test signal router distinguishes futures from options."""
    router = SignalRouter()

    # Futures symbols
    assert router.is_futures("ES") is True
    assert router.is_futures("NQ") is True
    assert router.is_futures("MES") is True

    # Options symbols (format: SYMBOL_YYMMDD_C_STRIKE)
    assert router.is_options("SPY_251220_C_450") is True
    assert router.is_options("AAPL_251220_P_150") is True

    # Equity symbols (treated as options for scanning)
    assert router.is_options("SPY") is False  # But will route to options
    assert router.is_options("AAPL") is False


def test_signal_router_routing():
    """Test signal routing logic."""
    from pearlalgo.agents.langgraph_state import Signal
    from datetime import datetime, timezone

    router = SignalRouter()

    # Futures signal
    futures_signal = Signal(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        side="long",
        strategy_name="intraday_swing",
        confidence=0.75,
    )

    assert router.route_signal(futures_signal) == "futures"

    # Options signal
    options_signal = Signal(
        symbol="SPY_251220_C_450",
        timestamp=datetime.now(timezone.utc),
        side="long",
        strategy_name="swing_momentum",
        confidence=0.75,
    )

    assert router.route_signal(options_signal) == "options"
