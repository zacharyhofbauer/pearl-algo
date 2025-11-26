from __future__ import annotations

from ib_insync import Contract, ContFuture, Future, Stock


def stock(symbol: str, exchange: str | None = None, currency: str = "USD") -> Stock:
    return Stock(symbol=symbol, exchange=exchange or "SMART", currency=currency)


def future(
    symbol: str,
    exchange: str | None = None,
    currency: str = "USD",
    *,
    expiry: str | None = None,
    local_symbol: str | None = None,
    trading_class: str | None = None,
) -> Future:
    # IB routes CME futures on GLOBEX; set the routing accordingly.
    tc = trading_class or symbol
    return Future(
        symbol=symbol,
        exchange=exchange or "GLOBEX",
        currency=currency,
        lastTradeDateOrContractMonth=expiry,
        localSymbol=local_symbol,
        tradingClass=tc,
    )


def continuous_future(symbol: str, exchange: str | None = None) -> ContFuture:
    # IB uses "GLOBEX" for CME continuous futures routing.
    return ContFuture(symbol=symbol, exchange=exchange or "GLOBEX")


def build_contract(
    symbol: str,
    sec_type: str,
    exchange: str | None = None,
    currency: str = "USD",
    *,
    expiry: str | None = None,
    local_symbol: str | None = None,
    trading_class: str | None = None,
) -> Contract:
    stype = sec_type.upper()
    if stype == "STK":
        return stock(symbol, exchange=exchange, currency=currency)
    if stype in {"FUT_CONT", "CONT", "CONT_FUT"}:
        # If an explicit contract is provided, treat it as a dated future.
        if expiry or local_symbol:
            return future(
                symbol,
                exchange=exchange,
                currency=currency,
                expiry=expiry,
                local_symbol=local_symbol,
                trading_class=trading_class,
            )
        return continuous_future(symbol, exchange=exchange)
    if stype == "FUT":
        return future(
            symbol,
            exchange=exchange,
            currency=currency,
            expiry=expiry,
            local_symbol=local_symbol,
            trading_class=trading_class,
        )
    raise ValueError(f"Unsupported sec_type: {sec_type}")
