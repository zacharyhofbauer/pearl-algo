from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
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
    Automatically sets cooldown_until after HARD_STOP or when max_trades is reached.
    """
    loss_limit = abs(profile.daily_loss_limit)
    near_level = near_threshold if near_threshold is not None else profile.risk_taper_threshold
    net_pnl = realized_pnl + unrealized_pnl
    remaining = max(0.0, loss_limit + net_pnl)  # net_pnl negative reduces buffer
    status: RiskStatus
    effective_max_trades = max_trades if max_trades is not None else profile.max_trades
    effective_cooldown_until = cooldown_until
    if now is None:
        current_time = datetime.now(timezone.utc)
    else:
        current_time = now if now.tzinfo else now.replace(tzinfo=timezone.utc)

    # Check if we need to set a new cooldown
    if not _time_allowed(now, session_start, session_end):
        status = "PAUSED"
    elif net_pnl <= -loss_limit:
        # HARD_STOP: set cooldown if not already set
        status = "HARD_STOP"
        if effective_cooldown_until is None or current_time >= effective_cooldown_until:
            effective_cooldown_until = current_time + timedelta(minutes=profile.cooldown_minutes)
    elif effective_max_trades is not None and trades_today >= effective_max_trades:
        # Max trades reached: set cooldown if not already set
        status = "COOLDOWN"
        if effective_cooldown_until is None or current_time >= effective_cooldown_until:
            effective_cooldown_until = current_time + timedelta(minutes=profile.cooldown_minutes)
    elif effective_cooldown_until and current_time < effective_cooldown_until:
        status = "COOLDOWN"
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
        max_trades=effective_max_trades,
        cooldown_until=effective_cooldown_until,
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
    - Tapers sizing as remaining buffer shrinks and as max_trades is approached.
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
    buffer_scale = max(taper_floor, min(1.0, buffer_frac))

    # Taper by remaining trades if max_trades is set
    trades_scale = 1.0
    if risk_state.max_trades is not None and risk_state.max_trades > 0:
        remaining_trades = max(0, risk_state.max_trades - risk_state.trades_today)
        trades_frac = remaining_trades / risk_state.max_trades
        # Start tapering when < 30% of trades remain
        if trades_frac < 0.3:
            trades_scale = max(0.5, trades_frac / 0.3)  # Scale down to 50% minimum

    # Combine both scales (use the more restrictive)
    combined_scale = min(buffer_scale, trades_scale)
    allowed = max(profile.min_contract_size, int(max_cap * combined_scale)) if buffer > 0 else 0
    # Cap at max_cap
    allowed = min(allowed, max_cap)

    direction = 1 if desired_side == "long" else -1
    return direction * allowed
