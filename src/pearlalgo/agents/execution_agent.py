from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import pandas as pd

from pearlalgo.brokers.base import Broker
from pearlalgo.core.events import OrderEvent


class ExecutionAgent:
    """
    Translates strategy signals into orders via a Broker.
    Backtest/paper are default; live trading must be explicitly selected upstream.
    """

    def __init__(self, broker: Broker, symbol: str, profile: str = "backtest"):
        self.broker = broker
        self.symbol = symbol
        self.profile = profile

    def _orders_from_signals(self, signals: pd.DataFrame) -> Iterable[OrderEvent]:
        for ts, row in signals.iterrows():
            signal_val = row.get("entry", 0)
            if signal_val is None or pd.isna(signal_val) or signal_val == 0:
                continue
            side = "BUY" if float(signal_val) > 0 else "SELL"
            qty = abs(float(row.get("size", 1)))
            price = float(row.get("Close", row.get("close", row.get("price", 0.0))))
            yield OrderEvent(
                timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                symbol=self.symbol,
                side=side,
                quantity=qty,
                order_type="MKT",
                limit_price=price,
                metadata={"profile": self.profile},
            )

    def execute(self, signals: pd.DataFrame) -> list[str]:
        if self.profile != "live":
            # Safety: warn that this agent is not routing to a live venue
            print(f"ExecutionAgent running in profile '{self.profile}'; live trading disabled.")
        order_ids: list[str] = []
        for order in self._orders_from_signals(signals):
            order_id = self.broker.submit_order(order)
            order_ids.append(order_id)
        return order_ids
