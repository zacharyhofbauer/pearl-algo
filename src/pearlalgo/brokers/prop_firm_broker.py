from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Iterable

from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class PropFirmBroker(Broker):
    """
    Skeleton broker adapter for prop-firm APIs.

    Implement REST/WS calls per prop API; enforce daily loss limits, time-of-day curfews,
    and scaling rules specific to evaluations/live.
    """

    def __init__(self, portfolio: Portfolio, config: BrokerConfig):
        super().__init__(portfolio, config)
        self._open_orders: Dict[str, OrderEvent] = {}
        self._fills: list[FillEvent] = []

    def submit_order(self, order: OrderEvent) -> str:
        # TODO: implement real submission; this is a dry-run placeholder.
        order_id = f"prop-{len(self._open_orders) + 1}"
        self._open_orders[order_id] = order
        logger.info("PropFirmBroker dry-run: would submit %s", order)
        return order_id

    def fetch_fills(self, since: datetime | None = None) -> Iterable[FillEvent]:
        return [f for f in self._fills if since is None or f.timestamp >= since]

    def cancel_order(self, order_id: str) -> None:
        self._open_orders.pop(order_id, None)

    def sync_positions(self) -> Dict[str, float]:
        # TODO: pull positions from prop API
        return {sym: pos.size for sym, pos in self.portfolio.positions.items()}
