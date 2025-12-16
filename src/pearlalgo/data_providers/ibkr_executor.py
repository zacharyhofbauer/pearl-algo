"""
IBKR Executor - Thread-safe executor for IBKR API calls.

This module provides a dedicated thread that owns the IB connection and executes
all IBKR API calls synchronously. Workers submit tasks via a queue and receive
results through Futures, eliminating event loop issues.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ib_insync import IB, Future, Option, Stock, util

from pearlalgo.utils.logger import logger


@dataclass
class Task(ABC):
    """Base class for executor tasks."""

    task_id: str
    # Note: timeout is not in base class to avoid dataclass inheritance issues
    # Subclasses can add timeout with default if needed

    @abstractmethod
    def execute(self, ib: IB) -> Any:
        """Execute the task using the IB connection."""
        pass


@dataclass
class ConnectTask(Task):
    """Task to establish IB connection."""

    host: str
    port: int
    client_id: int
    timeout: float = 10.0

    def execute(self, ib: IB) -> bool:
        """Connect to IB Gateway."""
        if ib.isConnected():
            return True
        ib.connect(host=self.host, port=self.port, clientId=self.client_id, timeout=self.timeout)
        return ib.isConnected()


@dataclass
class GetLatestBarTask(Task):
    """Task to fetch latest bar/quote for a symbol."""

    symbol: str
    is_futures: bool = False

    def execute(self, ib: IB) -> Optional[Dict]:
        """Fetch latest bar data."""
        # Create contract
        if self.is_futures:
            # For futures, use reqContractDetails to get all contracts, then select front month
            contract = Future(self.symbol, exchange="CME", currency="USD")
            try:
                # Request contract details which returns all available contracts
                contracts = ib.reqContractDetails(contract)
                if contracts:
                    # Select the front month (nearest expiration)
                    contract_details = min(contracts, key=lambda cd: cd.contract.lastTradeDateOrContractMonth)
                    contract = contract_details.contract
                    logger.debug(f"Selected front month contract: {contract.localSymbol} (exp: {contract.lastTradeDateOrContractMonth})")
                else:
                    logger.warning(f"No contract details found for {self.symbol}")
                    return None
            except Exception as e:
                logger.warning(f"Error getting contract details for {self.symbol}: {e}")
                return None
        else:
            contract = Stock(self.symbol, exchange="SMART", currency="USD")

        # Try to get real-time market data first
        ticker = None
        try:
            # Request market data (may fail with Error 354 if no subscription)
            ticker = ib.reqMktData(contract, "", False, False)
            
            # Wait a moment for data to arrive
            time.sleep(0.5)
            
            # Check for market data errors
            if hasattr(ticker, 'modelOption') and ticker.modelOption:
                # Check if there's an error message
                error_msg = str(ticker.modelOption) if ticker.modelOption else ""
                if "354" in error_msg or "subscription" in error_msg.lower():
                    logger.debug(f"Market data subscription not available for {self.symbol}, will use historical data fallback")
                    ib.cancelMktData(contract)
                    ticker = None  # Will fall back to historical data
                elif ticker.last or ticker.close:
                    # Got valid data
                    last_price = ticker.last if ticker.last else ticker.close
                    if last_price and last_price > 0:
                        result = {
                            "timestamp": datetime.now(timezone.utc),
                            "open": ticker.open if ticker.open else last_price,
                            "high": ticker.high if ticker.high else last_price,
                            "low": ticker.low if ticker.low else last_price,
                            "close": last_price,
                            "volume": ticker.volume if ticker.volume else 0,
                            "bid": ticker.bid if ticker.bid else None,
                            "ask": ticker.ask if ticker.ask else None,
                        }
                        ib.cancelMktData(contract)
                        return result
        except Exception as e:
            error_str = str(e).lower()
            if "354" in str(e) or "subscription" in error_str:
                logger.debug(f"Market data subscription error for {self.symbol}: {e}. Will use historical data fallback.")
            else:
                logger.warning(f"Error requesting market data for {self.symbol}: {e}")
            if ticker:
                try:
                    ib.cancelMktData(contract)
                except Exception:
                    pass
            ticker = None  # Will fall back to historical data

        # Fallback: Use latest historical bar if real-time data not available
        # This handles Error 354 (market data subscription not available)
        try:
            logger.debug(f"Using historical data fallback for latest bar (real-time subscription may not be available)")
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="1 D",
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
            )
            
            if bars:
                # Get the most recent bar
                latest_bar = bars[-1]
                return {
                    "timestamp": latest_bar.date.replace(tzinfo=timezone.utc) if latest_bar.date.tzinfo is None else latest_bar.date,
                    "open": float(latest_bar.open),
                    "high": float(latest_bar.high),
                    "low": float(latest_bar.low),
                    "close": float(latest_bar.close),
                    "volume": int(latest_bar.volume),
                    "bid": None,  # Not available from historical data
                    "ask": None,  # Not available from historical data
                }
        except Exception as e:
            logger.warning(f"Error fetching historical data fallback for {self.symbol}: {e}")
        
        return None


@dataclass
class GetHistoricalDataTask(Task):
    """Task to fetch historical OHLCV data."""

    symbol: str
    start: Optional[datetime]
    end: Optional[datetime]
    timeframe: Optional[str]
    is_futures: bool = False

    def execute(self, ib: IB) -> Any:
        """Fetch historical data."""
        if self.start is None:
            start = datetime.now(timezone.utc) - timedelta(days=365)
        else:
            start = self.start
        if self.end is None:
            end = datetime.now(timezone.utc)
        else:
            end = self.end

        # Convert timeframe to IB bar size format
        bar_size_map = {
            "1m": "1 min",
            "5m": "5 mins",
            "15m": "15 mins",
            "30m": "30 mins",
            "1h": "1 hour",
            "1d": "1 day",
        }
        bar_size = bar_size_map.get(self.timeframe.lower() if self.timeframe else "1d", "1 day")

        # Calculate duration string for IB
        duration_days = (end - start).days
        if duration_days <= 1:
            duration_str = "1 D"
        elif duration_days <= 7:
            duration_str = "1 W"
        elif duration_days <= 30:
            duration_str = "1 M"
        elif duration_days <= 365:
            duration_str = "1 Y"
        else:
            duration_str = f"{duration_days} D"

        # Create contract
        if self.is_futures:
            # For futures, use reqContractDetails to get all contracts, then select front month
            contract = Future(self.symbol, exchange="CME", currency="USD")
            try:
                # Request contract details which returns all available contracts
                contracts = ib.reqContractDetails(contract)
                if contracts:
                    # Select the front month (nearest expiration)
                    contract_details = min(contracts, key=lambda cd: cd.contract.lastTradeDateOrContractMonth)
                    contract = contract_details.contract
                    logger.debug(f"Selected front month contract: {contract.localSymbol} (exp: {contract.lastTradeDateOrContractMonth})")
                else:
                    logger.warning(f"No contract details found for {self.symbol}")
                    return []
            except Exception as e:
                logger.warning(f"Error getting contract details for {self.symbol}: {e}")
                return []
        else:
            contract = Stock(self.symbol, exchange="SMART", currency="USD")

        # Request historical data
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end,
            durationStr=duration_str,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
        )

        return bars


@dataclass
class GetOptionsChainTask(Task):
    """Task to fetch options chain."""

    underlying_symbol: str
    expiration_date: Optional[str] = None
    min_dte: Optional[int] = None
    max_dte: Optional[int] = None
    strike_proximity_pct: Optional[float] = None
    min_volume: Optional[int] = None
    min_open_interest: Optional[int] = None
    underlying_price: Optional[float] = None

    def execute(self, ib: IB) -> List[Dict]:
        """Fetch options chain with filtering."""
        # Create stock contract for underlying
        stock = Stock(self.underlying_symbol, "SMART", "USD")

        # Request option chains
        chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)

        if not chains:
            return []

        # Get today's date for DTE calculation
        today = date.today()
        all_options = []

        # Process each chain (each chain represents an expiration)
        for chain in chains:
            expiration_str = chain.expirations[0] if chain.expirations else None
            if not expiration_str:
                continue

            # Parse expiration date
            try:
                # IB returns expiration as YYYYMMDD string
                exp_date = datetime.strptime(expiration_str, "%Y%m%d").date()
                dte = (exp_date - today).days

                # Filter by DTE
                if self.min_dte is not None and dte < self.min_dte:
                    continue
                if self.max_dte is not None and dte > self.max_dte:
                    continue
                if self.expiration_date and expiration_str != self.expiration_date:
                    continue

                # Process strikes for this expiration
                for strike in chain.strikes:
                    # Filter by strike proximity
                    if self.strike_proximity_pct and self.underlying_price and self.underlying_price > 0:
                        strike_pct = abs(strike - self.underlying_price) / self.underlying_price
                        if strike_pct > self.strike_proximity_pct:
                            continue

                    # Get option contracts for call and put
                    for option_type in ["C", "P"]:
                        option = Option(
                            self.underlying_symbol,
                            expiration_str,
                            strike,
                            option_type,
                            "SMART"
                        )

                        try:
                            # Request market data for this option
                            ticker = ib.reqMktData(option, "", False, False)
                            time.sleep(0.1)  # Brief wait for data

                            # Get option data
                            volume = ticker.volume if ticker.volume else 0
                            open_interest = ticker.openInterest if hasattr(ticker, 'openInterest') else 0

                            # Filter by volume and OI
                            if self.min_volume is not None and volume < self.min_volume:
                                continue
                            if self.min_open_interest is not None and open_interest < self.min_open_interest:
                                continue

                            # Build option dict
                            option_dict = {
                                "symbol": f"{self.underlying_symbol} {expiration_str} {strike} {option_type}",
                                "underlying_symbol": self.underlying_symbol,
                                "strike": strike,
                                "expiration": expiration_str,
                                "expiration_date": exp_date.isoformat(),
                                "dte": dte,
                                "option_type": "call" if option_type == "C" else "put",
                                "bid": ticker.bid if ticker.bid else None,
                                "ask": ticker.ask if ticker.ask else None,
                                "last_price": ticker.last if ticker.last else (ticker.bid + ticker.ask) / 2 if ticker.bid and ticker.ask else None,
                                "volume": volume,
                                "open_interest": open_interest,
                                "iv": ticker.impliedVolatility if hasattr(ticker, 'impliedVolatility') else None,
                            }

                            all_options.append(option_dict)

                        except Exception as e:
                            logger.debug(f"Error fetching data for option {option}: {e}")
                            continue
            except Exception as e:
                logger.debug(f"Error parsing expiration {expiration_str}: {e}")
                continue

        return all_options


@dataclass
class ShutdownTask(Task):
    """Task to shutdown executor gracefully."""

    def execute(self, ib: IB) -> None:
        """Disconnect from IB Gateway."""
        if ib.isConnected():
            ib.disconnect()


class IBKRExecutor:
    """
    Thread-safe executor for IBKR API calls.
    
    Runs in a dedicated thread and executes all IBKR calls synchronously.
    Workers submit tasks via submit_task() and receive results through Futures.
    """

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 5,
    ):
        """
        Initialize IBKR executor.
        
        Args:
            host: IB Gateway host
            port: IB Gateway port
            client_id: Client ID for connection
            reconnect_delay: Initial delay between reconnection attempts (seconds)
            max_reconnect_attempts: Maximum reconnection attempts before giving up
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        # IB connection (owned by executor thread)
        self.ib: Optional[IB] = None
        self._connected = False

        # Task queue and results
        self._task_queue: queue.Queue = queue.Queue()
        self._results: Dict[str, ConcurrentFuture] = {}
        self._results_lock = threading.Lock()

        # Executor thread
        self._executor_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._running = False

        # Rate limiting
        self._last_request_time: float = 0.0
        self._min_request_interval = 0.1  # 100ms between requests

        # Connection state
        self._connection_lock = threading.Lock()
        self._reconnect_attempts = 0

        logger.info(
            f"IBKRExecutor initialized: host={host}, port={port}, client_id={client_id}"
        )

    def start(self) -> None:
        """Start the executor thread."""
        if self._running:
            return

        self._running = True
        self._executor_thread = threading.Thread(target=self._run_executor, daemon=False)
        self._executor_thread.start()
        logger.info("IBKRExecutor thread started")

    def stop(self, timeout: float = 10.0) -> None:
        """
        Stop the executor thread gracefully.
        
        Args:
            timeout: Maximum time to wait for shutdown (seconds)
        """
        if not self._running:
            return

        logger.info("Shutting down IBKRExecutor...")
        self._shutdown_event.set()

        # Submit shutdown task
        shutdown_task = ShutdownTask(task_id="shutdown")
        self._task_queue.put(shutdown_task)

        # Wait for thread to finish
        if self._executor_thread:
            self._executor_thread.join(timeout=timeout)
            if self._executor_thread.is_alive():
                logger.warning("IBKRExecutor thread did not stop within timeout")
            else:
                logger.info("IBKRExecutor thread stopped")

        self._running = False

    def submit_task(self, task: Task) -> ConcurrentFuture:
        """
        Submit a task to the executor.
        
        Args:
            task: Task to execute
            
        Returns:
            Future that will contain the result or exception
        """
        if not self._running:
            raise RuntimeError("Executor is not running. Call start() first.")

        # Create Future for result
        future = ConcurrentFuture()
        with self._results_lock:
            self._results[task.task_id] = future

        # Submit task to queue
        self._task_queue.put(task)

        return future

    def _run_executor(self) -> None:
        """Main executor loop (runs in dedicated thread)."""
        # Create event loop for this thread (required by ib_insync)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        logger.info("IBKRExecutor thread started")

        # Initialize IB connection
        self.ib = IB()

        # Connect on startup
        try:
            self._ensure_connected()
        except Exception as e:
            logger.error(f"Failed to connect on startup: {e}")

        # Main loop
        while not self._shutdown_event.is_set():
            try:
                # Get task from queue (with timeout to check shutdown)
                try:
                    task = self._task_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                # Handle shutdown task
                if isinstance(task, ShutdownTask):
                    task.execute(self.ib)
                    break

                # Execute task
                try:
                    # Ensure connection before executing
                    if not isinstance(task, ConnectTask):
                        self._ensure_connected()

                    # Rate limiting
                    self._rate_limit()

                    # Execute task
                    result = task.execute(self.ib)

                    # Set result in Future
                    with self._results_lock:
                        future = self._results.pop(task.task_id, None)
                        if future:
                            future.set_result(result)

                except Exception as e:
                    logger.error(f"Error executing task {task.task_id}: {e}", exc_info=True)

                    # Set exception in Future
                    with self._results_lock:
                        future = self._results.pop(task.task_id, None)
                        if future:
                            future.set_exception(e)

                    # Check if connection error - trigger reconnection
                    if "not connected" in str(e).lower() or "connection" in str(e).lower():
                        self._connected = False
                        logger.warning("Connection lost, will reconnect on next task")

            except Exception as e:
                logger.error(f"Unexpected error in executor loop: {e}", exc_info=True)
                time.sleep(1.0)

        # Cleanup
        if self.ib and self.ib.isConnected():
            try:
                self.ib.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting: {e}")

        # Cleanup event loop
        try:
            loop = asyncio.get_event_loop()
            if loop and not loop.is_closed():
                loop.close()
        except Exception as e:
            logger.debug(f"Error closing event loop: {e}")

        logger.info("IBKRExecutor thread stopped")

    def _ensure_connected(self) -> None:
        """Ensure IB connection is established (called from executor thread)."""
        with self._connection_lock:
            if self._connected and self.ib and self.ib.isConnected():
                return

            if self.ib is None:
                self.ib = IB()

            # Try to connect with retries
            while not self.ib.isConnected():
                logger.info(f"Connecting to IB Gateway at {self.host}:{self.port}")
                try:
                    self.ib.connect(
                        host=self.host,
                        port=self.port,
                        clientId=self.client_id,
                        timeout=10
                    )
                    self._connected = True
                    self._reconnect_attempts = 0
                    logger.info("Connected to IB Gateway successfully")
                    return
                except Exception as e:
                    self._connected = False
                    self._reconnect_attempts += 1

                    if self._reconnect_attempts >= self.max_reconnect_attempts:
                        logger.error(
                            f"Failed to connect after {self._reconnect_attempts} attempts. "
                            f"Giving up."
                        )
                        raise RuntimeError(
                            f"Cannot connect to IB Gateway at {self.host}:{self.port} "
                            f"after {self._reconnect_attempts} attempts. "
                            f"Error: {e}"
                        ) from e

                    # Exponential backoff (capped at 10s for tests)
                    delay = min(self.reconnect_delay * (2 ** (self._reconnect_attempts - 1)), 10.0)
                    logger.warning(
                        f"Connection failed (attempt {self._reconnect_attempts}/{self.max_reconnect_attempts}). "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    # Loop will retry connection

    def _rate_limit(self) -> None:
        """Enforce rate limiting (called from executor thread)."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def is_connected(self) -> bool:
        """Check if executor is connected to IB Gateway."""
        return self._connected and self.ib is not None and self.ib.isConnected()

    def get_queue_size(self) -> int:
        """Get current task queue size."""
        return self._task_queue.qsize()
