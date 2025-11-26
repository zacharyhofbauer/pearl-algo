from __future__ import annotations

import pandas as pd
from backtesting import Backtest, Strategy

from pearlalgo.agents.strategy_loader import get_strategy
from pearlalgo.config.symbols import get_symbol_meta
from pearlalgo.strategies.base import BaseStrategy
from pearlalgo.core.events import OrderEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.brokers.dummy_backtest import DummyBacktestBroker


def _make_strategy_adapter(strat: BaseStrategy) -> type[Strategy]:
    """Wrap a BaseStrategy so backtesting.py can instantiate and trade from its signals."""

    class Adapter(Strategy):
        finalize_trades: bool = True

        def init(self):
            df = self.data.df.copy()
            out = strat.run(df)
            self.entry = out.get("entry")
            self.size = out.get("size")
            self.stop = out.get("stop")
            self.target = out.get("target")

        def next(self):
            if self.entry is None:
                return
            idx = len(self.data) - 1
            signal = self.entry.iloc[idx] if hasattr(self.entry, "iloc") else self.entry[idx]

            def _val(series):
                if series is None:
                    return None
                val = series.iloc[idx] if hasattr(series, "iloc") else series[idx]
                if pd.isna(val):
                    return None
                return float(val)

            sz = _val(self.size) or 1
            sl = _val(self.stop)
            tp = _val(self.target)

            if signal > 0:
                if self.position.is_short:
                    self.position.close()
                self.buy(size=sz, sl=sl, tp=tp)
            elif signal < 0:
                if self.position.is_long:
                    self.position.close()
                self.sell(size=sz, sl=sl, tp=tp)

    Adapter.__name__ = f"{strat.name.title().replace('_', '')}Adapter"
    return Adapter


def _run_naive_engine(
    data: pd.DataFrame,
    strat: BaseStrategy,
    symbol: str,
    cash: float,
    commission: float,
) -> tuple[Portfolio, int]:
    """
    Lightweight bar-by-bar simulator using DummyBacktestBroker and Portfolio.

    This is not as feature-rich as backtesting.py but exercises the core abstractions.
    """
    portfolio = Portfolio(cash=cash)
    broker = DummyBacktestBroker(portfolio, commission_per_unit=commission)

    # Strategy run returns dataframe with entry/size/stop/target columns
    enriched = strat.run(data)
    size_series = enriched.get("size")
    entry_series = enriched.get("entry")

    for ts, row in enriched.iterrows():
        if entry_series is None:
            continue
        signal_val = row.get("entry", 0)
        if pd.isna(signal_val) or signal_val == 0:
            continue

        direction = int(signal_val)
        side = "BUY" if direction > 0 else "SELL"
        qty = float(row.get("size", 1) if size_series is not None else 1)
        price = float(row.get("Close", data.loc[ts, "Close"]))

        order = OrderEvent(
            timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
            symbol=symbol,
            side=side,
            quantity=abs(qty),
            order_type="MKT",
            limit_price=price,
            metadata={
                "stop": row.get("stop"),
                "target": row.get("target"),
            },
        )
        broker.submit_order(order)

    return portfolio, len(broker._fills)


def run_backtest(
    data: pd.DataFrame,
    strategy_name: str,
    symbol: str = "ES",
    cash: float = 1_000_000,
    commission: float = 0.0005,
    profile: str = "backtest",
    engine: str = "backtesting",
):
    """
    Run a backtest using backtesting.py adapter.

    Parameters
    ----------
    data : pd.DataFrame
        OHLCV data indexed by timestamp.
    strategy_name : str
        Registered strategy key.
    symbol : str
        Symbol metadata key (e.g., ES, NQ, SPY).
    cash : float
        Starting cash.
    commission : float
        Commission rate.
    profile : str
        Execution profile (backtest|paper|live). Currently used for logging/guardrails.
    engine : str
        Backtest engine to use ("backtesting" | "naive").
    """
    if profile not in {"backtest", "paper", "live"}:
        raise ValueError("profile must be one of: backtest, paper, live")
    if engine not in {"backtesting", "naive"}:
        raise ValueError("engine must be one of: backtesting, naive")

    strat = get_strategy(strategy_name)
    adapter = _make_strategy_adapter(strat)
    _ = get_symbol_meta(symbol)  # validate symbol metadata exists
    if engine == "backtesting":
        bt = Backtest(
            data,
            adapter,
            cash=cash,
            commission=commission,
            margin=1.0,  # use full cash; leverage/margin models can be added later
            trade_on_close=False,
            hedging=False,
        )
        stats = bt.run(finalize_trades=True)
        return stats, bt

    portfolio, fill_count = _run_naive_engine(data, strat, symbol, cash, commission)
    equity = portfolio.mark_to_market({symbol: float(data["Close"].iloc[-1])})
    stats = pd.Series({"Equity Final [$]": equity, "Fills": fill_count})
    return stats, portfolio


if __name__ == "__main__":
    df = pd.read_csv("data/futures/ES_15m_sample.csv")
    stats, bt = run_backtest(df, "es_breakout")
    print(stats)
