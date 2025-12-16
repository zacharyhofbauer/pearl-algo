"""
IBKR Executor - Thread-safe executor for IBKR API calls.

This module provides a dedicated thread that owns the IB connection and executes
all IBKR API calls synchronously. Workers submit tasks via a queue and receive
results through Futures, eliminating event loop issues.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ib_insync import IB, Future, Option, Stock, util

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.utils.logger import logger


def _calculate_order_book_metrics(bids: List[Any], asks: List[Any]) -> Dict[str, Any]:
    """
    Calculate order book metrics from bid/ask levels.
    
    Args:
        bids: List of bid levels (from ticker.domBids)
        asks: List of ask levels (from ticker.domAsks)
        
    Returns:
        Dictionary with order book metrics
    """
    if not bids and not asks:
        return {
            "order_book": {"bids": [], "asks": []},
            "bid_depth": 0,
            "ask_depth": 0,
            "imbalance": 0.0,
            "weighted_mid": None,
        }
    
    # Extract bid/ask data
    bid_levels = [{"price": float(level.price), "size": int(level.size)} for level in bids]
    ask_levels = [{"price": float(level.price), "size": int(level.size)} for level in asks]
    
    # Calculate total depth
    bid_depth = sum(level["size"] for level in bid_levels)
    ask_depth = sum(level["size"] for level in ask_levels)
    
    # Calculate imbalance (-1 to +1, positive = more bids)
    total_depth = bid_depth + ask_depth
    if total_depth > 0:
        imbalance = (bid_depth - ask_depth) / total_depth
    else:
        imbalance = 0.0
    
    # Calculate volume-weighted mid-price
    weighted_mid = None
    if bid_levels and ask_levels:
        # Weighted average of best bid and ask, weighted by their sizes
        best_bid = bid_levels[0]
        best_ask = ask_levels[0]
        bid_weight = best_bid["size"]
        ask_weight = best_ask["size"]
        total_weight = bid_weight + ask_weight
        
        if total_weight > 0:
            weighted_mid = (
                (best_bid["price"] * bid_weight + best_ask["price"] * ask_weight) / total_weight
            )
        else:
            # Fallback to simple mid if no volume
            weighted_mid = (best_bid["price"] + best_ask["price"]) / 2.0
    
    return {
        "order_book": {
            "bids": bid_levels,
            "asks": ask_levels,
        },
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "imbalance": float(imbalance),
        "weighted_mid": float(weighted_mid) if weighted_mid is not None else None,
    }


@dataclass
class Task(ABC):
    """Base class for executor tasks."""

    task_id: str
    # Note: timeout is not in base class to avoid dataclass inheritance issues
    # Subclasses can add timeout with default if needed

    @abstractmethod
    def execute(self, ib: IB) -> Any:
        """Execute the task using the IB connection."""
        pass


@dataclass
class ConnectTask(Task):
    """Task to establish IB connection."""

    host: str
    port: int
    client_id: int
    timeout: float = 10.0

    def execute(self, ib: IB) -> bool:
        """Connect to IB Gateway."""
        if ib.isConnected():
            return True
        ib.connect(host=self.host, port=self.port, clientId=self.client_id, timeout=self.timeout)
        return ib.isConnected()


@dataclass
class GetLatestBarTask(Task):
    """Task to fetch latest bar/quote for a symbol."""

    symbol: str
    is_futures: bool = False

    def execute(self, ib: IB) -> Optional[Dict]:
        """Fetch latest bar data with Level 2 support."""
        # Load configuration
        service_config = load_service_config()
        data_settings = service_config.get("data", {})
        use_level2 = data_settings.get("use_level2_data", True)
        order_book_depth = data_settings.get("order_book_depth", 10)
        
        logger.info(f"GetLatestBarTask.execute() called for {self.symbol}, use_level2={use_level2}")
        
        # Create contract
        if self.is_futures:
            # For futures, use reqContractDetails to get all contracts, then select front month
            contract = Future(self.symbol, exchange="CME", currency="USD")
            try:
                # Request contract details which returns all available contracts
                contracts = ib.reqContractDetails(contract)
                if contracts:
                    # Select the front month (nearest expiration)
                    contract_details = min(contracts, key=lambda cd: cd.contract.lastTradeDateOrContractMonth)
                    contract = contract_details.contract
                    logger.debug(f"Selected front month contract: {contract.localSymbol} (exp: {contract.lastTradeDateOrContractMonth})")
                else:
                    logger.warning(f"No contract details found for {self.symbol}")
                    return None
            except Exception as e:
                logger.warning(f"Error getting contract details for {self.symbol}: {e}")
                return None
        else:
            contract = Stock(self.symbol, exchange="SMART", currency="USD")

        # Try Level 2 first if enabled (user has Level 2 subscription), then Level 1 as fallback
        # User can only subscribe to Level 1 OR Level 2, not both
        # Priority: Level 2 (if enabled) → Level 1 → Historical
        
        # Try Level 2 (order book depth) first if enabled and user has Level 2 subscription
        # Note: User has Level 1 subscription, so Level 2 will fail and fall back to Level 1
        if use_level2:
            depth_ticker = None
            try:
                logger.info(f"Attempting Level 2 market depth for {self.symbol} (depth: {order_book_depth} levels)")
                depth_ticker = ib.reqMktDepth(contract, numRows=order_book_depth, isSmartDepth=False)
                
                # Wait for order book data to populate and errors to arrive
                # IBKR errors (354, 310) are logged but we need to check if we got data
                time.sleep(2.5)  # Increased wait time for errors to propagate and data to arrive
                
                # Check if we have order book data - if not, likely an error occurred
                # IBKR errors are logged to stderr but don't raise exceptions
                # The ticker object might exist but be empty if there's an error
                has_order_book_data = False
                if depth_ticker:
                    # Check if we actually got order book data
                    bids_list = list(depth_ticker.domBids) if depth_ticker.domBids else []
                    asks_list = list(depth_ticker.domAsks) if depth_ticker.domAsks else []
                    has_order_book_data = len(bids_list) > 0 or len(asks_list) > 0
                    
                    # If no data after waiting, likely an error (354 or 310)
                    if not has_order_book_data:
                        logger.warning(
                            f"⚠️  Level 2 request for {self.symbol} returned no order book data after 2.5s wait.\n"
                            f"   This indicates Error 354 (subscription not available) or Error 310 (market depth not found).\n"
                            f"   \n"
                            f"   📋 Since you have 'CME Real-Time (NP,L2)' subscribed, the issue is likely:\n"
                            f"   1. Subscription is active for TWS but NOT enabled for API access\n"
                            f"   2. IB Gateway needs to be restarted after subscription activation\n"
                            f"   3. Check IBKR Client Portal → Account → Market Data Subscriptions\n"
                            f"      - Look for 'API Access' or 'Market Data API' settings\n"
                            f"      - Some subscriptions require separate API enablement\n"
                            f"   4. Verify Gateway is connected with proper permissions\n"
                            f"   5. Try restarting Gateway: ./scripts/gateway/stop_ibgateway_ibc.sh && ./scripts/gateway/start_ibgateway_ibc.sh\n"
                            f"   \n"
                            f"   Falling back to Level 1, then historical if needed."
                        )
                        try:
                            ib.cancelMktDepth(contract)
                        except Exception:
                            pass
                        depth_ticker = None
                
                # Check if we have order book data
                if depth_ticker and has_order_book_data:
                    # Extract order book
                    bids = list(depth_ticker.domBids) if depth_ticker.domBids else []
                    asks = list(depth_ticker.domAsks) if depth_ticker.domAsks else []
                    
                    logger.debug(f"Level 2 data received for {self.symbol}: {len(bids)} bid levels, {len(asks)} ask levels")
                    
                    # Calculate order book metrics
                    order_book_metrics = _calculate_order_book_metrics(bids, asks)
                    
                    # Get price from order book (use weighted mid or best bid/ask)
                    if order_book_metrics["weighted_mid"]:
                        price = order_book_metrics["weighted_mid"]
                    elif bids and asks:
                        price = (bids[0].price + asks[0].price) / 2.0
                    elif bids:
                        price = float(bids[0].price)
                    elif asks:
                        price = float(asks[0].price)
                    else:
                        price = None
                    
                    if price and price > 0:
                        # Use order book price directly (don't request Level 1 since user can only subscribe to one)
                        # Level 2 order book gives us bid/ask, we'll use the weighted mid or best bid/ask as price
                        result = {
                            "timestamp": datetime.now(timezone.utc),
                            "open": price,  # Use order book price for all OHLC
                            "high": price,
                            "low": price,
                            "close": price,
                            "volume": 0,  # Volume not available from Level 2 order book alone
                            "bid": float(bids[0].price) if bids else None,
                            "ask": float(asks[0].price) if asks else None,
                            "_data_level": "level2",  # Metadata
                        }
                        # Add order book metrics
                        result.update(order_book_metrics)
                        
                        # Cleanup
                        ib.cancelMktDepth(contract)
                        
                        logger.info(f"✅ Successfully retrieved Level 2 data for {self.symbol}: ${price:.2f}, imbalance={order_book_metrics['imbalance']:.2f}, bid_depth={order_book_metrics['bid_depth']}, ask_depth={order_book_metrics['ask_depth']}")
                        return result
                    
                    # Cleanup depth ticker
                    ib.cancelMktDepth(contract)
                    depth_ticker = None
                # If we get here, Level 2 didn't work (no data or error)
                # The depth_ticker cleanup is already handled above
            except Exception as e:
                error_str = str(e).lower()
                if "354" in str(e) or "310" in str(e) or "subscription" in error_str:
                    logger.info(f"Level 2 subscription not available for {self.symbol} (Error 354/310), will try Level 1")
                else:
                    logger.debug(f"Level 2 data request failed for {self.symbol}: {e}, will try Level 1")
                if depth_ticker:
                    try:
                        ib.cancelMktDepth(contract)
                    except Exception:
                        pass

        # Check if market is likely open (CME futures: ETH Sun 6PM ET - Fri 5PM ET, with Mon-Thu 5-6PM maintenance break)
        # This helps explain Error 354 when market is closed
        from datetime import datetime, timezone
        try:
            from zoneinfo import ZoneInfo
            et_tz = ZoneInfo('America/New_York')
        except ImportError:
            # Fallback for older Python versions
            import pytz
            try:
                et_tz = pytz.timezone('America/New_York')
            except Exception:
                # Last resort: use UTC offset (not ideal but works)
                from datetime import timedelta
                et_tz = timezone(timedelta(hours=-5))  # EST offset (approximate)
        now_et = datetime.now(et_tz)
        weekday = now_et.weekday()  # 0=Monday, 6=Sunday
        hour_et = now_et.hour
        minute_et = now_et.minute
        time_et = hour_et + minute_et / 60.0
        
        # CME futures market hours:
        # - ETH: Sun 6:00 PM ET - Fri 5:00 PM ET (continuous)
        # - Maintenance break: Mon-Thu 5:00 PM - 6:00 PM ET
        is_market_open = False
        market_status = ""
        if weekday == 6:  # Sunday
            is_market_open = time_et >= 18.0  # After 6 PM ET
            market_status = "Market opens at 6:00 PM ET on Sunday" if time_et < 18.0 else "Market is open (ETH)"
        elif weekday < 4:  # Monday-Thursday
            if 17.0 <= time_et < 18.0:  # 5-6 PM ET maintenance break
                is_market_open = False
                market_status = "Market is in maintenance break (5:00-6:00 PM ET)"
            else:
                is_market_open = True
                market_status = "Market is open (ETH)"
        elif weekday == 4:  # Friday
            is_market_open = time_et < 17.0  # Before 5 PM ET
            market_status = "Market closed for weekend (closes at 5:00 PM ET Friday)" if time_et >= 17.0 else "Market is open (ETH)"
        else:  # Saturday
            is_market_open = False
            market_status = "Market closed (opens Sunday 6:00 PM ET)"
        
        # Fallback to Level 1 (top bid/ask) if Level 2 failed or not enabled
        ticker = None
        try:
            logger.info(
                f"Requesting Level 1 market data for {self.symbol} (you have CME Real-Time NP,L1 subscription)\n"
                f"   Current time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                f"   Market status: {market_status}"
            )
            # Request market data (may fail with Error 354 if no subscription OR if market is closed)
            ticker = ib.reqMktData(contract, "", False, False)
            
            # Wait longer for data to arrive (increased from 0.5s to 1.5s for better reliability)
            time.sleep(1.5)
            
            # Check for market data errors
            if hasattr(ticker, 'modelOption') and ticker.modelOption:
                # Check if there's an error message
                error_msg = str(ticker.modelOption) if ticker.modelOption else ""
                if "354" in error_msg or "subscription" in error_msg.lower():
                    if not is_market_open:
                        logger.info(
                            f"Level 1 data not available for {self.symbol} (Error 354) - Market is closed\n"
                            f"   {market_status}\n"
                            f"   Error 354 can occur when market is closed even with active subscription.\n"
                            f"   Will use historical data fallback."
                        )
                    else:
                        logger.warning(
                            f"Level 1 subscription not available for {self.symbol} (Error 354) - Market is OPEN\n"
                            f"   This suggests a subscription issue:\n"
                            f"   1. Verify subscription is active and paid\n"
                            f"   2. Check account balance (minimum USD 500)\n"
                            f"   3. Ensure Market Data API Acknowledgement is signed\n"
                            f"   4. Wait 1-2 minutes after subscribing, then restart Gateway\n"
                            f"   Will use historical data fallback."
                        )
                    ib.cancelMktData(contract)
                    ticker = None  # Will fall back to historical data
                elif ticker.last or ticker.close:
                    # Got valid data
                    last_price = ticker.last if ticker.last else ticker.close
                    if last_price and last_price > 0:
                        result = {
                            "timestamp": datetime.now(timezone.utc),
                            "open": ticker.open if ticker.open else last_price,
                            "high": ticker.high if ticker.high else last_price,
                            "low": ticker.low if ticker.low else last_price,
                            "close": last_price,
                            "volume": ticker.volume if ticker.volume else 0,
                            "bid": ticker.bid if ticker.bid else None,
                            "ask": ticker.ask if ticker.ask else None,
                            "_data_level": "level1",  # Metadata
                        }
                        # Add empty order book structure for consistency
                        result.update({
                            "order_book": {"bids": [], "asks": []},
                            "bid_depth": 0,
                            "ask_depth": 0,
                            "imbalance": 0.0,
                            "weighted_mid": None,
                        })
                        ib.cancelMktData(contract)
                        logger.info(f"✅ Successfully retrieved Level 1 data for {self.symbol}: ${last_price:.2f}")
                        return result
            
            # Check if we got data but it's not valid
            if ticker and not (ticker.last or ticker.close):
                logger.debug(f"Level 1 data request for {self.symbol} returned no price data, will use historical fallback")
                ib.cancelMktData(contract)
                ticker = None
        except Exception as e:
            error_str = str(e).lower()
            if "354" in str(e) or "subscription" in error_str:
                if not is_market_open:
                    logger.info(
                        f"Level 1 subscription error for {self.symbol}: {e}\n"
                        f"   Market is closed ({market_status})\n"
                        f"   Error 354 is normal when market is closed. Will use historical data fallback."
                    )
                else:
                    logger.warning(
                        f"Level 1 subscription error for {self.symbol}: {e}\n"
                        f"   Market is OPEN - this suggests a subscription issue. Will use historical data fallback."
                    )
            else:
                logger.debug(f"Error requesting Level 1 market data for {self.symbol}: {e}, will use historical fallback")
            if ticker:
                try:
                    ib.cancelMktData(contract)
                except Exception:
                    pass
            ticker = None  # Will fall back to historical data

        # Fallback: Use latest historical bar if real-time data not available
        # This handles Error 354 (market data subscription not available OR market closed)
        # Use longer durations that are more reliable when market is closed or contract is expiring
        try:
            logger.info(
                f"Using historical data fallback for {self.symbol} (real-time subscription not available)\n"
                f"   Market status: {market_status}\n"
                f"   Note: Error 354 can occur when market is closed, even with active subscription"
            )
            # IBKR requires duration format: integer{SPACE}unit where unit is S|D|W|M|Y (NOT H for hours!)
            # Error 162 often occurs with very short durations (5 min) when market is closed
            # Try longer durations first which are more reliable
            # Note: IBKR doesn't support "H" (hours), so we use "1 D" (1 day) for recent data
            bars = None
            duration_strategies = [
                ("1 D", True),   # 1 day with RTH - most reliable for recent data
                ("1 D", False), # 1 day without RTH - if market is closed
                ("1 W", False), # 1 week without RTH - final fallback
            ]
            
            for duration_str, use_rth in duration_strategies:
                try:
                    logger.debug(f"Trying historical data: {duration_str}, useRTH={use_rth}")
                    bars = ib.reqHistoricalData(
                        contract,
                        endDateTime="",
                        durationStr=duration_str,
                        barSizeSetting="1 min",
                        whatToShow="TRADES",
                        useRTH=use_rth,
                        formatDate=1,
                    )
                    if bars and len(bars) > 0:
                        logger.debug(f"Successfully retrieved {len(bars)} historical bars with {duration_str}")
                        break  # Success, exit the loop
                except Exception as hist_e:
                    error_str = str(hist_e).lower()
                    # Error 162 often means TWS session conflict, market closed, contract expired, or no data available
                    # Error 321 means invalid duration format (e.g., using "H" for hours which isn't supported)
                    if "162" in str(hist_e):
                        # Error 162: TWS session conflict - this is a critical issue
                        if "tws session" in error_str or "different ip" in error_str:
                            logger.error(
                                f"❌ Error 162: TWS session conflict detected for {self.symbol}\n"
                                f"   This means TWS is connected from a different IP address.\n"
                                f"   You cannot use both TWS and Gateway simultaneously from different IPs.\n"
                                f"   Solution: Close TWS or disconnect it, then restart Gateway.\n"
                                f"   Trying next historical data strategy..."
                            )
                        else:
                            logger.warning(f"Historical data request failed (Error 162) with {duration_str}, useRTH={use_rth}: {hist_e}")
                        continue  # Try next strategy
                    elif "321" in str(hist_e) or "duration format" in error_str:
                        logger.debug(f"Historical data request failed (Error 321 - invalid format) with {duration_str}: {hist_e}")
                        continue  # Try next strategy
                    elif "hmds" in error_str or "no data" in error_str:
                        logger.debug(f"Historical data request failed (no data) with {duration_str}, useRTH={use_rth}: {hist_e}")
                        continue  # Try next strategy
                    else:
                        # Non-162/321 error, log and try next
                        logger.debug(f"Historical data request failed with {duration_str}: {hist_e}")
                        continue
            
            if not bars or len(bars) == 0:
                logger.error(
                    f"❌ CRITICAL: All historical data strategies failed for {self.symbol}\n"
                    f"   This means:\n"
                    f"   - Level 2 subscription not available (if enabled)\n"
                    f"   - Level 1 subscription not available (Error 354)\n"
                    f"   - Historical data service unavailable (Error 162 - TWS conflict or market closed)\n"
                    f"   \n"
                    f"   📋 Immediate actions:\n"
                    f"   1. Check if market is open (CME futures: 17:00-16:00 CT, Sun-Fri)\n"
                    f"   2. If Error 162: Close any TWS sessions, restart Gateway\n"
                    f"   3. Verify Level 1 subscription is active and paid\n"
                    f"   4. Check account balance (minimum USD 500 required)\n"
                    f"   5. Wait 1-2 minutes after subscribing, then restart Gateway"
                )
            
            if bars:
                # Get the most recent bar
                latest_bar = bars[-1]
                bar_timestamp = latest_bar.date.replace(tzinfo=timezone.utc) if latest_bar.date.tzinfo is None else latest_bar.date
                
                # Validate timestamp - for historical fallback, be more lenient
                # Market may be closed, so data could be hours old
                now = datetime.now(timezone.utc)
                age_seconds = (now - bar_timestamp).total_seconds()
                age_minutes = age_seconds / 60
                age_hours = age_minutes / 60
                
                if age_minutes > 60:  # More than 1 hour old
                    logger.warning(
                        f"⚠️  Historical fallback data for {self.symbol} is {age_hours:.1f} hours old "
                        f"(timestamp: {bar_timestamp}). Market may be closed or contract expiring soon."
                    )
                elif age_minutes > 15:  # More than 15 minutes old
                    logger.info(
                        f"Historical fallback data for {self.symbol} is {age_minutes:.1f} minutes old "
                        f"(timestamp: {bar_timestamp}). Using as latest available data."
                    )
                else:
                    logger.debug(f"Historical fallback data for {self.symbol} is {age_minutes:.1f} minutes old (acceptable)")
                
                result = {
                    "timestamp": bar_timestamp,
                    "open": float(latest_bar.open),
                    "high": float(latest_bar.high),
                    "low": float(latest_bar.low),
                    "close": float(latest_bar.close),
                    "volume": int(latest_bar.volume),
                    "bid": None,  # Not available from historical data
                    "ask": None,  # Not available from historical data
                    "_data_level": "historical",  # Metadata
                }
                # Add empty order book structure for consistency
                result.update({
                    "order_book": {"bids": [], "asks": []},
                    "bid_depth": 0,
                    "ask_depth": 0,
                    "imbalance": 0.0,
                    "weighted_mid": None,
                })
                return result
            else:
                logger.error(
                    f"❌ CRITICAL: No historical bars returned for {self.symbol} - all data sources failed!\n"
                    f"   This means:\n"
                    f"   - Level 2 subscription not available (Error 354/310)\n"
                    f"   - Level 1 subscription not available (Error 354)\n"
                    f"   - Historical data service unavailable (Error 162)\n"
                    f"   \n"
                    f"   📋 Immediate actions:\n"
                    f"   1. Check if market is open (CME futures: 17:00-16:00 CT, Sun-Fri)\n"
                    f"   2. Verify contract {contract.localSymbol if hasattr(contract, 'localSymbol') else 'N/A'} hasn't expired\n"
                    f"   3. Check IBKR Gateway connection and subscriptions\n"
                    f"   4. Restart Gateway if needed"
                )
        except Exception as e:
            error_str = str(e).lower()
            # Error 162 often means TWS session conflict, market closed, contract expired, or no data available
            if "162" in str(e):
                if "tws session" in error_str or "different ip" in error_str:
                    logger.error(
                        f"❌ CRITICAL: Error 162 - TWS session conflict for {self.symbol}\n"
                        f"   TWS is connected from a different IP address.\n"
                        f"   You cannot use both TWS and Gateway simultaneously from different IPs.\n"
                        f"   \n"
                        f"   📋 Solution:\n"
                        f"   1. Close TWS or disconnect it completely\n"
                        f"   2. Wait 30 seconds for session to clear\n"
                        f"   3. Restart Gateway: ./scripts/gateway/stop_ibgateway_ibc.sh && ./scripts/gateway/start_ibgateway_ibc.sh\n"
                        f"   4. Restart service\n"
                        f"   \n"
                        f"   Error: {e}"
                    )
                else:
                    logger.error(
                        f"❌ CRITICAL: Historical data unavailable for {self.symbol} (Error 162)\n"
                        f"   Possible causes:\n"
                        f"   - Market is closed (CME futures: 17:00-16:00 CT, Sun-Fri)\n"
                        f"   - Contract may have expired (check expiration date)\n"
                        f"   - HMDS (Historical Market Data Service) temporarily unavailable\n"
                        f"   - Contract too close to expiration (within 3 days)\n"
                        f"   Error: {e}"
                    )
            elif "hmds" in error_str or "no data" in error_str:
                logger.error(f"❌ CRITICAL: Historical data unavailable for {self.symbol} (no data): {e}")
            else:
                logger.error(f"❌ CRITICAL: Error fetching historical data fallback for {self.symbol}: {e}")
        
        return None


@dataclass
class GetHistoricalDataTask(Task):
    """Task to fetch historical OHLCV data."""

    symbol: str
    start: Optional[datetime]
    end: Optional[datetime]
    timeframe: Optional[str]
    is_futures: bool = False

    def execute(self, ib: IB) -> Any:
        """Fetch historical data."""
        if self.start is None:
            start = datetime.now(timezone.utc) - timedelta(days=365)
        else:
            start = self.start
        if self.end is None:
            end = datetime.now(timezone.utc)
        else:
            end = self.end

        # Convert timeframe to IB bar size format
        bar_size_map = {
            "1m": "1 min",
            "5m": "5 mins",
            "15m": "15 mins",
            "30m": "30 mins",
            "1h": "1 hour",
            "1d": "1 day",
        }
        bar_size = bar_size_map.get(self.timeframe.lower() if self.timeframe else "1d", "1 day")

        # Calculate duration string for IB
        duration_days = (end - start).days
        if duration_days <= 1:
            duration_str = "1 D"
        elif duration_days <= 7:
            duration_str = "1 W"
        elif duration_days <= 30:
            duration_str = "1 M"
        elif duration_days <= 365:
            duration_str = "1 Y"
        else:
            duration_str = f"{duration_days} D"

        # Create contract
        if self.is_futures:
            # For futures, use reqContractDetails to get all contracts, then select front month
            contract = Future(self.symbol, exchange="CME", currency="USD")
            try:
                # Request contract details which returns all available contracts
                contracts = ib.reqContractDetails(contract)
                if contracts:
                    # Select the front month (nearest expiration)
                    contract_details = min(contracts, key=lambda cd: cd.contract.lastTradeDateOrContractMonth)
                    contract = contract_details.contract
                    logger.debug(f"Selected front month contract: {contract.localSymbol} (exp: {contract.lastTradeDateOrContractMonth})")
                else:
                    logger.warning(f"No contract details found for {self.symbol}")
                    return []
            except Exception as e:
                logger.warning(f"Error getting contract details for {self.symbol}: {e}")
                return []
        else:
            contract = Stock(self.symbol, exchange="SMART", currency="USD")

        # Request historical data
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end,
            durationStr=duration_str,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
        )

        return bars


@dataclass
class GetOptionsChainTask(Task):
    """Task to fetch options chain."""

    underlying_symbol: str
    expiration_date: Optional[str] = None
    min_dte: Optional[int] = None
    max_dte: Optional[int] = None
    strike_proximity_pct: Optional[float] = None
    min_volume: Optional[int] = None
    min_open_interest: Optional[int] = None
    underlying_price: Optional[float] = None

    def execute(self, ib: IB) -> List[Dict]:
        """Fetch options chain with filtering."""
        # Create stock contract for underlying
        stock = Stock(self.underlying_symbol, "SMART", "USD")

        # Request option chains
        chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)

        if not chains:
            return []

        # Get today's date for DTE calculation
        today = date.today()
        all_options = []

        # Process each chain (each chain represents an expiration)
        for chain in chains:
            expiration_str = chain.expirations[0] if chain.expirations else None
            if not expiration_str:
                continue

            # Parse expiration date
            try:
                # IB returns expiration as YYYYMMDD string
                exp_date = datetime.strptime(expiration_str, "%Y%m%d").date()
                dte = (exp_date - today).days

                # Filter by DTE
                if self.min_dte is not None and dte < self.min_dte:
                    continue
                if self.max_dte is not None and dte > self.max_dte:
                    continue
                if self.expiration_date and expiration_str != self.expiration_date:
                    continue

                # Process strikes for this expiration
                for strike in chain.strikes:
                    # Filter by strike proximity
                    if self.strike_proximity_pct and self.underlying_price and self.underlying_price > 0:
                        strike_pct = abs(strike - self.underlying_price) / self.underlying_price
                        if strike_pct > self.strike_proximity_pct:
                            continue

                    # Get option contracts for call and put
                    for option_type in ["C", "P"]:
                        option = Option(
                            self.underlying_symbol,
                            expiration_str,
                            strike,
                            option_type,
                            "SMART"
                        )

                        try:
                            # Request market data for this option
                            ticker = ib.reqMktData(option, "", False, False)
                            time.sleep(0.1)  # Brief wait for data

                            # Get option data
                            volume = ticker.volume if ticker.volume else 0
                            open_interest = ticker.openInterest if hasattr(ticker, 'openInterest') else 0

                            # Filter by volume and OI
                            if self.min_volume is not None and volume < self.min_volume:
                                continue
                            if self.min_open_interest is not None and open_interest < self.min_open_interest:
                                continue

                            # Build option dict
                            option_dict = {
                                "symbol": f"{self.underlying_symbol} {expiration_str} {strike} {option_type}",
                                "underlying_symbol": self.underlying_symbol,
                                "strike": strike,
                                "expiration": expiration_str,
                                "expiration_date": exp_date.isoformat(),
                                "dte": dte,
                                "option_type": "call" if option_type == "C" else "put",
                                "bid": ticker.bid if ticker.bid else None,
                                "ask": ticker.ask if ticker.ask else None,
                                "last_price": ticker.last if ticker.last else (ticker.bid + ticker.ask) / 2 if ticker.bid and ticker.ask else None,
                                "volume": volume,
                                "open_interest": open_interest,
                                "iv": ticker.impliedVolatility if hasattr(ticker, 'impliedVolatility') else None,
                            }

                            all_options.append(option_dict)

                        except Exception as e:
                            logger.debug(f"Error fetching data for option {option}: {e}")
                            continue
            except Exception as e:
                logger.debug(f"Error parsing expiration {expiration_str}: {e}")
                continue

        return all_options


@dataclass
class ShutdownTask(Task):
    """Task to shutdown executor gracefully."""

    def execute(self, ib: IB) -> None:
        """Disconnect from IB Gateway."""
        if ib.isConnected():
            ib.disconnect()


class IBKRExecutor:
    """
    Thread-safe executor for IBKR API calls.
    
    Runs in a dedicated thread and executes all IBKR calls synchronously.
    Workers submit tasks via submit_task() and receive results through Futures.
    """

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 5,
    ):
        """
        Initialize IBKR executor.
        
        Args:
            host: IB Gateway host
            port: IB Gateway port
            client_id: Client ID for connection
            reconnect_delay: Initial delay between reconnection attempts (seconds)
            max_reconnect_attempts: Maximum reconnection attempts before giving up
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        # IB connection (owned by executor thread)
        self.ib: Optional[IB] = None
        self._connected = False

        # Task queue and results
        self._task_queue: queue.Queue = queue.Queue()
        self._results: Dict[str, ConcurrentFuture] = {}
        self._results_lock = threading.Lock()

        # Executor thread
        self._executor_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._running = False

        # Rate limiting
        self._last_request_time: float = 0.0
        self._min_request_interval = 0.1  # 100ms between requests

        # Connection state
        self._connection_lock = threading.Lock()
        self._reconnect_attempts = 0

        logger.info(
            f"IBKRExecutor initialized: host={host}, port={port}, client_id={client_id}"
        )

    def start(self) -> None:
        """Start the executor thread."""
        if self._running:
            return

        self._running = True
        self._executor_thread = threading.Thread(target=self._run_executor, daemon=False)
        self._executor_thread.start()
        logger.info("IBKRExecutor thread started")

    def stop(self, timeout: float = 10.0) -> None:
        """
        Stop the executor thread gracefully.
        
        Args:
            timeout: Maximum time to wait for shutdown (seconds)
        """
        if not self._running:
            return

        logger.info("Shutting down IBKRExecutor...")
        self._shutdown_event.set()

        # Disconnect IB connection immediately to free client_id
        try:
            if hasattr(self, 'ib') and self.ib and self.ib.isConnected():
                logger.info("Disconnecting IB connection to free client_id...")
                self.ib.disconnect()
                logger.info("IB connection disconnected")
        except Exception as e:
            logger.warning(f"Error disconnecting IB connection: {e}")

        # Submit shutdown task
        shutdown_task = ShutdownTask(task_id="shutdown")
        self._task_queue.put(shutdown_task)

        # Wait for thread to finish
        if self._executor_thread:
            self._executor_thread.join(timeout=timeout)
            if self._executor_thread.is_alive():
                logger.warning("IBKRExecutor thread did not stop within timeout")
            else:
                logger.info("IBKRExecutor thread stopped")

        self._running = False

    def submit_task(self, task: Task) -> ConcurrentFuture:
        """
        Submit a task to the executor.
        
        Args:
            task: Task to execute
            
        Returns:
            Future that will contain the result or exception
        """
        if not self._running:
            raise RuntimeError("Executor is not running. Call start() first.")

        # Create Future for result
        future = ConcurrentFuture()
        with self._results_lock:
            self._results[task.task_id] = future

        # Submit task to queue
        self._task_queue.put(task)

        return future

    def _run_executor(self) -> None:
        """Main executor loop (runs in dedicated thread)."""
        # Create event loop for this thread (required by ib_insync)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        logger.info("IBKRExecutor thread started")

        # Initialize IB connection
        self.ib = IB()

        # Connect on startup
        try:
            self._ensure_connected()
        except Exception as e:
            logger.error(f"Failed to connect on startup: {e}")

        # Main loop
        while not self._shutdown_event.is_set():
            try:
                # Get task from queue (with timeout to check shutdown)
                try:
                    task = self._task_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                # Handle shutdown task
                if isinstance(task, ShutdownTask):
                    task.execute(self.ib)
                    break

                # Execute task
                try:
                    # Ensure connection before executing
                    if not isinstance(task, ConnectTask):
                        self._ensure_connected()

                    # Rate limiting
                    self._rate_limit()

                    # Execute task
                    result = task.execute(self.ib)

                    # Set result in Future
                    with self._results_lock:
                        future = self._results.pop(task.task_id, None)
                        if future:
                            future.set_result(result)

                except Exception as e:
                    logger.error(f"Error executing task {task.task_id}: {e}", exc_info=True)

                    # Set exception in Future
                    with self._results_lock:
                        future = self._results.pop(task.task_id, None)
                        if future:
                            future.set_exception(e)

                    # Check if connection error - trigger reconnection
                    if "not connected" in str(e).lower() or "connection" in str(e).lower():
                        self._connected = False
                        logger.warning("Connection lost, will reconnect on next task")

            except Exception as e:
                logger.error(f"Unexpected error in executor loop: {e}", exc_info=True)
                time.sleep(1.0)

        # Cleanup
        if self.ib and self.ib.isConnected():
            try:
                self.ib.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting: {e}")

        # Cleanup event loop
        try:
            loop = asyncio.get_event_loop()
            if loop and not loop.is_closed():
                loop.close()
        except Exception as e:
            logger.debug(f"Error closing event loop: {e}")

        logger.info("IBKRExecutor thread stopped")

    def _ensure_connected(self) -> None:
        """Ensure IB connection is established (called from executor thread)."""
        with self._connection_lock:
            if self._connected and self.ib and self.ib.isConnected():
                return

            if self.ib is None:
                self.ib = IB()

            # Try to connect with retries
            while not self.ib.isConnected():
                logger.info(f"Connecting to IB Gateway at {self.host}:{self.port}")
                try:
                    self.ib.connect(
                        host=self.host,
                        port=self.port,
                        clientId=self.client_id,
                        timeout=10
                    )
                    self._connected = True
                    self._reconnect_attempts = 0
                    logger.info("Connected to IB Gateway successfully")
                    return
                except Exception as e:
                    self._connected = False
                    self._reconnect_attempts += 1

                    if self._reconnect_attempts >= self.max_reconnect_attempts:
                        logger.error(
                            f"Failed to connect after {self._reconnect_attempts} attempts. "
                            f"Giving up."
                        )
                        raise RuntimeError(
                            f"Cannot connect to IB Gateway at {self.host}:{self.port} "
                            f"after {self._reconnect_attempts} attempts. "
                            f"Error: {e}"
                        ) from e

                    # Exponential backoff (capped at 10s for tests)
                    delay = min(self.reconnect_delay * (2 ** (self._reconnect_attempts - 1)), 10.0)
                    logger.warning(
                        f"Connection failed (attempt {self._reconnect_attempts}/{self.max_reconnect_attempts}). "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    # Loop will retry connection

    def _rate_limit(self) -> None:
        """Enforce rate limiting (called from executor thread)."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def is_connected(self) -> bool:
        """Check if executor is connected to IB Gateway."""
        return self._connected and self.ib is not None and self.ib.isConnected()

    def get_queue_size(self) -> int:
        """Get current task queue size."""
        return self._task_queue.qsize()
