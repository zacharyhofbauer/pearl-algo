"""
Paper Futures Trading Engine.

Event-driven futures trading simulation with realistic fills,
margin calculations, and position tracking.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Dict, Optional

from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.paper_trading.fill_models import FillModelConfig, FuturesFillModel
from pearlalgo.paper_trading.margin_models import FuturesMarginModel

logger = logging.getLogger(__name__)


class PaperFuturesEngine:
    """
    Paper trading engine for futures contracts.

    Features:
    - Event-driven fill simulation
    - ATR-based slippage
    - SPAN-like margin calculations
    - Real-time mark-to-market
    - Deterministic mode for backtesting
    """

    def __init__(
        self,
        portfolio: Portfolio,
        fill_config: Optional[FillModelConfig] = None,
        margin_model: Optional[FuturesMarginModel] = None,
        price_lookup: Optional[Callable[[str], Optional[float]]] = None,
    ):
        """
        Initialize paper futures engine.

        Args:
            portfolio: Portfolio instance
            fill_config: Fill model configuration
            margin_model: Margin model (default: FuturesMarginModel)
            price_lookup: Function to get current price for a symbol
        """
        self.portfolio = portfolio
        self.fill_model = FuturesFillModel(config=fill_config)
        self.margin_model = margin_model or FuturesMarginModel()
        self.price_lookup = price_lookup or (lambda s: None)

        # Track pending orders and fills
        self._pending_orders: Dict[str, OrderEvent] = {}
        self._fills: list[FillEvent] = []

        # ATR cache for slippage calculations
        self._atr_cache: Dict[str, float] = {}

    def update_price(self, symbol: str, price: float, atr: Optional[float] = None) -> None:
        """
        Update current price for a symbol (triggers fills and mark-to-market).

        Args:
            symbol: Futures symbol
            price: Current market price
            atr: Average True Range (optional, for slippage)
        """
        if atr is not None:
            self._atr_cache[symbol] = atr
            self.fill_model.atr = atr

        # Check for pending orders and fill them
        self._process_pending_orders(symbol, price)

        # Mark positions to market
        self._mark_to_market({symbol: price})

    def submit_order(self, order: OrderEvent) -> Optional[FillEvent]:
        """
        Submit an order for execution.

        Args:
            order: OrderEvent to execute

        Returns:
            FillEvent if immediately filled, None if pending
        """
        # Get current price
        current_price = self.price_lookup(order.symbol)

        if current_price is None:
            logger.warning(
                f"No price available for {order.symbol}, order will be pending"
            )
            self._pending_orders[order.symbol] = order
            return None

        # Process order immediately
        return self._execute_order(order, current_price)

    def _execute_order(self, order: OrderEvent, price: float) -> Optional[FillEvent]:
        """Execute an order at current price."""
        # Apply fill model
        fill_price, fill_quantity, fill_timestamp = self.fill_model.apply_fill(
            price=price,
            side=order.side,
            quantity=order.quantity,
            timestamp=order.timestamp,
        )

        # Check margin requirements
        margin_req = self.margin_model.get_margin_requirements(
            symbol=order.symbol,
            quantity=fill_quantity,
            price=fill_price,
        )

        # Check if we have enough margin (simplified check)
        current_equity = self.portfolio.cash
        if self.portfolio.positions:
            # Rough equity estimate
            for sym, pos in self.portfolio.positions.items():
                current_price = self.price_lookup(sym)
                if current_price:
                    current_equity += pos.size * current_price

        if margin_req.total_required > current_equity:
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
            f"Fill: {fill.side} {fill.quantity} {fill.symbol} @ {fill.price:.2f}"
        )

        return fill

    def _process_pending_orders(self, symbol: str, price: float) -> None:
        """Process pending orders for a symbol."""
        if symbol in self._pending_orders:
            order = self._pending_orders.pop(symbol)
            fill = self._execute_order(order, price)
            if fill:
                logger.info(f"Pending order filled: {order.symbol}")

    def _mark_to_market(self, prices: Dict[str, float]) -> None:
        """Mark positions to market."""
        self.portfolio.mark_to_market(prices)

    def check_margin_calls(self, prices: Dict[str, float]) -> Dict[str, float]:
        """
        Check for margin calls on all positions.

        Args:
            prices: Current prices for all symbols

        Returns:
            Dict of symbol -> additional margin required
        """
        margin_calls = {}
        current_equity = self.portfolio.cash

        for symbol, position in self.portfolio.positions.items():
            if position.size == 0:
                continue

            if symbol not in prices:
                continue

            current_price = prices[symbol]
            is_call, additional_margin = self.margin_model.check_margin_call(
                symbol=symbol,
                quantity=position.size,
                current_price=current_price,
                avg_entry_price=position.avg_price,
                account_equity=current_equity,
            )

            if is_call:
                margin_calls[symbol] = additional_margin
                logger.warning(
                    f"Margin call on {symbol}: requires additional ${additional_margin:.2f}"
                )

        return margin_calls

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


