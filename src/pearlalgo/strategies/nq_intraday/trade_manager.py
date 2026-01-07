"""
Trade Manager for NQ Intraday Strategy

Handles trade lifecycle management including:
- Trailing stop loss updates
- Breakeven protection
- Swing vs scalp trade management
- Exit logic
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pearlalgo.utils.logger import logger


@dataclass
class Trade:
    """Represents an active trade."""
    
    signal_id: str
    trade_type: str  # 'swing' or 'scalp'
    direction: str  # 'long' or 'short'
    entry_price: float
    stop_loss: float
    take_profit: float
    contracts: int
    entry_time: datetime
    current_price: float
    breakeven_moved: bool = False
    trailing_active: bool = False
    last_stop_update: Optional[datetime] = None


class TrailingStopManager:
    """Manages trailing stop loss and breakeven protection for trades."""
    
    def __init__(self, config: Dict):
        """Initialize trailing stop manager.
        
        Args:
            config: Configuration dictionary with trailing_stop settings
        """
        trailing_config = config.get("trailing_stop", {}) or {}
        self.enabled = bool(trailing_config.get("enabled", False))
        self.breakeven_immediate = bool(trailing_config.get("breakeven_immediate", True))
        self.trail_method = str(trailing_config.get("trail_method", "dynamic"))
        self.early_profit_trail_atr = float(trailing_config.get("early_profit_trail_atr", 0.5))
        self.medium_profit_trail_atr = float(trailing_config.get("medium_profit_trail_atr", 1.0))
        self.large_profit_trail_atr = float(trailing_config.get("large_profit_trail_atr", 1.5))
        self.update_frequency_bars = int(trailing_config.get("update_frequency_bars", 1))
        self.never_widen = bool(trailing_config.get("never_widen", True))
        self.min_profit_before_be = float(trailing_config.get("min_profit_before_be", 2.0))
        
        logger.info(
            "TrailingStopManager initialized: enabled=%s, breakeven_immediate=%s, method=%s",
            self.enabled,
            self.breakeven_immediate,
            self.trail_method,
        )
    
    def update_stop(self, trade: Trade, current_price: float, atr: float) -> Optional[float]:
        """Update stop loss based on profit level and ATR.
        
        Args:
            trade: Trade object
            current_price: Current market price
            atr: Current ATR value
            
        Returns:
            New stop price if updated, None otherwise
        """
        if not self.enabled:
            return None
        
        # Calculate current profit
        if trade.direction == "long":
            profit_points = current_price - trade.entry_price
        else:  # short
            profit_points = trade.entry_price - current_price
        
        # Phase 1: Move to breakeven immediately when in profit
        if profit_points > 0 and not trade.breakeven_moved:
            # Check minimum profit threshold before moving to BE
            if profit_points >= self.min_profit_before_be:
                new_stop = trade.entry_price
                if self._should_update_stop(trade, new_stop):
                    trade.stop_loss = new_stop
                    trade.breakeven_moved = True
                    trade.trailing_active = True
                    trade.last_stop_update = datetime.now(timezone.utc)
                    logger.info(
                        "Stop moved to breakeven: signal_id=%s, entry=%.2f, stop=%.2f, profit=%.2f",
                        trade.signal_id,
                        trade.entry_price,
                        new_stop,
                        profit_points,
                    )
                    return new_stop
        
        # Phase 2: Dynamic trailing (only if already at breakeven or in profit)
        if profit_points > 0 and trade.breakeven_moved:
            return self._update_trailing_stop(trade, current_price, atr, profit_points)
        
        return None
    
    def _update_trailing_stop(
        self, trade: Trade, current_price: float, atr: float, profit_points: float
    ) -> Optional[float]:
        """Update trailing stop using dynamic ATR-based method.
        
        Args:
            trade: Trade object
            current_price: Current market price
            atr: Current ATR value
            profit_points: Current profit in points
            
        Returns:
            New stop price if updated, None otherwise
        """
        if atr <= 0:
            return None
        
        # Calculate profit in ATR units
        profit_atr_ratio = profit_points / atr
        
        # Determine trail distance based on profit level
        if profit_atr_ratio < 1.0:
            trail_distance = self.early_profit_trail_atr * atr
        elif profit_atr_ratio < 2.0:
            trail_distance = self.medium_profit_trail_atr * atr
        else:
            trail_distance = self.large_profit_trail_atr * atr
        
        # Calculate new stop price
        if trade.direction == "long":
            new_stop = current_price - trail_distance
            # Only move stop in favorable direction (up)
            if new_stop > trade.stop_loss:
                if self._should_update_stop(trade, new_stop):
                    trade.stop_loss = new_stop
                    trade.trailing_active = True
                    trade.last_stop_update = datetime.now(timezone.utc)
                    logger.debug(
                        "Trailing stop updated: signal_id=%s, stop=%.2f, profit=%.2f (%.1fx ATR)",
                        trade.signal_id,
                        new_stop,
                        profit_points,
                        profit_atr_ratio,
                    )
                    return new_stop
        else:  # short
            new_stop = current_price + trail_distance
            # Only move stop in favorable direction (down)
            if new_stop < trade.stop_loss or trade.stop_loss == 0:
                if self._should_update_stop(trade, new_stop):
                    trade.stop_loss = new_stop
                    trade.trailing_active = True
                    trade.last_stop_update = datetime.now(timezone.utc)
                    logger.debug(
                        "Trailing stop updated: signal_id=%s, stop=%.2f, profit=%.2f (%.1fx ATR)",
                        trade.signal_id,
                        new_stop,
                        profit_points,
                        profit_atr_ratio,
                    )
                    return new_stop
        
        return None
    
    def _should_update_stop(self, trade: Trade, new_stop: float) -> bool:
        """Check if stop should be updated.
        
        Args:
            trade: Trade object
            new_stop: Proposed new stop price
            
        Returns:
            True if stop should be updated
        """
        if not self.never_widen:
            return True
        
        # Never widen: only move stop in favorable direction
        if trade.direction == "long":
            return new_stop >= trade.stop_loss
        else:  # short
            return new_stop <= trade.stop_loss or trade.stop_loss == 0


class TradeManager:
    """Manages trade lifecycle including classification, stops, and exits."""
    
    def __init__(self, config: Dict):
        """Initialize trade manager.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.trailing_stop_manager = TrailingStopManager(config)
        self.active_trades: Dict[str, Trade] = {}
        
        # Swing trading config
        swing_config = config.get("swing_trading", {}) or {}
        self.swing_enabled = bool(swing_config.get("enabled", False))
        self.swing_max_hold_hours = float(swing_config.get("max_hold_hours", 8))
        
        logger.info(
            "TradeManager initialized: trailing_stops=%s, swing_trading=%s",
            self.trailing_stop_manager.enabled,
            self.swing_enabled,
        )
    
    def add_trade(self, signal: Dict) -> Trade:
        """Add a new trade from a signal.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Trade object
        """
        trade = Trade(
            signal_id=signal.get("id", ""),
            trade_type=signal.get("trade_type", "scalp"),
            direction=signal.get("direction", "long"),
            entry_price=float(signal.get("entry_price", 0)),
            stop_loss=float(signal.get("stop_loss", 0)),
            take_profit=float(signal.get("take_profit", 0)),
            contracts=int(signal.get("contracts", 5)),
            entry_time=datetime.now(timezone.utc),
            current_price=float(signal.get("entry_price", 0)),
        )
        
        self.active_trades[trade.signal_id] = trade
        
        logger.info(
            "Trade added: signal_id=%s, type=%s, direction=%s, entry=%.2f, stop=%.2f, target=%.2f",
            trade.signal_id,
            trade.trade_type,
            trade.direction,
            trade.entry_price,
            trade.stop_loss,
            trade.take_profit,
        )
        
        return trade
    
    def update_trades(self, market_data: Dict) -> List[Dict]:
        """Update all active trades with current market data.
        
        Handles edge cases:
        - Overnight gaps (favorable and unfavorable)
        - Volatility spikes (ATR expansion)
        - End of day exits
        - Multiple concurrent trades (NO LIMITS)
        
        Args:
            market_data: Market data dictionary with current price, ATR, etc.
            
        Returns:
            List of exit signals (trades that should be closed)
        """
        if not self.active_trades:
            return []
        
        current_price = float(market_data.get("current_price", 0))
        atr = float(market_data.get("atr", 10.0))
        previous_price = float(market_data.get("previous_price", current_price))
        current_time = datetime.now(timezone.utc)
        is_market_open = bool(market_data.get("market_open", True))
        
        exit_signals = []
        
        for signal_id, trade in list(self.active_trades.items()):
            # Edge case: Detect gap moves (overnight gaps)
            gap_size = abs(current_price - previous_price) if previous_price > 0 else 0
            if gap_size > atr * 2.0:  # Significant gap (2x ATR)
                gap_direction = "favorable" if (
                    (trade.direction == "long" and current_price > previous_price) or
                    (trade.direction == "short" and current_price < previous_price)
                ) else "unfavorable"
                
                if gap_direction == "favorable":
                    # Favorable gap: Update stop immediately to protect profit
                    logger.info(
                        "Favorable gap detected: signal_id=%s, gap=%.2f, updating stop",
                        signal_id,
                        gap_size,
                    )
                else:
                    # Unfavorable gap: Check if stop was hit
                    if trade.direction == "long" and current_price <= trade.stop_loss:
                        exit_signals.append({
                            "signal_id": signal_id,
                            "exit_reason": "stop_loss_gap",
                            "exit_price": current_price,
                            "exit_time": current_time,
                        })
                        del self.active_trades[signal_id]
                        logger.info(
                            "Trade exited via gap: signal_id=%s, gap=%.2f, exit_price=%.2f",
                            signal_id,
                            gap_size,
                            current_price,
                        )
                        continue
                    elif trade.direction == "short" and current_price >= trade.stop_loss:
                        exit_signals.append({
                            "signal_id": signal_id,
                            "exit_reason": "stop_loss_gap",
                            "exit_price": current_price,
                            "exit_time": current_time,
                        })
                        del self.active_trades[signal_id]
                        logger.info(
                            "Trade exited via gap: signal_id=%s, gap=%.2f, exit_price=%.2f",
                            signal_id,
                            gap_size,
                            current_price,
                        )
                        continue
            
            trade.current_price = current_price
            
            # Edge case: Volatility spike - use rolling ATR if available
            rolling_atr = float(market_data.get("rolling_atr", atr))
            if rolling_atr > atr * 1.5:  # ATR expanded significantly
                logger.debug(
                    "Volatility spike detected: signal_id=%s, atr=%.2f -> %.2f",
                    signal_id,
                    atr,
                    rolling_atr,
                )
                # Use rolling ATR for trailing stop calculation
                effective_atr = rolling_atr
            else:
                effective_atr = atr
            
            # Update trailing stop
            if self.trailing_stop_manager.enabled:
                new_stop = self.trailing_stop_manager.update_stop(trade, current_price, effective_atr)
                if new_stop:
                    trade.stop_loss = new_stop
            
            # Edge case: End of day exit (16:10 ET for futures)
            et_hour = current_time.hour if current_time.tzinfo else 0
            if et_hour >= 16 or (et_hour == 16 and current_time.minute >= 10):
                if trade.trade_type == "swing":
                    exit_signals.append({
                        "signal_id": signal_id,
                        "exit_reason": "end_of_day",
                        "exit_price": current_price,
                        "exit_time": current_time,
                    })
                    del self.active_trades[signal_id]
                    logger.info(
                        "Swing trade exited at end of day: signal_id=%s, exit_price=%.2f",
                        signal_id,
                        current_price,
                    )
                    continue
            
            # Check exit conditions
            exit_reason = self._should_exit(trade, current_price, current_time)
            if exit_reason:
                exit_signals.append({
                    "signal_id": signal_id,
                    "exit_reason": exit_reason,
                    "exit_price": current_price,
                    "exit_time": current_time,
                })
                del self.active_trades[signal_id]
                logger.info(
                    "Trade exited: signal_id=%s, reason=%s, exit_price=%.2f",
                    signal_id,
                    exit_reason,
                    current_price,
                )
        
        return exit_signals
    
    def _should_exit(self, trade: Trade, current_price: float, current_time: datetime) -> Optional[str]:
        """Check if trade should be exited.
        
        Args:
            trade: Trade object
            current_price: Current market price
            current_time: Current time
            
        Returns:
            Exit reason if should exit, None otherwise
        """
        # Check stop loss
        if trade.direction == "long":
            if current_price <= trade.stop_loss:
                return "stop_loss"
        else:  # short
            if current_price >= trade.stop_loss:
                return "stop_loss"
        
        # Check take profit
        if trade.direction == "long":
            if current_price >= trade.take_profit:
                return "take_profit"
        else:  # short
            if current_price <= trade.take_profit:
                return "take_profit"
        
        # Check end of day for swing trades
        if trade.trade_type == "swing":
            hold_time_hours = (current_time - trade.entry_time).total_seconds() / 3600
            if hold_time_hours >= self.swing_max_hold_hours:
                return "end_of_day"
        
        return None
    
    def get_active_trades(self) -> List[Trade]:
        """Get all active trades.
        
        Returns:
            List of active Trade objects
        """
        return list(self.active_trades.values())
    
    def remove_trade(self, signal_id: str) -> bool:
        """Remove a trade.
        
        Args:
            signal_id: Signal ID
            
        Returns:
            True if trade was removed, False if not found
        """
        if signal_id in self.active_trades:
            del self.active_trades[signal_id]
            return True
        return False

