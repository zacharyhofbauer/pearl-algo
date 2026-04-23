"""Focused tests for extracted directional confidence helpers."""

from __future__ import annotations

import pytest

from pearlalgo.trading_bots import signal_generator as sg


def test_initialize_directional_score_prefers_first_matching_trigger() -> None:
    params = sg.StrategyParams()

    state = sg._initialize_directional_score(
        "long",
        sg.DirectionalTriggers(
            ema_cross=True,
            mean_reversion=True,
            trend_momentum=True,
        ),
        params,
    )

    assert state is not None
    assert state.entry_trigger == "ema_cross"
    assert state.confidence == pytest.approx(params.base_confidence)
    assert state.active_indicators == ["EMA_CROSS", "VWAP_ABOVE"]


def test_apply_directional_confidence_adjustments_long_keeps_existing_order() -> None:
    params = sg.StrategyParams()
    state = sg.DirectionalScoreState(
        confidence=params.base_confidence,
        entry_trigger="ema_cross",
        active_indicators=["EMA_CROSS", "VWAP_ABOVE"],
    )

    sg._apply_directional_confidence_adjustments(
        state,
        sg.DirectionalConfidenceContext(
            direction="long",
            close=100.1,
            atr=1.0,
            volume_confirmed=True,
            sr_signal="sr_breakout_long",
            sr_confidence=0.8,
            tbt_signal="tbt_breakout_long",
            tbt_confidence=0.7,
            sd_signal="sd_demand_bounce",
            key_levels={
                "prev_day_low": 100.0,
                "prev_week_low": 99.7,
                "prev_day_high": 100.35,
                "prev_week_high": 100.5,
            },
            key_level_signal="bounce_support_long",
            key_level_confidence=0.12,
            key_level_info={"nearest_support_name": "prev_day_low"},
            vwap_band_signal="near_vwap_above",
            or_state={
                "or_defined": True,
                "or_high": 100.0,
                "or_low": 99.0,
                "session_open_price": 99.0,
            },
        ),
        params,
    )

    # Issue 7-A: the additive sum (previously 1.375) now clamps to 1.0 so
    # downstream consumers see an in-range value. The pre-clamp sum is
    # preserved inline so a future refactor of individual boosts stays
    # auditable.
    assert state.confidence == pytest.approx(1.0)
    assert state.active_indicators == [
        "EMA_CROSS",
        "VWAP_ABOVE",
        "VOL_CONFIRM",
        "SR:sr_breakout_long",
        "TBT:tbt_breakout_long",
        "SD:sd_demand_bounce",
        "VWAP_NEAR",
        "KEY_BOUNCE:prev_day_low",
        "PDL_BOUNCE",
        "PWL_BOUNCE",
        "PDH_CAUTION",
        "PWH_CAUTION",
        "OR_BREAKOUT_CONFIRM",
    ]


def test_apply_directional_confidence_adjustments_short_uses_short_specific_labels() -> None:
    params = sg.StrategyParams()
    state = sg.DirectionalScoreState(
        confidence=0.55,
        entry_trigger="vwap_reclaim",
        active_indicators=["VWAP_RECLAIM", "VOL_CONFIRM"],
    )

    sg._apply_directional_confidence_adjustments(
        state,
        sg.DirectionalConfidenceContext(
            direction="short",
            close=99.9,
            atr=1.0,
            volume_confirmed=True,
            sr_signal="sr_breakout_short",
            sr_confidence=0.6,
            tbt_signal="tbt_breakout_short",
            tbt_confidence=0.7,
            sd_signal="sd_supply_rejection",
            key_levels={
                "prev_day_high": 100.0,
                "prev_week_high": 100.3,
                "prev_day_low": 99.7,
                "prev_week_low": 99.5,
            },
            key_level_signal="bounce_resistance_short",
            key_level_confidence=0.12,
            key_level_info={"nearest_resistance_name": "prev_day_high"},
            vwap_band_signal="near_vwap_below",
            or_state={
                "or_defined": True,
                "or_high": 101.0,
                "or_low": 100.0,
                "session_open_price": 101.0,
            },
        ),
        params,
    )

    # Issue 7-A: pre-clamp sum was 1.415; now clamped to the advertised
    # [0.0, 1.0] invariant.
    assert state.confidence == pytest.approx(1.0)
    assert state.active_indicators == [
        "VWAP_RECLAIM",
        "VOL_CONFIRM",
        "VOL_CONFIRM",
        "SR:sr_breakout_short",
        "TBT:tbt_breakout_short",
        "SD:sd_supply_rejection",
        "VWAP_NEAR",
        "KEY_BOUNCE:prev_day_high",
        "PDH_BOUNCE",
        "PWH_BOUNCE",
        "PDL_CAUTION",
        "PWL_CAUTION",
        "OR_BREAKDOWN_CONFIRM",
    ]