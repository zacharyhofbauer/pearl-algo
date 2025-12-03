from __future__ import annotations

from datetime import datetime, date, timezone
from typing import Dict

from pearlalgo.core.events import FillEvent


class DailyPnLTracker:
    """
    Enhanced daily PnL tracker with unrealized PnL support.
    
    Tracks both realized and unrealized PnL with mark-to-market updates.
    """

    def __init__(self):
        self.realized_daily: Dict[date, float] = {}
        self.unrealized_daily: Dict[date, float] = {}
        self.last_mark_to_market: Dict[date, Dict[str, float]] = {}  # symbol -> price

    def record_fill(self, fill: FillEvent) -> None:
        # Realized cash change: sell adds, buy subtracts.
        side_mult = 1.0 if fill.side.upper() == "SELL" else -1.0
        pnl = side_mult * fill.quantity * fill.price - fill.commission
        today = datetime.now(timezone.utc).date()
        self.realized_daily[today] = self.realized_daily.get(today, 0.0) + pnl

    def mark_to_market(
        self, positions: Dict[str, tuple[float, float]], prices: Dict[str, float]
    ) -> float:
        """
        Mark positions to market and calculate unrealized PnL.

        Args:
            positions: Dict of symbol -> (size, avg_price)
            prices: Current prices for all symbols

        Returns:
            Total unrealized PnL
        """
        today = datetime.now(timezone.utc).date()
        unrealized_pnl = 0.0

        for symbol, (size, avg_price) in positions.items():
            if size == 0 or symbol not in prices:
                continue

            current_price = prices[symbol]
            price_diff = current_price - avg_price
            symbol_unrealized = price_diff * size
            unrealized_pnl += symbol_unrealized

            # Store last mark-to-market price
            if today not in self.last_mark_to_market:
                self.last_mark_to_market[today] = {}
            self.last_mark_to_market[today][symbol] = current_price

        self.unrealized_daily[today] = unrealized_pnl
        return unrealized_pnl

    def realized_today(self) -> float:
        """Get realized PnL for today."""
        return self.realized_daily.get(datetime.now(timezone.utc).date(), 0.0)

    def unrealized_today(self) -> float:
        """Get unrealized PnL for today."""
        return self.unrealized_daily.get(datetime.now(timezone.utc).date(), 0.0)

    def total_pnl_today(self) -> float:
        """Get total PnL (realized + unrealized) for today."""
        return self.realized_today() + self.unrealized_today()

    def daily_loss_breached(self, max_daily_loss: float | None) -> bool:
        """Check if daily loss limit breached (based on realized PnL)."""
        if max_daily_loss is None:
            return False
        return self.realized_today() < -abs(max_daily_loss)

    def total_loss_breached(
        self, max_daily_loss: float | None, include_unrealized: bool = False
    ) -> bool:
        """
        Check if daily loss limit breached (optionally including unrealized).

        Args:
            max_daily_loss: Maximum allowed daily loss
            include_unrealized: If True, include unrealized PnL in check

        Returns:
            True if limit breached
        """
        if max_daily_loss is None:
            return False

        if include_unrealized:
            total_pnl = self.total_pnl_today()
        else:
            total_pnl = self.realized_today()

        return total_pnl < -abs(max_daily_loss)
