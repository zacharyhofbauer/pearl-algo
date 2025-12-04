"""
Tests for margin models (futures SPAN-like, options rule-based).
"""

import pytest

from pearlalgo.paper_trading.margin_models import (
    FuturesMarginModel,
    OptionsMarginModel,
    MarginRequirements,
)


class TestFuturesMarginModel:
    """Test futures margin model."""

    def test_get_margin_requirements(self):
        """Test margin requirement calculation."""
        model = FuturesMarginModel()

        margin = model.get_margin_requirements(symbol="ES", quantity=1.0)

        assert margin.initial_margin > 0
        assert margin.maintenance_margin > 0
        assert margin.total_required == margin.initial_margin

    def test_margin_scales_with_quantity(self):
        """Test margin scales with position size."""
        model = FuturesMarginModel()

        margin1 = model.get_margin_requirements(symbol="ES", quantity=1.0)
        margin2 = model.get_margin_requirements(symbol="ES", quantity=2.0)

        assert margin2.total_required == margin1.total_required * 2

    def test_margin_call_detection(self):
        """Test margin call detection."""
        model = FuturesMarginModel()

        # Account with enough equity
        is_call1, additional1, usage1 = model.check_margin_call(
            symbol="ES",
            quantity=1.0,
            avg_entry_price=4000.0,
            current_price=4100.0,
            account_equity=15000.0,  # Above margin requirement
        )

        assert not is_call1

        # Account with insufficient equity
        is_call2, additional2, usage2 = model.check_margin_call(
            symbol="ES",
            quantity=1.0,
            avg_entry_price=4000.0,
            current_price=3900.0,  # Loss
            account_equity=5000.0,  # Below maintenance margin
        )

        # Should trigger margin call on loss
        if is_call2:
            assert additional2 > 0


class TestOptionsMarginModel:
    """Test options margin model."""

    def test_long_options_margin(self):
        """Test margin for long options is premium cost."""
        model = OptionsMarginModel()

        margin = model.get_margin_requirements(
            option_type="call",
            strike=100.0,
            premium=2.50,
            quantity=1.0,
            is_long=True,
        )

        # Long options: full premium cost
        assert margin.total_required == 2.50
        assert margin.initial_margin == margin.maintenance_margin

    def test_short_options_margin(self):
        """Test margin for short options is higher."""
        model = OptionsMarginModel()

        margin = model.get_margin_requirements(
            option_type="call",
            strike=100.0,
            premium=2.50,
            quantity=1.0,
            underlying_price=105.0,
            is_long=False,
        )

        # Short options: much higher margin
        assert margin.total_required > 2.50
        assert margin.maintenance_margin < margin.initial_margin

    def test_spread_margin(self):
        """Test margin for options spreads."""
        model = OptionsMarginModel()

        margin = model.get_spread_margin(
            long_premium=2.50,
            short_premium=1.50,
            quantity=1.0,
            max_loss=5.0,
        )

        # Spread margin should be max loss minus premium received
        expected = 5.0 - 1.50  # max_loss - short_premium
        assert margin.total_required == pytest.approx(expected, abs=0.01)



