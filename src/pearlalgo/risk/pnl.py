from __future__ import annotations

from datetime import datetime, date
from typing import Dict

from pearlalgo.core.events import FillEvent


class DailyPnLTracker:
    """
    Minimal daily PnL tracker. Accumulates realized PnL per day; extend with
    mark-to-market updates to track unrealized and total equity.
    """

    def __init__(self):
        self.realized_daily: Dict[date, float] = {}

    def record_fill(self, fill: FillEvent) -> None:
        # Realized cash change: sell adds, buy subtracts.
        side_mult = 1.0 if fill.side.upper() == "SELL" else -1.0
        pnl = side_mult * fill.quantity * fill.price - fill.commission
        today = datetime.utcnow().date()
        self.realized_daily[today] = self.realized_daily.get(today, 0.0) + pnl

    def realized_today(self) -> float:
        return self.realized_daily.get(datetime.utcnow().date(), 0.0)

    def daily_loss_breached(self, max_daily_loss: float | None) -> bool:
        if max_daily_loss is None:
            return False
        return self.realized_today() < -abs(max_daily_loss)
