from __future__ import annotations

import logging
import pandas as pd
from pathlib import Path

from pearlalgo.brokers.base import Broker
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.agents.execution_agent import ExecutionAgent

logger = logging.getLogger(__name__)


class LiveRunner:
    """
    Minimal live runner skeleton.
    - Can run a strategy callable OR consume a signals CSV.
    - Routes orders via ExecutionAgent/Broker (paper by default).
    Add health checks, reconnection logic, and monitoring before production use.
    """

    def __init__(self, provider: DataProvider, broker: Broker, execution_agent: ExecutionAgent):
        self.provider = provider
        self.broker = broker
        self.execution_agent = execution_agent

    def run_once(self, strategy_fn, *symbols: str):
        """
        strategy_fn(provider, symbol) -> signals DataFrame
        """
        for symbol in symbols:
            try:
                signals = strategy_fn(self.provider, symbol)
                if signals is None:
                    continue
                self.execution_agent.symbol = symbol
                self.execution_agent.execute(signals)
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.exception("LiveRunner error for %s: %s", symbol, exc)

    def run_from_signals_file(self, path: Path, tiny_size: float | None = None) -> None:
        """Read signals CSV and route as paper 'would place' logs."""
        if not path.exists():
            logger.warning("Signals file not found: %s", path)
            return
        df = pd.read_csv(path)
        for _, row in df.iterrows():
            direction = row.get("direction", "FLAT")
            if direction == "FLAT":
                continue
            size = float(row.get("size_hint", 1))
            if tiny_size is not None:
                size = tiny_size
            order_side = "BUY" if direction.upper() == "BUY" else "SELL"
            logger.info("Would place %s %s qty=%s (paper)", order_side, row.get("symbol"), size)
