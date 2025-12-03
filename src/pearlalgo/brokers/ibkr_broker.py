from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Iterable

from ib_insync import (
    IB,
    Future,
    LimitOrder,
    MarketOrder,
    Stock,
    StopLimitOrder,
    StopOrder,
)

from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.brokers.contracts import build_contract, resolve_future_contract
from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.risk.limits import RiskGuard, RiskLimits

logger = logging.getLogger(__name__)


def _contract(symbol: str, sec_type: str = "STK", exchange: str | None = None):
    exch = exchange or ("CME" if sec_type.upper() == "FUT" else "SMART")
    if sec_type.upper() == "FUT":
        return Future(symbol=symbol, exchange=exch, currency="USD")
    return Stock(symbol=symbol, exchange=exch, currency="USD")


class IBKRBroker(Broker):
    """
    Minimal IBKR broker adapter using ib_insync.
    
    **DEPRECATED**: IBKR is now optional and deprecated.
    Use PaperBroker for internal simulation instead.
    See IBKR_DEPRECATION_NOTICE.md for migration guide.

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
        try:
            self._ib.connect(
                self.settings.ib_host,
                int(self.settings.ib_port),
                clientId=int(self.settings.ib_client_id),
                timeout=3,  # Short timeout to fail fast
            )
        except (ConnectionRefusedError, OSError) as exc:
            # Suppress noisy connection errors - expected when Gateway isn't running
            logger.debug(
                f"IBKR connection refused at {self.settings.ib_host}:{self.settings.ib_port} "
                f"(clientId={self.settings.ib_client_id}). Gateway may not be running."
            )
            raise RuntimeError(
                f"IBKR Gateway not available at {self.settings.ib_host}:{self.settings.ib_port}. "
                f"Please start IB Gateway or use paper trading with dummy data."
            ) from exc
        except Exception as exc:
            error_msg = str(exc).lower()
            # Handle client ID conflicts and event loop issues gracefully
            if "client id" in error_msg or "already in use" in error_msg:
                logger.debug(
                    f"IBKR client ID {self.settings.ib_client_id} already in use. "
                    f"This is expected if another connection exists."
                )
            elif "event loop" in error_msg:
                logger.debug(f"IBKR event loop conflict: {exc}")
            else:
                logger.warning(f"IBKR connection error: {exc}")
            raise
        return self._ib

    def _resolve_front_future(
        self, ib: IB, symbol: str, exchange: str | None = None
    ) -> Future:
        exch = exchange or "CME"
        contract = resolve_future_contract(ib, symbol, exchange=exch)
        if contract:
            return contract
        logger.warning(
            "No valid front-month contract found for %s on %s; using fallback future",
            symbol,
            exch,
        )
        return Future(symbol=symbol, exchange=exch, currency="USD")

    def _resolve_specific_future(
        self,
        ib: IB,
        symbol: str,
        *,
        exchange: str | None = None,
        expiry: str | None = None,
        local_symbol: str | None = None,
        trading_class: str | None = None,
    ) -> Future | None:
        contract = resolve_future_contract(
            ib,
            symbol,
            exchange=exchange,
            target_expiry=expiry,
            local_symbol=local_symbol,
            trading_class=trading_class,
        )
        if not contract:
            logger.warning(
                "No matching contract for %s expiry=%s local=%s tc=%s on %s",
                symbol,
                expiry,
                local_symbol,
                trading_class,
                exchange or "GLOBEX/CME",
            )
        return contract

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
            # Try resolving from contract details to avoid sec-def errors.
            contract = self._resolve_specific_future(
                ib,
                symbol,
                exchange=exchange,
                expiry=expiry,
                local_symbol=local_symbol,
                trading_class=trading_class or symbol,
            )
            if contract:
                return contract
            logger.warning(
                "Falling back to front future for %s after explicit lookup failed",
                symbol,
            )
            return self._resolve_front_future(ib, symbol, exchange)
        if stype.startswith("FUT"):
            return self._resolve_front_future(ib, symbol, exchange)
        return build_contract(symbol, sec_type=sec_type, exchange=exchange)

    def _live_enabled(self) -> bool:
        return (
            bool(self.settings.allow_live_trading) and self.settings.profile == "live"
        )

    # --- Broker interface ---------------------------------------------------
    def submit_order(self, order: OrderEvent) -> str:
        sec_type = (order.metadata or {}).get("sec_type") if order.metadata else None
        exchange = (order.metadata or {}).get("exchange") if order.metadata else None
        sec_type = sec_type or "STK"
        last_price = (
            (order.metadata or {}).get("last_price") if order.metadata else None
        )

        # Risk guard check before routing.
        try:
            self.risk_guard.check_order(order, last_price=last_price)
        except Exception as exc:
            raise RuntimeError(f"Order blocked by risk guard: {exc}") from exc

        if not self._live_enabled():
            self._dry_run_counter += 1
            order_id = f"dry-run-{self._dry_run_counter}"
            logger.warning(
                "⚠️  LIVE TRADING DISABLED - Order not submitted (profile=%s, allow_live_trading=%s); would submit %s %s qty=%s %s",
                self.settings.profile,
                self.settings.allow_live_trading,
                order.side,
                order.symbol,
                order.quantity,
                order.order_type,
            )
            # Also print to console for visibility
            print(
                f"⚠️  DRY RUN MODE: Would submit {order.side} {order.quantity} {order.symbol} @ {order.order_type}"
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

        logger.info(
            f"🚀 SUBMITTING LIVE ORDER: {order.side} {order.quantity} {order.symbol} @ {order.order_type}"
        )
        try:
            trade = ib.placeOrder(contract, ib_order)
            order_id = str(trade.order.orderId)
            logger.info(
                f"✅ Order placed successfully: OrderID={order_id}, Contract={contract.symbol}"
            )
            return order_id
        except Exception as e:
            logger.error(f"❌ Order placement failed: {e}", exc_info=True)
            raise

    def _build_order(self, order: OrderEvent):
        from ib_insync import Order

        side = "BUY" if order.side.upper() == "BUY" else "SELL"
        ib_order: Order

        if order.order_type == "MKT":
            ib_order = MarketOrder(side, order.quantity)
        elif order.order_type == "LMT":
            if order.limit_price is None:
                raise ValueError("Limit order requires limit_price")
            ib_order = LimitOrder(side, order.quantity, order.limit_price)
        elif order.order_type in {"STP", "STOP"}:
            if order.stop_price is None:
                raise ValueError("Stop order requires stop_price")
            ib_order = StopOrder(side, order.quantity, order.stop_price)
        elif order.order_type in {"STPLMT", "STOP_LIMIT"}:
            if order.stop_price is None or order.limit_price is None:
                raise ValueError("Stop-limit order requires stop_price and limit_price")
            ib_order = StopLimitOrder(
                side, order.quantity, order.limit_price, order.stop_price
            )
        else:
            raise ValueError(f"Unsupported order_type: {order.order_type}")

        # Set TimeInForce explicitly to avoid error 10349
        # For futures, use DAY (good for the day) or GTC (good till cancelled)
        # DAY is safer for testing
        ib_order.tif = "DAY"  # Time In Force: DAY

        return ib_order

    def fetch_fills(self, since: datetime | None = None) -> Iterable[FillEvent]:
        if not self._live_enabled() or not self._ib.isConnected():
            return []
        fills = []
        for fill in self._ib.fills():  # pragma: no cover - requires live IB
            exec_report, commission = fill
            ts = (
                exec_report.time.replace(tzinfo=None)
                if hasattr(exec_report.time, "replace")
                else datetime.utcnow()
            )
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
            logger.info(
                "Cancel requested for %s but live trading disabled or not connected",
                order_id,
            )
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
