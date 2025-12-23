"""
NQ Intraday Signal Generator

Generates trading signals from scanner results with validation and filtering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from pearlalgo.utils.logger import logger

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.scanner import NQScanner
from pearlalgo.strategies.nq_intraday.signal_quality import SignalQualityScorer


@dataclass
class SignalDiagnostics:
    """Per-cycle diagnostics for signal generation.
    
    Tracks why signals were or weren't generated for observability.
    """
    
    # Counts
    raw_signals: int = 0
    validated_signals: int = 0
    duplicates_filtered: int = 0
    
    # Rejection reasons
    rejected_market_hours: bool = False  # Filtered by market hours gate
    rejected_confidence: int = 0  # Below min_confidence
    rejected_risk_reward: int = 0  # Below min_risk_reward
    rejected_quality_scorer: int = 0  # Failed quality score threshold
    rejected_order_book: int = 0  # Filtered by order book imbalance
    rejected_invalid_prices: int = 0  # Invalid entry/stop/target prices
    
    # Context
    market_hours_checked: bool = False
    order_book_available: bool = False
    timestamp: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for state persistence."""
        return {
            "raw_signals": self.raw_signals,
            "validated_signals": self.validated_signals,
            "duplicates_filtered": self.duplicates_filtered,
            "rejected_market_hours": self.rejected_market_hours,
            "rejected_confidence": self.rejected_confidence,
            "rejected_risk_reward": self.rejected_risk_reward,
            "rejected_quality_scorer": self.rejected_quality_scorer,
            "rejected_order_book": self.rejected_order_book,
            "rejected_invalid_prices": self.rejected_invalid_prices,
            "market_hours_checked": self.market_hours_checked,
            "order_book_available": self.order_book_available,
            "timestamp": self.timestamp,
        }
    
    def format_compact(self) -> str:
        """
        Format as compact string for Telegram dashboard.
        
        Returns a one-line summary like:
        "Raw: 3 → Valid: 1 | Filtered: 1 dup, 1 conf"
        """
        if self.rejected_market_hours:
            return "Session closed"
        
        if self.raw_signals == 0:
            return "No patterns detected"
        
        parts = []
        
        # Main flow
        parts.append(f"Raw: {self.raw_signals}")
        if self.validated_signals > 0:
            parts.append(f"→ Valid: {self.validated_signals}")
        
        # Rejections
        rejections = []
        if self.duplicates_filtered > 0:
            rejections.append(f"{self.duplicates_filtered} dup")
        if self.rejected_confidence > 0:
            rejections.append(f"{self.rejected_confidence} conf")
        if self.rejected_risk_reward > 0:
            rejections.append(f"{self.rejected_risk_reward} R:R")
        if self.rejected_quality_scorer > 0:
            rejections.append(f"{self.rejected_quality_scorer} qual")
        if self.rejected_order_book > 0:
            rejections.append(f"{self.rejected_order_book} OB")
        if self.rejected_invalid_prices > 0:
            rejections.append(f"{self.rejected_invalid_prices} price")
        
        if rejections:
            parts.append(f"| Filtered: {', '.join(rejections)}")
        
        return " ".join(parts)


