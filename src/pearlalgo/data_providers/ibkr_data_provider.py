"""
IBKR Data Provider for stocks, futures, and options.

Uses IB Gateway via ib_insync for live and historical data.
Supports:
- Historical OHLCV data for stocks and futures
- Real-time quotes
- Full options chains with filtering
- Connection management and reconnection
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd
from ib_insync import IB, Contract, Future, Option, Stock, util

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.utils.retry import async_retry_with_backoff

logger = logging.getLogger(__name__)


class IBKRDataProvider(DataProvider):
    """
    IBKR data provider using IB Gateway via ib_insync.
    
    Supports:
    - Historical OHLCV data (stocks and futures)
    - Real-time quotes
    - Options chains with filtering
    - Automatic connection management
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
    ):
        """
        Initialize IBKR data provider.
        
        Args:
            settings: Settings instance (optional, uses get_settings() if not provided)
            host: IB Gateway host (default: from settings)
            port: IB Gateway port (default: from settings)
            client_id: Client ID for data connections (default: IBKR_DATA_CLIENT_ID from settings)
        """
        self.settings = settings or get_settings()
        self.host = host or self.settings.ib_host
        self.port = port or self.settings.ib_port
        self.client_id = client_id or self.settings.ib_data_client_id or self.settings.ib_client_id
        
        # IB connection instance
        self.ib: Optional[IB] = None
        self._connected = False
        self._connection_lock = asyncio.Lock()
        
        # Rate limiting
        self._last_request_time: float = 0.0
        self._min_request_interval = 0.1  # 100ms between requests
        
        logger.info(
            f"IBKRDataProvider initialized: host={self.host}, port={self.port}, client_id={self.client_id}"
        )

    async def _ensure_connected(self) -> None:
        """Ensure IB connection is established."""
        async with self._connection_lock:
            if self._connected and self.ib and self.ib.isConnected():
                return
            
            if self.ib is None:
                self.ib = IB()
            
            try:
                if not self.ib.isConnected():
                    logger.info(f"Connecting to IB Gateway at {self.host}:{self.port}")
                    await self.ib.connectAsync(
                        self.host,
                        self.port,
                        clientId=self.client_id,
                        timeout=10
                    )
                    self._connected = True
                    logger.info("Connected to IB Gateway successfully")
            except Exception as e:
                self._connected = False
                logger.error(f"Failed to connect to IB Gateway: {e}")
                raise RuntimeError(
                    f"Cannot connect to IB Gateway at {self.host}:{self.port}. "
                    f"Ensure IB Gateway/TWS is running with API enabled. Error: {e}"
                ) from e

    async def _rate_limit(self) -> None:
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    async def close(self) -> None:
        """Close IB connection."""
        if self.ib and self.ib.isConnected():
            try:
                self.ib.disconnect()
                logger.info("Disconnected from IB Gateway")
            except Exception as e:
                logger.warning(f"Error disconnecting from IB Gateway: {e}")
        self._connected = False

    def _create_stock_contract(self, symbol: str) -> Stock:
        """Create stock contract."""
        return Stock(symbol, "SMART", "USD")

    def _create_futures_contract(self, symbol: str, exchange: str = "GLOBEX") -> Future:
        """
        Create futures contract.
        
        For symbols like ES, NQ, we need to resolve to active contract.
        IB requires format like ESU5 (ES, Sep 2025) or we can use generic and let IB resolve.
        """
        # For now, use generic contract - IB will resolve to front month
        # For production, you may want to query active contracts first
        return Future(symbol, exchange, "USD")

    def _create_option_contract(
        self,
        underlying_symbol: str,
        strike: float,
        expiration: str,
        option_type: str,
    ) -> Option:
        """
        Create option contract.
        
        Args:
            underlying_symbol: Underlying symbol (e.g., 'QQQ')
            strike: Strike price
            expiration: Expiration date in YYYYMMDD format
            option_type: 'C' for call, 'P' for put
        """
        stock = Stock(underlying_symbol, "SMART", "USD")
        option = Option(
            underlying_symbol,
            expiration,
            strike,
            option_type,
            "SMART"
        )
        return option

    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data synchronously.
        
        Args:
            symbol: Ticker symbol (e.g., 'AAPL', 'ES' for futures)
            start: Start datetime (default: 1 year ago)
            end: End datetime (default: now)
            timeframe: Timeframe (e.g., '1m', '5m', '15m', '1h', '1d')
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            self._fetch_historical_async(symbol, start, end, timeframe)
        )

    async def _fetch_historical_async(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> pd.DataFrame:
        """Async implementation of fetch_historical."""
        await self._ensure_connected()
        
        if start is None:
            start = datetime.now(timezone.utc) - timedelta(days=365)
        if end is None:
            end = datetime.now(timezone.utc)
        
        # Convert timeframe to IB bar size format
        bar_size_map = {
            "1m": "1 min",
            "5m": "5 mins",
            "15m": "15 mins",
            "30m": "30 mins",
            "1h": "1 hour",
            "1d": "1 day",
        }
        bar_size = bar_size_map.get(timeframe.lower() if timeframe else "1d", "1 day")
        
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
        
        # Determine if symbol is futures or stock
        # Simple heuristic: if symbol is 2-3 letters and common futures, treat as futures
        futures_symbols = {"ES", "NQ", "YM", "RTY", "CL", "GC", "SI", "NG", "ZB", "ZN", "ZF", "ZT"}
        is_futures = symbol.upper() in futures_symbols
        
        try:
            await self._rate_limit()
            
            # Create contract
            if is_futures:
                contract = self._create_futures_contract(symbol)
            else:
                contract = self._create_stock_contract(symbol)
            
            # Request historical data
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end,
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
            )
            
            if not bars:
                logger.warning(f"No historical data returned for {symbol}")
                return pd.DataFrame()
            
            # Convert to DataFrame
            df = util.df(bars)
            if df.empty:
                return pd.DataFrame()
            
            # Rename columns to standard format
            df = df.rename(columns={
                "date": "timestamp",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            })
            
            # Ensure timestamp is datetime and set as index
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.set_index("timestamp")
            
            # Filter by start/end if needed (IB may return more data)
            if start:
                df = df[df.index >= start]
            if end:
                df = df[df.index <= end]
            
            logger.info(f"Retrieved {len(df)} bars for {symbol} ({df.index.min()} to {df.index.max()})")
            return df
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}", exc_info=True)
            return pd.DataFrame()

    @async_retry_with_backoff(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=5.0,
        exponential_base=2.0,
    )
    async def get_latest_bar(self, symbol: str) -> Optional[Dict]:
        """
        Get latest bar/quote for a symbol.
        
        Args:
            symbol: Ticker symbol
            
        Returns:
            Dict with timestamp, open, high, low, close, volume, or None if unavailable
        """
        try:
            await self._ensure_connected()
            await self._rate_limit()
            
            # Determine if futures or stock
            futures_symbols = {"ES", "NQ", "YM", "RTY", "CL", "GC", "SI", "NG", "ZB", "ZN", "ZF", "ZT"}
            is_futures = symbol.upper() in futures_symbols
            
            # Create contract
            if is_futures:
                contract = self._create_futures_contract(symbol)
            else:
                contract = self._create_stock_contract(symbol)
            
            # Request market data
            ticker = await self.ib.reqMktDataAsync(contract, "", False, False)
            
            # Wait a moment for data to arrive
            await asyncio.sleep(0.5)
            
            # Get last price
            last_price = ticker.last if ticker.last else ticker.close
            
            if last_price and last_price > 0:
                return {
                    "timestamp": datetime.now(timezone.utc),
                    "open": ticker.open if ticker.open else last_price,
                    "high": ticker.high if ticker.high else last_price,
                    "low": ticker.low if ticker.low else last_price,
                    "close": last_price,
                    "volume": ticker.volume if ticker.volume else 0,
                    "bid": ticker.bid if ticker.bid else None,
                    "ask": ticker.ask if ticker.ask else None,
                }
            
            logger.warning(f"No price data available for {symbol}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching latest bar for {symbol}: {e}")
            return None

    async def get_options_chain(
        self,
        underlying_symbol: str,
        expiration_date: Optional[str] = None,
        min_dte: Optional[int] = None,
        max_dte: Optional[int] = None,
        strike_proximity_pct: Optional[float] = None,
        min_volume: Optional[int] = None,
        min_open_interest: Optional[int] = None,
        underlying_price: Optional[float] = None,
    ) -> List[Dict]:
        """
        Get options chain for an underlying symbol with filtering.
        
        Args:
            underlying_symbol: Underlying ticker (e.g., 'QQQ', 'SPY')
            expiration_date: Expiration date in YYYYMMDD format (optional)
            min_dte: Minimum days to expiration (optional)
            max_dte: Maximum days to expiration (optional)
            strike_proximity_pct: Filter strikes within X% of current price (optional)
            min_volume: Minimum volume threshold (optional)
            min_open_interest: Minimum open interest threshold (optional)
            underlying_price: Current underlying price for strike filtering (optional)
            
        Returns:
            List of option contracts with strike, expiration, type (call/put)
        """
        try:
            await self._ensure_connected()
            await self._rate_limit()
            
            # Get underlying price if not provided
            if underlying_price is None:
                latest_bar = await self.get_latest_bar(underlying_symbol)
                if latest_bar:
                    underlying_price = latest_bar.get("close", 0)
                else:
                    logger.warning(f"Cannot get underlying price for {underlying_symbol}")
                    return []
            
            if underlying_price <= 0:
                logger.warning(f"Invalid underlying price for {underlying_symbol}: {underlying_price}")
                return []
            
            # Create stock contract for underlying
            stock = self._create_stock_contract(underlying_symbol)
            
            # Request option chains
            # IB requires us to request chains for specific expirations
            # First, get available expirations
            chains = await self.ib.reqSecDefOptParamsAsync(
                stock.symbol,
                "",
                stock.secType,
                stock.conId
            )
            
            if not chains:
                logger.warning(f"No option chains found for {underlying_symbol}")
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
                    if min_dte is not None and dte < min_dte:
                        continue
                    if max_dte is not None and dte > max_dte:
                        continue
                    if expiration_date and expiration_str != expiration_date:
                        continue
                    
                    # Process strikes for this expiration
                    for strike in chain.strikes:
                        # Filter by strike proximity
                        if strike_proximity_pct and underlying_price > 0:
                            strike_pct = abs(strike - underlying_price) / underlying_price
                            if strike_pct > strike_proximity_pct:
                                continue
                        
                        # Get option contracts for call and put
                        for option_type in ["C", "P"]:
                            option = Option(
                                underlying_symbol,
                                expiration_str,
                                strike,
                                option_type,
                                "SMART"
                            )
                            
                            try:
                                # Request market data for this option
                                await self._rate_limit()
                                ticker = await self.ib.reqMktDataAsync(option, "", False, False)
                                await asyncio.sleep(0.1)  # Brief wait for data
                                
                                # Get option data
                                volume = ticker.volume if ticker.volume else 0
                                open_interest = ticker.openInterest if hasattr(ticker, 'openInterest') else 0
                                
                                # Filter by volume and OI
                                if min_volume is not None and volume < min_volume:
                                    continue
                                if min_open_interest is not None and open_interest < min_open_interest:
                                    continue
                                
                                # Build option dict
                                option_dict = {
                                    "symbol": f"{underlying_symbol} {expiration_str} {strike} {option_type}",
                                    "underlying_symbol": underlying_symbol,
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
                                
            logger.info(f"Retrieved {len(all_options)} options for {underlying_symbol}")
            return all_options
            
        except Exception as e:
            logger.error(f"Error fetching options chain for {underlying_symbol}: {e}", exc_info=True)
            return []

    async def get_options_chain_filtered(
        self,
        underlying_symbol: str,
        mode: str = "intraday",  # "intraday" or "swing"
        underlying_price: Optional[float] = None,
    ) -> List[Dict]:
        """
        Get filtered options chain based on trading mode.
        
        Args:
            underlying_symbol: Underlying ticker
            mode: "intraday" (0-7 DTE) or "swing" (7-45 DTE)
            underlying_price: Current underlying price for strike filtering
            
        Returns:
            Filtered list of option contracts
        """
        if mode == "intraday":
            return await self.get_options_chain(
                underlying_symbol=underlying_symbol,
                min_dte=0,
                max_dte=7,
                strike_proximity_pct=0.10,  # Within 10% of current price
                min_volume=100,
                min_open_interest=500,
                underlying_price=underlying_price,
            )
        elif mode == "swing":
            return await self.get_options_chain(
                underlying_symbol=underlying_symbol,
                min_dte=7,
                max_dte=45,
                strike_proximity_pct=0.15,  # Within 15% of current price
                min_volume=50,
                min_open_interest=200,
                underlying_price=underlying_price,
            )
        else:
            logger.warning(f"Unknown mode: {mode}, using default filtering")
            return await self.get_options_chain(
                underlying_symbol=underlying_symbol,
                underlying_price=underlying_price,
            )
