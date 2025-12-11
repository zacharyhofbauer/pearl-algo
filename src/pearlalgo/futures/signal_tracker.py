"""
Signal Tracker - Track active signals with mark-to-market PnL updates.

Tracks signals generated in signal-only mode and updates their PnL
as market prices change.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction,
            "entry_price": self.entry_price,
            "size": self.size,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "strategy_name": self.strategy_name,
            "reasoning": self.reasoning,
            "unrealized_pnl": self.unrealized_pnl,
            "last_update": self.last_update.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TrackedSignal":
        """Create from dictionary."""
        return cls(
            symbol=data["symbol"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            direction=data["direction"],
            entry_price=data["entry_price"],
            size=data["size"],
            stop_loss=data.get("stop_loss"),
            take_profit=data.get("take_profit"),
            strategy_name=data.get("strategy_name", "unknown"),
            reasoning=data.get("reasoning"),
            unrealized_pnl=data.get("unrealized_pnl", 0.0),
            last_update=datetime.fromisoformat(data.get("last_update", data["timestamp"])),
        )


class SignalTracker:
    """Track active signals and update their PnL with persistence."""
    
    def __init__(self, persistence_path: Optional[Path] = None):
        """
        Initialize signal tracker.
        
        Args:
            persistence_path: Path to JSON file for persistence (optional)
        """
        self.active_signals: Dict[str, TrackedSignal] = {}
        self.persistence_path = persistence_path or Path("data/active_signals.json")
        
        # Create data directory if it doesn't exist
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load persisted signals on startup
        self._load_signals()
        
        logger.info(f"SignalTracker initialized with {len(self.active_signals)} active signals")
    
    def _load_signals(self) -> None:
        """Load persisted signals from disk."""
        if not self.persistence_path.exists():
            logger.debug(f"No persisted signals found at {self.persistence_path}")
            return
        
        try:
            with open(self.persistence_path, "r") as f:
                data = json.load(f)
                for symbol, signal_data in data.items():
                    try:
                        signal = TrackedSignal.from_dict(signal_data)
                        self.active_signals[symbol] = signal
                        logger.info(f"Loaded persisted signal: {symbol} {signal.direction} @ ${signal.entry_price:.2f}")
                    except Exception as e:
                        logger.warning(f"Failed to load signal for {symbol}: {e}")
            
            logger.info(f"Loaded {len(self.active_signals)} persisted signals")
        except Exception as e:
            logger.error(f"Failed to load persisted signals: {e}")
    
    def _save_signals(self) -> None:
        """Save active signals to disk."""
        try:
            data = {
                symbol: signal.to_dict()
                for symbol, signal in self.active_signals.items()
            }
            with open(self.persistence_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved {len(self.active_signals)} signals to {self.persistence_path}")
        except Exception as e:
            logger.error(f"Failed to save signals: {e}")
    
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
        self._save_signals()  # Persist immediately
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
        
        # Save after updating all PnL
        if updated_pnls:
            self._save_signals()
        
        return updated_pnls
    
    def remove_signal(self, symbol: str) -> Optional[TrackedSignal]:
        """Remove a signal from tracking."""
        signal = self.active_signals.pop(symbol, None)
        if signal:
            self._save_signals()  # Persist removal
            logger.info(f"Removed signal from tracker: {symbol}")
        return signal
    
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
        if self.persistence_path.exists():
            self.persistence_path.unlink()
        logger.info("SignalTracker cleared")
