"""
Alpaca Broker - US futures via REST API.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Optional

import requests
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


class AlpacaBroker(Broker):
    """
    Alpaca broker adapter for US futures.
    
    Uses Alpaca REST API for order execution.
    """
    
    def __init__(
        self,
        portfolio: Portfolio,
        config: Optional[BrokerConfig] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(portfolio, config)
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url or "https://paper-api.alpaca.markets"
        
        # Determine if paper trading
        self.is_paper = "paper" in self.base_url.lower()
        
        # Session for API requests
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": api_key or "",
            "APCA-API-SECRET-KEY": api_secret or "",
        })
        
        logger.info(f"AlpacaBroker initialized: base_url={self.base_url}, paper={self.is_paper}")
    
    def submit_order(self, order: OrderEvent) -> str:
        """
        Submit order to Alpaca.
        
        Returns order ID.
        """
        try:
            # Alpaca uses different symbol format for futures
            symbol = self._normalize_symbol(order.symbol)
            
            # Map order type
            order_type_map = {
                "MKT": "market",
                "LMT": "limit",
                "STP": "stop",
                "STP_LMT": "stop_limit",
            }
            alpaca_order_type = order_type_map.get(order.order_type, "market")
            
            # Map side
            side = order.side.lower()  # buy or sell
            
            # Prepare order payload
            payload = {
                "symbol": symbol,
                "qty": str(order.quantity),
                "side": side,
                "type": alpaca_order_type,
                "time_in_force": "day",
            }
            
            # Add price for limit orders
            if alpaca_order_type in ["limit", "stop_limit"]:
                payload["limit_price"] = str(order.limit_price)
            
            # Add stop price for stop orders
            if alpaca_order_type in ["stop", "stop_limit"]:
                payload["stop_price"] = str(order.limit_price)
            
            # Submit order
            if self.is_paper:
                logger.info(f"[PAPER] Submitting order to Alpaca: {payload}")
                # In paper mode, simulate order
                order_id = f"alpaca_paper_{datetime.now().timestamp()}"
            else:
                response = self.session.post(
                    f"{self.base_url}/v2/orders",
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                order_id = result.get("id", "")
            
            logger.info(f"Order submitted to Alpaca: {order_id}")
            return str(order_id)
        
        except Exception as e:
            logger.error(f"Failed to submit order to Alpaca: {e}", exc_info=True)
            raise
    
    def cancel_order(self, order_id: str) -> None:
        """Cancel an order."""
        try:
            response = self.session.delete(f"{self.base_url}/v2/orders/{order_id}")
            response.raise_for_status()
            logger.info(f"Order {order_id} canceled")
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise
    
    def sync_positions(self) -> Dict[str, float]:
        """Sync current positions; returns symbol -> quantity."""
        try:
            response = self.session.get(f"{self.base_url}/v2/positions")
            response.raise_for_status()
            positions = response.json()
            
            result = {}
            for pos in positions:
                symbol = pos.get("symbol", "")
                qty = float(pos.get("qty", 0))
                if symbol and qty != 0:
                    result[symbol] = qty
            
            return result
        except Exception as e:
            logger.error(f"Failed to sync positions from Alpaca: {e}")
            return {}
    
    def fetch_fills(self, since: Optional[datetime] = None) -> list[FillEvent]:
        """
        Fetch filled orders from Alpaca.
        
        Returns list of FillEvent objects.
        """
        fills = []
        
        try:
            # Fetch filled orders
            params = {"status": "filled"}
            if since:
                params["after"] = since.isoformat()
            
            response = self.session.get(
                f"{self.base_url}/v2/orders",
                params=params,
            )
            response.raise_for_status()
            orders = response.json()
            
            for order in orders:
                # Get fills for this order
                fills_response = self.session.get(
                    f"{self.base_url}/v2/orders/{order['id']}/fills",
                )
                if fills_response.status_code == 200:
                    order_fills = fills_response.json()
                    for fill_data in order_fills:
                        fill = FillEvent(
                            timestamp=datetime.fromisoformat(
                                fill_data.get("timestamp", "").replace("Z", "+00:00")
                            ),
                            symbol=order.get("symbol", ""),
                            side=order.get("side", "").upper(),
                            quantity=float(fill_data.get("qty", 0)),
                            price=float(fill_data.get("price", 0)),
                            commission=float(fill_data.get("commission", 0)),
                        )
                        fills.append(fill)
        
        except Exception as e:
            logger.error(f"Failed to fetch fills from Alpaca: {e}")
        
        return fills
    
    def get_positions(self) -> Dict[str, Dict]:
        """Get current positions from Alpaca."""
        try:
            response = self.session.get(f"{self.base_url}/v2/positions")
            response.raise_for_status()
            positions = response.json()
            
            result = {}
            for pos in positions:
                symbol = pos.get("symbol", "")
                if symbol and float(pos.get("qty", 0)) != 0:
                    result[symbol] = {
                        "size": float(pos.get("qty", 0)),
                        "entry_price": float(pos.get("avg_entry_price", 0)),
                        "unrealized_pnl": float(pos.get("unrealized_pl", 0)),
                    }
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to fetch positions from Alpaca: {e}")
            return {}
    
    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol for Alpaca format.
        
        Alpaca uses different formats for futures (e.g., /ES for E-mini S&P 500).
        """
        # Alpaca futures symbols are typically like /ES, /NQ, etc.
        # This is a simplified mapping
        futures_map = {
            "ES": "/ES",
            "NQ": "/NQ",
            "YM": "/YM",
            "RTY": "/RTY",
            "CL": "/CL",
            "GC": "/GC",
        }
        
        return futures_map.get(symbol.upper(), symbol)

