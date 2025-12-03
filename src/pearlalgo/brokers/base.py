from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, Optional

from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.brokers.interfaces import AccountSummary, MarginRequirements


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

    def get_account_summary(self) -> Optional[AccountSummary]:
        """
        Get account summary information.
        
        Returns:
            AccountSummary or None if not supported
        """
        # Default implementation - can be overridden
        equity = self.portfolio.cash
        if self.portfolio.positions:
            # Rough estimate - mark to market would be needed for accurate equity
            for pos in self.portfolio.positions.values():
                equity += pos.realized_pnl
        
        return AccountSummary(
            equity=equity,
            cash=self.portfolio.cash,
            buying_power=equity,
            margin_used=0.0,
            margin_available=equity,
            unrealized_pnl=0.0,
            realized_pnl=sum(p.realized_pnl for p in self.portfolio.positions.values()),
            timestamp=datetime.now(),
        )

    def get_margin_requirements(self, symbol: str) -> Optional[MarginRequirements]:
        """
        Get margin requirements for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            MarginRequirements or None if not supported
        """
        # Default implementation - can be overridden
        return None

    def apply_fill(self, fill: FillEvent) -> None:
        """Update portfolio with a fill and apply simple risk checks."""
        self.portfolio.update_with_fill(fill)
        # Risk enforcement: callers can inspect portfolio.enforce_risk()
        self.portfolio.enforce_risk()
