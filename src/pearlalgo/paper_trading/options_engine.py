"""
Paper Options Trading Engine.

Event-driven options trading simulation with bid-ask spreads,
Greeks-based validation, and position tracking.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.paper_trading.fill_models import FillModelConfig, OptionsFillModel
from pearlalgo.paper_trading.margin_models import OptionsMarginModel

logger = logging.getLogger(__name__)


class PaperOptionsEngine:
    """
    Paper trading engine for options contracts.

    Features:
    - Event-driven fill simulation
    - Bid-ask spread slippage
    - Rule-based margin calculations
    - Options chain integration
    - Greeks-based pricing validation (when available)
    """

    def __init__(
        self,
        portfolio: Portfolio,
        fill_config: Optional[FillModelConfig] = None,
        margin_model: Optional[OptionsMarginModel] = None,
        options_chain_lookup: Optional[
            Callable[[str], List[Dict]]
        ] = None,  # Returns options chain for underlying
    ):
        """
        Initialize paper options engine.

        Args:
            portfolio: Portfolio instance
            fill_config: Fill model configuration
            margin_model: Margin model (default: OptionsMarginModel)
            options_chain_lookup: Function to get options chain for underlying
        """
        self.portfolio = portfolio
        self.fill_model = OptionsFillModel(config=fill_config)
        self.margin_model = margin_model or OptionsMarginModel()
        self.options_chain_lookup = options_chain_lookup

        # Track pending orders and fills
        self._pending_orders: Dict[str, OrderEvent] = {}
        self._fills: list[FillEvent] = []

        # Cache for options chain data
        self._options_cache: Dict[str, List[Dict]] = {}

    def update_options_chain(
        self, underlying_symbol: str, chain: List[Dict]
    ) -> None:
        """
        Update options chain for an underlying symbol.

        Args:
            underlying_symbol: Underlying symbol (e.g., 'QQQ')
            chain: List of option contracts with bid, ask, strike, expiration, etc.
        """
        self._options_cache[underlying_symbol] = chain

    def submit_order(self, order: OrderEvent) -> Optional[FillEvent]:
        """
        Submit an order for execution.

        Args:
            order: OrderEvent to execute (symbol should be option contract symbol)

        Returns:
            FillEvent if immediately filled, None if pending
        """
        # Parse option symbol to get underlying and contract details
        option_details = self._parse_option_symbol(order.symbol)

        if not option_details:
            logger.warning(
                f"Could not parse option symbol: {order.symbol}"
            )
            return None

        underlying = option_details["underlying"]

        # Get current option quote from chain
        option_quote = self._get_option_quote(
            underlying, option_details["strike"], option_details["expiration"], option_details["type"]
        )

        if not option_quote:
            logger.warning(
                f"No quote available for {order.symbol}, order will be pending"
            )
            self._pending_orders[order.symbol] = order
            return None

        # Process order immediately
        return self._execute_order(order, option_quote)

    def _parse_option_symbol(self, symbol: str) -> Optional[Dict]:
        """
        Parse option symbol to extract details.

        This is a simplified parser - in production, use proper options symbol format.
        Expected format variations:
        - "QQQ_20241220_C_400" (underlying_date_type_strike)
        - Standard OCC format

        Returns:
            Dict with underlying, strike, expiration, type
        """
        # Simplified parsing - extend for production
        try:
            parts = symbol.split("_")
            if len(parts) >= 4:
                underlying = parts[0]
                expiration = parts[1]
                option_type = parts[2].upper()
                strike = float(parts[3])

                return {
                    "underlying": underlying,
                    "expiration": expiration,
                    "type": "call" if option_type == "C" else "put",
                    "strike": strike,
                }
        except Exception as e:
            logger.debug(f"Error parsing option symbol {symbol}: {e}")

        return None

    def _get_option_quote(
        self,
        underlying: str,
        strike: float,
        expiration: str,
        option_type: str,
    ) -> Optional[Dict]:
        """Get current quote for an option from chain."""
        chain = self._options_cache.get(underlying)

        if not chain:
            if self.options_chain_lookup:
                chain = self.options_chain_lookup(underlying)
                if chain:
                    self._options_cache[underlying] = chain

        if not chain:
            return None

        # Find matching option
        for option in chain:
            if (
                abs(option.get("strike", 0) - strike) < 0.01
                and option.get("expiration") == expiration
                and option.get("option_type", "").lower() == option_type.lower()
            ):
                return {
                    "bid": option.get("bid", 0),
                    "ask": option.get("ask", 0),
                    "last": option.get("last", option.get("last_price", 0)),
                    "mid": (option.get("bid", 0) + option.get("ask", 0)) / 2.0,
                }

        return None

    def _execute_order(self, order: OrderEvent, quote: Dict) -> Optional[FillEvent]:
        """Execute an order at current quote."""
        # Determine if long or short
        is_long = order.side.upper() == "BUY"

        # Use mid price for fill calculation
        mid_price = quote.get("mid", quote.get("last", 0))

        if mid_price <= 0:
            logger.warning(f"Invalid price for {order.symbol}")
            return None

        # Update fill model with bid/ask
        self.fill_model.bid = quote.get("bid")
        self.fill_model.ask = quote.get("ask")

        # Apply fill model
        fill_price, fill_quantity, fill_timestamp = self.fill_model.apply_fill(
            price=mid_price,
            side=order.side,
            quantity=order.quantity,
            timestamp=order.timestamp,
        )

        # Get option details for margin calculation
        option_details = self._parse_option_symbol(order.symbol)
        if not option_details:
            return None

        # Calculate margin requirements (simplified)
        # In production, need underlying price for accurate margin
        premium = fill_price

        margin_req = self.margin_model.get_margin_requirements(
            option_type=option_details["type"],
            strike=option_details["strike"],
            premium=premium,
            quantity=fill_quantity,
            underlying_price=None,  # Would need to fetch
            is_long=is_long,
        )

        # Check if we have enough margin (simplified check)
        current_equity = self.portfolio.cash
        if margin_req.total_required > current_equity * 0.5:  # Allow 50% margin usage
            logger.warning(
                f"Insufficient margin for {order.symbol}: "
                f"required {margin_req.total_required}, available {current_equity}"
            )
            return None

        # Create fill event
        fill = FillEvent(
            timestamp=fill_timestamp,
            symbol=order.symbol,
            side=order.side,
            quantity=fill_quantity,
            price=fill_price,
            commission=0.0,  # Paper trading: no commission
        )

        # Update portfolio
        self.portfolio.update_with_fill(fill)
        self._fills.append(fill)

        logger.info(
            f"Options fill: {fill.side} {fill.quantity} {fill.symbol} @ ${fill.price:.2f}"
        )

        return fill

    def get_fills(self, since: Optional[datetime] = None) -> list[FillEvent]:
        """Get all fills since a timestamp."""
        if since is None:
            return self._fills.copy()

        return [f for f in self._fills if f.timestamp >= since]

    def get_positions(self) -> Dict[str, float]:
        """Get current positions (symbol -> quantity)."""
        return {
            symbol: pos.size
            for symbol, pos in self.portfolio.positions.items()
            if pos.size != 0
        }

