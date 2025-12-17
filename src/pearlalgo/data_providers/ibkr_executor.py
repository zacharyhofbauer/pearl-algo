"""
IBKR Executor - Thread-safe executor for IBKR API calls.

This module provides a dedicated thread that owns the IB connection and executes
all IBKR API calls synchronously. Workers submit tasks via a queue and receive
results through Futures, eliminating event loop issues.
"""

from __future__ import annotations

import asyncio
import math
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


def _is_valid_price(value: Any) -> bool:
    """Check if a price value is valid (not None, not NaN, and > 0)."""
    if value is None:
        return False
    try:
        float_val = float(value)
        return not math.isnan(float_val) and float_val > 0
    except (ValueError, TypeError):
        return False


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

    def execute(self, ib: IB, executor=None) -> Optional[Dict]:
        """Fetch latest bar data using Level 1 market data only."""
        logger.info(f"🔵 GetLatestBarTask.execute() STARTED for {self.symbol}")
        
        # Store executor reference for error checking
        if executor:
            ib._executor = executor
        
        # Create contract with detailed logging
        logger.info(f"📋 Step 1: Creating contract for {self.symbol}")
        if self.is_futures:
            # For futures, use reqContractDetails to get all contracts, then select front month
            contract = Future(self.symbol, exchange="CME", currency="USD")
            logger.info(f"   Created Future contract: symbol={self.symbol}, exchange=CME, currency=USD")
            try:
                logger.info(f"   Requesting contract details from IBKR...")
                # Request contract details which returns all available contracts
                contracts = ib.reqContractDetails(contract)
                logger.info(f"   Received {len(contracts) if contracts else 0} contract(s) from IBKR")
                if contracts:
                    # Sort contracts by expiration date
                    sorted_contracts = sorted(contracts, key=lambda cd: cd.contract.lastTradeDateOrContractMonth)
                    
                    # Check if front month is expiring soon (within 3 days)
                    from datetime import datetime, timedelta
                    front_month = sorted_contracts[0]
                    expiration_str = front_month.contract.lastTradeDateOrContractMonth
                    try:
                        # Parse expiration date (format: YYYYMMDD)
                        expiration_date = datetime.strptime(expiration_str, "%Y%m%d")
                        days_until_expiration = (expiration_date - datetime.now()).days
                        
                        if days_until_expiration <= 3:
                            logger.warning(
                                f"⚠️  Front month contract expires in {days_until_expiration} days ({expiration_str})!\n"
                                f"   This may cause live data issues. Trying next month contract instead..."
                            )
                            # Use next month contract if available
                            if len(sorted_contracts) > 1:
                                contract_details = sorted_contracts[1]
                                logger.info(f"✅ Using next month contract instead (expires {contract_details.contract.lastTradeDateOrContractMonth})")
                            else:
                                contract_details = front_month
                                logger.warning(f"⚠️  Only one contract available, using front month despite expiration")
                        else:
                            contract_details = front_month
                            logger.info(f"✅ Front month contract expires in {days_until_expiration} days - OK")
                    except Exception as date_e:
                        logger.warning(f"⚠️  Could not parse expiration date '{expiration_str}': {date_e}, using front month")
                        contract_details = front_month
                    
                    contract = contract_details.contract
                    logger.info(
                        f"✅ Selected contract:\n"
                        f"   - Local Symbol: {contract.localSymbol}\n"
                        f"   - ConId: {contract.conId}\n"
                        f"   - Expiration: {contract.lastTradeDateOrContractMonth}\n"
                        f"   - Exchange: {contract.exchange}\n"
                        f"   - Currency: {contract.currency}"
                    )
                else:
                    logger.error(f"❌ No contract details found for {self.symbol}")
                    return None
            except Exception as e:
                logger.error(f"❌ Error getting contract details for {self.symbol}: {e}", exc_info=True)
                return None
        else:
            contract = Stock(self.symbol, exchange="SMART", currency="USD")
            logger.info(f"   Created Stock contract: symbol={self.symbol}, exchange=SMART")

        # REMOVED: All Level 2 code - user has Level 1 subscription only
        # Directly request Level 1 market data
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
        
        # Request Level 1 market data (ONLY - no Level 2)
        logger.info(f"📡 Step 2: Requesting Level 1 market data for {self.symbol}")
        logger.info(
            f"   Contract Details:\n"
            f"   - Symbol: {contract.symbol}\n"
            f"   - Local Symbol: {contract.localSymbol if hasattr(contract, 'localSymbol') else 'N/A'}\n"
            f"   - ConId: {contract.conId if hasattr(contract, 'conId') else 'N/A'}\n"
            f"   - Exchange: {contract.exchange}\n"
            f"   - Currency: {contract.currency}\n"
            f"   - SecType: {contract.secType if hasattr(contract, 'secType') else 'N/A'}"
        )
        logger.info(
            f"   Market Status:\n"
            f"   - Current time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"   - Market status: {market_status}\n"
            f"   - Market open: {is_market_open}"
        )
        logger.info(f"   Subscription: CME Real-Time (NP,L1) - Level 1 only")
        
        ticker = None
        try:
            # Ensure market data type is LIVE (1) before requesting
            logger.info(f"   Setting market data type to LIVE (1)...")
            try:
                ib.reqMarketDataType(1)  # 1 = Live, 2 = Frozen, 3 = Delayed, 4 = Delayed-Frozen
                logger.info(f"   ✅ Market data type set to LIVE (1)")
            except Exception as md_type_e:
                logger.warning(f"   ⚠️  Could not set market data type (may already be set): {md_type_e}")
            
            # Request Level 1 market data
            # Try snapshot first to get initial price, then switch to streaming if needed
            # Parameters: contract, genericTickList="", snapshot=True/False, regulatorySnapshot=False
            logger.info(f"   Attempting snapshot request first to get initial price...")
            logger.info(f"   Calling ib.reqMktData(contract, '', True, False) [snapshot=True]...")
            logger.info(f"   - genericTickList: '' (empty = default ticks)")
            logger.info(f"   - snapshot: True (one-time snapshot to get initial price)")
            logger.info(f"   - regulatorySnapshot: False")
            
            # Try snapshot first (one-time request, might work better for initial price)
            ticker = ib.reqMktData(contract, "", True, False)
            ticker_req_id = ticker.reqId if hasattr(ticker, 'reqId') else None
            logger.info(f"   ✅ reqMktData() call completed, ticker object created")
            logger.info(f"   Ticker object type: {type(ticker)}")
            logger.info(f"   Ticker ID: {ticker_req_id}")
            
            # Clear any previous errors for this reqId
            if ticker_req_id is not None:
                executor = getattr(ib, '_executor', None)
                if executor and hasattr(executor, '_market_data_errors'):
                    with executor._error_lock:
                        executor._market_data_errors.pop(ticker_req_id, None)
            
            # Wait for data/errors using event-based approach
            logger.info(f"   Waiting for market data to arrive (snapshot request, should be faster)...")
            max_wait = 15.0  # Increased wait time for snapshot requests
            check_interval = 0.5  # Check every 0.5 seconds
            waited = 0.0
            
            # For snapshot requests, we need to wait for the snapshot to complete
            # Use ib.waitForUpdate() to properly wait for ticker events
            # This is more reliable than time.sleep() polling
            while waited < max_wait:
                try:
                    # Wait for update with timeout (raises exception on timeout, which is expected)
                    ib.waitForUpdate(timeout=check_interval)
                    waited += check_interval
                    logger.info(f"   [{waited:.1f}s] Event received, checking ticker state...")
                except Exception:
                    # Timeout exception is expected when no update arrives - continue checking
                    waited += check_interval
                    # Only log every 2 seconds to reduce spam
                    if int(waited * 2) % 4 == 0:
                        logger.info(f"   [{waited:.1f}s] Waiting for snapshot data...")
                
                # Check ticker attributes
                if ticker:
                    # Check for NaN values explicitly
                    last_val = ticker.last if hasattr(ticker, 'last') else None
                    close_val = ticker.close if hasattr(ticker, 'close') else None
                    bid_val = ticker.bid if hasattr(ticker, 'bid') else None
                    ask_val = ticker.ask if hasattr(ticker, 'ask') else None
                    
                    # Format values for logging (show "NaN" if it's NaN)
                    last_str = "NaN" if (last_val is not None and math.isnan(float(last_val))) else str(last_val) if last_val is not None else "N/A"
                    close_str = "NaN" if (close_val is not None and math.isnan(float(close_val))) else str(close_val) if close_val is not None else "N/A"
                    bid_str = "NaN" if (bid_val is not None and math.isnan(float(bid_val))) else str(bid_val) if bid_val is not None else "N/A"
                    ask_str = "NaN" if (ask_val is not None and math.isnan(float(ask_val))) else str(ask_val) if ask_val is not None else "N/A"
                    
                    logger.info(
                        f"   Ticker state:\n"
                        f"   - last: {last_str}\n"
                        f"   - close: {close_str}\n"
                        f"   - bid: {bid_str}\n"
                        f"   - ask: {ask_str}\n"
                        f"   - volume: {ticker.volume if hasattr(ticker, 'volume') else 'N/A'}\n"
                        f"   - modelOption: {ticker.modelOption if hasattr(ticker, 'modelOption') else 'N/A'}"
                    )
                    
                    # Check if we have NaN values (indicates no data, market closed, or subscription issue)
                    has_nan = False
                    if last_val is not None and math.isnan(float(last_val)):
                        has_nan = True
                    if close_val is not None and math.isnan(float(close_val)):
                        has_nan = True
                    
                    if has_nan:
                        logger.warning(f"   ⚠️  Ticker contains NaN values - this indicates no market data available")
                        if not is_market_open:
                            logger.info(f"   Market is CLOSED ({market_status}) - NaN values are expected during market closure")
                        else:
                            # Only log this warning every 2 seconds to reduce spam
                            if int(waited * 2) % 4 == 0:  # Every 2 seconds
                                logger.warning(
                                    f"   Market is OPEN but ticker has NaN after {waited:.1f}s - may indicate:\n"
                                    f"   - Missing 'Market Data API Acknowledgement' in Client Portal (MOST LIKELY)\n"
                                    f"   - Subscription not active/paid for API access\n"
                                    f"   - Data not yet available (waiting for first tick)\n"
                                    f"   Continuing to wait for data/errors..."
                                )
                
                # Check for Error 354 from error callback (most reliable)
                error_354_detected = False
                error_msg = None
                executor = getattr(ib, '_executor', None)
                if ticker_req_id is not None and executor and hasattr(executor, '_market_data_errors'):
                    with executor._error_lock:
                        error_info = executor._market_data_errors.get(ticker_req_id)
                        if error_info:
                            error_code = error_info.get('code', 0)
                            error_msg = error_info.get('message', '')
                            if error_code == 354 or "354" in str(error_msg):
                                error_354_detected = True
                                logger.error(f"   ❌ ERROR 354 DETECTED via error callback (reqId={ticker_req_id})!")
                
                # Check modelOption for errors (backup method)
                if not error_354_detected and hasattr(ticker, 'modelOption') and ticker.modelOption:
                    error_msg = str(ticker.modelOption)
                    logger.info(f"   Ticker modelOption: {error_msg}")
                    if "354" in error_msg or "subscription" in error_msg.lower() or "not subscribed" in error_msg.lower():
                        error_354_detected = True
                
                # Check for other error indicators in ticker
                if not error_354_detected and hasattr(ticker, 'errorMessage') and ticker.errorMessage:
                    error_msg = str(ticker.errorMessage)
                    logger.warning(f"   ⚠️  Ticker errorMessage: {error_msg}")
                    if "354" in error_msg or "subscription" in error_msg.lower():
                        error_354_detected = True
                
                # Check marketDataType - if it's not LIVE (1), that's a problem
                if hasattr(ticker, 'marketDataType'):
                    mkt_data_type = ticker.marketDataType
                    logger.info(f"   Market data type: {mkt_data_type} (1=LIVE, 2=FROZEN, 3=DELAYED, 4=DELAYED_FROZEN)")
                    if mkt_data_type != 1:
                        logger.warning(f"   ⚠️  Market data type is {mkt_data_type}, not LIVE (1). This may indicate delayed data or subscription issue.")
                
                if error_354_detected:
                        logger.error(f"   ❌ ERROR 354 DETECTED!")
                        if not is_market_open:
                            logger.warning(
                                f"   Market is CLOSED ({market_status})\n"
                                f"   Error 354 is normal when market is closed.\n"
                                f"   Will use historical data fallback."
                            )
                        else:
                            logger.error(
                                f"   ❌ ERROR 354 - Market is OPEN but subscription not working!\n"
                                f"   \n"
                                f"   📋 CRITICAL: This usually means missing API acknowledgment!\n"
                                f"   \n"
                                f"   Steps to fix (MUST DO ALL):\n"
                                f"   1. Log into IBKR Client Portal: https://www.interactivebrokers.com/portal/\n"
                                f"   2. Go to: Settings → Account Settings → Market Data Subscriptions\n"
                                f"   3. Find 'CME Real-Time (NP,L1)' in your subscriptions\n"
                                f"   4. Look for 'Market Data API Acknowledgement' section\n"
                                f"   5. Click 'Read and Acknowledge' or 'Sign' button\n"
                                f"   6. Also check: Settings → Trading Permissions → API User Activity Certification\n"
                                f"   7. Complete any required certifications for futures/API access\n"
                                f"   8. Wait 2-3 minutes for changes to propagate\n"
                                f"   9. Restart Gateway: ./scripts/gateway/stop_ibgateway_ibc.sh && sleep 5 && ./scripts/gateway/start_ibgateway_ibc.sh\n"
                                f"   10. Wait 30 seconds for Gateway to fully connect\n"
                                f"   11. Restart service: ./scripts/lifecycle/start_nq_agent_service.sh\n"
                                f"   \n"
                                f"   Note: Subscription must be ACTIVE, PAID, and ACKNOWLEDGED for API access.\n"
                                f"   Will use historical data fallback."
                            )
                        try:
                            ib.cancelMktData(contract)
                            logger.info(f"   ✅ Cancelled market data request")
                        except Exception as cancel_e:
                            logger.warning(f"   ⚠️  Error cancelling market data: {cancel_e}")
                        ticker = None
                        break
                
                # Check if we got valid data (can exit early if data received)
                # Must check for valid price (not None, not NaN, > 0)
                if ticker:
                    last_val = ticker.last if hasattr(ticker, 'last') else None
                    close_val = ticker.close if hasattr(ticker, 'close') else None
                    if _is_valid_price(last_val) or _is_valid_price(close_val):
                        logger.info(f"   ✅ VALID DATA RECEIVED! Exiting wait loop early.")
                        break
            
            # Final check for valid data (must be valid price, not NaN)
            if ticker:
                last_val = ticker.last if hasattr(ticker, 'last') else None
                close_val = ticker.close if hasattr(ticker, 'close') else None
                
                # Get the first valid price (not None, not NaN, > 0)
                last_price = None
                if _is_valid_price(last_val):
                    last_price = float(last_val)
                elif _is_valid_price(close_val):
                    last_price = float(close_val)
                
                if last_price:
                    logger.info(f"   ✅ Processing Level 1 data...")
                    
                    # Extract all values, handling NaN properly
                    open_val = float(ticker.open) if _is_valid_price(ticker.open) else last_price
                    high_val = float(ticker.high) if _is_valid_price(ticker.high) else last_price
                    low_val = float(ticker.low) if _is_valid_price(ticker.low) else last_price
                    bid_val = float(ticker.bid) if _is_valid_price(ticker.bid) else None
                    ask_val = float(ticker.ask) if _is_valid_price(ticker.ask) else None
                    volume_val = int(ticker.volume) if ticker.volume and not math.isnan(float(ticker.volume)) else 0
                    
                    logger.info(
                        f"   Data received:\n"
                        f"   - Last: ${last_price:.2f}\n"
                        f"   - Close: ${last_price:.2f}\n"
                        f"   - Bid: ${bid_val:.2f if bid_val else 'N/A'}\n"
                        f"   - Ask: ${ask_val:.2f if ask_val else 'N/A'}\n"
                        f"   - Volume: {volume_val}\n"
                        f"   - Open: ${open_val:.2f}\n"
                        f"   - High: ${high_val:.2f}\n"
                        f"   - Low: ${low_val:.2f}"
                    )
                    
                    result = {
                        "timestamp": datetime.now(timezone.utc),
                        "open": open_val,
                        "high": high_val,
                        "low": low_val,
                        "close": last_price,
                        "volume": volume_val,
                        "bid": bid_val,
                        "ask": ask_val,
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
                    
                    # Note: For snapshot requests, we don't need to cancel (it's one-time)
                    # But we'll try anyway to be safe
                    try:
                        ib.cancelMktData(contract)
                        logger.info(f"   ✅ Cancelled market data request")
                    except Exception as cancel_e:
                        logger.debug(f"   Note: Error cancelling snapshot (may already be complete): {cancel_e}")
                    
                    logger.info(f"✅✅✅ SUCCESS: Retrieved Level 1 LIVE data for {self.symbol}: ${last_price:.2f} (bid: ${bid_val:.2f if bid_val else 'N/A'}, ask: ${ask_val:.2f if ask_val else 'N/A'})")
                    return result
                else:
                    # No valid price (all NaN or None) - snapshot request failed
                    last_val = ticker.last if hasattr(ticker, 'last') else None
                    close_val = ticker.close if hasattr(ticker, 'close') else None
                    logger.error(
                        f"   ❌ Snapshot request returned NaN/None after {waited:.1f}s:\n"
                        f"   - last: {last_val} ({'NaN' if last_val is not None and math.isnan(float(last_val)) else 'None' if last_val is None else 'valid'})\n"
                        f"   - close: {close_val} ({'NaN' if close_val is not None and math.isnan(float(close_val)) else 'None' if close_val is None else 'valid'})\n"
                        f"   - marketDataType: {ticker.marketDataType if hasattr(ticker, 'marketDataType') else 'N/A'} (1=LIVE)\n"
                        f"   \n"
                        f"   Possible causes:\n"
                        f"   1. Market is closed (check CME hours: Sun 6PM ET - Fri 5PM ET)\n"
                        f"   2. Contract expiring soon (check expiration date)\n"
                        f"   3. Subscription delay (acknowledgment may need time to propagate)\n"
                        f"   4. API connection issue (try restarting Gateway)\n"
                        f"   \n"
                        f"   Note: Your acknowledgment is signed, so this is likely a timing or market hours issue."
                    )
            else:
                logger.warning(
                    f"   ⚠️  No valid price data received after {waited:.1f}s wait\n"
                    f"   Ticker exists but has no valid price data (all NaN or None).\n"
                    f"   This may indicate:\n"
                    f"   - Market is closed ({market_status})\n"
                    f"   - Error 354 (subscription not available for API)\n"
                    f"   - Data not yet available\n"
                    f"   Will use historical data fallback."
                )
                if ticker:
                    try:
                        ib.cancelMktData(contract)
                        logger.info(f"   ✅ Cancelled market data request")
                    except Exception as cancel_e:
                        logger.debug(f"   Note: Error cancelling snapshot (may already be complete): {cancel_e}")
                    ticker = None
                    
        except Exception as e:
            logger.error(f"   ❌ EXCEPTION during Level 1 request: {e}", exc_info=True)
            error_str = str(e).lower()
            if "354" in str(e) or "subscription" in error_str:
                if not is_market_open:
                    logger.warning(
                        f"   Market is CLOSED ({market_status})\n"
                        f"   Error 354 is normal when market is closed.\n"
                        f"   Will use historical data fallback."
                    )
                else:
                    logger.error(
                        f"   ❌ ERROR 354 - Market is OPEN but subscription not working!\n"
                        f"   Will use historical data fallback."
                    )
            else:
                logger.warning(f"   Unexpected error: {e}. Will use historical data fallback.")
            if ticker:
                try:
                    ib.cancelMktData(contract)
                    logger.info(f"   ✅ Cancelled market data request")
                except Exception:
                    pass
            ticker = None

        # Fallback: Use latest historical bar if real-time data not available
        logger.info(f"📉 Step 3: Using historical data fallback for {self.symbol}")
        logger.info(f"   Reason: Level 1 real-time data not available")
        logger.info(f"   Market status: {market_status}")
        logger.info(f"   Note: Error 354 can occur when market is closed, even with active subscription")
        
        try:
            # IBKR requires duration format: integer{SPACE}unit where unit is S|D|W|M|Y (NOT H for hours!)
            # Error 162 often occurs with very short durations (5 min) when market is closed
            # Try longer durations first which are more reliable
            # Note: IBKR doesn't support "H" (hours), so we use "1 D" (1 day) for recent data
            bars = None
            used_eth = None  # Track whether ETH (False) or RTH (True) was used
            # For futures (NQ, etc.), prioritize ETH (Extended Trading Hours) to get all sessions:
            # - Asia session (evening US time)
            # - London session (early morning US time)  
            # - US session (regular trading hours)
            # For stocks, prioritize RTH (Regular Trading Hours) first
            if self.is_futures:
                duration_strategies = [
                    ("1 D", False), # 1 day with ETH (Extended Trading Hours) - includes all sessions (Asia, London, US)
                    ("1 D", True),  # 1 day with RTH - fallback if ETH fails
                    ("1 W", False), # 1 week with ETH - final fallback
                ]
            else:
                duration_strategies = [
                    ("1 D", True),   # 1 day with RTH - most reliable for recent data
                    ("1 D", False), # 1 day without RTH - if market is closed
                    ("1 W", False), # 1 week without RTH - final fallback
                ]
            
            for duration_str, use_rth in duration_strategies:
                try:
                    logger.info(f"   Trying historical data: duration={duration_str}, useRTH={use_rth}")
                    logger.info(f"   Calling ib.reqHistoricalData(contract, endDateTime='', durationStr='{duration_str}', barSizeSetting='1 min', whatToShow='TRADES', useRTH={use_rth})")
                    bars = ib.reqHistoricalData(
                        contract,
                        endDateTime="",
                        durationStr=duration_str,
                        barSizeSetting="1 min",
                        whatToShow="TRADES",
                        useRTH=use_rth,
                        formatDate=1,
                    )
                    logger.info(f"   ✅ Historical data request completed: received {len(bars) if bars else 0} bars")
                    if bars and len(bars) > 0:
                        used_eth = not use_rth  # Track whether ETH (False) or RTH (True) was used
                        logger.info(f"   ✅ SUCCESS: Retrieved {len(bars)} historical bars with {duration_str} (ETH={'Yes' if used_eth else 'No'})")
                        break  # Success, exit the loop
                    else:
                        logger.warning(f"   ⚠️  No bars returned for {duration_str}, trying next strategy...")
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
                    f"   - Level 1 subscription not available (Error 354) OR market is closed\n"
                    f"   - Historical data service unavailable (Error 162 - TWS conflict or market closed)\n"
                    f"   \n"
                    f"   📋 Immediate actions:\n"
                    f"   1. Check if market is open (CME futures: ETH Sun 6PM ET - Fri 5PM ET, Mon-Thu 5-6PM maintenance break)\n"
                    f"   2. If Error 162: Close any TWS sessions, wait 60s, restart Gateway\n"
                    f"   3. Verify Level 1 subscription is active and paid\n"
                    f"   4. Ensure 'Market Data API Acknowledgement' is signed\n"
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
                    "_historical_eth": used_eth if used_eth is not None else False,  # Track if ETH was used (includes all sessions)
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
                    f"   - Level 1 subscription not available (Error 354) OR market is closed\n"
                    f"   - Historical data service unavailable (Error 162 - TWS conflict)\n"
                    f"   \n"
                    f"   📋 Immediate actions:\n"
                    f"   1. Check if market is open (CME futures: ETH Sun 6PM ET - Fri 5PM ET, Mon-Thu 5-6PM maintenance break)\n"
                    f"   2. If Error 162: Close any TWS sessions, wait 60s, restart Gateway\n"
                    f"   3. Verify contract {contract.localSymbol if hasattr(contract, 'localSymbol') else 'N/A'} hasn't expired\n"
                    f"   4. Ensure 'Market Data API Acknowledgement' is signed\n"
                    f"   5. Restart Gateway if needed"
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
        
        # Error tracking for market data requests
        self._market_data_errors: Dict[int, Dict[str, Any]] = {}  # reqId -> error info
        self._error_lock = threading.Lock()

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

                    # Execute task (pass executor reference only for GetLatestBarTask)
                    # Check by class name since isinstance requires import
                    task_class_name = task.__class__.__name__
                    if task_class_name == "GetLatestBarTask":
                        # GetLatestBarTask needs executor for error tracking
                        result = task.execute(self.ib, executor=self)
                    else:
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
                
                # Register error handler to catch Error 354 and other market data errors
                def on_error(reqId, errorCode, errorString, contract):
                    """Handle IBKR error callbacks."""
                    error_str = str(errorString).lower()
                    if errorCode == 354 or "not subscribed" in error_str or "subscription" in error_str:
                        with self._error_lock:
                            self._market_data_errors[reqId] = {
                                "code": errorCode,
                                "message": errorString,
                                "contract": contract,
                                "timestamp": datetime.now(timezone.utc)
                            }
                        logger.error(
                            f"❌ IBKR Error {errorCode} (reqId={reqId}): {errorString}\n"
                            f"   This indicates market data subscription issue (Error 354)."
                        )
                    elif errorCode != 0:  # 0 is informational, not an error
                        logger.warning(f"IBKR Error {errorCode} (reqId={reqId}): {errorString}")
                
                self.ib.errorEvent += on_error

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
                    
                    # Verify account type (live vs paper)
                    try:
                        # Get account list to verify connection
                        accounts = self.ib.accountValues()
                        if accounts:
                            # Check if this is a paper trading account
                            # Paper accounts typically have "DU" prefix or contain "paper" in account ID
                            account_ids = [acc.account for acc in accounts if hasattr(acc, 'account')]
                            if account_ids:
                                account_id = account_ids[0]
                                is_paper = "DU" in account_id.upper() or "PAPER" in account_id.upper()
                                if is_paper:
                                    logger.warning(
                                        f"⚠️  WARNING: Connected to PAPER TRADING account ({account_id})\n"
                                        f"   To use LIVE trading, set TradingMode=live in ibkr/ibc/config-auto.ini\n"
                                        f"   Then restart Gateway: ./scripts/gateway/stop_ibgateway_ibc.sh && ./scripts/gateway/start_ibgateway_ibc.sh"
                                    )
                                else:
                                    logger.info(f"✅ Connected to LIVE account: {account_id}")
                        else:
                            logger.warning("⚠️  Could not verify account type - no account values returned")
                    except Exception as acc_e:
                        logger.warning(f"⚠️  Could not verify account type: {acc_e}")
                    
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
