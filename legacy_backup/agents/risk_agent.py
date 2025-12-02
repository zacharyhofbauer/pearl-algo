from __future__ import annotations

import pandas as pd

from pearlalgo.core.portfolio import Portfolio, RiskLimits


def position_size(capital: float, risk_perc: float, stop_distance: float, tick_value: float) -> int:
    """Compute position size given capital risk, stop distance, and tick value."""
    risk_amount = capital * risk_perc
    if stop_distance <= 0 or tick_value <= 0:
        return 0
    size = risk_amount / (stop_distance * tick_value)
    return max(int(size), 0)


def rolling_drawdown(equity: pd.Series, window: int = 100) -> pd.Series:
    """Simple rolling max drawdown series."""
    roll_max = equity.rolling(window, min_periods=1).max()
    dd = (equity - roll_max) / roll_max
    return dd


def apply_risk_limits(
    portfolio: Portfolio,
    daily_loss_limit: float | None = None,
    max_position_size: float | None = None,
    max_open_positions: int | None = None,
) -> bool:
    """
    Update portfolio risk limits and enforce them.
    Returns True if trading is permitted, False if a kill-switch should be triggered.
    """
    portfolio.risk_limits = RiskLimits(
        daily_loss_limit=daily_loss_limit,
        max_position_size=max_position_size,
        max_open_positions=max_open_positions,
    )
    return portfolio.enforce_risk()
