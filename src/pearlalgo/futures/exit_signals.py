"""
Exit Signal Generator - Generate exit signals based on stop/target/time rules.

Provides:
- Stop loss hit detection
- Take profit hit detection
- Time-based exits (end of day for intraday)
- Strategy-specific exit rules
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.futures.signal_tracker import SignalTracker, TrackedSignal
from pearlalgo.futures.signal_deduplicator import SignalDeduplicator
from pearlalgo.agents.langgraph_state import Signal, TradingState, MarketData
from pearlalgo.utils.market_hours import MarketHours


class ExitSignalGenerator:
    """
    Generate exit signals for active positions.

    Checks:
    - Stop loss hit
    - Take profit hit
    - Time-based exits (end of day for intraday strategies)
    - Strategy-specific exit rules
    """

    def __init__(
        self,
        signal_tracker: SignalTracker,
        market_hours: Optional[MarketHours] = None,
        data_provider=None,  # For fallback price fetching
        fallback_providers: Optional[List] = None,  # Additional fallback providers
        price_fetch_timeout: float = 5.0,  # Timeout for price fetching in seconds
        max_stale_data_minutes: int = 15,  # Max age for market data to be considered fresh
        enable_deduplication: bool = True,  # Enable exit signal deduplication
        telegram_alerts=None,  # Optional TelegramAlerts instance
    ):
        """
        Initialize exit signal generator.

        Args:
            signal_tracker: SignalTracker instance
            market_hours: MarketHours instance (optional)
            data_provider: Primary data provider for fallback price fetching (optional)
            fallback_providers: Additional fallback data providers to try (optional)
            price_fetch_timeout: Timeout for async price fetching in seconds (default: 5.0)
            max_stale_data_minutes: Maximum age in minutes for market data to be considered fresh (default: 15)
            enable_deduplication: Enable exit signal deduplication (default: True)
            telegram_alerts: Optional TelegramAlerts instance for sending notifications
        """
        self.signal_tracker = signal_tracker
        self.market_hours = market_hours
        self.data_provider = data_provider
        self.fallback_providers = fallback_providers or []
        self.price_fetch_timeout = price_fetch_timeout
        self.max_stale_data_minutes = max_stale_data_minutes
        self.telegram_alerts = telegram_alerts
        
        # Exit signal deduplication
        self.exit_deduplicator = SignalDeduplicator(window_minutes=5) if enable_deduplication else None
        
        # Price cache for optimization
        self._price_cache: OrderedDict[str, tuple[float, datetime]] = OrderedDict()
        self._price_cache_ttl = timedelta(minutes=1)  # Cache TTL
        self._max_cache_size = 100  # Maximum cache entries
        
        # Metrics tracking
        self.exit_generation_count = 0
        self.exit_success_count = 0
        self.fallback_fetch_attempts = 0
        self.fallback_fetch_success = 0
        self.price_validation_failures = 0
        self.stale_data_warnings = 0
        self.cache_hits = 0
        self.cache_misses = 0

        logger.info("ExitSignalGenerator initialized")
    
    def _validate_price(self, price: Optional[float], symbol: str, context: str = "") -> bool:
        """
        Validate price value for reasonableness with symbol-specific ranges.
        
        Args:
            price: Price to validate
            symbol: Symbol for context in logging
            context: Additional context for logging
            
        Returns:
            True if price is valid, False otherwise
        """
        if price is None:
            logger.warning(f"Price validation failed for {symbol}: None value {context}")
            self.price_validation_failures += 1
            return False
        
        if math.isnan(price) or math.isinf(price):
            logger.warning(f"Price validation failed for {symbol}: NaN or Inf value {context}")
            self.price_validation_failures += 1
            return False
        
        if price <= 0:
            logger.warning(f"Price validation failed for {symbol}: non-positive price ${price:.2f} {context}")
            self.price_validation_failures += 1
            return False
        
        if price > 1e6:  # Unreasonably high price
            logger.warning(f"Price validation failed for {symbol}: unreasonably high price ${price:.2f} {context}")
            self.price_validation_failures += 1
            return False
        
        # Symbol-specific price range validation for common futures
        symbol_ranges = {
            "ES": (3000.0, 7000.0),  # E-mini S&P 500
            "MES": (3000.0, 7000.0),  # Micro E-mini S&P 500
            "NQ": (10000.0, 25000.0),  # E-mini Nasdaq
            "MNQ": (10000.0, 25000.0),  # Micro E-mini Nasdaq
            "YM": (30000.0, 45000.0),  # E-mini Dow
            "MYM": (30000.0, 45000.0),  # Micro E-mini Dow
            "RTY": (1500.0, 3000.0),  # E-mini Russell 2000
            "M2K": (1500.0, 3000.0),  # Micro E-mini Russell 2000
        }
        
        # Check symbol-specific range
        base_symbol = symbol.split()[0] if " " in symbol else symbol
        if base_symbol in symbol_ranges:
            min_price, max_price = symbol_ranges[base_symbol]
            if price < min_price or price > max_price:
                logger.warning(
                    f"Price validation failed for {symbol}: price ${price:.2f} outside expected range "
                    f"${min_price:.2f}-${max_price:.2f} {context}"
                )
                self.price_validation_failures += 1
                return False
        
        return True
    
    def _is_stale_data(self, market_data: Optional[MarketData], symbol: str) -> bool:
        """
        Check if market data is stale.
        
        Args:
            market_data: MarketData to check
            symbol: Symbol for context
            
        Returns:
            True if data is stale, False otherwise
        """
        if not market_data:
            return True
        
        if not hasattr(market_data, 'timestamp') or not market_data.timestamp:
            logger.warning(f"Market data for {symbol} has no timestamp")
            return True
        
        now = datetime.now(timezone.utc)
        if isinstance(market_data.timestamp, str):
            try:
                data_time = datetime.fromisoformat(market_data.timestamp.replace('Z', '+00:00'))
            except Exception:
                logger.warning(f"Could not parse timestamp for {symbol}: {market_data.timestamp}")
                return True
        else:
            data_time = market_data.timestamp
        
        age = now - data_time
        max_age = timedelta(minutes=self.max_stale_data_minutes)
        
        if age > max_age:
            self.stale_data_warnings += 1
            logger.warning(
                f"Stale market data for {symbol}: age {age.total_seconds()/60:.1f} minutes "
                f"(max: {self.max_stale_data_minutes} minutes)"
            )
            return True
        
        return False

    def check_stop_loss(
        self, signal: TrackedSignal, current_price: float
    ) -> bool:
        """
        Check if stop loss has been hit.

        Args:
            signal: TrackedSignal
            current_price: Current market price

        Returns:
            True if stop loss hit
        """
        if not signal.stop_loss:
            return False

        if signal.direction == "long":
            return current_price <= signal.stop_loss
        else:  # short
            return current_price >= signal.stop_loss

    def check_take_profit(
        self, signal: TrackedSignal, current_price: float
    ) -> bool:
        """
        Check if take profit has been hit.

        Args:
            signal: TrackedSignal
            current_price: Current market price

        Returns:
            True if take profit hit
        """
        if not signal.take_profit:
            return False

        if signal.direction == "long":
            return current_price >= signal.take_profit
        else:  # short
            return current_price <= signal.take_profit

    def check_time_exit(
        self,
        signal: TrackedSignal,
        strategy_name: str,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """
        Check if time-based exit should trigger.

        For intraday strategies, exit at end of trading day.

        Args:
            signal: TrackedSignal
            strategy_name: Strategy name (e.g., "intraday_swing")
            current_time: Current time (default: now)

        Returns:
            True if time exit should trigger
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # Intraday strategies: exit at end of day
        if "intraday" in strategy_name.lower():
            try:
                import pytz
                et_timezone = pytz.timezone("America/New_York")
                et_time = current_time.astimezone(et_timezone)
                
                # Exit at 4:30 PM ET (30 min before 5 PM close) or later
                # Also exit on Friday at 4:30 PM (futures close)
                if et_time.hour == 16 and et_time.minute >= 30:
                    # Check if it's Friday (futures close)
                    if et_time.weekday() == 4:  # Friday
                        return True
                    # For other days, exit at 4:30 PM ET
                    return True
                
                # Also exit if it's past 5 PM ET (market closed)
                if et_time.hour >= 17:
                    return True
            except ImportError:
                logger.warning("pytz not available, using simplified time check")
                # Fallback: exit at 4:30 PM UTC (approximate)
                if current_time.hour >= 20:  # 4:30 PM ET ≈ 8:30 PM UTC
                    return True

        return False
    
    def _get_cached_price(self, symbol: str) -> Optional[float]:
        """
        Get price from cache if available and fresh.
        
        Args:
            symbol: Symbol to get price for
            
        Returns:
            Cached price or None if not in cache or stale
        """
        if symbol not in self._price_cache:
            self.cache_misses += 1
            return None
        
        price, timestamp = self._price_cache[symbol]
        age = datetime.now(timezone.utc) - timestamp
        
        if age > self._price_cache_ttl:
            # Cache entry is stale, remove it
            del self._price_cache[symbol]
            self.cache_misses += 1
            return None
        
        # Move to end (LRU)
        self._price_cache.move_to_end(symbol)
        self.cache_hits += 1
        return price
    
    def _cache_price(self, symbol: str, price: float) -> None:
        """
        Cache price for symbol.
        
        Args:
            symbol: Symbol
            price: Price to cache
        """
        # Remove oldest entries if cache is full
        while len(self._price_cache) >= self._max_cache_size:
            self._price_cache.popitem(last=False)  # Remove oldest
        
        # Add to cache
        self._price_cache[symbol] = (price, datetime.now(timezone.utc))
    
    async def _fetch_price_from_provider(self, provider, symbol: str) -> Optional[float]:
        """
        Fetch price from a single provider with timeout.
        
        Args:
            provider: Data provider instance
            symbol: Symbol to fetch price for
            
        Returns:
            Current price or None if fetch fails
        """
        try:
            # Try async methods first
            if hasattr(provider, 'get_latest_bar'):
                try:
                    # Check if it's async
                    import inspect
                    is_async = inspect.iscoroutinefunction(provider.get_latest_bar)
                    
                    if is_async:
                        bar = await asyncio.wait_for(
                            provider.get_latest_bar(symbol),  # Only symbol, no timeframe
                            timeout=self.price_fetch_timeout
                        )
                    else:
                        # Synchronous method
                        bar = provider.get_latest_bar(symbol)  # Only symbol, no timeframe
                    
                    if bar:
                        # Handle different return types
                        if isinstance(bar, dict):
                            # Polygon returns dict with 'close' or 'c' key
                            price = float(bar.get('close', bar.get('c', 0)))
                        elif hasattr(bar, 'close'):
                            price = float(bar.close)
                        elif hasattr(bar, '__getitem__'):
                            # Try to get close price from Series or similar
                            try:
                                if 'close' in bar:
                                    price = float(bar['close'])
                                elif hasattr(bar, 'iloc'):
                                    price = float(bar.iloc[-1])
                                else:
                                    price = float(bar[0])
                            except:
                                price = None
                        else:
                            price = None
                        
                        if price and self._validate_price(price, symbol, f"from {type(provider).__name__}"):
                            return price
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout fetching price for {symbol} from {type(provider).__name__}")
                except Exception as e:
                    logger.debug(f"Error fetching price for {symbol} from {type(provider).__name__}: {e}")
            
            if hasattr(provider, 'get_current_price'):
                try:
                    price = await asyncio.wait_for(
                        provider.get_current_price(symbol),
                        timeout=self.price_fetch_timeout
                    )
                    if price:
                        price_float = float(price)
                        if self._validate_price(price_float, symbol, f"from {type(provider).__name__}"):
                            return price_float
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout fetching current price for {symbol} from {type(provider).__name__}")
                except Exception as e:
                    logger.debug(f"Error fetching current price for {symbol} from {type(provider).__name__}: {e}")
            
            # Try synchronous methods as fallback (if not already tried)
            if hasattr(provider, 'get_latest_bar_sync'):
                try:
                    bar = provider.get_latest_bar_sync(symbol)  # Only symbol, no timeframe
                    if bar:
                        # Handle different return types
                        if isinstance(bar, dict):
                            price = float(bar.get('close', bar.get('c', 0)))
                        elif hasattr(bar, 'close'):
                            price = float(bar.close)
                        elif hasattr(bar, '__getitem__'):
                            try:
                                if 'close' in bar:
                                    price = float(bar['close'])
                                elif hasattr(bar, 'iloc'):
                                    price = float(bar.iloc[-1])
                                else:
                                    price = float(bar[0])
                            except:
                                price = None
                        else:
                            price = None
                        
                        if price and self._validate_price(price, symbol, f"from {type(provider).__name__} (sync)"):
                            return price
                except Exception as e:
                    logger.debug(f"Error fetching sync price for {symbol} from {type(provider).__name__}: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error fetching price for {symbol} from {type(provider).__name__}: {e}")
        
        return None
    
    async def _fetch_fallback_price(self, symbol: str, max_retries: int = 2) -> Optional[float]:
        """
        Fetch current price from data providers as fallback with multiple attempts.
        
        Args:
            symbol: Symbol to fetch price for
            max_retries: Maximum number of retry attempts per provider
            
        Returns:
            Current price or None if all attempts fail
        """
        # Check cache first
        cached_price = self._get_cached_price(symbol)
        if cached_price is not None:
            logger.debug(f"Using cached price for {symbol}: ${cached_price:.2f}")
            return cached_price
        
        # Collect all providers to try
        providers_to_try = []
        if self.data_provider:
            providers_to_try.append(self.data_provider)
        providers_to_try.extend(self.fallback_providers)
        
        if not providers_to_try:
            return None
        
        self.fallback_fetch_attempts += 1
        
        # Try each provider with retries
        for provider in providers_to_try:
            for attempt in range(max_retries):
                try:
                    price = await self._fetch_price_from_provider(provider, symbol)
                    if price is not None:
                        # Cache the price
                        self._cache_price(symbol, price)
                        self.fallback_fetch_success += 1
                        logger.info(
                            f"Fetched fallback price for {symbol}: ${price:.2f} "
                            f"from {type(provider).__name__} (attempt {attempt + 1})"
                        )
                        # Log if price seems suspicious for futures
                        if symbol in ["ES", "MES", "NQ", "MNQ"] and price < 100:
                            logger.warning(
                                f"Suspiciously low price ${price:.2f} for {symbol} from {type(provider).__name__}. "
                                f"This may indicate incorrect data source or symbol format."
                            )
                        return price
                except Exception as e:
                    logger.debug(f"Attempt {attempt + 1} failed for {symbol} from {type(provider).__name__}: {e}")
                
                # Wait before retry (exponential backoff)
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (2 ** attempt))
        
        logger.warning(f"Could not fetch fallback price for {symbol} from any provider")
        return None
    
    async def _fetch_prices_parallel(self, symbols: List[str]) -> Dict[str, Optional[float]]:
        """
        Fetch prices for multiple symbols in parallel.
        
        Args:
            symbols: List of symbols to fetch prices for
            
        Returns:
            Dictionary of symbol -> price (or None if fetch failed)
        """
        # Check cache first
        results = {}
        symbols_to_fetch = []
        
        for symbol in symbols:
            cached_price = self._get_cached_price(symbol)
            if cached_price is not None:
                results[symbol] = cached_price
            else:
                symbols_to_fetch.append(symbol)
        
        if not symbols_to_fetch:
            return results
        
        # Fetch remaining symbols in parallel
        fetch_tasks = [
            self._fetch_fallback_price(symbol, max_retries=1)  # Single retry for parallel fetches
            for symbol in symbols_to_fetch
        ]
        
        fetched_prices = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        
        for symbol, price in zip(symbols_to_fetch, fetched_prices):
            if isinstance(price, Exception):
                logger.debug(f"Error fetching price for {symbol}: {price}")
                results[symbol] = None
            else:
                results[symbol] = price
        
        return results

    async def generate_exit_signals(
        self, state: TradingState
    ) -> Dict[str, Signal]:
        """
        Generate exit signals for all active tracked signals.

        Args:
            state: TradingState with current market data

        Returns:
            Dictionary of symbol -> exit Signal
        """
        exit_signals = {}

        # Get all active signals
        active_signals = self.signal_tracker.get_all_signals()
        
        if not active_signals:
            logger.debug("No active signals to check for exits")
            return exit_signals

        logger.debug(f"Checking exit conditions for {len(active_signals)} active signals")
        
        self.exit_generation_count += 1

        # Fetch prices in parallel for symbols missing market data
        symbols_needing_fallback = []
        for symbol, signal in active_signals.items():
            market_data = state.market_data.get(symbol)
            if not market_data or self._is_stale_data(market_data, symbol):
                symbols_needing_fallback.append(symbol)
        
        # Parallel fetch for missing prices
        fallback_prices = {}
        if symbols_needing_fallback:
            fallback_prices = await self._fetch_prices_parallel(symbols_needing_fallback)

        for symbol, signal in active_signals.items():
            # Get current price from market data
            market_data = state.market_data.get(symbol)
            current_price = None
            price_source = "state"
            
            if market_data:
                # Check if data is stale
                if self._is_stale_data(market_data, symbol):
                    logger.warning(f"Market data for {symbol} is stale, attempting fallback")
                    market_data = None  # Force fallback
                else:
                    current_price = market_data.close
                    # Validate price from state
                    if not self._validate_price(current_price, symbol, "from state"):
                        logger.warning(f"Invalid price from state for {symbol}, attempting fallback")
                        current_price = None
                        market_data = None
            
            if not market_data or current_price is None:
                # Log missing market data
                stop_str = f"${signal.stop_loss:.2f}" if signal.stop_loss else "N/A"
                target_str = f"${signal.take_profit:.2f}" if signal.take_profit else "N/A"
                logger.warning(
                    f"Market data missing for {symbol} in state. "
                    f"Signal: {signal.direction} @ ${signal.entry_price:.2f}, "
                    f"Stop: {stop_str}, "
                    f"Target: {target_str}"
                )
                
                # Try to get from parallel fetch results first
                if symbol in fallback_prices:
                    current_price = fallback_prices[symbol]
                    if current_price:
                        price_source = "fallback_parallel"
                        logger.info(f"Got fallback price for {symbol} from parallel fetch: ${current_price:.2f}")
                    else:
                        logger.warning(f"Could not fetch fallback price for {symbol}, skipping exit check")
                        continue
                else:
                    # Fallback to individual fetch
                    logger.info(f"Attempting to fetch fallback price for {symbol}")
                    current_price = await self._fetch_fallback_price(symbol)
                    if current_price:
                        price_source = "fallback"
                        logger.info(f"Fetched fallback price for {symbol}: ${current_price:.2f}")
                    else:
                        logger.warning(f"Could not fetch fallback price for {symbol}, skipping exit check")
                        continue

            if current_price is None:
                logger.error(f"Could not determine current price for {symbol}, skipping")
                continue
            
            # Final price validation
            if not self._validate_price(current_price, symbol, f"final check ({price_source})"):
                logger.error(f"Price validation failed for {symbol} after all attempts, skipping")
                continue

            exit_reason = None
            exit_type = None

            # Check stop loss
            if self.check_stop_loss(signal, current_price):
                exit_reason = (
                    f"Stop loss hit: ${current_price:.2f} "
                    f"{'<=' if signal.direction == 'long' else '>='} ${signal.stop_loss:.2f}"
                )
                exit_type = "stop_loss"
                logger.info(f"Stop loss hit for {symbol}: {exit_reason}")

            # Check take profit
            elif self.check_take_profit(signal, current_price):
                exit_reason = (
                    f"Take profit hit: ${current_price:.2f} "
                    f"{'>=' if signal.direction == 'long' else '<='} ${signal.take_profit:.2f}"
                )
                exit_type = "take_profit"
                logger.info(f"Take profit hit for {symbol}: {exit_reason}")

            # Check time exit
            elif self.check_time_exit(signal, signal.strategy_name):
                exit_reason = "Time-based exit: End of trading day"
                exit_type = "time_exit"
                logger.info(f"Time exit for {symbol}: {exit_reason}")

            # Create exit signal if any condition met
            if exit_reason:
                # Check for duplicate exit signals
                if self.exit_deduplicator:
                    if self.exit_deduplicator.is_duplicate(
                        symbol=symbol,
                        direction=signal.direction,
                        price=current_price,
                        strategy=signal.strategy_name,
                        price_bucket_size=10.0,
                    ):
                        logger.debug(f"Skipping duplicate exit signal for {symbol}")
                        continue
                
                exit_signal = Signal(
                    symbol=symbol,
                    timestamp=datetime.now(timezone.utc),
                    side="flat",  # Exit signal
                    strategy_name=signal.strategy_name,
                    confidence=1.0,  # Exit signals are certain
                    entry_price=current_price,  # Exit price
                    stop_loss=None,
                    take_profit=None,
                    indicators={
                        "exit_type": exit_type,
                        "exit_reason": exit_reason,
                        "entry_price": signal.entry_price,
                        "unrealized_pnl": signal.unrealized_pnl,
                        "price_source": price_source,
                    },
                    reasoning=exit_reason,
                )

                exit_signals[symbol] = exit_signal
                self.exit_success_count += 1
                logger.info(
                    f"Generated exit signal for {symbol}: {exit_type} - {exit_reason} "
                    f"(price from {price_source})"
                )
                
                # Send Telegram alert for exit
                if self.telegram_alerts:
                    try:
                        # Calculate realized P&L
                        direction_multiplier = 1 if signal.direction == "long" else -1
                        realized_pnl = direction_multiplier * signal.size * (current_price - signal.entry_price)
                        
                        # Calculate hold duration
                        hold_duration = None
                        if signal.timestamp:
                            duration = datetime.now(timezone.utc) - signal.timestamp
                            hours = int(duration.total_seconds() // 3600)
                            minutes = int((duration.total_seconds() % 3600) // 60)
                            hold_duration = f"{hours}:{minutes:02d}:00" if hours > 0 else f"{minutes}:00"
                        
                        # Use asyncio to send alert
                        import asyncio
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(
                                self.telegram_alerts.notify_exit(
                                    symbol=symbol,
                                    direction=signal.direction,
                                    entry_price=signal.entry_price,
                                    exit_price=current_price,
                                    size=signal.size,
                                    realized_pnl=realized_pnl,
                                    hold_duration=hold_duration,
                                    exit_reason=exit_reason,
                                )
                            )
                        else:
                            asyncio.run(
                                self.telegram_alerts.notify_exit(
                                    symbol=symbol,
                                    direction=signal.direction,
                                    entry_price=signal.entry_price,
                                    exit_price=current_price,
                                    size=signal.size,
                                    realized_pnl=realized_pnl,
                                    hold_duration=hold_duration,
                                    exit_reason=exit_reason,
                                )
                            )
                    except Exception as e:
                        logger.warning(f"Failed to send Telegram alert for exit: {e}")

        if exit_signals:
            logger.info(f"Generated {len(exit_signals)} exit signals")
        else:
            logger.debug("No exit conditions met for any active signals")

        return exit_signals
    
    def get_exit_metrics(self) -> Dict:
        """
        Get exit signal generation metrics.
        
        Returns:
            Dictionary with exit signal statistics
        """
        total_attempts = self.exit_generation_count
        success_rate = (
            self.exit_success_count / total_attempts
            if total_attempts > 0 else 0.0
        )
        
        fallback_success_rate = (
            self.fallback_fetch_success / self.fallback_fetch_attempts
            if self.fallback_fetch_attempts > 0 else 0.0
        )
        
        metrics = {
            "exit_generation": {
                "total_attempts": total_attempts,
                "successful_exits": self.exit_success_count,
                "success_rate": success_rate,
            },
            "fallback_fetching": {
                "total_attempts": self.fallback_fetch_attempts,
                "successful_fetches": self.fallback_fetch_success,
                "success_rate": fallback_success_rate,
            },
            "data_quality": {
                "price_validation_failures": self.price_validation_failures,
                "stale_data_warnings": self.stale_data_warnings,
            },
            "price_cache": {
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_size": len(self._price_cache),
                "hit_rate": (
                    self.cache_hits / (self.cache_hits + self.cache_misses)
                    if (self.cache_hits + self.cache_misses) > 0 else 0.0
                ),
            },
        }
        
        return metrics

    def update_tracked_pnl(self, state: TradingState) -> None:
        """
        Update PnL for all tracked signals.

        Args:
            state: TradingState with current market data
        """
        prices = {
            symbol: md.close
            for symbol, md in state.market_data.items()
        }
        
        # Also update PnL for signals without market data (use last known price)
        active_signals = self.signal_tracker.get_all_signals()
        for symbol in active_signals:
            if symbol not in prices:
                # Try to get price from signal's last update or entry price
                signal = active_signals[symbol]
                # Use entry price as fallback (will be updated when price available)
                logger.debug(f"No market data for {symbol}, using entry price for PnL calculation")
        
        self.signal_tracker.update_all_pnl(prices)
