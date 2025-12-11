"""
Signal Tracker - Track active signals with mark-to-market PnL updates.

Tracks signals generated in signal-only mode and updates their PnL
as market prices change.
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


class SignalLifecycleState:
    """Signal lifecycle states."""
    PENDING = "pending"
    ACTIVE = "active"
    EXITED = "exited"
    EXPIRED = "expired"


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
    lifecycle_state: str = SignalLifecycleState.ACTIVE
    exit_timestamp: Optional[datetime] = None
    exit_reason: Optional[str] = None
    
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
            "lifecycle_state": self.lifecycle_state,
            "exit_timestamp": self.exit_timestamp.isoformat() if self.exit_timestamp else None,
            "exit_reason": self.exit_reason,
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
            lifecycle_state=data.get("lifecycle_state", SignalLifecycleState.ACTIVE),
            exit_timestamp=datetime.fromisoformat(data["exit_timestamp"]) if data.get("exit_timestamp") else None,
            exit_reason=data.get("exit_reason"),
        )


class SignalTracker:
    """Track active signals and update their PnL with persistence."""
    
    def __init__(
        self, 
        persistence_path: Optional[Path] = None,
        max_signal_age_days: int = 7,
        enable_backup: bool = True,
    ):
        """
        Initialize signal tracker.
        
        Args:
            persistence_path: Path to JSON file for persistence (optional)
            max_signal_age_days: Maximum age in days before signal is considered stale (default: 7)
            enable_backup: Enable backup of persistence file before writes (default: True)
        """
        self.active_signals: Dict[str, TrackedSignal] = {}
        self.persistence_path = persistence_path or Path("data/active_signals.json")
        self.max_signal_age_days = max_signal_age_days
        self.enable_backup = enable_backup
        
        # Metrics tracking
        self.persistence_save_count = 0
        self.persistence_load_count = 0
        self.persistence_error_count = 0
        self.validation_error_count = 0
        self.exited_signals_cleanup_count = 0
        
        # Performance optimization: debounced batch writes
        self._debounce_delay = 2.0  # seconds
        self._debounce_timer: Optional[asyncio.Task] = None
        self._pending_write = False
        
        # Create data directory if it doesn't exist
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load persisted signals on startup
        self._load_signals()
        
        # Cleanup stale signals on startup
        self.cleanup_stale_signals()
        
        logger.info(f"SignalTracker initialized with {len(self.active_signals)} active signals")
    
    def _validate_signal(self, signal: TrackedSignal) -> bool:
        """
        Validate signal integrity.
        
        Args:
            signal: TrackedSignal to validate
            
        Returns:
            True if signal is valid, False otherwise
        """
        # Check required fields
        if not signal.symbol or not isinstance(signal.symbol, str):
            logger.warning(f"Invalid signal: missing or invalid symbol")
            return False
        
        if signal.direction not in ["long", "short"]:
            logger.warning(f"Invalid signal {signal.symbol}: invalid direction '{signal.direction}'")
            return False
        
        # Check price values are reasonable
        if signal.entry_price <= 0 or signal.entry_price > 1e6:
            logger.warning(f"Invalid signal {signal.symbol}: unreasonable entry_price ${signal.entry_price:.2f}")
            return False
        
        if signal.size <= 0 or signal.size > 1000:
            logger.warning(f"Invalid signal {signal.symbol}: unreasonable size {signal.size}")
            return False
        
        # Check stop loss and take profit are reasonable if set
        if signal.stop_loss is not None:
            if signal.stop_loss <= 0 or signal.stop_loss > 1e6:
                logger.warning(f"Invalid signal {signal.symbol}: unreasonable stop_loss ${signal.stop_loss:.2f}")
                return False
            # For long: stop should be below entry; for short: stop should be above entry
            if signal.direction == "long" and signal.stop_loss >= signal.entry_price:
                logger.warning(f"Invalid signal {signal.symbol}: stop_loss ${signal.stop_loss:.2f} >= entry ${signal.entry_price:.2f} for long")
                return False
            if signal.direction == "short" and signal.stop_loss <= signal.entry_price:
                logger.warning(f"Invalid signal {signal.symbol}: stop_loss ${signal.stop_loss:.2f} <= entry ${signal.entry_price:.2f} for short")
                return False
        
        if signal.take_profit is not None:
            if signal.take_profit <= 0 or signal.take_profit > 1e6:
                logger.warning(f"Invalid signal {signal.symbol}: unreasonable take_profit ${signal.take_profit:.2f}")
                return False
            # For long: target should be above entry; for short: target should be below entry
            if signal.direction == "long" and signal.take_profit <= signal.entry_price:
                logger.warning(f"Invalid signal {signal.symbol}: take_profit ${signal.take_profit:.2f} <= entry ${signal.entry_price:.2f} for long")
                return False
            if signal.direction == "short" and signal.take_profit >= signal.entry_price:
                logger.warning(f"Invalid signal {signal.symbol}: take_profit ${signal.take_profit:.2f} >= entry ${signal.entry_price:.2f} for short")
                return False
        
        # Check timestamp is reasonable (not too far in future or past)
        now = datetime.now(timezone.utc)
        if signal.timestamp > now + timedelta(days=1):
            logger.warning(f"Invalid signal {signal.symbol}: timestamp in future")
            return False
        if signal.timestamp < now - timedelta(days=365):
            logger.warning(f"Invalid signal {signal.symbol}: timestamp too old")
            return False
        
        return True
    
    def _backup_persistence_file(self) -> bool:
        """
        Create backup of persistence file before write.
        
        Returns:
            True if backup successful, False otherwise
        """
        if not self.enable_backup or not self.persistence_path.exists():
            return True
        
        try:
            backup_path = self.persistence_path.with_suffix('.json.bak')
            shutil.copy2(self.persistence_path, backup_path)
            logger.debug(f"Created backup: {backup_path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to create backup: {e}")
            return False
    
    def _recover_from_corruption(self) -> bool:
        """
        Attempt to recover from corrupted persistence file.
        
        Returns:
            True if recovery successful, False otherwise
        """
        backup_path = self.persistence_path.with_suffix('.json.bak')
        
        if backup_path.exists():
            try:
                logger.info(f"Attempting recovery from backup: {backup_path}")
                shutil.copy2(backup_path, self.persistence_path)
                # Try loading again
                self._load_signals()
                logger.info("Recovery from backup successful")
                return True
            except Exception as e:
                logger.error(f"Recovery from backup failed: {e}")
        
        logger.error("No backup available for recovery")
        return False
    
    def _load_signals(self) -> None:
        """Load persisted signals from disk with validation and corruption recovery."""
        if not self.persistence_path.exists():
            logger.debug(f"No persisted signals found at {self.persistence_path}")
            return
        
        try:
            self.persistence_load_count += 1
            with open(self.persistence_path, "r") as f:
                data = json.load(f)
            
            loaded_count = 0
            for symbol, signal_data in data.items():
                try:
                    signal = TrackedSignal.from_dict(signal_data)
                    
                    # Validate signal before adding
                    if not self._validate_signal(signal):
                        self.validation_error_count += 1
                        logger.warning(f"Skipping invalid signal for {symbol}")
                        continue
                    
                    self.active_signals[symbol] = signal
                    loaded_count += 1
                    logger.debug(f"Loaded persisted signal: {symbol} {signal.direction} @ ${signal.entry_price:.2f}")
                except Exception as e:
                    self.validation_error_count += 1
                    logger.warning(f"Failed to load signal for {symbol}: {e}")
            
            logger.info(f"Loaded {loaded_count} persisted signals (skipped {len(data) - loaded_count} invalid)")
        except json.JSONDecodeError as e:
            self.persistence_error_count += 1
            logger.error(f"JSON decode error in persistence file: {e}")
            # Attempt recovery
            if self._recover_from_corruption():
                logger.info("Recovered from corruption, retrying load")
                self._load_signals()
            else:
                logger.error("Failed to recover from corruption, starting with empty signals")
        except Exception as e:
            self.persistence_error_count += 1
            logger.error(f"Failed to load persisted signals: {e}")
    
    def _save_signals(self, immediate: bool = False) -> None:
        """
        Save active signals to disk with backup and validation.
        
        Args:
            immediate: If True, save immediately. If False, use debounced batch write.
        """
        if immediate:
            self._save_signals_immediate()
        else:
            # Schedule debounced write
            self._schedule_debounced_write()
    
    def _save_signals_immediate(self) -> None:
        """Save signals immediately (synchronous)."""
        try:
            # Create backup before write
            self._backup_persistence_file()
            
            # Validate all signals before saving
            valid_signals = {}
            for symbol, signal in self.active_signals.items():
                if self._validate_signal(signal):
                    valid_signals[symbol] = signal
                else:
                    self.validation_error_count += 1
                    logger.warning(f"Skipping invalid signal {symbol} during save")
            
            data = {
                symbol: signal.to_dict()
                for symbol, signal in valid_signals.items()
            }
            
            # Write to temporary file first, then rename (atomic write)
            temp_path = self.persistence_path.with_suffix('.json.tmp')
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)
            
            # Atomic rename
            temp_path.replace(self.persistence_path)
            
            self.persistence_save_count += 1
            logger.debug(f"Saved {len(valid_signals)} signals to {self.persistence_path}")
        except Exception as e:
            self.persistence_error_count += 1
            logger.error(f"Failed to save signals: {e}")
    
    def _schedule_debounced_write(self) -> None:
        """Schedule a debounced write operation."""
        self._pending_write = True
        
        # Cancel existing timer if any
        if self._debounce_timer and not self._debounce_timer.done():
            self._debounce_timer.cancel()
        
        # Create new timer
        try:
            loop = asyncio.get_event_loop()
            self._debounce_timer = loop.create_task(self._debounced_write_task())
        except RuntimeError:
            # No event loop, save immediately
            self._save_signals_immediate()
    
    async def _debounced_write_task(self) -> None:
        """Debounced write task that waits before writing."""
        try:
            await asyncio.sleep(self._debounce_delay)
            if self._pending_write:
                self._save_signals_immediate()
                self._pending_write = False
        except asyncio.CancelledError:
            # Timer was cancelled, save now
            if self._pending_write:
                self._save_signals_immediate()
                self._pending_write = False
        except Exception as e:
            logger.error(f"Error in debounced write task: {e}")
    
    async def _async_save_signals(self) -> None:
        """Async version of save signals (non-blocking)."""
        # Run save in executor to avoid blocking
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._save_signals_immediate)
        except Exception as e:
            logger.error(f"Error in async save: {e}")
            # Fallback to immediate save
            self._save_signals_immediate()
    
    def cleanup_stale_signals(self, max_age_days: Optional[int] = None) -> int:
        """
        Remove stale signals older than max_age_days.
        
        Args:
            max_age_days: Maximum age in days (uses self.max_signal_age_days if None)
            
        Returns:
            Number of signals removed
        """
        if max_age_days is None:
            max_age_days = self.max_signal_age_days
        
        now = datetime.now(timezone.utc)
        max_age = timedelta(days=max_age_days)
        
        stale_signals = []
        for symbol, signal in list(self.active_signals.items()):
            age = now - signal.timestamp
            if age > max_age:
                stale_signals.append((symbol, age))
        
        for symbol, age in stale_signals:
            self.active_signals.pop(symbol, None)
            logger.info(f"Removed stale signal: {symbol} (age: {age.days} days)")
        
        if stale_signals:
            self._save_signals(immediate=True)  # Immediate save for cleanup
            logger.info(f"Cleaned up {len(stale_signals)} stale signals")
        
        return len(stale_signals)
    
    def mark_signal_exited(self, symbol: str, exit_reason: Optional[str] = None) -> bool:
        """
        Mark a signal as exited.
        
        Args:
            symbol: Symbol of signal to mark as exited
            exit_reason: Reason for exit (optional)
            
        Returns:
            True if signal was found and marked, False otherwise
        """
        if symbol not in self.active_signals:
            return False
        
        signal = self.active_signals[symbol]
        signal.lifecycle_state = SignalLifecycleState.EXITED
        signal.exit_timestamp = datetime.now(timezone.utc)
        signal.exit_reason = exit_reason
        
        self._save_signals(immediate=False)  # Use debounced write
        logger.info(f"Marked signal {symbol} as exited: {exit_reason or 'unknown reason'}")
        return True
    
    def cleanup_exited_signals(self, grace_period_hours: int = 24) -> int:
        """
        Remove exited signals after grace period.
        
        Args:
            grace_period_hours: Hours to keep exited signals before cleanup (default: 24)
            
        Returns:
            Number of signals removed
        """
        now = datetime.now(timezone.utc)
        grace_period = timedelta(hours=grace_period_hours)
        
        exited_signals = []
        for symbol, signal in list(self.active_signals.items()):
            if signal.lifecycle_state == SignalLifecycleState.EXITED:
                if signal.exit_timestamp:
                    age = now - signal.exit_timestamp
                    if age > grace_period:
                        exited_signals.append(symbol)
                else:
                    # Exited but no timestamp - remove immediately
                    exited_signals.append(symbol)
        
        for symbol in exited_signals:
            self.active_signals.pop(symbol, None)
            logger.debug(f"Removed exited signal: {symbol} (grace period expired)")
        
        if exited_signals:
            self.exited_signals_cleanup_count += len(exited_signals)
            self._save_signals(immediate=True)  # Immediate save for cleanup
            logger.info(f"Cleaned up {len(exited_signals)} exited signals")
        
        return len(exited_signals)
    
    def reconcile_signals(self, expected_symbols: Optional[List[str]] = None) -> Dict[str, int]:
        """
        Reconcile signals with expected state.
        
        Args:
            expected_symbols: List of symbols that should have active signals (optional)
            
        Returns:
            Dictionary with reconciliation results
        """
        results = {
            "total_signals": len(self.active_signals),
            "orphaned_signals": 0,
            "missing_signals": 0,
            "invalid_states": 0,
        }
        
        # Check for orphaned signals (signals not in expected list)
        if expected_symbols:
            for symbol in list(self.active_signals.keys()):
                if symbol not in expected_symbols:
                    results["orphaned_signals"] += 1
                    logger.warning(f"Orphaned signal detected: {symbol}")
            
            # Check for missing signals (expected but not present)
            for symbol in expected_symbols:
                if symbol not in self.active_signals:
                    results["missing_signals"] += 1
                    logger.warning(f"Missing expected signal: {symbol}")
        
        # Check for invalid lifecycle states
        for symbol, signal in self.active_signals.items():
            if signal.lifecycle_state not in [
                SignalLifecycleState.PENDING,
                SignalLifecycleState.ACTIVE,
                SignalLifecycleState.EXITED,
                SignalLifecycleState.EXPIRED,
            ]:
                results["invalid_states"] += 1
                logger.warning(f"Invalid lifecycle state for {symbol}: {signal.lifecycle_state}")
        
        if any(v > 0 for k, v in results.items() if k != "total_signals"):
            logger.warning(f"Signal reconciliation found issues: {results}")
        else:
            logger.debug(f"Signal reconciliation passed: {results}")
        
        return results
    
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
    ) -> bool:
        """
        Add a new signal to track.
        
        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            entry_price: Entry price
            size: Position size
            stop_loss: Stop loss price (optional)
            take_profit: Take profit price (optional)
            strategy_name: Strategy name
            reasoning: Signal reasoning (optional)
            
        Returns:
            True if signal was added successfully, False if validation failed
        """
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
            lifecycle_state=SignalLifecycleState.ACTIVE,
        )
        
        # Validate before adding
        if not self._validate_signal(signal):
            self.validation_error_count += 1
            logger.error(f"Failed to add signal {symbol}: validation failed")
            return False
        
        self.active_signals[symbol] = signal
        self._save_signals(immediate=False)  # Use debounced write
        logger.info(f"Added signal to tracker: {symbol} {direction} @ ${entry_price:.2f}")
        return True
    
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
        
        # Save after updating all PnL (debounced)
        if updated_pnls:
            self._save_signals(immediate=False)
        
        return updated_pnls
    
    def remove_signal(self, symbol: str, mark_exited: bool = True) -> Optional[TrackedSignal]:
        """
        Remove a signal from tracking.
        
        Args:
            symbol: Symbol to remove
            mark_exited: If True, mark as exited before removing (default: True)
            
        Returns:
            Removed signal or None
        """
        signal = self.active_signals.get(symbol)
        if signal:
            if mark_exited:
                signal.lifecycle_state = SignalLifecycleState.EXITED
                signal.exit_timestamp = datetime.now(timezone.utc)
            self.active_signals.pop(symbol, None)
            self._save_signals(immediate=False)  # Use debounced write
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
    
    def get_metrics(self) -> Dict:
        """
        Get signal tracking metrics.
        
        Returns:
            Dictionary with signal statistics and metrics
        """
        now = datetime.now(timezone.utc)
        signals = list(self.active_signals.values())
        
        # Calculate age distribution
        ages = []
        for signal in signals:
            age = (now - signal.timestamp).total_seconds() / 3600  # hours
            ages.append(age)
        
        # Lifecycle state distribution
        lifecycle_counts = {}
        for state in [SignalLifecycleState.PENDING, SignalLifecycleState.ACTIVE, 
                     SignalLifecycleState.EXITED, SignalLifecycleState.EXPIRED]:
            lifecycle_counts[state] = sum(1 for s in signals if s.lifecycle_state == state)
        
        metrics = {
            "active_signals_count": len(self.active_signals),
            "total_pnl": self.get_total_pnl(),
            "lifecycle_distribution": lifecycle_counts,
            "signal_age_stats": {
                "min_hours": min(ages) if ages else 0,
                "max_hours": max(ages) if ages else 0,
                "avg_hours": sum(ages) / len(ages) if ages else 0,
            },
            "persistence_operations": {
                "save_count": self.persistence_save_count,
                "load_count": self.persistence_load_count,
                "error_count": self.persistence_error_count,
                "success_rate": (
                    (self.persistence_save_count + self.persistence_load_count - self.persistence_error_count) /
                    max(1, self.persistence_save_count + self.persistence_load_count)
                ) if (self.persistence_save_count + self.persistence_load_count) > 0 else 1.0,
            },
            "validation_errors": self.validation_error_count,
            "exited_signals_cleaned": self.exited_signals_cleanup_count,
        }
        
        return metrics
    
    def clear(self) -> None:
        """Clear all tracked signals."""
        self.active_signals.clear()
        if self.persistence_path.exists():
            self.persistence_path.unlink()
        logger.info("SignalTracker cleared")
