from __future__ import annotations

from dataclasses import dataclass

from pearlalgo.futures.config import PropProfile


@dataclass
class RiskState:
    current_realized_pnl: float
    current_unrealized_pnl: float
    day_starting_equity: float
    daily_loss_limit: float
    remaining_loss_buffer: float
    status: str  # "OK" | "NEAR_LIMIT" | "HARD_STOP"


def compute_risk_state(
    profile: PropProfile,
    day_starting_equity: float,
    realized_pnl: float,
    unrealized_pnl: float,
    *,
    near_threshold: float = 0.2,
) -> RiskState:
    loss_limit = abs(profile.daily_loss_limit)
    equity_now = day_starting_equity + realized_pnl + unrealized_pnl
    remaining = max(0.0, loss_limit - max(0.0, day_starting_equity - equity_now))

    if remaining <= 0:
        status = "HARD_STOP"
    elif remaining <= loss_limit * near_threshold:
        status = "NEAR_LIMIT"
    else:
        status = "OK"

    return RiskState(
        current_realized_pnl=realized_pnl,
        current_unrealized_pnl=unrealized_pnl,
        day_starting_equity=day_starting_equity,
        daily_loss_limit=loss_limit,
        remaining_loss_buffer=remaining,
        status=status,
    )


def _max_contracts_from_buffer(buffer: float, tick_value: float, price: float) -> int:
    if tick_value <= 0 or price <= 0:
        return 0
    max_by_buffer = int(buffer // tick_value)
    return max(max_by_buffer, 0)


def compute_position_size(
    symbol: str,
    risk_state: RiskState,
    profile: PropProfile,
    price: float,
    *,
    side: str = "long",
) -> int:
    if risk_state.status == "HARD_STOP":
        return 0

    root = symbol.upper()
    tick_value = profile.tick_values_by_symbol.get(root)
    if tick_value is None:
        return 0

    buffer_contracts = _max_contracts_from_buffer(risk_state.remaining_loss_buffer, tick_value, price)
    max_cap = profile.max_contracts_by_symbol.get(root, 0)
    allowed = min(buffer_contracts, max_cap)

    if allowed <= 0:
        return 0

    direction = 1 if side.lower() == "long" else -1 if side.lower() == "short" else 0
    return direction * allowed
