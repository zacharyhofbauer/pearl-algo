"""
Deterministic fixtures for trade-overlay visual regression tests.

These helpers are intentionally shared between:
- Visual regression tests under `tests/`
- Baseline generation scripts under `scripts/testing/`

They do NOT duplicate production code; they only create deterministic synthetic
inputs (trade dicts) for exercising chart overlay rendering.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from pearlalgo.market_agent.chart_profiles import (
    apply_telegram_trade_overlay_defaults,
    apply_telegram_unified_profile,
)

def apply_telegram_render_profile(cfg: Any) -> None:
    """
    Apply a best-effort Telegram/mobile render profile to a ChartConfig-like object.

    This mirrors the service-layer Telegram profile (without requiring the service).
    """

    apply_telegram_unified_profile(cfg)
    apply_telegram_trade_overlay_defaults(cfg)


def _make_trade(
    *,
    direction: str,
    entry_time,
    entry_price: float,
    exit_time,
    exit_price: float,
) -> Dict[str, Any]:
    """Create a trade dict compatible with ChartGenerator's trade overlay."""

    dir_norm = str(direction or "long").lower()
    if dir_norm not in {"long", "short"}:
        dir_norm = "long"

    tick_value = 2.0  # MNQ-ish dollars per point (visual-only)
    if dir_norm == "long":
        pnl = (float(exit_price) - float(entry_price)) * tick_value
    else:
        pnl = (float(entry_price) - float(exit_price)) * tick_value

    return {
        "direction": dir_norm,
        "entry_time": entry_time,
        "entry_price": float(entry_price),
        "exit_time": exit_time,
        "exit_price": float(exit_price),
        "pnl": float(pnl),
    }


def build_trade_list(
    data: pd.DataFrame,
    *,
    lookback_bars: int,
    num_trades: int,
    spacing_bars: int,
    hold_bars: int,
    start_offset_into_window: int = 6,
) -> List[Dict[str, Any]]:
    """
    Build a deterministic set of synthetic trades within the visible lookback window.

    This is intentionally synthetic: we are testing readability/rendering, not strategy logic.
    """

    if data is None or data.empty:
        return []

    df = data.copy()
    if "timestamp" not in df.columns:
        return []

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
    if df.empty:
        return []

    n = len(df)
    window_start = max(0, n - int(lookback_bars))
    start_idx = min(n - 2, window_start + max(0, int(start_offset_into_window)))

    trades: List[Dict[str, Any]] = []
    for i in range(int(num_trades)):
        entry_idx = start_idx + (i * int(spacing_bars))
        if entry_idx >= n - 2:
            break

        exit_idx = min(n - 1, entry_idx + max(1, int(hold_bars)))

        entry_time = df["timestamp"].iloc[entry_idx]
        exit_time = df["timestamp"].iloc[exit_idx]

        # Use OHLC-derived prices so markers sit near real candles.
        entry_price = float(df["close"].iloc[entry_idx])

        # Alternate direction; nudge exit to create a mix of wins/losses.
        direction = "long" if i % 2 == 0 else "short"
        base_exit_price = float(df["close"].iloc[exit_idx])
        delta = 10.0 + (i % 4) * 2.5  # deterministic variety

        if direction == "long":
            exit_price = base_exit_price + (delta if (i % 3 != 0) else -delta)
        else:
            exit_price = base_exit_price - (delta if (i % 3 != 0) else -delta)

        trades.append(
            _make_trade(
                direction=direction,
                entry_time=entry_time,
                entry_price=entry_price,
                exit_time=exit_time,
                exit_price=exit_price,
            )
        )

    return trades


def deterministic_regime_info(*, confidence: float = 0.64) -> Dict[str, Any]:
    """
    Small deterministic regime_info payload for exercising optional HUD badges.

    Chart code treats this as best-effort: if it can't render, it will skip.
    """

    conf = float(confidence)
    conf = max(0.0, min(1.0, conf))
    return {
        "regime": "test_regime",
        "confidence": conf,
    }

