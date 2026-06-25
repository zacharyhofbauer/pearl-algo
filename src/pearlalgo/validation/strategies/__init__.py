"""Isolated, self-contained signal sources for the validation head-to-head.

Config flags on the live composite strategy can't isolate ORB / VWAP-reversion /
pure-Pine (the base EMA-cross always fires), so each baseline is its own
strategy_fn here with the contract expected by scripts/ops/backtest_config.py:

    fn(df, config=None, current_time=None) -> list[signal_dict]

where each signal_dict has: direction, entry_price, stop_loss, take_profit,
confidence, entry_trigger, signal_id. Indicators (EMA, session-anchored VWAP,
Wilder ATR, RTH gating) are computed here so these are faithful to the Pine
definitions, not the live confidence-scoring engine.
"""
from __future__ import annotations

from .signal_fns import (
    STRATEGY_FNS,
    hourly_defender_signals,
    opening_drive_5_signals,
    opening_drive_signals,
    orb_signals,
    overnight_seasonality_signals,
    pine_simple_signals,
    tod_rth_long_signals,
    vwap_reversion_signals,
)

__all__ = [
    "STRATEGY_FNS",
    "pine_simple_signals",
    "orb_signals",
    "vwap_reversion_signals",
    "hourly_defender_signals",
    "opening_drive_signals",
    "opening_drive_5_signals",
    "tod_rth_long_signals",
    "overnight_seasonality_signals",
]
