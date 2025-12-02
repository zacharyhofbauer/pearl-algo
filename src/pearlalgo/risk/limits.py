from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from pearlalgo.core.events import OrderEvent, FillEvent
from pearlalgo.risk.pnl import DailyPnLTracker


@dataclass
class RiskLimits:
    max_daily_loss: float | None = None
    max_symbol_position: Dict[str, float] | None = None
    max_order_notional: float | None = None


class RiskGuard:
    """
    Lightweight risk guard to block dangerous orders.
    Extend with live position lookups and intraday reset logic.
    """

    def __init__(self, limits: RiskLimits, pnl_tracker: DailyPnLTracker | None = None):
        self.limits = limits
        self.pnl_tracker = pnl_tracker or DailyPnLTracker()

    def record_fill(self, fill: FillEvent) -> None:
        self.pnl_tracker.record_fill(fill)

    def check_order(self, order: OrderEvent, last_price: float | None = None) -> None:
        if self.limits.max_order_notional and last_price is not None:
            notional = abs(order.quantity) * last_price
            if notional > self.limits.max_order_notional:
                raise RuntimeError(
                    f"Order exceeds notional limit: {notional} > {self.limits.max_order_notional}"
                )

        if (
            self.limits.max_symbol_position
            and order.symbol in self.limits.max_symbol_position
        ):
            # Placeholder: ideally compare against live positions + this order.
            if abs(order.quantity) > self.limits.max_symbol_position[order.symbol]:
                raise RuntimeError(
                    f"Order exceeds position limit for {order.symbol}: {order.quantity} > "
                    f"{self.limits.max_symbol_position[order.symbol]}"
                )

        if self.pnl_tracker.daily_loss_breached(self.limits.max_daily_loss):
            raise RuntimeError("Daily loss limit breached; blocking orders.")
