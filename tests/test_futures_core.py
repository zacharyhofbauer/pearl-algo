from __future__ import annotations

import pandas as pd

from pearlalgo.futures.config import PropProfile
from pearlalgo.futures.contracts import fut_contract
from pearlalgo.futures.performance import (
    PerformanceRow,
    load_performance,
    log_performance_row,
)
from pearlalgo.futures.risk import compute_position_size, compute_risk_state
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
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=-500,
        unrealized_pnl=0,
    )
    assert state.status == "OK"
    size_ok = compute_position_size("ES", "long", profile, state, price=5000)
    assert size_ok > 0

    near = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=-0.8 * profile.daily_loss_limit,
        unrealized_pnl=0,
    )
    assert near.status == "NEAR_LIMIT"
    size_near = compute_position_size("ES", "long", profile, near, price=5000)
    assert 0 < abs(size_near) <= profile.max_contracts_by_symbol["ES"]

    hard_stop = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=-profile.daily_loss_limit,
        unrealized_pnl=0,
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


def test_cooldown_after_hard_stop():
    """Test that HARD_STOP automatically sets cooldown_until."""
    from datetime import datetime, timezone
    import pytest

    profile = PropProfile(cooldown_minutes=60)
    now = datetime.now(timezone.utc)

    # Trigger HARD_STOP
    state = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=-profile.daily_loss_limit,
        unrealized_pnl=0.0,
        now=now,
    )
    assert state.status == "HARD_STOP"
    assert state.cooldown_until is not None
    assert state.cooldown_until > now
    assert (state.cooldown_until - now).total_seconds() / 60.0 == pytest.approx(
        60.0, abs=1.0
    )


def test_position_size_tapers_by_trades():
    """Test that position sizing tapers as max_trades is approached."""
    from datetime import datetime, timezone

    profile = PropProfile(max_trades=10, max_contracts_by_symbol={"ES": 2})
    now = datetime.now(timezone.utc)

    # Early in session: full size
    state_early = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        trades_today=2,
        max_trades=10,
        now=now,
    )
    size_early = compute_position_size("ES", "long", profile, state_early, price=5000)

    # Near max trades: should taper
    state_late = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        trades_today=8,  # 80% of max
        max_trades=10,
        now=now,
    )
    size_late = compute_position_size("ES", "long", profile, state_late, price=5000)

    # Late sizing should be smaller or equal (tapered)
    assert abs(size_late) <= abs(size_early)


def test_sr_strategy_with_ema_filter():
    """Test S/R strategy with EMA filter generates proper trade_reason."""
    # Create data with clear trend and proper datetime indices
    dates = pd.date_range("2025-01-01 09:30:00", periods=6, freq="15min")
    closes = pd.Series([100, 101, 102, 103, 104, 105], name="Close", index=dates)
    highs = pd.Series([101, 102, 103, 104, 105, 106], name="High", index=dates)
    lows = pd.Series([99, 100, 101, 102, 103, 104], name="Low", index=dates)
    volumes = pd.Series(
        [1000, 1100, 1200, 1300, 1400, 1500], name="Volume", index=dates
    )
    df = pd.DataFrame({"Close": closes, "High": highs, "Low": lows, "Volume": volumes})

    signal = generate_signal("ES", df, strategy_name="sr", fast=20, slow=50)
    assert signal["strategy_name"] == "sr"
    # Should have trade_reason if signal is not flat
    if signal["side"] != "flat":
        assert "comment" in signal
        assert signal["comment"] is not None
