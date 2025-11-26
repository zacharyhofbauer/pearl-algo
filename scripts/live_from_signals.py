from __future__ import annotations

import argparse
from pathlib import Path

from pearlalgo.agents.execution_agent import ExecutionAgent
from pearlalgo.brokers.dummy_backtest import DummyBacktestBroker
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.live.runner import LiveRunner
from pearlalgo.data_providers.local_csv_provider import LocalCSVProvider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume signals CSV and print paper 'would place' orders.")
    parser.add_argument("--signals", required=True, help="Path to signals CSV (timestamp,symbol,instrument_type,direction,size_hint)")
    parser.add_argument("--tiny-size", type=float, default=None, help="Override size for safety (paper-only).")
    args = parser.parse_args(argv)

    portfolio = Portfolio(cash=100000)
    broker = DummyBacktestBroker(portfolio)
    exec_agent = ExecutionAgent(broker, symbol="N/A", profile="paper")
    runner = LiveRunner(provider=LocalCSVProvider(Path(".")), broker=broker, execution_agent=exec_agent)
    runner.run_from_signals_file(Path(args.signals), tiny_size=args.tiny_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
