"""
Options Feature Computation Module

Provides modular feature computation for options trading strategies:
- Moving averages (SMA, EMA)
- Implied volatility calculations
- Volume spike detection
- Momentum indicators (RSI, MACD)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class OptionsFeatureComputer:
    """
    Computes technical features for options trading strategies.
    
    All parameters are configurable via config.yaml.
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize feature computer.
        
        Args:
            config: Configuration dictionary with feature parameters
        """
        self.config = config or {}
        
        # Default parameters (can be overridden by config)
        self.default_periods = {
            'sma_short': 20,
            'sma_long': 50,
            'ema_short': 12,
            'ema_long': 26,
            'rsi_period': 14,
            'macd_signal': 9,
            'volume_spike_lookback': 20,
        }
        
        logger.info("OptionsFeatureComputer initialized")
    
    def compute_moving_averages(
        self,
        df: pd.DataFrame,
        periods: Optional[Dict[str, int]] = None,
    ) -> pd.DataFrame:
        """
        Compute Simple Moving Average (SMA) and Exponential Moving Average (EMA).
        
        Args:
            df: DataFrame with 'close' column
            periods: Dictionary with 'sma_short', 'sma_long', 'ema_short', 'ema_long'
            
        Returns:
            DataFrame with added columns: sma_short, sma_long, ema_short, ema_long
        """
        if df.empty or 'close' not in df.columns:
            logger.warning("Cannot compute moving averages: empty DataFrame or missing 'close' column")
            return df
        
        df = df.copy()
        periods = periods or self.default_periods
        
        # SMA
        sma_short = periods.get('sma_short', 20)
        sma_long = periods.get('sma_long', 50)
        
        if sma_short > 0:
            df['sma_short'] = df['close'].rolling(window=sma_short).mean()
        if sma_long > 0:
            df['sma_long'] = df['close'].rolling(window=sma_long).mean()
        
        # EMA
        ema_short = periods.get('ema_short', 12)
        ema_long = periods.get('ema_long', 26)
        
        if ema_short > 0:
            df['ema_short'] = df['close'].ewm(span=ema_short, adjust=False).mean()
        if ema_long > 0:
            df['ema_long'] = df['close'].ewm(span=ema_long, adjust=False).mean()
        
        logger.debug(f"Computed moving averages: SMA({sma_short}, {sma_long}), EMA({ema_short}, {ema_long})")
        
        return df
    
    def compute_implied_volatility(
        self,
        options_chain: List[Dict],
        method: str = "bid_ask_spread",
    ) -> Dict[str, float]:
        """
        Compute implied volatility from options chain.
        
        Args:
            options_chain: List of option contracts with bid/ask prices
            method: Method to compute IV ("bid_ask_spread", "mid_price")
            
        Returns:
            Dictionary with 'avg_iv', 'min_iv', 'max_iv', 'iv_percentile'
        """
        if not options_chain:
            return {
                'avg_iv': 0.0,
                'min_iv': 0.0,
                'max_iv': 0.0,
                'iv_percentile': 0.0,
            }
        
        iv_values = []
        
        for option in options_chain:
            bid = option.get('bid')
            ask = option.get('ask')
            last_price = option.get('last_price')
            strike = option.get('strike')
            
            if not strike or strike <= 0:
                continue
            
            # Use bid-ask spread as proxy for IV (wider spread = higher IV)
            if method == "bid_ask_spread" and bid is not None and ask is not None:
                mid_price = (bid + ask) / 2
                if mid_price > 0:
                    spread_pct = (ask - bid) / mid_price
                    iv_values.append(spread_pct)
            elif method == "mid_price" and bid is not None and ask is not None:
                mid_price = (bid + ask) / 2
                if mid_price > 0 and strike > 0:
                    # Simple IV approximation: price/strike ratio
                    iv_approx = mid_price / strike
                    iv_values.append(iv_approx)
            elif last_price is not None and strike > 0:
                # Fallback: use last price
                iv_approx = last_price / strike
                iv_values.append(iv_approx)
        
        if not iv_values:
            return {
                'avg_iv': 0.0,
                'min_iv': 0.0,
                'max_iv': 0.0,
                'iv_percentile': 0.0,
            }
        
        iv_array = np.array(iv_values)
        
        result = {
            'avg_iv': float(np.mean(iv_array)),
            'min_iv': float(np.min(iv_array)),
            'max_iv': float(np.max(iv_array)),
            'iv_percentile': float(np.percentile(iv_array, 50)),  # Median
        }
        
        logger.debug(f"Computed IV: avg={result['avg_iv']:.4f}, min={result['min_iv']:.4f}, max={result['max_iv']:.4f}")
        
        return result
    
    def detect_volume_spikes(
        self,
        df: pd.DataFrame,
        threshold: float = 2.0,
        lookback: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Detect volume spikes (anomalies).
        
        Args:
            df: DataFrame with 'volume' column
            threshold: Multiplier for average volume (e.g., 2.0 = 2x average)
            lookback: Lookback period for average (default from config)
            
        Returns:
            DataFrame with added columns: volume_avg, volume_spike, volume_spike_ratio
        """
        if df.empty or 'volume' not in df.columns:
            logger.warning("Cannot detect volume spikes: empty DataFrame or missing 'volume' column")
            return df
        
        df = df.copy()
        lookback = lookback or self.default_periods.get('volume_spike_lookback', 20)
        
        # Compute rolling average volume
        df['volume_avg'] = df['volume'].rolling(window=lookback).mean()
        
        # Detect spikes
        df['volume_spike'] = df['volume'] > (df['volume_avg'] * threshold)
        df['volume_spike_ratio'] = df['volume'] / df['volume_avg'].replace(0, np.nan)
        
        # Fill NaN values
        df['volume_spike'] = df['volume_spike'].fillna(False)
        df['volume_spike_ratio'] = df['volume_spike_ratio'].fillna(1.0)
        
        spike_count = df['volume_spike'].sum()
        logger.debug(f"Detected {spike_count} volume spikes (threshold={threshold}x, lookback={lookback})")
        
        return df
    
    def compute_momentum_indicators(
        self,
        df: pd.DataFrame,
        rsi_period: Optional[int] = None,
        macd_params: Optional[Dict] = None,
    ) -> pd.DataFrame:
        """
        Compute momentum indicators: RSI and MACD.
        
        Args:
            df: DataFrame with 'close' column
            rsi_period: RSI period (default from config)
            macd_params: Dictionary with 'fast', 'slow', 'signal' periods
            
        Returns:
            DataFrame with added columns: rsi, macd, macd_signal, macd_histogram
        """
        if df.empty or 'close' not in df.columns:
            logger.warning("Cannot compute momentum indicators: empty DataFrame or missing 'close' column")
            return df
        
        df = df.copy()
        
        # RSI
        rsi_period = rsi_period or self.default_periods.get('rsi_period', 14)
        if rsi_period > 0 and len(df) > rsi_period:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
            rs = gain / loss.replace(0, np.nan)
            df['rsi'] = 100 - (100 / (1 + rs))
        else:
            df['rsi'] = np.nan
        
        # MACD
        macd_params = macd_params or {
            'fast': self.default_periods.get('ema_short', 12),
            'slow': self.default_periods.get('ema_long', 26),
            'signal': self.default_periods.get('macd_signal', 9),
        }
        
        fast_period = macd_params.get('fast', 12)
        slow_period = macd_params.get('slow', 26)
        signal_period = macd_params.get('signal', 9)
        
        if fast_period > 0 and slow_period > 0 and len(df) > slow_period:
            ema_fast = df['close'].ewm(span=fast_period, adjust=False).mean()
            ema_slow = df['close'].ewm(span=slow_period, adjust=False).mean()
            df['macd'] = ema_fast - ema_slow
            
            if signal_period > 0:
                df['macd_signal'] = df['macd'].ewm(span=signal_period, adjust=False).mean()
                df['macd_histogram'] = df['macd'] - df['macd_signal']
            else:
                df['macd_signal'] = np.nan
                df['macd_histogram'] = np.nan
        else:
            df['macd'] = np.nan
            df['macd_signal'] = np.nan
            df['macd_histogram'] = np.nan
        
        logger.debug(f"Computed momentum indicators: RSI({rsi_period}), MACD({fast_period},{slow_period},{signal_period})")
        
        return df
    
    def compute_all_features(
        self,
        df: pd.DataFrame,
        options_chain: Optional[List[Dict]] = None,
    ) -> pd.DataFrame:
        """
        Compute all available features.
        
        Args:
            df: DataFrame with OHLCV data
            options_chain: Optional options chain for IV computation
            
        Returns:
            DataFrame with all computed features
        """
        logger.info("Computing all features")
        
        # Moving averages
        df = self.compute_moving_averages(df)
        
        # Volume spikes
        df = self.detect_volume_spikes(df)
        
        # Momentum indicators
        df = self.compute_momentum_indicators(df)
        
        # IV (if options chain provided)
        if options_chain:
            iv_data = self.compute_implied_volatility(options_chain)
            # Add IV as constant columns (could be enhanced to be time-varying)
            for key, value in iv_data.items():
                df[f'iv_{key}'] = value
        
        logger.info(f"Computed all features: {len(df.columns)} total columns")
        
        return df
