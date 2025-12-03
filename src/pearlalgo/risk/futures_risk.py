"""
Futures Risk Calculator.

SPAN-like risk calculations for futures positions.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from pearlalgo.paper_trading.margin_models import FuturesMarginModel

logger = logging.getLogger(__name__)


class FuturesRiskCalculator:
    """
    Futures risk calculator with SPAN-like methodology.

    Calculates:
    - Initial margin requirements
    - Maintenance margin requirements
    - Margin calls
    - Risk-adjusted position sizing
    """

    def __init__(self, margin_model: Optional[FuturesMarginModel] = None):
        """Initialize futures risk calculator."""
        self.margin_model = margin_model or FuturesMarginModel()

    def calculate_margin_requirement(
        self, symbol: str, quantity: float, price: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Calculate margin requirement for a futures position.

        Args:
            symbol: Futures symbol
            quantity: Position quantity
            price: Current price (optional)

        Returns:
            Dict with initial_margin, maintenance_margin, total_required
        """
        margin_req = self.margin_model.get_margin_requirements(
            symbol=symbol, quantity=abs(quantity), price=price
        )

        return {
            "initial_margin": margin_req.initial_margin,
            "maintenance_margin": margin_req.maintenance_margin,
            "total_required": margin_req.total_required,
        }

    def calculate_portfolio_margin(
        self, positions: Dict[str, float], prices: Optional[Dict[str, float]] = None
    ) -> Dict[str, float]:
        """
        Calculate total margin requirement for multiple positions.

        Args:
            positions: Dict of symbol -> quantity
            prices: Current prices (optional)

        Returns:
            Dict with total_margin, per_symbol_margins
        """
        total_margin = 0.0
        per_symbol = {}

        for symbol, quantity in positions.items():
            price = prices.get(symbol) if prices else None
            margin_req = self.calculate_margin_requirement(
                symbol=symbol, quantity=quantity, price=price
            )
            total_margin += margin_req["total_required"]
            per_symbol[symbol] = margin_req

        return {
            "total_margin": total_margin,
            "per_symbol_margins": per_symbol,
        }

    def check_margin_call(
        self,
        symbol: str,
        quantity: float,
        avg_entry_price: float,
        current_price: float,
        account_equity: float,
    ) -> tuple[bool, float, float]:
        """
        Check if margin call is triggered.

        Args:
            symbol: Futures symbol
            quantity: Position quantity
            avg_entry_price: Average entry price
            current_price: Current market price
            account_equity: Current account equity

        Returns:
            Tuple of (is_margin_call, required_margin, current_margin_usage)
        """
        is_call, additional_margin = self.margin_model.check_margin_call(
            symbol=symbol,
            quantity=quantity,
            current_price=current_price,
            avg_entry_price=avg_entry_price,
            account_equity=account_equity,
        )

        margin_req = self.margin_model.get_margin_requirements(
            symbol=symbol, quantity=abs(quantity), price=current_price
        )

        current_usage = margin_req.total_required / account_equity if account_equity > 0 else 0.0

        return is_call, additional_margin, current_usage

    def calculate_max_position_size(
        self,
        symbol: str,
        available_margin: float,
        price: Optional[float] = None,
    ) -> float:
        """
        Calculate maximum position size given available margin.

        Args:
            symbol: Futures symbol
            available_margin: Available margin/capital
            price: Current price (optional)

        Returns:
            Maximum position size (quantity)
        """
        # Get margin requirement for 1 contract
        margin_req = self.margin_model.get_margin_requirements(
            symbol=symbol, quantity=1.0, price=price
        )

        if margin_req.total_required <= 0:
            return 0.0

        max_size = available_margin / margin_req.total_required
        return max_size


