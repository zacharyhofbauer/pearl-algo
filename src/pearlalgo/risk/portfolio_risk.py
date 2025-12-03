"""
Portfolio Risk Aggregator.

Aggregates risk across futures, options, and other instruments at portfolio level.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from pearlalgo.core.portfolio import Portfolio
from pearlalgo.risk.futures_risk import FuturesRiskCalculator
from pearlalgo.risk.options_risk import OptionsRiskCalculator

logger = logging.getLogger(__name__)


class PortfolioRiskAggregator:
    """
    Portfolio-level risk aggregator.

    Combines futures and options risk to provide portfolio-wide metrics.
    """

    def __init__(
        self,
        futures_calculator: Optional[FuturesRiskCalculator] = None,
        options_calculator: Optional[OptionsRiskCalculator] = None,
    ):
        """Initialize portfolio risk aggregator."""
        self.futures_calculator = futures_calculator or FuturesRiskCalculator()
        self.options_calculator = options_calculator or OptionsRiskCalculator()

    def calculate_total_margin(
        self,
        portfolio: Portfolio,
        prices: Optional[Dict[str, float]] = None,
        options_data: Optional[Dict[str, Dict]] = None,
    ) -> Dict[str, float]:
        """
        Calculate total margin requirement for portfolio.

        Args:
            portfolio: Portfolio instance
            prices: Current prices for all positions
            options_data: Options-specific data (Greeks, underlying, etc.)

        Returns:
            Dict with total_margin, futures_margin, options_margin
        """
        prices = prices or {}
        options_data = options_data or {}

        futures_positions = {}
        options_positions = {}

        # Separate futures and options positions
        for symbol, position in portfolio.positions.items():
            if position.size == 0:
                continue

            # Simple heuristic: futures don't have underscores typically
            if "_" not in symbol or symbol.split("_")[0] in [
                "ES",
                "NQ",
                "MES",
                "MNQ",
                "CL",
                "GC",
            ]:
                futures_positions[symbol] = position.size
            else:
                options_positions[symbol] = position.size

        # Calculate futures margin
        futures_margin = 0.0
        if futures_positions:
            futures_margin_req = self.futures_calculator.calculate_portfolio_margin(
                positions=futures_positions, prices=prices
            )
            futures_margin = futures_margin_req["total_margin"]

        # Calculate options margin (simplified)
        options_margin = 0.0
        for symbol, quantity in options_positions.items():
            if symbol in options_data:
                opt_data = options_data[symbol]
                margin_req = self.options_calculator.calculate_margin_requirement(
                    option_type=opt_data.get("type", "call"),
                    strike=opt_data.get("strike", 0),
                    premium=opt_data.get("premium", 0),
                    quantity=quantity,
                    underlying_price=prices.get(opt_data.get("underlying")),
                    is_long=quantity > 0,
                )
                options_margin += margin_req["total_required"]

        total_margin = futures_margin + options_margin

        return {
            "total_margin": total_margin,
            "futures_margin": futures_margin,
            "options_margin": options_margin,
            "available_margin": max(0.0, portfolio.cash - total_margin),
        }

    def calculate_portfolio_risk_metrics(
        self,
        portfolio: Portfolio,
        prices: Optional[Dict[str, float]] = None,
        options_data: Optional[Dict[str, Dict]] = None,
    ) -> Dict[str, float]:
        """
        Calculate comprehensive portfolio risk metrics.

        Args:
            portfolio: Portfolio instance
            prices: Current prices
            options_data: Options-specific data

        Returns:
            Dict with various risk metrics
        """
        prices = prices or {}

        # Calculate unrealized PnL
        unrealized_pnl = 0.0
        for symbol, position in portfolio.positions.items():
            if position.size == 0:
                continue

            if symbol in prices:
                price_diff = prices[symbol] - position.avg_price
                unrealized_pnl += price_diff * position.size

        # Calculate realized PnL
        realized_pnl = sum(p.realized_pnl for p in portfolio.positions.values())

        # Calculate total equity
        total_equity = portfolio.cash + unrealized_pnl + realized_pnl

        # Calculate margin usage
        margin_req = self.calculate_total_margin(
            portfolio=portfolio, prices=prices, options_data=options_data
        )

        margin_usage_pct = (
            (margin_req["total_margin"] / total_equity * 100)
            if total_equity > 0
            else 0.0
        )

        # Calculate position concentration (max single position as % of equity)
        max_position_value = 0.0
        for symbol, position in portfolio.positions.items():
            if position.size == 0:
                continue
            if symbol in prices:
                position_value = abs(position.size * prices[symbol])
                max_position_value = max(max_position_value, position_value)

        concentration_pct = (
            (max_position_value / total_equity * 100) if total_equity > 0 else 0.0
        )

        return {
            "total_equity": total_equity,
            "cash": portfolio.cash,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_margin": margin_req["total_margin"],
            "margin_usage_pct": margin_usage_pct,
            "available_margin": margin_req["available_margin"],
            "max_position_concentration_pct": concentration_pct,
            "num_positions": sum(
                1 for p in portfolio.positions.values() if p.size != 0
            ),
        }


