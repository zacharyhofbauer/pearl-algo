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
            logger.error(f"Tradovate order failed: {e}")
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
            logger.error(f"Tradovate flatten failed: {e}")
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
            logger.error(f"Failed to get Tradovate positions: {e}")
            return []

    # ── WebSocket event handler ───────────────────────────────────────

    def _handle_ws_event(self, event: Dict[str, Any]) -> None:
        """Handle real-time events from Tradovate WebSocket."""
        event_type = event.get("e")
        data = event.get("d", {})

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

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get adapter status for telemetry."""
        base = {
            "adapter": "tradovate",
            "connected": self._connected,
            "authenticated": self._client.is_authenticated,
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
