from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pearlalgo.futures.config import PropProfile

Side = Literal["long", "short", "flat"]


@dataclass
class RiskState:
    day_start_equity: float
    realized_pnl: float
    unrealized_pnl: float
    daily_loss_limit: float
    target_profit: float
    remaining_loss_buffer: float
    status: Literal["OK", "NEAR_LIMIT", "HARD_STOP"]


def compute_risk_state(
    profile: PropProfile,
    day_start_equity: float,
    realized_pnl: float,
    unrealized_pnl: float,
    *,
    near_threshold: float | None = None,
) -> RiskState:
    """
    Compute intraday risk state relative to daily loss limit/target.
    """
    loss_limit = abs(profile.daily_loss_limit)
    near_level = near_threshold if near_threshold is not None else profile.risk_taper_threshold
    net_pnl = realized_pnl + unrealized_pnl
    remaining = max(0.0, loss_limit + net_pnl)  # net_pnl negative reduces buffer

    if net_pnl <= -loss_limit:
        status: Literal["OK", "NEAR_LIMIT", "HARD_STOP"] = "HARD_STOP"
    elif remaining <= loss_limit * near_level:
        status = "NEAR_LIMIT"
    else:
        status = "OK"

    return RiskState(
        day_start_equity=day_start_equity,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        daily_loss_limit=loss_limit,
        target_profit=profile.target_profit,
        remaining_loss_buffer=remaining,
        status=status,
    )


def compute_position_size(
    symbol: str,
    desired_side: Side,
    profile: PropProfile,
    risk_state: RiskState,
    price: float,
) -> int:
    """
    Prop-firm-aware position sizing:
    - Returns 0 on flat or hard stop.
    - Caps by per-symbol max contracts.
    - Optionally tapers sizing as remaining buffer shrinks.
    """
    if desired_side == "flat" or risk_state.status == "HARD_STOP":
        return 0

    root = symbol.upper()
    max_cap = profile.max_contracts_by_symbol.get(root, 0)
    if max_cap <= 0:
        return 0

    # Taper sizing as buffer shrinks; minimum of 1 when buffer > 0
    buffer_frac = (
        risk_state.remaining_loss_buffer / risk_state.daily_loss_limit if risk_state.daily_loss_limit > 0 else 1.0
    )
    taper_floor = max(profile.risk_taper_threshold, 0.1)
    scale = max(taper_floor, min(1.0, buffer_frac))
    allowed = max(1, int(max_cap * scale)) if risk_state.remaining_loss_buffer > 0 else 0

    direction = 1 if desired_side == "long" else -1
    return direction * allowed
