from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping

from pearlalgo.core.events import FillEvent


@dataclass
class Position:
    """Represents a single-symbol position."""

    symbol: str
    size: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0

    def update_with_fill(self, fill: FillEvent) -> None:
        """Adjust position given a fill."""
        direction = 1.0 if fill.side.upper() == "BUY" else -1.0
        fill_qty = direction * fill.quantity

        # If flipping direction, realize PnL on closed portion
        if self.size != 0 and (self.size > 0 > fill_qty or self.size < 0 < fill_qty):
            closing_qty = min(abs(self.size), abs(fill_qty)) * (1 if self.size > 0 else -1)
            pnl = -closing_qty * (fill.price - self.avg_price)
            self.realized_pnl += pnl

        new_size = self.size + fill_qty

        if new_size == 0:
            # Fully flat after fill
            self.size = 0.0
            self.avg_price = 0.0
            return

        if self.size == 0:
            # Opening a new position
            self.avg_price = fill.price
        else:
            # Adjust average price for same-direction adds
            if (self.size > 0 and new_size > 0) or (self.size < 0 and new_size < 0):
                weighted_notional = self.avg_price * abs(self.size) + fill.price * abs(fill_qty)
                self.avg_price = weighted_notional / abs(new_size)
            else:
                # Reduced but not flipped; keep existing avg
                pass

        self.size = new_size


@dataclass
class RiskLimits:
    """Simple risk limits applied portfolio-wide."""

    daily_loss_limit: float | None = None
    max_position_size: float | None = None  # per symbol absolute quantity
    max_open_positions: int | None = None


@dataclass
class Portfolio:
    """Tracks cash, positions, and PnL."""

    cash: float = 1_000_000.0
    positions: Dict[str, Position] = field(default_factory=dict)
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    equity_curve: list[float] = field(default_factory=list)

    def update_with_fill(self, fill: FillEvent) -> None:
        pos = self.positions.get(fill.symbol)
        if pos is None:
            pos = Position(symbol=fill.symbol)
            self.positions[fill.symbol] = pos

        # Adjust cash for fill and commission
        direction = 1.0 if fill.side.upper() == "BUY" else -1.0
        self.cash -= direction * fill.quantity * fill.price
        self.cash -= fill.commission

        pos.update_with_fill(fill)

    def mark_to_market(self, prices: Mapping[str, float]) -> float:
        """Return total equity after marking positions to current prices."""
        equity = self.cash
        for sym, pos in self.positions.items():
            if sym not in prices:
                continue
            equity += pos.size * prices[sym]
        self.equity_curve.append(equity)
        return equity

    def enforce_risk(self) -> bool:
        """
        Apply simple risk limits. Returns True if portfolio remains tradable,
        False if limits breached (caller should trigger kill-switch/flatten).
        """
        if self.risk_limits.max_open_positions is not None:
            open_positions = sum(1 for p in self.positions.values() if p.size != 0)
            if open_positions > self.risk_limits.max_open_positions:
                return False

        if self.risk_limits.max_position_size is not None:
            for p in self.positions.values():
                if abs(p.size) > self.risk_limits.max_position_size:
                    return False

        if self.risk_limits.daily_loss_limit is not None and self.equity_curve:
            peak = max(self.equity_curve)
            if peak - self.equity_curve[-1] > self.risk_limits.daily_loss_limit:
                return False

        return True
