from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class MarketDataEvent:
    """Normalized market data bar/tick event."""

    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float | int
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class SignalEvent:
    """Standardized trading signal emitted by strategies."""

    timestamp: datetime
    symbol: str
    direction: int  # 1 long, -1 short, 0 flat
    confidence: float = 1.0
    size_hint: float | None = None
    stop: float | None = None
    target: float | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class OrderEvent:
    """Order intent routed to a broker."""

    timestamp: datetime
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: float
    order_type: str = "MKT"  # "MKT" | "LMT" | "STP"
    limit_price: float | None = None
    stop_price: float | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class FillEvent:
    """Execution/fill from broker."""

    timestamp: datetime
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: float
    price: float
    commission: float = 0.0
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PortfolioEvent:
    """Portfolio update such as PnL or risk trigger."""

    timestamp: datetime
    equity: float
    cash: float
    positions: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] | None = None
