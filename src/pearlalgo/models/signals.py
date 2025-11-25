from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Signal:
    timestamp: datetime
    symbol: str
    direction: int  # 1 long, -1 short, 0 flat
    confidence: float = 1.0
