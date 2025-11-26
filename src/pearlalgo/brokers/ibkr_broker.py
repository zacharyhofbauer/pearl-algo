from __future__ import annotations

import calendar
import logging
from datetime import datetime
from typing import Dict, Iterable

from ib_insync import IB, ContFuture, Future, LimitOrder, MarketOrder, Stock, StopLimitOrder, StopOrder

from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.brokers.contracts import build_contract

logger = logging.getLogger(__name__)


def _contract(symbol: str, sec_type: str = "STK", exchange: str | None = None):
    exch = exchange or ("GLOBEX" if sec_type.upper() == "FUT" else "SMART")
    if sec_type.upper() == "FUT":
        return Future(symbol=symbol, exchange=exch, currency="USD")
    return Stock(symbol=symbol, exchange=exch, currency="USD")


class IBKRBroker(Broker):
    """
    Minimal IBKR broker adapter using ib_insync.

    Safe-by-default: unless allow_live_trading and profile=live are set, orders are logged and not sent.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        settings: Settings | None = None,
        config: BrokerConfig | None = None,
        risk_guard: RiskGuard | None = None,
    ):
        super().__init__(portfolio, config)
        self.settings = settings or get_settings()
        self._ib = IB()
        self._dry_run_counter = 0
        # Minimal guard; extend with PnL tracking and live position checks.
        self.risk_guard = risk_guard or RiskGuard(RiskLimits())

    # --- Connection helpers -------------------------------------------------
    def _connect(self) -> IB:
        if self._ib.isConnected():
            return self._ib
        self._ib.connect(self.settings.ib_host, int(self.settings.ib_port), clientId=int(self.settings.ib_client_id))
        return self._ib

    @staticmethod
    def _parse_ib_expiry(expiry: str) -> datetime | None:
        clean = expiry.replace("-", "")
        if len(clean) == 6:
            try:
                year, month = int(clean[:4]), int(clean[4:6])
                last_day = calendar.monthrange(year, month)[1]
                return datetime(year, month, last_day)
            except ValueError:
                return None
        for fmt in ("%Y%m%d",):
            try:
                return datetime.strptime(clean, fmt)
            except ValueError:
                continue
        return None

    def _resolve_front_future(self, ib: IB, symbol: str, exchange: str | None = None) -> Future:
        exch = exchange or "GLOBEX"
        candidates = []
        now = datetime.utcnow()

        try:
            details = ib.reqContractDetails(ContFuture(symbol=symbol, exchange=exch))
            if not details:
                details = ib.reqContractDetails(Future(symbol=symbol, exchange=exch, currency="USD"))
        except Exception as exc:
            logger.warning("IBKR contract lookup failed for %s on %s: %s", symbol, exch, exc)
            details = []

        for det in details or []:
            expiry = det.contract.lastTradeDateOrContractMonth or ""
            expiry_dt = self._parse_ib_expiry(expiry)
            if not expiry_dt or expiry_dt <= now:
                continue
            candidates.append((expiry_dt, det.contract))

        if not candidates:
            logger.warning("No valid front-month contract found for %s on %s; using fallback future", symbol, exch)
            return Future(symbol=symbol, exchange=exch, currency="USD")

        front_contract = sorted(candidates, key=lambda item: item[0])[0][1]
        try:
            qualified = ib.qualifyContracts(front_contract)
            if qualified:
                front_contract = qualified[0]
        except Exception as exc:
            logger.warning("Qualification failed for %s on %s: %s", symbol, exch, exc)
        return front_contract

    def _resolve_contract(
        self,
        ib: IB,
        symbol: str,
        sec_type: str,
        exchange: str | None = None,
        *,
        expiry: str | None = None,
        local_symbol: str | None = None,
        trading_class: str | None = None,
    ):
        stype = sec_type.upper()
        if stype.startswith("FUT") and (expiry or local_symbol):
            return build_contract(
                symbol,
                sec_type="FUT",
                exchange=exchange or "CME",
                expiry=expiry,
                local_symbol=local_symbol,
                trading_class=trading_class or symbol,
            )
        if stype.startswith("FUT_CONT"):
            return self._resolve_front_future(ib, symbol, exchange)
        return build_contract(symbol, sec_type=sec_type, exchange=exchange)

    def _live_enabled(self) -> bool:
        return bool(self.settings.allow_live_trading) and self.settings.profile == "live"

    # --- Broker interface ---------------------------------------------------
    def submit_order(self, order: OrderEvent) -> str:
        sec_type = (order.metadata or {}).get("sec_type") if order.metadata else None
        exchange = (order.metadata or {}).get("exchange") if order.metadata else None
        sec_type = sec_type or "STK"
        last_price = (order.metadata or {}).get("last_price") if order.metadata else None

        # Risk guard check before routing.
        try:
            self.risk_guard.check_order(order, last_price=last_price)
        except Exception as exc:
            raise RuntimeError(f"Order blocked by risk guard: {exc}") from exc

        if not self._live_enabled():
            self._dry_run_counter += 1
            order_id = f"dry-run-{self._dry_run_counter}"
            logger.info(
                "Live trading disabled (profile=%s, allow_live_trading=%s); would submit %s %s qty=%s %s",
                self.settings.profile,
                self.settings.allow_live_trading,
                order.side,
                order.symbol,
                order.quantity,
                order.order_type,
            )
            return order_id

        ib = self._connect()
        metadata = order.metadata or {}
        contract = self._resolve_contract(
            ib,
            order.symbol,
            sec_type=sec_type,
            exchange=exchange or metadata.get("exchange"),
            expiry=metadata.get("expiry"),
            local_symbol=metadata.get("local_symbol"),
            trading_class=metadata.get("trading_class"),
        )
        ib_order = self._build_order(order)
        trade = ib.placeOrder(contract, ib_order)
        return str(trade.order.orderId)

    def _build_order(self, order: OrderEvent):
        side = "BUY" if order.side.upper() == "BUY" else "SELL"
        if order.order_type == "MKT":
            return MarketOrder(side, order.quantity)
        if order.order_type == "LMT":
            if order.limit_price is None:
                raise ValueError("Limit order requires limit_price")
            return LimitOrder(side, order.quantity, order.limit_price)
        if order.order_type in {"STP", "STOP"}:
            if order.stop_price is None:
                raise ValueError("Stop order requires stop_price")
            return StopOrder(side, order.quantity, order.stop_price)
        if order.order_type in {"STPLMT", "STOP_LIMIT"}:
            if order.stop_price is None or order.limit_price is None:
                raise ValueError("Stop-limit order requires stop_price and limit_price")
            return StopLimitOrder(side, order.quantity, order.limit_price, order.stop_price)
        raise ValueError(f"Unsupported order_type: {order.order_type}")

    def fetch_fills(self, since: datetime | None = None) -> Iterable[FillEvent]:
        if not self._live_enabled() or not self._ib.isConnected():
            return []
        fills = []
        for fill in self._ib.fills():  # pragma: no cover - requires live IB
            exec_report, commission = fill
            ts = exec_report.time.replace(tzinfo=None) if hasattr(exec_report.time, "replace") else datetime.utcnow()
            if since and ts < since:
                continue
            fe = FillEvent(
                timestamp=ts,
                symbol=exec_report.contract.symbol,
                side=exec_report.side,
                quantity=exec_report.shares,
                price=exec_report.price,
                commission=getattr(commission, "commission", 0.0),
            )
            fills.append(fe)
            self.risk_guard.record_fill(fe)
        return fills

    def cancel_order(self, order_id: str) -> None:
        if not self._live_enabled() or not self._ib.isConnected():
            logger.info("Cancel requested for %s but live trading disabled or not connected", order_id)
            return
        for trade in list(self._ib.trades()):  # pragma: no cover - requires live IB
            if str(trade.order.orderId) == str(order_id):
                self._ib.cancelOrder(trade.order)
                break

    def sync_positions(self) -> Dict[str, float]:
        if not self._live_enabled() or not self._ib.isConnected():
            return {}
        positions = {}
        for pos in self._ib.positions():  # pragma: no cover - requires live IB
            positions[pos.contract.symbol] = pos.position
        return positions
