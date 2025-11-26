#!/usr/bin/env python
from __future__ import annotations

"""
Paper loop using the futures core: fetch data, generate signals, size with prop profile, and route tiny IBKR paper orders.
"""

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pearlalgo.agents.execution_agent import ExecutionAgent
from pearlalgo.brokers.dummy_backtest import DummyBacktestBroker
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.data.loaders import load_csv
from pearlalgo.data_providers.ibkr_data_provider import IBKRConnection, IBKRDataProvider
from pearlalgo.futures.config import load_profile
from pearlalgo.futures.performance import PerformanceRow, log_performance_row
from pearlalgo.futures.risk import compute_position_size, compute_risk_state
from pearlalgo.futures.signals import generate_signal
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.core.events import FillEvent


def fetch_data(
    provider: IBKRDataProvider,
    symbol: str,
    sec_type: str,
    source: str,
    data_path: Path | None = None,
    *,
    expiry: str | None = None,
    local_symbol: str | None = None,
    trading_class: str | None = None,
):
    if source == "csv":
        if not data_path:
            raise ValueError("CSV source requires --data-path")
        return load_csv(data_path)
    return provider.fetch_historical(
        symbol,
        sec_type=sec_type,
        duration="2 D",
        bar_size="15 mins",
        expiry=expiry,
        local_symbol=local_symbol,
        trading_class=trading_class or symbol,
    )


def compute_atr(df: pd.DataFrame, window: int = 14) -> float | None:
    """Lightweight ATR; returns None if data insufficient."""
    required = {"High", "Low", "Close"}
    if not required.issubset(set(df.columns)):
        return None
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_series = tr.rolling(window=window).mean()
    atr_val = atr_series.iloc[-1]
    return float(atr_val) if not pd.isna(atr_val) else None


def portfolio_pnls(portfolio: Portfolio, marks: dict[str, float]) -> tuple[float, float]:
    """
    Compute aggregate realized/unrealized PnL from the portfolio given mark prices.
    Realized comes from Position.realized_pnl; unrealized marks open positions.
    """
    realized = 0.0
    unrealized = 0.0
    for sym, pos in portfolio.positions.items():
        realized += pos.realized_pnl
        if pos.size != 0:
            price = marks.get(sym, pos.avg_price)
            unrealized += pos.size * (price - pos.avg_price)
    return realized, unrealized


