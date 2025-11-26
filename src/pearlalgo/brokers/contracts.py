from __future__ import annotations

from ib_insync import Contract, ContFuture, Future, Stock


def stock(symbol: str, exchange: str | None = None, currency: str = "USD") -> Stock:
    return Stock(symbol=symbol, exchange=exchange or "SMART", currency=currency)


def future(symbol: str, exchange: str | None = None, currency: str = "USD") -> Future:
    return Future(symbol=symbol, exchange=exchange or "CME", currency=currency)


def continuous_future(symbol: str, exchange: str | None = None) -> ContFuture:
    # IB uses "GLOBEX" for CME continuous futures routing.
    return ContFuture(symbol=symbol, exchange=exchange or "GLOBEX")


def build_contract(symbol: str, sec_type: str, exchange: str | None = None, currency: str = "USD") -> Contract:
    stype = sec_type.upper()
    if stype == "STK":
        return stock(symbol, exchange=exchange, currency=currency)
    if stype in {"FUT_CONT", "CONT", "CONT_FUT"}:
        return continuous_future(symbol, exchange=exchange)
    if stype == "FUT":
        return future(symbol, exchange=exchange, currency=currency)
    raise ValueError(f"Unsupported sec_type: {sec_type}")
