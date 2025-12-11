"""
Market Data Agent - Streams live market data via IBKR Gateway.

This agent is responsible for:
- Real-time data streaming for OHLCV, order book, OI
- IBKR Gateway primary provider for US stocks, futures, and options
- Requires IB Gateway/TWS running with API enabled
- Real-time data aggregation and normalization
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.agents.langgraph_state import (
    MarketData,
    TradingState,
    add_agent_reasoning,
)
from pearlalgo.config.settings import get_settings
from pearlalgo.data_providers.ibkr_data_provider import IBKRDataProvider
from pearlalgo.data_providers.buffer_manager import BufferManager

logger = logging.getLogger(__name__)


class MarketDataAgent:
    """
    Market Data Agent for LangGraph workflow.

    Fetches and streams real-time market data for all configured symbols.
    Uses IBKR Gateway for live data.
    """

    def __init__(
        self,
        symbols: List[str],
        config: Optional[Dict] = None,
        buffer_manager: Optional[BufferManager] = None,
    ):
        self.symbols = symbols
        self.config = config or {}

        # Initialize data providers
        self.ibkr_provider: Optional[IBKRDataProvider] = None

        # Data buffers (for caching normalized data)
        self.data_buffers: Dict[str, List[MarketData]] = {symbol: [] for symbol in symbols}

        # Historical data buffer manager
        self.buffer_manager = buffer_manager

        # Initialize IBKR provider
        self._initialize_providers()

        logger.info(f"MarketDataAgent initialized: symbols={symbols}")

    def _initialize_providers(self) -> None:
        """Initialize IBKR data provider."""
        try:
            from pearlalgo.config.settings import get_settings
            
            settings = get_settings()
            
            # Initialize IBKR provider (primary data source)
            try:
                self.ibkr_provider = IBKRDataProvider(settings=settings)
                logger.info("IBKR provider initialized")
            except Exception as e:
                logger.warning(f"IBKR provider initialization failed: {e}")
                logger.warning("Ensure IB Gateway/TWS is running with API enabled")

        except Exception as e:
            logger.error(f"Error initializing providers: {e}", exc_info=True)

    async def fetch_live_data(self, state: TradingState) -> TradingState:
        """
        Fetch live market data for all symbols.

        This is the main entry point called by the LangGraph workflow.
        """
        logger.info("MarketDataAgent: Fetching live data for all symbols")

        state = add_agent_reasoning(
            state,
            "market_data_agent",
            f"Fetching market data for {len(self.symbols)} symbols",
            level="info",
        )

        # Try WebSocket first, then REST fallback
        for symbol in self.symbols:
            try:
                market_data = await self._fetch_symbol_data(symbol)
                if market_data:
                    # Store in state
                    state.market_data[symbol] = market_data
                    
                    # Update historical buffer if available
                    if self.buffer_manager:
                        self.buffer_manager.add_bar(
                            symbol=symbol,
                            timestamp=market_data.timestamp,
                            open=market_data.open,
                            high=market_data.high,
                            low=market_data.low,
                            close=market_data.close,
                            volume=market_data.volume,
                        )
                    
                    # Update buffer (keep last 100 entries per symbol)
                    if symbol not in self.data_buffers:
                        self.data_buffers[symbol] = []
                    self.data_buffers[symbol].append(market_data)
                    if len(self.data_buffers[symbol]) > 100:
                        self.data_buffers[symbol] = self.data_buffers[symbol][-100:]
                    
                    state = add_agent_reasoning(
                        state,
                        "market_data_agent",
                        f"Updated market data for {symbol}: ${market_data.close:.2f}",
                        level="debug",
                        data={"symbol": symbol, "price": market_data.close, "volume": market_data.volume},
                    )
                else:
                    # No data returned - likely IB Gateway connection issue
                    logger.warning(
                        f"No market data available for {symbol}. "
                        f"⚠️  IB Gateway may not be connected or market data subscription may be required. "
                        f"Service will continue but cannot generate signals without market data. "
                        f"Ensure IB Gateway/TWS is running with API enabled."
                    )
                    state = add_agent_reasoning(
                        state,
                        "market_data_agent",
                        f"No data available for {symbol}",
                        level="warning",
                        data={"symbol": symbol},
                    )
            except Exception as e:
                error_msg = f"Error fetching data for {symbol}: {e}"
                logger.warning(error_msg, exc_info=True)  # Changed to warning, not error
                state.errors.append(error_msg)
                state = add_agent_reasoning(
                    state,
                    "market_data_agent",
                    error_msg,
                    level="warning",  # Changed to warning
                    data={"symbol": symbol, "error": str(e)},
                )

        # Update timestamp
        state.timestamp = datetime.now(timezone.utc)

        logger.info(f"MarketDataAgent: Updated {len(state.market_data)} symbols")

        # Cleanup: Close IBKR provider session if it exists
        if self.ibkr_provider:
            try:
                await self.ibkr_provider.close()
            except Exception as e:
                error_msg = f"Error closing IBKR provider: {e}"
                logger.warning(error_msg, exc_info=True)
                # Don't add to state.errors as this is cleanup, not critical

        return state

    async def _fetch_symbol_data(self, symbol: str) -> Optional[MarketData]:
        """
        Fetch data for a single symbol from IBKR provider.
        
        Raises:
            RuntimeError: If IBKR provider fails or is unavailable
        """
        if not self.ibkr_provider:
            raise RuntimeError(
                f"Cannot fetch data for {symbol}: IBKR provider is not initialized. "
                f"Please check your IB Gateway connection settings."
            )
        
        try:
            data = await self.ibkr_provider.get_latest_bar(symbol)
            if data:
                logger.debug(f"Successfully fetched IBKR data for {symbol}")
                return self._convert_to_market_data(symbol, data)
            else:
                # No data returned - could be market closed, contract expired, or connection issue
                logger.warning(
                    f"IBKR provider returned no data for {symbol}. "
                    f"This may indicate: market is closed, contract expired, or IB Gateway connection issue. "
                    f"Service will continue but cannot generate signals without market data."
                )
                # Don't raise error - let the service continue, it will just skip this symbol
                return None
        except Exception as e:
            error_msg = (
                f"Failed to fetch data for {symbol} from IBKR provider: {e}. "
                f"Please check your IB Gateway connection and ensure it's running with API enabled."
            )
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e

    def _convert_dataframe_to_market_data(
        self, symbol: str, df: pd.DataFrame
    ) -> MarketData:
        """Convert pandas DataFrame row to MarketData."""
        latest = df.iloc[-1]

        return MarketData(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            open=float(latest.get("Open", latest.get("open", 0))),
            high=float(latest.get("High", latest.get("high", 0))),
            low=float(latest.get("Low", latest.get("low", 0))),
            close=float(latest.get("Close", latest.get("close", 0))),
            volume=float(latest.get("Volume", latest.get("volume", 0))),
            vwap=float(latest.get("VWAP", latest.get("vwap", 0)))
            if "VWAP" in latest or "vwap" in latest
            else None,
        )

    def _convert_to_market_data(self, symbol: str, data: Dict) -> MarketData:
        """
        Convert dict data to MarketData with normalization.
        
        Ensures consistent format: (timestamp, symbol, price, volume).
        Normalizes data from different sources to common format.
        """
        # Normalize timestamp
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except Exception:
                timestamp = datetime.now(timezone.utc)
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.now(timezone.utc)
        
        # Normalize price (use close as primary price)
        price = float(data.get("close") or data.get("last") or data.get("price", 0))
        
        # Normalize volume
        volume = float(data.get("volume") or data.get("quoteVolume") or data.get("baseVolume", 0))
        
        return MarketData(
            symbol=symbol,
            timestamp=timestamp,
            open=float(data.get("open", price)) if data.get("open") else price,
            high=float(data.get("high", price)) if data.get("high") else price,
            low=float(data.get("low", price)) if data.get("low") else price,
            close=price,
            volume=volume,
            vwap=float(data.get("vwap")) if data.get("vwap") else None,
            bid=float(data.get("bid")) if data.get("bid") else None,
            ask=float(data.get("ask")) if data.get("ask") else None,
            bid_size=float(data.get("bid_size") or data.get("bidVolume")) if data.get("bid_size") or data.get("bidVolume") else None,
            ask_size=float(data.get("ask_size") or data.get("askVolume")) if data.get("ask_size") or data.get("askVolume") else None,
            funding_rate=float(data.get("funding_rate")) if data.get("funding_rate") else None,
            open_interest=float(data.get("open_interest")) if data.get("open_interest") else None,
            metadata=data.get("metadata", {}),
        )

    # WebSocket methods removed - system uses IBKR Gateway API only

    def get_latest_data(self, symbol: str) -> Optional[MarketData]:
        """
        Get latest cached data for a symbol (synchronous interface).
        
        Returns cached MarketData if available, otherwise None.
        """
        if symbol in self.data_buffers and self.data_buffers[symbol]:
            return self.data_buffers[symbol][-1]
        return None
    
    def fetch_live_data_sync(self, state: TradingState) -> TradingState:
        """
        Synchronous interface for fetching live data.
        
        Uses asyncio.run() to execute async fetch_live_data.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(self.fetch_live_data(state))
