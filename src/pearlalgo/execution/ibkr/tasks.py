"""
IBKR Executor Tasks for Order Placement

Defines tasks for the IBKRExecutor thread to handle order-related operations.
These tasks are submitted to the executor queue and executed synchronously
in the dedicated IBKR thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ib_insync import IB, Future, LimitOrder, StopOrder

from pearlalgo.utils.logger import logger


@dataclass
class PlaceBracketOrderTask:
    """
    Task to place a bracket order (entry + stop loss + take profit).
    
    Uses IBKR's native bracket order support with OCA (One-Cancels-All) groups.
    """
    task_id: str
    symbol: str
    direction: str  # "long" or "short"
    quantity: int
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    signal_id: str
    
    def execute(self, ib: IB) -> Dict[str, Any]:
        """
        Execute the bracket order placement.
        
        Returns:
            Dictionary with order IDs and status
        """
        logger.info(
            f"PlaceBracketOrderTask: {self.direction} {self.quantity} {self.symbol} "
            f"@ {self.entry_price:.2f}, SL={self.stop_loss_price:.2f}, TP={self.take_profit_price:.2f}"
        )
        
        try:
            # Create futures contract
            contract = Future(self.symbol, exchange="CME", currency="USD")
            
            # Qualify the contract to get full details
            contracts = ib.reqContractDetails(contract)
            if not contracts:
                return {
                    "success": False,
                    "error": f"No contract found for {self.symbol}",
                    "signal_id": self.signal_id,
                }
            
            # Use front month contract
            sorted_contracts = sorted(
                contracts, 
                key=lambda cd: cd.contract.lastTradeDateOrContractMonth if cd.contract else ""
            )
            qualified_contract = sorted_contracts[0].contract
            
            if qualified_contract is None:
                return {
                    "success": False,
                    "error": f"Contract details missing for {self.symbol}",
                    "signal_id": self.signal_id,
                }
            
            logger.info(
                f"Using contract: {qualified_contract.localSymbol} "
                f"(exp: {qualified_contract.lastTradeDateOrContractMonth})"
            )
            
            # Determine order actions based on direction
            if self.direction == "long":
                entry_action = "BUY"
                exit_action = "SELL"
            else:
                entry_action = "SELL"
                exit_action = "BUY"
            
            # Create OCA group name for bracket
            oca_group = f"bracket_{self.signal_id}_{datetime.now(timezone.utc).timestamp()}"
            
            # Create parent order (limit order at entry price)
            parent_order = LimitOrder(
                action=entry_action,
                totalQuantity=self.quantity,
                lmtPrice=self.entry_price,
                transmit=False,  # Don't transmit until all orders are ready
            )
            parent_order.orderId = ib.client.getReqId()
            
            # Create stop loss order
            stop_order = StopOrder(
                action=exit_action,
                totalQuantity=self.quantity,
                stopPrice=self.stop_loss_price,
                transmit=False,
                parentId=parent_order.orderId,
            )
            stop_order.orderId = ib.client.getReqId()
            stop_order.ocaGroup = oca_group
            stop_order.ocaType = 1  # Cancel other orders in OCA group when filled
            
            # Create take profit order (limit order)
            take_profit_order = LimitOrder(
                action=exit_action,
                totalQuantity=self.quantity,
                lmtPrice=self.take_profit_price,
                transmit=True,  # Transmit all orders when this one is submitted
                parentId=parent_order.orderId,
            )
            take_profit_order.orderId = ib.client.getReqId()
            take_profit_order.ocaGroup = oca_group
            take_profit_order.ocaType = 1
            
            # Place orders
            ib.placeOrder(qualified_contract, parent_order)
            ib.placeOrder(qualified_contract, stop_order)
            ib.placeOrder(qualified_contract, take_profit_order)
            
            # Wait briefly for order acknowledgment
            ib.sleep(1)
            
            logger.info(
                f"Bracket order placed: parent={parent_order.orderId}, "
                f"stop={stop_order.orderId}, tp={take_profit_order.orderId}"
            )
            
            return {
                "success": True,
                "signal_id": self.signal_id,
                "parent_order_id": str(parent_order.orderId),
                "stop_order_id": str(stop_order.orderId),
                "take_profit_order_id": str(take_profit_order.orderId),
                "oca_group": oca_group,
                "contract": qualified_contract.localSymbol if qualified_contract else self.symbol,
                "status": "placed",
            }
            
        except Exception as e:
            logger.error(f"Error placing bracket order: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "signal_id": self.signal_id,
            }


@dataclass
class CancelOrderTask:
    """Task to cancel a specific order."""
    task_id: str
    order_id: int
    
    def execute(self, ib: IB) -> Dict[str, Any]:
        """Cancel the specified order."""
        logger.info(f"CancelOrderTask: cancelling order {self.order_id}")
        
        try:
            # Find the order in open orders
            target_order = None
            
            for trade in ib.openTrades():
                if trade.order.orderId == self.order_id:
                    target_order = trade.order
                    break
            
            if target_order is None:
                return {
                    "success": False,
                    "error": f"Order {self.order_id} not found in open orders",
                    "order_id": self.order_id,
                }
            
            # Cancel the order
            ib.cancelOrder(target_order)
            ib.sleep(1)
            
            logger.info(f"Order {self.order_id} cancelled")
            return {
                "success": True,
                "order_id": self.order_id,
                "status": "cancelled",
            }
            
        except Exception as e:
            logger.error(f"Error cancelling order {self.order_id}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "order_id": self.order_id,
            }


@dataclass
class CancelAllOrdersTask:
    """Task to cancel all open orders (kill switch)."""
    task_id: str
    
    def execute(self, ib: IB) -> Dict[str, Any]:
        """Cancel all open orders."""
        logger.warning("CancelAllOrdersTask: KILL SWITCH - cancelling all orders")
        
        try:
            # Get all open trades
            open_trades = ib.openTrades()
            cancelled = []
            errors = []
            
            for trade in open_trades:
                try:
                    ib.cancelOrder(trade.order)
                    cancelled.append(trade.order.orderId)
                except Exception as e:
                    errors.append({
                        "order_id": trade.order.orderId,
                        "error": str(e),
                    })
            
            ib.sleep(1)
            
            logger.warning(
                f"Kill switch complete: cancelled {len(cancelled)} orders, "
                f"{len(errors)} errors"
            )
            
            return {
                "success": len(errors) == 0,
                "cancelled": cancelled,
                "errors": errors,
                "total_cancelled": len(cancelled),
            }
            
        except Exception as e:
            logger.error(f"Error in kill switch: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "cancelled": [],
            }


@dataclass
class GetPositionsTask:
    """Task to retrieve current positions."""
    task_id: str
    symbol_filter: Optional[str] = None  # Filter to specific symbol
    
    def execute(self, ib: IB) -> Dict[str, Any]:
        """Get current positions."""
        logger.debug("GetPositionsTask: fetching positions")
        
        try:
            positions = []
            
            for position in ib.positions():
                # Filter by symbol if specified
                if self.symbol_filter:
                    if position.contract.symbol != self.symbol_filter:
                        continue
                
                # Only include futures positions
                if position.contract.secType != "FUT":
                    continue
                
                positions.append({
                    "symbol": position.contract.symbol,
                    "local_symbol": position.contract.localSymbol,
                    "quantity": int(position.position),
                    "avg_price": float(position.avgCost),
                    "account": position.account,
                })
            
            logger.debug(f"Found {len(positions)} positions")
            return {
                "success": True,
                "positions": positions,
            }
            
        except Exception as e:
            logger.error(f"Error getting positions: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "positions": [],
            }


@dataclass
class GetOpenOrdersTask:
    """Task to retrieve open orders."""
    task_id: str
    
    def execute(self, ib: IB) -> Dict[str, Any]:
        """Get open orders."""
        logger.debug("GetOpenOrdersTask: fetching open orders")
        
        try:
            orders = []
            
            for trade in ib.openTrades():
                order = trade.order
                contract = trade.contract
                
                orders.append({
                    "order_id": order.orderId,
                    "symbol": contract.symbol,
                    "local_symbol": contract.localSymbol,
                    "action": order.action,
                    "quantity": int(order.totalQuantity),
                    "order_type": order.orderType,
                    "limit_price": getattr(order, "lmtPrice", None),
                    "stop_price": getattr(order, "stopPrice", None),
                    "status": trade.orderStatus.status,
                    "filled": int(trade.orderStatus.filled),
                    "remaining": int(trade.orderStatus.remaining),
                })
            
            logger.debug(f"Found {len(orders)} open orders")
            return {
                "success": True,
                "orders": orders,
            }
            
        except Exception as e:
            logger.error(f"Error getting open orders: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "orders": [],
            }






