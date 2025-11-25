from datetime import datetime

import pytest

from pearlalgo.core.events import OrderEvent
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.risk.sizing import volatility_position_size
from pearlalgo.risk.pnl import DailyPnLTracker
from pearlalgo.core.events import FillEvent


def test_risk_guard_notional_limit_blocks():
    guard = RiskGuard(RiskLimits(max_order_notional=1000))
    order = OrderEvent(timestamp=datetime.utcnow(), symbol="ES", side="BUY", quantity=10, order_type="MKT")
    with pytest.raises(RuntimeError):
        guard.check_order(order, last_price=150)


def test_sizing_vol_basic():
    size = volatility_position_size(account_equity=100000, risk_per_trade=0.01, atr=10, dollar_vol_per_point=50)
    assert size > 0


def test_pnl_tracker_daily_loss():
    tracker = DailyPnLTracker()
    # Simulate a loss: buy then sell lower
    tracker.record_fill(FillEvent(timestamp=datetime.utcnow(), symbol="ES", side="BUY", quantity=1, price=100))
    tracker.record_fill(FillEvent(timestamp=datetime.utcnow(), symbol="ES", side="SELL", quantity=1, price=90))
    assert tracker.daily_loss_breached(5) is True
