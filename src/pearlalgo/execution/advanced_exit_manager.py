"""
Advanced Exit Manager - Implements 3 additional exit strategies:
1. Quick Exit (Stalled Trades) - Exit when no momentum develops
2. Time-Based Exits - Take profit if holding profitable position too long
3. Stop Optimization - Dynamic stop adjustment based on volatility
"""
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class AdvancedExitManager:
    """Manages advanced exit logic beyond basic stop/target"""
    
    def __init__(self, config: Dict):
        self.config = config
        
        # Strategy 1: Quick Exit (Stalled Trades)
        self.quick_exit_enabled = config.get('quick_exit', {}).get('enabled', False)
        self.quick_exit_min_duration_min = config.get('quick_exit', {}).get('min_duration_minutes', 20)
        self.quick_exit_max_mfe = config.get('quick_exit', {}).get('max_mfe_threshold', 20)
        self.quick_exit_min_mae = config.get('quick_exit', {}).get('min_mae_threshold', 60)
        
        # Strategy 2: Time-Based Exits
        self.time_exit_enabled = config.get('time_based_exit', {}).get('enabled', False)
        self.time_exit_min_duration_min = config.get('time_based_exit', {}).get('min_duration_minutes', 10)
        self.time_exit_min_profit = config.get('time_based_exit', {}).get('min_profit_threshold', 30)
        self.time_exit_take_pct = config.get('time_based_exit', {}).get('take_percentage', 0.70)
        
        # Strategy 3: Stop Optimization
        self.stop_opt_enabled = config.get('stop_optimization', {}).get('enabled', False)
        self.stop_opt_mae_percentile = config.get('stop_optimization', {}).get('mae_percentile', 75)
        
        logger.info(f"AdvancedExitManager initialized: quick_exit={self.quick_exit_enabled}, "
                   f"time_based={self.time_exit_enabled}, stop_opt={self.stop_opt_enabled}")
    
    def check_quick_exit(self, position: Dict, current_price: float, entry_time: datetime) -> Tuple[bool, str]:
        """
        Strategy 1: Quick Exit for Stalled Trades
        
        Exit if:
        - Trade has been open for min_duration_minutes
        - Maximum profit (MFE) is low (< max_mfe_threshold)
        - Maximum loss (MAE) is high (> min_mae_threshold)
        
        This catches trades that never develop momentum and saves on dead trades.
        
        Returns: (should_exit, reason)
        """
        if not self.quick_exit_enabled:
            return False, ""
        
        # Calculate hold duration
        duration_min = (datetime.now() - entry_time).total_seconds() / 60
        
        if duration_min < self.quick_exit_min_duration_min:
            return False, ""
        
        # Get MFE and MAE
        mfe = position.get('mfe_dollars', 0)
        mae = position.get('mae_dollars', 0)
        current_pnl = position.get('unrealized_pnl', 0)
        
        # Check if stalled: low profit potential, high drawdown
        if mfe < self.quick_exit_max_mfe and mae > self.quick_exit_min_mae:
            reason = (f"Quick exit: stalled trade (MFE ${mfe:.2f} < ${self.quick_exit_max_mfe}, "
                     f"MAE ${mae:.2f} > ${self.quick_exit_min_mae}, {duration_min:.0f} min)")
            logger.info(f"🚪 {reason}")
            return True, reason
        
        return False, ""
    
    def check_time_based_exit(self, position: Dict, current_price: float, entry_time: datetime) -> Tuple[bool, str]:
        """
        Strategy 2: Time-Based Profit Taking
        
        Exit if:
        - Trade has been profitable for min_duration_minutes
        - Current profit > min_profit_threshold
        - Take take_percentage of max profit seen
        
        This prevents giving back profits on trades that stall after hitting good profit.
        
        Returns: (should_exit, reason)
        """
        if not self.time_exit_enabled:
            return False, ""
        
        # Calculate hold duration
        duration_min = (datetime.now() - entry_time).total_seconds() / 60
        
        if duration_min < self.time_exit_min_duration_min:
            return False, ""
        
        # Get current P&L and MFE
        current_pnl = position.get('unrealized_pnl', 0)
        mfe = position.get('mfe_dollars', 0)
        
        # Check if profitable and has been for a while
        if current_pnl > self.time_exit_min_profit and mfe > self.time_exit_min_profit:
            # If current profit has fallen below take_percentage of max, exit
            target_exit = mfe * self.time_exit_take_pct
            
            if current_pnl < target_exit and current_pnl > 0:
                reason = (f"Time-based exit: profit declining (current ${current_pnl:.2f} < "
                         f"{self.time_exit_take_pct*100:.0f}% of max ${mfe:.2f}, {duration_min:.0f} min)")
                logger.info(f"⏰ {reason}")
                return True, reason
        
        return False, ""
    
    def get_optimized_stop(self, atr: float, historical_mae_data: list) -> float:
        """
        Strategy 3: Stop Optimization
        
        Calculate optimal stop distance based on historical MAE distribution.
        
        Returns: stop distance in dollars
        """
        if not self.stop_opt_enabled or not historical_mae_data:
            return atr * 4.0  # Default 4 ATR stop
        
        # Sort MAE data
        sorted_mae = sorted(historical_mae_data)
        
        # Get percentile-based stop
        percentile_idx = int(len(sorted_mae) * (self.stop_opt_mae_percentile / 100))
        optimized_stop = sorted_mae[percentile_idx] if percentile_idx < len(sorted_mae) else sorted_mae[-1]
        
        # Don't go tighter than 2 ATR or wider than 5 ATR
        min_stop = atr * 2.0
        max_stop = atr * 5.0
        
        optimized_stop = max(min_stop, min(optimized_stop, max_stop))
        
        logger.info(f"🎯 Optimized stop: ${optimized_stop:.2f} "
                   f"(based on {self.stop_opt_mae_percentile}th percentile of {len(sorted_mae)} trades)")
        
        return optimized_stop
    
    def should_exit(self, position: Dict, current_price: float, entry_time: datetime) -> Tuple[bool, str]:
        """
        Check all exit strategies and return first one that triggers.
        
        Priority order:
        1. Quick Exit (highest priority - save losses)
        2. Time-Based Exit (medium - lock profits)
        3. Stop Optimization (passive - better stop placement)
        
        Returns: (should_exit, reason)
        """
        # Check quick exit first (most important - saves losses)
        should_exit, reason = self.check_quick_exit(position, current_price, entry_time)
        if should_exit:
            return True, reason
        
        # Check time-based exit second (locks profits)
        should_exit, reason = self.check_time_based_exit(position, current_price, entry_time)
        if should_exit:
            return True, reason
        
        return False, ""
