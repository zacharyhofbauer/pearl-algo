from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Callable

from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio


class DummyBacktestBroker(Broker):
    """
    Enhanced in-memory broker for backtests with slippage, fees, and execution delays.

    Features:
    - Slippage modeling (fixed or percentage-based)
    - Commission/fee models
    - Execution delays (simulated)
    - Partial fills support
    """

    def __init__(
        self,
        portfolio: Portfolio,
        config: BrokerConfig | None = None,
        price_lookup: Callable[[str], float | None] | None = None,
        commission_per_unit: float = 0.0,
        commission_per_trade: float = 0.0,
        slippage_bps: float = 2.0,  # Basis points (0.02% default)
        fixed_slippage: float = 0.0,  # Fixed slippage in price units
        execution_delay_seconds: int = 0,  # Execution delay simulation
        enable_partial_fills: bool = False,
        partial_fill_probability: float = 0.1,  # 10% chance of partial fill
    ):
        super().__init__(portfolio, config)
        self._orders: Dict[str, OrderEvent] = {}
        self._fills: List[FillEvent] = []
        self._price_lookup = price_lookup or (lambda symbol: None)
        self._commission_per_unit = commission_per_unit
        self._commission_per_trade = commission_per_trade
        self._slippage_bps = slippage_bps
        self._fixed_slippage = fixed_slippage
        self._execution_delay_seconds = execution_delay_seconds
        self._enable_partial_fills = enable_partial_fills
        self._partial_fill_probability = partial_fill_probability

    def _apply_slippage(self, price: float, side: str, quantity: int) -> float:
        """
        Apply slippage to fill price.
        - Long orders: pay more (positive slippage)
        - Short orders: receive less (positive slippage)
        """
        # Percentage-based slippage
        slippage_pct = (self._slippage_bps / 10000.0) * abs(quantity)  # Scale with size
        slippage_amount = price * slippage_pct

        # Fixed slippage
        slippage_amount += self._fixed_slippage

        # Apply slippage based on side
        if side.lower() in ["long", "buy"]:
            return price + slippage_amount
        elif side.lower() in ["short", "sell"]:
            return price - slippage_amount
        return price

    def _calculate_commission(self, quantity: int) -> float:
        """Calculate total commission for a trade."""
        per_unit = self._commission_per_unit * abs(quantity)
        per_trade = self._commission_per_trade
        return per_unit + per_trade

    def _simulate_execution_delay(self, order_time: datetime) -> datetime:
        """Simulate execution delay."""
        if self._execution_delay_seconds > 0:
            return order_time + timedelta(seconds=self._execution_delay_seconds)
        return order_time

    def submit_order(self, order: OrderEvent) -> str:
        order_id = f"sim-{len(self._orders) + 1}"
        self._orders[order_id] = order

        base_price = (
            order.limit_price or order.stop_price or self._price_lookup(order.symbol)
        )
        if base_price is None:
            return order_id

        # Simulate execution delay
        fill_time = self._simulate_execution_delay(order.timestamp)

        # Apply slippage
        fill_price = self._apply_slippage(base_price, order.side, order.quantity)

        # Simulate partial fills if enabled
        fill_quantity = order.quantity
        if (
            self._enable_partial_fills
            and random.random() < self._partial_fill_probability
        ):
            # Partial fill: 50-90% of order
            fill_ratio = random.uniform(0.5, 0.9)
            fill_quantity = int(order.quantity * fill_ratio)
            if fill_quantity == 0:
                fill_quantity = 1  # At least 1 unit

        # Calculate commission
        commission = self._calculate_commission(fill_quantity)

        fill = FillEvent(
            timestamp=fill_time,
            symbol=order.symbol,
            side=order.side,
            quantity=fill_quantity,
            price=fill_price,
            commission=commission,
        )
        self._fills.append(fill)
        self.apply_fill(fill)
        return order_id

    def fetch_fills(self, since: datetime | None = None) -> Iterable[FillEvent]:
        if since is None:
            return list(self._fills)
        return [f for f in self._fills if f.timestamp >= since]

    def cancel_order(self, order_id: str) -> None:
        self._orders.pop(order_id, None)

    def sync_positions(self) -> Dict[str, float]:
        return {sym: pos.size for sym, pos in self.portfolio.positions.items()}
