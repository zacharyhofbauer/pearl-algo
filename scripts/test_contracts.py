#!/usr/bin/env python
"""
Futures discovery helper for IBKR.

IB returns error 200 when futures are requested with guessed expiry/localSymbol
combinations. The safe pattern is:
1) Ask reqContractDetails with only symbol/secType/exchange to discover the
   canonical expiries, localSymbols, tradingClasses, and conIds IB knows about.
2) Use those discovered values (or conId directly) when requesting details or
   placing orders.

This script demonstrates that flow for ES and NQ (and can be extended to other
Globex futures easily).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from ib_insync import IB

from pearlalgo.futures.contracts import available_symbols, fut_contract


def _parse_expiry(expiry: str) -> datetime | None:
    clean = (expiry or "").replace("-", "")
    if len(clean) == 6:
        year, month = int(clean[:4]), int(clean[4:6])
        # Use last day of month to approximate expiry boundary
        if month < 1 or month > 12:
            return None
        return datetime(year, month, 1, tzinfo=timezone.utc)
    if len(clean) == 8:
        try:
            return datetime.strptime(clean, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _format_contract(det) -> str:
    c = det.contract
    expiry = c.lastTradeDateOrContractMonth or "-"
    expiry_dt = _parse_expiry(expiry)
    expiry_fmt = expiry_dt.date().isoformat() if expiry_dt else expiry
    return (
        f"{c.symbol} localSymbol={c.localSymbol} expiry={expiry} ({expiry_fmt}) "
        f"tc={getattr(c, 'tradingClass', '')} conId={getattr(c, 'conId', '')} exchange={c.exchange}"
    )


def _choose_upcoming_expiry(details) -> str | None:
    now = datetime.now(timezone.utc)
    for det in details:
        exp = det.contract.lastTradeDateOrContractMonth or ""
        exp_dt = _parse_expiry(exp)
        if exp_dt and exp_dt > now:
            return exp
    return None


def _request_and_report(
    ib: IB, symbol: str, *, expiry: str | None = None, label: str = ""
) -> None:
    contract = fut_contract(symbol, expiry=expiry)
    try:
        cds = ib.reqContractDetails(contract)
        if not cds:
            print(f"✗ {symbol} {label or 'front'} -> request returned no details")
            return
        c = cds[0].contract
        exp = c.lastTradeDateOrContractMonth
        print(
            f"✓ {symbol} {label or 'front'} -> localSymbol={c.localSymbol}, expiry={exp}, conId={c.conId}"
        )
    except Exception as exc:  # pragma: no cover - requires live IB
        print(f"✗ {symbol} {label or 'front'} -> {exc}")


def inspect_symbol(ib: IB, symbol: str) -> None:
    print(f"\n=== {symbol} discovery ===")
    base_contract = fut_contract(symbol)
    try:
        details = ib.reqContractDetails(base_contract)
    except Exception as exc:  # pragma: no cover - requires live IB
        print(f"✗ {symbol} request failed: {exc}")
        return
    if not details:
        print(f"✗ No futures discovered for {symbol} on GLOBEX/CME")
        return

    print("Discovered contracts (first 10):")
    for det in details[:10]:
        print("  - " + _format_contract(det))

    upcoming_expiry = _choose_upcoming_expiry(details)
    if not upcoming_expiry:
        print("✗ No upcoming expiry identified; cannot request explicit contract")
        return

    # Demonstrate both full and month-only expiry formats to show tolerance.
    _request_and_report(ib, symbol, expiry=upcoming_expiry, label="exact expiry")
    _request_and_report(ib, symbol, expiry=upcoming_expiry[:6], label="YYYYMM")
    # Also show front-month selection when no expiry is provided.
    _request_and_report(ib, symbol, expiry=None, label="front-month (auto)")


def main() -> int:
    ib = IB()
    try:
        ib.connect("127.0.0.1", 4002, clientId=999)
        print("Connected to IBKR\n")
        for sym in available_symbols():
            inspect_symbol(ib, sym)
    finally:
        ib.disconnect()
        print("\nDisconnected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
