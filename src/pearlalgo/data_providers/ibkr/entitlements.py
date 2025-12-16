"""
IBKR Entitlements - Validate market data permissions and account type.

Checks:
- Account type (paper vs live)
- Options data availability
- Real-time quotes enabled
- Historical data accessible
"""

from __future__ import annotations

from typing import Dict, Optional

from ib_insync import IB, Stock

from pearlalgo.utils.logger import logger


class IBKREntitlements:
    """
    Validates IBKR market data entitlements.
    
    Checks what data the account has access to and logs warnings
    for missing entitlements.
    """

    def __init__(self, ib: IB):
        """
        Initialize entitlements checker.
        
        Args:
            ib: IB connection instance
        """
        self.ib = ib
        self._cached_entitlements: Optional[Dict[str, bool]] = None

    async def validate_entitlements(self) -> Dict[str, bool]:
        """
        Validate all market data entitlements.
        
        Returns:
            Dictionary with entitlement status:
                - options_data: True if options data is available
                - realtime_quotes: True if real-time quotes are enabled
                - historical_data: True if historical data is accessible
                - account_type: 'paper' or 'live' (as string in dict)
        """
        if not self.ib.isConnected():
            logger.error("Cannot validate entitlements: not connected to IB Gateway")
            return {
                "options_data": False,
                "realtime_quotes": False,
                "historical_data": False,
                "account_type": "unknown",
            }

        entitlements = {
            "options_data": False,
            "realtime_quotes": False,
            "historical_data": False,
            "account_type": "unknown",
        }

        try:
            # Get account summary to determine account type
            accounts = self.ib.accountSummary()
            if accounts:
                # Check if paper account (usually contains "DU" or "Paper" in account ID)
                account_id = accounts[0].account if accounts else ""
                if "DU" in account_id.upper() or "PAPER" in account_id.upper():
                    entitlements["account_type"] = "paper"
                else:
                    entitlements["account_type"] = "live"
                logger.info(f"Account type detected: {entitlements['account_type']}")
            else:
                logger.warning("Could not determine account type (no account summary)")
                entitlements["account_type"] = "unknown"

            # Test options data by requesting option chain for SPY
            try:
                stock = Stock("SPY", "SMART", "USD")
                chains = self.ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
                if chains and len(chains) > 0:
                    entitlements["options_data"] = True
                    logger.info("Options data: Available")
                else:
                    logger.warning("Options data: Not available (no chains returned)")
            except Exception as e:
                logger.warning(f"Options data: Not available ({e})")

            # Test real-time quotes by requesting market data for SPY
            try:
                stock = Stock("SPY", "SMART", "USD")
                ticker = self.ib.reqMktData(stock, "", False, False)
                # Wait a moment for data
                import time

                time.sleep(0.5)
                if ticker and (ticker.bid or ticker.ask or ticker.last):
                    entitlements["realtime_quotes"] = True
                    logger.info("Real-time quotes: Available")
                    # Cancel the market data request
                    self.ib.cancelMktData(stock)
                else:
                    logger.warning("Real-time quotes: Not available (no data received)")
            except Exception as e:
                logger.warning(f"Real-time quotes: Not available ({e})")

            # Test historical data by requesting a small amount
            try:
                stock = Stock("SPY", "SMART", "USD")
                bars = self.ib.reqHistoricalData(
                    stock,
                    endDateTime="",
                    durationStr="1 D",
                    barSizeSetting="1 hour",
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=1,
                )
                if bars and len(bars) > 0:
                    entitlements["historical_data"] = True
                    logger.info("Historical data: Available")
                else:
                    logger.warning("Historical data: Not available (no bars returned)")
            except Exception as e:
                logger.warning(f"Historical data: Not available ({e})")

            self._cached_entitlements = entitlements
            return entitlements

        except Exception as e:
            logger.error(f"Error validating entitlements: {e}", exc_info=True)
            return entitlements

    def get_cached_entitlements(self) -> Optional[Dict[str, bool]]:
        """Get cached entitlements (if validation was run previously)."""
        return self._cached_entitlements

    def log_entitlement_warnings(self, entitlements: Dict[str, bool]) -> None:
        """
        Log warnings for missing entitlements.
        
        Args:
            entitlements: Entitlements dictionary from validate_entitlements()
        """
        warnings = []

        if not entitlements.get("options_data", False):
            warnings.append(
                "Options data not available. "
                "You may need to subscribe to options data in your IBKR account."
            )

        if not entitlements.get("realtime_quotes", False):
            warnings.append(
                "Real-time quotes not available. "
                "You may need to subscribe to market data in your IBKR account."
            )

        if not entitlements.get("historical_data", False):
            warnings.append(
                "Historical data not available. "
                "You may need to subscribe to historical data in your IBKR account."
            )

        if warnings:
            logger.warning("Market data entitlement warnings:")
            for warning in warnings:
                logger.warning(f"  - {warning}")
        else:
            logger.info("All market data entitlements validated successfully")
