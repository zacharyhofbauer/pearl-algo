"""
Bybit Broker - Crypto perpetual contracts via ccxt.

Uses ccxt.pro for WebSocket + REST API access to Bybit unified margin.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Optional

import ccxt
import ccxt.pro as ccxtpro
import logging

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class BybitBroker(Broker):
    """
    Bybit broker adapter using ccxt for crypto perpetual contracts.
    
    Supports unified margin and WebSocket streaming via ccxt.pro.
    """
    
    def __init__(
        self,
        portfolio: Portfolio,
        config: Optional[BrokerConfig] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        testnet: bool = False,
        unified_margin: bool = True,
    ):
        super().__init__(portfolio, config)
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.unified_margin = unified_margin
        
        # Initialize ccxt exchange
        self.exchange = ccxt.bybit({
            "apiKey": api_key or "",
            "secret": api_secret or "",
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",  # Perpetual contracts
                "test": testnet,
                "unifiedMargin": unified_margin,
            },
        })
        
        # WebSocket exchange (for streaming)
        self.ws_exchange: Optional[ccxtpro.bybit] = None
        if api_key and api_secret:
            try:
                self.ws_exchange = ccxtpro.bybit({
                    "apiKey": api_key,
                    "secret": api_secret,
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "swap",
                        "test": testnet,
                        "unifiedMargin": unified_margin,
                    },
                })
            except Exception as e:
                logger.warning(f"Failed to initialize WebSocket exchange: {e}")
        
        logger.info(f"BybitBroker initialized: testnet={testnet}, unified_margin={unified_margin}")
    
    def submit_order(self, order: OrderEvent) -> str:
        """
        Submit order to Bybit.
        
        Returns order ID.
        """
        try:
            # Normalize symbol for Bybit (e.g., BTCUSDT -> BTC/USDT:USDT)
            symbol = self._normalize_symbol(order.symbol)
            
            # Map order type
            order_type_map = {
                "MKT": "market",
                "LMT": "limit",
                "STP": "stop",
                "STP_LMT": "stop_limit",
            }
            bybit_order_type = order_type_map.get(order.order_type, "market")
            
            # Map side
            side = order.side.lower()  # buy or sell
            
            # Prepare order parameters
            params = {
                "symbol": symbol,
                "type": bybit_order_type,
                "side": side,
                "amount": float(order.quantity),
            }
            
            # Add price for limit orders
            if bybit_order_type in ["limit", "stop_limit"]:
                params["price"] = float(order.limit_price)
            
            # Add stop price for stop orders
            if bybit_order_type in ["stop", "stop_limit"]:
                params["stopPrice"] = float(order.limit_price)
            
            # Submit order
            if self.testnet:
                logger.info(f"[PAPER] Submitting order to Bybit testnet: {params}")
                # In paper mode, simulate order
                order_id = f"bybit_test_{datetime.now().timestamp()}"
            else:
                result = self.exchange.create_order(**params)
                order_id = result.get("id", result.get("orderId", ""))
            
            logger.info(f"Order submitted to Bybit: {order_id}")
            return str(order_id)
        
        except Exception as e:
            logger.error(f"Failed to submit order to Bybit: {e}", exc_info=True)
            raise
    
    def cancel_order(self, order_id: str) -> None:
        """Cancel an order."""
        try:
            # Bybit requires symbol, but base class doesn't provide it
            # We'll need to track orders or use a different approach
            result = self.exchange.cancel_order(order_id)
            logger.info(f"Order {order_id} canceled")
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise
    
    def sync_positions(self) -> Dict[str, float]:
        """Sync current positions; returns symbol -> quantity."""
        try:
            positions = self.exchange.fetch_positions()
            result = {}
            
            for pos in positions:
                symbol = pos.get("symbol", "")
                contracts = float(pos.get("contracts", 0))
                if symbol and contracts != 0:
                    result[symbol] = contracts
            
            return result
        except Exception as e:
            logger.error(f"Failed to sync positions from Bybit: {e}")
            return {}
    
    def fetch_fills(self, since: Optional[datetime] = None) -> list[FillEvent]:
        """
        Fetch filled orders from Bybit.
        
        Returns list of FillEvent objects.
        """
        fills = []
        
        try:
            # Fetch trades
            trades = self.exchange.fetch_my_trades()
            
            for trade in trades:
                # Check if trade is after 'since' timestamp
                if since:
                    trade_time = datetime.fromtimestamp(
                        trade.get("timestamp", 0) / 1000
                    )
                    if trade_time <= since:
                        continue
                
                # Create FillEvent
                fill = FillEvent(
                    timestamp=datetime.fromtimestamp(
                        trade.get("timestamp", 0) / 1000
                    ),
                    symbol=trade.get("symbol", ""),
                    side=trade.get("side", "").upper(),
                    quantity=float(trade.get("amount", 0)),
                    price=float(trade.get("price", 0)),
                    commission=float(trade.get("fee", {}).get("cost", 0)),
                )
                fills.append(fill)
        
        except Exception as e:
            logger.error(f"Failed to fetch fills from Bybit: {e}")
        
        return fills
    
    def get_positions(self) -> Dict[str, Dict]:
        """Get current positions from Bybit."""
        try:
            positions = self.exchange.fetch_positions()
            result = {}
            
            for pos in positions:
                symbol = pos.get("symbol", "")
                if symbol and float(pos.get("contracts", 0)) != 0:
                    result[symbol] = {
                        "size": float(pos.get("contracts", 0)),
                        "entry_price": float(pos.get("entryPrice", 0)),
                        "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                    }
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to fetch positions from Bybit: {e}")
            return {}
    
    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol for Bybit format.
        
        Converts BTCUSDT -> BTC/USDT:USDT for perpetual contracts.
        """
        # If already in correct format, return as is
        if "/" in symbol or ":" in symbol:
            return symbol
        
        # Try to convert (e.g., BTCUSDT -> BTC/USDT:USDT)
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USDT:USDT"
        
        return symbol

