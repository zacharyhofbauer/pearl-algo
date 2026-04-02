"""
Execution Adapter Base Interface

Defines the abstract interface for execution adapters and shared types.
All execution adapters (IBKR, paper, dry-run) implement this interface.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
from enum import Enum
from typing import Any, Dict, List, Optional

from pearlalgo.config import defaults
from pearlalgo.utils.logger import logger


class ExecutionMode(Enum):
    """Execution mode controls whether real orders are placed."""
    DRY_RUN = "dry_run"  # Log only, no orders
    PAPER = "paper"       # Paper trading account
    LIVE = "live"         # Live trading account


class OrderStatus(Enum):
    """Order status in the execution lifecycle."""
    PENDING = "pending"
    PLACED = "placed"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class ExecutionConfig:
    """
    Configuration for the execution layer.
    
    Safety defaults: enabled=False, armed=False, mode=dry_run
    This ensures no accidental order placement without explicit operator action.
    
    NOTE: Canonical defaults are in pearlalgo.config.defaults module.
    """
    # Master toggle - must be True for any execution to occur
    enabled: bool = defaults.EXECUTION_ENABLED
    
    # Arm/disarm - must be True to place orders (runtime toggle via /arm command)
    armed: bool = defaults.EXECUTION_ARMED
    
    # Execution mode
    mode: ExecutionMode = ExecutionMode.DRY_RUN
    
    # Risk limits
    max_positions: int = defaults.MAX_POSITIONS
    max_orders_per_day: int = defaults.MAX_ORDERS_PER_DAY
    max_daily_loss: float = defaults.MAX_DAILY_LOSS
    cooldown_seconds: int = defaults.COOLDOWN_SECONDS
    max_position_size_per_order: int = 1  # HARD CAP: never send more than this to broker
    
    # Reversal behavior: flatten existing position when opposite signal arrives
    allow_reversal_on_opposite_signal: bool = True  # If True, opposite signal closes existing position
    enforce_protection_guard: bool = False  # If True, block entries when positions lack protective orders
    
    # Symbol whitelist (empty = all symbols allowed)
    symbol_whitelist: List[str] = field(default_factory=lambda: defaults.DEFAULT_SYMBOL_WHITELIST.copy())
    
    # IBKR-specific
    ibkr_trading_client_id: int = defaults.IBKR_TRADING_CLIENT_ID
    ibkr_host: str = defaults.IBKR_HOST
    ibkr_port: int = defaults.IBKR_PORT
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "ExecutionConfig":
        """Create ExecutionConfig from a dictionary (e.g., from config.yaml)."""
        mode_str = config.get("mode", defaults.EXECUTION_MODE).lower()
        mode_map = {
            "dry_run": ExecutionMode.DRY_RUN,
            "paper": ExecutionMode.PAPER,
            "live": ExecutionMode.LIVE,
        }
        mode = mode_map.get(mode_str, ExecutionMode.DRY_RUN)

        # Parse and validate values
        max_positions = int(config.get("max_positions", defaults.MAX_POSITIONS))
        max_orders_per_day = int(config.get("max_orders_per_day", defaults.MAX_ORDERS_PER_DAY))
        max_daily_loss = float(config.get("max_daily_loss", defaults.MAX_DAILY_LOSS))
        cooldown_seconds = int(config.get("cooldown_seconds", defaults.COOLDOWN_SECONDS))

        # Validate ranges to prevent disabled risk controls
        if max_positions <= 0:
            logger.warning(f"Invalid max_positions={max_positions}, using default {defaults.MAX_POSITIONS}")
            max_positions = defaults.MAX_POSITIONS
        if max_orders_per_day <= 0:
            logger.warning(f"Invalid max_orders_per_day={max_orders_per_day}, using default {defaults.MAX_ORDERS_PER_DAY}")
            max_orders_per_day = defaults.MAX_ORDERS_PER_DAY
        if max_daily_loss <= 0:
            logger.warning(f"Invalid max_daily_loss={max_daily_loss}, using default {defaults.MAX_DAILY_LOSS}")
            max_daily_loss = defaults.MAX_DAILY_LOSS
        if cooldown_seconds < 0:
            logger.warning(f"Invalid cooldown_seconds={cooldown_seconds}, using default {defaults.COOLDOWN_SECONDS}")
            cooldown_seconds = defaults.COOLDOWN_SECONDS

        # Debug logging
        enforce_guard_val = bool(config.get("enforce_protection_guard", True))  # FIXED 2026-03-25: default True — always protect open positions
        logger.warning(f"🔍 ExecutionConfig.from_dict: enforce_protection_guard in config={('enforce_protection_guard' in config)}, value={config.get('enforce_protection_guard', 'NOT_FOUND')}, parsed={enforce_guard_val}")
        
        return cls(
            enabled=bool(config.get("enabled", defaults.EXECUTION_ENABLED)),
            armed=bool(config.get("armed", defaults.EXECUTION_ARMED)),
            mode=mode,
            max_positions=max_positions,
            max_orders_per_day=max_orders_per_day,
            max_daily_loss=max_daily_loss,
            cooldown_seconds=cooldown_seconds,
            max_position_size_per_order=int(config.get("max_position_size_per_order", 1)),
            symbol_whitelist=list(config.get("symbol_whitelist", defaults.DEFAULT_SYMBOL_WHITELIST)),
            allow_reversal_on_opposite_signal=bool(config.get("allow_reversal_on_opposite_signal", False)),
            enforce_protection_guard=enforce_guard_val,
            ibkr_trading_client_id=int(config.get("ibkr_trading_client_id", defaults.IBKR_TRADING_CLIENT_ID)),
            ibkr_host=str(config.get("ibkr_host", defaults.IBKR_HOST)),
            ibkr_port=int(config.get("ibkr_port", defaults.IBKR_PORT)),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "armed": self.armed,
            "mode": self.mode.value,
            "max_positions": self.max_positions,
            "max_orders_per_day": self.max_orders_per_day,
            "max_daily_loss": self.max_daily_loss,
            "cooldown_seconds": self.cooldown_seconds,
            "symbol_whitelist": self.symbol_whitelist,
            "allow_reversal_on_opposite_signal": self.allow_reversal_on_opposite_signal,
            "enforce_protection_guard": self.enforce_protection_guard,
            "ibkr_trading_client_id": self.ibkr_trading_client_id,
            "ibkr_host": self.ibkr_host,
            "ibkr_port": self.ibkr_port,
        }


@dataclass
class Position:
    """Represents a trading position."""
    symbol: str
    quantity: int  # Positive for long, negative for short
    avg_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    signal_id: Optional[str] = None  # Link back to originating signal
    entry_time: Optional[datetime] = None
    
    @property
    def direction(self) -> str:
        """Return 'long' or 'short' based on quantity."""
        return "long" if self.quantity > 0 else "short"
    
    @property
    def abs_quantity(self) -> int:
        """Return absolute position size."""
        return abs(self.quantity)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "direction": self.direction,
            "avg_price": self.avg_price,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "signal_id": self.signal_id,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
        }


@dataclass
class ExecutionDecision:
    """
    Decision about whether to execute a signal.
    
    Captures why a signal was executed or skipped for observability.
    """
    execute: bool  # True = place order, False = skip
    reason: str    # Human-readable reason
    signal_id: str
    
    # Optional modifiers
    size_multiplier: float = 1.0  # Adjust position size (from policy)
    adjusted_size: Optional[int] = None  # Final position size after adjustment
    
    # Optional strategy metadata
    policy_score: Optional[float] = None
    policy_recommendation: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "execute": self.execute,
            "reason": self.reason,
            "signal_id": self.signal_id,
            "size_multiplier": self.size_multiplier,
            "adjusted_size": self.adjusted_size,
            "policy_score": self.policy_score,
            "policy_recommendation": self.policy_recommendation,
        }


@dataclass
class ExecutionResult:
    """
    Result of an execution attempt.
    
    Tracks order placement outcome for state persistence and observability.
    """
    success: bool
    status: OrderStatus
    signal_id: str
    
    # Order details (if placed)
    order_id: Optional[str] = None
    parent_order_id: Optional[str] = None  # For bracket orders
    stop_order_id: Optional[str] = None
    take_profit_order_id: Optional[str] = None
    
    # Fill details
    fill_price: Optional[float] = None
    fill_quantity: Optional[int] = None
    fill_time: Optional[datetime] = None
    
    # Error details
    error_message: Optional[str] = None
    error_code: Optional[int] = None
    
    # Timing
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "status": self.status.value,
            "signal_id": self.signal_id,
            "order_id": self.order_id,
            "parent_order_id": self.parent_order_id,
            "stop_order_id": self.stop_order_id,
            "take_profit_order_id": self.take_profit_order_id,
            "fill_price": self.fill_price,
            "fill_quantity": self.fill_quantity,
            "fill_time": self.fill_time.strftime('%Y-%m-%dT%H:%M:%S') if self.fill_time else None,  # FIXED 2026-03-25: ET
            "error_message": self.error_message,
            "error_code": self.error_code,
            "timestamp": self.timestamp.strftime('%Y-%m-%dT%H:%M:%S'),  # FIXED 2026-03-25: ET
        }


class ExecutionAdapter(ABC):
    """
    Abstract base class for execution adapters.
    
    All execution adapters (IBKR, paper, dry-run) implement this interface.
    The adapter is responsible for:
    - Checking pre-conditions (armed, limits, cooldowns)
    - Placing bracket orders (entry + stop + take profit)
    - Tracking positions
    - Providing kill switch functionality
    """
    
    def __init__(self, config: ExecutionConfig):
        """Initialize with configuration."""
        self.config = config
        self._armed = config.armed
        self._orders_today = 0
        self._daily_pnl = 0.0
        self._last_order_time: Dict[str, datetime] = {}  # signal_type -> last order time
        self._positions: Dict[str, Position] = {}  # symbol -> position
        self._pending_orders: Dict[str, Dict] = {}  # order_id -> order info

        # Thread lock for concurrent access to counters
        self._counter_lock = threading.Lock()
    
    @property
    def armed(self) -> bool:
        """Check if execution is armed."""
        return self._armed
    
    def arm(self) -> bool:
        """
        Arm the execution adapter for order placement.
        
        Returns:
            True if successfully armed, False if preconditions not met
        """
        if not self.config.enabled:
            return False
        self._armed = True
        return True
    
    def disarm(self) -> None:
        """Disarm the execution adapter - no new orders will be placed."""
        self._armed = False
    
    def check_preconditions(self, signal: Dict) -> ExecutionDecision:
        """
        Check if all preconditions are met for executing a signal.
        
        Args:
            signal: Signal dictionary with entry_price, stop_loss, take_profit, etc.
            
        Returns:
            ExecutionDecision with execute=True if all checks pass
        """
        signal_id = signal.get("signal_id", "unknown")
        signal_type = signal.get("type", "unknown")
        symbol = signal.get("symbol", "MNQ")
        
        # Check 1: Execution enabled
        if not self.config.enabled:
            return ExecutionDecision(
                execute=False,
                reason="execution_disabled",
                signal_id=signal_id,
            )
        
        # Check 2: Armed
        if not self._armed:
            return ExecutionDecision(
                execute=False,
                reason="not_armed",
                signal_id=signal_id,
            )
        
        # Check 3: Symbol whitelist
        if self.config.symbol_whitelist and symbol not in self.config.symbol_whitelist:
            return ExecutionDecision(
                execute=False,
                reason=f"symbol_not_whitelisted:{symbol}",
                signal_id=signal_id,
            )
        
        # Check 4: Max positions
        current_positions = len([p for p in self._positions.values() if p.abs_quantity > 0])
        if current_positions >= self.config.max_positions:
            return ExecutionDecision(
                execute=False,
                reason=f"max_positions_reached:{current_positions}/{self.config.max_positions}",
                signal_id=signal_id,
            )
        
        # Check 5: Daily order limit
        if self._orders_today >= self.config.max_orders_per_day:
            return ExecutionDecision(
                execute=False,
                reason=f"max_daily_orders_reached:{self._orders_today}/{self.config.max_orders_per_day}",
                signal_id=signal_id,
            )
        
        # Check 6: Daily loss limit (kill switch)
        # SAFETY: Auto-disarm when daily loss limit is hit to prevent further execution
        # until operator explicitly re-arms (requires manual intervention)
        if self._daily_pnl <= -self.config.max_daily_loss:
            if self._armed:
                self.disarm()
                logger.warning(
                    f"🚨 AUTO-DISARM: Daily loss limit hit (${self._daily_pnl:.2f}). "
                    f"Re-arm manually with /arm when ready."
                )
            return ExecutionDecision(
                execute=False,
                reason=f"daily_loss_limit_hit:{self._daily_pnl:.2f}",
                signal_id=signal_id,
            )
        
        # Check 7: Cooldown per signal type
        if signal_type in self._last_order_time:
            elapsed = (datetime.now(timezone.utc) - self._last_order_time[signal_type]).total_seconds()
            if elapsed < self.config.cooldown_seconds:
                return ExecutionDecision(
                    execute=False,
                    reason=f"cooldown_active:{signal_type}:{int(self.config.cooldown_seconds - elapsed)}s_remaining",
                    signal_id=signal_id,
                )
        
        # ==========================================================================
        # BRACKET VALIDATION: Ensure signal has valid order geometry
        # ==========================================================================
        
        # Check 8: Direction must be "long" or "short"
        direction = str(signal.get("direction", "")).lower()
        if direction not in ("long", "short"):
            return ExecutionDecision(
                execute=False,
                reason=f"invalid_direction:{direction}",
                signal_id=signal_id,
            )
        
        # Check 9: Prices must be positive numbers
        try:
            entry_price = float(signal.get("entry_price", 0))
            stop_loss = float(signal.get("stop_loss", 0))
            take_profit = float(signal.get("take_profit", 0))
        except (TypeError, ValueError):
            return ExecutionDecision(
                execute=False,
                reason="invalid_prices:non_numeric",
                signal_id=signal_id,
            )
        
        if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
            return ExecutionDecision(
                execute=False,
                reason=f"invalid_prices:non_positive:entry={entry_price},sl={stop_loss},tp={take_profit}",
                signal_id=signal_id,
            )
        
        # Check 10: Bracket geometry must be correct for direction
        # Long: stop_loss < entry_price < take_profit
        # Short: take_profit < entry_price < stop_loss
        if direction == "long":
            if not (stop_loss < entry_price < take_profit):
                return ExecutionDecision(
                    execute=False,
                    reason=f"invalid_bracket_geometry:long:sl={stop_loss},entry={entry_price},tp={take_profit}",
                    signal_id=signal_id,
                )
        else:  # short
            if not (take_profit < entry_price < stop_loss):
                return ExecutionDecision(
                    execute=False,
                    reason=f"invalid_bracket_geometry:short:tp={take_profit},entry={entry_price},sl={stop_loss}",
                    signal_id=signal_id,
                )
        
        # Check 11: Position size must be a positive integer
        try:
            position_size = int(signal.get("position_size", 0))
        except (TypeError, ValueError):
            return ExecutionDecision(
                execute=False,
                reason="invalid_position_size:non_integer",
                signal_id=signal_id,
            )
        
        if position_size <= 0:
            return ExecutionDecision(
                execute=False,
                reason=f"invalid_position_size:non_positive:{position_size}",
                signal_id=signal_id,
            )
        
        # All checks passed
        return ExecutionDecision(
            execute=True,
            reason="preconditions_passed",
            signal_id=signal_id,
        )
    
    @abstractmethod
    async def place_bracket(self, signal: Dict) -> ExecutionResult:
        """
        Place a bracket order (entry + stop loss + take profit).
        
        Args:
            signal: Signal dictionary with:
                - signal_id: Unique signal identifier
                - symbol: Trading symbol (e.g., "MNQ")
                - direction: "long" or "short"
                - entry_price: Entry price
                - stop_loss: Stop loss price
                - take_profit: Take profit price
                - position_size: Number of contracts
                
        Returns:
            ExecutionResult with order details or error
        """
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> ExecutionResult:
        """
        Cancel a specific order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            ExecutionResult with cancellation status
        """
        pass
    
    @abstractmethod
    async def cancel_all(self) -> List[ExecutionResult]:
        """
        Cancel all open orders (kill switch).
        
        Returns:
            List of ExecutionResults for each cancellation
        """
        pass

    @abstractmethod
    async def flatten_all_positions(self) -> List[ExecutionResult]:
        """
        Flatten all open broker positions (kill switch).

        This should place market orders to offset any open positions, and is
        intended to be used as part of an emergency/kill-switch workflow.

        Returns:
            List of ExecutionResults for each flatten order (or a single no-op result).
        """
        pass
    
    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """
        Get current positions.
        
        Returns:
            List of Position objects
        """
        pass
    
    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to the broker.
        
        Returns:
            True if connected successfully
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the broker."""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to the broker."""
        pass
    
    def reset_daily_counters(self) -> None:
        """Reset daily counters (call at start of each trading day)."""
        with self._counter_lock:
            self._orders_today = 0
            self._daily_pnl = 0.0
            self._last_order_time.clear()

    def update_daily_pnl(self, pnl_change: float) -> None:
        """Update daily P&L tracking."""
        with self._counter_lock:
            self._daily_pnl += pnl_change

    def increment_order_count(self, signal_type: str) -> None:
        """Increment order count and record last order time (thread-safe)."""
        with self._counter_lock:
            self._orders_today += 1
            self._last_order_time[signal_type] = datetime.now(timezone.utc)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current execution status for observability."""
        return {
            "enabled": self.config.enabled,
            "armed": self._armed,
            "mode": self.config.mode.value,
            "connected": self.is_connected(),
            "orders_today": self._orders_today,
            "daily_pnl": self._daily_pnl,
            "positions": len([p for p in self._positions.values() if p.abs_quantity > 0]),
            "max_positions": self.config.max_positions,
            "max_orders_per_day": self.config.max_orders_per_day,
            "max_daily_loss": self.config.max_daily_loss,
        }