def apply_fills(portfolio: Portfolio, fills: list[FillEvent]) -> None:
    """Apply broker fills to the portfolio."""
    for fill in fills:
        portfolio.update_with_fill(fill)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Paper loop: fetch data, generate signals, size with prop profile, send tiny orders."
    )
    parser.add_argument("--symbols", nargs="+", default=["ES", "NQ", "GC"])
    parser.add_argument("--sec-types", nargs="+", default=["FUT", "FUT", "FUT"])
    parser.add_argument("--strategy", choices=["ma_cross"], default="ma_cross")
    parser.add_argument("--source", choices=["ibkr", "csv"], default="ibkr")
    parser.add_argument("--data-paths", nargs="*", help="CSV paths matching symbols when source=csv")
    parser.add_argument("--interval", type=int, default=300, help="Loop interval seconds")
    parser.add_argument("--profile-config", default=None, help="Optional prop profile config (yaml/json)")
    parser.add_argument("--mode", choices=["print", "ibkr-paper"], default="print")
    parser.add_argument("--ib-host", default=None, help="IB host override")
    parser.add_argument("--ib-port", type=int, default=None, help="IB port override")
    parser.add_argument("--ib-client-id", type=int, default=None, help="IB clientId override")
    parser.add_argument("--expiries", nargs="*", help="Optional futures expiries (YYYYMM or YYYYMMDD) matching symbols")
    parser.add_argument("--local-symbols", nargs="*", help="Optional IBKR local symbols matching symbols")
    parser.add_argument("--trading-classes", nargs="*", help="Optional trading classes matching symbols (defaults to symbol)")
    args = parser.parse_args(argv)

    profile = load_profile(args.profile_config)
    settings = get_settings()
    ib_data_client_id = (
        settings.ib_data_client_id
        if settings.ib_data_client_id is not None
        else args.ib_client_id + 1
        if args.ib_client_id is not None
        else settings.ib_client_id + 1
    )
    ib_settings = Settings(
        allow_live_trading=True,
        profile="live",
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

    portfolio = Portfolio(cash=profile.starting_balance)
    risk_guard = RiskGuard(RiskLimits(max_daily_loss=profile.daily_loss_limit))
    provider = IBKRDataProvider(settings=ib_settings, connection=data_connection)

    if args.mode == "ibkr-paper":
        broker = IBKRBroker(portfolio, settings=ib_settings, risk_guard=risk_guard)
        exec_agent = ExecutionAgent(broker, symbol="N/A", profile="live", risk_guard=risk_guard)
    else:
        broker = DummyBacktestBroker(portfolio)
        exec_agent = ExecutionAgent(broker, symbol="N/A", profile="paper", risk_guard=risk_guard)

    data_paths = args.data_paths or []
    expiries = args.expiries or []
    local_symbols = args.local_symbols or []
    trading_classes = args.trading_classes or []

    print(
        "IBKR connections -> data clientId=%s, orders clientId=%s, host=%s, port=%s"
        % (data_connection.client_id, ib_settings.ib_client_id, ib_settings.ib_host, ib_settings.ib_port)
    )

    last_fill_ts: datetime | None = None

    try:
        while True:
            for idx, sym in enumerate(args.symbols):
                sec_type = args.sec_types[idx] if idx < len(args.sec_types) else "STK"
                path = Path(data_paths[idx]) if args.source == "csv" and idx < len(data_paths) else None
                expiry = expiries[idx] if idx < len(expiries) else None
                local_symbol = local_symbols[idx] if idx < len(local_symbols) else None
                trading_class = trading_classes[idx] if idx < len(trading_classes) else sym
                ts = datetime.now(timezone.utc).isoformat()
                try:
                    df = fetch_data(
                        provider,
                        sym,
                        sec_type,
                        args.source,
                        path,
                        expiry=expiry,
                        local_symbol=local_symbol,
                        trading_class=trading_class,
                    )
                    if df.empty:
                        print(f"[{ts}] {sym} {sec_type} no data")
                        continue
                    signal = generate_signal(sym, df, strategy_name=args.strategy, fast=20, slow=50)
                    side = signal["side"]
                    if side == "flat":
                        print(f"[{ts}] {sym} {sec_type} {args.strategy}: FLAT")
                        continue

                    price = float(df["Close"].iloc[-1])
                    marks = {sym: price}
                    realized_pnl, unrealized_pnl = portfolio_pnls(portfolio, marks)
                    risk_state = compute_risk_state(
                        profile,
                        day_start_equity=profile.starting_balance,
                        realized_pnl=realized_pnl,
                        unrealized_pnl=unrealized_pnl,
                    )
                    size = compute_position_size(sym, side, profile, risk_state, price=price)
                    if size == 0:
                        print(f"[{ts}] {sym} {sec_type} {args.strategy}: blocked by risk state {risk_state.status}")
                        continue

                    atr_val = compute_atr(df)
                    risk_label = "SAFE" if risk_state.status == "OK" else "NEAR_LIMIT" if risk_state.status == "NEAR_LIMIT" else "BLOCKED_DD"
                    print(
                        f"[{ts}] {sym} {sec_type} {args.strategy}: {side.upper()} qty={abs(size)} "
                        f"risk={risk_label} price={price}"
                    )

                    sig_df = pd.DataFrame(
                        {
                            "entry": [1 if side == "long" else -1],
                            "size": [abs(size)],
                            "sec_type": [sec_type],
                            "expiry": [expiry],
                            "local_symbol": [local_symbol],
                            "trading_class": [trading_class],
                            "Close": [price],
                        },
                        index=[df.index[-1]],
                    )
                    exec_agent.symbol = sym
                    exec_agent.execute(sig_df)
                    # Apply any available fills from the broker (IBKR or dummy).
                    fills = list(broker.fetch_fills(since=last_fill_ts))
                    if fills:
                        apply_fills(portfolio, fills)
                        last_fill_ts = max((f.timestamp for f in fills), default=last_fill_ts)

                    # Recompute PnL after potential fills and log decision/trade.
                    realized_pnl_after, unrealized_pnl_after = portfolio_pnls(portfolio, {sym: price})
                    log_performance_row(
                        PerformanceRow(
                            timestamp=datetime.now(timezone.utc),
                            symbol=sym,
                            sec_type=sec_type,
                            strategy_name=signal["strategy_name"],
                            side=side,
                            requested_size=size,
                            filled_size=size if args.mode == "ibkr-paper" else 0,
                            entry_price=price,
                            realized_pnl=realized_pnl_after,
                            unrealized_pnl=unrealized_pnl_after,
                            fast_ma=signal.get("fast_ma"),
                            slow_ma=signal.get("slow_ma"),
                            risk_status=risk_label,
                            notes="live_paper_loop",
                        )
                    )
                except Exception as exc:
                    print(f"[{ts}] WARN {sym} failed: {exc}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Exiting paper loop.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
