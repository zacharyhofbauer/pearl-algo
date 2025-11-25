from __future__ import annotations

import logging

from pearlalgo.brokers.base import Broker
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.agents.execution_agent import ExecutionAgent

logger = logging.getLogger(__name__)


class LiveRunner:
    """
    Minimal live runner skeleton.
    - Fetches data via provider
    - Invokes strategies (to be injected)
    - Routes orders via ExecutionAgent/Broker
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
