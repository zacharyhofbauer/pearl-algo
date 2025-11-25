from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pearlalgo.data.loaders import load_csv
from pearlalgo.agents.backtest_agent import run_backtest
from pearlalgo.agents.strategy_loader import list_strategies
from pearlalgo.utils.logging import setup_logging
from pearlalgo.config.settings import get_settings, require_keys
from pearlalgo.data_providers.local_csv_provider import LocalCSVProvider
from pearlalgo.agents.research_agent import scan_for_entries
from pearlalgo.data_providers.ib_provider import IBDataProvider
from pearlalgo.config.settings import Settings


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    for name in list_strategies():
        print(name)
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    settings = get_settings(profile=args.profile, config_file=args.config_file)
    if settings.profile == "live":
        require_keys(settings, ["broker_api_key", "broker_api_secret", "broker_base_url"])
        print("WARNING: live profile selected; ensure broker adapter uses paper/live toggle.")
    else:
        print(f"Profile '{settings.profile}' active; live trading disabled.")
    df = load_csv(args.data)
    stats, _ = run_backtest(
        df,
        args.strategy,
        symbol=args.symbol,
        cash=args.cash,
        commission=args.commission,
        profile=settings.profile,
        engine=args.engine,
    )
    print(stats)
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    settings = get_settings(profile=args.profile, config_file=args.config_file)
    data_dir = args.data_dir or settings.data_dir
    provider = LocalCSVProvider(data_dir)
    symbols = args.symbols
    results = scan_for_entries(
        symbols=symbols,
        provider=provider,
        strategy_name=args.strategy,
        timeframe=args.timeframe,
    )
    if not results:
        print("No actionable entries found.")
        return 0
    for res in results:
        if "error" in res:
            print(f"{res['symbol']}: ERROR {res['error']}")
            continue
        print(
            f"{res['symbol']}: {res['direction']} at close={res['close']} "
            f"stop={res.get('stop')} target={res.get('target')} [{res['timestamp']}]"
        )
    return 0


def cmd_fetch_ib(args: argparse.Namespace) -> int:
    settings: Settings = get_settings(profile=args.profile, config_file=args.config_file)
    provider = IBDataProvider(settings, host=settings.ib_host, port=settings.ib_port, client_id=settings.ib_client_id)
    try:
        df = provider.fetch_historical(
            symbol=args.symbol,
            duration=args.duration,
            bar_size=args.bar_size,
            what_to_show=args.what_to_show,
            sec_type=args.sec_type,
            exchange=args.exchange,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path)
    print(f"Saved {len(df)} rows to {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PearlAlgo R&D CLI (equities/options/index futures)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser.add_argument("--profile", default="backtest", help="Execution profile: backtest|paper|live")
    parser.add_argument("--config-file", default=None, help="Optional JSON/YAML config file for settings")

    p_list = subparsers.add_parser("list-strategies", help="List available strategies")
    p_list.set_defaults(func=cmd_list_strategies)

    p_bt = subparsers.add_parser("backtest", help="Run a backtest")
    p_bt.add_argument("--data", required=True, help="Path to OHLCV CSV for a futures symbol")
    p_bt.add_argument("--strategy", default="es_breakout", choices=list_strategies())
    p_bt.add_argument("--symbol", default="ES", help="Symbol metadata key (e.g., ES, NQ, GC)")
    p_bt.add_argument("--cash", type=float, default=1_000_000)
    p_bt.add_argument("--commission", type=float, default=0.0005)
    p_bt.add_argument("--engine", default="backtesting", choices=["backtesting", "naive"], help="Backtest engine to use")
    p_bt.set_defaults(func=cmd_backtest)

    p_scan = subparsers.add_parser("scan", help="Scan symbols for entry callouts using a strategy")
    p_scan.add_argument("--symbols", nargs="+", default=["ES", "NQ"], help="Symbols to scan (expects CSVs in data_dir)")
    p_scan.add_argument("--strategy", default="es_breakout", choices=list_strategies(), help="Strategy to run for signals")
    p_scan.add_argument("--timeframe", default=None, help="Optional resample rule (e.g., 1H)")
    p_scan.add_argument("--data-dir", default=None, help="Override data directory (defaults to PEARLALGO_DATA_DIR or ./data)")
    p_scan.set_defaults(func=cmd_scan)

    p_ib = subparsers.add_parser("fetch-ib", help="Fetch historical data from IBKR and save to CSV")
    p_ib.add_argument("--symbol", required=True, help="Symbol to fetch (e.g., ES, NQ, AAPL)")
    p_ib.add_argument("--duration", default="2 D", help="IB duration string (e.g., '2 D', '1 W')")
    p_ib.add_argument("--bar-size", default="15 mins", help="IB bar size setting (e.g., '15 mins', '1 hour')")
    p_ib.add_argument("--what-to-show", default="TRADES", help="IB whatToShow (TRADES, MIDPOINT, BID_ASK)")
    p_ib.add_argument("--sec-type", default="FUT", help="Security type (FUT or STK)")
    p_ib.add_argument("--exchange", default=None, help="Exchange override (e.g., CME, SMART)")
    p_ib.add_argument("--output", default="data/futures/{symbol}_ib.csv", help="Output CSV path (supports {symbol})")
    p_ib.set_defaults(func=cmd_fetch_ib)

    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "output", None) and "{symbol}" in str(args.output) and getattr(args, "symbol", None):
        args.output = Path(str(args.output).format(symbol=args.symbol))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
