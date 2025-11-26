from datetime import datetime, timezone

import pytest

from pearlalgo.core.events import OrderEvent
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.risk.sizing import volatility_position_size
from pearlalgo.risk.pnl import DailyPnLTracker
from pearlalgo.core.events import FillEvent
from pearlalgo.futures.config import PropProfile
from pearlalgo.futures.risk import compute_risk_state


def test_risk_guard_notional_limit_blocks():
    guard = RiskGuard(RiskLimits(max_order_notional=1000))
    order = OrderEvent(timestamp=datetime.now(timezone.utc), symbol="ES", side="BUY", quantity=10, order_type="MKT")
    with pytest.raises(RuntimeError):
        guard.check_order(order, last_price=150)


def test_sizing_vol_basic():
    size = volatility_position_size(account_equity=100000, risk_per_trade=0.01, atr=10, dollar_vol_per_point=50)
    assert size > 0


def test_pnl_tracker_daily_loss():
    tracker = DailyPnLTracker()
    # Simulate a loss: buy then sell lower
    now = datetime.now(timezone.utc)
    tracker.record_fill(FillEvent(timestamp=now, symbol="ES", side="BUY", quantity=1, price=100))
    tracker.record_fill(FillEvent(timestamp=now, symbol="ES", side="SELL", quantity=1, price=90))
    assert tracker.realized_today() == -10
    assert tracker.daily_loss_breached(5) is True


def test_risk_state_cooldown_and_max_trades():
    profile = PropProfile()
    now = datetime.now(timezone.utc)
    # max trades hit
    rs = compute_risk_state(profile, day_start_equity=profile.starting_balance, realized_pnl=0, unrealized_pnl=0, trades_today=5, max_trades=5, now=now)
    assert rs.status == "COOLDOWN"
    # session paused
    start = (now.replace(hour=9, minute=0, second=0, microsecond=0)).time()
    end = (now.replace(hour=10, minute=0, second=0, microsecond=0)).time()
    rs_paused = compute_risk_state(profile, day_start_equity=profile.starting_balance, realized_pnl=0, unrealized_pnl=0, now=now.replace(hour=11), session_start=start, session_end=end)
    assert rs_paused.status == "PAUSED"
