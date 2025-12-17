"""
NQ Intraday Market Scanner

Scans NQ futures for intraday trading opportunities using real-time data.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Dict, List, Optional

import pandas as pd

from pearlalgo.utils.logger import logger

# Timezone handling - use zoneinfo (Python 3.9+) or pytz as fallback
try:
    from zoneinfo import ZoneInfo
    ET_TIMEZONE = ZoneInfo("America/New_York")
except ImportError:
    try:
        import pytz
        ET_TIMEZONE = pytz.timezone("America/New_York")
    except ImportError:
        # Fallback if neither available (shouldn't happen in Python 3.9+)
        logger.warning("No timezone library available, using simplified timezone handling")
        ET_TIMEZONE = None

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.regime_detector import RegimeDetector
from pearlalgo.strategies.nq_intraday.mtf_analyzer import MTFAnalyzer
from pearlalgo.strategies.nq_intraday.volume_profile import VolumeProfile
from pearlalgo.strategies.nq_intraday.order_flow import OrderFlowApproximator
from pearlalgo.utils.vwap import VWAPCalculator


class NQScanner:
    """
    Market scanner for NQ intraday strategy.
    
    Scans NQ futures data for trading opportunities using:
    - Momentum signals
    - Mean reversion signals
    - Breakout signals
    """

    def __init__(self, config: Optional[NQIntradayConfig] = None):
        """
        Initialize scanner.
        
        Args:
            config: Configuration instance (optional)
        """
        self.config = config or NQIntradayConfig()
        self.regime_detector = RegimeDetector()
        self.mtf_analyzer = MTFAnalyzer()
        self.vwap_calculator = VWAPCalculator()
        self.volume_profile = VolumeProfile()
        self.order_flow = OrderFlowApproximator(lookback_periods=self.config.lookback_periods)
        logger.info(f"NQScanner initialized with symbol={self.config.symbol}, timeframe={self.config.timeframe}")

    def is_market_hours(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if current time is within market hours (ET timezone).
        
        Args:
            dt: Datetime to check in UTC (default: now)
            
        Returns:
            True if within market hours (09:30-16:00 ET)
        """
        if dt is None:
            dt = datetime.now(timezone.utc)

        # Ensure dt has timezone info (assume UTC if naive)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Convert UTC to Eastern Time (handles EST/EDT automatically)
        if ET_TIMEZONE is not None:
            # Ensure dt is in UTC
            if dt.tzinfo != timezone.utc:
                dt_utc = dt.astimezone(timezone.utc)
            else:
                dt_utc = dt

            # Convert to ET
            et_dt = dt_utc.astimezone(ET_TIMEZONE)
        else:
            # Fallback to simplified conversion (shouldn't happen)
            logger.warning("Using simplified timezone conversion")
            from datetime import timedelta
            et_offset = timedelta(hours=-5)  # EST offset (doesn't handle DST)
            et_dt = dt + et_offset

        # Get ET time components
        et_time = et_dt.time()

        # Parse start and end times from config
        start = time.fromisoformat(self.config.start_time)
        end = time.fromisoformat(self.config.end_time)

        # Check if current time is within market hours
        # Also check if it's a weekday (market closed on weekends)
        is_weekday = et_dt.weekday() < 5  # Monday=0, Friday=4

        return is_weekday and start <= et_time <= end

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators for signal generation.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame with added indicator columns
        """
        if df.empty or len(df) < self.config.lookback_periods:
            return df

        # Ensure we have required columns
        required_cols = ["open", "high", "low", "close", "volume"]
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"Missing required columns in dataframe")
            return df

        df = df.copy()

        # Simple Moving Averages
        df["sma_fast"] = df["close"].rolling(window=9).mean()
        df["sma_slow"] = df["close"].rolling(window=21).mean()
        df["sma_50"] = df["close"].rolling(window=50).mean()

        # EMA for regime detection
        df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()

        # RSI
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))

        # ATR for volatility and stop loss calculation
        high_low = df["high"] - df["low"]
        high_close = abs(df["high"] - df["close"].shift())
        low_close = abs(df["low"] - df["close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=14).mean()

        # MACD (Moving Average Convergence Divergence)
        ema_12 = df["close"].ewm(span=12, adjust=False).mean()
        ema_26 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = ema_12 - ema_26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_histogram"] = df["macd"] - df["macd_signal"]

        # Volume moving average
        df["volume_ma"] = df["volume"].rolling(window=20).mean()
        df["volume_ratio"] = df["volume"] / df["volume_ma"]

        # Bollinger Bands
        df["bb_middle"] = df["close"].rolling(window=20).mean()
        bb_std = df["close"].rolling(window=20).std()
        df["bb_upper"] = df["bb_middle"] + (bb_std * 2)
        df["bb_lower"] = df["bb_middle"] - (bb_std * 2)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]

        # Support/Resistance levels (simplified - recent highs/lows)
        df["recent_high"] = df["high"].rolling(window=20).max()
        df["recent_low"] = df["low"].rolling(window=20).min()

        return df

    def scan(
        self,
        df: pd.DataFrame,
        df_5m: Optional[pd.DataFrame] = None,
        df_15m: Optional[pd.DataFrame] = None,
        market_data: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Scan market data for trading signals.
        
        Args:
            df: DataFrame with OHLCV data and indicators (1m)
            df_5m: Optional DataFrame with 5m bars for multi-timeframe analysis
            df_15m: Optional DataFrame with 15m bars for multi-timeframe analysis
            market_data: Optional market data dictionary with latest_bar (for order book access)
            
        Returns:
            List of signal dictionaries
        """
        signals = []

        if df.empty or len(df) < self.config.lookback_periods:
            return signals

        # Ensure indicators are calculated
        if "sma_fast" not in df.columns:
            df = self.calculate_indicators(df)

        if df.empty or len(df) < self.config.lookback_periods:
            return signals

        # Detect market regime
        regime = self.regime_detector.detect_regime(df)
        regime_type = regime.get("regime", "unknown")
        volatility = regime.get("volatility", "unknown")
        regime_confidence = regime.get("confidence", 0)
        
        # Detect ATR expansion (volatility expansion day indicator)
        atr_expansion = False
        if len(df) >= 5 and "atr" in df.columns:
            current_atr = df.iloc[-1].get("atr", 0)
            atr_5bars_ago = df.iloc[-5].get("atr", 0) if len(df) >= 5 else current_atr
            if atr_5bars_ago > 0:
                atr_expansion_ratio = current_atr / atr_5bars_ago
                atr_expansion = atr_expansion_ratio > 1.20  # 20% increase
                if atr_expansion:
                    expansion_pct = ((current_atr / atr_5bars_ago - 1) * 100)
                    logger.info(f"ATR expansion detected: +{expansion_pct:.1f}% (current: {current_atr:.2f}, 5 bars ago: {atr_5bars_ago:.2f})")
        
        # Add ATR expansion to regime dict for signal context
        regime["atr_expansion"] = atr_expansion
        
        logger.info(f"Regime: {regime_type}, Volatility: {volatility}, Confidence: {regime_confidence:.2f}, ATR Expansion: {atr_expansion}")
        
        # Log market hours status
        is_market_hours = self.is_market_hours()
        if ET_TIMEZONE is not None:
            now_utc = datetime.now(timezone.utc)
            et_time = now_utc.astimezone(ET_TIMEZONE)
            logger.info(f"Market hours: {is_market_hours}, Current ET time: {et_time.strftime('%H:%M:%S')}")
        else:
            logger.info(f"Market hours: {is_market_hours}")

        # Get latest bar
        latest = df.iloc[-1]

        # Analyze multi-timeframe structure
        mtf_analysis = self.mtf_analyzer.analyze(df_5m, df_15m)
        logger.debug(f"MTF alignment: {mtf_analysis.get('alignment')} (score: {mtf_analysis.get('alignment_score', 0):.2f})")

        # Calculate VWAP
        atr = latest.get("atr", 0) if "atr" in df.columns else 0
        vwap_data = self.vwap_calculator.calculate_vwap(df, atr=atr)
        logger.debug(f"VWAP: {vwap_data.get('vwap', 0):.2f}, Distance: {vwap_data.get('distance_pct', 0):.2f}%")

        # Calculate volume profile
        volume_profile_data = self.volume_profile.calculate_profile(df)
        logger.debug(f"Volume Profile POC: {volume_profile_data.get('poc', 0):.2f}")

        # Analyze order flow - use real order book if available, otherwise approximate
        order_flow_data = None
        latest_bar = market_data.get("latest_bar") if market_data else None
        if latest_bar and latest_bar.get("order_book") and latest_bar["order_book"].get("bids"):
            # Use real Level 2 order book data
            order_flow_data = self.order_flow.analyze_order_book(latest_bar)
            logger.debug(f"Order Flow (Level 2): {order_flow_data.get('recent_trend')} (imbalance: {order_flow_data.get('order_book_imbalance', 0):.2f})")
        else:
            # Fall back to approximation from bar characteristics
            order_flow_data = self.order_flow.analyze_order_flow(df)
            logger.debug(f"Order Flow (approximated): {order_flow_data.get('recent_trend')} (net: {order_flow_data.get('net_pressure', 0):.2f})")

        # Check volume threshold
        min_volume = self.config.min_volume
        if self.config.symbol == "NQ":
            # NQ has good liquidity, standard threshold
            min_volume = max(min_volume, 100)
        elif self.config.symbol == "MNQ":
            # MNQ typically has higher volume, but we want to ensure liquidity
            min_volume = max(min_volume, 500)  # Ensure minimum liquidity

        if latest.get("volume", 0) < min_volume:
            return signals

        # Check volatility threshold (slightly lower for scalping opportunities)
        volatility_threshold = self.config.volatility_threshold
        if self.config.symbol in ["NQ", "MNQ"]:
            # Allow slightly lower volatility for scalping setups (works for both NQ and MNQ)
            volatility_threshold = volatility_threshold * 0.8

        if latest.get("atr", 0) / latest["close"] < volatility_threshold:
            return signals

        # Calculate ATR-based stop loss and take profit
        current_price = float(latest["close"])
        atr = float(latest.get("atr", 0))

        def calculate_stop_take(direction: str, entry: float, atr_val: float) -> tuple[float, float]:
            """Calculate stop loss and take profit using ATR."""
            if atr_val == 0:
                # Fallback to tick-based if ATR not available
                stop_loss_dist = self.config.stop_loss_ticks * 0.25
                take_profit_dist = self.config.take_profit_ticks * 0.25
            else:
                # ATR-based calculation
                stop_loss_dist = atr_val * self.config.stop_loss_atr_multiplier
                # Take profit based on risk/reward ratio
                take_profit_dist = stop_loss_dist * self.config.take_profit_risk_reward

            if direction == "long":
                stop_loss = entry - stop_loss_dist
                take_profit = entry + take_profit_dist
            else:  # short
                stop_loss = entry + stop_loss_dist
                take_profit = entry - take_profit_dist

            return stop_loss, take_profit

        def calculate_signal_score(signal_type: str, latest: pd.Series, df: pd.DataFrame) -> float:
            """Calculate signal quality score (0-1)."""
            # Detect volatility expansion (ATR increased >20% in last 5 bars)
            atr_expansion = False
            current_atr = latest.get("atr", 0)
            atr_5bars_ago = current_atr
            if len(df) >= 5 and "atr" in df.columns:
                current_atr = latest.get("atr", 0)
                atr_5bars_ago = df.iloc[-5].get("atr", 0) if len(df) >= 5 else current_atr
                if atr_5bars_ago > 0:
                    atr_expansion_ratio = current_atr / atr_5bars_ago
                    atr_expansion = atr_expansion_ratio > 1.20  # 20% increase
            
            # Base score: boost during volatility expansion
            if atr_expansion and regime.get("volatility") == "high":
                score = 0.55  # Boosted base score for volatility expansion
                expansion_pct = ((current_atr / atr_5bars_ago - 1) * 100) if atr_5bars_ago > 0 else 0
                logger.debug(f"Volatility expansion detected (ATR +{expansion_pct:.1f}%), boosting base confidence to 0.55")
            else:
                score = 0.45  # Base score (slightly lower to allow more signals)

            # Volume confirmation (adjusted weights)
            volume_ratio = latest.get("volume_ratio", 1.0)
            if volume_ratio > 1.5:
                score += 0.20  # Strong volume gets more weight
            elif volume_ratio > 1.2:
                score += 0.12  # Moderate volume confirmation

            # Volatility (ATR) - good volatility is important
            atr_pct = (latest.get("atr", 0) / latest["close"]) if latest["close"] > 0 else 0
            if 0.001 <= atr_pct <= 0.015:  # Slightly wider volatility range
                score += 0.12

            # RSI confirmation (adjusted thresholds)
            rsi = latest.get("rsi", 50)
            
            # For momentum signals: check relative RSI movement OR absolute level
            # During fast moves, RSI oscillates - relative movement captures momentum better
            if signal_type == "momentum_long":
                rsi_momentum = False
                if len(df) >= 3 and "rsi" in df.columns:
                    rsi_3bars_ago = df.iloc[-3].get("rsi", rsi) if len(df) >= 3 else rsi
                    rsi_momentum = (rsi - rsi_3bars_ago) > 5  # RSI increased >5 points in 3 bars
                
                # Accept if RSI momentum OR absolute level in range
                if rsi_momentum or (35 < rsi < 75):
                    score += 0.12
                    if rsi_momentum:
                        logger.debug(f"RSI momentum detected (+{rsi - rsi_3bars_ago:.1f} points in 3 bars), using relative movement")
            elif signal_type == "mean_reversion_long" and rsi < 35:  # Slightly higher threshold
                score += 0.18  # Strong confirmation for mean reversion
            elif signal_type == "breakout_long" and rsi > 45:  # Lower threshold
                score += 0.12

            # MACD confirmation
            if "macd_histogram" in latest:
                macd_hist = latest.get("macd_histogram", 0)
                if signal_type == "momentum_long" and macd_hist > 0:
                    score += 0.12
                elif signal_type == "mean_reversion_long" and macd_hist < 0:
                    score += 0.12

            # Price position relative to MAs (trend filter)
            if "sma_50" in latest and latest["close"] > latest.get("sma_50", 0):
                score += 0.08  # Slightly more weight for trend alignment

            return min(score, 1.0)

        # Session-based filters
        session = regime.get("session", "afternoon")

        # Prop firm style: Avoid lunch lull for scalping (low volume, choppy)
        avoid_lunch = getattr(self.config, 'avoid_lunch_lull', True)
        if avoid_lunch and session == "lunch_lull":
            logger.debug("Skipping signals during lunch lull (prop firm style)")
            return signals

        # Momentum signal (fast MA crosses above slow MA with MACD confirmation)
        # Disable momentum during lunch lull (low volume, choppy)
        if self.config.enable_momentum and session != "lunch_lull":
            if len(df) >= 2:
                prev = df.iloc[-2]
                if (
                    prev["sma_fast"] < prev["sma_slow"]
                    and latest["sma_fast"] > latest["sma_slow"]
                    and latest["close"] > latest["sma_fast"]
                    and latest.get("volume_ratio", 0) > 1.2  # Volume confirmation
                ):
                    stop_loss, take_profit = calculate_stop_take("long", current_price, atr)
                    confidence = calculate_signal_score("momentum_long", latest, df)

                    # Adjust confidence based on regime
                    confidence = self.regime_detector.adjust_confidence_by_regime(
                        "momentum_long", confidence, regime
                    )

                    # Check MTF alignment
                    is_aligned, mtf_adjustment = self.mtf_analyzer.check_signal_alignment(
                        "long", mtf_analysis
                    )

                    # During volatility expansion, relax MTF conflict threshold
                    # Higher timeframes lag during expansion, so structure breaks are valid
                    # even if MTF hasn't caught up yet
                    atr_expansion = regime.get("atr_expansion", False)
                    if atr_expansion and volatility == "high":
                        # Allow signals even if mtf_adjustment >= -0.20 (was -0.15 for momentum)
                        mtf_threshold = -0.20
                    else:
                        mtf_threshold = -0.15

                    if is_aligned or mtf_adjustment >= mtf_threshold:
                        confidence = max(0.0, min(1.0, confidence + mtf_adjustment))

                        # Adjust confidence based on VWAP position
                        confidence = self.vwap_calculator.adjust_confidence_by_vwap(
                            "long", confidence, vwap_data
                        )

                        # Adjust confidence based on volume profile proximity
                        proximity = self.volume_profile.get_proximity_to_key_levels(
                            current_price, volume_profile_data
                        )
                        confidence = self.volume_profile.adjust_confidence_by_proximity(
                            confidence, proximity
                        )

                        # Check order flow alignment
                        is_flow_aligned, flow_adjustment = self.order_flow.check_signal_alignment(
                            "long", order_flow_data
                        )

                        if is_flow_aligned:
                            confidence = max(0.0, min(1.0, confidence + flow_adjustment))

                            signals.append({
                                "type": "momentum_long",
                                "direction": "long",
                                "confidence": confidence,
                                "entry_price": current_price,
                                "stop_loss": stop_loss,
                                "take_profit": take_profit,
                                "reason": "Fast MA crossed above slow MA with volume and MACD confirmation",
                                "regime": regime,  # Include regime context
                                "mtf_analysis": mtf_analysis,  # Include MTF context
                                "vwap_data": vwap_data,  # Include VWAP context
                                "volume_profile": volume_profile_data,  # Include volume profile context
                                "order_flow": order_flow_data,  # Include order flow context
                            })
                        else:
                            # Reject if order flow strongly conflicts
                            logger.debug("Momentum long signal rejected due to order flow conflict")
                    else:
                        # Reject signal if MTF is strongly conflicting
                        logger.debug("Momentum long signal rejected due to MTF conflict")

        # Mean reversion signal (RSI oversold with multiple confirmations)
        if self.config.enable_mean_reversion and session != "opening":
            # Mean reversion: check relative RSI movement OR absolute level
            # During fast moves, RSI may not reach <35 but can drop rapidly (40→35 in 3 bars)
            # Relative movement captures momentum shifts during fast pullbacks
            rsi = latest.get("rsi", 50)
            rsi_momentum_down = False
            if len(df) >= 3 and "rsi" in df.columns:
                rsi_3bars_ago = df.iloc[-3].get("rsi", rsi) if len(df) >= 3 else rsi
                rsi_momentum_down = (rsi_3bars_ago - rsi) > 5  # RSI dropped >5 points in 3 bars
            
            # Accept if RSI momentum down OR absolute oversold
            rsi_ok = rsi_momentum_down or rsi < 35
            
            if (
                rsi_ok  # Relative RSI movement OR absolute oversold
                and latest["close"] < latest.get("bb_lower", current_price)
                and latest.get("volume_ratio", 0) > 1.0
            ):
                if rsi_momentum_down:
                    logger.debug(f"Mean reversion: RSI momentum down detected (-{rsi_3bars_ago - rsi:.1f} points in 3 bars), using relative movement")
                # Use lower BB as entry reference, but stop below it
                stop_loss, take_profit = calculate_stop_take("long", current_price, atr)
                # Adjust stop to be below lower BB
                if stop_loss > latest.get("bb_lower", stop_loss):
                    stop_loss = float(latest.get("bb_lower", stop_loss)) - (atr * 0.5)
                confidence = calculate_signal_score("mean_reversion_long", latest, df)

                # Adjust confidence based on regime
                confidence = self.regime_detector.adjust_confidence_by_regime(
                    "mean_reversion_long", confidence, regime
                )

                # Check MTF alignment (mean reversion less strict on MTF)
                is_aligned, mtf_adjustment = self.mtf_analyzer.check_signal_alignment(
                    "long", mtf_analysis
                )

                # During volatility expansion, relax MTF conflict threshold further
                # Mean reversion can work against MTF (it's counter-trend by nature)
                atr_expansion = regime.get("atr_expansion", False)
                if atr_expansion and volatility == "high":
                    # Allow mean reversion even if mtf_adjustment >= -0.30 (was -0.25)
                    mtf_threshold = -0.30
                else:
                    mtf_threshold = -0.25

                # Allow mean reversion even with partial MTF conflict (it's counter-trend by nature)
                # Only reject if strongly conflicting
                if is_aligned or mtf_adjustment >= mtf_threshold:
                    confidence = max(0.0, min(1.0, confidence + mtf_adjustment * 0.5))  # Less weight for mean reversion

                    # Adjust confidence based on VWAP position (mean reversion less sensitive to VWAP)
                    confidence = self.vwap_calculator.adjust_confidence_by_vwap(
                        "long", confidence, vwap_data
                    ) * 0.9  # Slightly reduce VWAP impact for mean reversion

                    # Adjust confidence based on volume profile proximity
                    proximity = self.volume_profile.get_proximity_to_key_levels(
                        current_price, volume_profile_data
                    )
                    confidence = self.volume_profile.adjust_confidence_by_proximity(
                        confidence, proximity
                    )

                    # Check order flow alignment (mean reversion less strict)
                    is_flow_aligned, flow_adjustment = self.order_flow.check_signal_alignment(
                        "long", order_flow_data
                    )

                    # Mean reversion can work against order flow (it's counter-trend)
                    # During high volatility, order flow may lag reversals - relax threshold
                    if regime.get("volatility") == "high":
                        # High volatility: allow mean reversion even if order flow adjustment >= -0.20
                        flow_threshold = -0.20
                    else:
                        # Normal volatility: reject if order flow adjustment < -0.12
                        flow_threshold = -0.12

                    # Only reject if very strong conflict
                    if is_flow_aligned or flow_adjustment >= flow_threshold:
                        confidence = max(0.0, min(1.0, confidence + flow_adjustment * 0.5))  # Less weight for mean reversion

                        signals.append({
                            "type": "mean_reversion_long",
                            "direction": "long",
                            "confidence": confidence,
                            "entry_price": current_price,
                            "stop_loss": stop_loss,
                            "take_profit": float(latest.get("bb_middle", take_profit)),
                            "reason": "RSI oversold with price at lower Bollinger Band and volume confirmation",
                            "regime": regime,  # Include regime context
                            "mtf_analysis": mtf_analysis,  # Include MTF context
                            "vwap_data": vwap_data,  # Include VWAP context
                            "volume_profile": volume_profile_data,  # Include volume profile context
                            "order_flow": order_flow_data,  # Include order flow context
                        })
                    else:
                        # Only reject if very strong conflict
                        logger.debug("Mean reversion long signal rejected due to strong order flow conflict")
                else:
                    # Only reject if strongly conflicting
                    logger.debug("Mean reversion long signal rejected due to strong MTF conflict")

        # Breakout signal (price breaks above recent high with volume)
        if self.config.enable_breakout:
            if len(df) >= 5:
                recent_high = df["high"].tail(5).max()
                
                # Structure-first gate: check if this is a fresh breakout (within 0.3% of level)
                # Fresh breakouts are price-action based, not indicator-based, so relax RSI requirement
                is_fresh_breakout = False
                if latest["close"] > recent_high:
                    is_fresh_breakout = abs(current_price - recent_high) / recent_high < 0.003
                
                # For fresh breakouts, relax RSI requirement (structure breaks happen before indicators confirm)
                rsi = latest.get("rsi", 50)
                if is_fresh_breakout:
                    rsi_ok = rsi > 40  # Lower threshold for fresh breakouts
                else:
                    rsi_ok = rsi > 45  # Original threshold for established breakouts
                
                if (
                    latest["close"] > recent_high
                    and latest.get("volume_ratio", 0) > 1.3  # Slightly lower threshold (was 1.5)
                    and rsi_ok  # Conditional RSI threshold based on fresh breakout
                    and latest.get("macd_histogram", 0) > 0  # MACD bullish
                ):
                    stop_loss, take_profit = calculate_stop_take("long", current_price, atr)
                    # Stop loss below recent high
                    stop_loss = min(stop_loss, float(recent_high) - (atr * 0.5))
                    confidence = calculate_signal_score("breakout_long", latest, df)

                    # is_fresh_breakout already calculated above
                    if is_fresh_breakout:
                        logger.debug(f"Fresh breakout detected (within 0.3% of level {recent_high:.2f}), applying structure-first gate with relaxed RSI threshold")
                    
                    # Adjust confidence based on regime
                    confidence = self.regime_detector.adjust_confidence_by_regime(
                        "breakout_long", confidence, regime
                    )

                    # Check MTF alignment (breakouts need strong MTF confirmation)
                    is_aligned, mtf_adjustment = self.mtf_analyzer.check_signal_alignment(
                        "long", mtf_analysis
                    )

                    # For breakouts, check if we're breaking 5m/15m resistance
                    breakout_levels = self.mtf_analyzer.get_breakout_levels(mtf_analysis)
                    resistance_5m = breakout_levels.get("resistance_5m")
                    resistance_15m = breakout_levels.get("resistance_15m")

                    # Breakout should break higher timeframe resistance
                    if resistance_5m and current_price < resistance_5m:
                        # Not breaking 5m resistance - reduce confidence
                        mtf_adjustment -= 0.15
                    elif resistance_5m and current_price > resistance_5m:
                        # Breaking 5m resistance - boost confidence
                        mtf_adjustment += 0.10

                    # Structure-first: allow fresh breakouts even with MTF conflicts
                    # Fresh breakouts are structure-based, not indicator-based
                    # During volatility expansion, relax threshold further
                    atr_expansion = regime.get("atr_expansion", False)
                    if is_fresh_breakout:
                        # For fresh breakouts, allow even if MTF adjustment >= -0.25
                        mtf_threshold = -0.25
                        logger.debug(f"Fresh breakout detected (within 0.3% of level), applying structure-first gate")
                    elif atr_expansion and volatility == "high":
                        # During expansion, relax threshold for all breakouts
                        mtf_threshold = -0.25
                    else:
                        mtf_threshold = -0.20

                    # Reject if strongly conflicting (unless fresh breakout)
                    if is_aligned or mtf_adjustment >= mtf_threshold:
                        confidence = max(0.0, min(1.0, confidence + mtf_adjustment))

                        # Adjust confidence based on VWAP position (breakouts benefit from VWAP support)
                        confidence = self.vwap_calculator.adjust_confidence_by_vwap(
                            "long", confidence, vwap_data
                        )

                        # Adjust confidence based on volume profile proximity
                        proximity = self.volume_profile.get_proximity_to_key_levels(
                            current_price, volume_profile_data
                        )
                        confidence = self.volume_profile.adjust_confidence_by_proximity(
                            confidence, proximity
                        )

                        # Check order flow alignment (breakouts need strong order flow)
                        is_flow_aligned, flow_adjustment = self.order_flow.check_signal_alignment(
                            "long", order_flow_data
                        )

                        # Structure-first: for fresh breakouts, relax order flow conflict threshold
                        if is_fresh_breakout:
                            # Allow fresh breakouts even if order flow adjustment >= -0.20 (was -0.12)
                            flow_threshold = -0.20
                        else:
                            flow_threshold = -0.12

                        # Reject if order flow strongly conflicts (unless fresh breakout)
                        if is_flow_aligned or flow_adjustment >= flow_threshold:
                            confidence = max(0.0, min(1.0, confidence + flow_adjustment))

                            signals.append({
                                "type": "breakout_long",
                                "direction": "long",
                                "confidence": confidence,
                                "entry_price": current_price,
                                "stop_loss": stop_loss,
                                "take_profit": take_profit,
                                "reason": f"Price broke above recent high ({recent_high:.2f}) with strong volume and MACD confirmation",
                                "regime": regime,  # Include regime context
                                "mtf_analysis": mtf_analysis,  # Include MTF context
                                "vwap_data": vwap_data,  # Include VWAP context
                                "volume_profile": volume_profile_data,  # Include volume profile context
                                "order_flow": order_flow_data,  # Include order flow context
                            })
                        else:
                            # Reject if order flow strongly conflicts
                            logger.debug("Breakout long signal rejected due to order flow conflict")
                    else:
                        # Reject if strongly conflicting
                        logger.debug("Breakout long signal rejected due to MTF conflict")

        return signals
