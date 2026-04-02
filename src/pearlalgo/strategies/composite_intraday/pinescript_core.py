"""
Compatibility-backed wrappers around the Pearl strategy core.

This module is the canonical import surface for the live composite intraday
strategy while the underlying implementation is still delegated through the
legacy bridge module.

Keep new business logic out of this bridge layer until the legacy implementation
has been fully retired.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import pandas as pd

from pearlalgo.trading_bots import pearl_bot_auto as legacy


StrategyParams = legacy.StrategyParams


def default_config() -> dict[str, Any]:
    """Return the legacy default strategy config as a mutable dict copy."""
    return legacy.CONFIG.copy()


def generate_signals(
    df: pd.DataFrame,
    *,
    config: Optional[dict[str, Any]] = None,
    current_time: Optional[datetime] = None,
    df_5m: Optional[pd.DataFrame] = None,
) -> list[dict[str, Any]]:
    return legacy.generate_signals(
        df,
        config=config,
        current_time=current_time,
        df_5m=df_5m,
    )


def detect_market_regime(
    df: pd.DataFrame,
    *,
    lookback: int = 50,
):
    return legacy.detect_market_regime(df, lookback=lookback)


def check_trading_session(dt: datetime, config: dict[str, Any]) -> bool:
    return legacy.check_trading_session(dt, config)


def calculate_atr(df: pd.DataFrame, *, period: int = 14):
    return legacy.calculate_atr(df, period=period)
