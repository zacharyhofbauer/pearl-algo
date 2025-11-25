from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List

from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio


class ExampleRestBroker(Broker):
    """
    Skeleton REST broker adapter.

    Replace the placeholder methods with real HTTP calls to your broker/prop-firm API.
    DO NOT embed secrets; pass them via env/config.
    """

    def __init__(self, portfolio: Portfolio, config: BrokerConfig):
        super().__init__(portfolio, config)
        if not config.base_url:
            raise ValueError("Broker base_url must be provided")
        self._open_orders: Dict[str, OrderEvent] = {}
        self._fills: List[FillEvent] = []

    def submit_order(self, order: OrderEvent) -> str:
        # TODO: Implement POST /orders against your broker API.
        # Use self.config.api_key/api_secret for auth headers.
        # Map order fields to broker schema; handle idempotency and errors.
        order_id = f"rest-{len(self._open_orders) + 1}"
        self._open_orders[order_id] = order
        return order_id

    def fetch_fills(self, since: datetime | None = None) -> Iterable[FillEvent]:
        # TODO: Implement GET /fills (or websocket stream) and translate to FillEvent.
        return [f for f in self._fills if since is None or f.timestamp >= since]

    def cancel_order(self, order_id: str) -> None:
        # TODO: Implement DELETE /orders/{id}
        self._open_orders.pop(order_id, None)

    def sync_positions(self) -> Dict[str, float]:
        # TODO: Implement GET /positions and map to symbol -> quantity
        return {sym: pos.size for sym, pos in self.portfolio.positions.items()}
