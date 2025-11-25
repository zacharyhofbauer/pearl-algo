from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Literal

import pandas as pd
from dotenv import load_dotenv
from ib_insync import IB, Future, Stock

from pearlalgo.config.settings import get_settings
from pearlalgo.utils.logging import setup_logging

SecurityType = Literal["STK", "FUT"]
logger = logging.getLogger(__name__)

# Default download targets; can be overridden with CLI flags later if needed.
DEFAULT_TASKS = [
    ("SPY", "STK", "1 D", "5 mins", Path("data/equities/SPY_ib_5m.csv")),
    ("ES", "FUT", "1 D", "15 mins", Path("data/futures/ES_ib_15m.csv")),
]


def make_contract(symbol: str, sec_type: SecurityType, exchange: str | None = None):
    """
    Build an IBKR contract for stocks or futures.
    - Stocks default to SMART / USD
    - Futures default to CME / USD and require a continuous-like symbol (e.g., ES, NQ).
    """
    if sec_type == "STK":
        return Stock(symbol=symbol, exchange=exchange or "SMART", currency="USD")
    return Future(symbol=symbol, exchange=exchange or "CME", currency="USD")


def download_symbol(
    ib: IB,
    symbol: str,
    sec_type: SecurityType,
    duration: str,
    bar_size: str,
    output_path: Path,
    what_to_show: str = "TRADES",
) -> None:
    """Download historical bars and save to CSV."""
    contract = make_contract(symbol, sec_type)
    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=False,
            formatDate=1,
        )
    except Exception as exc:  # pragma: no cover - requires IB
        raise RuntimeError(f"IBKR request failed for {symbol}: {exc}") from exc

    if not bars:
        raise RuntimeError(f"No data returned for {symbol} ({sec_type})")

    df = pd.DataFrame(bars)
    df = df.rename(columns=str.title)
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path)
    logger.info("[OK] Saved %s (%s) %s rows -> %s", symbol, sec_type, len(df), output_path)


def run_download(host: str, port: int, client_id: int) -> None:
    ib = IB()
    logger.info("Connecting to IBKR Gateway %s:%s (clientId=%s) ...", host, port, client_id)
    try:
        ib.connect(host, port, clientId=client_id)
    except Exception as exc:  # pragma: no cover - requires IB
        raise SystemExit(
            f"Failed to connect to IBKR at {host}:{port} (clientId={client_id}). "
            "Ensure IB Gateway is running and API is enabled. "
            f"Error: {exc}"
        )

    try:
        for symbol, sec_type, duration, bar_size, out_path in DEFAULT_TASKS:
            try:
                download_symbol(
                    ib,
                    symbol=symbol,
                    sec_type=sec_type,  # type: ignore[arg-type]
                    duration=duration,
                    bar_size=bar_size,
                    output_path=out_path,
                )
            except Exception as exc:
                logger.error("[ERR] %s (%s) failed: %s", symbol, sec_type, exc)
            time.sleep(1)  # pacing guard to avoid IBKR rate limits
    finally:
        ib.disconnect()
        logger.info("Disconnected from IBKR.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IBKR historical data downloader (paper-safe).")
    parser.add_argument("--host", default=None, help="IBKR host (default from settings or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="IBKR port (default from settings or 4002)")
    parser.add_argument("--client-id", type=int, default=None, help="IBKR clientId (default from settings or 1)")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    setup_logging()
    settings = get_settings()
    parser = build_parser()
    args = parser.parse_args(argv)

    host = args.host or settings.ib_host or "127.0.0.1"
    port = args.port or settings.ib_port or 4002
    client_id = args.client_id or settings.ib_client_id or 1

    # Safety: this script only fetches data; no orders are placed.
    run_download(host=host, port=int(port), client_id=int(client_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
