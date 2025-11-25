from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolMeta:
    symbol: str
    asset: str
    exchange: str
    tick_size: float
    multiplier: float
    margin_hint: float


FUTURES = {
    "ES": SymbolMeta(symbol="ES", asset="S&P 500 E-mini", exchange="CME", tick_size=0.25, multiplier=50.0, margin_hint=10000.0),
    "NQ": SymbolMeta(symbol="NQ", asset="Nasdaq 100 E-mini", exchange="CME", tick_size=0.25, multiplier=20.0, margin_hint=10000.0),
    "GC": SymbolMeta(symbol="GC", asset="Gold", exchange="COMEX", tick_size=0.1, multiplier=100.0, margin_hint=7000.0),
    "ZN": SymbolMeta(symbol="ZN", asset="10Y T-Note", exchange="CBOT", tick_size=0.015625, multiplier=1000.0, margin_hint=4000.0),
    "CL": SymbolMeta(symbol="CL", asset="Crude Oil WTI", exchange="NYMEX", tick_size=0.01, multiplier=1000.0, margin_hint=8000.0),
}


def get_symbol_meta(symbol: str) -> SymbolMeta:
    key = symbol.upper()
    if key not in FUTURES:
        raise ValueError(f"Unknown symbol metadata for {symbol}")
    return FUTURES[key]
