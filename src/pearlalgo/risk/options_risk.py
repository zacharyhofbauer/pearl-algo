"""
Options Risk Calculator.

Greeks-based risk calculations for options positions.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from pearlalgo.paper_trading.margin_models import OptionsMarginModel

logger = logging.getLogger(__name__)


class OptionsRiskCalculator:
    """
    Options risk calculator using Greeks and margin models.

    Calculates:
    - Delta exposure
    - Greeks-based risk metrics
    - Margin requirements
    - Portfolio-level options risk
    """

    def __init__(self, margin_model: Optional[OptionsMarginModel] = None):
        """Initialize options risk calculator."""
        self.margin_model = margin_model or OptionsMarginModel()

    def calculate_delta_exposure(
        self,
        position_quantity: float,
        option_delta: float,
        underlying_price: float,
    ) -> float:
        """
        Calculate delta exposure (equivalent shares).

        Args:
            position_quantity: Option position quantity
            option_delta: Option delta
            underlying_price: Current underlying price

        Returns:
            Delta exposure in dollars
        """
        # Delta exposure = quantity * delta * underlying_price * multiplier
        # For options, multiplier is typically 100
        multiplier = 100.0  # Standard options multiplier
        delta_exposure = position_quantity * option_delta * underlying_price * multiplier
        return delta_exposure

    def calculate_portfolio_delta(
        self,
        positions: Dict[str, Dict],
        underlying_prices: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Calculate portfolio-level delta exposure.

        Args:
            positions: Dict of symbol -> {quantity, delta, ...}
            underlying_prices: Dict of underlying symbol -> price

        Returns:
            Dict with total_delta, per_underlying_delta
        """
        total_delta = 0.0
        per_underlying = {}

        for symbol, pos_data in positions.items():
            quantity = pos_data.get("quantity", 0)
            delta = pos_data.get("delta", 0)
            underlying_symbol = pos_data.get("underlying", symbol)

            underlying_price = underlying_prices.get(underlying_symbol, 0.0)
            delta_exposure = self.calculate_delta_exposure(
                position_quantity=quantity,
                option_delta=delta,
                underlying_price=underlying_price,
            )

            total_delta += delta_exposure

            if underlying_symbol not in per_underlying:
                per_underlying[underlying_symbol] = 0.0
            per_underlying[underlying_symbol] += delta_exposure

        return {
            "total_delta": total_delta,
            "per_underlying_delta": per_underlying,
        }

    def calculate_margin_requirement(
        self,
        option_type: str,
        strike: float,
        premium: float,
        quantity: float,
        underlying_price: Optional[float] = None,
        is_long: bool = True,
    ) -> Dict[str, float]:
        """
        Calculate margin requirement for an options position.

        Args:
            option_type: "call" or "put"
            strike: Strike price
            premium: Option premium
            quantity: Position quantity
            underlying_price: Current underlying price
            is_long: True for long position

        Returns:
            Dict with initial_margin, maintenance_margin, total_required
        """
        margin_req = self.margin_model.get_margin_requirements(
            option_type=option_type,
            strike=strike,
            premium=premium,
            quantity=abs(quantity),
            underlying_price=underlying_price,
            is_long=is_long,
        )

        return {
            "initial_margin": margin_req.initial_margin,
            "maintenance_margin": margin_req.maintenance_margin,
            "total_required": margin_req.total_required,
        }

    def calculate_greeks_risk(
        self,
        position_quantity: float,
        greeks: Dict[str, float],
        underlying_price: float,
        price_move: float = 0.01,  # 1% move
    ) -> Dict[str, float]:
        """
        Calculate risk from Greeks for a price move.

        Args:
            position_quantity: Option position quantity
            greeks: Dict with delta, gamma, theta, vega, rho
            underlying_price: Current underlying price
            price_move: Expected price move (as decimal, e.g., 0.01 for 1%)

        Returns:
            Dict with risk metrics
        """
        multiplier = 100.0  # Standard options multiplier

        delta = greeks.get("delta", 0.0)
        gamma = greeks.get("gamma", 0.0)
        theta = greeks.get("theta", 0.0)
        vega = greeks.get("vega", 0.0)

        # Delta risk (linear approximation)
        delta_pnl = position_quantity * delta * underlying_price * price_move * multiplier

        # Gamma risk (second-order)
        gamma_pnl = (
            0.5
            * position_quantity
            * gamma
            * (underlying_price * price_move) ** 2
            * multiplier
        )

        # Theta decay (per day, negative for long options)
        theta_pnl = position_quantity * theta * multiplier

        # Vega risk (volatility move)
        vol_move = 0.01  # 1% volatility move
        vega_pnl = position_quantity * vega * vol_move * multiplier

        return {
            "delta_pnl": delta_pnl,
            "gamma_pnl": gamma_pnl,
            "theta_pnl": theta_pnl,
            "vega_pnl": vega_pnl,
            "total_pnl_estimate": delta_pnl + gamma_pnl + theta_pnl + vega_pnl,
        }


