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
        
        # RSI
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))
        
        # ATR for volatility
        high_low = df["high"] - df["low"]
        high_close = abs(df["high"] - df["close"].shift())
        low_close = abs(df["low"] - df["close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=14).mean()
        
        # Volume moving average
        df["volume_ma"] = df["volume"].rolling(window=20).mean()
        
        # Bollinger Bands
        df["bb_middle"] = df["close"].rolling(window=20).mean()
        bb_std = df["close"].rolling(window=20).std()
        df["bb_upper"] = df["bb_middle"] + (bb_std * 2)
        df["bb_lower"] = df["bb_middle"] - (bb_std * 2)
        
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
        
        # Momentum signal (fast MA crosses above slow MA)
        if self.config.enable_momentum:
            if len(df) >= 2:
                prev = df.iloc[-2]
                if (
                    prev["sma_fast"] < prev["sma_slow"]
                    and latest["sma_fast"] > latest["sma_slow"]
                    and latest["close"] > latest["sma_fast"]
                ):
                    signals.append({
                        "type": "momentum_long",
                        "direction": "long",
                        "confidence": 0.7,
                        "entry_price": float(latest["close"]),
                        "stop_loss": float(latest["close"] - (self.config.stop_loss_ticks * 0.25)),
                        "take_profit": float(latest["close"] + (self.config.take_profit_ticks * 0.25)),
                        "reason": "Fast MA crossed above slow MA with price confirmation",
                    })
        
        # Mean reversion signal (RSI oversold)
        if self.config.enable_mean_reversion:
            if latest.get("rsi", 50) < 30 and latest["close"] < latest["bb_lower"]:
                signals.append({
                    "type": "mean_reversion_long",
                    "direction": "long",
                    "confidence": 0.6,
                    "entry_price": float(latest["close"]),
                    "stop_loss": float(latest["bb_lower"] - (self.config.stop_loss_ticks * 0.25)),
                    "take_profit": float(latest["bb_middle"]),
                    "reason": "RSI oversold with price at lower Bollinger Band",
                })
        
        # Breakout signal
        if self.config.enable_breakout:
            if len(df) >= 5:
                recent_high = df["high"].tail(5).max()
                if latest["close"] > recent_high and latest["volume"] > latest.get("volume_ma", 0) * 1.5:
                    signals.append({
                        "type": "breakout_long",
                        "direction": "long",
                        "confidence": 0.65,
                        "entry_price": float(latest["close"]),
                        "stop_loss": float(latest["close"] - (self.config.stop_loss_ticks * 0.25)),
                        "take_profit": float(latest["close"] + (self.config.take_profit_ticks * 0.25)),
                        "reason": f"Price broke above recent high ({recent_high}) with volume confirmation",
                    })
        
        return signals
