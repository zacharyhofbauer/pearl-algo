"""
Advanced Exit Manager - Implements 4 exit strategies:
1. Quick Exit (Stalled Trades) - Exit when no momentum develops
2. Time-Based Exits - Take profit if holding profitable position too long
3. Stop Optimization - Dynamic stop adjustment based on volatility
4. Partial Profit Runner - Progressive stop management to let winners run
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import logging
import pytz

_ET = pytz.timezone("America/New_York")

logger = logging.getLogger(__name__)


# ============================================================================
# PARTIAL PROFIT RUNNER (Upgrade 2)
# ============================================================================

class RunnerPhase(Enum):
    """Phases of the partial profit runner strategy."""
    INITIAL = "initial"       # Entry to 1.5x ATR: normal SL/TP bracket
    BREAKEVEN = "breakeven"   # 1.5x ATR hit: cancel TP, move SL to BE+0.25
    TIGHT_TRAIL = "tight_trail"  # 2.5x ATR hit: tighten trailing to 1.0x ATR, no TP


class PartialRunnerState:
    """Tracks the runner state for a single position."""

    def __init__(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        breakeven_trigger_atr: float = 1.5,
        tight_trail_trigger_atr: float = 2.5,
        tight_trail_distance_atr: float = 1.0,
        breakeven_offset: float = 0.25,
    ):
        self.entry_price = entry_price
        self.direction = direction  # "long" or "short"
        self.atr = atr
        self.breakeven_trigger_atr = breakeven_trigger_atr
        self.tight_trail_trigger_atr = tight_trail_trigger_atr
        self.tight_trail_distance_atr = tight_trail_distance_atr
        self.breakeven_offset = breakeven_offset
        self.phase = RunnerPhase.INITIAL
        self.best_price = entry_price
        self.tp_cancelled = False

    @property
    def favorable_move(self) -> float:
        """How far price has moved in favorable direction (in ATR multiples)."""
        if self.direction == "long":
            return (self.best_price - self.entry_price) / self.atr if self.atr > 0 else 0.0
        else:
            return (self.entry_price - self.best_price) / self.atr if self.atr > 0 else 0.0

    def update(self, current_price: float) -> Tuple[Optional[str], Optional[float], bool]:
        """Update runner state with current price.

        Returns: (action, new_stop_price, should_cancel_tp)
            action: None, "move_to_breakeven", or "tighten_trail"
            new_stop_price: The new stop price if action is taken, else None
            should_cancel_tp: True if the TP order should be cancelled
        """
        # Update best price
        if self.direction == "long":
            self.best_price = max(self.best_price, current_price)
        else:
            self.best_price = min(self.best_price, current_price)

        fav_move = self.favorable_move

        action = None
        new_stop = None
        cancel_tp = False

        # Phase transitions
        if self.phase == RunnerPhase.INITIAL and fav_move >= self.breakeven_trigger_atr:
            # Phase 1 -> Phase 2: Move to breakeven + small offset
            self.phase = RunnerPhase.BREAKEVEN
            if self.direction == "long":
                new_stop = self.entry_price + self.breakeven_offset
            else:
                new_stop = self.entry_price - self.breakeven_offset
            cancel_tp = not self.tp_cancelled
            self.tp_cancelled = True
            action = "move_to_breakeven"
            logger.info(
                f"Runner Phase 2 (breakeven): {self.direction} entry={self.entry_price:.2f} "
                f"best={self.best_price:.2f} fav={fav_move:.1f}x ATR → "
                f"new_stop={new_stop:.2f}, cancel_tp={cancel_tp}"
            )

        if self.phase == RunnerPhase.BREAKEVEN and fav_move >= self.tight_trail_trigger_atr:
            # Phase 2 -> Phase 3: Tight trailing stop
            self.phase = RunnerPhase.TIGHT_TRAIL
            trail_dist = self.atr * self.tight_trail_distance_atr
            if self.direction == "long":
                new_stop = self.best_price - trail_dist
            else:
                new_stop = self.best_price + trail_dist
            action = "tighten_trail"
            logger.info(
                f"Runner Phase 3 (tight trail): {self.direction} "
                f"best={self.best_price:.2f} fav={fav_move:.1f}x ATR → "
                f"trail_stop={new_stop:.2f} (dist={trail_dist:.2f})"
            )

        elif self.phase == RunnerPhase.TIGHT_TRAIL:
            # Continue tightening in Phase 3
            trail_dist = self.atr * self.tight_trail_distance_atr
            if self.direction == "long":
                candidate = self.best_price - trail_dist
                if new_stop is None or candidate > new_stop:
                    new_stop = candidate
                    action = "tighten_trail"
            else:
                candidate = self.best_price + trail_dist
                if new_stop is None or candidate < new_stop:
                    new_stop = candidate
                    action = "tighten_trail"

        return action, new_stop, cancel_tp


class PartialRunnerManager:
    """Manages partial profit runner states for all positions."""

    def __init__(self, config: Dict):
        # Support both 'partial_runner' (legacy) and 'runner_mode' (new) config keys
        pr_cfg = config.get("runner_mode") or config.get("partial_runner", {})
        self.enabled = bool(pr_cfg.get("enabled", False))
        self.breakeven_trigger_atr = float(pr_cfg.get("breakeven_trigger_atr", 1.5))
        # Support both key names: runner_trigger_atr (runner_mode) and tight_trail_trigger_atr (legacy)
        self.tight_trail_trigger_atr = float(
            pr_cfg.get("runner_trigger_atr", pr_cfg.get("tight_trail_trigger_atr", 2.5))
        )
        self.tight_trail_distance_atr = float(
            pr_cfg.get("runner_trail_distance_atr", pr_cfg.get("tight_trail_distance_atr", 1.0))
        )
        self.remove_fixed_tp = bool(pr_cfg.get("remove_fixed_tp", True))
        self.breakeven_offset = float(
            pr_cfg.get("breakeven_offset_points", pr_cfg.get("breakeven_offset", 0.25))
        )

        # Active runner states: position_id -> PartialRunnerState
        self._states: Dict[str, PartialRunnerState] = {}

        if self.enabled:
            logger.info(
                f"PartialRunnerManager initialized: "
                f"BE_trigger={self.breakeven_trigger_atr}x ATR, "
                f"tight_trigger={self.tight_trail_trigger_atr}x ATR, "
                f"tight_dist={self.tight_trail_distance_atr}x ATR, "
                f"remove_tp={self.remove_fixed_tp}"
            )

    def register_position(
        self,
        position_id: str,
        entry_price: float,
        direction: str,
        atr: float,
    ) -> None:
        """Register a new position for runner tracking."""
        if not self.enabled:
            return
        self._states[position_id] = PartialRunnerState(
            entry_price=entry_price,
            direction=direction,
            atr=atr,
            breakeven_trigger_atr=self.breakeven_trigger_atr,
            tight_trail_trigger_atr=self.tight_trail_trigger_atr,
            tight_trail_distance_atr=self.tight_trail_distance_atr,
            breakeven_offset=self.breakeven_offset,
        )
        logger.info(f"Runner registered: pos={position_id} entry={entry_price:.2f} dir={direction} atr={atr:.2f}")

    def update_position(
        self,
        position_id: str,
        current_price: float,
    ) -> Tuple[Optional[str], Optional[float], bool]:
        """Update a tracked position.

        Returns: (action, new_stop_price, should_cancel_tp)
        """
        if not self.enabled or position_id not in self._states:
            return None, None, False
        return self._states[position_id].update(current_price)

    def remove_position(self, position_id: str) -> None:
        """Remove a closed position from tracking."""
        self._states.pop(position_id, None)

    def get_phase(self, position_id: str) -> Optional[str]:
        """Get the current phase for a position."""
        state = self._states.get(position_id)
        return state.phase.value if state else None

    def get_all_states(self) -> Dict[str, Dict]:
        """Get summary of all tracked runner states."""
        result = {}
        for pid, state in self._states.items():
            result[pid] = {
                "phase": state.phase.value,
                "entry_price": state.entry_price,
                "direction": state.direction,
                "best_price": state.best_price,
                "favorable_move_atr": state.favorable_move,
                "tp_cancelled": state.tp_cancelled,
            }
        return result


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

        # Strategy 4: Partial Profit Runner
        self.runner = PartialRunnerManager(config)

        logger.info(f"AdvancedExitManager initialized: quick_exit={self.quick_exit_enabled}, "
                   f"time_based={self.time_exit_enabled}, stop_opt={self.stop_opt_enabled}, "
                   f"partial_runner={self.runner.enabled}")
    
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

        # Calculate hold duration — FIXED 2026-03-25: naive ET
        now_et = datetime.now(_ET).replace(tzinfo=None)
        et_naive = entry_time.replace(tzinfo=None) if entry_time.tzinfo else entry_time
        duration_min = (now_et - et_naive).total_seconds() / 60

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

        # Calculate hold duration — FIXED 2026-03-25: naive ET
        now_et = datetime.now(_ET).replace(tzinfo=None)
        et_naive = entry_time.replace(tzinfo=None) if entry_time.tzinfo else entry_time
        duration_min = (now_et - et_naive).total_seconds() / 60

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

    def check_runner_promotion(
        self,
        position_id: str,
        current_price: float,
    ) -> Tuple[Optional[str], Optional[float], bool]:
        """Check if a tracked position should be promoted through runner phases.

        Delegates to the PartialRunnerManager. Call this each monitoring cycle
        for open positions.

        Returns:
            (action, new_stop_price, should_cancel_tp)
            action: None, "move_to_breakeven", or "tighten_trail"
            new_stop_price: new stop price if action taken
            should_cancel_tp: True if TP order should be cancelled
        """
        return self.runner.update_position(position_id, current_price)
