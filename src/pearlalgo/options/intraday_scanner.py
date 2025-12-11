"""
Options Intraday Scanner - High-frequency scanning for QQQ and SPY options.

Provides:
- Dedicated scanner for QQQ and SPY options
- High-frequency scanning (1-5 minute intervals)
- Real-time data ingestion from Massive
- Signal detection: momentum, volatility compression, unusual option flow
- Entry and exit signal generation
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.data_providers.buffer_manager import BufferManager
from pearlalgo.monitoring.data_feed_manager import DataFeedManager
from pearlalgo.utils.market_hours import is_market_open
from pearlalgo.options.features import OptionsFeatureComputer


class OptionsIntradayScanner:
    """
    Scanner for intraday options trading on QQQ and SPY.

    Designed for high-frequency scanning with 1-5 minute intervals.
    Detects momentum, volatility compression, and unusual option flow.
    """

    def __init__(
        self,
        symbols: List[str],
        strategy: str = "momentum",
        config: Optional[Dict] = None,
        data_feed_manager: Optional[DataFeedManager] = None,
        buffer_manager: Optional[BufferManager] = None,
        data_provider=None,  # IBKRDataProvider
    ):
        """
        Initialize options intraday scanner.

        Args:
            symbols: List of underlying symbols (e.g., ["QQQ", "SPY"])
            strategy: Strategy name (default: "momentum")
            config: Configuration dictionary
            data_feed_manager: DataFeedManager instance (optional)
            buffer_manager: BufferManager instance (optional)
            data_provider: Data provider instance (optional)
        """
        self.symbols = symbols
        self.strategy = strategy
        self.config = config or {}
        self.data_feed_manager = data_feed_manager
        self.buffer_manager = buffer_manager
        self.data_provider = data_provider
        
        # Get data provider from feed manager if not provided
        if not self.data_provider and self.data_feed_manager:
            self.data_provider = self.data_feed_manager.data_provider
        
        # Initialize feature computer
        self.feature_computer = OptionsFeatureComputer(config=self.config.get("features", {}))
        
        # Load strategy parameters from config (separated from core logic)
        strategy_config = self.config.get("strategies", {}).get(strategy, {})
        self.strategy_params = {
            "momentum_threshold": strategy_config.get("momentum_threshold", 0.01),  # 1%
            "volume_threshold": strategy_config.get("volume_threshold", 1.5),  # 50% increase
            "compression_threshold": strategy_config.get("compression_threshold", 0.20),  # 20%
            "unusual_volume_threshold": strategy_config.get("unusual_volume_threshold", 1000),
            "unusual_oi_threshold": strategy_config.get("unusual_oi_threshold", 5000),
        }
        
        # Position sizing parameters
        position_config = self.config.get("position_sizing", {})
        self.position_params = {
            "max_position_size": position_config.get("max_position_size", 10),  # Max contracts
            "base_position_size": position_config.get("base_position_size", 1),  # Base contracts
            "risk_per_trade": position_config.get("risk_per_trade", 0.01),  # 1% of account
        }
        
        # Stop loss and exit parameters
        exit_config = self.config.get("exits", {})
        self.exit_params = {
            "stop_loss_pct": exit_config.get("stop_loss_pct", 0.20),  # 20% stop loss
            "take_profit_pct": exit_config.get("take_profit_pct", 0.50),  # 50% take profit
            "time_exit_hours": exit_config.get("time_exit_hours", 4),  # Exit after 4 hours
            "trailing_stop": exit_config.get("trailing_stop", False),
            "trailing_stop_pct": exit_config.get("trailing_stop_pct", 0.10),  # 10% trailing stop
        }

        logger.info(
            f"OptionsIntradayScanner initialized: symbols={symbols}, "
            f"strategy={strategy}"
        )

    async def scan(self) -> Dict:
        """
        Run a single scan cycle.

        Returns:
            Dictionary with scan results
        """
        if not is_market_open():
            logger.debug("Market closed, skipping scan")
            return {"status": "skipped", "reason": "market_closed"}

        if not self.data_provider:
            logger.error("No data provider available")
            return {"status": "error", "error": "No data provider"}

        try:
            logger.info(f"Running options intraday scan for {self.symbols}")

            signals = []
            exits = []

            for symbol in self.symbols:
                try:
                    # Add small delay between symbols to avoid rate limit bursts
                    if symbol != self.symbols[0]:
                        await asyncio.sleep(1.0)  # 1 second delay between symbols
                    
                    # Fetch latest stock price with retry
                    latest_bar = None
                    for retry in range(3):
                        latest_bar = await self.data_provider.get_latest_bar(symbol)
                        if latest_bar and latest_bar.get("close", 0) > 0:
                            break
                        if retry < 2:
                            logger.debug(f"Retrying price fetch for {symbol} (attempt {retry + 1}/3)")
                            await asyncio.sleep(2.0 * (retry + 1))  # Exponential backoff
                    
                    if not latest_bar:
                        logger.warning(f"No price data for {symbol} after retries")
                        continue

                    underlying_price = latest_bar.get("close", 0)
                    if underlying_price <= 0:
                        logger.warning(f"Invalid price for {symbol}: {underlying_price} (skipping)")
                        continue

                    # Fetch options chain filtered for intraday (0-7 DTE)
                    options_chain = await self.data_provider.get_options_chain_filtered(
                        underlying_symbol=symbol,
                        mode="intraday",
                        underlying_price=underlying_price,
                    )

                    if not options_chain:
                        logger.debug(f"No options found for {symbol}")
                        continue

                    # Generate signals based on strategy
                    signal = await self._generate_signal(
                        symbol=symbol,
                        underlying_price=underlying_price,
                        options_chain=options_chain,
                        latest_bar=latest_bar,
                    )

                    if signal and signal.get("side") != "flat":
                        # Add position sizing
                        signal = self._add_position_sizing(signal, underlying_price)
                        
                        # Add stop loss and take profit
                        signal = self._add_stops_and_targets(signal, underlying_price)
                        
                        signals.append(signal)
                        logger.info(
                            f"Generated {signal.get('side')} signal for {symbol}: "
                            f"{signal.get('option_symbol')} @ {signal.get('entry_price')}, "
                            f"size={signal.get('position_size')}, stop={signal.get('stop_loss')}, target={signal.get('take_profit')}"
                        )

                    # Check for exit conditions (will be implemented with signal tracker)
                    # TODO: Implement exit signal checking

                except Exception as e:
                    logger.error(f"Error scanning {symbol}: {e}", exc_info=True)
                    continue

            results = {
                "status": "success",
                "symbols": self.symbols,
                "signals_generated": len(signals),
                "signals": signals,
                "exits": exits,
            }

            return results

        except Exception as e:
            logger.error(f"Error in options intraday scan: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def _generate_signal(
        self,
        symbol: str,
        underlying_price: float,
        options_chain: List[Dict],
        latest_bar: Dict,
    ) -> Optional[Dict]:
        """
        Generate trading signal based on strategy.

        Args:
            symbol: Underlying symbol
            underlying_price: Current underlying price
            options_chain: Filtered options chain
            latest_bar: Latest price bar

        Returns:
            Signal dictionary or None
        """
        if self.strategy == "momentum":
            return await self._momentum_signal(
                symbol, underlying_price, options_chain, latest_bar
            )
        elif self.strategy == "volatility":
            return await self._volatility_signal(
                symbol, underlying_price, options_chain, latest_bar
            )
        elif self.strategy == "unusual_flow":
            return await self._unusual_flow_signal(
                symbol, underlying_price, options_chain, latest_bar
            )
        else:
            logger.warning(f"Unknown strategy: {self.strategy}")
            return None

    async def _momentum_signal(
        self,
        symbol: str,
        underlying_price: float,
        options_chain: List[Dict],
        latest_bar: Dict,
    ) -> Optional[Dict]:
        """
        Generate momentum-based signal.

        Detects price acceleration and volume surge.
        """
        # Get historical data for momentum calculation
        if self.buffer_manager and self.buffer_manager.has_buffer(symbol):
            buffer = self.buffer_manager.get_buffer(symbol)
            if len(buffer) < 20:
                return None

            # Calculate momentum indicators
            recent_prices = [bar["close"] for bar in buffer[-20:]]
            recent_volumes = [bar.get("volume", 0) for bar in buffer[-20:]]

            # Price momentum (rate of change)
            price_change = (recent_prices[-1] - recent_prices[-5]) / recent_prices[-5]
            volume_surge = (
                sum(recent_volumes[-5:]) / max(sum(recent_volumes[-10:-5]), 1) - 1
            )

            # Momentum threshold from config (separated from core logic)
            momentum_threshold = self.strategy_params.get("momentum_threshold", 0.01)  # 1%
            volume_threshold = self.strategy_params.get("volume_threshold", 1.5)  # 50% increase

            if price_change > momentum_threshold and volume_surge > volume_threshold:
                # Bullish momentum - look for call options
                atm_calls = [
                    opt
                    for opt in options_chain
                    if opt.get("option_type") == "call"
                    and abs(opt.get("strike", 0) - underlying_price) / underlying_price
                    < 0.05  # Within 5% of current price
                ]

                if atm_calls:
                    # Select option with highest volume
                    best_option = max(atm_calls, key=lambda x: x.get("volume", 0))
                    return {
                        "side": "long",
                        "confidence": min(0.9, 0.5 + abs(price_change) * 10),
                        "symbol": symbol,
                        "option_symbol": best_option.get("symbol"),
                        "strike": best_option.get("strike"),
                        "expiration": best_option.get("expiration"),
                        "option_type": "call",
                        "entry_price": best_option.get("last_price") or best_option.get("bid", 0),
                        "underlying_price": underlying_price,
                        "reasoning": f"Momentum signal: {price_change:.2%} price change, {volume_surge:.2%} volume surge",
                    }

            elif price_change < -momentum_threshold and volume_surge > volume_threshold:
                # Bearish momentum - look for put options
                atm_puts = [
                    opt
                    for opt in options_chain
                    if opt.get("option_type") == "put"
                    and abs(opt.get("strike", 0) - underlying_price) / underlying_price
                    < 0.05
                ]

                if atm_puts:
                    best_option = max(atm_puts, key=lambda x: x.get("volume", 0))
                    return {
                        "side": "long",  # Long put
                        "confidence": min(0.9, 0.5 + abs(price_change) * 10),
                        "symbol": symbol,
                        "option_symbol": best_option.get("symbol"),
                        "strike": best_option.get("strike"),
                        "expiration": best_option.get("expiration"),
                        "option_type": "put",
                        "entry_price": best_option.get("last_price") or best_option.get("bid", 0),
                        "underlying_price": underlying_price,
                        "reasoning": f"Momentum signal: {price_change:.2%} price change, {volume_surge:.2%} volume surge",
                    }

        return None

    async def _volatility_signal(
        self,
        symbol: str,
        underlying_price: float,
        options_chain: List[Dict],
        latest_bar: Dict,
    ) -> Optional[Dict]:
        """
        Generate volatility compression signal.

        Detects low IV periods that may lead to breakouts.
        """
        # Calculate average bid-ask spread as proxy for volatility
        spreads = []
        for opt in options_chain:
            bid = opt.get("bid", 0)
            ask = opt.get("ask", 0)
            mid = (bid + ask) / 2 if bid and ask else opt.get("last_price", 0)
            if mid > 0:
                spread_pct = (ask - bid) / mid if ask > bid else 0
                spreads.append(spread_pct)

        if not spreads:
            return None

        avg_spread = sum(spreads) / len(spreads)
        compression_threshold = self.config.get("compression_threshold", 0.20)  # 20%

        if avg_spread < compression_threshold:
            # Low volatility - look for breakout plays
            # Prefer ATM calls for upward breakouts
            atm_calls = [
                opt
                for opt in options_chain
                if opt.get("option_type") == "call"
                and abs(opt.get("strike", 0) - underlying_price) / underlying_price
                < 0.05
            ]

            if atm_calls:
                best_option = max(atm_calls, key=lambda x: x.get("volume", 0))
                return {
                    "side": "long",
                    "confidence": 0.7,
                    "symbol": symbol,
                    "option_symbol": best_option.get("symbol"),
                    "strike": best_option.get("strike"),
                    "expiration": best_option.get("expiration"),
                    "option_type": "call",
                    "entry_price": best_option.get("last_price") or best_option.get("bid", 0),
                    "underlying_price": underlying_price,
                    "reasoning": f"Volatility compression: {avg_spread:.2%} avg spread",
                }

        return None

    async def _unusual_flow_signal(
        self,
        symbol: str,
        underlying_price: float,
        options_chain: List[Dict],
        latest_bar: Dict,
    ) -> Optional[Dict]:
        """
        Generate unusual option flow signal.

        Detects volume/OI spikes that may indicate smart money activity.
        """
        # Find options with unusually high volume or OI
        volume_threshold = self.strategy_params.get("unusual_volume_threshold", 1000)
        oi_threshold = self.strategy_params.get("unusual_oi_threshold", 5000)

        unusual_options = [
            opt
            for opt in options_chain
            if (opt.get("volume", 0) > volume_threshold)
            or (opt.get("open_interest", 0) > oi_threshold)
        ]

        if unusual_options:
            # Sort by volume * OI (activity score)
            unusual_options.sort(
                key=lambda x: x.get("volume", 0) * x.get("open_interest", 0),
                reverse=True,
            )

            best_option = unusual_options[0]
            activity_score = (
                best_option.get("volume", 0) * best_option.get("open_interest", 0)
            )

            return {
                "side": "long",
                "confidence": min(0.85, 0.5 + activity_score / 100000),
                "symbol": symbol,
                "option_symbol": best_option.get("symbol"),
                "strike": best_option.get("strike"),
                "expiration": best_option.get("expiration"),
                "option_type": best_option.get("option_type"),
                "entry_price": best_option.get("last_price") or best_option.get("bid", 0),
                "underlying_price": underlying_price,
                "reasoning": f"Unusual flow: vol={best_option.get('volume')}, OI={best_option.get('open_interest')}",
            }

        return None
    
    def _add_position_sizing(self, signal: Dict, underlying_price: float) -> Dict:
        """
        Add position sizing to signal based on risk parameters.
        
        Args:
            signal: Signal dictionary
            underlying_price: Current underlying price
            
        Returns:
            Signal with position_size added
        """
        entry_price = signal.get("entry_price", 0)
        if entry_price <= 0:
            signal["position_size"] = self.position_params.get("base_position_size", 1)
            return signal
        
        # Calculate position size based on risk per trade
        # For options, we use a fixed base size with max limit
        base_size = self.position_params.get("base_position_size", 1)
        max_size = self.position_params.get("max_position_size", 10)
        
        # Adjust size based on confidence
        confidence = signal.get("confidence", 0.5)
        size_multiplier = 1.0 + (confidence - 0.5) * 2.0  # 0.5 conf = 1x, 1.0 conf = 2x
        
        position_size = int(base_size * size_multiplier)
        position_size = min(position_size, max_size)
        position_size = max(position_size, 1)  # At least 1 contract
        
        signal["position_size"] = position_size
        signal["risk_amount"] = entry_price * position_size * self.position_params.get("risk_per_trade", 0.01)
        
        return signal
    
    def _add_stops_and_targets(self, signal: Dict, underlying_price: float) -> Dict:
        """
        Add stop loss and take profit to signal.
        
        Args:
            signal: Signal dictionary
            underlying_price: Current underlying price
            
        Returns:
            Signal with stop_loss and take_profit added
        """
        entry_price = signal.get("entry_price", 0)
        if entry_price <= 0:
            return signal
        
        # Calculate stop loss and take profit as percentage of entry price
        stop_loss_pct = self.exit_params.get("stop_loss_pct", 0.20)  # 20% stop
        take_profit_pct = self.exit_params.get("take_profit_pct", 0.50)  # 50% target
        
        stop_loss = entry_price * (1 - stop_loss_pct)
        take_profit = entry_price * (1 + take_profit_pct)
        
        signal["stop_loss"] = stop_loss
        signal["take_profit"] = take_profit
        signal["stop_loss_pct"] = stop_loss_pct
        signal["take_profit_pct"] = take_profit_pct
        
        # Add time-based exit
        signal["time_exit_hours"] = self.exit_params.get("time_exit_hours", 4)
        
        # Add trailing stop if enabled
        if self.exit_params.get("trailing_stop", False):
            signal["trailing_stop"] = True
            signal["trailing_stop_pct"] = self.exit_params.get("trailing_stop_pct", 0.10)
        
        return signal

    async def scan_continuous(
        self, interval: int = 60, shutdown_check: Optional[callable] = None
    ) -> None:
        """
        Run continuous scanning with specified interval.

        Args:
            interval: Scan interval in seconds (default: 60)
            shutdown_check: Optional callable that returns True to stop
        """
        logger.info(
            f"Starting continuous options intraday scanning: "
            f"symbols={self.symbols}, interval={interval}s"
        )

        # Backfill buffers on startup
        if self.buffer_manager and self.data_provider:
            logger.info(f"Backfilling buffers for {self.symbols}...")
            await self.buffer_manager.backfill_multiple(
                self.symbols,
                timeframe="15m",
                days=30,
                data_provider=self.data_provider,
            )

        cycle_count = 0

        try:
            while True:
                if shutdown_check and shutdown_check():
                    logger.info("Shutdown requested, stopping scanner")
                    break

                cycle_count += 1
                logger.info(f"Options intraday scan cycle #{cycle_count}")

                # Run scan
                results = await self.scan()
                logger.debug(f"Scan results: {results}")

                # Wait for next cycle
                await asyncio.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Scanner interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error in scanner: {e}", exc_info=True)
            raise
        finally:
            logger.info(f"Options intraday scanner stopped after {cycle_count} cycles")
