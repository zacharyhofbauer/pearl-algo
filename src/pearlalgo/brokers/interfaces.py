"""
Enhanced Broker Interfaces for Professional Trading Systems.

Defines detailed interfaces and data structures for broker operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional


@dataclass
class AccountSummary:
    """Account summary information."""

    equity: float
    cash: float
    buying_power: float
    margin_used: float
    margin_available: float
    unrealized_pnl: float
    realized_pnl: float
    timestamp: datetime


@dataclass
class MarginRequirements:
    """Margin requirements for a symbol."""

    initial_margin: float
    maintenance_margin: float
    total_required: float
    available_margin: float


@dataclass
class OrderStatus:
    """Order status information."""

    order_id: str
    symbol: str
    side: str
    quantity: float
    filled_quantity: float
    status: str  # Pending, Submitted, PartiallyFilled, Filled, Cancelled, Rejected
    timestamp: datetime
    price: Optional[float] = None  # Fill price if filled


# Order lifecycle states
class OrderState:
    PENDING = "Pending"
    SUBMITTED = "Submitted"
    PARTIALLY_FILLED = "PartiallyFilled"
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    REJECTED = "Rejected"



