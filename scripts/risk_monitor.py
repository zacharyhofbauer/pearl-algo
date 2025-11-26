#!/usr/bin/env python
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def current_pnl(trades_path: Path) -> float:
    if not trades_path.exists():
        return 0.0
    df = pd.read_csv(trades_path)
    if "pnl_after" in df.columns and not df.empty:
        return df["pnl_after"].iloc[-1]
    return 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simple risk monitor loop.")
    parser.add_argument("--max-daily-loss", type=float, default=None, help="Trigger halt if breached.")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between checks.")
    args = parser.parse_args(argv)

    trades_path = Path("journal/trades.csv")
    halt_file = Path("RISK_HALT")

    try:
        while True:
            ts = datetime.now(timezone.utc).isoformat()
            pnl = current_pnl(trades_path)
            if args.max_daily_loss is not None and pnl < -abs(args.max_daily_loss):
                halt_file.write_text(f"{ts} Breached max daily loss {args.max_daily_loss}, pnl={pnl}\n")
                print(f"[{ts}] RISK HALT: pnl={pnl} < -{args.max_daily_loss}. Wrote {halt_file}")
                break
            if halt_file.exists():
                print(f"[{ts}] RISK HALT file exists; stop trading.")
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Risk monitor stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
