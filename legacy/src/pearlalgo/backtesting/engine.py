from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

import pandas as pd

from pearlalgo.core.events import OrderEvent, FillEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.brokers.dummy_backtest import DummyBacktestBroker
from pearlalgo.strategies.base import BaseStrategy


@dataclass
class BacktestResult:
    fills: List[FillEvent]
    portfolio: Portfolio


class SimpleBacktestEngine:
    """
    Lightweight backtest engine that reuses the DummyBacktestBroker.
    Extend with slippage, commissions, and bar-by-bar simulation.
    """

    def __init__(self, portfolio: Portfolio, commission_per_unit: float = 0.0):
        self.portfolio = portfolio
        self.broker = DummyBacktestBroker(portfolio, commission_per_unit=commission_per_unit)

    def run(self, orders: Iterable[OrderEvent]) -> BacktestResult:
        for order in orders:
            self.broker.submit_order(order)
        fills = list(self.broker.fetch_fills())
        return BacktestResult(fills=fills, portfolio=self.portfolio)

    def run_signals(self, signals: pd.DataFrame, symbol: str) -> BacktestResult:
        orders: list[OrderEvent] = []
        for ts, row in signals.iterrows():
            side = "BUY" if row.get("entry", 0) > 0 else "SELL"
            qty = abs(float(row.get("size", 1)))
            price = float(row.get("Close", row.get("close", row.get("price", 0.0))))
            orders.append(
                OrderEvent(
                    timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    order_type="MKT",
                    limit_price=price,
                )
            )
        return self.run(orders)

    def run_strategy(self, strategy: BaseStrategy, data: pd.DataFrame, symbol: str) -> BacktestResult:
        signals = strategy.run(data)
        return self.run_signals(signals, symbol)
