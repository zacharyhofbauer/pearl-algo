"""
Tradovate Execution Adapter

Implements the ExecutionAdapter interface for Tradovate paper/live trading.
Used for the MFFU prop firm evaluation on Tradovate demo accounts.

Key design decisions:
- Uses placeOSO for bracket orders (entry spawns OCO stop+target)
- All orders set isAutomated=true (exchange requirement)
- Real-time sync via WebSocket user/syncrequest
- Resolves front-month contract symbol automatically
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pearlalgo.execution.base import (
    ExecutionAdapter,
    ExecutionConfig,
    ExecutionDecision,
    ExecutionResult,
    OrderStatus,
    Position,
)
from pearlalgo.execution.tradovate.client import (
    TradovateClient,
    TradovateAPIError,
    TradovateAuthError,
)
from pearlalgo.execution.tradovate.config import TradovateConfig

logger = logging.getLogger(__name__)


class TradovateExecutionAdapter(ExecutionAdapter):
    """
    Tradovate implementation of the ExecutionAdapter interface.

    Features:
    - Bracket orders via placeOSO (entry + stop + take profit)
    - Kill switch: cancel all orders + flatten positions
    - Position tracking via REST polling + WebSocket sync
    - Automatic front-month contract resolution
    """

    def __init__(self, config: ExecutionConfig, tradovate_config: Optional[TradovateConfig] = None):
        """
        Initialize Tradovate execution adapter.

        Args:
            config: Standard execution configuration (mode, limits, etc.)
            tradovate_config: Tradovate-specific config (credentials, env).
                            If None, loads from environment variables.
        """
        super().__init__(config)

        self._tv_config = tradovate_config or TradovateConfig.from_env()
        self._client = TradovateClient(self._tv_config)

        # Cached contract symbol (resolved on connect)
        self._contract_symbol: Optional[str] = None
        self._contract_id: Optional[int] = None

        # Connection state
        self._connected = False

        # Track open orders for reconciliation
        self._open_orders: Dict[str, Dict[str, Any]] = {}

        # Background reconciliation task
        self._reconciliation_task: Optional[asyncio.Task] = None

        logger.info(
            f"TradovateExecutionAdapter initialized: "
            f"env={self._tv_config.env}, mode={config.mode.value}"
        )

    # ── Connection lifecycle ──────────────────────────────────────────

    async def connect(self) -> bool:
        """Establish connection to Tradovate API."""
        if self._connected:
            return True

        try:
            success = await self._client.connect()
            if not success:
                return False

            # Resolve front-month contract for the trading symbol
            symbol = self.config.symbol_whitelist[0] if self.config.symbol_whitelist else "MNQ"
            try:
                self._contract_symbol = await self._client.resolve_front_month(symbol)
                logger.info(f"Tradovate contract resolved: {symbol} -> {self._contract_symbol}")

                # Also get the contract ID for position matching
                contract_info = await self._client.find_contract(self._contract_symbol)
                self._contract_id = contract_info.get("id")
            except Exception as e:
                logger.warning(f"Contract resolution failed (will retry on first order): {e}")

            # Start WebSocket for real-time updates
            try:
                await self._client.start_websocket()
                self._client.add_event_handler(self._handle_ws_event)
            except Exception as e:
                logger.warning(f"WebSocket start failed (REST-only mode): {e}")

            self._connected = True

            # Start background reconciliation (polls orders when WS is down)
            self._reconciliation_task = asyncio.create_task(
                self._reconciliation_loop()
            )
            logger.info(
                f"Tradovate connected: account={self._client.account_name}, "
                f"contract={self._contract_symbol}"
            )
            return True

        except TradovateAuthError as e:
            logger.error(f"Tradovate auth failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Tradovate connect failed: {e}", exc_info=True)
            return False

    async def disconnect(self) -> None:
        """Disconnect from Tradovate."""
        self._connected = False

        if self._reconciliation_task and not self._reconciliation_task.done():
            self._reconciliation_task.cancel()
            try:
                await self._reconciliation_task
            except asyncio.CancelledError:
                pass

        await self._client.disconnect()
        logger.info("Tradovate disconnected")

    def is_connected(self) -> bool:
        """Check if connected to Tradovate."""
        return self._connected and self._client.is_authenticated

    # ── Order placement ───────────────────────────────────────────────

    async def place_bracket(self, signal: Dict) -> ExecutionResult:
        """
        Place a bracket order via Tradovate's placeOSO endpoint.

        The entry order automatically spawns an OCO pair (stop loss + take profit).
        """
        signal_id = signal.get("signal_id", str(uuid.uuid4()))

        # Check preconditions (armed, limits, cooldowns, etc.)
        decision = self.check_preconditions(signal)
        if not decision.execute:
            logger.info(f"Tradovate execution skipped: {decision.reason}")
            return ExecutionResult(
                success=False,
                status=OrderStatus.REJECTED,
                signal_id=signal_id,
                error_message=decision.reason,
            )

        # Dry-run mode
        if self.config.mode.value == "dry_run":
            logger.info(f"DRY_RUN: Would place Tradovate bracket for {signal_id}")
            self.increment_order_count(signal.get("type", "unknown"))
            return ExecutionResult(
                success=True,
                status=OrderStatus.PLACED,
                signal_id=signal_id,
                order_id=f"tv_dry_{signal_id}",
            )

        # Connection check
        if not self.is_connected():
            return ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id=signal_id,
                error_message="Not connected to Tradovate",
            )

        # Resolve contract symbol if not yet done
        if not self._contract_symbol:
            try:
                symbol = signal.get("symbol", "MNQ")
                self._contract_symbol = await self._client.resolve_front_month(symbol)
                # Guard: contract resolution must return a non-empty symbol
                if not self._contract_symbol:
                    logger.warning(
                        f"Contract resolution returned empty result for symbol={symbol}; "
                        f"cannot place order for signal {signal_id}"
                    )
                    return ExecutionResult(
                        success=False,
                        status=OrderStatus.ERROR,
                        signal_id=signal_id,
                        error_message=f"Contract resolution returned empty for {symbol}",
                    )
            except Exception as e:
                return ExecutionResult(
                    success=False,
                    status=OrderStatus.ERROR,
                    signal_id=signal_id,
                    error_message=f"Contract resolution failed: {e}",
                )

        # Extract signal parameters
        direction = signal.get("direction", "long")
        entry_price = float(signal.get("entry_price", 0))
        stop_loss = float(signal.get("stop_loss", 0))
        take_profit = float(signal.get("take_profit", 0))
        position_size = int(signal.get("position_size", 1))

        # Guard: position size must be positive
        if position_size <= 0:
            logger.warning(
                f"Invalid position_size={position_size} for signal {signal_id}; "
                f"skipping order placement"
            )
            return ExecutionResult(
                success=False,
                status=OrderStatus.REJECTED,
                signal_id=signal_id,
                error_message=f"Invalid position_size: {position_size}",
            )

        # Guard: stop loss must be on the correct side of entry price
        if stop_loss > 0 and entry_price > 0:
            if direction == "long" and stop_loss >= entry_price:
                logger.warning(
                    f"Invalid stop_loss for LONG: stop_loss={stop_loss} >= "
                    f"entry_price={entry_price} for signal {signal_id}; skipping order"
                )
                return ExecutionResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    signal_id=signal_id,
                    error_message=f"Stop loss {stop_loss} invalid for LONG entry {entry_price}",
                )
            elif direction == "short" and stop_loss <= entry_price:
                logger.warning(
                    f"Invalid stop_loss for SHORT: stop_loss={stop_loss} <= "
                    f"entry_price={entry_price} for signal {signal_id}; skipping order"
                )
                return ExecutionResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    signal_id=signal_id,
                    error_message=f"Stop loss {stop_loss} invalid for SHORT entry {entry_price}",
                )

        # Map direction to Tradovate action
        action = "Buy" if direction == "long" else "Sell"

        try:
            result = await self._client.place_oso(
                symbol=self._contract_symbol,
                action=action,
                order_qty=position_size,
                order_type="Market",
                tp_price=take_profit if take_profit > 0 else None,
                sl_price=stop_loss if stop_loss > 0 else None,
            )

            # Guard: verify response is a dict with expected structure
            if not isinstance(result, dict):
                logger.warning(
                    f"Unexpected response type from place_oso: {type(result).__name__} "
                    f"for signal {signal_id}; expected dict"
                )
                return ExecutionResult(
                    success=False,
                    status=OrderStatus.ERROR,
                    signal_id=signal_id,
                    error_message=f"Unexpected place_oso response type: {type(result).__name__}",
                )

            order_id = result.get("orderId") or result.get("id")
            if order_id:
                self.increment_order_count(signal.get("type", "unknown"))

                # Track the order
                self._open_orders[str(order_id)] = {
                    "signal_id": signal_id,
                    "direction": direction,
                    "symbol": self._contract_symbol,
                    "qty": position_size,
                    "placed_at": datetime.now(timezone.utc).isoformat(),
                }

                logger.info(
                    f"Tradovate bracket placed: order_id={order_id}, "
                    f"signal={signal_id}, {action} {position_size}x {self._contract_symbol}"
                )

                return ExecutionResult(
                    success=True,
                    status=OrderStatus.PLACED,
                    signal_id=signal_id,
                    order_id=str(order_id),
                )
            else:
                error_text = result.get("errorText", "No order ID returned")
                return ExecutionResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    signal_id=signal_id,
                    error_message=error_text,
                )

        except TradovateAPIError as e:
            logger.error(f"Tradovate order failed: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id=signal_id,
                error_message=str(e),
            )
        except Exception as e:
            logger.error(f"Tradovate order error: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id=signal_id,
                error_message=str(e),
            )

    # ── Cancel / Flatten ──────────────────────────────────────────────

    async def cancel_order(self, order_id: str) -> ExecutionResult:
        """Cancel a specific order on Tradovate."""
        if self.config.mode.value == "dry_run":
            return ExecutionResult(success=True, status=OrderStatus.CANCELLED, signal_id="cancel", order_id=order_id)

        try:
            await self._client.cancel_order(int(order_id))
            self._open_orders.pop(order_id, None)
            return ExecutionResult(
                success=True,
                status=OrderStatus.CANCELLED,
                signal_id="cancel",
                order_id=order_id,
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id="cancel",
                order_id=order_id,
                error_message=str(e),
            )

    async def cancel_all(self) -> List[ExecutionResult]:
        """Cancel all open orders (kill switch)."""
        logger.warning("TRADOVATE KILL SWITCH: Cancelling all orders")
        self.disarm()

        if self.config.mode.value == "dry_run":
            return [ExecutionResult(success=True, status=OrderStatus.CANCELLED, signal_id="kill_cancel")]

        results = []
        for order_id in list(self._open_orders.keys()):
            result = await self.cancel_order(order_id)
            results.append(result)

        return results if results else [
            ExecutionResult(success=True, status=OrderStatus.CANCELLED, signal_id="kill_cancel_noop")
        ]

    async def flatten_all_positions(self) -> List[ExecutionResult]:
        """Flatten all open positions (kill switch)."""
        logger.warning("TRADOVATE KILL SWITCH: Flattening all positions")
        self.disarm()

        if self.config.mode.value == "dry_run":
            return [ExecutionResult(success=True, status=OrderStatus.PLACED, signal_id="kill_flatten")]

        if not self.is_connected():
            return [ExecutionResult(
                success=False, status=OrderStatus.ERROR,
                signal_id="kill_flatten", error_message="Not connected",
            )]

        try:
            result = await self._client.liquidate_all_positions()
            count = result.get("positions_liquidated", 0)
            logger.warning(f"Tradovate flatten: {count} positions liquidated")
            return [ExecutionResult(
                success=True,
                status=OrderStatus.PLACED,
                signal_id="kill_flatten",
            )]
        except Exception as e:
            logger.error(f"Tradovate flatten failed: {e}", exc_info=True)
            return [ExecutionResult(
                success=False, status=OrderStatus.ERROR,
                signal_id="kill_flatten", error_message=str(e),
            )]

    # ── Position queries ──────────────────────────────────────────────

    async def get_positions(self) -> List[Position]:
        """Get current positions from Tradovate."""
        if self.config.mode.value == "dry_run" or not self.is_connected():
            return []

        try:
            tv_positions = await self._client.get_positions()
            positions = []
            for pos in tv_positions:
                net_pos = pos.get("netPos", 0)
                if net_pos == 0:
                    continue
                positions.append(Position(
                    symbol=str(pos.get("contractId", "")),
                    quantity=net_pos,
                    avg_price=float(pos.get("netPrice", 0)),
                ))
            return positions
        except Exception as e:
            logger.error(f"Failed to get Tradovate positions: {e}", exc_info=True)
            return []

    # ── WebSocket event handler ───────────────────────────────────────

    def _handle_ws_event(self, event: Dict[str, Any]) -> None:
        """Handle real-time events from Tradovate WebSocket."""
        event_type = event.get("e")
        data = event.get("d", {})

        # Reconcile orders on WebSocket reconnection
        if event_type == "ws_reconnected":
            logger.info(
                "WebSocket reconnected -- reconciling order status via REST"
            )
            try:
                asyncio.create_task(self._poll_order_status())
            except Exception as e:
                logger.error(f"Failed to schedule post-reconnect poll: {e}")
            return

        if event_type == "props" and isinstance(data, dict):
            entity_type = data.get("entityType", "")
            event_action = data.get("eventType", "")
            entity = data.get("entity", {})

            if entity_type == "order":
                ord_status = entity.get("ordStatus", "")
                order_id = str(entity.get("id", ""))
                logger.debug(f"Tradovate order event: {order_id} -> {ord_status} ({event_action})")

                if ord_status in ("Filled", "Cancelled", "Rejected", "Expired"):
                    self._open_orders.pop(order_id, None)

            elif entity_type == "fill":
                logger.debug(
                    f"Tradovate fill: contract={entity.get('contractId')}, "
                    f"qty={entity.get('qty')}, price={entity.get('price')}"
                )

            elif entity_type == "position":
                logger.debug(
                    f"Tradovate position update: contract={entity.get('contractId')}, "
                    f"netPos={entity.get('netPos')}"
                )

    # ── REST order reconciliation ─────────────────────────────────────

    async def _poll_order_status(self) -> None:
        """
        Poll order status via REST and reconcile with ``_open_orders``.

        Called periodically when the WebSocket is disconnected and once
        immediately after a successful reconnection.
        """
        try:
            rest_orders = await self._client.get_orders()
        except Exception as e:
            logger.error(f"REST order poll failed: {e}", exc_info=True)
            return

        if not isinstance(rest_orders, list):
            logger.warning(
                f"Unexpected /order/list response type: {type(rest_orders).__name__}"
            )
            return

        # Build a lookup of REST order states keyed by order ID
        rest_order_map: Dict[str, Dict[str, Any]] = {}
        for order in rest_orders:
            oid = str(order.get("id", ""))
            if oid:
                rest_order_map[oid] = order

        # Reconcile tracked orders against the REST snapshot
        for order_id in list(self._open_orders.keys()):
            rest_order = rest_order_map.get(order_id)
            if rest_order is None:
                # Order not in REST list at all -- may have been purged
                logger.warning(
                    f"Order {order_id} tracked locally but absent from REST "
                    f"/order/list; removing from open orders"
                )
                self._open_orders.pop(order_id, None)
                continue

            ord_status = rest_order.get("ordStatus", "")
            if ord_status in ("Filled", "Cancelled", "Rejected", "Expired"):
                logger.warning(
                    f"Order reconciliation: order {order_id} status changed "
                    f"to {ord_status} (detected via REST poll)"
                )
                self._open_orders.pop(order_id, None)

    async def _reconciliation_loop(self) -> None:
        """
        Background task that polls order status via REST when the WebSocket
        feed is disconnected, ensuring no order updates are missed.
        """
        while self._connected:
            try:
                if not self._client.ws_connected and self._open_orders:
                    logger.debug(
                        "WebSocket disconnected -- polling order status via REST"
                    )
                    await self._poll_order_status()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Reconciliation loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get adapter status for telemetry."""
        base = {
            "adapter": "tradovate",
            "connected": self._connected,
            "authenticated": self._client.is_authenticated,
            "ws_connected": self._client.ws_connected,
            "account": self._client.account_name,
            "account_id": self._client.account_id,
            "contract": self._contract_symbol,
            "env": self._tv_config.env,
            "armed": self._armed,
            "mode": self.config.mode.value,
            "orders_today": self._orders_today,
            "daily_pnl": self._daily_pnl,
            "open_orders": len(self._open_orders),
        }
        return base

    async def get_account_summary(self) -> Dict[str, Any]:
        """
        Get live Tradovate account summary (balance, positions, P&L).

        Returns a dict suitable for embedding in state.json so the web
        dashboard can display real broker values instead of virtual P&L.
        """
        if not self.is_connected():
            return {}

        result: Dict[str, Any] = {}
        try:
            snap = await self._client.get_cash_balance_snapshot()
            result["equity"] = snap.get("netLiq", 0.0)
            result["cash_balance"] = snap.get("totalCashValue", 0.0)
            result["open_pnl"] = snap.get("openPnL", 0.0)
            result["realized_pnl"] = snap.get("realizedPnL", 0.0)
            result["week_realized_pnl"] = snap.get("weekRealizedPnL", 0.0)
            result["initial_margin"] = snap.get("initialMargin", 0.0)
            result["maintenance_margin"] = snap.get("maintenanceMargin", 0.0)
        except Exception as e:
            logger.warning(f"Critical path error: {e}", exc_info=True)

        try:
            tv_positions = await self._client.get_positions()
            positions = []
            for pos in tv_positions:
                net_pos = pos.get("netPos", 0)
                if net_pos == 0:
                    continue
                positions.append({
                    "contract_id": pos.get("contractId"),
                    "net_pos": net_pos,
                    "net_price": pos.get("netPrice", 0.0),
                    "open_pnl": pos.get("openPnL", 0.0),
                })
            result["positions"] = positions
            result["position_count"] = len(positions)
        except Exception as e:
            logger.warning(f"Critical path error: {e}", exc_info=True)
            result["positions"] = []
            result["position_count"] = 0

        try:
            raw_fills = await self._client.get_fills()
            fills = []
            for f in raw_fills:
                fills.append({
                    "id": f.get("id"),
                    "order_id": f.get("orderId"),
                    "contract_id": f.get("contractId"),
                    "timestamp": f.get("timestamp"),
                    "action": f.get("action"),        # "Buy" or "Sell"
                    "qty": f.get("qty", 0),
                    "price": f.get("price", 0.0),
                    "net_pos": f.get("netPos", 0),    # position after this fill
                })
            result["fills"] = fills
        except Exception as e:
            logger.warning(f"Critical path error: {e}", exc_info=True)
            result["fills"] = []

        result["account"] = self._client.account_name
        result["env"] = self._tv_config.env
        return result
