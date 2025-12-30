"""
IBKR Execution Adapter

Implements the ExecutionAdapter interface for Interactive Brokers.
Uses a dedicated executor thread for order operations, separate from data operations.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
import uuid
from concurrent.futures import Future as ConcurrentFuture
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ib_insync import IB

from pearlalgo.execution.base import (
    ExecutionAdapter,
    ExecutionConfig,
    ExecutionResult,
    OrderStatus,
    Position,
)
from pearlalgo.execution.ibkr.tasks import (
    CancelAllOrdersTask,
    CancelOrderTask,
    GetOpenOrdersTask,
    GetPositionsTask,
    PlaceBracketOrderTask,
)
from pearlalgo.utils.logger import logger


class IBKRExecutionAdapter(ExecutionAdapter):
    """
    IBKR implementation of the ExecutionAdapter.
    
    Features:
    - Bracket orders with stop loss and take profit
    - Kill switch to cancel all orders
    - Position tracking
    - Separate executor thread from data operations
    """
    
    def __init__(self, config: ExecutionConfig):
        """
        Initialize IBKR execution adapter.
        
        Args:
            config: Execution configuration
        """
        super().__init__(config)
        
        # IB connection (owned by executor thread)
        self._ib: Optional[IB] = None
        self._connected = False
        
        # Executor thread
        self._task_queue: queue.Queue = queue.Queue()
        self._results: Dict[str, ConcurrentFuture] = {}
        self._results_lock = threading.Lock()
        self._executor_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._running = False
        
        # Rate limiting
        self._last_request_time: float = 0.0
        self._min_request_interval = 0.2  # 200ms between requests
        
        logger.info(
            f"IBKRExecutionAdapter initialized: "
            f"host={config.ibkr_host}, port={config.ibkr_port}, "
            f"client_id={config.ibkr_trading_client_id}, mode={config.mode.value}"
        )
    
    async def connect(self) -> bool:
        """
        Establish connection to IBKR Gateway.
        
        Starts the executor thread which owns the IB connection.
        """
        if self._running:
            return self._connected
        
        # Start executor thread
        self._running = True
        self._shutdown_event.clear()
        self._executor_thread = threading.Thread(
            target=self._run_executor,
            daemon=False,
            name="IBKRExecutionThread",
        )
        self._executor_thread.start()
        
        # Wait for connection
        for _ in range(50):  # 5 second timeout
            if self._connected:
                return True
            await asyncio.sleep(0.1)
        
        logger.error("Failed to connect to IBKR Gateway within timeout")
        return False
    
    async def disconnect(self) -> None:
        """Disconnect from IBKR Gateway and stop executor thread."""
        if not self._running:
            return
        
        logger.info("Disconnecting IBKRExecutionAdapter...")
        self._shutdown_event.set()
        
        # Wait for thread to finish
        if self._executor_thread:
            self._executor_thread.join(timeout=10.0)
            if self._executor_thread.is_alive():
                logger.warning("Executor thread did not stop within timeout")
        
        self._running = False
        self._connected = False
        logger.info("IBKRExecutionAdapter disconnected")
    
    def is_connected(self) -> bool:
        """Check if connected to IBKR Gateway."""
        return self._connected and self._ib is not None and self._ib.isConnected()
    
    def _run_executor(self) -> None:
        """Main executor loop (runs in dedicated thread)."""
        # Create event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        logger.info("IBKR Execution thread started")
        
        # Initialize IB connection
        self._ib = IB()
        
        # Connect
        try:
            self._ib.connect(
                host=self.config.ibkr_host,
                port=self.config.ibkr_port,
                clientId=self.config.ibkr_trading_client_id,
                timeout=10,
            )
            self._connected = True
            logger.info(
                f"Connected to IBKR Gateway for execution "
                f"(client_id={self.config.ibkr_trading_client_id})"
            )
        except Exception as e:
            logger.error(f"Failed to connect to IBKR Gateway: {e}")
            self._connected = False
        
        # Main loop
        while not self._shutdown_event.is_set():
            try:
                # Get task from queue
                try:
                    task = self._task_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # Execute task
                try:
                    # Rate limiting
                    elapsed = time.time() - self._last_request_time
                    if elapsed < self._min_request_interval:
                        time.sleep(self._min_request_interval - elapsed)
                    self._last_request_time = time.time()
                    
                    # Execute
                    result = task.execute(self._ib)
                    
                    # Set result in Future
                    with self._results_lock:
                        future = self._results.pop(task.task_id, None)
                        if future:
                            future.set_result(result)
                            
                except Exception as e:
                    logger.error(f"Error executing task {task.task_id}: {e}", exc_info=True)
                    with self._results_lock:
                        future = self._results.pop(task.task_id, None)
                        if future:
                            future.set_exception(e)
                            
            except Exception as e:
                logger.error(f"Unexpected error in executor loop: {e}", exc_info=True)
                time.sleep(1.0)
        
        # Cleanup
        if self._ib and self._ib.isConnected():
            try:
                self._ib.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting: {e}")
        
        try:
            loop.close()
        except Exception:
            pass
        
        logger.info("IBKR Execution thread stopped")
    
    def _submit_task(self, task: Any) -> ConcurrentFuture:
        """Submit a task to the executor."""
        if not self._running:
            raise RuntimeError("Executor is not running")
        
        future = ConcurrentFuture()
        with self._results_lock:
            self._results[task.task_id] = future
        
        self._task_queue.put(task)
        return future
    
    async def place_bracket(self, signal: Dict) -> ExecutionResult:
        """
        Place a bracket order (entry + stop loss + take profit).
        
        Args:
            signal: Signal dictionary
            
        Returns:
            ExecutionResult with order details or error
        """
        signal_id = signal.get("signal_id", str(uuid.uuid4()))
        
        # Check preconditions
        decision = self.check_preconditions(signal)
        if not decision.execute:
            logger.info(f"Execution skipped: {decision.reason}")
            return ExecutionResult(
                success=False,
                status=OrderStatus.REJECTED,
                signal_id=signal_id,
                error_message=decision.reason,
            )
        
        # In dry_run mode, simulate success without placing orders
        if self.config.mode.value == "dry_run":
            logger.info(f"DRY_RUN: Would place bracket order for {signal_id}")
            self._orders_today += 1
            signal_type = signal.get("type", "unknown")
            self._last_order_time[signal_type] = datetime.now(timezone.utc)
            
            return ExecutionResult(
                success=True,
                status=OrderStatus.PLACED,
                signal_id=signal_id,
                order_id=f"dry_run_{signal_id}",
            )
        
        # Check connection
        if not self.is_connected():
            return ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id=signal_id,
                error_message="Not connected to IBKR",
            )
        
        # Extract signal parameters
        symbol = signal.get("symbol", "MNQ")
        direction = signal.get("direction", "long")
        entry_price = float(signal.get("entry_price", 0))
        stop_loss = float(signal.get("stop_loss", 0))
        take_profit = float(signal.get("take_profit", 0))
        position_size = int(signal.get("position_size", 1))
        
        # Validate prices
        if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
            return ExecutionResult(
                success=False,
                status=OrderStatus.REJECTED,
                signal_id=signal_id,
                error_message="Invalid prices in signal",
            )
        
        # Create and submit task
        task = PlaceBracketOrderTask(
            task_id=f"place_{signal_id}",
            symbol=symbol,
            direction=direction,
            quantity=position_size,
            entry_price=entry_price,
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            signal_id=signal_id,
        )
        
        try:
            future = self._submit_task(task)
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: future.result(timeout=30)
            )
            
            if result.get("success"):
                self._orders_today += 1
                signal_type = signal.get("type", "unknown")
                self._last_order_time[signal_type] = datetime.now(timezone.utc)
                
                return ExecutionResult(
                    success=True,
                    status=OrderStatus.PLACED,
                    signal_id=signal_id,
                    parent_order_id=result.get("parent_order_id"),
                    stop_order_id=result.get("stop_order_id"),
                    take_profit_order_id=result.get("take_profit_order_id"),
                )
            else:
                return ExecutionResult(
                    success=False,
                    status=OrderStatus.ERROR,
                    signal_id=signal_id,
                    error_message=result.get("error", "Unknown error"),
                )
                
        except Exception as e:
            logger.error(f"Error placing bracket order: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id=signal_id,
                error_message=str(e),
            )
    
    async def cancel_order(self, order_id: str) -> ExecutionResult:
        """Cancel a specific order."""
        if self.config.mode.value == "dry_run":
            logger.info(f"DRY_RUN: Would cancel order {order_id}")
            return ExecutionResult(
                success=True,
                status=OrderStatus.CANCELLED,
                signal_id="",
                order_id=order_id,
            )
        
        if not self.is_connected():
            return ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id="",
                error_message="Not connected to IBKR",
            )
        
        task = CancelOrderTask(
            task_id=f"cancel_{order_id}",
            order_id=int(order_id),
        )
        
        try:
            future = self._submit_task(task)
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: future.result(timeout=10)
            )
            
            return ExecutionResult(
                success=result.get("success", False),
                status=OrderStatus.CANCELLED if result.get("success") else OrderStatus.ERROR,
                signal_id="",
                order_id=order_id,
                error_message=result.get("error"),
            )
            
        except Exception as e:
            logger.error(f"Error cancelling order: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id="",
                error_message=str(e),
            )
    
    async def cancel_all(self) -> List[ExecutionResult]:
        """Cancel all open orders (kill switch)."""
        logger.warning("KILL SWITCH ACTIVATED - Cancelling all orders")
        
        # Disarm immediately
        self.disarm()
        
        if self.config.mode.value == "dry_run":
            logger.info("DRY_RUN: Would cancel all orders")
            return [ExecutionResult(
                success=True,
                status=OrderStatus.CANCELLED,
                signal_id="kill_switch",
            )]
        
        if not self.is_connected():
            return [ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id="kill_switch",
                error_message="Not connected to IBKR",
            )]
        
        task = CancelAllOrdersTask(task_id=f"cancel_all_{time.time()}")
        
        try:
            future = self._submit_task(task)
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: future.result(timeout=30)
            )
            
            results = []
            for order_id in result.get("cancelled", []):
                results.append(ExecutionResult(
                    success=True,
                    status=OrderStatus.CANCELLED,
                    signal_id="kill_switch",
                    order_id=str(order_id),
                ))
            
            for error in result.get("errors", []):
                results.append(ExecutionResult(
                    success=False,
                    status=OrderStatus.ERROR,
                    signal_id="kill_switch",
                    order_id=str(error.get("order_id")),
                    error_message=error.get("error"),
                ))
            
            if not results:
                results.append(ExecutionResult(
                    success=True,
                    status=OrderStatus.CANCELLED,
                    signal_id="kill_switch",
                ))
            
            return results
            
        except Exception as e:
            logger.error(f"Error in kill switch: {e}", exc_info=True)
            return [ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id="kill_switch",
                error_message=str(e),
            )]
    
    async def get_positions(self) -> List[Position]:
        """Get current positions."""
        if self.config.mode.value == "dry_run":
            return list(self._positions.values())
        
        if not self.is_connected():
            logger.warning("Not connected - returning cached positions")
            return list(self._positions.values())
        
        task = GetPositionsTask(
            task_id=f"positions_{time.time()}",
            symbol_filter=None,  # Get all positions
        )
        
        try:
            future = self._submit_task(task)
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: future.result(timeout=10)
            )
            
            positions = []
            for pos_data in result.get("positions", []):
                pos = Position(
                    symbol=pos_data.get("symbol", ""),
                    quantity=pos_data.get("quantity", 0),
                    avg_price=pos_data.get("avg_price", 0.0),
                )
                positions.append(pos)
                # Update cache
                self._positions[pos.symbol] = pos
            
            return positions
            
        except Exception as e:
            logger.error(f"Error getting positions: {e}", exc_info=True)
            return list(self._positions.values())
    
    async def get_open_orders(self) -> List[Dict]:
        """Get open orders (for status display)."""
        if self.config.mode.value == "dry_run":
            return []
        
        if not self.is_connected():
            return []
        
        task = GetOpenOrdersTask(task_id=f"orders_{time.time()}")
        
        try:
            future = self._submit_task(task)
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: future.result(timeout=10)
            )
            return result.get("orders", [])
            
        except Exception as e:
            logger.error(f"Error getting open orders: {e}", exc_info=True)
            return []

