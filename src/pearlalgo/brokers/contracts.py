from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone
from typing import Sequence

from ib_insync import Contract, ContractDetails, ContFuture, Future, IB, Stock

logger = logging.getLogger(__name__)


def parse_ib_expiry(expiry: str) -> datetime | None:
    """
    Parse IBKR futures expiry strings (YYYYMM or YYYYMMDD) into a UTC datetime.

    IB sometimes returns month precision (e.g., "202412") and sometimes day
    precision ("20241220"). We normalize both so we can sort/select front
    months reliably.
    """
    if not expiry:
        return None
    clean = expiry.replace("-", "")
    if len(clean) == 6:
        try:
            year, month = int(clean[:4]), int(clean[4:6])
            last_day = calendar.monthrange(year, month)[1]
            return datetime(year, month, last_day, tzinfo=timezone.utc)
        except ValueError:
            return None
    for fmt in ("%Y%m%d",):
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _default_exchange_for_symbol(symbol: str | None) -> str:
    """
    Map common CME-family roots to their primary venue to avoid sec-def 200s.
    YM/ZB/ZN/ZF/ZT are CBOT; CL/NG are NYMEX; GC/SI/HG are COMEX.
    """
    sym = (symbol or "").upper()
    cbot = {"YM", "ZB", "ZN", "ZF", "ZT", "ZC", "ZW", "ZS"}
    nymex = {"CL", "NG", "RB", "HO", "B0"}
    comex = {"GC", "SI", "HG", "PA", "PL"}
    if sym in cbot:
        return "CBOT"
    if sym in nymex:
        return "NYMEX"
    if sym in comex:
        return "COMEX"
    return "CME"


def _exchange_candidates(symbol: str | None, exchange: str | None) -> list[str]:
    """
    Return a deduped list of exchanges to try for CME-family futures.

    Prioritise the symbol's home venue (e.g., YM -> CBOT) to avoid repeated
    200s when CME/GLOBEX do not host that contract.
    """
    exchange = exchange.upper() if exchange else None
    base_order = ["CME", "GLOBEX", "CBOT", "NYMEX", "COMEX", "ECBOT"]
    preferred = _default_exchange_for_symbol(symbol)
    exchanges: list[str] = [preferred]
    if exchange:
        exchanges.insert(0, exchange)
    exchanges.extend(base_order)
    seen: set[str] = set()
    return [ex for ex in exchanges if not (ex in seen or seen.add(ex))]


def _expiry_matches(candidate: str, target: str) -> bool:
    """Allow matching YYYYMM with YYYYMMDD or vice versa."""
    cand = (candidate or "").replace("-", "")
    targ = (target or "").replace("-", "")
    if not targ:
        return True
    if cand.startswith(targ):
        return True
    if len(targ) == 6 and len(cand) == 8 and cand.startswith(targ):
        return True
    if len(targ) == 8 and len(cand) == 6 and cand.startswith(targ[:6]):
        return True
    return False


def discover_future_contracts(
    ib: IB,
    symbol: str,
    *,
    exchange: str | None = None,
    currency: str = "USD",
) -> list[ContractDetails]:
    """
    Ask IBKR for all contract details for a futures root.

    We intentionally request with only symbol/secType/exchange to let IBKR tell
    us which exact expiries/localSymbols/conIds exist; using ad-hoc expiry
    strings is what usually triggers error 200.
    """
    details: list[ContractDetails] = []
    seen: set[int] = set()
    for exch in _exchange_candidates(symbol, exchange):
        try:
            res = ib.reqContractDetails(Future(symbol=symbol, exchange=exch, currency=currency))
        except Exception as exc:  # pragma: no cover - requires live IB
            logger.warning("ContractDetails lookup failed for %s on %s: %s", symbol, exch, exc)
            continue
        if not res:
            continue
        for det in res:
            cid = getattr(det.contract, "conId", 0)
            if cid and cid in seen:
                continue
            seen.add(cid)
            details.append(det)
        if details:
            break
    details.sort(
        key=lambda d: parse_ib_expiry(getattr(d.contract, "lastTradeDateOrContractMonth", "") or "") or datetime.max.replace(tzinfo=timezone.utc)
    )
    return details


def _select_from_details(
    details: Sequence[ContractDetails],
    *,
    target_expiry: str | None = None,
    local_symbol: str | None = None,
    trading_class: str | None = None,
) -> Contract | None:
    now = datetime.now(timezone.utc)
    filtered: list[ContractDetails] = []
    for det in details:
        c = det.contract
        if local_symbol and c.localSymbol != local_symbol:
            continue
        if trading_class and getattr(c, "tradingClass", None) not in {trading_class, c.symbol}:
            continue
        exp = getattr(c, "lastTradeDateOrContractMonth", "") or ""
        if target_expiry and not _expiry_matches(exp, target_expiry):
            continue
        exp_dt = parse_ib_expiry(exp)
        if not target_expiry and exp_dt and exp_dt <= now:
            # Skip expired/expiring contracts when no target is requested.
            continue
        filtered.append(det)

    candidates = filtered or list(details)
    if not candidates:
        return None
    candidates.sort(
        key=lambda d: parse_ib_expiry(getattr(d.contract, "lastTradeDateOrContractMonth", "") or "") or datetime.max.replace(tzinfo=timezone.utc)
    )
    return candidates[0].contract


def resolve_future_contract(
    ib: IB,
    symbol: str,
    *,
    exchange: str | None = None,
    currency: str = "USD",
    target_expiry: str | None = None,
    local_symbol: str | None = None,
    trading_class: str | None = None,
) -> Future | None:
    """
    Discover and return a fully-specified futures contract for IBKR requests.

    This avoids error 200 by:
    1) Discovering all contract details for the symbol via reqContractDetails with
       only the root symbol/exchange.
    2) Selecting a contract that matches the requested expiry/localSymbol/tradingClass.
       If no filters are given, the front (nearest future) is returned.
    3) Returning the contract (qualified if needed) that IBKR will accept.
    """
    details = discover_future_contracts(ib, symbol, exchange=exchange, currency=currency)
    if not details:
        logger.warning("No futures contracts returned for %s on %s", symbol, exchange or "GLOBEX/CME")
        return None

    contract = _select_from_details(
        details,
        target_expiry=target_expiry,
        local_symbol=local_symbol,
        trading_class=trading_class or symbol,
    )
    if contract is None:
        logger.warning(
            "No matching contract for %s expiry=%s local=%s tc=%s",
            symbol,
            target_expiry,
            local_symbol,
            trading_class,
        )
        return None

    try:
        qualified = ib.qualifyContracts(contract)
        if qualified:
            contract = qualified[0]
    except Exception as exc:  # pragma: no cover - requires live IB
        logger.warning("Qualification failed for %s on %s: %s", symbol, contract.exchange, exc)
    return contract


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
    # Route to the symbol's home venue (e.g., YM -> CBOT, CL -> NYMEX). If using only a local symbol,
    # leave tradingClass unset so IBKR can match the contract.
    tc = trading_class or symbol if local_symbol is None else None
    return Future(
        symbol=symbol,
        exchange=exchange or _default_exchange_for_symbol(symbol),
        currency=currency,
        lastTradeDateOrContractMonth=expiry,
        localSymbol=local_symbol,
        tradingClass=tc,
    )


def continuous_future(symbol: str, exchange: str | None = None) -> ContFuture:
    # IB may require the symbol's home venue for routing continuous CME futures.
    return ContFuture(symbol=symbol, exchange=exchange or _default_exchange_for_symbol(symbol))


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
