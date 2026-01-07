"""
NQ Intraday Market Scanner

Scans NQ futures for intraday trading opportunities using real-time data.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timezone
from typing import Callable, Dict, List, Optional, Tuple

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
from pearlalgo.strategies.nq_intraday.hud_context import build_hud_context

# Custom indicators for enhanced signal generation
from pearlalgo.strategies.nq_intraday.indicators import get_enabled_indicators, IndicatorBase

# Adaptive stops and market depth (v2.0 risk management)
try:
    from pearlalgo.strategies.nq_intraday.adaptive_stops import (
        AdaptiveStopCalculator,
        get_adaptive_stop_calculator,
        StopTakeProfit,
    )
    ADAPTIVE_STOPS_AVAILABLE = True
except ImportError:
    ADAPTIVE_STOPS_AVAILABLE = False
    AdaptiveStopCalculator = None  # type: ignore
    get_adaptive_stop_calculator = None  # type: ignore
    StopTakeProfit = None  # type: ignore

try:
    from pearlalgo.strategies.nq_intraday.market_depth import (
        MarketDepthAnalyzer,
        get_market_depth_analyzer,
    )
    MARKET_DEPTH_AVAILABLE = True
except ImportError:
    MARKET_DEPTH_AVAILABLE = False
    MarketDepthAnalyzer = None  # type: ignore
    get_market_depth_analyzer = None  # type: ignore


class NQScanner:
    """
    Market scanner for NQ intraday strategy.
    
    Scans NQ futures data for trading opportunities using:
    - Momentum signals
    - Mean reversion signals
    - Breakout signals
    """

    # Timeframe to minutes mapping for threshold scaling
    TIMEFRAME_MINUTES = {
        "1m": 1, "2m": 2, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60,
    }

    def __init__(self, config: Optional[NQIntradayConfig] = None, service_config: Optional[Dict] = None):
        """
        Initialize scanner.
        
        Args:
            config: Configuration instance (optional)
            service_config: Full service configuration for adaptive stops (optional)
        """
        self.config = config or NQIntradayConfig()
        self.regime_detector = RegimeDetector()
        self.mtf_analyzer = MTFAnalyzer()
        self.vwap_calculator = VWAPCalculator()
        self.volume_profile = VolumeProfile()
        self.order_flow = OrderFlowApproximator(lookback_periods=self.config.lookback_periods)
        
        # Initialize custom indicators from config
        # These provide additional features for the learning system and optional rule-based signals
        indicators_config = getattr(config, "indicators", None) or {}
        self.custom_indicators: List[IndicatorBase] = get_enabled_indicators(
            {"indicators": indicators_config} if indicators_config else None
        )
        
        # Track gate reasons from most recent scan (for diagnostics)
        self.last_gate_reasons: List[str] = []
        
        # Initialize adaptive stop calculator (v2.0 risk management)
        self._adaptive_stops: Optional[AdaptiveStopCalculator] = None
        self._market_depth: Optional[MarketDepthAnalyzer] = None
        
        if ADAPTIVE_STOPS_AVAILABLE and get_adaptive_stop_calculator is not None:
            try:
                self._adaptive_stops = get_adaptive_stop_calculator(service_config)
                logger.info("Adaptive stop calculator initialized")
            except Exception as e:
                logger.warning(f"Could not initialize adaptive stops: {e}")
        
        if MARKET_DEPTH_AVAILABLE and get_market_depth_analyzer is not None:
            try:
                self._market_depth = get_market_depth_analyzer()
                logger.info("Market depth analyzer initialized")
            except Exception as e:
                logger.warning(f"Could not initialize market depth analyzer: {e}")
        
        # Log adaptive volatility filter status
        avf_enabled = getattr(self.config, "adaptive_volatility_filter_enabled", False)
        avf_expansion = getattr(self.config, "adaptive_volatility_expansion_requirement", 2.0)
        
        logger.info(
            f"NQScanner initialized with symbol={self.config.symbol}, timeframe={self.config.timeframe}, "
            f"custom_indicators={[ind.name for ind in self.custom_indicators]}, "
            f"adaptive_stops={self._adaptive_stops is not None}, "
            f"adaptive_volatility_filter={'ENABLED' if avf_enabled else 'DISABLED'} "
            f"(expansion_req={avf_expansion:.1f}x)"
        )

    def _get_timeframe_minutes(self, timeframe: str) -> int:
        """Get minutes for a timeframe string (e.g. '1m' -> 1, '5m' -> 5)."""
        return self.TIMEFRAME_MINUTES.get(timeframe.lower(), 5)

    def get_gate_reasons(self) -> List[str]:
        """
        Get the gate reasons from the most recent scan cycle.
        
        Use this for diagnostics to understand why no signals were generated.
        
        Returns:
            List of gate reason strings (empty if signals were generated or no gates hit).
        """
        return list(self.last_gate_reasons)

    def _get_scaled_thresholds(self) -> Tuple[int, float]:
        """
        Get volume and volatility thresholds scaled for the current timeframe.
        
        Rationale:
        - Volume aggregates over the bar period: 1m bar has ~1/5 the volume of a 5m bar.
        - ATR is the average range which also scales (though less linearly).
        
        We scale relative to 5m as the reference timeframe (the original defaults).
        
        Note: The config.min_volume is respected directly (no hard-coded symbol floors).
        For 24h futures trading (Tokyo/London/NY), set signals.min_volume in config.yaml
        to a value that works across all sessions (e.g., 50-100 for 5m reference).
        
        Returns:
            Tuple of (min_volume, volatility_threshold) scaled for this timeframe.
        """
        ref_minutes = 5  # Reference timeframe (5m)
        tf_minutes = self._get_timeframe_minutes(self.config.timeframe)
        
        # Scale factor: 1m = 0.2, 5m = 1.0, 15m = 3.0
        scale = tf_minutes / ref_minutes
        
        # Volume scales roughly linearly with bar duration.
        # Use configured min_volume directly (no hard-coded symbol floors).
        # Safety floor of 10 prevents 0-volume bars from passing.
        base_min_volume = self.config.min_volume
        scaled_min_volume = max(10, int(base_min_volume * scale))
        
        # Volatility (ATR/price) scales with sqrt of bar duration (rough heuristic)
        # Using linear scaling is too aggressive; sqrt is a compromise
        import math
        volatility_scale = math.sqrt(scale)
        base_volatility = self.config.volatility_threshold
        if self.config.symbol in ["NQ", "MNQ"]:
            base_volatility = base_volatility * 0.8  # Existing scalp-friendly reduction
        scaled_volatility = base_volatility * volatility_scale
        
        return scaled_min_volume, scaled_volatility

    def is_market_hours(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if current time is within the configured strategy session window (ET timezone).
        
        Args:
            dt: Datetime to check in UTC (default: now)
            
        Returns:
            True if within the configured session window (start_time/end_time in config).
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

        weekday = et_dt.weekday()  # 0=Monday, 6=Sunday

        # Simple same-day window (e.g., 09:30–16:10 ET).
        # For strategy sessions we keep this weekday-only (Mon–Fri).
        if start <= end:
            is_weekday = weekday < 5
            return is_weekday and start <= et_time <= end

        # Cross-midnight window (e.g., 18:00–16:10 ET).
        # Intended for prop-firm style futures sessions:
        # - Opens Sunday evening at start_time
        # - Closed Friday after end_time until Sunday start_time
        if weekday == 5:  # Saturday
            return False
        if weekday == 6:  # Sunday
            return et_time >= start
        if weekday == 4:  # Friday
            return et_time <= end

        # Monday–Thursday: open from midnight->end and from start->midnight.
        return (et_time >= start) or (et_time <= end)

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
        # Reset gate reasons for this scan cycle
        self.last_gate_reasons = []

        if df.empty or len(df) < self.config.lookback_periods:
            self.last_gate_reasons.append(f"Insufficient data: {len(df)} bars < {self.config.lookback_periods} required")
            return signals

        # Ensure indicators are calculated
        if "sma_fast" not in df.columns:
            df = self.calculate_indicators(df)

        if df.empty or len(df) < self.config.lookback_periods:
            return signals

        # Calculate custom indicators (supply/demand zones, power channel, divergences)
        # These add columns to df and provide features for the learning system
        custom_features: Dict[str, float] = {}
        for indicator in self.custom_indicators:
            try:
                df = indicator.calculate(df)
                # Extract features from the latest bar for the learning system
                if len(df) > 0:
                    features = indicator.as_features(df.iloc[-1], df)
                    custom_features.update(features)
            except Exception as e:
                logger.warning(f"Failed to calculate indicator {indicator.name}: {e}")

        # Extract bar timestamp for deterministic session detection in backtests.
        # Use latest_bar.timestamp if available (backtest passes is_backtest=True),
        # otherwise fall back to df index or None (uses wall-clock).
        bar_dt = None
        latest_bar = market_data.get("latest_bar") if market_data else None
        if latest_bar and latest_bar.get("timestamp"):
            ts = latest_bar["timestamp"]
            if isinstance(ts, str):
                try:
                    bar_dt = pd.to_datetime(ts)
                    if bar_dt.tzinfo is None:
                        bar_dt = bar_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    bar_dt = None
            elif isinstance(ts, pd.Timestamp):
                bar_dt = ts.to_pydatetime()
                if bar_dt.tzinfo is None:
                    bar_dt = bar_dt.replace(tzinfo=timezone.utc)
            elif isinstance(ts, datetime):
                bar_dt = ts
                if bar_dt.tzinfo is None:
                    bar_dt = bar_dt.replace(tzinfo=timezone.utc)
        # Fallback: extract from df index if backtest and bar_dt not set
        if bar_dt is None and market_data and market_data.get("is_backtest"):
            if isinstance(df.index, pd.DatetimeIndex) and len(df) > 0:
                bar_dt = df.index[-1].to_pydatetime()
                if bar_dt.tzinfo is None:
                    bar_dt = bar_dt.replace(tzinfo=timezone.utc)

        # Detect market regime (pass bar_dt for deterministic session detection)
        regime = self.regime_detector.detect_regime(df, dt=bar_dt)
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

        # Persist last regime snapshot for service-level observability / drift guard.
        # This avoids re-running regime detection outside the scanner.
        try:
            self.last_regime = dict(regime) if isinstance(regime, dict) else None
            self.last_regime_timestamp = bar_dt.isoformat() if bar_dt is not None else None
        except Exception:
            self.last_regime = None
            self.last_regime_timestamp = None
        
        logger.info(f"Regime: {regime_type}, Volatility: {volatility}, Confidence: {regime_confidence:.2f}, ATR Expansion: {atr_expansion}")
        
        # Log market hours status (use bar_dt for deterministic backtest logging)
        is_market_hours = self.is_market_hours(bar_dt)
        if ET_TIMEZONE is not None:
            check_time = bar_dt if bar_dt else datetime.now(timezone.utc)
            et_time = check_time.astimezone(ET_TIMEZONE)
            logger.info(f"Market hours: {is_market_hours}, ET time: {et_time.strftime('%H:%M:%S')}")
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

        # Get timeframe-scaled thresholds (1m bars have lower volume/ATR than 5m)
        min_volume, volatility_threshold = self._get_scaled_thresholds()
        
        # Check volume threshold
        current_volume = latest.get("volume", 0)
        if current_volume < min_volume:
            self.last_gate_reasons.append(
                f"Low volume: {current_volume:.0f} < {min_volume} (scaled for {self.config.timeframe})"
            )
            logger.debug(f"Volume gate: {current_volume:.0f} < {min_volume} ({self.config.timeframe})")
            return signals

        # Check volatility threshold
        current_atr = latest.get("atr", 0)
        current_close = latest["close"]
        atr_pct = current_atr / current_close if current_close > 0 else 0
        # IMPORTANT: Tokyo/London can be low-vol but still tradable for mean-reversion/scalps.
        # Treat the configured volatility threshold as a "soft" reference and only hard-gate
        # when volatility is *extremely* low.
        extreme_vol_threshold = volatility_threshold * 0.75
        if atr_pct < extreme_vol_threshold:
            self.last_gate_reasons.append(
                f"Extreme low volatility: ATR/price={atr_pct:.5f} < {extreme_vol_threshold:.5f} (scaled for {self.config.timeframe})"
            )
            logger.debug(
                f"Volatility gate: ATR/price={atr_pct:.5f} < {extreme_vol_threshold:.5f} ({self.config.timeframe})"
            )
            return signals

        # Adaptive volatility expansion filter (LANE B feature)
        # During low-vol consolidation, require ATR expansion before entry.
        # This reduces false breakout signals when market is ranging in tight range.
        if getattr(self.config, "adaptive_volatility_filter_enabled", False):
            median_threshold = getattr(self.config, "adaptive_volatility_median_threshold", 0.0003)
            expansion_req = getattr(self.config, "adaptive_volatility_expansion_requirement", 2.0)
            
            if atr_pct < median_threshold:
                # Low-vol environment detected - check for ATR expansion
                # Compare current ATR to ATR from 5 bars ago
                if len(df) >= 5 and "atr" in df.columns:
                    atr_5_bars_ago = float(df["atr"].iloc[-5])
                    expansion_ratio = current_atr / atr_5_bars_ago if atr_5_bars_ago > 0 else 1.0
                    
                    if expansion_ratio < expansion_req:
                        self.last_gate_reasons.append(
                            f"Low-vol consolidation: ATR expansion {expansion_ratio:.2f}x < {expansion_req:.1f}x required"
                        )
                        logger.debug(
                            f"Adaptive volatility gate: expansion {expansion_ratio:.2f}x < {expansion_req:.1f}x, "
                            f"atr_pct={atr_pct:.5f} < median={median_threshold:.5f}"
                        )
                        return signals

        # Calculate ATR-based stop loss and take profit
        current_price = float(latest["close"])
        atr = float(latest.get("atr", 0))

        def calculate_stop_take(
            direction: str,
            entry: float,
            atr_val: float,
            signal_type: str = "unknown",
        ) -> tuple[float, float]:
            """Calculate stop loss and take profit using adaptive or legacy methods.
            
            v2.0: Uses AdaptiveStopCalculator for context-aware stops.
            Falls back to legacy ATR/scalp presets if adaptive stops unavailable.
            
            Args:
                direction: "long" or "short"
                entry: Entry price
                atr_val: ATR value
                signal_type: Signal type for adaptive stops
                
            Returns:
                Tuple of (stop_loss, take_profit)
            """
            # v2.0: Try adaptive stops first
            if self._adaptive_stops is not None:
                try:
                    context = {
                        "regime": regime,
                        "df": df,
                    }
                    result = self._adaptive_stops.calculate_stop_take_profit(
                        signal_type=signal_type,
                        direction=direction,
                        entry_price=entry,
                        atr=atr_val,
                        context=context,
                        df=df,
                    )
                    logger.debug(
                        f"Adaptive stops: SL=${result.stop_loss:.2f}, TP=${result.take_profit:.2f}, "
                        f"mult={result.final_multiplier:.2f}, R:R={result.risk_reward_ratio:.2f}"
                    )
                    return result.stop_loss, result.take_profit
                except Exception as e:
                    logger.warning(f"Adaptive stops failed, using legacy: {e}")
            
            # Legacy fallback: scalp presets or ATR-based
            use_scalp = getattr(self.config, "use_scalp_presets", False)
            if use_scalp:
                scalp_target = getattr(self.config, "scalp_target_points", 20.0)
                scalp_stop = getattr(self.config, "scalp_stop_points", 12.0)
                stop_loss_dist = scalp_stop
                take_profit_dist = scalp_target
            elif atr_val == 0:
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
            """Calculate signal quality score (0-1) for both LONG and SHORT signals."""
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
            elif signal_type == "momentum_short":
                # For SHORT momentum: RSI dropping or in bearish range
                rsi_momentum = False
                if len(df) >= 3 and "rsi" in df.columns:
                    rsi_3bars_ago = df.iloc[-3].get("rsi", rsi) if len(df) >= 3 else rsi
                    rsi_momentum = (rsi_3bars_ago - rsi) > 5  # RSI decreased >5 points in 3 bars
                
                # Accept if RSI momentum down OR in bearish range
                if rsi_momentum or (25 < rsi < 65):
                    score += 0.12
                    if rsi_momentum:
                        logger.debug(f"RSI momentum down detected (-{rsi_3bars_ago - rsi:.1f} points in 3 bars), using relative movement")
            elif signal_type == "mean_reversion_long" and rsi < 35:  # Slightly higher threshold
                score += 0.18  # Strong confirmation for mean reversion
            elif signal_type == "mean_reversion_short" and rsi > 65:  # RSI overbought for short
                score += 0.18  # Strong confirmation for mean reversion short
            elif signal_type == "breakout_long" and rsi > 45:  # Lower threshold
                score += 0.12
            elif signal_type == "breakout_short" and rsi < 55:  # RSI below neutral for short breakout
                score += 0.12
            # New pattern types
            elif signal_type in ("sr_bounce_long", "vwap_reversion_long") and rsi < 40:
                score += 0.15  # Oversold for bounce/reversion
            elif signal_type in ("sr_bounce_short", "vwap_reversion_short") and rsi > 60:
                score += 0.15  # Overbought for rejection/reversion
            elif signal_type == "engulfing_long" and 30 < rsi < 50:
                score += 0.12  # Not too extreme for reversal
            elif signal_type == "engulfing_short" and 50 < rsi < 70:
                score += 0.12  # Not too extreme for reversal

            # MACD confirmation
            if "macd_histogram" in latest:
                macd_hist = latest.get("macd_histogram", 0)
                if signal_type == "momentum_long" and macd_hist > 0:
                    score += 0.12
                elif signal_type == "momentum_short" and macd_hist < 0:
                    score += 0.12
                elif signal_type == "mean_reversion_long" and macd_hist < 0:
                    score += 0.12
                elif signal_type == "mean_reversion_short" and macd_hist > 0:
                    score += 0.12  # For short mean reversion, MACD should be positive (overbought)
                elif signal_type == "breakout_short" and macd_hist < 0:
                    score += 0.12
                # New pattern types - MACD momentum alignment
                elif signal_type in ("sr_bounce_long", "vwap_reversion_long", "engulfing_long") and macd_hist > -0.5:
                    score += 0.08  # Not strongly bearish
                elif signal_type in ("sr_bounce_short", "vwap_reversion_short", "engulfing_short") and macd_hist < 0.5:
                    score += 0.08  # Not strongly bullish

            # Price position relative to MAs (trend filter)
            # For LONG: price above SMA_50 is good
            # For SHORT: price below SMA_50 is good
            if "sma_50" in latest:
                if signal_type.endswith("_long") and latest["close"] > latest.get("sma_50", 0):
                    score += 0.08  # Slightly more weight for trend alignment
                elif signal_type.endswith("_short") and latest["close"] < latest.get("sma_50", float("inf")):
                    score += 0.08  # Price below SMA_50 for short signals

            return min(score, 1.0)

        # Session-based filters
        session = regime.get("session", "afternoon")

        # 24h futures: overnight (Tokyo/London) typically has lower volume/volatility.
        # COMPLETELY DISABLED (2026-01-07): No volume requirements at all.
        is_overnight = str(session).lower() == "overnight"
        vr_momentum = 0.0  # DISABLED: No volume gate
        vr_meanrev = 0.0   # DISABLED: No volume gate
        vr_breakout = 0.0  # DISABLED: No volume gate

        # Prop firm style: Avoid lunch lull for scalping (low volume, choppy)
        avoid_lunch = getattr(self.config, 'avoid_lunch_lull', True)
        if avoid_lunch and session == "lunch_lull":
            self.last_gate_reasons.append("Lunch lull session (11:30-13:00 ET) - skipping signals")
            logger.debug("Skipping signals during lunch lull (prop firm style)")
            return signals

        # Momentum LONG signal (fast MA crosses above slow MA with MACD confirmation)
        # LOOSENED (2026-01-07): Accept upward momentum without strict MA crossover
        if self.config.enable_momentum and self.config.is_signal_enabled("momentum_long") and session != "lunch_lull":
            if len(df) >= 2:
                prev = df.iloc[-2]
                # LOOSENED: Accept if fast MA trending up OR crossed above slow MA
                ma_bullish = (
                    (prev["sma_fast"] < prev["sma_slow"] and latest["sma_fast"] > latest["sma_slow"])  # Crossover
                    or (latest["sma_fast"] > latest["sma_slow"] and latest["close"] > prev["close"])  # Trending up
                )
                if (
                    ma_bullish
                    and latest.get("volume_ratio", 0) > vr_momentum  # Volume confirmation
                ):
                    stop_loss, take_profit = calculate_stop_take("long", current_price, atr, "momentum_long")
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

        # Momentum SHORT signal (fast MA crosses below slow MA with MACD confirmation)
        # LOOSENED (2026-01-07): Accept downward momentum without strict MA crossover
        if self.config.enable_momentum and self.config.is_signal_enabled("momentum_short") and session != "lunch_lull":
            if len(df) >= 2:
                prev = df.iloc[-2]
                # LOOSENED: Accept if fast MA trending down OR crossed below slow MA
                ma_bearish = (
                    (prev["sma_fast"] > prev["sma_slow"] and latest["sma_fast"] < latest["sma_slow"])  # Crossover
                    or (latest["sma_fast"] < latest["sma_slow"] and latest["close"] < prev["close"])  # Trending down
                )
                if (
                    ma_bearish
                    and latest.get("volume_ratio", 0) > vr_momentum  # Volume confirmation
                ):
                    stop_loss, take_profit = calculate_stop_take("short", current_price, atr, "momentum_short")
                    confidence = calculate_signal_score("momentum_short", latest, df)

                    # Adjust confidence based on regime
                    confidence = self.regime_detector.adjust_confidence_by_regime(
                        "momentum_short", confidence, regime
                    )

                    # Check MTF alignment for SHORT
                    is_aligned, mtf_adjustment = self.mtf_analyzer.check_signal_alignment(
                        "short", mtf_analysis
                    )

                    # During volatility expansion, relax MTF conflict threshold
                    atr_expansion = regime.get("atr_expansion", False)
                    if atr_expansion and volatility == "high":
                        mtf_threshold = -0.20
                    else:
                        mtf_threshold = -0.15

                    if is_aligned or mtf_adjustment >= mtf_threshold:
                        confidence = max(0.0, min(1.0, confidence + mtf_adjustment))

                        # Adjust confidence based on VWAP position
                        confidence = self.vwap_calculator.adjust_confidence_by_vwap(
                            "short", confidence, vwap_data
                        )

                        # Adjust confidence based on volume profile proximity
                        proximity = self.volume_profile.get_proximity_to_key_levels(
                            current_price, volume_profile_data
                        )
                        confidence = self.volume_profile.adjust_confidence_by_proximity(
                            confidence, proximity
                        )

                        # Check order flow alignment for SHORT
                        is_flow_aligned, flow_adjustment = self.order_flow.check_signal_alignment(
                            "short", order_flow_data
                        )

                        if is_flow_aligned:
                            confidence = max(0.0, min(1.0, confidence + flow_adjustment))

                            signals.append({
                                "type": "momentum_short",
                                "direction": "short",
                                "confidence": confidence,
                                "entry_price": current_price,
                                "stop_loss": stop_loss,
                                "take_profit": take_profit,
                                "reason": "Fast MA crossed below slow MA with volume and MACD confirmation",
                                "regime": regime,
                                "mtf_analysis": mtf_analysis,
                                "vwap_data": vwap_data,
                                "volume_profile": volume_profile_data,
                                "order_flow": order_flow_data,
                            })
                        else:
                            logger.debug("Momentum short signal rejected due to order flow conflict")
                    else:
                        logger.debug("Momentum short signal rejected due to MTF conflict")

        # Mean reversion LONG signal (RSI oversold with multiple confirmations)
        # NOTE: mean_reversion_long has 2 wins in backtest - keep enabled
        if self.config.enable_mean_reversion and self.config.is_signal_enabled("mean_reversion_long") and session != "opening":
            # Mean reversion: check relative RSI movement OR absolute level
            # LOOSENED (2026-01-07): More permissive thresholds to generate more signals
            rsi = latest.get("rsi", 50)
            rsi_momentum_down = False
            if len(df) >= 3 and "rsi" in df.columns:
                rsi_3bars_ago = df.iloc[-3].get("rsi", rsi) if len(df) >= 3 else rsi
                rsi_momentum_down = (rsi_3bars_ago - rsi) > 3  # LOOSENED: was >5
            
            # Accept if RSI momentum down OR relatively low (loosened from <35 to <45)
            rsi_ok = rsi_momentum_down or rsi < 45  # LOOSENED: was <35
            
            if (
                rsi_ok  # Relative RSI movement OR relatively low
                and latest["close"] < latest.get("bb_middle", current_price)  # LOOSENED: was bb_lower
                and latest.get("volume_ratio", 0) > vr_meanrev
            ):
                if rsi_momentum_down:
                    logger.debug(f"Mean reversion: RSI momentum down detected (-{rsi_3bars_ago - rsi:.1f} points in 3 bars), using relative movement")
                # Use lower BB as entry reference, but stop below it
                stop_loss, take_profit = calculate_stop_take("long", current_price, atr, "mean_reversion_long")
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

        # Mean reversion SHORT signal (RSI overbought with price at upper Bollinger Band)
        if self.config.enable_mean_reversion and self.config.is_signal_enabled("mean_reversion_short") and session != "opening":
            # LOOSENED (2026-01-07): More permissive thresholds
            rsi = latest.get("rsi", 50)
            rsi_momentum_up = False
            if len(df) >= 3 and "rsi" in df.columns:
                rsi_3bars_ago = df.iloc[-3].get("rsi", rsi) if len(df) >= 3 else rsi
                rsi_momentum_up = (rsi - rsi_3bars_ago) > 3  # LOOSENED: was >5
            
            # Accept if RSI momentum up OR relatively high (loosened from >65 to >55)
            rsi_ok = rsi_momentum_up or rsi > 55  # LOOSENED: was >65
            
            if (
                rsi_ok  # Relative RSI movement up OR relatively high
                and latest["close"] > latest.get("bb_middle", current_price)  # LOOSENED: was bb_upper
                and latest.get("volume_ratio", 0) > vr_meanrev
            ):
                if rsi_momentum_up:
                    logger.debug(f"Mean reversion short: RSI momentum up detected (+{rsi - rsi_3bars_ago:.1f} points in 3 bars), using relative movement")
                
                stop_loss, take_profit = calculate_stop_take("short", current_price, atr, "mean_reversion_short")
                # Adjust stop to be above upper BB
                if stop_loss < latest.get("bb_upper", stop_loss):
                    stop_loss = float(latest.get("bb_upper", stop_loss)) + (atr * 0.5)
                confidence = calculate_signal_score("mean_reversion_short", latest, df)

                # Adjust confidence based on regime
                confidence = self.regime_detector.adjust_confidence_by_regime(
                    "mean_reversion_short", confidence, regime
                )

                # Check MTF alignment (mean reversion less strict on MTF)
                is_aligned, mtf_adjustment = self.mtf_analyzer.check_signal_alignment(
                    "short", mtf_analysis
                )

                # During volatility expansion, relax MTF conflict threshold further
                atr_expansion = regime.get("atr_expansion", False)
                if atr_expansion and volatility == "high":
                    mtf_threshold = -0.30
                else:
                    mtf_threshold = -0.25

                # Allow mean reversion even with partial MTF conflict (it's counter-trend by nature)
                if is_aligned or mtf_adjustment >= mtf_threshold:
                    confidence = max(0.0, min(1.0, confidence + mtf_adjustment * 0.5))

                    # Adjust confidence based on VWAP position (mean reversion less sensitive to VWAP)
                    confidence = self.vwap_calculator.adjust_confidence_by_vwap(
                        "short", confidence, vwap_data
                    ) * 0.9

                    # Adjust confidence based on volume profile proximity
                    proximity = self.volume_profile.get_proximity_to_key_levels(
                        current_price, volume_profile_data
                    )
                    confidence = self.volume_profile.adjust_confidence_by_proximity(
                        confidence, proximity
                    )

                    # Check order flow alignment (mean reversion less strict)
                    is_flow_aligned, flow_adjustment = self.order_flow.check_signal_alignment(
                        "short", order_flow_data
                    )

                    if regime.get("volatility") == "high":
                        flow_threshold = -0.20
                    else:
                        flow_threshold = -0.12

                    if is_flow_aligned or flow_adjustment >= flow_threshold:
                        confidence = max(0.0, min(1.0, confidence + flow_adjustment * 0.5))

                        signals.append({
                            "type": "mean_reversion_short",
                            "direction": "short",
                            "confidence": confidence,
                            "entry_price": current_price,
                            "stop_loss": stop_loss,
                            "take_profit": float(latest.get("bb_middle", take_profit)),
                            "reason": "RSI overbought with price at upper Bollinger Band and volume confirmation",
                            "regime": regime,
                            "mtf_analysis": mtf_analysis,
                            "vwap_data": vwap_data,
                            "volume_profile": volume_profile_data,
                            "order_flow": order_flow_data,
                        })
                    else:
                        logger.debug("Mean reversion short signal rejected due to strong order flow conflict")
                else:
                    logger.debug("Mean reversion short signal rejected due to strong MTF conflict")

        # Breakout LONG signal (price breaks above *prior* recent high with volume)
        if self.config.enable_breakout and self.config.is_signal_enabled("breakout_long"):
            # IMPORTANT: use the prior window (exclude the current bar), otherwise
            # recent_high includes the current bar's high and the breakout condition can never be true.
            if len(df) >= 6:
                recent_high = df.iloc[:-1]["high"].tail(5).max()
            elif len(df) >= 2:
                recent_high = df.iloc[:-1]["high"].max()
            else:
                recent_high = None

            # Nothing to compare against (need at least 1 prior bar)
            if recent_high is not None:
                # Structure-first gate: check if this is a fresh breakout (within 0.3% of level)
                # Fresh breakouts are price-action based, not indicator-based, so relax RSI requirement
                is_fresh_breakout = False
                if latest["close"] > float(recent_high):
                    is_fresh_breakout = abs(current_price - float(recent_high)) / float(recent_high) < 0.003

                # For fresh breakouts, relax RSI requirement (structure breaks happen before indicators confirm)
                rsi = latest.get("rsi", 50)
                if is_fresh_breakout:
                    rsi_ok = rsi > 40  # Lower threshold for fresh breakouts
                else:
                    rsi_ok = rsi > 45  # Original threshold for established breakouts

                if (
                    latest["close"] > float(recent_high)
                    and latest.get("volume_ratio", 0) > vr_breakout  # Volume confirmation (session-aware)
                    and rsi_ok  # Conditional RSI threshold based on fresh breakout
                    and latest.get("macd_histogram", 0) > 0  # MACD bullish
                ):
                    stop_loss, take_profit = calculate_stop_take("long", current_price, atr, "breakout_long")
                    # Stop loss below recent high
                    stop_loss = min(stop_loss, float(recent_high) - (atr * 0.5))
                    confidence = calculate_signal_score("breakout_long", latest, df)

                    if is_fresh_breakout:
                        logger.debug(
                            f"Fresh breakout detected (within 0.3% of level {float(recent_high):.2f}), "
                            "applying structure-first gate with relaxed RSI threshold"
                        )

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
                    atr_expansion = regime.get("atr_expansion", False)
                    if is_fresh_breakout:
                        mtf_threshold = -0.25
                    elif atr_expansion and volatility == "high":
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
                        flow_threshold = -0.20 if is_fresh_breakout else -0.12

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
                                "reason": f"Price broke above recent high ({float(recent_high):.2f}) with strong volume and MACD confirmation",
                                "regime": regime,  # Include regime context
                                "mtf_analysis": mtf_analysis,  # Include MTF context
                                "vwap_data": vwap_data,  # Include VWAP context
                                "volume_profile": volume_profile_data,  # Include volume profile context
                                "order_flow": order_flow_data,  # Include order flow context
                            })
                        else:
                            logger.debug("Breakout long signal rejected due to order flow conflict")
                    else:
                        logger.debug("Breakout long signal rejected due to MTF conflict")

        # Breakout SHORT signal (price breaks below *prior* recent low with volume)
        if self.config.enable_breakout and self.config.is_signal_enabled("breakout_short"):
            # IMPORTANT: use the prior window (exclude the current bar), otherwise
            # recent_low includes the current bar's low and the breakdown condition can never be true.
            if len(df) >= 6:
                recent_low = df.iloc[:-1]["low"].tail(5).min()
            elif len(df) >= 2:
                recent_low = df.iloc[:-1]["low"].min()
            else:
                recent_low = None

            # Nothing to compare against (need at least 1 prior bar)
            if recent_low is not None:
                # Structure-first gate: check if this is a fresh breakdown (within 0.3% of level)
                is_fresh_breakdown = False
                if latest["close"] < float(recent_low):
                    is_fresh_breakdown = abs(current_price - float(recent_low)) / float(recent_low) < 0.003

                # For fresh breakdowns, relax RSI requirement
                rsi = latest.get("rsi", 50)
                if is_fresh_breakdown:
                    rsi_ok = rsi < 60  # Higher threshold for fresh breakdowns
                else:
                    rsi_ok = rsi < 55  # Original threshold for established breakdowns

                if (
                    latest["close"] < float(recent_low)
                    and latest.get("volume_ratio", 0) > vr_breakout  # Volume confirmation (session-aware)
                    and rsi_ok  # Conditional RSI threshold based on fresh breakdown
                    and latest.get("macd_histogram", 0) < 0  # MACD bearish
                ):
                    stop_loss, take_profit = calculate_stop_take("short", current_price, atr, "breakout_short")
                    # Stop loss above recent low
                    stop_loss = max(stop_loss, float(recent_low) + (atr * 0.5))
                    confidence = calculate_signal_score("breakout_short", latest, df)

                    if is_fresh_breakdown:
                        logger.debug(
                            f"Fresh breakdown detected (within 0.3% of level {float(recent_low):.2f}), "
                            "applying structure-first gate with relaxed RSI threshold"
                        )

                    # Adjust confidence based on regime
                    confidence = self.regime_detector.adjust_confidence_by_regime(
                        "breakout_short", confidence, regime
                    )

                    # Check MTF alignment (breakouts need strong MTF confirmation)
                    is_aligned, mtf_adjustment = self.mtf_analyzer.check_signal_alignment(
                        "short", mtf_analysis
                    )

                    # For breakdowns, check if we're breaking 5m/15m support
                    breakout_levels = self.mtf_analyzer.get_breakout_levels(mtf_analysis)
                    support_5m = breakout_levels.get("support_5m")
                    support_15m = breakout_levels.get("support_15m")

                    # Breakdown should break higher timeframe support
                    if support_5m and current_price > support_5m:
                        # Not breaking 5m support - reduce confidence
                        mtf_adjustment -= 0.15
                    elif support_5m and current_price < support_5m:
                        # Breaking 5m support - boost confidence
                        mtf_adjustment += 0.10

                    # Structure-first: allow fresh breakdowns even with MTF conflicts
                    atr_expansion = regime.get("atr_expansion", False)
                    if is_fresh_breakdown:
                        mtf_threshold = -0.25
                    elif atr_expansion and volatility == "high":
                        mtf_threshold = -0.25
                    else:
                        mtf_threshold = -0.20

                    if is_aligned or mtf_adjustment >= mtf_threshold:
                        confidence = max(0.0, min(1.0, confidence + mtf_adjustment))

                        # Adjust confidence based on VWAP position
                        confidence = self.vwap_calculator.adjust_confidence_by_vwap(
                            "short", confidence, vwap_data
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
                            "short", order_flow_data
                        )

                        # Structure-first: for fresh breakdowns, relax order flow conflict threshold
                        flow_threshold = -0.20 if is_fresh_breakdown else -0.12

                        if is_flow_aligned or flow_adjustment >= flow_threshold:
                            confidence = max(0.0, min(1.0, confidence + flow_adjustment))

                            signals.append({
                                "type": "breakout_short",
                                "direction": "short",
                                "confidence": confidence,
                                "entry_price": current_price,
                                "stop_loss": stop_loss,
                                "take_profit": take_profit,
                                "reason": f"Price broke below recent low ({float(recent_low):.2f}) with strong volume and MACD confirmation",
                                "regime": regime,
                                "mtf_analysis": mtf_analysis,
                                "vwap_data": vwap_data,
                                "volume_profile": volume_profile_data,
                                "order_flow": order_flow_data,
                            })
                        else:
                            logger.debug("Breakout short signal rejected due to order flow conflict")
                    else:
                        logger.debug("Breakout short signal rejected due to MTF conflict")

        # VWAP reversion signals (price returning to VWAP)
        if self.config.enable_mean_reversion and self.config.is_signal_enabled("vwap_reversion") and vwap_data.get("vwap", 0) > 0:
            vwap_signals = self._scan_vwap_reversion(
                df, latest, current_price, atr, vwap_data, regime,
                mtf_analysis, volume_profile_data, order_flow_data,
                calculate_stop_take, calculate_signal_score
            )
            signals.extend(vwap_signals)

        # Support/Resistance bounce signals
        # NOTE: sr_bounce has 3 wins in backtest - best performing signal type
        sr_levels = self._identify_support_resistance(df)
        if sr_levels and self.config.is_signal_enabled("sr_bounce"):
            sr_signals = self._scan_sr_levels(
                df, latest, current_price, atr, sr_levels, regime,
                mtf_analysis, vwap_data, volume_profile_data, order_flow_data,
                calculate_stop_take, calculate_signal_score
            )
            signals.extend(sr_signals)

        # Engulfing candle pattern signals
        # NOTE: engulfing has 0/3 wins in backtest - disabled by default via config
        if self.config.is_signal_enabled("engulfing"):
            engulfing_signals = self._scan_engulfing_patterns(
                df, latest, current_price, atr, regime,
                mtf_analysis, vwap_data, volume_profile_data, order_flow_data,
                calculate_stop_take, calculate_signal_score
            )
            signals.extend(engulfing_signals)

        # Custom indicator signals (supply/demand zones, power channel, divergences)
        # These are additional signal types that can be enabled/disabled via config
        custom_indicator_signals = self._scan_custom_indicators(
            df, latest, current_price, atr, regime,
            mtf_analysis, vwap_data, volume_profile_data, order_flow_data,
            calculate_stop_take, calculate_signal_score, custom_features
        )
        signals.extend(custom_indicator_signals)

        # Attach custom features to all signals for learning system
        for sig in signals:
            if custom_features:
                sig["custom_features"] = custom_features

        # Attach a compact HUD context to every signal for TradingView-style chart rendering.
        # Keep this computed once per scan cycle (not per signal) for performance.
        if signals:
            try:
                hud_context = build_hud_context(
                    df,
                    symbol=self.config.symbol,
                    tick_size=0.25,  # MNQ/NQ tick size (configurable later)
                    vwap_data=vwap_data,
                    volume_profile=volume_profile_data,
                    sr_levels=sr_levels,
                    threshold_pct=10.0,
                    bins=50,
                    power_length=130,
                    tbt_period=10,
                )
                for s in signals:
                    # Avoid mutating shared dict references across cycles.
                    s["hud_context"] = hud_context
            except Exception:
                # Never fail signal generation due to HUD context.
                pass

        return signals

    def _identify_support_resistance(
        self,
        df: pd.DataFrame,
        lookback: int = 50,
        min_touches: int = 2,
    ) -> Dict:
        """
        Identify key support and resistance levels from price action.
        
        Uses swing high/low pivots to find levels with multiple touches.
        
        Args:
            df: DataFrame with OHLCV data
            lookback: Number of bars to analyze
            min_touches: Minimum touches required for a valid level
            
        Returns:
            Dictionary with support and resistance levels:
            {
                "support_levels": [float, ...],
                "resistance_levels": [float, ...],
                "strongest_support": float,
                "strongest_resistance": float,
            }
        """
        if df.empty or len(df) < lookback:
            return {}

        df_recent = df.tail(lookback)
        
        # Find swing highs (local maxima)
        swing_highs = []
        for i in range(2, len(df_recent) - 2):
            if (df_recent["high"].iloc[i] > df_recent["high"].iloc[i-1] and
                df_recent["high"].iloc[i] > df_recent["high"].iloc[i-2] and
                df_recent["high"].iloc[i] > df_recent["high"].iloc[i+1] and
                df_recent["high"].iloc[i] > df_recent["high"].iloc[i+2]):
                swing_highs.append(float(df_recent["high"].iloc[i]))

        # Find swing lows (local minima)
        swing_lows = []
        for i in range(2, len(df_recent) - 2):
            if (df_recent["low"].iloc[i] < df_recent["low"].iloc[i-1] and
                df_recent["low"].iloc[i] < df_recent["low"].iloc[i-2] and
                df_recent["low"].iloc[i] < df_recent["low"].iloc[i+1] and
                df_recent["low"].iloc[i] < df_recent["low"].iloc[i+2]):
                swing_lows.append(float(df_recent["low"].iloc[i]))

        # Cluster nearby levels (within 0.2% of each other)
        def cluster_levels(levels: List[float], threshold_pct: float = 0.002) -> List[float]:
            if not levels:
                return []
            levels = sorted(levels)
            clusters = []
            current_cluster = [levels[0]]
            
            for level in levels[1:]:
                if abs(level - current_cluster[-1]) / current_cluster[-1] < threshold_pct:
                    current_cluster.append(level)
                else:
                    clusters.append(sum(current_cluster) / len(current_cluster))
                    current_cluster = [level]
            clusters.append(sum(current_cluster) / len(current_cluster))
            return clusters

        resistance_levels = cluster_levels(swing_highs)
        support_levels = cluster_levels(swing_lows)

        # Find strongest levels (most touches)
        current_price = df_recent["close"].iloc[-1]
        
        strongest_resistance = None
        if resistance_levels:
            # Closest resistance above current price
            above = [r for r in resistance_levels if r > current_price]
            if above:
                strongest_resistance = min(above)

        strongest_support = None
        if support_levels:
            # Closest support below current price
            below = [s for s in support_levels if s < current_price]
            if below:
                strongest_support = max(below)

        return {
            "support_levels": support_levels[-5:] if len(support_levels) > 5 else support_levels,
            "resistance_levels": resistance_levels[-5:] if len(resistance_levels) > 5 else resistance_levels,
            "strongest_support": strongest_support,
            "strongest_resistance": strongest_resistance,
        }

    def _scan_sr_levels(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        current_price: float,
        atr: float,
        sr_levels: Dict,
        regime: Dict,
        mtf_analysis: Dict,
        vwap_data: Dict,
        volume_profile_data: Dict,
        order_flow_data: Dict,
        calculate_stop_take,
        calculate_signal_score,
    ) -> List[Dict]:
        """
        Scan for signals at support/resistance levels.
        
        Generates signals when price bounces off support (long) or resistance (short).
        """
        signals = []

        # Overnight futures (Tokyo/London) often has lower relative volume.
        session = str(regime.get("session", "") or "").lower()
        vr_sr = 0.8 if session == "overnight" else 1.0

        strongest_support = sr_levels.get("strongest_support")
        strongest_resistance = sr_levels.get("strongest_resistance")
        
        if not strongest_support and not strongest_resistance:
            return signals

        # Check for support bounce (long signal)
        if strongest_support:
            # Price is at or near support (within 0.3%)
            distance_to_support = abs(current_price - strongest_support) / strongest_support
            
            if distance_to_support < 0.003:
                # Check for bounce conditions
                is_bouncing = (
                    latest.get("close") > latest.get("open")  # Up bar
                    and latest.get("low") <= strongest_support * 1.002  # Touched support
                    and latest.get("volume_ratio", 0) > vr_sr  # Volume present (session-aware)
                )
                
                if is_bouncing:
                    stop_loss, take_profit = calculate_stop_take("long", current_price, atr, "sr_bounce_long")
                    # Place stop below support
                    stop_loss = min(stop_loss, strongest_support - (atr * 0.5))
                    
                    confidence = calculate_signal_score("sr_bounce_long", latest, df)
                    
                    # Adjust for regime
                    confidence = self.regime_detector.adjust_confidence_by_regime(
                        "mean_reversion_long", confidence, regime
                    )
                    
                    if confidence >= 0.45:  # Slightly lower threshold for S/R
                        signals.append({
                            "type": "sr_bounce_long",
                            "direction": "long",
                            "confidence": confidence,
                            "entry_price": current_price,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "reason": f"Price bouncing off support level at {strongest_support:.2f}",
                            "regime": regime,
                            "mtf_analysis": mtf_analysis,
                            "vwap_data": vwap_data,
                            "volume_profile": volume_profile_data,
                            "order_flow": order_flow_data,
                            "sr_levels": sr_levels,
                        })

        # Check for resistance rejection (short signal)
        if strongest_resistance:
            # Price is at or near resistance (within 0.3%)
            distance_to_resistance = abs(current_price - strongest_resistance) / strongest_resistance
            
            if distance_to_resistance < 0.003:
                # Check for rejection conditions
                is_rejecting = (
                    latest.get("close") < latest.get("open")  # Down bar
                    and latest.get("high") >= strongest_resistance * 0.998  # Touched resistance
                    and latest.get("volume_ratio", 0) > vr_sr  # Volume present (session-aware)
                )
                
                if is_rejecting:
                    stop_loss, take_profit = calculate_stop_take("short", current_price, atr, "sr_bounce_short")
                    # Place stop above resistance
                    stop_loss = max(stop_loss, strongest_resistance + (atr * 0.5))
                    
                    confidence = calculate_signal_score("sr_bounce_short", latest, df)
                    
                    # Adjust for regime
                    confidence = self.regime_detector.adjust_confidence_by_regime(
                        "mean_reversion_short", confidence, regime
                    )
                    
                    if confidence >= 0.45:
                        signals.append({
                            "type": "sr_bounce_short",
                            "direction": "short",
                            "confidence": confidence,
                            "entry_price": current_price,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "reason": f"Price rejecting from resistance level at {strongest_resistance:.2f}",
                            "regime": regime,
                            "mtf_analysis": mtf_analysis,
                            "vwap_data": vwap_data,
                            "volume_profile": volume_profile_data,
                            "order_flow": order_flow_data,
                            "sr_levels": sr_levels,
                        })

        return signals

    def _scan_vwap_reversion(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        current_price: float,
        atr: float,
        vwap_data: Dict,
        regime: Dict,
        mtf_analysis: Dict,
        volume_profile_data: Dict,
        order_flow_data: Dict,
        calculate_stop_take,
        calculate_signal_score,
    ) -> List[Dict]:
        """
        Scan for VWAP reversion signals.
        
        Generates signals when price returns to VWAP after extended move.
        """
        signals = []

        # Overnight futures (Tokyo/London) typically has lower relative volume; relax slightly.
        session = str(regime.get("session", "") or "").lower()
        is_overnight = session == "overnight"
        vr_vwap = 0.8 if is_overnight else 1.0
        min_conf_vwap = 0.45 if is_overnight else 0.50
        
        vwap = vwap_data.get("vwap", 0)
        if vwap == 0:
            return signals

        distance_pct = vwap_data.get("distance_pct", 0)
        
        # Only look for VWAP reversion when price is extended from VWAP
        # and moving back toward it
        
        if len(df) < 3:
            return signals

        prev = df.iloc[-2]
        prev_close = prev.get("close", 0)
        
        # Long: Price was below VWAP, now crossing back up
        if distance_pct > -0.5 and distance_pct < 0.1:  # Near VWAP from below
            prev_distance = ((prev_close - vwap) / vwap * 100) if vwap > 0 else 0
            if prev_distance < -0.3 and current_price > prev_close:  # Was further below, now rising
                # VWAP long reversion
                stop_loss, take_profit = calculate_stop_take("long", current_price, atr, "vwap_reversion")
                confidence = calculate_signal_score("vwap_reversion_long", latest, df)
                
                # Adjust for regime
                confidence = self.regime_detector.adjust_confidence_by_regime(
                    "mean_reversion_long", confidence, regime
                )
                
                if confidence >= min_conf_vwap and latest.get("volume_ratio", 0) > vr_vwap:
                    signals.append({
                        "type": "vwap_reversion_long",
                        "direction": "long",
                        "confidence": confidence,
                        "entry_price": current_price,
                        "stop_loss": stop_loss,
                        "take_profit": vwap + (atr * 0.5),  # Target slightly above VWAP
                        "reason": f"Price reverting to VWAP ({vwap:.2f}) from below",
                        "regime": regime,
                        "mtf_analysis": mtf_analysis,
                        "vwap_data": vwap_data,
                        "volume_profile": volume_profile_data,
                        "order_flow": order_flow_data,
                    })

        # Short: Price was above VWAP, now crossing back down
        if distance_pct > -0.1 and distance_pct < 0.5:  # Near VWAP from above
            prev_distance = ((prev_close - vwap) / vwap * 100) if vwap > 0 else 0
            if prev_distance > 0.3 and current_price < prev_close:  # Was further above, now falling
                # VWAP short reversion
                stop_loss, take_profit = calculate_stop_take("short", current_price, atr, "vwap_reversion")
                confidence = calculate_signal_score("vwap_reversion_short", latest, df)
                
                # Adjust for regime
                confidence = self.regime_detector.adjust_confidence_by_regime(
                    "mean_reversion_short", confidence, regime
                )
                
                if confidence >= min_conf_vwap and latest.get("volume_ratio", 0) > vr_vwap:
                    signals.append({
                        "type": "vwap_reversion_short",
                        "direction": "short",
                        "confidence": confidence,
                        "entry_price": current_price,
                        "stop_loss": stop_loss,
                        "take_profit": vwap - (atr * 0.5),  # Target slightly below VWAP
                        "reason": f"Price reverting to VWAP ({vwap:.2f}) from above",
                        "regime": regime,
                        "mtf_analysis": mtf_analysis,
                        "vwap_data": vwap_data,
                        "volume_profile": volume_profile_data,
                        "order_flow": order_flow_data,
                    })

        return signals

    def _scan_engulfing_patterns(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        current_price: float,
        atr: float,
        regime: Dict,
        mtf_analysis: Dict,
        vwap_data: Dict,
        volume_profile_data: Dict,
        order_flow_data: Dict,
        calculate_stop_take,
        calculate_signal_score,
    ) -> List[Dict]:
        """
        Scan for engulfing candle patterns.
        
        Bullish engulfing: Down bar followed by up bar that completely engulfs it
        Bearish engulfing: Up bar followed by down bar that completely engulfs it
        """
        signals = []
        
        if len(df) < 3:
            return signals

        prev = df.iloc[-2]
        prev2 = df.iloc[-3]
        
        # Bullish engulfing
        prev_is_down = prev.get("close") < prev.get("open")
        curr_is_up = latest.get("close") > latest.get("open")
        bullish_engulf = (
            prev_is_down and curr_is_up and
            latest.get("open") <= prev.get("close") and
            latest.get("close") >= prev.get("open") and
            latest.get("volume_ratio", 0) > 1.2  # Strong volume
        )
        
        if bullish_engulf:
            stop_loss, take_profit = calculate_stop_take("long", current_price, atr, "engulfing_long")
            stop_loss = min(stop_loss, latest.get("low") - (atr * 0.25))  # Stop below engulfing low
            
            confidence = calculate_signal_score("engulfing_long", latest, df)
            confidence = self.regime_detector.adjust_confidence_by_regime(
                "momentum_long", confidence, regime
            )
            
            # Boost if after a downtrend (reversal pattern)
            if prev2.get("close", 0) > prev.get("close", 0):
                confidence = min(1.0, confidence + 0.05)
            
            if confidence >= 0.50:
                signals.append({
                    "type": "engulfing_long",
                    "direction": "long",
                    "confidence": confidence,
                    "entry_price": current_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "reason": "Bullish engulfing pattern with volume confirmation",
                    "regime": regime,
                    "mtf_analysis": mtf_analysis,
                    "vwap_data": vwap_data,
                    "volume_profile": volume_profile_data,
                    "order_flow": order_flow_data,
                })

        # Bearish engulfing
        prev_is_up = prev.get("close") > prev.get("open")
        curr_is_down = latest.get("close") < latest.get("open")
        bearish_engulf = (
            prev_is_up and curr_is_down and
            latest.get("open") >= prev.get("close") and
            latest.get("close") <= prev.get("open") and
            latest.get("volume_ratio", 0) > 1.2  # Strong volume
        )
        
        if bearish_engulf:
            stop_loss, take_profit = calculate_stop_take("short", current_price, atr, "engulfing_short")
            stop_loss = max(stop_loss, latest.get("high") + (atr * 0.25))  # Stop above engulfing high
            
            confidence = calculate_signal_score("engulfing_short", latest, df)
            confidence = self.regime_detector.adjust_confidence_by_regime(
                "momentum_short", confidence, regime
            )
            
            # Boost if after an uptrend (reversal pattern)
            if prev2.get("close", 0) < prev.get("close", 0):
                confidence = min(1.0, confidence + 0.05)
            
            if confidence >= 0.50:
                signals.append({
                    "type": "engulfing_short",
                    "direction": "short",
                    "confidence": confidence,
                    "entry_price": current_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "reason": "Bearish engulfing pattern with volume confirmation",
                    "regime": regime,
                    "mtf_analysis": mtf_analysis,
                    "vwap_data": vwap_data,
                    "volume_profile": volume_profile_data,
                    "order_flow": order_flow_data,
                })

        return signals

    def _scan_custom_indicators(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        current_price: float,
        atr: float,
        regime: Dict,
        mtf_analysis: Dict,
        vwap_data: Dict,
        volume_profile_data: Dict,
        order_flow_data: Dict,
        calculate_stop_take: Callable,
        calculate_signal_score: Callable,
        custom_features: Dict[str, float],
    ) -> List[Dict]:
        """
        Scan for signals from custom indicators (supply/demand, power channel, divergences).
        
        Each indicator can generate its own signals based on its internal logic.
        These signals are then filtered and adjusted like regular signals.
        
        Args:
            df: DataFrame with OHLCV and indicator data
            latest: Latest bar data
            current_price: Current price
            atr: Current ATR value
            regime: Market regime data
            mtf_analysis: Multi-timeframe analysis data
            vwap_data: VWAP data
            volume_profile_data: Volume profile data
            order_flow_data: Order flow data
            calculate_stop_take: Function to calculate stop loss and take profit
            calculate_signal_score: Function to calculate signal quality score
            custom_features: Extracted features from custom indicators
            
        Returns:
            List of signal dictionaries from custom indicators
        """
        signals = []
        
        # Check if custom indicator signals are enabled in config
        indicators_config = getattr(self.config, "indicators", None) or {}
        generate_signals = indicators_config.get("as_signals", True)
        
        if not generate_signals:
            return signals
        
        # Iterate through each custom indicator and generate signals
        for indicator in self.custom_indicators:
            try:
                # Check if this specific indicator's signals are enabled
                indicator_enabled = self.config.is_signal_enabled(indicator.name)
                if not indicator_enabled:
                    continue
                
                # Generate signal from indicator
                ind_signal = indicator.generate_signal(latest, df, atr)
                
                if ind_signal is None:
                    continue
                
                # Convert IndicatorSignal to dictionary
                signal_dict = ind_signal.to_dict()
                
                # Apply regime-based confidence adjustment
                # Map indicator signal types to base signal types for regime adjustment
                base_type_map = {
                    "sd_zone_bounce_long": "mean_reversion_long",
                    "sd_zone_bounce_short": "mean_reversion_short",
                    "pc_breakout_long": "breakout_long",
                    "pc_breakout_short": "breakout_short",
                    "pc_pullback_long": "mean_reversion_long",
                    "pc_pullback_short": "mean_reversion_short",
                    "smd_bullish_divergence": "mean_reversion_long",
                    "smd_bearish_divergence": "mean_reversion_short",
                }
                base_type = base_type_map.get(signal_dict["type"], "momentum_long")
                
                confidence = self.regime_detector.adjust_confidence_by_regime(
                    base_type, signal_dict["confidence"], regime
                )
                
                # Check MTF alignment
                is_aligned, mtf_adjustment = self.mtf_analyzer.check_signal_alignment(
                    signal_dict["direction"], mtf_analysis
                )
                
                # For custom indicators, use moderate MTF threshold (they have their own confirmation)
                mtf_threshold = -0.20
                if not is_aligned and mtf_adjustment < mtf_threshold:
                    logger.debug(
                        f"Custom indicator signal {signal_dict['type']} rejected due to MTF conflict"
                    )
                    continue
                
                confidence = max(0.0, min(1.0, confidence + mtf_adjustment * 0.7))
                
                # Adjust confidence based on VWAP position
                confidence = self.vwap_calculator.adjust_confidence_by_vwap(
                    signal_dict["direction"], confidence, vwap_data
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
                    signal_dict["direction"], order_flow_data
                )
                
                # Custom indicators are often counter-trend, so be more lenient on order flow
                if not is_flow_aligned and flow_adjustment < -0.15:
                    logger.debug(
                        f"Custom indicator signal {signal_dict['type']} rejected due to order flow conflict"
                    )
                    continue
                
                confidence = max(0.0, min(1.0, confidence + flow_adjustment * 0.5))
                
                # Minimum confidence threshold for custom indicator signals
                if confidence < 0.45:
                    logger.debug(
                        f"Custom indicator signal {signal_dict['type']} rejected: "
                        f"confidence {confidence:.3f} < 0.45"
                    )
                    continue
                
                # Build complete signal dictionary
                complete_signal = {
                    "type": signal_dict["type"],
                    "direction": signal_dict["direction"],
                    "confidence": confidence,
                    "entry_price": signal_dict["entry_price"],
                    "stop_loss": signal_dict["stop_loss"],
                    "take_profit": signal_dict["take_profit"],
                    "reason": signal_dict["reason"],
                    "regime": regime,
                    "mtf_analysis": mtf_analysis,
                    "vwap_data": vwap_data,
                    "volume_profile": volume_profile_data,
                    "order_flow": order_flow_data,
                    "indicator_metadata": signal_dict.get("indicator_metadata", {}),
                    "custom_features": custom_features,
                }
                
                signals.append(complete_signal)
                logger.info(
                    f"Custom indicator signal: {signal_dict['type']} | "
                    f"direction={signal_dict['direction']} | confidence={confidence:.3f} | "
                    f"entry={signal_dict['entry_price']:.2f}"
                )
                
            except Exception as e:
                logger.warning(f"Error generating signal from indicator {indicator.name}: {e}")
                continue
        
        return signals
