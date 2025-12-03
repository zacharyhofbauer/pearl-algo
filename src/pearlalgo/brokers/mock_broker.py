"""
Mock Broker for Testing.

Provides deterministic, configurable broker behavior for unit and integration tests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, Iterable, Optional

from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.brokers.interfaces import AccountSummary, MarginRequirements
from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class MockBroker(Broker):
    """
    Mock broker for testing with configurable behavior.

    Features:
    - Deterministic fills
    - Configurable fill prices
    - Configurable delays
    - No external dependencies
    """

    def __init__(
        self,
        portfolio: Portfolio,
        config: BrokerConfig | None = None,
        fill_price_func: Optional[Callable[[OrderEvent], float]] = None,
        fill_delay_seconds: float = 0.0,
        always_fill: bool = True,
    ):
        """
        Initialize mock broker.

        Args:
            portfolio: Portfolio instance
            config: Broker configuration
            fill_price_func: Function to determine fill price from order (default: use limit_price or market)
            fill_delay_seconds: Delay before filling orders
            always_fill: If True, always fill orders immediately (default: True)
        """
        super().__init__(portfolio, config)

        self.fill_price_func = fill_price_func or self._default_fill_price
        self.fill_delay_seconds = fill_delay_seconds
        self.always_fill = always_fill

        # Track orders and fills
        self._order_counter = 0
        self._orders: Dict[str, OrderEvent] = {}
        self._fills: list[FillEvent] = []
        self._rejected_orders: set[str] = set()

    def _default_fill_price(self, order: OrderEvent) -> float:
        """Default fill price logic."""
        if order.order_type == "LMT" and order.limit_price:
            return order.limit_price
        elif order.order_type == "STP" and order.stop_price:
            return order.stop_price
        else:
            # Market order - use a default price (would normally come from market data)
            return 100.0  # Default price

    def submit_order(self, order: OrderEvent) -> str:
        """Submit an order and optionally fill it immediately."""
        self._order_counter += 1
        order_id = f"MOCK_{self._order_counter:06d}"
        self._orders[order_id] = order

        if self.always_fill:
            # Fill immediately (or after delay)
            fill_price = self.fill_price_func(order)

            fill_timestamp = order.timestamp
            if self.fill_delay_seconds > 0:
                fill_timestamp = order.timestamp + timedelta(
                    seconds=self.fill_delay_seconds
                )

            fill = FillEvent(
                timestamp=fill_timestamp,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=fill_price,
                commission=0.0,
            )

            self.portfolio.update_with_fill(fill)
            self._fills.append(fill)

            logger.debug(
                f"Mock fill: {fill.side} {fill.quantity} {fill.symbol} @ {fill.price:.4f}"
            )

        return order_id

    def fetch_fills(self, since: datetime | None = None) -> Iterable[FillEvent]:
        """Retrieve fills."""
        if since is None:
            return self._fills.copy()

        return [f for f in self._fills if f.timestamp >= since]

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order."""
        if order_id in self._orders:
            logger.debug(f"Cancelling mock order {order_id}")
            del self._orders[order_id]
        else:
            logger.warning(f"Order {order_id} not found")

    def sync_positions(self) -> Dict[str, float]:
        """Sync positions from portfolio."""
        return {
            symbol: pos.size
            for symbol, pos in self.portfolio.positions.items()
            if pos.size != 0
        }

    def get_account_summary(self) -> AccountSummary:
        """Get account summary."""
        equity = self.portfolio.cash
        for pos in self.portfolio.positions.values():
            equity += pos.realized_pnl

        return AccountSummary(
            equity=equity,
            cash=self.portfolio.cash,
            buying_power=equity,
            margin_used=0.0,
            margin_available=equity,
            unrealized_pnl=0.0,
            realized_pnl=sum(
                pos.realized_pnl for pos in self.portfolio.positions.values()
            ),
            timestamp=datetime.now(),
        )

    def get_margin_requirements(self, symbol: str) -> Optional[MarginRequirements]:
        """Get margin requirements (mock - returns None)."""
        return None

    def reject_next_order(self) -> None:
        """Configure to reject the next order (for testing)."""
        self.always_fill = False

    def set_fill_price(self, price: float) -> None:
        """Set a fixed fill price for all orders."""
        self.fill_price_func = lambda order: price

