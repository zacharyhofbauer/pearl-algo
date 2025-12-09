"""
Signal Tracker - Track active signals with mark-to-market PnL updates.

Tracks signals generated in signal-only mode and updates their PnL
as market prices change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


@dataclass
class TrackedSignal:
    """Represents a tracked signal with PnL."""
    symbol: str
    timestamp: datetime
    direction: str  # "long" or "short"
    entry_price: float
    size: int
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy_name: str = "unknown"
    reasoning: Optional[str] = None
    unrealized_pnl: float = 0.0
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SignalTracker:
    """Track active signals and update their PnL."""
    
    def __init__(self):
        self.active_signals: Dict[str, TrackedSignal] = {}
        logger.info("SignalTracker initialized")
    
    def add_signal(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        size: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy_name: str = "unknown",
        reasoning: Optional[str] = None,
    ) -> None:
        """Add a new signal to track."""
        signal = TrackedSignal(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            direction=direction,
            entry_price=entry_price,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
            reasoning=reasoning,
        )
        self.active_signals[symbol] = signal
        logger.info(f"Added signal to tracker: {symbol} {direction} @ ${entry_price:.2f}")
    
    def update_pnl(self, symbol: str, current_price: float) -> Optional[float]:
        """
        Update PnL for a signal based on current market price.
        
        Returns:
            Updated unrealized PnL, or None if signal not found
        """
        if symbol not in self.active_signals:
            return None
        
        signal = self.active_signals[symbol]
        direction_multiplier = 1 if signal.direction == "long" else -1
        signal.unrealized_pnl = direction_multiplier * signal.size * (current_price - signal.entry_price)
        signal.last_update = datetime.now(timezone.utc)
        
        return signal.unrealized_pnl
    
    def update_all_pnl(self, prices: Dict[str, float]) -> Dict[str, float]:
        """
        Update PnL for all active signals.
        
        Args:
            prices: Dictionary of symbol -> current_price
            
        Returns:
            Dictionary of symbol -> updated_pnl
        """
        updated_pnls = {}
        for symbol, price in prices.items():
            if symbol in self.active_signals:
                pnl = self.update_pnl(symbol, price)
                if pnl is not None:
                    updated_pnls[symbol] = pnl
        return updated_pnls
    
    def remove_signal(self, symbol: str) -> Optional[TrackedSignal]:
        """Remove a signal from tracking."""
        return self.active_signals.pop(symbol, None)
    
    def get_signal(self, symbol: str) -> Optional[TrackedSignal]:
        """Get a tracked signal."""
        return self.active_signals.get(symbol)
    
    def get_all_signals(self) -> Dict[str, TrackedSignal]:
        """Get all active signals."""
        return self.active_signals.copy()
    
    def get_total_pnl(self) -> float:
        """Get total unrealized PnL across all signals."""
        return sum(signal.unrealized_pnl for signal in self.active_signals.values())
    
    def clear(self) -> None:
        """Clear all tracked signals."""
        self.active_signals.clear()
        logger.info("SignalTracker cleared")
