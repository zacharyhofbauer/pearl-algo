"""
WebSocket Data Provider for real-time market data streaming.

Supports multiple brokers via ccxt.pro for WebSocket connections.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import ccxt.pro as ccxtpro
from loguru import logger

logger = logging.getLogger(__name__)


class WebSocketDataProvider:
    """
    WebSocket provider for real-time market data.
    
    Uses ccxt.pro for Bybit/Binance, with extensibility for other brokers.
    """
    
    def __init__(
        self,
        broker: str,
        symbols: List[str],
        config: Optional[Dict] = None,
    ):
        self.broker = broker.lower()
        self.symbols = symbols
        self.config = config or {}
        
        self.exchange = None
        self.streams: Dict[str, any] = {}
        self.data_cache: Dict[str, Dict] = {}
        self.running = False
        
        self._initialize_exchange()
    
    def _initialize_exchange(self) -> None:
        """Initialize ccxt exchange for WebSocket streaming."""
        try:
            if self.broker == "bybit":
                api_key = self.config.get("broker", {}).get("bybit", {}).get("api_key")
                api_secret = self.config.get("broker", {}).get("bybit", {}).get("api_secret")
                testnet = self.config.get("broker", {}).get("bybit", {}).get("testnet", False)
                
                self.exchange = ccxtpro.bybit({
                    "apiKey": api_key or "",
                    "secret": api_secret or "",
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "swap",  # Perpetual contracts
                        "test": testnet,
                    },
                })
                logger.info("Bybit WebSocket exchange initialized")
            
            elif self.broker == "binance":
                api_key = self.config.get("broker", {}).get("binance", {}).get("api_key")
                api_secret = self.config.get("broker", {}).get("binance", {}).get("api_secret")
                
                self.exchange = ccxtpro.binance({
                    "apiKey": api_key or "",
                    "secret": api_secret or "",
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "future",  # Perpetual contracts
                    },
                })
                logger.info("Binance WebSocket exchange initialized")
            
            else:
                logger.warning(f"WebSocket not supported for broker: {self.broker}")
                self.exchange = None
        
        except Exception as e:
            logger.error(f"Failed to initialize WebSocket exchange: {e}", exc_info=True)
            self.exchange = None
    
    async def start_stream(self) -> None:
        """Start WebSocket streaming for all symbols."""
        if not self.exchange:
            logger.warning("No exchange initialized, cannot start stream")
            return
        
        self.running = True
        
        # Start streaming for each symbol
        tasks = []
        for symbol in self.symbols:
            task = asyncio.create_task(self._stream_symbol(symbol))
            tasks.append(task)
        
        logger.info(f"Started WebSocket streams for {len(self.symbols)} symbols")
        
        # Wait for all streams (they run indefinitely)
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in WebSocket streams: {e}", exc_info=True)
    
    async def stop_stream(self) -> None:
        """Stop WebSocket streaming."""
        self.running = False
        
        # Close all streams
        for symbol, stream in self.streams.items():
            try:
                await stream.close()
            except Exception as e:
                logger.warning(f"Error closing stream for {symbol}: {e}")
        
        self.streams.clear()
        
        # Close exchange
        if self.exchange:
            try:
                await self.exchange.close()
            except Exception as e:
                logger.warning(f"Error closing exchange: {e}")
        
        logger.info("WebSocket streams stopped")
    
    async def _stream_symbol(self, symbol: str) -> None:
        """Stream data for a single symbol."""
        if not self.exchange:
            return
        
        try:
            # Normalize symbol for exchange
            normalized_symbol = self._normalize_symbol(symbol)
            
            # Subscribe to ticker (OHLCV updates)
            while self.running:
                try:
                    ticker = await self.exchange.watch_ticker(normalized_symbol)
                    
                    # Update cache
                    self.data_cache[symbol] = {
                        "timestamp": datetime.now(timezone.utc),
                        "open": ticker.get("open"),
                        "high": ticker.get("high"),
                        "low": ticker.get("low"),
                        "close": ticker.get("last") or ticker.get("close"),
                        "volume": ticker.get("quoteVolume") or ticker.get("volume"),
                        "bid": ticker.get("bid"),
                        "ask": ticker.get("ask"),
                        "bid_size": ticker.get("bidVolume"),
                        "ask_size": ticker.get("askVolume"),
                    }
                    
                    # Also subscribe to order book if available
                    # orderbook = await self.exchange.watch_order_book(normalized_symbol)
                    # Can add order book data to cache if needed
                
                except Exception as e:
                    logger.error(f"Error streaming {symbol}: {e}")
                    await asyncio.sleep(5)  # Wait before retry
        
        except Exception as e:
            logger.error(f"Stream error for {symbol}: {e}", exc_info=True)
    
    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol for exchange format."""
        # For Bybit/Binance, symbols are like BTC/USDT:USDT
        if self.broker in ["bybit", "binance"]:
            # If symbol is already in correct format, return as is
            if "/" in symbol or ":" in symbol:
                return symbol
            # Otherwise, try to convert (e.g., BTCUSDT -> BTC/USDT:USDT)
            if symbol.endswith("USDT"):
                base = symbol[:-4]
                return f"{base}/USDT:USDT"
            return symbol
        return symbol
    
    async def get_latest_data(self, symbol: str) -> Optional[Dict]:
        """Get latest cached data for a symbol."""
        return self.data_cache.get(symbol)

