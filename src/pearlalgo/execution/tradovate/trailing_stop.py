"""
Trailing Stop Manager for Tradovate Execution

Implements a 3-phase ratcheting stop that progressively tightens as a trade
moves in the favorable direction:

1. Breakeven: After 1.0 ATR favorable -> move stop to entry + 1 tick
2. Lock profit: After 2.0 ATR favorable -> trail 1.5 ATR behind best price
3. Tight trail: After 3.0 ATR favorable -> trail 1.0 ATR behind best price

The stop only ever moves in the favorable direction (ratchet — never loosens).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TrailingPhase:
    """Configuration for a single trailing stop phase."""
    name: str
    activation_atr: float  # ATR multiples of favorable move to activate
    trail_atr: float       # ATR multiples to trail behind best price (0.0 = breakeven)


@dataclass
class TrailingState:
    """Tracks trailing stop state for a single position."""
    entry_price: float
    direction: str  # "long" or "short"
    current_stop: float  # Current stop price
    best_price: float    # Best favorable price seen
    current_phase: Optional[str] = None  # Active phase name
    last_modified_stop: float = 0.0  # Last stop price sent to broker


class TrailingStopManager:
    """
    Manages trailing stops for open positions.

    Call check_and_update() on each price tick/bar to determine if the stop
    should be moved. The manager returns the new stop price if a modification
    is needed, or None if no change.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize from config dict.

        Expected config format:
            trailing_stop:
              enabled: true
              min_move_points: 0.50
              phases:
                - name: breakeven
                  activation_atr: 1.0
                  trail_atr: 0.0
                - name: lock_profit
                  activation_atr: 2.0
                  trail_atr: 1.5
                - name: tight_trail
                  activation_atr: 3.0
                  trail_atr: 1.0
        """
        ts_config = config.get("trailing_stop", {})
        self.enabled = bool(ts_config.get("enabled", False))
        self.min_move_points = float(ts_config.get("min_move_points", 0.50))

        # Parse phases (sorted by activation_atr descending for checking highest first)
        raw_phases = ts_config.get("phases", [])
        self.phases: List[TrailingPhase] = []
        for p in raw_phases:
            self.phases.append(TrailingPhase(
                name=str(p.get("name", "unknown")),
                activation_atr=float(p.get("activation_atr", 0)),
                trail_atr=float(p.get("trail_atr", 0)),
            ))
        self.phases.sort(key=lambda x: x.activation_atr, reverse=True)

        # Active trailing states keyed by contract_id or position identifier
        self._states: Dict[str, TrailingState] = {}

        if self.enabled:
            logger.info(
                f"TrailingStopManager initialized: {len(self.phases)} phases, "
                f"min_move={self.min_move_points}pts"
            )

    def register_position(
        self,
        position_id: str,
        entry_price: float,
        direction: str,
        initial_stop: float,
    ) -> None:
        """Register a new position for trailing stop tracking."""
        self._states[position_id] = TrailingState(
            entry_price=entry_price,
            direction=direction.lower(),
            current_stop=initial_stop,
            best_price=entry_price,
            last_modified_stop=initial_stop,
        )
        logger.info(
            f"Trailing stop registered: {position_id} | {direction} @ {entry_price} | "
            f"initial_stop={initial_stop}"
        )

    def remove_position(self, position_id: str) -> None:
        """Remove a position from tracking (after exit)."""
        if position_id in self._states:
            del self._states[position_id]

    def check_and_update(
        self,
        position_id: str,
        current_price: float,
        current_atr: float,
    ) -> Optional[float]:
        """
        Check if the trailing stop should be updated for a position.

        Args:
            position_id: Unique position identifier
            current_price: Current market price
            current_atr: Current ATR value

        Returns:
            New stop price if modification needed, None otherwise.
        """
        if not self.enabled or not self.phases:
            return None

        state = self._states.get(position_id)
        if state is None:
            return None

        if current_atr <= 0:
            return None

        # Update best price
        if state.direction == "long":
            state.best_price = max(state.best_price, current_price)
            favorable_move = state.best_price - state.entry_price
        else:
            state.best_price = min(state.best_price, current_price)
            favorable_move = state.entry_price - state.best_price

        if favorable_move <= 0:
            return None

        # Check phases (highest activation first)
        new_stop = None
        active_phase = None

        for phase in self.phases:
            if favorable_move >= phase.activation_atr * current_atr:
                if phase.trail_atr == 0.0:
                    # Breakeven: entry + 1 tick
                    tick = 0.25  # MNQ tick size
                    if state.direction == "long":
                        candidate = state.entry_price + tick
                    else:
                        candidate = state.entry_price - tick
                else:
                    trail_distance = phase.trail_atr * current_atr
                    if state.direction == "long":
                        candidate = state.best_price - trail_distance
                    else:
                        candidate = state.best_price + trail_distance

                new_stop = candidate
                active_phase = phase.name
                break  # Use the highest activated phase

        if new_stop is None:
            return None

        # Ratchet: only move in favorable direction
        if state.direction == "long" and new_stop <= state.current_stop:
            return None
        if state.direction == "short" and new_stop >= state.current_stop:
            return None

        # Min move filter: avoid API churn
        move_size = abs(new_stop - state.last_modified_stop)
        if move_size < self.min_move_points:
            return None

        # Update state
        old_stop = state.current_stop
        state.current_stop = new_stop
        state.last_modified_stop = new_stop
        state.current_phase = active_phase

        logger.info(
            f"Trailing stop update: {position_id} | phase={active_phase} | "
            f"stop {old_stop:.2f} -> {new_stop:.2f} | "
            f"best={state.best_price:.2f} | move={favorable_move:.2f}pts"
        )

        return new_stop

    def get_state(self, position_id: str) -> Optional[Dict[str, Any]]:
        """Get current trailing state for a position (for logging/debugging)."""
        state = self._states.get(position_id)
        if state is None:
            return None
        return {
            "entry_price": state.entry_price,
            "direction": state.direction,
            "current_stop": state.current_stop,
            "best_price": state.best_price,
            "current_phase": state.current_phase,
        }

    @property
    def active_positions(self) -> int:
        """Number of positions being tracked."""
        return len(self._states)
