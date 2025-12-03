"""
Tests for fill models (slippage, delays, deterministic mode).
"""

import pytest
from datetime import datetime

from pearlalgo.paper_trading.fill_models import (
    FillModel,
    FillModelConfig,
    FuturesFillModel,
    OptionsFillModel,
)


class TestFillModel:
    """Test base fill model."""

    def test_basic_fill(self):
        """Test basic fill calculation."""
        model = FillModel()
        timestamp = datetime.now()

        fill_price, fill_qty, fill_time = model.apply_fill(
            price=100.0, side="BUY", quantity=1.0, timestamp=timestamp
        )

        assert fill_price > 100.0  # Should add slippage for BUY
        assert fill_qty == 1.0  # No partial fill by default
        assert fill_time >= timestamp

    def test_sell_fill(self):
        """Test sell fill has negative slippage."""
        model = FillModel()
        timestamp = datetime.now()

        fill_price, _, _ = model.apply_fill(
            price=100.0, side="SELL", quantity=1.0, timestamp=timestamp
        )

        assert fill_price < 100.0  # Should subtract slippage for SELL

    def test_deterministic_mode(self):
        """Test deterministic mode produces consistent results."""
        config = FillModelConfig(deterministic=True, random_seed=42)
        model1 = FillModel(config=config)
        model2 = FillModel(config=config)

        timestamp = datetime.now()

        fill1 = model1.apply_fill(price=100.0, side="BUY", quantity=1.0, timestamp=timestamp)
        fill2 = model2.apply_fill(price=100.0, side="BUY", quantity=1.0, timestamp=timestamp)

        assert fill1[0] == fill2[0]  # Same fill price
        assert fill1[1] == fill2[1]  # Same quantity

    def test_slippage_calculation(self):
        """Test slippage is applied correctly."""
        config = FillModelConfig(slippage_bps=10.0)  # 10 bps = 0.1%
        model = FillModel(config=config)

        buy_fill = model.calculate_slippage(price=100.0, side="BUY", quantity=1.0)
        sell_fill = model.calculate_slippage(price=100.0, side="SELL", quantity=1.0)

        # Buy should pay more (add slippage)
        assert buy_fill > 100.0
        assert abs(buy_fill - 100.1) < 0.01  # ~0.1% slippage

        # Sell should receive less (subtract slippage)
        assert sell_fill < 100.0
        assert abs(sell_fill - 99.9) < 0.01


class TestFuturesFillModel:
    """Test futures-specific fill model."""

    def test_atr_based_slippage(self):
        """Test ATR-based slippage for futures."""
        config = FillModelConfig(slippage_bps=2.0)
        model = FuturesFillModel(config=config, atr=5.0)

        fill_price = model.calculate_slippage(price=4000.0, side="BUY", quantity=1.0)

        # Should use ATR for slippage calculation
        assert fill_price > 4000.0


class TestOptionsFillModel:
    """Test options-specific fill model."""

    def test_bid_ask_spread_slippage(self):
        """Test bid-ask spread based slippage."""
        config = FillModelConfig(slippage_bps=2.0)
        model = OptionsFillModel(config=config, bid=2.45, ask=2.55)

        # Mid price would be 2.50
        buy_fill = model.calculate_slippage(price=2.50, side="BUY", quantity=1.0)
        sell_fill = model.calculate_slippage(price=2.50, side="SELL", quantity=1.0)

        # Buy should fill near ask
        assert buy_fill >= 2.55

        # Sell should fill near bid
        assert sell_fill <= 2.45


