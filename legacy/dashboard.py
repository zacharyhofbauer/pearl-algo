#!/usr/bin/env python
from __future__ import annotations

import argparse
import curses
import time
from pathlib import Path
import pandas as pd


def load_signals(path: Path):
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_trades(path: Path):
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def draw_screen(stdscr, symbols, signals_path, trades_path, interval):
    curses.curs_set(0)
    while True:
        stdscr.erase()
        sigs = load_signals(signals_path)
        trades = load_trades(trades_path)
        stdscr.addstr(0, 0, f"Dashboard (signals: {signals_path.name}, trades: {trades_path.name})")
        row = 2
        stdscr.addstr(row, 0, "Symbol  Direction  Size  LastPrice")
        row += 1
        for sym in symbols:
            direction = "NA"
            size = "-"
            if not sigs.empty:
                latest = sigs[sigs["symbol"] == sym]
                if not latest.empty:
                    latest = latest.iloc[-1]
                    direction = latest.get("direction", "FLAT")
                    size = latest.get("size_hint", "-")
            stdscr.addstr(row, 0, f"{sym:<6} {direction:<9} {size:<4} -")
            row += 1
        row += 1
        stdscr.addstr(row, 0, "Risk / PnL")
        row += 1
        pnl = 0.0
        if not trades.empty and "pnl_after" in trades.columns:
            pnl = trades["pnl_after"].iloc[-1]
        stdscr.addstr(row, 0, f"Daily PnL: {pnl}")
        row += 2
        stdscr.addstr(row, 0, "Press Ctrl+C to exit.")
        stdscr.refresh()
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Terminal dashboard (curses).")
    parser.add_argument("--symbols", nargs="+", default=["ES", "NQ", "SPY", "QQQ"])
    parser.add_argument("--signals", default=None, help="Signals CSV path (default: latest in signals/)")
    parser.add_argument("--interval", type=int, default=2)
    args = parser.parse_args(argv)

    if args.signals:
        signals_path = Path(args.signals)
    else:
        sig_dir = Path("signals")
        candidates = sorted(sig_dir.glob("*_signals.csv"))
        signals_path = candidates[-1] if candidates else Path("signals/latest.csv")
    trades_path = Path("journal/trades.csv")

    curses.wrapper(draw_screen, args.symbols, signals_path, trades_path, args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
