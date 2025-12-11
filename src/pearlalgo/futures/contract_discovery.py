"""
Futures Contract Discovery

Discovers active futures contracts for base symbols (ES, NQ) using Massive API.
Handles contract rollover and caching.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    from massive import RESTClient
except ImportError:
    RESTClient = None
    logger.warning("massive package not installed. Install with: pip install massive")


class ContractDiscovery:
    """
    Discovers and caches active futures contracts.
    
    Queries Massive API for active contracts and caches results
    with automatic refresh on expiration.
    """
    
    def __init__(
        self,
        api_key: str,
        cache_ttl_hours: int = 4,
        client: Optional[RESTClient] = None,
    ):
        """
        Initialize contract discovery.
        
        Args:
            api_key: Massive API key
            cache_ttl_hours: Cache TTL in hours (default: 4)
            client: Optional RESTClient instance (if None, creates new)
        """
        if RESTClient is None:
            raise ImportError(
                "massive package is required. Install with: pip install massive"
            )
        
        self.api_key = api_key
        self.client = client or RESTClient(api_key=api_key)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        
        # Cache: symbol -> (contract_code, expiration_time)
        self._cache: Dict[str, tuple[str, datetime]] = {}
        
        logger.info(f"ContractDiscovery initialized with {cache_ttl_hours}h cache TTL")
    
    async def get_active_contract(self, symbol: str) -> str:
        """
        Get active contract code for a base symbol.
        
        Args:
            symbol: Base futures symbol (e.g., 'ES', 'NQ')
            
        Returns:
            Active contract code (e.g., 'ESU5', 'NQU5')
        """
        # Check cache first
        if symbol in self._cache:
            contract_code, expiration = self._cache[symbol]
            if datetime.now(timezone.utc) < expiration:
                logger.debug(f"Cache hit for {symbol}: {contract_code}")
                return contract_code
            else:
                logger.debug(f"Cache expired for {symbol}, refreshing...")
        
        # Query Massive API
        try:
            contract_code = await self._query_active_contract(symbol)
            
            # Cache with TTL (expires 4 hours before contract expiration or cache TTL, whichever is earlier)
            expiration = datetime.now(timezone.utc) + self.cache_ttl
            self._cache[symbol] = (contract_code, expiration)
            
            logger.info(f"Resolved {symbol} to active contract {contract_code}")
            return contract_code
            
        except Exception as e:
            logger.error(f"Error discovering contract for {symbol}: {e}")
            # Fallback: return symbol as-is
            return symbol
    
    async def _query_active_contract(self, symbol: str) -> str:
        """
        Query Massive API for active contract.
        
        Args:
            symbol: Base futures symbol
            
        Returns:
            Active contract code
        """
        try:
            # Use list_futures_contracts (returns iterator, sync call)
            contracts = []
            try:
                # Run in executor since we're in async context
                import asyncio
                loop = asyncio.get_event_loop()
                contracts_iter = await loop.run_in_executor(
                    None,
                    lambda: self.client.list_futures_contracts(
                        product_code=symbol,
                        active="true",  # String "true" not boolean
                        limit=100,
                        sort="expiration_date"
                    )
                )
                for contract in contracts_iter:
                    contracts.append(contract)
                    # Only need first few
                    if len(contracts) >= 10:
                        break
            except Exception as e:
                logger.warning(f"Error iterating contracts for {symbol}: {e}")
            
            if contracts:
                # First contract has nearest expiration (sorted)
                active_contract = contracts[0]
                contract_code = getattr(active_contract, 'ticker', symbol)
                
                # Parse expiration date
                expiration_str = getattr(active_contract, 'expiration_date', None)
                if expiration_str:
                    try:
                        if isinstance(expiration_str, str):
                            expiration_date = datetime.fromisoformat(
                                expiration_str.replace("Z", "+00:00")
                            )
                        else:
                            expiration_date = expiration_str
                        # Cache until 4 hours before expiration
                        cache_expiration = expiration_date - timedelta(hours=4)
                        # Use earlier of cache TTL or contract expiration
                        now = datetime.now(timezone.utc)
                        final_expiration = min(
                            now + self.cache_ttl,
                            cache_expiration
                        )
                        self._cache[symbol] = (contract_code, final_expiration)
                    except Exception as e:
                        logger.warning(f"Could not parse expiration for {contract_code}: {e}")
                
                return contract_code
            
            # No active contracts found
            logger.warning(f"No active contracts found for {symbol}, using symbol as-is")
            return symbol
            
        except Exception as e:
            logger.error(f"Error querying contracts for {symbol}: {e}")
            raise
    
    async def refresh_contract_cache(self, symbol: Optional[str] = None) -> None:
        """
        Refresh contract cache.
        
        Args:
            symbol: Specific symbol to refresh (if None, refreshes all)
        """
        if symbol:
            if symbol in self._cache:
                del self._cache[symbol]
            await self.get_active_contract(symbol)
        else:
            # Refresh all cached contracts
            symbols = list(self._cache.keys())
            self._cache.clear()
            for sym in symbols:
                try:
                    await self.get_active_contract(sym)
                except Exception as e:
                    logger.warning(f"Failed to refresh contract for {sym}: {e}")
    
    def get_contract_expiration(self, contract_code: str) -> Optional[datetime]:
        """
        Get expiration date for a contract code.
        
        Args:
            contract_code: Contract code (e.g., 'ESU5')
            
        Returns:
            Expiration datetime or None if not found
        """
        # Parse contract code to get expiration
        # Format: ES + month code + year
        # Month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun,
        #               N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
        if len(contract_code) < 3:
            return None
        
        try:
            month_codes = {
                'F': 1, 'G': 2, 'H': 3, 'J': 4, 'K': 5, 'M': 6,
                'N': 7, 'Q': 8, 'U': 9, 'V': 10, 'X': 11, 'Z': 12
            }
            
            # Extract month and year from contract code
            # E.g., ESU5 -> U=Sep, 5=2025
            month_code = contract_code[-2]
            year_code = contract_code[-1]
            
            if month_code not in month_codes:
                return None
            
            month = month_codes[month_code]
            # Year code: 0-9 = 2020-2029, but we'll assume current decade
            year = 2020 + int(year_code) if year_code.isdigit() else None
            
            if year is None:
                return None
            
            # Futures typically expire on third Friday of expiration month
            # For simplicity, use last day of month
            from calendar import monthrange
            last_day = monthrange(year, month)[1]
            expiration = datetime(year, month, last_day, tzinfo=timezone.utc)
            
            return expiration
            
        except Exception as e:
            logger.warning(f"Could not parse expiration from contract code {contract_code}: {e}")
            return None
    
    def clear_cache(self) -> None:
        """Clear all cached contracts."""
        self._cache.clear()
        logger.info("Contract cache cleared")
    
    def get_cache_status(self) -> Dict[str, Dict]:
        """
        Get cache status for all symbols.
        
        Returns:
            Dictionary mapping symbols to cache info
        """
        status = {}
        now = datetime.now(timezone.utc)
        
        for symbol, (contract_code, expiration) in self._cache.items():
            status[symbol] = {
                "contract_code": contract_code,
                "expiration": expiration.isoformat(),
                "is_valid": now < expiration,
                "time_until_expiry": str(expiration - now) if now < expiration else "expired",
            }
        
        return status
