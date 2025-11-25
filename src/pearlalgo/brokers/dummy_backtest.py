from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Callable

from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio


class DummyBacktestBroker(Broker):
    """
    In-memory broker for backtests and dry-runs.

    Immediately fills market/limit orders using a provided price lookup or the order's limit price.
    This is intentionally simple; a full backtest engine should simulate slippage and partial fills.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        config: BrokerConfig | None = None,
        price_lookup: Callable[[str], float | None] | None = None,
        commission_per_unit: float = 0.0,
    ):
        super().__init__(portfolio, config)
        self._orders: Dict[str, OrderEvent] = {}
        self._fills: List[FillEvent] = []
        self._price_lookup = price_lookup or (lambda symbol: None)
        self._commission_per_unit = commission_per_unit

    def submit_order(self, order: OrderEvent) -> str:
        order_id = f"sim-{len(self._orders) + 1}"
        self._orders[order_id] = order

        price = order.limit_price or order.stop_price or self._price_lookup(order.symbol)
        if price is not None:
            fill = FillEvent(
                timestamp=order.timestamp,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=price,
                commission=self._commission_per_unit * order.quantity,
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
