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
    ):
        """
        Initialize exit signal generator.

        Args:
            signal_tracker: SignalTracker instance
            market_hours: MarketHours instance (optional)
        """
        self.signal_tracker = signal_tracker
        self.market_hours = market_hours

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
            if self.market_hours:
                # Check if market is closing soon (within 30 minutes)
                # For futures, market closes at 5 PM ET on Friday
                # For simplicity, exit 30 minutes before market close
                # In practice, you'd check actual market close time
                return False  # Simplified - implement actual time check
            else:
                # Without market hours, use simple time check
                # Exit at 4:30 PM ET (30 min before 5 PM close)
                et_time = current_time.astimezone(
                    __import__("pytz").timezone("America/New_York")
                )
                if et_time.hour == 16 and et_time.minute >= 30:
                    return True

        return False

    def generate_exit_signals(
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

        for symbol, signal in active_signals.items():
            # Get current price from market data
            market_data = state.market_data.get(symbol)
            if not market_data:
                continue

            current_price = market_data.close
            exit_reason = None
            exit_type = None

            # Check stop loss
            if self.check_stop_loss(signal, current_price):
                exit_reason = f"Stop loss hit: ${current_price:.2f} <= ${signal.stop_loss:.2f}"
                exit_type = "stop_loss"
                logger.info(f"Stop loss hit for {symbol}: {exit_reason}")

            # Check take profit
            elif self.check_take_profit(signal, current_price):
                exit_reason = f"Take profit hit: ${current_price:.2f} >= ${signal.take_profit:.2f}"
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
        self.signal_tracker.update_all_pnl(prices)
