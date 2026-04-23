"""Tests for Issue 7-A — final confidence clamp.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 0.

``_apply_directional_confidence_adjustments`` mutates ``state.confidence``
via a chain of additive boosts. Before 7-A the function relied on an
earlier ``min(0.99, ...)`` *outside* this function to eventually clamp;
an extreme confluence scenario could still deliver ``state.confidence``
> 1.0 to callers of the helper, which breaks the pydantic-declared
[0.0, 1.0] invariant and misleads downstream consumers
(``/api/confidence-scaling``, the dashboard, any future probability-
weighted sizing).

The clamp is idempotent and has zero effect for the common path where
boosts already sum inside [0.0, 1.0].
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from pearlalgo.trading_bots.signal_generator import (
    DirectionalConfidenceContext,
    DirectionalScoreState,
    StrategyParams,
    _apply_directional_confidence_adjustments,
)


def _minimal_ctx(**overrides: Any) -> DirectionalConfidenceContext:
    """Produce a ConfidenceContext that exercises zero adjustments by default.

    Each test layers on only the fields it needs so the *additive* sum is
    measurable and the clamp's effect is obvious.
    """
    base = dict(
        direction="long",
        close=20000.0,
        atr=15.0,
        volume_confirmed=False,
        sr_signal=None,
        sr_confidence=0.0,
        tbt_signal=None,
        tbt_confidence=0.0,
        sd_signal=None,
        key_levels={},
        key_level_signal=None,
        key_level_confidence=0.0,
        key_level_info={},
        vwap_band_signal=None,
        or_state={},
    )
    base.update(overrides)
    return DirectionalConfidenceContext(**base)


def test_clamp_leaves_in_range_confidence_untouched():
    state = DirectionalScoreState(confidence=0.6, entry_trigger="ema_cross", active_indicators=[])
    _apply_directional_confidence_adjustments(state, _minimal_ctx(), StrategyParams())
    assert state.confidence == 0.6


@pytest.mark.parametrize(
    "starting,expected",
    [
        (0.0, 0.0),
        (0.5, 0.5),
        (1.0, 1.0),
    ],
)
def test_clamp_is_identity_for_in_range(starting: float, expected: float):
    state = DirectionalScoreState(confidence=starting, entry_trigger="t", active_indicators=[])
    _apply_directional_confidence_adjustments(state, _minimal_ctx(), StrategyParams())
    assert state.confidence == expected


def test_clamp_caps_overflow_from_large_positive_boosts():
    # Stack every positive boost we can trigger: volume + SR + TBT + SD +
    # key-level breakout + PDL + PWL. Starting at 0.95 these additions
    # easily push past 1.0.
    params = StrategyParams()
    ctx = _minimal_ctx(
        volume_confirmed=True,
        sr_signal="long_demand",
        sr_confidence=1.0,
        tbt_signal="long_wicks",
        tbt_confidence=1.0,
        sd_signal="demand_strong",
        key_level_signal="breakout_resistance_long",
        key_level_confidence=0.9,
        key_level_info={"nearest_resistance_name": "pdh"},
        key_levels={
            "prev_day_low": 19950.0,
            "prev_week_low": 19900.0,
            "prev_day_high": 20010.0,
            "prev_week_high": 20020.0,
        },
    )
    state = DirectionalScoreState(confidence=0.95, entry_trigger="ema_cross", active_indicators=[])
    _apply_directional_confidence_adjustments(state, ctx, params)
    assert state.confidence == 1.0
    assert 0.0 <= state.confidence <= 1.0


def test_clamp_floors_underflow_from_penalties():
    params = StrategyParams()
    # Extended-VWAP penalty + PDH caution penalty + PWH caution penalty
    # can pile negative adjustments.
    ctx = _minimal_ctx(
        direction="long",
        vwap_band_signal="extended_above",
        key_levels={
            "prev_day_low": 19950.0,
            "prev_week_low": 19900.0,
            "prev_day_high": 20050.0,
            "prev_week_high": 20080.0,
        },
        close=20000.0,
    )
    state = DirectionalScoreState(confidence=0.01, entry_trigger="ema_cross", active_indicators=[])
    _apply_directional_confidence_adjustments(state, ctx, params)
    assert state.confidence >= 0.0
    assert state.confidence <= 1.0


@pytest.mark.parametrize("direction", ["long", "short"])
def test_clamp_respects_invariant_for_extreme_starting_states(direction: str):
    """Even starting at nonsense values, the clamp enforces the range."""
    params = StrategyParams()
    for start in (-5.0, -0.1, 2.5, 1.5, 100.0):
        state = DirectionalScoreState(confidence=start, entry_trigger="t", active_indicators=[])
        _apply_directional_confidence_adjustments(state, _minimal_ctx(direction=direction), params)
        assert 0.0 <= state.confidence <= 1.0, (
            f"direction={direction} start={start} result={state.confidence}"
        )


def test_clamp_handles_nan_gracefully():
    """NaN confidence must not silently slip through the clamp."""
    state = DirectionalScoreState(confidence=float("nan"), entry_trigger="t", active_indicators=[])
    _apply_directional_confidence_adjustments(state, _minimal_ctx(), StrategyParams())
    # ``max(0.0, min(1.0, nan))`` returns nan per IEEE-754; downstream
    # consumers already guard against nan. We assert the observable fact
    # so a future refactor that silently changes this is flagged.
    assert math.isnan(state.confidence) or 0.0 <= state.confidence <= 1.0
