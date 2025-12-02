"""
Market Data Agent - Streams live market data via WebSockets with REST fallback.

This agent is responsible for:
- WebSocket streaming for OHLCV, order book, funding rates (crypto), OI
- IBKR REST fallback for futures
- Polygon.io fallback for US futures
- Real-time data aggregation and normalization
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import logging

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
from pearlalgo.data_providers.polygon_provider import PolygonDataProvider
from pearlalgo.data_providers.websocket_provider import WebSocketDataProvider

logger = logging.getLogger(__name__)


class MarketDataAgent:
    """
    Market Data Agent for LangGraph workflow.
    
    Fetches and streams real-time market data for all configured symbols.
    Uses WebSocket when available, falls back to REST APIs.
    """
    
    def __init__(
        self,
        symbols: List[str],
        broker: str = "ibkr",
        config: Optional[Dict] = None,
    ):
        self.symbols = symbols
        self.broker = broker.lower()
        self.config = config or {}
        
        # Initialize data providers
        self.websocket_provider: Optional[WebSocketDataProvider] = None
        self.rest_provider = None
        self.polygon_provider: Optional[PolygonDataProvider] = None
        
        # Data buffers
        self.data_buffers: Dict[str, List[MarketData]] = {}
        
        # Initialize providers based on broker
        self._initialize_providers()
        
        logger.info(
            f"MarketDataAgent initialized: broker={broker}, symbols={symbols}"
        )
    
    def _initialize_providers(self) -> None:
        """Initialize data providers based on broker configuration."""
        try:
            # Try WebSocket provider first (if enabled)
            websocket_enabled = self.config.get("data", {}).get(
                "websocket", {}
            ).get("enabled", True)
            
            if websocket_enabled:
                try:
                    self.websocket_provider = WebSocketDataProvider(
                        broker=self.broker,
                        symbols=self.symbols,
                        config=self.config,
                    )
                    logger.info("WebSocket provider initialized")
                except Exception as e:
                    logger.warning(f"WebSocket provider failed to initialize: {e}")
            
            # Initialize REST provider based on broker
            if self.broker == "ibkr":
                settings = get_settings()
                self.rest_provider = IBKRDataProvider(settings=settings)
                logger.info("IBKR REST provider initialized")
            elif self.broker == "bybit":
                # Bybit will be handled via ccxt in websocket provider
                pass
            elif self.broker == "alpaca":
                # Alpaca will be handled via REST API
                pass
            
            # Initialize Polygon.io as fallback
            polygon_api_key = self.config.get("data", {}).get(
                "fallback", {}
            ).get("polygon", {}).get("api_key")
            if polygon_api_key:
                try:
                    self.polygon_provider = PolygonDataProvider(
                        api_key=polygon_api_key
                    )
                    logger.info("Polygon.io provider initialized as fallback")
                except Exception as e:
                    logger.warning(f"Polygon.io provider failed: {e}")
        
        except Exception as e:
            logger.error(f"Error initializing providers: {e}", exc_info=True)
    
    async def fetch_live_data(
        self, state: TradingState
    ) -> TradingState:
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
                    state.market_data[symbol] = market_data
                    state = add_agent_reasoning(
                        state,
                        "market_data_agent",
                        f"Updated market data for {symbol}: ${market_data.close:.2f}",
                        level="debug",
                        data={"symbol": symbol, "price": market_data.close},
                    )
            except Exception as e:
                error_msg = f"Error fetching data for {symbol}: {e}"
                logger.error(error_msg, exc_info=True)
                state.errors.append(error_msg)
                state = add_agent_reasoning(
                    state,
                    "market_data_agent",
                    error_msg,
                    level="error",
                    data={"symbol": symbol, "error": str(e)},
                )
        
        # Update timestamp
        state.timestamp = datetime.now(timezone.utc)
        
        logger.info(
            f"MarketDataAgent: Updated {len(state.market_data)} symbols"
        )
        
        # Cleanup: Close Polygon provider session if it exists
        if self.polygon_provider:
            try:
                await self.polygon_provider.close()
            except Exception as e:
                logger.debug(f"Error closing Polygon provider: {e}")
        
        return state
    
    async def _fetch_symbol_data(self, symbol: str) -> Optional[MarketData]:
        """
        Fetch data for a single symbol.
        Tries WebSocket first, then REST, then Polygon fallback.
        """
        # Try WebSocket first
        if self.websocket_provider:
            try:
                data = await self.websocket_provider.get_latest_data(symbol)
                if data:
                    return self._convert_to_market_data(symbol, data)
            except Exception as e:
                logger.debug(f"WebSocket fetch failed for {symbol}: {e}")
        
        # Try REST provider
        if self.rest_provider:
            try:
                # Fetch recent bars and get latest
                df = self.rest_provider.fetch_historical(
                    symbol,
                    sec_type="FUT",
                    duration="1 D",
                    bar_size="1 min",
                )
                if df is not None and not df.empty:
                    return self._convert_dataframe_to_market_data(symbol, df)
            except Exception as e:
                logger.debug(f"REST fetch failed for {symbol}: {e}")
        
        # Try Polygon fallback
        if self.polygon_provider:
            try:
                data = await self.polygon_provider.get_latest_bar(symbol)
                if data:
                    return self._convert_to_market_data(symbol, data)
            except Exception as e:
                logger.debug(f"Polygon fetch failed for {symbol}: {e}")
        
        logger.warning(f"All data sources failed for {symbol}")
        return None
    
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
    
    def _convert_to_market_data(
        self, symbol: str, data: Dict
    ) -> MarketData:
        """Convert dict data to MarketData."""
        return MarketData(
            symbol=symbol,
            timestamp=data.get("timestamp", datetime.now(timezone.utc)),
            open=float(data.get("open", 0)),
            high=float(data.get("high", 0)),
            low=float(data.get("low", 0)),
            close=float(data.get("close", 0)),
            volume=float(data.get("volume", 0)),
            vwap=data.get("vwap"),
            bid=data.get("bid"),
            ask=data.get("ask"),
            bid_size=data.get("bid_size"),
            ask_size=data.get("ask_size"),
            funding_rate=data.get("funding_rate"),
            open_interest=data.get("open_interest"),
            metadata=data.get("metadata", {}),
        )
    
    async def start_websocket_stream(self) -> None:
        """Start WebSocket streaming (if available)."""
        if self.websocket_provider:
            try:
                await self.websocket_provider.start_stream()
                logger.info("WebSocket stream started")
            except Exception as e:
                logger.error(f"Failed to start WebSocket stream: {e}")
    
    async def stop_websocket_stream(self) -> None:
        """Stop WebSocket streaming."""
        if self.websocket_provider:
            try:
                await self.websocket_provider.stop_stream()
                logger.info("WebSocket stream stopped")
            except Exception as e:
                logger.error(f"Failed to stop WebSocket stream: {e}")
    
    def get_latest_data(self, symbol: str) -> Optional[MarketData]:
        """Get latest cached data for a symbol."""
        # This would be used if we're maintaining a buffer
        # For now, we fetch on-demand
        return None

