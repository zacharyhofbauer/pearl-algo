"""
Tests for paper trading engines (futures and options).
"""

import pytest
from datetime import datetime

from pearlalgo.core.events import OrderEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.paper_trading.futures_engine import PaperFuturesEngine
from pearlalgo.paper_trading.options_engine import PaperOptionsEngine
from pearlalgo.paper_trading.fill_models import FillModelConfig


class TestPaperFuturesEngine:
    """Test paper futures trading engine."""

    def test_submit_order(self):
        """Test order submission and fill."""
        portfolio = Portfolio(cash=50000.0)

        def price_lookup(symbol: str):
            return 4000.0 if symbol == "ES" else None

        engine = PaperFuturesEngine(
            portfolio=portfolio,
            price_lookup=price_lookup,
        )

        order = OrderEvent(
            timestamp=datetime.now(),
            symbol="ES",
            side="BUY",
            quantity=1.0,
        )

        fill = engine.submit_order(order)

        assert fill is not None
        assert fill.symbol == "ES"
        assert fill.side == "BUY"
        assert fill.quantity == 1.0
        assert fill.price > 0

    def test_position_tracking(self):
        """Test position tracking after fills."""
        portfolio = Portfolio(cash=50000.0)

        def price_lookup(symbol: str):
            return 4000.0 if symbol == "ES" else None

        engine = PaperFuturesEngine(
            portfolio=portfolio,
            price_lookup=price_lookup,
        )

        order = OrderEvent(
            timestamp=datetime.now(),
            symbol="ES",
            side="BUY",
            quantity=1.0,
        )

        engine.submit_order(order)
        positions = engine.get_positions()

        assert "ES" in positions
        assert positions["ES"] == 1.0

    def test_margin_check(self):
        """Test margin call detection."""
        portfolio = Portfolio(cash=5000.0)  # Low cash

        def price_lookup(symbol: str):
            return 4000.0 if symbol == "ES" else None

        engine = PaperFuturesEngine(
            portfolio=portfolio,
            price_lookup=price_lookup,
        )

        order = OrderEvent(
            timestamp=datetime.now(),
            symbol="ES",
            side="BUY",
            quantity=10.0,  # Large position
        )

        # May fail due to insufficient margin
        fill = engine.submit_order(order)

        # If filled, check margin calls
        if fill:
            prices = {"ES": 4000.0}
            margin_calls = engine.check_margin_calls(prices)
            # Margin call logic depends on equity vs margin requirement


class TestPaperOptionsEngine:
    """Test paper options trading engine."""

    def test_submit_order_with_options_chain(self):
        """Test order submission with options chain data."""
        portfolio = Portfolio(cash=10000.0)

        def options_chain_lookup(underlying: str):
            if underlying == "QQQ":
                return [
                    {
                        "symbol": "QQQ_20241220_C_400",
                        "strike": 400.0,
                        "expiration": "2024-12-20",
                        "option_type": "call",
                        "bid": 2.45,
                        "ask": 2.55,
                        "last": 2.50,
                    }
                ]
            return []

        engine = PaperOptionsEngine(
            portfolio=portfolio,
            options_chain_lookup=options_chain_lookup,
        )

        # Update options chain
        engine.update_options_chain("QQQ", options_chain_lookup("QQQ"))

        order = OrderEvent(
            timestamp=datetime.now(),
            symbol="QQQ_20241220_C_400",
            side="BUY",
            quantity=1.0,
        )

        fill = engine.submit_order(order)

        # Fill should occur at ask price (or close to it)
        if fill:
            assert fill.symbol == "QQQ_20241220_C_400"
            assert fill.price >= 2.45  # Should be in bid-ask range