class NQSignalGenerator:
    """Signal generator for MNQ intraday strategy.

    Processes scanner results and generates validated trading signals.
    """

    def __init__(
        self,
        config: Optional[NQIntradayConfig] = None,
        scanner: Optional[NQScanner] = None,
    ):
        """Initialize signal generator.

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
        self._duplicate_price_threshold_pct = (
            signal_settings.get("duplicate_price_threshold_pct", 0.5) / 100.0
        )

        # Per-cycle diagnostics for observability
        self.last_diagnostics: Optional[SignalDiagnostics] = None

        logger.info("NQSignalGenerator initialized")

    def generate(self, market_data: Dict) -> List[Dict]:
        """Generate trading signals from market data.

        Args:
            market_data: Dictionary with 'df' (DataFrame) and optionally 'latest_bar' (Dict)

        Returns:
            List of validated signal dictionaries
        """
        # Initialize diagnostics for this cycle
        diagnostics = SignalDiagnostics(
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        df = market_data.get("df")
        if df is None or df.empty:
            self.last_diagnostics = diagnostics
            return []

        # Check market hours using the *bar timestamp* (critical for backtests).
        # If we don't pass a datetime, the scanner defaults to "now", which makes
        # backtests depend on current wall-clock time.
        dt = None
        latest_bar = market_data.get("latest_bar") if isinstance(market_data, dict) else None
        ts = latest_bar.get("timestamp") if isinstance(latest_bar, dict) else None
        if ts:
            try:
                dt = pd.to_datetime(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                dt = None
        if dt is None and isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0:
            # Fallback to latest dataframe timestamp
            try:
                dt = df.index[-1].to_pydatetime() if hasattr(df.index[-1], "to_pydatetime") else df.index[-1]
            except Exception:
                dt = None

        diagnostics.market_hours_checked = True
        if not self.scanner.is_market_hours(dt):
            diagnostics.rejected_market_hours = True
            self.last_diagnostics = diagnostics
            return []

        # Get multi-timeframe data
        df_5m = market_data.get("df_5m")
        df_15m = market_data.get("df_15m")

        # Scan for signals with MTF context and order book data
        raw_signals = self.scanner.scan(df, df_5m=df_5m, df_15m=df_15m, market_data=market_data)

        # Track raw signal count for diagnostics
        diagnostics.raw_signals = len(raw_signals)

        # Log raw signal count at INFO level for observability
        logger.info(f"Raw signals from scanner: {len(raw_signals)}")

        # Diagnostic logging: log raw signals
        if raw_signals:
            logger.debug(f"Raw signals generated: {len(raw_signals)}")
            for raw_signal in raw_signals:
                logger.debug(
                    "Raw signal: type=%s, direction=%s, confidence=%.3f, entry=%.2f",
                    raw_signal.get("type"),
                    raw_signal.get("direction"),
                    raw_signal.get("confidence", 0.0),
                    raw_signal.get("entry_price", 0.0),
                )

        # Get order book data for signal filtering
        latest_bar = market_data.get("latest_bar")
        order_book_available = (
            latest_bar
            and latest_bar.get("order_book")
            and latest_bar["order_book"].get("bids")
        )
        diagnostics.order_book_available = order_book_available

        # Validate and filter signals
        validated_signals = []
        for signal in raw_signals:
            # Apply order book filter if Level 2 data available
            if order_book_available:
                order_book_imbalance = latest_bar.get("imbalance", 0.0)
                signal_direction = signal.get("direction", "")

                # Filter signals based on order book alignment
                # Long signals need positive imbalance (more bids), short need negative (more asks)
                if signal_direction == "long" and order_book_imbalance < -0.2:
                    logger.debug(
                        "Signal filtered by order book: long signal rejected (imbalance: %.2f, strong ask pressure)",
                        order_book_imbalance,
                    )
                    diagnostics.rejected_order_book += 1
                    continue
                if signal_direction == "short" and order_book_imbalance > 0.2:
                    logger.debug(
                        "Signal filtered by order book: short signal rejected (imbalance: %.2f, strong bid pressure)",
                        order_book_imbalance,
                    )
                    diagnostics.rejected_order_book += 1
                    continue

            # Track validation result with rejection reason
            validation_result = self._validate_signal_with_reason(signal)
            if not validation_result["valid"]:
                reason = validation_result.get("reason", "unknown")
                if reason == "confidence":
                    diagnostics.rejected_confidence += 1
                elif reason == "risk_reward":
                    diagnostics.rejected_risk_reward += 1
                elif reason == "invalid_prices":
                    diagnostics.rejected_invalid_prices += 1
                continue

            validated_signal = self._format_signal(signal, market_data)

            # Apply order book confidence adjustment if available
            if order_book_available:
                order_book_imbalance = latest_bar.get("imbalance", 0.0)
                signal_direction = validated_signal.get("direction", "")
                current_confidence = validated_signal.get("confidence", 0.5)

                # Boost confidence when order book aligns with signal
                if signal_direction == "long" and order_book_imbalance > 0.15:
                    confidence_boost = min(0.10, order_book_imbalance * 0.3)
                    validated_signal["confidence"] = min(
                        1.0,
                        current_confidence + confidence_boost,
                    )
                    logger.debug(
                        "Order book confidence boost: +%.3f (imbalance: %.2f)",
                        confidence_boost,
                        order_book_imbalance,
                    )
                elif signal_direction == "short" and order_book_imbalance < -0.15:
                    confidence_boost = min(0.10, abs(order_book_imbalance) * 0.3)
                    validated_signal["confidence"] = min(
                        1.0,
                        current_confidence + confidence_boost,
                    )
                    logger.debug(
                        "Order book confidence boost: +%.3f (imbalance: %.2f)",
                        confidence_boost,
                        order_book_imbalance,
                    )

            if self._is_duplicate(validated_signal):
                diagnostics.duplicates_filtered += 1
                continue
                
            logger.debug(
                "Signal passed validation: type=%s, confidence=%.3f, entry=%.2f",
                validated_signal.get("type"),
                validated_signal.get("confidence", 0.0),
                validated_signal.get("entry_price", 0.0),
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
                diagnostics.rejected_quality_scorer += 1
                # Near-miss diagnostic logging: track signals that fail quality scorer
                signal_type = validated_signal.get("type", "unknown")
                signal_confidence = validated_signal.get("confidence", 0.0)
                historical_wr = quality_score.get("historical_wr", 0.0)
                meets_threshold = quality_score.get("meets_threshold", False)
                information_ratio = quality_score.get("information_ratio", 0.0)
                regime = validated_signal.get("regime", {})
                volatility = regime.get("volatility", "normal")
                atr_expansion = regime.get("atr_expansion", False)

                logger.info(
                    "NEAR_MISS: quality_scorer_rejection | type=%s | confidence=%.3f | "
                    "historical_wr=%.0f%% | meets_threshold=%s | information_ratio=%.3f | "
                    "volatility=%s | atr_expansion=%s",
                    signal_type,
                    signal_confidence,
                    historical_wr * 100.0,
                    meets_threshold,
                    information_ratio,
                    volatility,
                    atr_expansion,
                )
                logger.debug(
                    "Signal context: entry=%.2f, regime=%s, indicators=%s",
                    validated_signal.get("entry_price", 0.0),
                    regime.get("regime", "unknown"),
                    validated_signal.get("indicators", {}),
                )

        # Clean up old signals from recent list
        self._cleanup_recent_signals()

        # Finalize diagnostics
        diagnostics.validated_signals = len(validated_signals)
        self.last_diagnostics = diagnostics

        if validated_signals:
            logger.info("Generated %d validated signal(s)", len(validated_signals))
        else:
            # Log diagnostics summary when no signals
            logger.debug(
                "Signal diagnostics: %s",
                diagnostics.format_compact(),
            )

        return validated_signals

    def _validate_signal(self, signal: Dict) -> bool:
        """Validate a signal meets criteria.

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
        signal_confidence = signal.get("confidence", 0.0)
        atr_expansion = regime.get("atr_expansion", False)

        if volatility == "high" and atr_expansion:
            # Floor confidence at 0.48 during expansion (was 0.50 threshold)
            # This allows signals that get penalized down to 0.42-0.49 to still pass
            effective_confidence = max(signal_confidence, 0.48)
            if effective_confidence > signal_confidence:
                logger.debug(
                    "Volatility expansion: applying confidence floor 0.48 (original: %.3f, adjusted: %.3f)",
                    signal_confidence,
                    effective_confidence,
                )
                signal["confidence"] = effective_confidence
                signal_confidence = effective_confidence

        # Check confidence threshold
        confidence = signal_confidence
        if confidence < self._min_confidence:
            # Near-miss diagnostic logging: track signals that fail confidence threshold
            signal_type = signal.get("type", "unknown")
            logger.info(
                "NEAR_MISS: confidence_rejection | type=%s | confidence=%.3f | "
                "threshold=%.3f | gap=%.3f | volatility=%s | atr_expansion=%s",
                signal_type,
                confidence,
                self._min_confidence,
                self._min_confidence - confidence,
                volatility,
                atr_expansion,
            )
            logger.debug(
                "Signal context: entry=%.2f, regime=%s, indicators=%s",
                signal.get("entry_price", 0.0),
                regime.get("regime", "unknown"),
                signal.get("indicators", {}),
            )
            return False

        # Check entry price is valid
        entry_price = signal.get("entry_price")
        if not entry_price or entry_price <= 0:
            logger.info("Signal rejected: invalid entry_price %s", entry_price)
            return False

        # Check stop loss and take profit are valid
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if signal["direction"] == "long":
            if stop_loss and stop_loss >= entry_price:
                logger.info(
                    "Signal rejected: stop_loss %.2f >= entry %.2f (long)",
                    stop_loss,
                    entry_price,
                )
                return False
            if take_profit and take_profit <= entry_price:
                logger.info(
                    "Signal rejected: take_profit %.2f <= entry %.2f (long)",
                    take_profit,
                    entry_price,
                )
                return False
        else:  # short
            if stop_loss and stop_loss <= entry_price:
                logger.info(
                    "Signal rejected: stop_loss %.2f <= entry %.2f (short)",
                    stop_loss,
                    entry_price,
                )
                return False
            if take_profit and take_profit >= entry_price:
                logger.info(
                    "Signal rejected: take_profit %.2f >= entry %.2f (short)",
                    take_profit,
                    entry_price,
                )
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
                        "NEAR_MISS: risk_reward_rejection | type=%s | risk_reward=%.2f:1 | "
                        "threshold=%.2f:1 | gap=%.2f | entry=%.2f | stop=%.2f | target=%.2f",
                        signal_type,
                        risk_reward,
                        self._min_risk_reward,
                        self._min_risk_reward - risk_reward,
                        entry_price,
                        stop_loss,
                        take_profit,
                    )
                    return False

        return True

    def _validate_signal_with_reason(self, signal: Dict) -> Dict:
        """Validate a signal and return rejection reason.

        Args:
            signal: Signal dictionary

        Returns:
            Dict with "valid" (bool) and "reason" (str) keys
        """
        # Volatility-aware confidence floor: during high volatility expansion,
        # apply a floor to prevent valid structure-based signals from being
        # killed by confidence stacking penalties
        regime = signal.get("regime", {})
        volatility = regime.get("volatility", "normal")
        signal_confidence = signal.get("confidence", 0.0)
        atr_expansion = regime.get("atr_expansion", False)

        if volatility == "high" and atr_expansion:
            effective_confidence = max(signal_confidence, 0.48)
            if effective_confidence > signal_confidence:
                signal["confidence"] = effective_confidence
                signal_confidence = effective_confidence

        # Check confidence threshold
        if signal_confidence < self._min_confidence:
            return {"valid": False, "reason": "confidence"}

        # Check entry price is valid
        entry_price = signal.get("entry_price")
        if not entry_price or entry_price <= 0:
            return {"valid": False, "reason": "invalid_prices"}

        # Check stop loss and take profit are valid
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if signal["direction"] == "long":
            if stop_loss and stop_loss >= entry_price:
                return {"valid": False, "reason": "invalid_prices"}
            if take_profit and take_profit <= entry_price:
                return {"valid": False, "reason": "invalid_prices"}
        else:  # short
            if stop_loss and stop_loss <= entry_price:
                return {"valid": False, "reason": "invalid_prices"}
            if take_profit and take_profit >= entry_price:
                return {"valid": False, "reason": "invalid_prices"}

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
                    return {"valid": False, "reason": "risk_reward"}

        return {"valid": True, "reason": None}

    def _format_signal(self, signal: Dict, market_data: Dict) -> Dict:
        """Format signal with additional metadata.

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
        entry_price = signal.get("entry_price", 0.0)
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if entry_price > 0 and stop_loss:
            # MNQ: $2 per point. tick_value is MNQ-native in config.
            tick_value = getattr(self.config, "tick_value", 2.0)
            position_size = getattr(self.config, "max_position_size", 10)

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
            # Add order book metrics if available
            if latest_bar.get("order_book") and latest_bar["order_book"].get("bids"):
                formatted["order_book"] = {
                    "imbalance": latest_bar.get("imbalance", 0.0),
                    "bid_depth": latest_bar.get("bid_depth", 0),
                    "ask_depth": latest_bar.get("ask_depth", 0),
                    "weighted_mid": latest_bar.get("weighted_mid"),
                    "data_level": latest_bar.get("_data_level", "unknown"),
                }

        # Add indicator values for context
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            formatted["indicators"] = {
                "rsi": float(latest.get("rsi", 0.0)) if "rsi" in latest else None,
                "atr": float(latest.get("atr", 0.0)) if "atr" in latest else None,
                "volume_ratio": float(latest.get("volume_ratio", 0.0)) if "volume_ratio" in latest else None,
                "macd_histogram": float(latest.get("macd_histogram", 0.0)) if "macd_histogram" in latest else None,
            }

        return formatted

    def _is_duplicate(self, signal: Dict) -> bool:
        """Check if signal is a duplicate of a recent signal.

        Args:
            signal: Signal dictionary

        Returns:
            True if duplicate
        """
        signal_time = datetime.fromisoformat(
            signal.get("timestamp", datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")
        )
        signal_entry = signal.get("entry_price", 0.0)

        for recent in self._recent_signals:
            recent_time = datetime.fromisoformat(
                recent.get("timestamp", "").replace("Z", "+00:00")
            )
            time_diff = (signal_time - recent_time).total_seconds()
            recent_entry = recent.get("entry_price", 0.0)

            # Check if same type and direction within time window
            same_type = recent.get("type") == signal.get("type")
            same_direction = recent.get("direction") == signal.get("direction")
            within_time_window = time_diff < self._signal_window_seconds

            # Also check if price is too close (within threshold for same signal)
            price_close = False
            if recent_entry > 0 and signal_entry > 0:
                price_diff_pct = abs(signal_entry - recent_entry) / recent_entry
                price_close = price_diff_pct < self._duplicate_price_threshold_pct

            if same_type and same_direction and (within_time_window or price_close):
                return True

        return False

    def _cleanup_recent_signals(self) -> None:
        """Remove old signals from recent signals list."""
        now = datetime.now(timezone.utc)
        self._recent_signals = [
            s
            for s in self._recent_signals
            if (
                now
                - datetime.fromisoformat(s["timestamp"].replace("Z", "+00:00"))
            ).total_seconds()
            < self._signal_window_seconds
        ]
