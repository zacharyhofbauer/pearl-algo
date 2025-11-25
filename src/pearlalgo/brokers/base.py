from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable

from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio


@dataclass
class BrokerConfig:
    """Generic broker configuration for paper/live routing."""

    base_url: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    paper: bool = True


class Broker(ABC):
    """Abstract broker interface."""

    def __init__(self, portfolio: Portfolio, config: BrokerConfig | None = None):
        self.portfolio = portfolio
        self.config = config or BrokerConfig()

    @abstractmethod
    def submit_order(self, order: OrderEvent) -> str:
        """Submit an order and return broker order id."""

    @abstractmethod
    def fetch_fills(self, since: datetime | None = None) -> Iterable[FillEvent]:
        """Retrieve fills from the broker."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        """Cancel an existing order if supported."""

    @abstractmethod
    def sync_positions(self) -> Dict[str, float]:
        """Sync current positions; returns symbol -> quantity."""

    def apply_fill(self, fill: FillEvent) -> None:
        """Update portfolio with a fill and apply simple risk checks."""
        self.portfolio.update_with_fill(fill)
        # Risk enforcement: callers can inspect portfolio.enforce_risk()
        self.portfolio.enforce_risk()
