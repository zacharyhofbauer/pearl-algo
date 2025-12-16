"""
NQ Intraday Signal Generator

Generates trading signals from scanner results with validation and filtering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pearlalgo.utils.logger import logger

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.scanner import NQScanner
from pearlalgo.strategies.nq_intraday.signal_quality import SignalQualityScorer


class NQSignalGenerator:
    """
    Signal generator for NQ intraday strategy.
    
    Processes scanner results and generates validated trading signals.
    """

    def __init__(
        self,
        config: Optional[NQIntradayConfig] = None,
        scanner: Optional[NQScanner] = None,
    ):
        """
        Initialize signal generator.
        
        Args:
            config: Configuration instance (optional)
            scanner: Scanner instance (optional, creates new if not provided)
        """
        self.config = config or NQIntradayConfig()
        self.scanner = scanner or NQScanner(config=self.config)
        self.quality_scorer = SignalQualityScorer(min_edge_threshold=0.55)

        # Load signal configuration
        service_config = load_service_config()
        signal_settings = service_config.get("signals", {})

        # Track recent signals to avoid duplicates
        self._recent_signals: List[Dict] = []
        self._signal_window_seconds = signal_settings.get("duplicate_window_seconds", 300)
        self._min_confidence = signal_settings.get("min_confidence", 0.50)
        self._min_risk_reward = signal_settings.get("min_risk_reward", 1.5)

        logger.info("NQSignalGenerator initialized")

    def generate(self, market_data: Dict) -> List[Dict]:
        """
        Generate trading signals from market data.
        
        Args:
            market_data: Dictionary with 'df' (DataFrame) and optionally 'latest_bar' (Dict)
            
        Returns:
            List of validated signal dictionaries
        """
        df = market_data.get("df")
        if df is None or df.empty:
            return []

        # Check market hours
        if not self.scanner.is_market_hours():
            return []

        # Get multi-timeframe data
        df_5m = market_data.get("df_5m")
        df_15m = market_data.get("df_15m")

        # Scan for signals with MTF context
        raw_signals = self.scanner.scan(df, df_5m=df_5m, df_15m=df_15m)
        
        # Log raw signal count at INFO level for observability
        logger.info(f"Raw signals from scanner: {len(raw_signals)}")
        
        # Diagnostic logging: log raw signals
        if raw_signals:
            logger.debug(f"Raw signals generated: {len(raw_signals)}")
            for raw_signal in raw_signals:
                logger.debug(
                    f"Raw signal: type={raw_signal.get('type')}, "
                    f"direction={raw_signal.get('direction')}, "
                    f"confidence={raw_signal.get('confidence', 0):.3f}, "
                    f"entry={raw_signal.get('entry_price', 0):.2f}"
                )

        # Validate and filter signals
        validated_signals = []
        for signal in raw_signals:
            if self._validate_signal(signal):
                validated_signal = self._format_signal(signal, market_data)
                if not self._is_duplicate(validated_signal):
                    logger.debug(
                        f"Signal passed validation: type={validated_signal.get('type')}, "
                        f"confidence={validated_signal.get('confidence', 0):.3f}, "
                        f"entry={validated_signal.get('entry_price', 0):.2f}"
                    )
                    # Score signal quality
                    quality_score = self.quality_scorer.score_signal(validated_signal)

                    # Only send if meets quality threshold
                    if quality_score.get("should_send", True):
                        # Add quality score to signal
                        validated_signal["quality_score"] = quality_score
                        validated_signals.append(validated_signal)
                        self._recent_signals.append(validated_signal)
                    else:
                        # Near-miss diagnostic logging: track signals that fail quality scorer
                        signal_type = validated_signal.get("type", "unknown")
                        signal_confidence = validated_signal.get("confidence", 0)
                        historical_wr = quality_score.get("historical_wr", 0)
                        meets_threshold = quality_score.get("meets_threshold", False)
                        information_ratio = quality_score.get("information_ratio", 0)
                        regime = validated_signal.get("regime", {})
                        volatility = regime.get("volatility", "normal")
                        atr_expansion = regime.get("atr_expansion", False)
                        
                        logger.info(
                            f"NEAR_MISS: quality_scorer_rejection | "
                            f"type={signal_type} | "
                            f"confidence={signal_confidence:.3f} | "
                            f"historical_wr={historical_wr:.0%} | "
                            f"meets_threshold={meets_threshold} | "
                            f"information_ratio={information_ratio:.3f} | "
                            f"volatility={volatility} | "
                            f"atr_expansion={atr_expansion}"
                        )
                        logger.debug(
                            f"Signal context: entry={validated_signal.get('entry_price', 0):.2f}, "
                            f"regime={regime.get('regime', 'unknown')}, "
                            f"indicators={validated_signal.get('indicators', {})}"
                        )

        # Clean up old signals from recent list
        self._cleanup_recent_signals()

        if validated_signals:
            logger.info(f"Generated {len(validated_signals)} validated signal(s)")

        return validated_signals

    def _validate_signal(self, signal: Dict) -> bool:
        """
        Validate a signal meets criteria.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            True if signal is valid
        """
        # Volatility-aware confidence floor: during high volatility expansion,
        # apply a floor to prevent valid structure-based signals from being
        # killed by confidence stacking penalties
        regime = signal.get("regime", {})
        volatility = regime.get("volatility", "normal")
        signal_confidence = signal.get("confidence", 0)
        atr_expansion = regime.get("atr_expansion", False)
        
        if volatility == "high" and atr_expansion:
            # Floor confidence at 0.48 during expansion (was 0.50 threshold)
            # This allows signals that get penalized down to 0.42-0.49 to still pass
            effective_confidence = max(signal_confidence, 0.48)
            if effective_confidence > signal_confidence:
                logger.debug(
                    f"Volatility expansion: applying confidence floor 0.48 "
                    f"(original: {signal_confidence:.3f}, adjusted: {effective_confidence:.3f})"
                )
                signal["confidence"] = effective_confidence
                signal_confidence = effective_confidence
        
        # Check confidence threshold
        confidence = signal_confidence
        if confidence < self._min_confidence:
            # Near-miss diagnostic logging: track signals that fail confidence threshold
            signal_type = signal.get("type", "unknown")
            logger.info(
                f"NEAR_MISS: confidence_rejection | "
                f"type={signal_type} | "
                f"confidence={confidence:.3f} | "
                f"threshold={self._min_confidence:.3f} | "
                f"gap={self._min_confidence - confidence:.3f} | "
                f"volatility={volatility} | "
                f"atr_expansion={atr_expansion}"
            )
            logger.debug(
                f"Signal context: entry={signal.get('entry_price', 0):.2f}, "
                f"regime={regime.get('regime', 'unknown')}, "
                f"indicators={signal.get('indicators', {})}"
            )
            return False

        # Check entry price is valid
        entry_price = signal.get("entry_price")
        if not entry_price or entry_price <= 0:
            logger.info(f"Signal rejected: invalid entry_price {entry_price}")
            return False

        # Check stop loss and take profit are valid
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if signal["direction"] == "long":
            if stop_loss and stop_loss >= entry_price:
                logger.info(f"Signal rejected: stop_loss {stop_loss:.2f} >= entry {entry_price:.2f} (long)")
                return False
            if take_profit and take_profit <= entry_price:
                logger.info(f"Signal rejected: take_profit {take_profit:.2f} <= entry {entry_price:.2f} (long)")
                return False
        else:  # short
            if stop_loss and stop_loss <= entry_price:
                logger.info(f"Signal rejected: stop_loss {stop_loss:.2f} <= entry {entry_price:.2f} (short)")
                return False
            if take_profit and take_profit >= entry_price:
                logger.info(f"Signal rejected: take_profit {take_profit:.2f} >= entry {entry_price:.2f} (short)")
                return False

        # Validate risk/reward ratio meets minimum
        if stop_loss and take_profit:
            if signal["direction"] == "long":
                risk = entry_price - stop_loss
                reward = take_profit - entry_price
            else:
                risk = stop_loss - entry_price
                reward = entry_price - take_profit

            if risk > 0:
                risk_reward = reward / risk
                if risk_reward < self._min_risk_reward:
                    # Near-miss diagnostic logging: track signals that fail R:R threshold
                    signal_type = signal.get("type", "unknown")
                    logger.info(
                        f"NEAR_MISS: risk_reward_rejection | "
                        f"type={signal_type} | "
                        f"risk_reward={risk_reward:.2f}:1 | "
                        f"threshold={self._min_risk_reward:.2f}:1 | "
                        f"gap={self._min_risk_reward - risk_reward:.2f} | "
                        f"entry={entry_price:.2f} | "
                        f"stop={stop_loss:.2f} | "
                        f"target={take_profit:.2f}"
                    )
                    return False

        return True

    def _format_signal(self, signal: Dict, market_data: Dict) -> Dict:
        """
        Format signal with additional metadata.
        
        Args:
            signal: Raw signal dictionary
            market_data: Market data context
            
        Returns:
            Formatted signal dictionary
        """
        formatted = signal.copy()

        # Add metadata
        formatted["symbol"] = self.config.symbol
        formatted["timestamp"] = datetime.now(timezone.utc).isoformat()
        formatted["strategy"] = "nq_intraday"
        formatted["timeframe"] = self.config.timeframe

        # Calculate risk amount and expected hold time
        entry_price = signal.get("entry_price", 0)
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if entry_price > 0 and stop_loss:
            # Calculate risk amount based on contract type
            # MNQ: $2 per point, NQ: $20 per point
            tick_value = getattr(self.config, 'tick_value', 2.0 if self.config.symbol == "MNQ" else 20.0)
            position_size = getattr(self.config, 'max_position_size', 10)

            if signal["direction"] == "long":
                risk_points = abs(entry_price - stop_loss)
            else:
                risk_points = abs(stop_loss - entry_price)

            # Risk = points * tick_value * contracts
            risk_amount = risk_points * tick_value * position_size
            formatted["risk_amount"] = risk_amount
            formatted["position_size"] = position_size
            formatted["tick_value"] = tick_value

        # Expected hold time (prop firm style: quick scalps 5-15 min, swings 15-60 min)
        # For scalping with tighter stops, expect faster exits
        if self.config.stop_loss_atr_multiplier <= 1.5:
            formatted["expected_hold_minutes"] = 10  # Quick scalps
        else:
            formatted["expected_hold_minutes"] = 30  # Intraday swings

        # Add market context
        latest_bar = market_data.get("latest_bar")
        df = market_data.get("df")
        if latest_bar:
            formatted["market_data"] = {
                "price": latest_bar.get("close"),
                "volume": latest_bar.get("volume"),
                "bid": latest_bar.get("bid"),
                "ask": latest_bar.get("ask"),
            }

        # Add indicator values for context
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            formatted["indicators"] = {
                "rsi": float(latest.get("rsi", 0)) if "rsi" in latest else None,
                "atr": float(latest.get("atr", 0)) if "atr" in latest else None,
                "volume_ratio": float(latest.get("volume_ratio", 0)) if "volume_ratio" in latest else None,
                "macd_histogram": float(latest.get("macd_histogram", 0)) if "macd_histogram" in latest else None,
            }

        return formatted

    def _is_duplicate(self, signal: Dict) -> bool:
        """
        Check if signal is a duplicate of a recent signal.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            True if duplicate
        """
        signal_time = datetime.fromisoformat(signal.get("timestamp", datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
        signal_entry = signal.get("entry_price", 0)

        for recent in self._recent_signals:
            recent_time = datetime.fromisoformat(recent.get("timestamp", "").replace("Z", "+00:00"))
            time_diff = (signal_time - recent_time).total_seconds()
            recent_entry = recent.get("entry_price", 0)

            # Check if same type and direction within time window
            same_type = recent.get("type") == signal.get("type")
            same_direction = recent.get("direction") == signal.get("direction")
            within_time_window = time_diff < self._signal_window_seconds

            # Also check if price is too close (within 0.5% for same signal)
            price_close = False
            if recent_entry > 0 and signal_entry > 0:
                price_diff_pct = abs(signal_entry - recent_entry) / recent_entry
                price_close = price_diff_pct < 0.005  # 0.5%

            if same_type and same_direction and (within_time_window or price_close):
                return True

        return False

    def _cleanup_recent_signals(self) -> None:
        """Remove old signals from recent signals list."""
        now = datetime.now(timezone.utc)
        self._recent_signals = [
            s for s in self._recent_signals
            if (now - datetime.fromisoformat(s["timestamp"].replace("Z", "+00:00"))).total_seconds()
            < self._signal_window_seconds
        ]
