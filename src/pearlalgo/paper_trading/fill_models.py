"""
Fill Models for Realistic Trade Execution Simulation.

Implements slippage, execution delays, and partial fills for
realistic paper trading.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FillModelConfig:
    """Configuration for fill models."""

    # Slippage settings
    slippage_bps: float = 2.0  # Basis points (0.02% default)
    fixed_slippage: float = 0.0  # Fixed slippage in price units

    # Execution delay
    execution_delay_ms: int = 100  # Milliseconds

    # Partial fills
    enable_partial_fills: bool = False
    partial_fill_probability: float = 0.1  # 10% chance

    # Deterministic mode (for backtesting)
    deterministic: bool = False
    random_seed: Optional[int] = None


class FillModel:
    """
    Base fill model for realistic trade execution.

    Models slippage, execution delays, and optional partial fills.
    """

    def __init__(self, config: Optional[FillModelConfig] = None):
        """
        Initialize fill model.

        Args:
            config: Fill model configuration
        """
        self.config = config or FillModelConfig()
        if self.config.deterministic and self.config.random_seed is not None:
            random.seed(self.config.random_seed)

    def calculate_slippage(
        self, price: float, side: str, quantity: float
    ) -> float:
        """
        Calculate slippage-adjusted fill price.

        Args:
            price: Market price (mid-price)
            side: "BUY" or "SELL"
            quantity: Order quantity

        Returns:
            Fill price with slippage applied
        """
        # Basis points slippage
        bps_slippage = self.config.slippage_bps / 10000.0
        slippage_amount = price * bps_slippage

        # Fixed slippage
        total_slippage = slippage_amount + self.config.fixed_slippage

        # Direction matters: buy pays more (add slippage), sell receives less (subtract)
        if side.upper() == "BUY":
            fill_price = price + total_slippage
        else:  # SELL
            fill_price = price - total_slippage

        return max(0.0, fill_price)  # Ensure non-negative

    def calculate_execution_delay(self) -> timedelta:
        """
        Calculate execution delay.

        Returns:
            Timedelta representing execution delay
        """
        if self.config.deterministic:
            # Fixed delay in deterministic mode
            delay_ms = self.config.execution_delay_ms
        else:
            # Random delay around configured value (±20%)
            delay_ms = random.randint(
                int(self.config.execution_delay_ms * 0.8),
                int(self.config.execution_delay_ms * 1.2),
            )

        return timedelta(milliseconds=delay_ms)

    def should_partial_fill(self, quantity: float) -> tuple[bool, float]:
        """
        Determine if order should be partially filled.

        Args:
            quantity: Order quantity

        Returns:
            Tuple of (should_partial_fill, partial_quantity)
        """
        if not self.config.enable_partial_fills:
            return False, quantity

        if self.config.deterministic:
            # Deterministic: use quantity to determine
            should_partial = (int(quantity) % 3) == 0  # Every 3rd order
        else:
            # Random chance
            should_partial = random.random() < self.config.partial_fill_probability

        if not should_partial:
            return False, quantity

        # Calculate partial fill (50-80% of order)
        if self.config.deterministic:
            partial_pct = 0.65  # Fixed percentage
        else:
            partial_pct = random.uniform(0.5, 0.8)

        partial_qty = quantity * partial_pct

        return True, partial_qty

    def apply_fill(
        self,
        price: float,
        side: str,
        quantity: float,
        timestamp: datetime,
    ) -> tuple[float, float, datetime]:
        """
        Apply fill model to an order.

        Args:
            price: Market price
            side: "BUY" or "SELL"
            quantity: Order quantity
            timestamp: Order timestamp

        Returns:
            Tuple of (fill_price, fill_quantity, fill_timestamp)
        """
        # Calculate slippage
        fill_price = self.calculate_slippage(price, side, quantity)

        # Check for partial fill
        is_partial, fill_quantity = self.should_partial_fill(quantity)

        # Calculate execution delay
        delay = self.calculate_execution_delay()
        fill_timestamp = timestamp + delay

        if is_partial:
            logger.debug(
                f"Partial fill: {fill_quantity:.2f} of {quantity} at {fill_price:.4f}"
            )

        return fill_price, fill_quantity, fill_timestamp


class FuturesFillModel(FillModel):
    """
    Futures-specific fill model.

    Uses ATR-based slippage for more realistic futures fills.
    """

    def __init__(
        self,
        config: Optional[FillModelConfig] = None,
        atr: Optional[float] = None,
    ):
        """
        Initialize futures fill model.

        Args:
            config: Fill model configuration
            atr: Average True Range for slippage calculation
        """
        super().__init__(config)
        self.atr = atr or 0.0

    def calculate_slippage(
        self, price: float, side: str, quantity: float
    ) -> float:
        """
        Calculate ATR-based slippage for futures.

        Args:
            price: Market price
            side: "BUY" or "SELL"
            quantity: Order quantity

        Returns:
            Fill price with slippage
        """
        # Use ATR for slippage if available (0.5-2 bps of ATR)
        if self.atr > 0:
            atr_slippage = self.atr * (self.config.slippage_bps / 10000.0)
        else:
            atr_slippage = price * (self.config.slippage_bps / 10000.0)

        total_slippage = atr_slippage + self.config.fixed_slippage

        if side.upper() == "BUY":
            fill_price = price + total_slippage
        else:
            fill_price = price - total_slippage

        return max(0.0, fill_price)


class OptionsFillModel(FillModel):
    """
    Options-specific fill model.

    Uses bid-ask spread for more realistic options fills.
    """

    def __init__(
        self,
        config: Optional[FillModelConfig] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
    ):
        """
        Initialize options fill model.

        Args:
            config: Fill model configuration
            bid: Current bid price
            ask: Current ask price
        """
        super().__init__(config)
        self.bid = bid
        self.ask = ask

    def calculate_slippage(
        self, price: float, side: str, quantity: float
    ) -> float:
        """
        Calculate bid-ask spread based slippage for options.

        Args:
            price: Mid-price
            side: "BUY" or "SELL"
            quantity: Order quantity

        Returns:
            Fill price with spread slippage
        """
        if self.bid is not None and self.ask is not None:
            spread = self.ask - self.bid
            mid_price = (self.bid + self.ask) / 2.0

            # Fill at bid (sell) or ask (buy) plus additional slippage
            if side.upper() == "BUY":
                fill_price = self.ask + (spread * 0.1)  # Slight additional slippage
            else:  # SELL
                fill_price = self.bid - (spread * 0.1)

            # Apply additional config slippage
            additional_slippage = price * (self.config.slippage_bps / 10000.0)
            if side.upper() == "BUY":
                fill_price += additional_slippage
            else:
                fill_price -= additional_slippage

            return max(0.0, fill_price)

        # Fallback to base model if bid/ask not available
        return super().calculate_slippage(price, side, quantity)

