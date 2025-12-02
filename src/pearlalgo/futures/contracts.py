from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ib_insync import Future

FuturesSymbol = Literal["ES", "NQ", "GC"]


@dataclass(frozen=True)
class FutureSpec:
    symbol: str
    exchange: str
    currency: str = "USD"
    trading_class: str | None = None
    multiplier: str | None = None
    tick_value: float | None = None


FUTURES_METADATA: dict[str, FutureSpec] = {
    # Equity index futures (CME/GLOBEX)
    "ES": FutureSpec(
        symbol="ES",
        exchange="GLOBEX",
        trading_class="ES",
        multiplier="50",
        tick_value=12.5,
    ),
    "NQ": FutureSpec(
        symbol="NQ",
        exchange="GLOBEX",
        trading_class="NQ",
        multiplier="20",
        tick_value=20.0,
    ),
    # Metals (COMEX)
    "GC": FutureSpec(
        symbol="GC",
        exchange="COMEX",
        trading_class="GC",
        multiplier="100",
        tick_value=10.0,
    ),
}


def fut_contract(
    symbol: FuturesSymbol, expiry: str | None = None, local_symbol: str | None = None
) -> Future:
    """
    Build an IBKR Future contract for ES/NQ/GC.
    - If local_symbol provided, tradingClass is left to IBKR resolution.
    - If expiry provided, uses YYYYMM (or YYYYMMDD) in lastTradeDateOrContractMonth.
    """
    root = symbol.upper()
    if root not in FUTURES_METADATA:
        raise ValueError(f"Unsupported future symbol: {symbol}")
    spec = FUTURES_METADATA[root]
    tc = spec.trading_class or spec.symbol
    return Future(
        symbol=spec.symbol,
        exchange=spec.exchange,
        currency=spec.currency,
        lastTradeDateOrContractMonth=expiry,
        localSymbol=local_symbol,
        tradingClass=tc,
        multiplier=spec.multiplier,
    )


def es_contract(expiry: str | None = None, local_symbol: str | None = None) -> Future:
    return fut_contract("ES", expiry=expiry, local_symbol=local_symbol)


def nq_contract(expiry: str | None = None, local_symbol: str | None = None) -> Future:
    return fut_contract("NQ", expiry=expiry, local_symbol=local_symbol)


def gc_contract(expiry: str | None = None, local_symbol: str | None = None) -> Future:
    return fut_contract("GC", expiry=expiry, local_symbol=local_symbol)


def available_symbols() -> list[str]:
    return sorted(FUTURES_METADATA.keys())
