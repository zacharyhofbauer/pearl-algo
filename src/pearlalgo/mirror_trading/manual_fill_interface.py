"""
Manual Fill Interface for Mirror Trading.

Allows manual entry of fills from prop firm execution to sync with internal simulation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from pearlalgo.core.events import FillEvent
from pearlalgo.core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class ManualFillInterface:
    """
    Interface for manual fill entry in mirror trading scenario.

    Allows users to:
    1. Enter actual fill prices/sizes from prop firm
    2. Override simulated fills
    3. Reconcile PnL between internal and external
    """

    def __init__(self, portfolio: Portfolio):
        """
        Initialize manual fill interface.

        Args:
            portfolio: Portfolio instance to update
        """
        self.portfolio = portfolio
        self.manual_fills: list[FillEvent] = []

    def enter_fill(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        timestamp: Optional[datetime] = None,
        commission: float = 0.0,
        override_simulated: bool = False,
    ) -> FillEvent:
        """
        Enter a manual fill from prop firm execution.

        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            quantity: Fill quantity
            price: Fill price
            timestamp: Fill timestamp (default: now)
            commission: Commission paid
            override_simulated: Whether to override any simulated fill

        Returns:
            Created FillEvent
        """
        if timestamp is None:
            timestamp = datetime.now()

        # Validate fill
        if not self._validate_fill(symbol, side, quantity, price):
            raise ValueError(f"Invalid fill: {symbol} {side} {quantity} @ {price}")

        fill = FillEvent(
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            commission=commission,
            metadata={"source": "manual", "override": override_simulated},
        )

        # Update portfolio
        self.portfolio.update_with_fill(fill)
        self.manual_fills.append(fill)

        logger.info(
            f"Manual fill entered: {fill.side} {fill.quantity} {fill.symbol} @ {fill.price:.4f}"
        )

        return fill

    def _validate_fill(
        self, symbol: str, side: str, quantity: float, price: float
    ) -> bool:
        """
        Validate fill reasonableness.

        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            quantity: Fill quantity
            price: Fill price

        Returns:
            True if fill appears valid
        """
        if quantity <= 0:
            logger.warning(f"Invalid quantity: {quantity}")
            return False

        if price <= 0:
            logger.warning(f"Invalid price: {price}")
            return False

        if side.upper() not in ["BUY", "SELL"]:
            logger.warning(f"Invalid side: {side}")
            return False

        # Additional validation could check:
        # - Price is within reasonable range (e.g., not 10x market price)
        # - Quantity is reasonable
        # - Symbol is valid

        return True

    def get_manual_fills(self, since: Optional[datetime] = None) -> list[FillEvent]:
        """Get all manual fills since a timestamp."""
        if since is None:
            return self.manual_fills.copy()

        return [f for f in self.manual_fills if f.timestamp >= since]



