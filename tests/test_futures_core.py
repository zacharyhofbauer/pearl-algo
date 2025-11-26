from __future__ import annotations

import pandas as pd

from pearlalgo.futures.config import PropProfile
from pearlalgo.futures.contracts import fut_contract
from pearlalgo.futures.performance import PerformanceRow, load_performance, log_performance_row
from pearlalgo.futures.risk import RiskState, compute_position_size, compute_risk_state
from pearlalgo.futures.signals import generate_signal


def test_build_future_fields():
    contract = fut_contract("ES", expiry="202412", local_symbol="ESZ4")
    assert contract.symbol == "ES"
    assert contract.exchange == "GLOBEX"
    assert contract.currency == "USD"
    assert contract.lastTradeDateOrContractMonth == "202412"
    assert contract.localSymbol == "ESZ4"
    assert contract.tradingClass == "ES"


def test_risk_state_and_position_size():
    profile = PropProfile()
    state = compute_risk_state(
        profile, day_start_equity=profile.starting_balance, realized_pnl=-500, unrealized_pnl=0
    )
    assert state.status == "OK"
    size_ok = compute_position_size("ES", "long", profile, state, price=5000)
    assert size_ok > 0

    near = compute_risk_state(
        profile, day_start_equity=profile.starting_balance, realized_pnl=-0.8 * profile.daily_loss_limit, unrealized_pnl=0
    )
    assert near.status == "NEAR_LIMIT"
    size_near = compute_position_size("ES", "long", profile, near, price=5000)
    assert 0 < abs(size_near) <= profile.max_contracts_by_symbol["ES"]

    hard_stop = compute_risk_state(
        profile, day_start_equity=profile.starting_balance, realized_pnl=-profile.daily_loss_limit, unrealized_pnl=0
    )
    assert hard_stop.status == "HARD_STOP"
    blocked = compute_position_size("ES", "short", profile, hard_stop, price=5000)
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


def test_performance_log(tmp_path):
    path = tmp_path / "perf.csv"
    row = PerformanceRow(
        timestamp=pd.Timestamp("2025-01-01", tz="UTC").to_pydatetime(),
        symbol="ES",
        sec_type="FUT",
        strategy_name="ma_cross",
        side="long",
        requested_size=1,
        filled_size=1,
        entry_price=100.0,
        realized_pnl=5.0,
        unrealized_pnl=0.0,
        fast_ma=10.0,
        slow_ma=11.0,
        risk_status="OK",
        notes="test",
    )
    log_performance_row(row, path=path)
    df = load_performance(path)
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "ES"
