from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class OrderRequest:
    timestamp: datetime
    symbol: str
    size: int
    order_type: str = "MKT"  # MKT | LMT | STP
    price: float | None = None
    stop_price: float | None = None
    time_in_force: str | None = None


@dataclass
class OrderFill:
    timestamp: datetime
    symbol: str
    size: int
    price: float
    commission: float = 0.0
