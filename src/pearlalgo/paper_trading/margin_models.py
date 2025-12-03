"""
Margin Models for Paper Trading Simulation.

Implements SPAN-like margin for futures and rule-based margin for options.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class MarginRequirements:
    """Margin requirements for a position."""

    initial_margin: float
    maintenance_margin: float
    total_required: float  # Current margin requirement


class FuturesMarginModel:
    """
    SPAN-like margin model for futures contracts.

    Uses simplified margin requirements based on exchange specifications.
    """

    # Simplified CME margin requirements (typical values, can be customized)
    FUTURES_MARGIN_TABLE: Dict[str, Dict[str, float]] = {
        "ES": {"initial": 13200.0, "maintenance": 12000.0},  # E-mini S&P 500
        "NQ": {"initial": 18620.0, "maintenance": 16900.0},  # E-mini NASDAQ
        "MES": {"initial": 1320.0, "maintenance": 1200.0},  # Micro E-mini S&P
        "MNQ": {"initial": 1862.0, "maintenance": 1690.0},  # Micro E-mini NASDAQ
        "CL": {"initial": 5500.0, "maintenance": 5000.0},  # Crude Oil
        "GC": {"initial": 7700.0, "maintenance": 7000.0},  # Gold
    }

    def __init__(self, custom_margins: Optional[Dict[str, Dict[str, float]]] = None):
        """
        Initialize futures margin model.

        Args:
            custom_margins: Custom margin requirements (optional)
        """
        self.margin_table = self.FUTURES_MARGIN_TABLE.copy()
        if custom_margins:
            self.margin_table.update(custom_margins)

    def get_margin_requirements(
        self, symbol: str, quantity: float, price: Optional[float] = None
    ) -> MarginRequirements:
        """
        Get margin requirements for a futures position.

        Args:
            symbol: Futures symbol (e.g., "ES", "NQ")
            quantity: Position quantity (absolute value)
            price: Current price (optional, for price-based margin)

        Returns:
            MarginRequirements object
        """
        # Look up symbol in margin table
        symbol_base = symbol.split("_")[0].upper()  # Handle contract specs
        margins = self.margin_table.get(symbol_base)

        if not margins:
            # Default margins if not found
            logger.warning(
                f"No margin data for {symbol}, using default margins"
            )
            initial = 10000.0
            maintenance = 9000.0
        else:
            initial = margins["initial"]
            maintenance = margins["maintenance"]

        # Scale by quantity (absolute)
        position_size = abs(quantity)

        total_initial = initial * position_size
        total_maintenance = maintenance * position_size

        return MarginRequirements(
            initial_margin=total_initial,
            maintenance_margin=total_maintenance,
            total_required=total_initial,
        )

    def check_margin_call(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
        avg_entry_price: float,
        account_equity: float,
    ) -> tuple[bool, float]:
        """
        Check if margin call is triggered.

        Args:
            symbol: Futures symbol
            quantity: Position quantity
            current_price: Current market price
            avg_entry_price: Average entry price
            account_equity: Current account equity

        Returns:
            Tuple of (is_margin_call, required_additional_margin)
        """
        if quantity == 0:
            return False, 0.0

        # Calculate unrealized PnL
        price_diff = current_price - avg_entry_price
        unrealized_pnl = price_diff * quantity * self._get_contract_multiplier(symbol)

        # Current equity including unrealized PnL
        current_equity = account_equity + unrealized_pnl

        # Get maintenance margin requirement
        margin_req = self.get_margin_requirements(symbol, abs(quantity))
        maintenance_margin = margin_req.maintenance_margin

        # Margin call if equity < maintenance margin
        if current_equity < maintenance_margin:
            required_additional = maintenance_margin - current_equity
            return True, required_additional

        return False, 0.0

    def _get_contract_multiplier(self, symbol: str) -> float:
        """Get contract multiplier for symbol."""
        multipliers = {
            "ES": 50.0,
            "NQ": 20.0,
            "MES": 5.0,
            "MNQ": 2.0,
            "CL": 1000.0,
            "GC": 100.0,
        }
        symbol_base = symbol.split("_")[0].upper()
        return multipliers.get(symbol_base, 50.0)


class OptionsMarginModel:
    """
    Rule-based margin model for options.

    Simplified margin calculations sufficient for small-scale paper trading.
    """

    def get_margin_requirements(
        self,
        option_type: str,  # "call" or "put"
        strike: float,
        premium: float,
        quantity: float,
        underlying_price: Optional[float] = None,
        is_long: bool = True,
    ) -> MarginRequirements:
        """
        Get margin requirements for an options position.

        Args:
            option_type: "call" or "put"
            strike: Strike price
            premium: Option premium
            quantity: Position quantity (absolute)
            underlying_price: Current underlying price (optional)
            is_long: True for long position, False for short

        Returns:
            MarginRequirements object
        """
        position_size = abs(quantity)

        if is_long:
            # Long options: full premium cost
            margin_required = premium * position_size
            return MarginRequirements(
                initial_margin=margin_required,
                maintenance_margin=margin_required,
                total_required=margin_required,
            )
        else:
            # Short options: margin required based on type
            if underlying_price is None:
                underlying_price = strike  # Fallback

            if option_type.lower() == "call":
                # Short call: higher of (strike - underlying + premium) or (premium + 20% underlying)
                margin1 = (strike - underlying_price) * position_size + (
                    premium * position_size
                )
                margin2 = (premium * position_size) + (underlying_price * 0.2 * position_size)
                margin_required = max(margin1, margin2, premium * position_size)
            else:  # put
                # Short put: higher of (underlying - strike + premium) or (premium + 20% underlying)
                margin1 = (underlying_price - strike) * position_size + (
                    premium * position_size
                )
                margin2 = (premium * position_size) + (underlying_price * 0.2 * position_size)
                margin_required = max(margin1, margin2, premium * position_size)

            # Maintenance margin is typically 75-90% of initial
            maintenance_margin = margin_required * 0.85

            return MarginRequirements(
                initial_margin=margin_required,
                maintenance_margin=maintenance_margin,
                total_required=margin_required,
            )

    def get_spread_margin(
        self,
        long_premium: float,
        short_premium: float,
        quantity: float,
        max_loss: float,
    ) -> MarginRequirements:
        """
        Get margin requirements for an options spread.

        Args:
            long_premium: Premium paid for long leg
            short_premium: Premium received for short leg
            quantity: Position quantity (absolute)
            max_loss: Maximum potential loss

        Returns:
            MarginRequirements object
        """
        position_size = abs(quantity)
        net_premium_paid = (long_premium - short_premium) * position_size

        # Margin is max loss minus premium received
        margin_required = max_loss * position_size - (short_premium * position_size)

        return MarginRequirements(
            initial_margin=margin_required,
            maintenance_margin=margin_required * 0.85,
            total_required=margin_required,
        )


