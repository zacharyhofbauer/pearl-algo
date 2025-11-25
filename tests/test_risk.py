from datetime import datetime

import pytest

from pearlalgo.core.events import OrderEvent
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.risk.sizing import volatility_position_size


def test_risk_guard_notional_limit_blocks():
    guard = RiskGuard(RiskLimits(max_order_notional=1000))
    order = OrderEvent(timestamp=datetime.utcnow(), symbol="ES", side="BUY", quantity=10, order_type="MKT")
    with pytest.raises(RuntimeError):
        guard.check_order(order, last_price=150)


def test_sizing_vol_basic():
    size = volatility_position_size(account_equity=100000, risk_per_trade=0.01, atr=10, dollar_vol_per_point=50)
    assert size > 0
