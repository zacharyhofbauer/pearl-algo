"""
Trailing Stop Manager for Tradovate Execution

Implements a 3-phase ratcheting stop that progressively tightens as a trade
moves in the favorable direction:

1. Breakeven: After 1.0 ATR favorable -> move stop to entry + 1 tick
2. Lock profit: After 2.0 ATR favorable -> trail 1.5 ATR behind best price
3. Tight trail: After 3.0 ATR favorable -> trail 1.0 ATR behind best price

The stop only ever moves in the favorable direction (ratchet — never loosens).

Supports dynamic parameter overrides from OpenClaw or regime-adaptive presets.
Overrides scale the phase multipliers but never violate the ratchet invariant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Hard bounds for override multipliers — prevents absurd values
MULTIPLIER_MIN = 0.5
MULTIPLIER_MAX = 2.0


def _clamp(value: float, lo: float = MULTIPLIER_MIN, hi: float = MULTIPLIER_MAX) -> float:
    return max(lo, min(hi, value))


@dataclass
class TrailingOverride:
    """Dynamic parameter override for trailing stop behavior."""
    trail_atr_multiplier: float = 1.0       # Scale trail_atr (0.5 = 50% tighter)
    activation_atr_multiplier: float = 1.0  # Scale activation thresholds
    force_phase: Optional[str] = None       # Force a specific phase
    min_move_override: Optional[float] = None  # Override min_move_points
    expires_at: Optional[datetime] = None
    source: str = "default"                 # Who set it: "openclaw", "regime", "manual"
    reason: str = ""

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    def clamp(self) -> TrailingOverride:
        """Return a copy with multipliers clamped to safe bounds."""
        return TrailingOverride(
            trail_atr_multiplier=_clamp(self.trail_atr_multiplier),
            activation_atr_multiplier=_clamp(self.activation_atr_multiplier),
            force_phase=self.force_phase,
            min_move_override=self.min_move_override,
            expires_at=self.expires_at,
            source=self.source,
            reason=self.reason,
        )


# Regime-adaptive presets — applied automatically when no external override is active
REGIME_PRESETS: Dict[str, TrailingOverride] = {
    "trending": TrailingOverride(
        trail_atr_multiplier=1.2,
        source="regime",
        reason="Trending - wider trail to let winners run",
    ),
    "volatile": TrailingOverride(
        trail_atr_multiplier=0.7,
        source="regime",
        reason="Volatile - tighter trail to protect gains",
    ),
    "ranging": TrailingOverride(
        trail_atr_multiplier=0.85,
        source="regime",
        reason="Ranging - slightly tighter for quick exits",
    ),
}


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

    Supports dynamic overrides that scale phase parameters. Overrides can come
    from OpenClaw (via API), regime presets, or manual operator commands.
    The ratchet invariant is always enforced after override calculations.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize from config dict.

        Expected config format:
            trailing_stop:
              enabled: true
              min_move_points: 0.50
              allow_external_override: true
              regime_adaptive: true
              override_bounds:
                trail_atr_multiplier: [0.5, 2.0]
                activation_atr_multiplier: [0.5, 2.0]
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
        self.allow_external_override = bool(ts_config.get("allow_external_override", True))
        self.regime_adaptive = bool(ts_config.get("regime_adaptive", True))
        self.max_override_ttl_minutes = int(ts_config.get("max_override_ttl_minutes", 120))

        # Parse override bounds from config
        bounds = ts_config.get("override_bounds", {})
        trail_bounds = bounds.get("trail_atr_multiplier", [MULTIPLIER_MIN, MULTIPLIER_MAX])
        act_bounds = bounds.get("activation_atr_multiplier", [MULTIPLIER_MIN, MULTIPLIER_MAX])
        self._trail_mult_bounds = (float(trail_bounds[0]), float(trail_bounds[1]))
        self._act_mult_bounds = (float(act_bounds[0]), float(act_bounds[1]))

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

        # Active override (None = use defaults)
        self._override: Optional[TrailingOverride] = None

        if self.enabled:
            logger.info(
                f"TrailingStopManager initialized: {len(self.phases)} phases, "
                f"min_move={self.min_move_points}pts, "
                f"regime_adaptive={self.regime_adaptive}, "
                f"allow_external_override={self.allow_external_override}"
            )

    def apply_override(self, override: TrailingOverride) -> None:
        """Apply a parameter override. Clamps multipliers to configured bounds."""
        clamped = TrailingOverride(
            trail_atr_multiplier=_clamp(
                override.trail_atr_multiplier,
                self._trail_mult_bounds[0],
                self._trail_mult_bounds[1],
            ),
            activation_atr_multiplier=_clamp(
                override.activation_atr_multiplier,
                self._act_mult_bounds[0],
                self._act_mult_bounds[1],
            ),
            force_phase=override.force_phase,
            min_move_override=override.min_move_override,
            expires_at=override.expires_at,
            source=override.source,
            reason=override.reason,
        )
        self._override = clamped
        logger.info(
            f"Trailing stop override applied: source={clamped.source} | "
            f"trail_mult={clamped.trail_atr_multiplier:.2f} | "
            f"act_mult={clamped.activation_atr_multiplier:.2f} | "
            f"force_phase={clamped.force_phase} | "
            f"reason={clamped.reason} | "
            f"expires_at={clamped.expires_at}"
        )

    def apply_regime_preset(self, regime: str) -> None:
        """Apply a regime-based preset if regime_adaptive is enabled and no external override."""
        if not self.regime_adaptive:
            return
        # Don't overwrite external (openclaw/manual) overrides with regime presets
        if self._override and self._override.source not in ("regime", "default"):
            return
        preset = REGIME_PRESETS.get(regime)
        if preset:
            self._override = preset
            logger.debug(f"Regime preset applied: {regime} -> trail_mult={preset.trail_atr_multiplier}")

    def clear_override(self) -> None:
        """Clear the active override, reverting to default parameters."""
        if self._override:
            logger.info(f"Trailing stop override cleared (was: source={self._override.source})")
            self._override = None

    def get_override(self) -> Optional[Dict[str, Any]]:
        """Get current override state (for API/debugging)."""
        if self._override is None:
            return None
        remaining = None
        if self._override.expires_at:
            delta = self._override.expires_at - datetime.now(timezone.utc)
            remaining = max(0, delta.total_seconds() / 60.0)
        return {
            "trail_atr_multiplier": self._override.trail_atr_multiplier,
            "activation_atr_multiplier": self._override.activation_atr_multiplier,
            "force_phase": self._override.force_phase,
            "source": self._override.source,
            "reason": self._override.reason,
            "expires_in_minutes": remaining,
        }

    def _get_effective_override(self) -> Optional[TrailingOverride]:
        """Get the active override, auto-clearing if expired."""
        if self._override is None:
            return None
        if self._override.is_expired():
            logger.info(f"Trailing stop override expired (source={self._override.source})")
            self._override = None
            return None
        return self._override

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

        # Get effective override (auto-clears expired)
        override = self._get_effective_override()
        trail_mult = override.trail_atr_multiplier if override else 1.0
        act_mult = override.activation_atr_multiplier if override else 1.0
        forced_phase = override.force_phase if override else None
        min_move = (override.min_move_override if override and override.min_move_override is not None
                    else self.min_move_points)

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
            # If force_phase is set, skip to the forced phase
            if forced_phase and phase.name != forced_phase:
                continue

            activation_threshold = phase.activation_atr * act_mult * current_atr

            if favorable_move >= activation_threshold:
                if phase.trail_atr == 0.0:
                    # Breakeven: entry + 1 tick
                    tick = 0.25  # MNQ tick size
                    if state.direction == "long":
                        candidate = state.entry_price + tick
                    else:
                        candidate = state.entry_price - tick
                else:
                    trail_distance = phase.trail_atr * trail_mult * current_atr
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
        if move_size < min_move:
            return None

        # Update state
        old_stop = state.current_stop
        state.current_stop = new_stop
        state.last_modified_stop = new_stop
        state.current_phase = active_phase

        override_info = f" | override={override.source}" if override else ""
        logger.info(
            f"Trailing stop update: {position_id} | phase={active_phase} | "
            f"stop {old_stop:.2f} -> {new_stop:.2f} | "
            f"best={state.best_price:.2f} | move={favorable_move:.2f}pts"
            f"{override_info}"
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

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get trailing state for all tracked positions."""
        result = {}
        for pid, state in self._states.items():
            result[pid] = {
                "entry_price": state.entry_price,
                "direction": state.direction,
                "current_stop": state.current_stop,
                "best_price": state.best_price,
                "current_phase": state.current_phase,
            }
        return result

    @property
    def active_positions(self) -> int:
        """Number of positions being tracked."""
        return len(self._states)
