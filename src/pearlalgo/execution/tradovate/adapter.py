"""
Tradovate Execution Adapter

Implements the ExecutionAdapter interface for Tradovate paper/live trading.
Used for the Tradovate Paper prop firm evaluation on Tradovate demo accounts.

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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        
        # Partial fill tracking: order_id -> cumulative filled qty
        self._pending_fills: Dict[str, float] = {}
        self._contract_id: Optional[int] = None

        # Connection state
        self._connected = False

        # Track open orders for reconciliation (guarded by _orders_lock)
        self._open_orders: Dict[str, Dict[str, Any]] = {}
        self._orders_lock = asyncio.Lock()

        # Live position cache updated from WebSocket events
        self._live_positions: Dict[str, Dict[str, Any]] = {}
        self._live_positions_updated_at: float = 0.0  # time.monotonic()
        self._POSITION_CACHE_TTL: float = 120.0  # 2 minutes — stale after this

        # Path for immediate fill persistence (set by service)
        self._fills_file: Optional[Path] = None

        # Background reconciliation task
        self._reconciliation_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None

        # Rate limit backoff state
        self._rate_limit_backoff: float = 0.0  # extra delay after 429
        self._rate_limit_until: float = 0.0  # time.monotonic() cooldown deadline

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

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

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

        # ── Broker-position guard ────────────────────────────────────
        # Tradovate rejects OSO bracket orders that conflict with existing
        # positions (e.g. sending a short bracket while already long).
        # Check actual broker positions before placing any order.
        direction = signal.get("direction", "long")
        try:
            # Use cached live positions from WS events, or fall back to REST
            # Discard stale cache when WS is disconnected for too long
            cache_age = time.monotonic() - self._live_positions_updated_at
            if cache_age > self._POSITION_CACHE_TTL:
                if self._live_positions:
                    logger.info(
                        f"Position cache stale ({cache_age:.0f}s old), clearing "
                        f"{len(self._live_positions)} cached positions"
                    )
                    self._live_positions.clear()

            broker_positions = list(self._live_positions.values())
            if not broker_positions and self.is_connected():
                try:
                    broker_positions_raw = await self._client.get_positions()
                    broker_positions = [
                        {"net_pos": p.get("netPos", 0), "contract_id": p.get("contractId")}
                        for p in (broker_positions_raw or [])
                        if isinstance(p, dict)
                    ]
                except Exception:
                    logger.warning("Failed to fetch broker positions, defaulting to empty", exc_info=True)
                    broker_positions = []

            active_broker_positions = [
                p for p in broker_positions if p.get("net_pos", 0) != 0
            ]
            max_net_positions = getattr(self.config, "max_positions", 5)

            # Compute total absolute position size across all contracts
            total_abs_pos = sum(abs(p.get("net_pos", 0)) for p in active_broker_positions)

            for pos in active_broker_positions:
                net_pos = pos.get("net_pos", 0)
                if net_pos == 0:
                    continue
                existing_dir = "long" if net_pos > 0 else "short"

                # Block opposite-direction orders while in a position
                if existing_dir != direction:
                    logger.info(
                        f"Broker position guard: existing {existing_dir} position (net={net_pos}), "
                        f"blocking {direction} order for {signal_id}"
                    )
                    return ExecutionResult(
                        success=False,
                        status=OrderStatus.REJECTED,
                        signal_id=signal_id,
                        error_message=f"opposite_direction_blocked: existing {existing_dir} vs requested {direction}",
                    )

            # Block if total contracts >= max (uses abs(net_pos), not len())
            if total_abs_pos >= max_net_positions:
                logger.info(
                    f"Broker position guard: total position size {total_abs_pos} >= max {max_net_positions}, "
                    f"blocking {signal_id}"
                )
                return ExecutionResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    signal_id=signal_id,
                    error_message=f"max_position_size ({total_abs_pos}/{max_net_positions}) reached",
                )
        except Exception as e:
            logger.warning(f"Broker position guard check failed (non-fatal): {e}")

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

        # HARD CAP: Never exceed max_positions_per_order (default 1 contract)
        # This is the last line of defense — even if all upstream sizing is wrong,
        # the adapter will never send more than this to the broker.
        max_per_order = getattr(self.config, "max_position_size_per_order", 1)
        if position_size > max_per_order:
            logger.warning(
                f"HARD CAP: position_size={position_size} exceeds max_per_order={max_per_order} "
                f"for signal {signal_id}; clamping to {max_per_order}"
            )
            position_size = max_per_order

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

        # ── Structured order logging ─────────────────────────────────
        logger.info(
            f"Tradovate place_oso request: signal={signal_id} "
            f"action={action} symbol={self._contract_symbol} qty={position_size} "
            f"tp={take_profit} sl={stop_loss} entry={entry_price}"
        )

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
                logger.warning(
                    f"Tradovate place_oso REJECTED: signal={signal_id} "
                    f"error={error_text} response={result}"
                )
                return ExecutionResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    signal_id=signal_id,
                    error_message=error_text,
                )

        except TradovateAPIError as e:
            logger.error(
                f"Tradovate place_oso ERROR: signal={signal_id} error={e}",
                exc_info=True,
            )
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

    async def modify_stop_order(self, order_id: int, new_stop_price: float) -> bool:
        """
        Modify a working stop order's price in-place.

        Preserves OCO bracket linkage. Returns True if successful.
        """
        if not self._connected:
            logger.warning("Cannot modify stop order: not connected")
            return False

        try:
            result = await self._client.modify_order(
                order_id=order_id,
                stop_price=new_stop_price,
            )
            logger.info(f"Stop order {order_id} modified to {new_stop_price:.2f}")
            return True
        except Exception as e:
            logger.warning(f"Failed to modify stop order {order_id}: {e}")
            return False

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
        """Get current positions from Tradovate.

        Falls back to WebSocket ``_live_positions`` cache when REST returns
        empty or fails with a 429 rate-limit error.
        """
        if self.config.mode.value == "dry_run" or not self.is_connected():
            return []

        positions: List[Position] = []
        rest_failed_429 = False
        try:
            # Respect rate-limit cooldown
            if time.monotonic() < self._rate_limit_until:
                rest_failed_429 = True
                raise TradovateAPIError("Rate-limit cooldown active")

            tv_positions = await self._client.get_positions()
            for pos in tv_positions:
                net_pos = pos.get("netPos", 0)
                if net_pos == 0:
                    continue
                positions.append(Position(
                    symbol=str(pos.get("contractId", "")),
                    quantity=net_pos,
                    avg_price=float(pos.get("netPrice", 0)),
                ))
        except TradovateAPIError as e:
            if "429" in str(e) or rest_failed_429:
                # Exponential backoff: 30s, 60s, 120s, max 300s
                self._rate_limit_backoff = min((self._rate_limit_backoff or 30) * 2, 300)
                self._rate_limit_until = time.monotonic() + self._rate_limit_backoff
                logger.warning(f"Tradovate 429 rate limit on get_positions, backoff={self._rate_limit_backoff:.0f}s")
            else:
                logger.error(f"Failed to get Tradovate positions: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to get Tradovate positions: {e}", exc_info=True)

        # Fallback: use WebSocket live position cache when REST returned empty
        if not positions and self._live_positions:
            logger.info(f"Using WebSocket _live_positions cache ({len(self._live_positions)} positions) as REST fallback")
            for contract_id, lp in self._live_positions.items():
                net_pos = lp.get("net_pos", 0)
                if net_pos == 0:
                    continue
                positions.append(Position(
                    symbol=str(contract_id),
                    quantity=net_pos,
                    avg_price=float(lp.get("net_price", 0)),
                ))
        elif positions:
            # Successful REST call -- reset backoff
            self._rate_limit_backoff = 0.0

        return positions

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
                    # Safe: dict.pop is atomic in CPython; the _orders_lock is
                    # used for multi-step operations in async contexts.
                    self._open_orders.pop(order_id, None)
                    # Clean up partial fill tracking
                    self._pending_fills.pop(order_id, None)

            elif entity_type == "fill":
                contract_id = str(entity.get("contractId", ""))
                order_id = str(entity.get("orderId", ""))
                fill_qty = float(entity.get("qty", 0))
                logger.debug(
                    f"Tradovate fill: contract={contract_id}, "
                    f"qty={fill_qty}, price={entity.get('price')}"
                )
                
                # Track partial fills
                if order_id:
                    if order_id not in self._pending_fills:
                        self._pending_fills[order_id] = 0.0
                    self._pending_fills[order_id] += abs(fill_qty)
                    
                    # Check if order is complete
                    order_info = self._open_orders.get(order_id)
                    if order_info:
                        order_qty = abs(float(order_info.get("quantity", 0)))
                        filled_qty = self._pending_fills[order_id]
                        if filled_qty >= order_qty:
                            # Order fully filled
                            self._pending_fills.pop(order_id, None)
                        elif filled_qty > order_qty:
                            # Overfill detected
                            logger.warning(
                                f"Tradovate fill overfill detected: order_id={order_id}, "
                                f"order_qty={order_qty}, filled_qty={filled_qty}"
                            )
                        else:
                            # Partial fill
                            logger.info(
                                f"Tradovate partial fill: order_id={order_id}, "
                                f"filled={filled_qty}/{order_qty}"
                            )
                
                # Persist fill immediately to tradovate_fills.json
                try:
                    _ff = self._fills_file
                    if _ff is None:
                        import os
                        state_dir = os.environ.get("PEARL_STATE_DIR")
                        if state_dir:
                            _ff = Path(state_dir) / "tradovate_fills.json"
                    if _ff:
                        fill_record = {
                            "id": entity.get("id"),
                            "order_id": entity.get("orderId"),
                            "contract_id": contract_id,
                            "timestamp": entity.get("timestamp"),
                            "action": entity.get("action"),
                            "qty": fill_qty,
                            "price": entity.get("price", 0.0),
                            "net_pos": entity.get("netPos"),
                        }
                        import json as _json
                        with open(_ff, "a") as f:
                            _json.dump(fill_record, f)
                            f.write("\n")
                except Exception as e:
                    logger.debug(f"Non-critical: could not persist fill: {e}")

            elif entity_type == "position":
                contract_id = str(entity.get("contractId", ""))
                net_pos = entity.get("netPos", 0)
                logger.debug(
                    f"Tradovate position update: contract={contract_id}, "
                    f"netPos={net_pos}"
                )
                # Update live position cache for faster reporting
                if net_pos != 0:
                    self._live_positions[contract_id] = {
                        "contract_id": contract_id,
                        "net_pos": net_pos,
                        "net_price": entity.get("netPrice", 0),
                        "open_pnl": entity.get("openPnL", 0),
                        "timestamp": entity.get("timestamp"),
                    }
                else:
                    self._live_positions.pop(contract_id, None)
                self._live_positions_updated_at = time.monotonic()

    # ── REST order reconciliation ─────────────────────────────────────

    async def _poll_order_status(self) -> None:
        """
        Poll order status via REST and reconcile with ``_open_orders``.

        Called periodically when the WebSocket is disconnected and once
        immediately after a successful reconnection.
        """
        # Skip if in rate-limit cooldown
        if time.monotonic() < self._rate_limit_until:
            logger.debug("Skipping REST order poll: rate-limit cooldown active")
            return

        try:
            rest_orders = await self._client.get_orders()
        except TradovateAPIError as e:
            if "429" in str(e):
                self._rate_limit_backoff = min((self._rate_limit_backoff or 30) * 2, 300)
                self._rate_limit_until = time.monotonic() + self._rate_limit_backoff
                logger.warning(f"Tradovate 429 on order poll, backoff={self._rate_limit_backoff:.0f}s")
            else:
                logger.error(f"REST order poll failed: {e}", exc_info=True)
            return
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
        if not hasattr(self, '_reconnect_task'):
            self._reconnect_task = None
        if not hasattr(self, '_reconnect_gave_up'):
            self._reconnect_gave_up = False

        while self._connected:
            try:
                if not self._client.ws_connected and self._open_orders:
                    logger.debug(
                        "WebSocket disconnected -- polling order status via REST"
                    )
                    await self._poll_order_status()

                # If REST auth also failed, attempt reconnection
                if not self._connected or not self._client.is_authenticated:
                    reconnect_running = (
                        self._reconnect_task is not None
                        and not self._reconnect_task.done()
                    )
                    if not reconnect_running and not self._reconnect_gave_up:
                        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
                else:
                    # Connection restored — reset gave_up flag
                    self._reconnect_gave_up = False

                # RESTORED: 5s reconciliation for fast exit detection
                # Rate limit backoff is handled per-API-call, not here
                # This keeps stop loss detection fast while being gentle on API
                sleep_time = 5
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Reconciliation loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _reconnect_loop(self) -> None:
        """Auto-reconnect with exponential backoff when disconnected.

        Backoff: 30s, 60s, 120s, 240s (max 4 min between attempts).
        Max attempts: 20, then gives up and logs a critical warning.
        """
        max_attempts = 20
        base_delay = 30
        max_delay = 240
        attempt = 0

        while attempt < max_attempts:
            if self._connected and self._client.is_authenticated:
                logger.info("Tradovate reconnection successful")
                return

            attempt += 1
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            logger.warning(
                f"Tradovate disconnected — reconnect attempt {attempt}/{max_attempts} "
                f"in {delay}s"
            )
            await asyncio.sleep(delay)

            try:
                await self.connect()
                if self._connected:
                    logger.info(f"Tradovate reconnected after {attempt} attempt(s)")
                    # Trigger a status reconciliation after reconnect
                    await self._poll_order_status()
                    return
            except Exception as e:
                logger.warning(f"Reconnect attempt {attempt} failed: {e}")

        self._reconnect_gave_up = True
        logger.critical(
            f"Tradovate reconnection FAILED after {max_attempts} attempts — "
            f"manual restart required"
        )

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

    @staticmethod
    def _normalize_order_status(order: Dict[str, Any]) -> str:
        """Return normalized lowercase order status."""
        raw = (
            order.get("ordStatus")
            or order.get("orderStatus")
            or order.get("status")
            or ""
        )
        return str(raw).strip().lower()

    @staticmethod
    def _extract_order_qty(order: Dict[str, Any]) -> int:
        """Extract best-effort remaining/working quantity from mixed payload keys."""
        qty_raw = None
        for key in ("remainingQty", "remainingQuantity", "orderQty", "qty", "quantity"):
            val = order.get(key)
            if val is not None:
                qty_raw = val
                break
        try:
            return int(float(qty_raw or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalize_working_order(order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalize a raw Tradovate order row into canonical working-order shape."""
        if not isinstance(order, dict):
            return None

        status = TradovateExecutionAdapter._normalize_order_status(order)
        # Treat a broad set of non-terminal states as "working".
        working_states = {
            "working", "open", "accepted", "pending", "held",
            "submitted", "partiallyfilled", "partially_filled", "partial",
        }
        terminal_states = {
            "filled", "cancelled", "canceled", "rejected", "expired",
        }
        if status in terminal_states:
            return None
        if status and status not in working_states:
            return None

        qty = TradovateExecutionAdapter._extract_order_qty(order)
        order_type = str(
            order.get("orderType")
            or order.get("ordType")
            or order.get("type")
            or ""
        ).strip()
        price = (
            order.get("price")
            if order.get("price") is not None
            else order.get("limitPrice")
        )
        stop_price = (
            order.get("stopPrice")
            if order.get("stopPrice") is not None
            else order.get("triggerPrice")
        )
        oco_id = order.get("ocoId") or order.get("oco_id")
        parent_id = order.get("parentId") or order.get("parent_id")
        has_oco_link = oco_id is not None or parent_id is not None
        has_price = price is not None or stop_price is not None
        # Tradovate /order/list may return sparse working rows with only
        # id/contract/action/ocoId (no price/type/qty). Keep these rows so
        # protective classification can still reason about broker protection.
        if qty <= 0 and not order_type and not has_price and not has_oco_link:
            return None

        return {
            "id": order.get("id") or order.get("orderId"),
            "contract_id": order.get("contractId") or order.get("contract_id"),
            "action": order.get("action"),
            "order_type": order_type,
            "qty": qty,
            "price": price,
            "stop_price": stop_price,
            "status": status or "working",
            "oco_id": oco_id,
            "parent_id": parent_id,
        }

    @staticmethod
    def _is_protective_order(
        working_order: Dict[str, Any], position_side_by_contract: Dict[str, str],
    ) -> bool:
        """
        True when a working order looks like SL/TP protection for an open position.
        """
        contract_id = working_order.get("contract_id")
        if contract_id is None:
            return False
        side = position_side_by_contract.get(str(contract_id))
        if side is None:
            return False

        required_action = "sell" if side == "long" else "buy"
        action = str(working_order.get("action") or "").strip().lower()
        if action != required_action:
            return False

        order_type = str(working_order.get("order_type") or "").strip().lower()
        # Typical protective legs are stop/limit family.
        type_is_protective = any(tok in order_type for tok in ("stop", "limit", "trailing"))
        has_price = working_order.get("price") is not None or working_order.get("stop_price") is not None
        qty = int(working_order.get("qty") or 0)
        if qty > 0 and has_price and type_is_protective:
            return True

        # Fallback for sparse Tradovate /order/list rows:
        # treat working OCO-linked opposite-side orders as protective.
        has_oco_link = working_order.get("oco_id") is not None or working_order.get("parent_id") is not None
        status = str(working_order.get("status") or "").strip().lower()
        return has_oco_link and status in {
            "working", "open", "accepted", "pending", "held",
            "submitted", "partiallyfilled", "partially_filled", "partial",
        }

    @staticmethod
    def _protective_rejection_reason(
        working_order: Dict[str, Any], position_side_by_contract: Dict[str, str],
    ) -> str:
        """Explain why a normalized working order is not classified as protective."""
        contract_id = working_order.get("contract_id")
        if contract_id is None:
            return "missing_contract_id"
        side = position_side_by_contract.get(str(contract_id))
        if side is None:
            return "no_open_position_for_contract"

        required_action = "sell" if side == "long" else "buy"
        action = str(working_order.get("action") or "").strip().lower()
        if action != required_action:
            return f"action_mismatch:{action or 'unknown'}!=protective_{required_action}"

        qty = int(working_order.get("qty") or 0)
        if qty <= 0:
            has_oco_link = working_order.get("oco_id") is not None or working_order.get("parent_id") is not None
            if has_oco_link:
                return "accepted_sparse_oco_order"
            return "non_positive_qty"

        has_price = working_order.get("price") is not None or working_order.get("stop_price") is not None
        if not has_price:
            return "missing_price_fields"

        order_type = str(working_order.get("order_type") or "").strip().lower()
        if not any(tok in order_type for tok in ("stop", "limit", "trailing")):
            has_oco_link = working_order.get("oco_id") is not None or working_order.get("parent_id") is not None
            if has_oco_link:
                return "accepted_sparse_oco_order"
            return f"non_protective_order_type:{order_type or 'unknown'}"

        return "unknown_non_protective"

    @staticmethod
    def build_working_orders(
        raw_orders: Optional[List[Dict[str, Any]]],
        positions: Optional[List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[Dict[str, Any]]]:
        """
        Canonical working-order derivation with debug trace.

        Returns:
            - working protective orders only
            - aggregate order stats
            - debug classification rows for each raw order
        """
        working: List[Dict[str, Any]] = []
        order_stats = {"working": 0, "filled": 0, "cancelled": 0, "rejected": 0}
        debug_rows: List[Dict[str, Any]] = []

        position_side_by_contract: Dict[str, str] = {}
        position_qty_by_contract: Dict[str, int] = {}
        for pos in positions or []:
            try:
                cid = str(pos.get("contract_id"))
                np = float(pos.get("net_pos", 0) or 0)
                if cid and np != 0:
                    position_side_by_contract[cid] = "long" if np > 0 else "short"
                    position_qty_by_contract[cid] = int(abs(np))
            except (TypeError, ValueError):
                continue

        working_states = {
            "working", "open", "accepted", "pending", "held",
            "submitted", "partiallyfilled", "partially_filled", "partial",
        }
        terminal_filled = {"filled"}
        terminal_cancelled = {"cancelled", "canceled", "expired"}
        terminal_rejected = {"rejected"}

        for order in raw_orders or []:
            status = TradovateExecutionAdapter._normalize_order_status(order)
            if status in working_states:
                order_stats["working"] += 1
            elif status in terminal_filled:
                order_stats["filled"] += 1
            elif status in terminal_cancelled:
                order_stats["cancelled"] += 1
            elif status in terminal_rejected:
                order_stats["rejected"] += 1

            normalized = TradovateExecutionAdapter._normalize_working_order(order)
            accepted = False
            reason = ""
            if status not in working_states:
                reason = f"status_not_working:{status or 'unknown'}"
            elif normalized is None:
                reason = "invalid_or_incomplete_working_order_payload"
            else:
                if int(normalized.get("qty") or 0) <= 0:
                    cq = position_qty_by_contract.get(str(normalized.get("contract_id")))
                    if cq and cq > 0:
                        normalized = {**normalized, "qty": cq}
                accepted = TradovateExecutionAdapter._is_protective_order(
                    normalized, position_side_by_contract
                )
                if accepted:
                    reason = "accepted_protective"
                    working.append(normalized)
                else:
                    reason = TradovateExecutionAdapter._protective_rejection_reason(
                        normalized, position_side_by_contract
                    )

            debug_rows.append(
                {
                    "order_id": order.get("id") or order.get("orderId"),
                    "contract_id": order.get("contractId") or order.get("contract_id"),
                    "status": status or "unknown",
                    "accepted": accepted,
                    "reason": reason,
                    "raw": {
                        "ordStatus": order.get("ordStatus"),
                        "action": order.get("action"),
                        "orderType": order.get("orderType"),
                        "qty": order.get("qty"),
                        "orderQty": order.get("orderQty"),
                        "remainingQty": order.get("remainingQty"),
                        "price": order.get("price"),
                        "stopPrice": order.get("stopPrice"),
                        "ocoId": order.get("ocoId"),
                        "parentId": order.get("parentId"),
                    },
                    "normalized": normalized,
                }
            )

        return working, order_stats, debug_rows

    async def get_account_summary(self) -> Dict[str, Any]:
        """
        Get live Tradovate account summary (balance, positions, P&L).

        Returns a dict suitable for embedding in state.json so the web
        dashboard can display real broker values instead of virtual P&L.
        """
        if not self.is_connected():
            return {}

        result: Dict[str, Any] = {}

        # Parallelize all 4 REST calls (they're independent) for faster cycles
        async def _fetch_cash():
            try:
                return await self._client.get_cash_balance_snapshot()
            except Exception as e:
                logger.warning(f"get_cash_balance_snapshot failed: {e}", exc_info=True)
                return None

        async def _fetch_positions():
            try:
                return await self._client.get_positions()
            except Exception as e:
                logger.warning(f"get_positions failed: {e}", exc_info=True)
                return None

        async def _fetch_fills():
            try:
                return await self._client.get_fills()
            except Exception as e:
                logger.warning(f"get_fills failed: {e}", exc_info=True)
                return None

        async def _fetch_orders():
            try:
                return await self._client.get_orders()
            except Exception as e:
                logger.warning(f"get_orders failed: {e}", exc_info=True)
                return None

        snap, tv_positions, raw_fills, raw_orders = await asyncio.gather(
            _fetch_cash(), _fetch_positions(), _fetch_fills(), _fetch_orders()
        )

        # Process cash balance
        if snap:
            result["equity"] = snap.get("netLiq", 0.0)
            result["cash_balance"] = snap.get("totalCashValue", 0.0)
            result["open_pnl"] = snap.get("openPnL", 0.0)
            result["realized_pnl"] = snap.get("realizedPnL", 0.0)
            result["week_realized_pnl"] = snap.get("weekRealizedPnL", 0.0)
            result["initial_margin"] = snap.get("initialMargin", 0.0)
            result["maintenance_margin"] = snap.get("maintenanceMargin", 0.0)

        # Process positions (with _live_positions fallback for rate limiting)
        positions = []
        if tv_positions is not None:
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

        # Fallback: when REST returned empty but WS cache has positions
        if not positions and self._live_positions:
            logger.info(f"get_account_summary: using _live_positions cache ({len(self._live_positions)} pos) as REST fallback")
            for contract_id, lp in self._live_positions.items():
                net_pos = lp.get("net_pos", 0)
                if net_pos == 0:
                    continue
                positions.append({
                    "contract_id": contract_id,
                    "net_pos": net_pos,
                    "net_price": lp.get("net_price", 0.0),
                    "open_pnl": lp.get("open_pnl", 0.0),
                })

        result["positions"] = positions
        result["position_count"] = len(positions)

        # Process fills
        if raw_fills is not None:
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
        else:
            result["fills"] = []

        # Process orders (canonical normalization + protective-order extraction)
        if raw_orders is not None:
            working, order_stats, working_debug = self.build_working_orders(raw_orders, positions)
            result["working_orders"] = working
            result["order_stats"] = order_stats
            result["working_orders_raw_count"] = len(raw_orders)
            # Keep debug bounded for state payload size while preserving diagnostics.
            result["working_orders_debug"] = working_debug[:300]
        else:
            result["working_orders"] = []
            result["order_stats"] = {}
            result["working_orders_raw_count"] = 0
            result["working_orders_debug"] = []

        result["account"] = self._client.account_name
        result["env"] = self._tv_config.env
        return result
