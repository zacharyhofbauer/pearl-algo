from __future__ import annotations

import pandas as pd


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> float:
    """
    Calculate Average True Range (ATR).

    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ATR period (default: 14)

    Returns:
        ATR value
    """
    if len(high) < period + 1:
        return 0.0

    # Calculate True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Calculate ATR as moving average of TR
    atr = tr.rolling(window=period).mean().iloc[-1]

    return float(atr) if not pd.isna(atr) else 0.0


def volatility_position_size(
    account_equity: float,
    risk_per_trade: float,
    atr: float,
    dollar_vol_per_point: float,
    max_units: int | None = None,
    atr_multiplier: float = 1.0,
) -> int:
    """
    ATR-based position sizing. Assumes stop loss at ATR * multiplier.

    Args:
        account_equity: Account equity
        risk_per_trade: Risk per trade as fraction (e.g., 0.01 for 1%)
        atr: Average True Range
        dollar_vol_per_point: Dollar value per point move
        max_units: Maximum position size
        atr_multiplier: ATR multiplier for stop loss (default: 1.0)

    Returns:
        Position size in units
    """
    if atr <= 0 or dollar_vol_per_point <= 0:
        return 0

    # Calculate stop loss distance
    stop_distance = atr * atr_multiplier

    # Calculate position size based on risk
    risk_amount = account_equity * risk_per_trade
    raw_units = int(risk_amount / (stop_distance * dollar_vol_per_point))

    if max_units is not None:
        raw_units = min(raw_units, max_units)

    return max(raw_units, 0)


def atr_based_position_size(
    account_equity: float,
    risk_per_trade: float,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    dollar_vol_per_point: float,
    atr_period: int = 14,
    atr_multiplier: float = 1.0,
    max_units: int | None = None,
) -> int:
    """
    Calculate position size using ATR from price data.

    Args:
        account_equity: Account equity
        risk_per_trade: Risk per trade as fraction
        high: High prices
        low: Low prices
        close: Close prices
        dollar_vol_per_point: Dollar value per point move
        atr_period: ATR calculation period
        atr_multiplier: ATR multiplier for stop loss
        max_units: Maximum position size

    Returns:
        Position size in units
    """
    atr = calculate_atr(high, low, close, period=atr_period)
    return volatility_position_size(
        account_equity=account_equity,
        risk_per_trade=risk_per_trade,
        atr=atr,
        dollar_vol_per_point=dollar_vol_per_point,
        max_units=max_units,
        atr_multiplier=atr_multiplier,
    )


def volatility_adjusted_risk_limit(
    base_risk_limit: float,
    current_atr: float,
    baseline_atr: float,
    min_adjustment: float = 0.5,
    max_adjustment: float = 2.0,
) -> float:
    """
    Adjust risk limits based on current volatility relative to baseline.

    When volatility is high, reduce risk limits.
    When volatility is low, can increase risk limits (up to max).

    Args:
        base_risk_limit: Base risk limit
        current_atr: Current ATR value
        baseline_atr: Baseline/reference ATR value
        min_adjustment: Minimum adjustment factor (default: 0.5 = 50% of base)
        max_adjustment: Maximum adjustment factor (default: 2.0 = 200% of base)

    Returns:
        Adjusted risk limit
    """
    if baseline_atr <= 0:
        return base_risk_limit

    # Calculate volatility ratio
    vol_ratio = current_atr / baseline_atr

    # Inverse relationship: higher volatility = lower risk limit
    # When vol_ratio = 1.0, adjustment = 1.0
    # When vol_ratio = 2.0, adjustment = 0.5 (half the risk)
    # When vol_ratio = 0.5, adjustment = 2.0 (double the risk, capped at max)
    adjustment = 1.0 / vol_ratio

    # Apply min/max bounds
    adjustment = max(min_adjustment, min(max_adjustment, adjustment))

    return base_risk_limit * adjustment
