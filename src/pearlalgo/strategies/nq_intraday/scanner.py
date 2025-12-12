"""
NQ Intraday Market Scanner

Scans NQ futures for intraday trading opportunities using real-time data.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Dict, List, Optional

import pandas as pd

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


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
        logger.info(f"NQScanner initialized with symbol={self.config.symbol}, timeframe={self.config.timeframe}")
    
    def is_market_hours(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if current time is within market hours.
        
        Args:
            dt: Datetime to check (default: now)
            
        Returns:
            True if within market hours
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        
        # Convert to ET (simplified - in production use proper timezone handling)
        # ET is UTC-5 (EST) or UTC-4 (EDT)
        et_offset = -5  # Simplified: assume EST
        et_time = dt.replace(tzinfo=None).replace(hour=dt.hour + et_offset)
        
        start = time.fromisoformat(self.config.start_time)
        end = time.fromisoformat(self.config.end_time)
        
        current_time = et_time.time()
        return start <= current_time <= end
    
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
    
    def scan(self, df: pd.DataFrame) -> List[Dict]:
        """
        Scan market data for trading signals.
        
        Args:
            df: DataFrame with OHLCV data and indicators
            
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
        
        # Get latest bar
        latest = df.iloc[-1]
        
        # Check volume threshold
        if latest.get("volume", 0) < self.config.min_volume:
            return signals
        
        # Check volatility threshold
        if latest.get("atr", 0) / latest["close"] < self.config.volatility_threshold:
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
            score = 0.5  # Base score
            
            # Volume confirmation
            volume_ratio = latest.get("volume_ratio", 1.0)
            if volume_ratio > 1.5:
                score += 0.15
            elif volume_ratio > 1.2:
                score += 0.1
            
            # Volatility (ATR)
            atr_pct = (latest.get("atr", 0) / latest["close"]) if latest["close"] > 0 else 0
            if 0.001 <= atr_pct <= 0.01:  # Good volatility range
                score += 0.1
            
            # RSI confirmation
            rsi = latest.get("rsi", 50)
            if signal_type == "momentum_long" and 40 < rsi < 70:
                score += 0.1
            elif signal_type == "mean_reversion_long" and rsi < 30:
                score += 0.15
            elif signal_type == "breakout_long" and rsi > 50:
                score += 0.1
            
            # MACD confirmation
            if "macd_histogram" in latest:
                macd_hist = latest.get("macd_histogram", 0)
                if signal_type == "momentum_long" and macd_hist > 0:
                    score += 0.1
                elif signal_type == "mean_reversion_long" and macd_hist < 0:
                    score += 0.1
            
            # Price position relative to MAs
            if "sma_50" in latest and latest["close"] > latest.get("sma_50", 0):
                score += 0.05
            
            return min(score, 1.0)
        
        # Momentum signal (fast MA crosses above slow MA with MACD confirmation)
        if self.config.enable_momentum:
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
                    
                    signals.append({
                        "type": "momentum_long",
                        "direction": "long",
                        "confidence": confidence,
                        "entry_price": current_price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "reason": "Fast MA crossed above slow MA with volume and MACD confirmation",
                    })
        
        # Mean reversion signal (RSI oversold with multiple confirmations)
        if self.config.enable_mean_reversion:
            if (
                latest.get("rsi", 50) < 30
                and latest["close"] < latest.get("bb_lower", current_price)
                and latest.get("volume_ratio", 0) > 1.0
            ):
                # Use lower BB as entry reference, but stop below it
                stop_loss, take_profit = calculate_stop_take("long", current_price, atr)
                # Adjust stop to be below lower BB
                if stop_loss > latest.get("bb_lower", stop_loss):
                    stop_loss = float(latest.get("bb_lower", stop_loss)) - (atr * 0.5)
                confidence = calculate_signal_score("mean_reversion_long", latest, df)
                
                signals.append({
                    "type": "mean_reversion_long",
                    "direction": "long",
                    "confidence": confidence,
                    "entry_price": current_price,
                    "stop_loss": stop_loss,
                    "take_profit": float(latest.get("bb_middle", take_profit)),
                    "reason": "RSI oversold with price at lower Bollinger Band and volume confirmation",
                })
        
        # Breakout signal (price breaks above recent high with volume)
        if self.config.enable_breakout:
            if len(df) >= 5:
                recent_high = df["high"].tail(5).max()
                if (
                    latest["close"] > recent_high
                    and latest.get("volume_ratio", 0) > 1.5
                    and latest.get("rsi", 50) > 50  # Not oversold
                    and latest.get("macd_histogram", 0) > 0  # MACD bullish
                ):
                    stop_loss, take_profit = calculate_stop_take("long", current_price, atr)
                    # Stop loss below recent high
                    stop_loss = min(stop_loss, float(recent_high) - (atr * 0.5))
                    confidence = calculate_signal_score("breakout_long", latest, df)
                    
                    signals.append({
                        "type": "breakout_long",
                        "direction": "long",
                        "confidence": confidence,
                        "entry_price": current_price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "reason": f"Price broke above recent high ({recent_high:.2f}) with strong volume and MACD confirmation",
                    })
        
        return signals
