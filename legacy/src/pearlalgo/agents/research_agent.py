from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable, Optional

import pandas as pd

from pearlalgo.agents.strategy_agent import StrategyAgent
from pearlalgo.strategies.base import BaseStrategy
from pearlalgo.agents.strategy_loader import get_strategy
from pearlalgo.data_providers.base import DataProvider


def describe(df: pd.DataFrame) -> pd.DataFrame:
    """Basic exploratory statistics."""
    return df.describe()


def scan_for_entries(
    symbols: Iterable[str],
    provider: DataProvider,
    strategy_name: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    timeframe: Optional[str] = None,
    strategy_factory: Optional[Callable[[], BaseStrategy]] = None,
) -> list[dict]:
    """
    Run a strategy over symbols and return callouts for non-flat latest entries.
    """
    results: list[dict] = []
    for sym in symbols:
        try:
            strat = strategy_factory() if strategy_factory else get_strategy(strategy_name)
            agent = StrategyAgent(
                provider=provider,
                strategy=strat,
                symbol=sym,
                start=start,
                end=end,
                timeframe=timeframe,
            )
            signals = agent.run()
        except Exception as exc:  # narrow handling for missing data
            results.append({"symbol": sym, "error": str(exc)})
            continue

        if "entry" not in signals.columns or signals.empty:
            continue

        last = signals.iloc[-1]
        entry = last.get("entry", 0)
        if entry is None or pd.isna(entry) or entry == 0:
            continue
        direction = "LONG" if float(entry) > 0 else "SHORT"
        results.append(
            {
                "symbol": sym,
                "direction": direction,
                "timestamp": signals.index[-1],
                "close": float(last.get("Close", last.get("close", 0.0))),
                "stop": last.get("stop"),
                "target": last.get("target"),
            }
        )
    return results
