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
        data_provider=None,  # MassiveDataProvider
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
                    # Fetch latest stock price
                    latest_bar = await self.data_provider.get_latest_bar(symbol)
                    if not latest_bar:
                        logger.warning(f"No price data for {symbol}")
                        continue

                    underlying_price = latest_bar.get("close", 0)
                    if underlying_price <= 0:
                        logger.warning(f"Invalid price for {symbol}: {underlying_price}")
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
                        signals.append(signal)
                        logger.info(
                            f"Generated {signal.get('side')} signal for {symbol}: "
                            f"{signal.get('option_symbol')} @ {signal.get('entry_price')}"
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

            # Momentum threshold from config
            momentum_threshold = self.config.get("momentum_threshold", 0.01)  # 1%
            volume_threshold = self.config.get("volume_threshold", 1.5)  # 50% increase

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
        volume_threshold = self.config.get("unusual_volume_threshold", 1000)
        oi_threshold = self.config.get("unusual_oi_threshold", 5000)

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
