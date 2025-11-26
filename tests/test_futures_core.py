from __future__ import annotations

import pandas as pd

from pearlalgo.futures.config import PropProfile
from pearlalgo.futures.contracts import build_future
from pearlalgo.futures.risk import compute_position_size, compute_risk_state
from pearlalgo.futures.signals import generate_signal


def test_build_future_fields():
    contract = build_future("ES", expiry="202412", local_symbol="ESZ4")
    assert contract.symbol == "ES"
    assert contract.exchange == "CME"
    assert contract.currency == "USD"
    assert contract.lastTradeDateOrContractMonth == "202412"
    assert contract.localSymbol == "ESZ4"
    assert contract.tradingClass == "ES"


def test_risk_state_and_position_size():
    profile = PropProfile()
    state = compute_risk_state(profile, day_starting_equity=profile.starting_balance, realized_pnl=-2200, unrealized_pnl=0)
    assert state.status == "NEAR_LIMIT"
    # Remaining buffer should allow some contracts but capped by profile max (2 for ES)
    size = compute_position_size("ES", state, profile, price=5000, side="long")
    assert size == 2

    hard_stop = compute_risk_state(profile, day_starting_equity=profile.starting_balance, realized_pnl=-3000, unrealized_pnl=0)
    assert hard_stop.status == "HARD_STOP"
    blocked = compute_position_size("ES", hard_stop, profile, price=5000, side="short")
    assert blocked == 0


def test_ma_cross_signal():
    closes = pd.Series([10, 11, 12, 11, 10], name="Close")
    df = pd.DataFrame({"Close": closes})
    signal = generate_signal("ES", df, strategy_name="ma_cross", fast=2, slow=3)
    assert signal["symbol"] == "ES"
    assert signal["strategy_name"] == "ma_cross"
    # Last two closes are 11 and 10, so fast < slow -> short
    assert signal["side"] == "short"
    assert signal["fast_ma"] is not None and signal["slow_ma"] is not None
