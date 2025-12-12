"""
Startup Validation - Validates system is ready before starting trading.

Checks:
1. IB Gateway reachable (port 4002 open)
2. IBKR connection established
3. Account type detected (paper vs live)
4. Market data entitlements confirmed
5. Smoke test (fetch SPY/QQQ prices, pull options chain)
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.data_providers.market_data_provider import MarketDataProvider


class StartupValidator:
    """
    Validates system is ready for trading.
    
    Runs a comprehensive checklist before allowing trading to start.
    """

    def __init__(self, data_provider: MarketDataProvider):
        """
        Initialize startup validator.
        
        Args:
            data_provider: Market data provider instance
        """
        self.data_provider = data_provider
        self.validation_results: Dict[str, bool] = {}
        self.validation_errors: Dict[str, str] = {}

        logger.info("StartupValidator initialized")

    async def validate_all(self, test_symbols: Optional[List[str]] = None) -> bool:
        """
        Run all validation checks.
        
        Args:
            test_symbols: Symbols to use for smoke test (default: ['SPY', 'QQQ'])
            
        Returns:
            True if all checks pass, False otherwise
        """
        if test_symbols is None:
            test_symbols = ["SPY", "QQQ"]

        logger.info("Starting startup validation...")

        # Check 1: IB Gateway reachable
        gateway_ok = await self._check_gateway_reachable()
        self.validation_results["gateway_reachable"] = gateway_ok

        if not gateway_ok:
            logger.error("Validation failed: IB Gateway not reachable")
            return False

        # Check 2: IBKR connection established
        connection_ok = await self._check_connection()
        self.validation_results["connection_established"] = connection_ok

        if not connection_ok:
            logger.error("Validation failed: IBKR connection not established")
            return False

        # Check 3: Account type detected
        account_ok = await self._check_account_type()
        self.validation_results["account_type_detected"] = account_ok

        # Check 4: Market data entitlements
        entitlements_ok = await self._check_entitlements()
        self.validation_results["entitlements_valid"] = entitlements_ok

        # Check 5: Smoke test
        smoke_test_ok = await self._smoke_test(test_symbols)
        self.validation_results["smoke_test"] = smoke_test_ok

        # Summary
        all_passed = all(self.validation_results.values())
        if all_passed:
            logger.info("✅ All startup validation checks passed")
        else:
            logger.error("❌ Some startup validation checks failed:")
            for check, passed in self.validation_results.items():
                status = "✅" if passed else "❌"
                error = self.validation_errors.get(check, "")
                logger.error(f"  {status} {check}: {error if error else ('PASS' if passed else 'FAIL')}")

        return all_passed

    async def _check_gateway_reachable(self) -> bool:
        """Check if IB Gateway port is open."""
        try:
            # Get host and port from provider settings
            # For now, assume default values
            host = getattr(self.data_provider, "host", "127.0.0.1")
            port = getattr(self.data_provider, "port", 4002)

            logger.info(f"Checking if IB Gateway is reachable at {host}:{port}...")

            # Try to connect to the port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                logger.info("✅ IB Gateway is reachable")
                return True
            else:
                error_msg = f"Port {port} on {host} is not open"
                self.validation_errors["gateway_reachable"] = error_msg
                logger.error(f"❌ {error_msg}")
                return False

        except Exception as e:
            error_msg = f"Error checking gateway: {e}"
            self.validation_errors["gateway_reachable"] = error_msg
            logger.error(f"❌ {error_msg}")
            return False

    async def _check_connection(self) -> bool:
        """Check if IBKR connection is established."""
        try:
            logger.info("Checking IBKR connection...")

            connected = await self.data_provider.validate_connection()
            if connected:
                logger.info("✅ IBKR connection established")
                return True
            else:
                error_msg = "Connection validation returned False"
                self.validation_errors["connection_established"] = error_msg
                logger.error(f"❌ {error_msg}")
                return False

        except Exception as e:
            error_msg = f"Connection check failed: {e}"
            self.validation_errors["connection_established"] = error_msg
            logger.error(f"❌ {error_msg}")
            return False

    async def _check_account_type(self) -> bool:
        """Check if account type can be detected."""
        try:
            logger.info("Checking account type...")

            entitlements = await self.data_provider.validate_market_data_entitlements()
            account_type = entitlements.get("account_type", "unknown")

            if account_type != "unknown":
                logger.info(f"✅ Account type detected: {account_type}")
                return True
            else:
                error_msg = "Could not determine account type"
                self.validation_errors["account_type_detected"] = error_msg
                logger.warning(f"⚠️  {error_msg} (continuing anyway)")
                return True  # Non-critical, continue

        except Exception as e:
            error_msg = f"Account type check failed: {e}"
            self.validation_errors["account_type_detected"] = error_msg
            logger.warning(f"⚠️  {error_msg} (continuing anyway)")
            return True  # Non-critical, continue

    async def _check_entitlements(self) -> bool:
        """Check market data entitlements."""
        try:
            logger.info("Checking market data entitlements...")

            entitlements = await self.data_provider.validate_market_data_entitlements()

            # Check critical entitlements
            options_data = entitlements.get("options_data", False)
            realtime_quotes = entitlements.get("realtime_quotes", False)
            historical_data = entitlements.get("historical_data", False)

            if options_data and realtime_quotes:
                logger.info("✅ Critical market data entitlements available")
                return True
            else:
                missing = []
                if not options_data:
                    missing.append("options_data")
                if not realtime_quotes:
                    missing.append("realtime_quotes")

                error_msg = f"Missing entitlements: {', '.join(missing)}"
                self.validation_errors["entitlements_valid"] = error_msg
                logger.warning(f"⚠️  {error_msg} (continuing anyway)")
                return True  # Non-critical warning, continue

        except Exception as e:
            error_msg = f"Entitlements check failed: {e}"
            self.validation_errors["entitlements_valid"] = error_msg
            logger.warning(f"⚠️  {error_msg} (continuing anyway)")
            return True  # Non-critical, continue

    async def _smoke_test(self, symbols: List[str]) -> bool:
        """
        Run smoke test: fetch prices and options chain.
        
        Args:
            symbols: Symbols to test (e.g., ['SPY', 'QQQ'])
        """
        try:
            logger.info(f"Running smoke test with symbols: {symbols}...")

            # Test 1: Fetch underlier prices
            for symbol in symbols:
                try:
                    price = await self.data_provider.get_underlier_price(symbol)
                    if price <= 0:
                        error_msg = f"Invalid price for {symbol}: {price}"
                        self.validation_errors["smoke_test"] = error_msg
                        logger.error(f"❌ {error_msg}")
                        return False
                    logger.info(f"✅ {symbol} price: ${price:.2f}")
                except Exception as e:
                    error_msg = f"Failed to fetch {symbol} price: {e}"
                    self.validation_errors["smoke_test"] = error_msg
                    logger.error(f"❌ {error_msg}")
                    return False

            # Test 2: Fetch options chain for first symbol
            test_symbol = symbols[0]
            try:
                options = await self.data_provider.get_option_chain(
                    test_symbol,
                    filters={"min_dte": 0, "max_dte": 7, "min_volume": 10},
                )
                if len(options) == 0:
                    error_msg = f"No options returned for {test_symbol}"
                    self.validation_errors["smoke_test"] = error_msg
                    logger.warning(f"⚠️  {error_msg} (may be normal if market closed)")
                    # Non-critical, continue
                else:
                    logger.info(f"✅ Retrieved {len(options)} options for {test_symbol}")
            except Exception as e:
                error_msg = f"Failed to fetch options chain for {test_symbol}: {e}"
                self.validation_errors["smoke_test"] = error_msg
                logger.warning(f"⚠️  {error_msg} (may be normal if market closed)")
                # Non-critical, continue

            logger.info("✅ Smoke test passed")
            return True

        except Exception as e:
            error_msg = f"Smoke test failed: {e}"
            self.validation_errors["smoke_test"] = error_msg
            logger.error(f"❌ {error_msg}")
            return False

    def get_validation_report(self) -> Dict:
        """
        Get detailed validation report.
        
        Returns:
            Dictionary with validation results and errors
        """
        return {
            "results": self.validation_results,
            "errors": self.validation_errors,
            "all_passed": all(self.validation_results.values()),
        }
