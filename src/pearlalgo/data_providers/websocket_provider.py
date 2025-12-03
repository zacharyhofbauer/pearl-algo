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

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

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

        # Reconnection settings
        websocket_config = self.config.get("data", {}).get("websocket", {})
        self.reconnect_delay = websocket_config.get("reconnect_delay", 5)
        self.max_reconnect_attempts = websocket_config.get("max_reconnect_attempts", 10)
        self.reconnect_attempts: Dict[str, int] = {}

        self._initialize_exchange()

    def _initialize_exchange(self) -> None:
        """Initialize ccxt exchange for WebSocket streaming."""
        try:
            if self.broker == "bybit":
                api_key = self.config.get("broker", {}).get("bybit", {}).get("api_key")
                api_secret = (
                    self.config.get("broker", {}).get("bybit", {}).get("api_secret")
                )
                testnet = (
                    self.config.get("broker", {}).get("bybit", {}).get("testnet", False)
                )

                self.exchange = ccxtpro.bybit(
                    {
                        "apiKey": api_key or "",
                        "secret": api_secret or "",
                        "enableRateLimit": True,
                        "options": {
                            "defaultType": "swap",  # Perpetual contracts
                            "test": testnet,
                        },
                    }
                )
                logger.info("Bybit WebSocket exchange initialized")

            elif self.broker == "binance":
                api_key = (
                    self.config.get("broker", {}).get("binance", {}).get("api_key")
                )
                api_secret = (
                    self.config.get("broker", {}).get("binance", {}).get("api_secret")
                )

                self.exchange = ccxtpro.binance(
                    {
                        "apiKey": api_key or "",
                        "secret": api_secret or "",
                        "enableRateLimit": True,
                        "options": {
                            "defaultType": "future",  # Perpetual contracts
                        },
                    }
                )
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
        """Stream data for a single symbol with reconnection logic."""
        if not self.exchange:
            return

            normalized_symbol = self._normalize_symbol(symbol)
        self.reconnect_attempts[symbol] = 0

            while self.running:
                try:
                # Subscribe to ticker (OHLCV updates)
                    ticker = await self.exchange.watch_ticker(normalized_symbol)

                # Reset reconnect attempts on successful data
                self.reconnect_attempts[symbol] = 0

                # Normalize and update cache
                normalized_data = self._normalize_ticker_data(ticker)
                self.data_cache[symbol] = normalized_data

                except Exception as e:
                self.reconnect_attempts[symbol] = self.reconnect_attempts.get(symbol, 0) + 1
                
                if self.reconnect_attempts[symbol] >= self.max_reconnect_attempts:
                    logger.error(
                        f"Max reconnection attempts ({self.max_reconnect_attempts}) reached for {symbol}. "
                        f"Stopping stream."
                    )
                    break
                
                logger.warning(
                    f"Error streaming {symbol} (attempt {self.reconnect_attempts[symbol]}/{self.max_reconnect_attempts}): {e}. "
                    f"Reconnecting in {self.reconnect_delay}s..."
                )
                
                # Wait before reconnecting
                await asyncio.sleep(self.reconnect_delay)
                
                # Try to reinitialize exchange if needed
                if not self.exchange or not self.running:
                    try:
                        self._initialize_exchange()
                        if not self.exchange:
                            logger.error(f"Failed to reinitialize exchange for {symbol}")
                            break
                    except Exception as reinit_error:
                        logger.error(f"Error reinitializing exchange: {reinit_error}")
                        break
    
    def _normalize_ticker_data(self, ticker: Dict) -> Dict:
        """
        Normalize ticker data to consistent format: (timestamp, symbol, price, volume).
        
        Returns normalized dict with consistent field names.
        """
        return {
            "timestamp": datetime.now(timezone.utc),
            "open": float(ticker.get("open", 0)) if ticker.get("open") else None,
            "high": float(ticker.get("high", 0)) if ticker.get("high") else None,
            "low": float(ticker.get("low", 0)) if ticker.get("low") else None,
            "close": float(ticker.get("last") or ticker.get("close", 0)),
            "volume": float(ticker.get("quoteVolume") or ticker.get("volume", 0)),
            "bid": float(ticker.get("bid", 0)) if ticker.get("bid") else None,
            "ask": float(ticker.get("ask", 0)) if ticker.get("ask") else None,
            "bid_size": float(ticker.get("bidVolume", 0)) if ticker.get("bidVolume") else None,
            "ask_size": float(ticker.get("askVolume", 0)) if ticker.get("askVolume") else None,
        }

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
