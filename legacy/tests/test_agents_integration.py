from pathlib import Path

import pandas as pd

from pearlalgo.agents.strategy_agent import StrategyAgent
from pearlalgo.agents.execution_agent import ExecutionAgent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.brokers.dummy_backtest import DummyBacktestBroker
from pearlalgo.data_providers.local_csv_provider import LocalCSVProvider
from pearlalgo.strategies.base import BaseStrategy


class AlwaysLongStrategy(BaseStrategy):
    name = "always_long"

    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["entry"] = 1
        df["size"] = 1
        return df


def test_strategy_and_execution_round_trip(tmp_path: Path):
    csv = tmp_path / "ES.csv"
    csv.write_text("Date,Open,High,Low,Close,Volume\n2024-01-01,1,2,0.5,1.5,100\n2024-01-02,2,3,1,2.5,200\n")
    provider = LocalCSVProvider(tmp_path)
    strategy_agent = StrategyAgent(provider, AlwaysLongStrategy(), symbol="ES")
    signals = strategy_agent.run()
    portfolio = Portfolio(cash=1000)

    def price(sym: str) -> float:
        return float(signals["Close"].iloc[-1])

    broker = DummyBacktestBroker(portfolio, price_lookup=price)
    exec_agent = ExecutionAgent(broker, symbol="ES", profile="backtest")
    order_ids = exec_agent.execute(signals)

    assert order_ids, "No orders were submitted"
    assert portfolio.positions["ES"].size > 0
