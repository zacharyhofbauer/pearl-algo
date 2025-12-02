from datetime import datetime
from pathlib import Path

import pandas as pd

from pearlalgo.core.portfolio import Portfolio
from pearlalgo.data_providers.local_csv_provider import LocalCSVProvider
from pearlalgo.brokers.dummy_backtest import DummyBacktestBroker
from pearlalgo.core.events import OrderEvent


def test_local_csv_provider_filters(tmp_path: Path):
    csv = tmp_path / "ES.csv"
    csv.write_text(
        "Date,Open,High,Low,Close,Volume\n2024-01-01,1,2,0.5,1.5,100\n2024-01-02,2,3,1,2.5,200\n"
    )
    provider = LocalCSVProvider(tmp_path)
    df = provider.fetch_historical("ES", start=datetime(2024, 1, 2))
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2024-01-02")


def test_dummy_backtest_broker_fills_and_portfolio():
    portfolio = Portfolio(cash=1000)

    def price(sym: str) -> float:
        return 10.0

    broker = DummyBacktestBroker(portfolio, commission_per_unit=0.1, price_lookup=price)
    order = OrderEvent(
        timestamp=datetime(2024, 1, 1),
        symbol="ES",
        side="BUY",
        quantity=2,
        order_type="MKT",
    )
    broker.submit_order(order)

    assert portfolio.positions["ES"].size == 2
    # Allow for floating point precision
    expected_cash = 1000 - 2 * 10.0 - 0.2
    assert abs(portfolio.cash - expected_cash) < 0.01
