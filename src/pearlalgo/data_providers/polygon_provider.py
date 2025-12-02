"""
Polygon.io Data Provider for US futures fallback.

Uses Polygon.io free tier API for historical and real-time data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import aiohttp
from loguru import logger

from pearlalgo.data_providers.base import DataProvider

logger = logging.getLogger(__name__)


class PolygonDataProvider(DataProvider):
    """
    Polygon.io data provider for US futures.
    
    Uses free tier API with rate limits.
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.polygon.io"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self) -> None:
        """Close aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def get_latest_bar(self, symbol: str) -> Optional[Dict]:
        """
        Get latest bar for a symbol.
        
        Note: Polygon.io uses different symbol formats.
        For futures, format is like: ES1 (for front month ES contract).
        """
        try:
            session = await self._get_session()
            
            # For futures, we need to use the aggregates endpoint
            # This is a simplified version - in production, you'd resolve the contract
            url = f"{self.base_url}/v2/aggs/ticker/{symbol}/prev"
            params = {"apikey": self.api_key}
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                        result = data["results"][0]
                        return {
                            "timestamp": datetime.fromtimestamp(
                                result["t"] / 1000, tz=timezone.utc
                            ),
                            "open": result["o"],
                            "high": result["h"],
                            "low": result["l"],
                            "close": result["c"],
                            "volume": result["v"],
                            "vwap": result.get("vw"),
                        }
                else:
                    logger.warning(
                        f"Polygon API error for {symbol}: {response.status}"
                    )
        
        except Exception as e:
            logger.error(f"Error fetching Polygon data for {symbol}: {e}")
        
        return None
    
    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> None:
        """
        Fetch historical data (not implemented for async provider).
        
        Use get_latest_bar for real-time data, or implement sync version.
        """
        raise NotImplementedError(
            "Use async get_latest_bar or implement sync fetch_historical"
        )

