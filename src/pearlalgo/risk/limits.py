from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from pearlalgo.core.events import OrderEvent


@dataclass
class RiskLimits:
    max_daily_loss: float | None = None
    max_symbol_position: Dict[str, float] | None = None
    max_order_notional: float | None = None


class RiskGuard:
    """
    Lightweight risk guard to block obviously dangerous orders.
    Extend with PnL tracking and intraday reset logic.
    """

    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self.daily_pnl: float = 0.0  # wire to real PnL tracker in live mode

    def check_order(self, order: OrderEvent, last_price: float | None = None) -> None:
        if self.limits.max_order_notional and last_price is not None:
            notional = abs(order.quantity) * last_price
            if notional > self.limits.max_order_notional:
                raise RuntimeError(f"Order exceeds notional limit: {notional} > {self.limits.max_order_notional}")

        if self.limits.max_symbol_position and order.symbol in self.limits.max_symbol_position:
            # This guard should compare against live positions; placeholder uses quantity requested.
            if abs(order.quantity) > self.limits.max_symbol_position[order.symbol]:
                raise RuntimeError(
                    f"Order exceeds position limit for {order.symbol}: {order.quantity} > "
                    f"{self.limits.max_symbol_position[order.symbol]}"
                )

        if self.limits.max_daily_loss is not None and self.daily_pnl < -abs(self.limits.max_daily_loss):
            raise RuntimeError("Daily loss limit breached; blocking orders.")
