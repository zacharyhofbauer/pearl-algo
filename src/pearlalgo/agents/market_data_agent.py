"""
Market Data Agent - Streams live market data via WebSockets with REST fallback.

This agent is responsible for:
- WebSocket streaming for OHLCV, order book, funding rates (crypto), OI
- Polygon.io primary provider for US futures
- Dummy data provider for testing/development
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
from pearlalgo.data_providers.dummy_provider import DummyDataProvider
from pearlalgo.data_providers.polygon_provider import PolygonDataProvider
# WebSocket provider removed - system uses Polygon REST API only

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
        config: Optional[Dict] = None,
    ):
        self.symbols = symbols
        self.config = config or {}

        # Initialize data providers
        self.polygon_provider: Optional[PolygonDataProvider] = None
        self.dummy_provider: Optional[DummyDataProvider] = None

        # Data buffers (for caching normalized data)
        self.data_buffers: Dict[str, List[MarketData]] = {symbol: [] for symbol in symbols}

        # Initialize Polygon provider
        self._initialize_providers()

        logger.info(f"MarketDataAgent initialized: symbols={symbols}")

    def _initialize_providers(self) -> None:
        """Initialize Polygon data provider."""
        try:
            import os
            
            # Initialize Polygon provider (primary data source)
            # Try to get API key from config or environment
            polygon_api_key = (
                self.config.get("data", {})
                .get("fallback", {})
                .get("polygon", {})
                .get("api_key")
            )
            if not polygon_api_key:
                # Try environment variable
                polygon_api_key = os.getenv("POLYGON_API_KEY")
            
            if polygon_api_key:
                try:
                    self.polygon_provider = PolygonDataProvider(api_key=polygon_api_key)
                    logger.info("Polygon.io provider initialized")
                except Exception as e:
                    logger.warning(f"Polygon provider initialization failed: {e}")
            else:
                logger.warning("Polygon API key not found - Polygon provider disabled. Set POLYGON_API_KEY environment variable.")

            # Initialize dummy provider as fallback (enabled by default for testing)
            dummy_mode_env = os.getenv("PEARLALGO_DUMMY_MODE", "").lower()
            if dummy_mode_env in ("true", "1", "yes"):
                dummy_mode = True
            elif dummy_mode_env in ("false", "0", "no"):
                dummy_mode = False
            else:
                # Default to True if not explicitly set (allows testing without API keys)
                dummy_mode = True
            
            if dummy_mode:
                try:
                    self.dummy_provider = DummyDataProvider(symbols=self.symbols)
                    logger.info("Dummy data provider initialized (for testing/development)")
                except Exception as e:
                    logger.warning(f"Dummy provider initialization failed: {e}")
            else:
                logger.debug("Dummy provider disabled (dummy_mode=False)")

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

        logger.info(f"MarketDataAgent: Updated {len(state.market_data)} symbols")

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
        Tries Polygon first, then Dummy provider as fallback.
        """
        # Try Polygon provider (primary data source)
        if self.polygon_provider:
            try:
                data = await self.polygon_provider.get_latest_bar(symbol)
                if data:
                    logger.debug(f"Successfully fetched Polygon data for {symbol}")
                    return self._convert_to_market_data(symbol, data)
            except Exception as e:
                logger.debug(f"Polygon fetch failed for {symbol}: {e}")

        # Final fallback: Dummy provider (for testing/development)
        if self.dummy_provider:
            try:
                data = self.dummy_provider.get_latest_bar(symbol)
                if data:
                    logger.info(f"Using dummy data for {symbol} (all real sources failed or unavailable)")
                    return self._convert_to_market_data(symbol, data)
            except Exception as e:
                logger.debug(f"Dummy provider failed for {symbol}: {e}")

        # If we get here, all providers failed
        logger.warning(
            f"All data sources failed for {symbol}. "
            f"Tried: Polygon, Dummy. "
            f"To enable dummy data for testing, set PEARLALGO_DUMMY_MODE=true in .env. "
            f"To use Polygon, set POLYGON_API_KEY in .env."
        )
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

    # WebSocket methods removed - system uses Polygon REST API only

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
