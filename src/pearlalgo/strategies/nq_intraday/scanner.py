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
    
    Uses unified strategy: EMA crossover + VWAP bias + RSI confirmation + ATR stops.
    Only trades in afternoon session during trending regimes.
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
        # Keep a reference to the canonical service config so scanner gates can follow
        # config.yaml (signals.regime_filters) instead of drifting into hard-coded behavior.
        self._service_config = service_config if isinstance(service_config, dict) else {}
        self.regime_detector = RegimeDetector()
        self.mtf_analyzer = MTFAnalyzer()
        self.vwap_calculator = VWAPCalculator()
        self.volume_profile = VolumeProfile()
        self.order_flow = OrderFlowApproximator(lookback_periods=self.config.lookback_periods)
        
        # Initialize custom indicators only when explicitly configured.
        indicators_config = getattr(config, "indicators", None) or {}
        if indicators_config:
            self.custom_indicators: List[IndicatorBase] = get_enabled_indicators(
                {"indicators": indicators_config}
            )
        else:
            self.custom_indicators = []
        
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
        vwap_data = self.vwap_calculator.calculate_vwap(df, atr=atr, dt=bar_dt)
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

        # ====================================================================
        # UNIFIED STRATEGY: EMA + VWAP + RSI + ATR (Lux Algo-style)
        # ====================================================================
        # Single unified strategy replacing all previous signal types.
        # Based on proven patterns: EMA crossover, VWAP bias, RSI confirmation, ATR stops.
        # ====================================================================
        
        session = regime.get("session", "afternoon")
        regime_type = regime.get("regime", "unknown")
        
        # Regime allowlist for unified strategy (canonical: signals.regime_filters.unified_strategy.allowed_regimes).
        # Default behavior (when config not present) remains "trending only".
        allowed_regimes = None
        try:
            rf = (self._service_config.get("signals", {}) or {}).get("regime_filters", {}) or {}
            allowed_regimes = (rf.get("unified_strategy", {}) or {}).get("allowed_regimes")
            if not isinstance(allowed_regimes, (list, tuple, set)):
                allowed_regimes = None
        except Exception:
            allowed_regimes = None
        if allowed_regimes is None:
            allowed_regimes = ("trending_bullish", "trending_bearish")
        if regime_type not in set(allowed_regimes):
            self.last_gate_reasons.append(f"Regime filter: {regime_type} not allowed")
            logger.debug(f"Skipping signals in {regime_type} regime (allowed={list(allowed_regimes)})")
            return signals

        # ====================================================================
        # UNIFIED STRATEGY: EMA + VWAP + RSI + ATR (Lux Algo-style)
        # ====================================================================
        # Single unified strategy replacing all previous signal types.
        # Based on proven patterns: EMA crossover, VWAP bias, RSI confirmation, ATR stops.
        # ====================================================================
        
        # Get indicators
        ema_fast = latest.get("sma_fast", 0)  # 9 EMA (fast)
        ema_slow = latest.get("sma_slow", 0)  # 20 EMA (slow)
        vwap = vwap_data.get("vwap", current_price)
        # VWAP bands (1σ) are used as a simple overextension guard to avoid chasing.
        try:
            vwap_upper_1 = float(vwap_data.get("vwap_upper_1", 0.0) or 0.0)
        except Exception:
            vwap_upper_1 = 0.0
        try:
            vwap_lower_1 = float(vwap_data.get("vwap_lower_1", 0.0) or 0.0)
        except Exception:
            vwap_lower_1 = 0.0
        rsi = latest.get("rsi", 50)
        macd_hist = latest.get("macd_histogram", 0)
        
        # Need at least 2 bars for crossover detection
        if len(df) < 2:
            return signals
        
        prev = df.iloc[-2]
        prev_ema_fast = prev.get("sma_fast", ema_fast)
        prev_ema_slow = prev.get("sma_slow", ema_slow)
        
        # Unified strategy logic
        signal_type = None
        direction = None
        confidence = 0.5  # Base confidence
        
        # LONG: EMA9 > EMA20, price > VWAP, RSI 40-70, MACD positive
        if (regime_type == "trending_bullish" and
            ema_fast > ema_slow and  # EMA crossover or trending
            current_price > vwap and  # Price above VWAP
            (vwap_upper_1 <= 0 or current_price <= vwap_upper_1) and  # avoid buying above +1σ VWAP
            40 <= rsi <= 70 and  # RSI in bullish range
            macd_hist > 0):  # MACD bullish
            
            # Check for EMA crossover or strong trend
            ema_crossed = (prev_ema_fast <= prev_ema_slow and ema_fast > ema_slow)
            ema_trending = (ema_fast > ema_slow and current_price > prev["close"])
            
            if ema_crossed or ema_trending:
                signal_type = "unified_strategy"
                direction = "long"
                confidence = 0.65  # Base confidence for unified strategy
                
                # Boost confidence for strong alignment
                if ema_crossed:
                    confidence += 0.10  # Fresh crossover
                if current_price > vwap * 1.001:  # Price well above VWAP
                    confidence += 0.05
                if 45 <= rsi <= 65:  # RSI in sweet spot
                    confidence += 0.05
                if macd_hist > 0.5:  # Strong MACD
                    confidence += 0.05
                
                # MTF alignment boost
                is_aligned, mtf_adjustment = self.mtf_analyzer.check_signal_alignment("long", mtf_analysis)
                if is_aligned:
                    confidence += 0.10
                elif mtf_adjustment > -0.15:
                    confidence += mtf_adjustment
                
                # VWAP boost
                confidence = self.vwap_calculator.adjust_confidence_by_vwap("long", confidence, vwap_data)
                
                confidence = min(confidence, 1.0)
        
        # SHORT: EMA9 < EMA20, price < VWAP, RSI 30-60, MACD negative
        elif (regime_type == "trending_bearish" and
              ema_fast < ema_slow and  # EMA crossover or trending
              current_price < vwap and  # Price below VWAP
              (vwap_lower_1 <= 0 or current_price >= vwap_lower_1) and  # avoid selling below -1σ VWAP
              30 <= rsi <= 60 and  # RSI in bearish range
              macd_hist < 0):  # MACD bearish
            
            # Check for EMA crossover or strong trend
            ema_crossed = (prev_ema_fast >= prev_ema_slow and ema_fast < ema_slow)
            ema_trending = (ema_fast < ema_slow and current_price < prev["close"])
            
            if ema_crossed or ema_trending:
                signal_type = "unified_strategy"
                direction = "short"
                confidence = 0.65  # Base confidence for unified strategy
                
                # Boost confidence for strong alignment
                if ema_crossed:
                    confidence += 0.10  # Fresh crossover
                if current_price < vwap * 0.999:  # Price well below VWAP
                    confidence += 0.05
                if 35 <= rsi <= 55:  # RSI in sweet spot
                    confidence += 0.05
                if macd_hist < -0.5:  # Strong MACD
                    confidence += 0.05
                
                # MTF alignment boost
                is_aligned, mtf_adjustment = self.mtf_analyzer.check_signal_alignment("short", mtf_analysis)
                if is_aligned:
                    confidence += 0.10
                elif mtf_adjustment > -0.15:
                    confidence += mtf_adjustment
                
                # VWAP boost
                confidence = self.vwap_calculator.adjust_confidence_by_vwap("short", confidence, vwap_data)
                
                confidence = min(confidence, 1.0)

        # RANGING: mean-reversion around VWAP (both directions).
        # This avoids the prior "trending-only" bias which produced prolonged quiet periods in ranging regimes.
        elif regime_type == "ranging":
            try:
                vwap_val = float(vwap or 0.0)
            except Exception:
                vwap_val = 0.0
            try:
                dist_pct = float(vwap_data.get("distance_pct", 0.0) or 0.0)  # percent
            except Exception:
                dist_pct = 0.0

            # Require a meaningful VWAP deviation to avoid spam in tight chop.
            dev_min_pct = 0.05  # 0.05% (~12.5 pts on 25k)
            # Avoid "catching a falling knife" when price is extremely extended from VWAP.
            # Scale by ATR for invariance across volatility regimes.
            dev_atr = None
            try:
                dist_pts = float(vwap_data.get("distance_from_vwap", 0.0) or 0.0)
                if float(atr) > 0:
                    dev_atr = abs(dist_pts) / float(atr)
            except Exception:
                dev_atr = None
            max_dev_atr = 2.5

            # Simple reversal confirmation: require momentum to start reverting.
            try:
                prev_close = float(prev.get("close", current_price))
            except Exception:
                prev_close = float(current_price)
            try:
                prev_rsi = float(prev.get("rsi", rsi))
            except Exception:
                prev_rsi = float(rsi)
            try:
                prev_macd = float(prev.get("macd_histogram", macd_hist))
            except Exception:
                prev_macd = float(macd_hist)

            # Long mean-reversion: price below VWAP + oversold RSI.
            if (
                vwap_val > 0
                and current_price < vwap_val
                and dist_pct <= -dev_min_pct
                and (dev_atr is None or dev_atr <= max_dev_atr)
                and rsi <= 40
                and current_price > prev_close
                and rsi >= prev_rsi
                and macd_hist >= prev_macd
            ):
                signal_type = "unified_strategy"
                direction = "long"
                confidence = 0.62
                if dist_pct <= -0.10:
                    confidence += 0.05
                if rsi <= 35:
                    confidence += 0.05
                if macd_hist > -0.4:
                    confidence += 0.03
                confidence = min(confidence, 1.0)

            # Short mean-reversion: price above VWAP + overbought RSI.
            elif (
                vwap_val > 0
                and current_price > vwap_val
                and dist_pct >= dev_min_pct
                and (dev_atr is None or dev_atr <= max_dev_atr)
                and rsi >= 60
                and current_price < prev_close
                and rsi <= prev_rsi
                and macd_hist <= prev_macd
            ):
                signal_type = "unified_strategy"
                direction = "short"
                confidence = 0.62
                if dist_pct >= 0.10:
                    confidence += 0.05
                if rsi >= 65:
                    confidence += 0.05
                if macd_hist < 0.4:
                    confidence += 0.03
                confidence = min(confidence, 1.0)
        
        # Generate signal if conditions met
        if signal_type and direction:
            # Use the shared stop/target calculator (adaptive stops + config-driven ATR multipliers).
            stop_loss, take_profit = calculate_stop_take(
                direction=direction,
                entry=current_price,
                atr_val=atr,
                signal_type=str(signal_type or "unified_strategy"),
            )
            
            # Minimum confidence threshold
            if confidence >= 0.60:
                logger.info(
                    f"📊 UNIFIED STRATEGY SIGNAL: {direction.upper()} | "
                    f"entry={current_price:.2f} | stop={stop_loss:.2f} | target={take_profit:.2f} | "
                    f"conf={confidence:.2f} | EMA9={ema_fast:.2f} EMA20={ema_slow:.2f} | "
                    f"VWAP={vwap:.2f} | RSI={rsi:.1f} | MACD={macd_hist:.2f}"
                )
                
                signals.append({
                    "type": "unified_strategy",
                    "direction": direction,
                    "confidence": confidence,
                    "entry_price": current_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "reason": f"EMA crossover + VWAP bias + RSI confirmation (EMA9={ema_fast:.2f}, EMA20={ema_slow:.2f}, VWAP={vwap:.2f}, RSI={rsi:.1f})",
                    "regime": regime,
                    "mtf_analysis": mtf_analysis,
                    "vwap_data": vwap_data,
                    "volume_profile": volume_profile_data,
                    "order_flow": order_flow_data,
                })
        
        # OLD SIGNAL GENERATION CODE REMOVED - replaced with unified strategy above
        # All momentum_long, momentum_short, mean_reversion, breakout, sr_bounce, etc. removed
        
        # Support/Resistance levels (still used for HUD context, but not for signals)
        sr_levels = self._identify_support_resistance(df) if hasattr(self, '_identify_support_resistance') else None
        # Attach custom features to all signals for learning system
        for sig in signals:
            if custom_features:
                sig["custom_features"] = custom_features

        # Final config enforcement: filter by the *actual* signal type.
        #
        # Some scanner gates use base keys (e.g., "sr_bounce") to decide whether to run a scan,
        # but the scan may emit more specific types (e.g., "sr_bounce_long"/"sr_bounce_short").
        # Filtering here ensures `strategy.disabled_signals` is respected for sub-types.
        try:
            filtered: List[Dict] = []
            for sig in signals:
                sig_type = str(sig.get("type") or "")
                if not sig_type:
                    continue
                if hasattr(self.config, "is_signal_enabled") and not self.config.is_signal_enabled(sig_type):
                    continue
                filtered.append(sig)
            signals = filtered
        except Exception:
            # Never fail the scan loop due to config filtering.
            pass

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

