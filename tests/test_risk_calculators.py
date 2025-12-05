"""
Tests for risk calculators (futures, options, portfolio).
"""

import pytest

from pearlalgo.risk.futures_risk import FuturesRiskCalculator
from pearlalgo.risk.options_risk import OptionsRiskCalculator
from pearlalgo.risk.portfolio_risk import PortfolioRiskAggregator
from pearlalgo.core.portfolio import Portfolio


class TestFuturesRiskCalculator:
    """Test futures risk calculator."""

    def test_calculate_margin_requirement(self):
        """Test margin requirement calculation."""
        calculator = FuturesRiskCalculator()

        margin = calculator.calculate_margin_requirement(
            symbol="ES", quantity=1.0
        )

        assert margin["initial_margin"] > 0
        assert margin["maintenance_margin"] > 0
        assert margin["total_required"] > 0

    def test_calculate_portfolio_margin(self):
        """Test portfolio margin calculation."""
        calculator = FuturesRiskCalculator()

        positions = {"ES": 1.0, "NQ": 1.0}
        margin_req = calculator.calculate_portfolio_margin(positions=positions)

        assert margin_req["total_margin"] > 0
        assert "ES" in margin_req["per_symbol_margins"]
        assert "NQ" in margin_req["per_symbol_margins"]

    def test_calculate_max_position_size(self):
        """Test maximum position size calculation."""
        calculator = FuturesRiskCalculator()

        max_size = calculator.calculate_max_position_size(
            symbol="ES", available_margin=50000.0
        )

        assert max_size > 0


class TestOptionsRiskCalculator:
    """Test options risk calculator."""

    def test_calculate_delta_exposure(self):
        """Test delta exposure calculation."""
        calculator = OptionsRiskCalculator()

        exposure = calculator.calculate_delta_exposure(
            position_quantity=1.0,
            option_delta=0.5,
            underlying_price=400.0,
        )

        # Delta exposure = quantity * delta * underlying_price * 100
        expected = 1.0 * 0.5 * 400.0 * 100
        assert exposure == pytest.approx(expected, abs=0.01)

    def test_calculate_greeks_risk(self):
        """Test Greeks-based risk calculation."""
        calculator = OptionsRiskCalculator()

        greeks = {
            "delta": 0.5,
            "gamma": 0.1,
            "theta": -0.05,
            "vega": 0.2,
            "rho": 0.01,
        }

        risk = calculator.calculate_greeks_risk(
            position_quantity=1.0,
            greeks=greeks,
            underlying_price=400.0,
            price_move=0.01,  # 1% move
        )

        assert "delta_pnl" in risk
        assert "gamma_pnl" in risk
        assert "theta_pnl" in risk
        assert "vega_pnl" in risk


class TestPortfolioRiskAggregator:
    """Test portfolio risk aggregator."""

    def test_calculate_total_margin(self):
        """Test total margin calculation."""
        portfolio = Portfolio(cash=50000.0)
        aggregator = PortfolioRiskAggregator()

        # Add a position (would need to actually add via fills)
        margin_req = aggregator.calculate_total_margin(
            portfolio=portfolio, prices={"ES": 4000.0}
        )

        assert "total_margin" in margin_req
        assert "futures_margin" in margin_req
        assert "options_margin" in margin_req
        assert "available_margin" in margin_req

    def test_calculate_portfolio_risk_metrics(self):
        """Test portfolio risk metrics calculation."""
        portfolio = Portfolio(cash=50000.0)
        aggregator = PortfolioRiskAggregator()

        metrics = aggregator.calculate_portfolio_risk_metrics(
            portfolio=portfolio, prices={}
        )

        assert "total_equity" in metrics
        assert "cash" in metrics
        assert "margin_usage_pct" in metrics
        assert "num_positions" in metrics





