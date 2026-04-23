"""Tests for Issue 5-A — hard-coded confidence floors + StrategyParams drift.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 0.

Covers:
  * Every trigger in ``_initialize_directional_score`` honors its tunable base
    confidence (no hard-coded ``0.55`` shadows remain).
  * New tunables ``mean_reversion_base_confidence`` and
    ``vwap_reclaim_base_confidence`` are surfaced on ``StrategyParams`` with
    the same pydantic bounds as other base-confidence fields.
  * ``min_confidence`` / ``min_confidence_long`` / ``min_confidence_short``
    in-code defaults now match live YAML (0.60 each).
"""

from __future__ import annotations

import pytest

from pearlalgo.trading_bots.signal_generator import (
    DirectionalScoreState,
    DirectionalTriggers,
    StrategyParams,
    _initialize_directional_score,
)

_TRIGGER_ATTRS: tuple[str, ...] = (
    "ema_cross",
    "vwap_cross",
    "vwap_retest",
    "trend_breakout",
    "mean_reversion",
    "ema_pullback",
    "vwap_reclaim",
    "trend_momentum",
)


def _single_trigger(attr: str) -> DirectionalTriggers:
    """Return a DirectionalTriggers with exactly `attr` set True."""
    kwargs = {name: False for name in _TRIGGER_ATTRS}
    kwargs[attr] = True
    return DirectionalTriggers(**kwargs)


def _tuned_params() -> StrategyParams:
    """Return StrategyParams with every base confidence pushed up to 0.80.

    If any trigger still hard-codes 0.55 it will fail the ``>= 0.80`` check.
    """
    return StrategyParams(
        base_confidence=0.80,
        mean_reversion_base_confidence=0.80,
        vwap_reclaim_base_confidence=0.80,
    )


@pytest.mark.parametrize("trigger_attr", _TRIGGER_ATTRS)
@pytest.mark.parametrize("direction", ["long", "short"])
def test_every_trigger_honors_tunable_base_confidence(trigger_attr: str, direction: str):
    """Every trigger returns confidence >= the tunable floor (no 0.55 shadow)."""
    triggers = _single_trigger(trigger_attr)
    params = _tuned_params()
    state = _initialize_directional_score(direction, triggers, params)
    assert state is not None, f"trigger {trigger_attr}/{direction} returned None"
    assert isinstance(state, DirectionalScoreState)
    assert state.confidence >= 0.80, (
        f"trigger {trigger_attr}/{direction} returned confidence="
        f"{state.confidence} < tuned floor 0.80 (hard-coded 0.55 may remain)"
    )
    assert state.entry_trigger == trigger_attr


def test_initialize_directional_score_returns_none_when_no_trigger_fired():
    params = StrategyParams()
    empty = DirectionalTriggers(**{name: False for name in _TRIGGER_ATTRS})
    assert _initialize_directional_score("long", empty, params) is None


def test_strategy_params_defaults_match_live_yaml_confidence_floors():
    """In-code defaults must match config/live/tradovate_paper.yaml
    (0.60 / 0.60 / 0.60). Previously 0.55 / 0.72 / 0.60."""
    params = StrategyParams()
    assert params.min_confidence == 0.60
    assert params.min_confidence_long == 0.60
    assert params.min_confidence_short == 0.60


def test_strategy_params_long_short_symmetric_by_default():
    """Prior 0.72/0.60 asymmetry silently biased the system long."""
    params = StrategyParams()
    assert params.min_confidence_long == params.min_confidence_short


def test_mean_reversion_and_vwap_reclaim_tunables_exposed():
    """New fields are first-class StrategyParams attributes with bounds."""
    params = StrategyParams()
    assert params.mean_reversion_base_confidence == 0.55  # preserves prior behavior
    assert params.vwap_reclaim_base_confidence == 0.55

    # Bounds honored by pydantic
    StrategyParams(mean_reversion_base_confidence=0.0)
    StrategyParams(mean_reversion_base_confidence=1.0)
    with pytest.raises(Exception):
        StrategyParams(mean_reversion_base_confidence=1.5)
    with pytest.raises(Exception):
        StrategyParams(vwap_reclaim_base_confidence=-0.1)


def test_mean_reversion_trigger_uses_tunable_not_literal():
    """Move the tunable up to 0.90 — confidence must follow."""
    triggers = _single_trigger("mean_reversion")
    params = StrategyParams(mean_reversion_base_confidence=0.90)
    state = _initialize_directional_score("long", triggers, params)
    assert state is not None
    assert state.confidence == 0.90


def test_vwap_reclaim_trigger_uses_tunable_not_literal():
    triggers = _single_trigger("vwap_reclaim")
    params = StrategyParams(vwap_reclaim_base_confidence=0.90)
    state = _initialize_directional_score("short", triggers, params)
    assert state is not None
    assert state.confidence == 0.90


def test_mean_reversion_and_vwap_reclaim_independent():
    """Tuning one must not affect the other."""
    triggers_mr = _single_trigger("mean_reversion")
    triggers_vr = _single_trigger("vwap_reclaim")
    params = StrategyParams(
        mean_reversion_base_confidence=0.80,
        vwap_reclaim_base_confidence=0.60,
    )
    mr_state = _initialize_directional_score("long", triggers_mr, params)
    vr_state = _initialize_directional_score("long", triggers_vr, params)
    assert mr_state is not None and vr_state is not None
    assert mr_state.confidence == 0.80
    assert vr_state.confidence == 0.60
