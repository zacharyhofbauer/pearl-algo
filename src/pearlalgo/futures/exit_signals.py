"""
Exit Signal Generator - Generate exit signals based on stop/target/time rules.

Provides:
- Stop loss hit detection
- Take profit hit detection
- Time-based exits (end of day for intraday)
- Strategy-specific exit rules
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.futures.signal_tracker import SignalTracker, TrackedSignal
from pearlalgo.agents.langgraph_state import Signal, TradingState
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
    ):
        """
        Initialize exit signal generator.

        Args:
            signal_tracker: SignalTracker instance
            market_hours: MarketHours instance (optional)
            data_provider: Data provider for fallback price fetching (optional)
        """
        self.signal_tracker = signal_tracker
        self.market_hours = market_hours
        self.data_provider = data_provider

        logger.info("ExitSignalGenerator initialized")

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

    async def _fetch_fallback_price(self, symbol: str) -> Optional[float]:
        """
        Fetch current price from data provider as fallback.
        
        Args:
            symbol: Symbol to fetch price for
            
        Returns:
            Current price or None if fetch fails
        """
        if not self.data_provider:
            return None
        
        try:
            # Try to get latest bar
            if hasattr(self.data_provider, 'get_latest_bar'):
                bar = await self.data_provider.get_latest_bar(symbol, "15m")
                if bar and hasattr(bar, 'close'):
                    return float(bar.close)
            elif hasattr(self.data_provider, 'get_current_price'):
                price = await self.data_provider.get_current_price(symbol)
                if price:
                    return float(price)
            # Try synchronous methods as fallback
            elif hasattr(self.data_provider, 'get_latest_bar_sync'):
                bar = self.data_provider.get_latest_bar_sync(symbol, "15m")
                if bar and hasattr(bar, 'close'):
                    return float(bar.close)
        except Exception as e:
            logger.debug(f"Failed to fetch fallback price for {symbol}: {e}")
        
        return None

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

        for symbol, signal in active_signals.items():
            # Get current price from market data
            market_data = state.market_data.get(symbol)
            current_price = None
            
            if market_data:
                current_price = market_data.close
            else:
                # Log missing market data
                logger.warning(
                    f"Market data missing for {symbol} in state. "
                    f"Signal: {signal.direction} @ ${signal.entry_price:.2f}, "
                    f"Stop: ${signal.stop_loss:.2f if signal.stop_loss else 'N/A'}, "
                    f"Target: ${signal.take_profit:.2f if signal.take_profit else 'N/A'}"
                )
                
                # Try to fetch fallback price
                if self.data_provider:
                    logger.info(f"Attempting to fetch fallback price for {symbol}")
                    current_price = await self._fetch_fallback_price(symbol)
                    if current_price:
                        logger.info(f"Fetched fallback price for {symbol}: ${current_price:.2f}")
                    else:
                        logger.warning(f"Could not fetch fallback price for {symbol}, skipping exit check")
                        continue
                else:
                    logger.warning(
                        f"No data provider available for fallback price fetch. "
                        f"Skipping exit check for {symbol}"
                    )
                    continue

            if current_price is None:
                logger.error(f"Could not determine current price for {symbol}, skipping")
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
                    },
                    reasoning=exit_reason,
                )

                exit_signals[symbol] = exit_signal
                logger.info(
                    f"Generated exit signal for {symbol}: {exit_type} - {exit_reason}"
                )

        if exit_signals:
            logger.info(f"Generated {len(exit_signals)} exit signals")
        else:
            logger.debug("No exit conditions met for any active signals")

        return exit_signals

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
