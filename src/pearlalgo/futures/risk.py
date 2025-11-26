from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal, Optional

from pearlalgo.futures.config import PropProfile

Side = Literal["long", "short", "flat"]
RiskStatus = Literal["OK", "NEAR_LIMIT", "HARD_STOP", "COOLDOWN", "PAUSED"]


@dataclass
class RiskState:
    day_start_equity: float
    realized_pnl: float
    unrealized_pnl: float
    daily_loss_limit: float
    target_profit: float
    remaining_loss_buffer: float
    status: RiskStatus
    trades_today: int = 0
    max_trades: Optional[int] = None
    cooldown_until: Optional[datetime] = None
    drawdown_remaining: float | None = None


def _time_allowed(now: datetime | None, start: time | None, end: time | None) -> bool:
    if now is None or (start is None and end is None):
        return True
    now_t = now.time()
    if start and now_t < start:
        return False
    if end and now_t > end:
        return False
    return True


def compute_risk_state(
    profile: PropProfile,
    day_start_equity: float,
    realized_pnl: float,
    unrealized_pnl: float,
    *,
    near_threshold: float | None = None,
    trades_today: int = 0,
    max_trades: int | None = None,
    cooldown_until: datetime | None = None,
    now: datetime | None = None,
    session_start: time | None = None,
    session_end: time | None = None,
) -> RiskState:
    """
    Compute intraday risk state relative to daily limits, trade limits, and sessions.
    """
    loss_limit = abs(profile.daily_loss_limit)
    near_level = near_threshold if near_threshold is not None else profile.risk_taper_threshold
    net_pnl = realized_pnl + unrealized_pnl
    remaining = max(0.0, loss_limit + net_pnl)  # net_pnl negative reduces buffer
    status: RiskStatus

    if not _time_allowed(now, session_start, session_end):
        status = "PAUSED"
    elif max_trades is not None and trades_today >= max_trades:
        status = "COOLDOWN"
    elif cooldown_until and now and now < cooldown_until:
        status = "COOLDOWN"
    elif net_pnl <= -loss_limit:
        status = "HARD_STOP"
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
        trades_today=trades_today,
        max_trades=max_trades,
        cooldown_until=cooldown_until,
        drawdown_remaining=remaining,
    )


def compute_position_size(
    symbol: str,
    desired_side: Side,
    profile: PropProfile,
    risk_state: RiskState,
    price: float,
    remaining_daily_drawdown: float | None = None,
) -> int:
    """
    Prop-firm-aware position sizing:
    - Returns 0 on flat, hard stop, cooldown, or paused.
    - Caps by per-symbol max contracts.
    - Tapers sizing as remaining buffer shrinks.
    """
    if desired_side == "flat" or risk_state.status in {"HARD_STOP", "COOLDOWN", "PAUSED"}:
        return 0

    root = symbol.upper()
    max_cap = profile.max_contracts_by_symbol.get(root, 0)
    if max_cap <= 0:
        return 0

    buffer = remaining_daily_drawdown
    if buffer is None:
        buffer = risk_state.remaining_loss_buffer
    buffer_frac = buffer / risk_state.daily_loss_limit if risk_state.daily_loss_limit > 0 else 1.0
    taper_floor = max(profile.risk_taper_threshold, 0.1)
    scale = max(taper_floor, min(1.0, buffer_frac))
    allowed = max(1, int(max_cap * scale)) if buffer > 0 else 0

    direction = 1 if desired_side == "long" else -1
    return direction * allowed
