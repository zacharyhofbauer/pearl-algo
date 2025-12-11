"""
Options Signal Tracker - Track active options positions with mark-to-market PnL.

Tracks options positions (not just underlying) and updates their PnL
as option prices change. Handles expiration automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class OptionsSignalLifecycleState:
    """Options signal lifecycle states."""
    PENDING = "pending"
    ACTIVE = "active"
    EXITED = "exited"
    EXPIRED = "expired"


@dataclass
class TrackedOptionsSignal:
    """Represents a tracked options position with PnL."""
    # Underlying info
    underlying_symbol: str
    timestamp: datetime
    
    # Option contract details
    option_symbol: str
    strike: float
    expiration: datetime
    option_type: str  # "call" or "put"
    dte: int  # Days to expiration at entry
    
    # Position details
    direction: str  # "long" or "short"
    entry_premium: float  # Option premium paid/received
    quantity: int  # Number of contracts
    
    # Risk management
    stop_loss_underlying: Optional[float] = None  # Stop in underlying terms
    take_profit_underlying: Optional[float] = None  # Target in underlying terms
    
    # Strategy info
    strategy_name: str = "unknown"
    reasoning: Optional[str] = None
    
    # PnL tracking
    unrealized_pnl: float = 0.0
    last_premium: Optional[float] = None  # Last known option premium
    last_underlying_price: Optional[float] = None
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Lifecycle
    lifecycle_state: str = OptionsSignalLifecycleState.ACTIVE
    exit_timestamp: Optional[datetime] = None
    exit_reason: Optional[str] = None
    
    # Greeks (if available)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "underlying_symbol": self.underlying_symbol,
            "timestamp": self.timestamp.isoformat(),
            "option_symbol": self.option_symbol,
            "strike": self.strike,
            "expiration": self.expiration.isoformat(),
            "option_type": self.option_type,
            "dte": self.dte,
            "direction": self.direction,
            "entry_premium": self.entry_premium,
            "quantity": self.quantity,
            "stop_loss_underlying": self.stop_loss_underlying,
            "take_profit_underlying": self.take_profit_underlying,
            "strategy_name": self.strategy_name,
            "reasoning": self.reasoning,
            "unrealized_pnl": self.unrealized_pnl,
            "last_premium": self.last_premium,
            "last_underlying_price": self.last_underlying_price,
            "last_update": self.last_update.isoformat(),
            "lifecycle_state": self.lifecycle_state,
            "exit_timestamp": self.exit_timestamp.isoformat() if self.exit_timestamp else None,
            "exit_reason": self.exit_reason,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TrackedOptionsSignal":
        """Create from dictionary."""
        return cls(
            underlying_symbol=data["underlying_symbol"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            option_symbol=data["option_symbol"],
            strike=data["strike"],
            expiration=datetime.fromisoformat(data["expiration"]),
            option_type=data["option_type"],
            dte=data.get("dte", 0),
            direction=data["direction"],
            entry_premium=data["entry_premium"],
            quantity=data["quantity"],
            stop_loss_underlying=data.get("stop_loss_underlying"),
            take_profit_underlying=data.get("take_profit_underlying"),
            strategy_name=data.get("strategy_name", "unknown"),
            reasoning=data.get("reasoning"),
            unrealized_pnl=data.get("unrealized_pnl", 0.0),
            last_premium=data.get("last_premium"),
            last_underlying_price=data.get("last_underlying_price"),
            last_update=datetime.fromisoformat(data.get("last_update", data["timestamp"])),
            lifecycle_state=data.get("lifecycle_state", OptionsSignalLifecycleState.ACTIVE),
            exit_timestamp=datetime.fromisoformat(data["exit_timestamp"]) if data.get("exit_timestamp") else None,
            exit_reason=data.get("exit_reason"),
            delta=data.get("delta"),
            gamma=data.get("gamma"),
            theta=data.get("theta"),
        )
    
    def is_expired(self) -> bool:
        """Check if option has expired."""
        return datetime.now(timezone.utc) >= self.expiration
    
    def get_current_dte(self) -> int:
        """Get current days to expiration."""
        if self.is_expired():
            return 0
        return (self.expiration - datetime.now(timezone.utc)).days


class OptionsSignalTracker:
    """Track active options positions and update their PnL with persistence."""
    
    def __init__(
        self, 
        persistence_path: Optional[Path] = None,
        max_signal_age_days: int = 30,  # Options can have longer DTE
        enable_backup: bool = True,
    ):
        """
        Initialize options signal tracker.
        
        Args:
            persistence_path: Path to persistence file
            max_signal_age_days: Maximum age for signals before cleanup
            enable_backup: Enable automatic backups
        """
        self.persistence_path = persistence_path or Path("data/options_signals.json")
        self.max_signal_age_days = max_signal_age_days
        self.enable_backup = enable_backup
        
        # Tracked signals: option_symbol -> TrackedOptionsSignal
        self.signals: Dict[str, TrackedOptionsSignal] = {}
        
        # Load persisted signals
        self._load_signals()
        
        logger.info(
            f"OptionsSignalTracker initialized: {len(self.signals)} signals loaded"
        )
    
    def add_signal(
        self,
        underlying_symbol: str,
        option_symbol: str,
        strike: float,
        expiration: datetime,
        option_type: str,
        direction: str,
        entry_premium: float,
        quantity: int = 1,
        stop_loss_underlying: Optional[float] = None,
        take_profit_underlying: Optional[float] = None,
        strategy_name: str = "unknown",
        reasoning: Optional[str] = None,
        delta: Optional[float] = None,
        gamma: Optional[float] = None,
        theta: Optional[float] = None,
    ) -> TrackedOptionsSignal:
        """
        Add a new options signal to track.
        
        Args:
            underlying_symbol: Underlying symbol (e.g., "QQQ")
            option_symbol: Option contract symbol
            strike: Strike price
            expiration: Expiration datetime
            option_type: "call" or "put"
            direction: "long" or "short"
            entry_premium: Option premium paid/received
            quantity: Number of contracts
            stop_loss_underlying: Stop loss in underlying terms
            take_profit_underlying: Take profit in underlying terms
            strategy_name: Strategy name
            reasoning: Signal reasoning
            delta: Option delta (optional)
            gamma: Option gamma (optional)
            theta: Option theta (optional)
            
        Returns:
            TrackedOptionsSignal instance
        """
        dte = (expiration - datetime.now(timezone.utc)).days
        
        signal = TrackedOptionsSignal(
            underlying_symbol=underlying_symbol,
            timestamp=datetime.now(timezone.utc),
            option_symbol=option_symbol,
            strike=strike,
            expiration=expiration,
            option_type=option_type,
            dte=dte,
            direction=direction,
            entry_premium=entry_premium,
            quantity=quantity,
            stop_loss_underlying=stop_loss_underlying,
            take_profit_underlying=take_profit_underlying,
            strategy_name=strategy_name,
            reasoning=reasoning,
            delta=delta,
            gamma=gamma,
            theta=theta,
        )
        
        self.signals[option_symbol] = signal
        self._save_signals()
        
        logger.info(
            f"Added options signal: {option_symbol} "
            f"({underlying_symbol} {option_type} ${strike:.2f} exp {expiration.date()})"
        )
        
        return signal
    
    def update_pnl(
        self,
        option_symbol: str,
        current_premium: float,
        underlying_price: Optional[float] = None,
    ) -> Optional[TrackedOptionsSignal]:
        """
        Update PnL for an options position.
        
        Args:
            option_symbol: Option contract symbol
            current_premium: Current option premium
            underlying_price: Current underlying price (optional)
            
        Returns:
            Updated TrackedOptionsSignal or None if not found
        """
        if option_symbol not in self.signals:
            return None
        
        signal = self.signals[option_symbol]
        
        # Calculate unrealized PnL
        # For long positions: PnL = (current_premium - entry_premium) * quantity * 100
        # For short positions: PnL = (entry_premium - current_premium) * quantity * 100
        premium_diff = current_premium - signal.entry_premium
        if signal.direction == "long":
            signal.unrealized_pnl = premium_diff * signal.quantity * 100
        else:  # short
            signal.unrealized_pnl = -premium_diff * signal.quantity * 100
        
        signal.last_premium = current_premium
        signal.last_underlying_price = underlying_price
        signal.last_update = datetime.now(timezone.utc)
        
        # Check for expiration
        if signal.is_expired():
            signal.lifecycle_state = OptionsSignalLifecycleState.EXPIRED
            signal.exit_timestamp = datetime.now(timezone.utc)
            signal.exit_reason = "Expired"
            logger.warning(f"Option {option_symbol} has expired")
        
        self._save_signals()
        
        return signal
    
    def remove_signal(self, option_symbol: str) -> Optional[TrackedOptionsSignal]:
        """
        Remove a signal (e.g., on exit).
        
        Args:
            option_symbol: Option contract symbol
            
        Returns:
            Removed TrackedOptionsSignal or None if not found
        """
        if option_symbol not in self.signals:
            return None
        
        signal = self.signals.pop(option_symbol)
        signal.lifecycle_state = OptionsSignalLifecycleState.EXITED
        signal.exit_timestamp = datetime.now(timezone.utc)
        
        self._save_signals()
        
        logger.info(f"Removed options signal: {option_symbol}")
        
        return signal
    
    def get_signal(self, option_symbol: str) -> Optional[TrackedOptionsSignal]:
        """Get signal by option symbol."""
        return self.signals.get(option_symbol)
    
    def get_active_signals(self) -> Dict[str, TrackedOptionsSignal]:
        """Get all active signals."""
        return {
            sym: sig for sym, sig in self.signals.items()
            if sig.lifecycle_state == OptionsSignalLifecycleState.ACTIVE
        }
    
    def get_expired_signals(self) -> Dict[str, TrackedOptionsSignal]:
        """Get all expired signals."""
        return {
            sym: sig for sym, sig in self.signals.items()
            if sig.lifecycle_state == OptionsSignalLifecycleState.EXPIRED
        }
    
    def cleanup_old_signals(self) -> int:
        """
        Clean up old signals beyond max age.
        
        Returns:
            Number of signals cleaned up
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.max_signal_age_days)
        
        to_remove = [
            sym for sym, sig in self.signals.items()
            if sig.timestamp < cutoff_date and sig.lifecycle_state != OptionsSignalLifecycleState.ACTIVE
        ]
        
        for sym in to_remove:
            del self.signals[sym]
        
        if to_remove:
            self._save_signals()
            logger.info(f"Cleaned up {len(to_remove)} old signals")
        
        return len(to_remove)
    
    def _load_signals(self) -> None:
        """Load signals from persistence file."""
        if not self.persistence_path.exists():
            logger.debug(f"Persistence file not found: {self.persistence_path}")
            return
        
        try:
            with open(self.persistence_path, "r") as f:
                data = json.load(f)
            
            for option_symbol, signal_data in data.items():
                try:
                    signal = TrackedOptionsSignal.from_dict(signal_data)
                    self.signals[option_symbol] = signal
                except Exception as e:
                    logger.warning(f"Error loading signal {option_symbol}: {e}")
                    continue
            
            logger.info(f"Loaded {len(self.signals)} signals from {self.persistence_path}")
        except Exception as e:
            logger.error(f"Error loading signals: {e}", exc_info=True)
    
    def _save_signals(self) -> None:
        """Save signals to persistence file."""
        try:
            # Create backup if enabled
            if self.enable_backup and self.persistence_path.exists():
                backup_path = self.persistence_path.with_suffix(".json.bak")
                shutil.copy2(self.persistence_path, backup_path)
            
            # Ensure directory exists
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save signals
            data = {
                option_symbol: signal.to_dict()
                for option_symbol, signal in self.signals.items()
            }
            
            with open(self.persistence_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            
            logger.debug(f"Saved {len(self.signals)} signals to {self.persistence_path}")
        except Exception as e:
            logger.error(f"Error saving signals: {e}", exc_info=True)
    
    def get_statistics(self) -> Dict:
        """Get tracker statistics."""
        active = self.get_active_signals()
        expired = self.get_expired_signals()
        
        total_pnl = sum(sig.unrealized_pnl for sig in self.signals.values())
        active_pnl = sum(sig.unrealized_pnl for sig in active.values())
        
        return {
            "total_signals": len(self.signals),
            "active_signals": len(active),
            "expired_signals": len(expired),
            "total_unrealized_pnl": total_pnl,
            "active_unrealized_pnl": active_pnl,
        }
