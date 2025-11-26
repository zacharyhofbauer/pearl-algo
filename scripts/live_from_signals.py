from __future__ import annotations

import argparse
from pathlib import Path

from pearlalgo.agents.execution_agent import ExecutionAgent
from pearlalgo.brokers.dummy_backtest import DummyBacktestBroker
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.live.runner import LiveRunner
from pearlalgo.data_providers.local_csv_provider import LocalCSVProvider
from pearlalgo.config.settings import Settings, get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume signals CSV and print paper 'would place' orders.")
    parser.add_argument("--signals", required=True, help="Path to signals CSV (timestamp,symbol,instrument_type,direction,size_hint)")
    parser.add_argument("--tiny-size", type=float, default=None, help="Override size for safety (paper-only).")
    parser.add_argument("--mode", choices=["print", "ibkr-paper"], default="print", help="print=dry-run, ibkr-paper=route tiny size to IBKR paper")
    parser.add_argument("--ib-host", default=None, help="IB host (default from settings)")
    parser.add_argument("--ib-port", type=int, default=None, help="IB port (default from settings)")
    parser.add_argument("--ib-client-id", type=int, default=None, help="IB client id (default from settings)")
    args = parser.parse_args(argv)

    portfolio = Portfolio(cash=100000)
    provider = LocalCSVProvider(Path("."))

    if args.mode == "ibkr-paper":
        # Enable live routing but keep profile paper-esque; caller must point at paper Gateway.
        base_settings = get_settings()
        settings = Settings(
            allow_live_trading=True,
            profile="live",
            ib_host=args.ib_host or base_settings.ib_host,
            ib_port=args.ib_port or base_settings.ib_port,
            ib_client_id=args.ib_client_id or base_settings.ib_client_id,
        )
        broker = IBKRBroker(portfolio, settings=settings)
        exec_agent = ExecutionAgent(broker, symbol="N/A", profile="live")
    else:
        broker = DummyBacktestBroker(portfolio)
        exec_agent = ExecutionAgent(broker, symbol="N/A", profile="paper")

    runner = LiveRunner(provider=provider, broker=broker, execution_agent=exec_agent)
    runner.run_from_signals_file(Path(args.signals), tiny_size=args.tiny_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
