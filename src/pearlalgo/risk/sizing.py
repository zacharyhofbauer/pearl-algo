from __future__ import annotations

def volatility_position_size(
    account_equity: float,
    risk_per_trade: float,
    atr: float,
    dollar_vol_per_point: float,
    max_units: int | None = None,
) -> int:
    """
    Simple vol-based sizing. Assumes 1 ATR stop; trims to max_units if provided.
    """
    if atr <= 0 or dollar_vol_per_point <= 0:
        return 0
    raw_units = int((account_equity * risk_per_trade) / (atr * dollar_vol_per_point))
    if max_units is not None:
        raw_units = min(raw_units, max_units)
    return max(raw_units, 0)
