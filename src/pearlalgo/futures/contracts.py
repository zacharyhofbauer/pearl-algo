from __future__ import annotations

from dataclasses import dataclass

from ib_insync import Future


@dataclass(frozen=True)
class FutureSpec:
    symbol: str
    exchange: str
    currency: str = "USD"
    trading_class: str | None = None
    multiplier: str | None = None


def _make_future(spec: FutureSpec, expiry: str | None = None, local_symbol: str | None = None) -> Future:
    return Future(
        symbol=spec.symbol,
        exchange=spec.exchange,
        currency=spec.currency,
        lastTradeDateOrContractMonth=expiry,
        localSymbol=local_symbol,
        tradingClass=spec.trading_class or spec.symbol,
        multiplier=spec.multiplier,
    )


FUTURES_SPECS: dict[str, FutureSpec] = {
    "ES": FutureSpec(symbol="ES", exchange="CME", trading_class="ES", multiplier="50"),
    "MES": FutureSpec(symbol="MES", exchange="CME", trading_class="MES", multiplier="5"),
    "NQ": FutureSpec(symbol="NQ", exchange="CME", trading_class="NQ", multiplier="20"),
    "MNQ": FutureSpec(symbol="MNQ", exchange="CME", trading_class="MNQ", multiplier="2"),
    "GC": FutureSpec(symbol="GC", exchange="COMEX", trading_class="GC", multiplier="100"),
    "MGC": FutureSpec(symbol="MGC", exchange="COMEX", trading_class="MGC", multiplier="10"),
}


def build_future(symbol: str, *, expiry: str | None = None, local_symbol: str | None = None) -> Future:
    """
    Build an IBKR Future for supported symbols.
    """
    root = symbol.upper()
    if root not in FUTURES_SPECS:
        raise ValueError(f"Unsupported future symbol: {symbol}")
    spec = FUTURES_SPECS[root]
    return _make_future(spec, expiry=expiry, local_symbol=local_symbol)


def available_symbols() -> list[str]:
    return sorted(FUTURES_SPECS.keys())
