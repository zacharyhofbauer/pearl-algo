#!/usr/bin/env python
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

from pearlalgo.agents.execution_agent import ExecutionAgent
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.data.loaders import load_csv
from pearlalgo.data_providers.ibkr_data_provider import IBKRConnection, IBKRDataProvider
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.risk.pnl import DailyPnLTracker
from pearlalgo.strategies.daily import MovingAverageCross, Breakout
from pearlalgo.utils.brain_log import brain_log
from pearlalgo.utils.journal import append_trade


def fetch_data(
    provider: IBKRDataProvider,
    symbol: str,
    sec_type: str,
    source: str,
    data_path: Path | None = None,
):
    if source == "csv":
        if not data_path:
            raise ValueError("CSV source requires --data-path")
        return load_csv(data_path)
    # 2 days of 15m bars for a simple intraday view
    return provider.fetch_historical(symbol, sec_type=sec_type, duration="2 D", bar_size="15 mins")


def select_strategy(name: str):
    if name == "ma_cross":
        return MovingAverageCross(fast=10, slow=20)
    return Breakout(lookback=20)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-only loop: fetch data, run strategy, send tiny IBKR paper orders.")
    parser.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    parser.add_argument("--sec-types", nargs="+", default=["FUT_CONT", "FUT_CONT"])
    parser.add_argument("--strategy", choices=["ma_cross", "breakout"], default="ma_cross")
    parser.add_argument("--source", choices=["ibkr", "csv"], default="ibkr")
    parser.add_argument("--data-paths", nargs="*", help="CSV paths matching symbols when source=csv")
    parser.add_argument("--interval", type=int, default=300, help="Loop interval seconds")
    parser.add_argument("--tiny-size", type=float, default=0.1, help="Position size to send (paper)")
    parser.add_argument("--max-daily-loss", type=float, default=None, help="Block orders if PnL below -X")
    parser.add_argument("--max-open-per-asset", type=int, default=None, help="Max open positions per asset class (placeholder)")
    parser.add_argument("--ib-host", default=None, help="IB host override (default from settings)")
    parser.add_argument("--ib-port", type=int, default=None, help="IB port override (default from settings)")
    parser.add_argument("--ib-client-id", type=int, default=None, help="IB clientId override (default from settings)")
    args = parser.parse_args(argv)

    settings = get_settings()
    ib_data_client_id = (
        settings.ib_data_client_id
        if settings.ib_data_client_id is not None
        else args.ib_client_id + 1
        if args.ib_client_id is not None
        else settings.ib_client_id + 1
    )
    ib_settings = Settings(
        allow_live_trading=True,  # needed for IBKRBroker to route
        profile="live",  # IBKRBroker checks this; still use paper Gateway (port 4002)
        ib_host=args.ib_host or settings.ib_host,
        ib_port=args.ib_port or settings.ib_port,
        ib_client_id=args.ib_client_id or settings.ib_client_id,
        ib_data_client_id=ib_data_client_id,
    )
    data_connection = IBKRConnection(
        host=ib_settings.ib_host,
        port=int(ib_settings.ib_port),
        client_id=int(ib_settings.ib_data_client_id or ib_data_client_id),
    )

    portfolio = Portfolio(cash=100000)
    risk_limits = RiskLimits(
        max_daily_loss=args.max_daily_loss,
    )
    risk_guard = RiskGuard(risk_limits, pnl_tracker=DailyPnLTracker())
    broker = IBKRBroker(portfolio, settings=ib_settings, risk_guard=risk_guard)
    exec_agent = ExecutionAgent(broker, symbol="N/A", profile="live", risk_guard=risk_guard)
    provider = IBKRDataProvider(settings=ib_settings, connection=data_connection)

    data_paths = args.data_paths or []
    strat = select_strategy(args.strategy)

    print(
        "IBKR connections -> data clientId=%s, orders clientId=%s, host=%s, port=%s"
        % (data_connection.client_id, ib_settings.ib_client_id, ib_settings.ib_host, ib_settings.ib_port)
    )

    try:
        while True:
            for idx, sym in enumerate(args.symbols):
                sec_type = args.sec_types[idx] if idx < len(args.sec_types) else "STK"
                path = Path(data_paths[idx]) if args.source == "csv" and idx < len(data_paths) else None
                ts = datetime.now(timezone.utc).isoformat()
                try:
                    df = fetch_data(provider, sym, sec_type, args.source, path)
                    sigs = strat.run(df)
                    latest = sigs.iloc[-1] if not sigs.empty else None
                    if latest is None:
                        print(f"[{ts}] {sym} {sec_type} no data")
                        continue
                    entry = latest.get("entry", 0)
                    direction = "BUY" if entry > 0 else "SELL" if entry < 0 else "FLAT"
                    if direction == "FLAT":
                        print(f"[{ts}] {sym} {sec_type} {args.strategy}: FLAT")
                        continue
                    size = args.tiny_size
                    print(f"[{ts}] {sym} {sec_type} {args.strategy}: sending {direction} qty={size} (paper)")
                    brain_log(
                        {
                            "symbol": sym,
                            "sec_type": sec_type,
                            "strategy": args.strategy,
                            "direction": direction,
                            "size": size,
                            "features": {
                                "entry": float(entry),
                                "price": float(df["Close"].iloc[-1]),
                            },
                            "risk": {
                                "max_daily_loss": args.max_daily_loss,
                                "pnl_realized": risk_guard.pnl_tracker.realized_today(),
                            },
                        }
                    )
                    append_trade(
                        {
                            "symbol": sym,
                            "direction": direction,
                            "size": size,
                            "price": float(df["Close"].iloc[-1]),
                            "reason": args.strategy,
                            "pnl_after": risk_guard.pnl_tracker.realized_today(),
                            "risk_state": "ok",
                        }
                    )
                    # Build a one-row signals df for ExecutionAgent
                    sig_df = latest.to_frame().T
                    sig_df.index = [df.index[-1]]
                    sig_df["entry"] = 1 if direction == "BUY" else -1
                    sig_df["size"] = size
                    sig_df["sec_type"] = sec_type
                    # Snapshot/telemetry
                    snapshot_dir = Path("state_cache")
                    snapshot_dir.mkdir(parents=True, exist_ok=True)
                    snap_path = snapshot_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pkl"
                    import pickle
                    pickle.dump(
                        {
                            "symbol": sym,
                            "sec_type": sec_type,
                            "strategy": args.strategy,
                            "entry": entry,
                            "close": float(df["Close"].iloc[-1]),
                            "risk_ok": True,
                        },
                        snap_path.open("wb"),
                    )
                    telem_dir = Path("telemetry")
                    telem_dir.mkdir(parents=True, exist_ok=True)
                    with (telem_dir / "strategy_stream.jsonl").open("a") as f:
                        f.write(
                            (
                                f'{{"timestamp":"{ts}","symbol":"{sym}","strategy":"{args.strategy}",'
                                f'"direction":"{direction}","signal_strength":{abs(entry)},'
                                f'"raw_indicators":{{"entry":{entry}}}}}\n'
                            )
                        )

                    exec_agent.symbol = sym
                    exec_agent.execute(sig_df)
                except Exception as exc:
                    print(f"[{ts}] WARN {sym} failed: {exc}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Exiting paper loop.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
