"""
Volume Profile Calculator

Calculates volume-at-price profile for the trading session to identify
value areas (where most trading occurred) and POC (Point of Control).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class VolumeProfile:
    """
    Calculates volume profile for the trading session.
    
    Volume profile shows where most trading occurred (value areas).
    Price tends to return to value areas, making them key support/resistance levels.
    """

    def __init__(self, price_buckets: int = 50):
        """
        Initialize volume profile calculator.
        
        Args:
            price_buckets: Number of price buckets for volume distribution (default: 50)
        """
        self.price_buckets = price_buckets
        self._session_profile: Optional[Dict] = None
        self._session_start: Optional[datetime] = None
        logger.info(f"VolumeProfile initialized with {price_buckets} price buckets")

    def calculate_profile(
        self,
        df: pd.DataFrame,
        session_start: Optional[datetime] = None,
    ) -> Dict:
        """
        Calculate volume profile for the session.
        
        Args:
            df: DataFrame with OHLCV data
            session_start: Session start datetime (if None, uses today 9:30 ET)
            
        Returns:
            Dictionary with volume profile data:
            {
                "poc": float,  # Point of Control (price with highest volume)
                "value_area_high": float,  # Upper bound of value area (70% volume)
                "value_area_low": float,  # Lower bound of value area (70% volume)
                "profile": List[Dict],  # Volume at each price bucket
                "total_volume": float,
            }
        """
        if df.empty or len(df) < 5:
            return self._default_profile()

        # Filter to session data if session_start provided
        if session_start:
            df_session = self._filter_session_data(df, session_start)
        else:
            df_session = df.copy()

        if df_session.empty:
            return self._default_profile()

        # Get price range
        price_min = df_session["low"].min()
        price_max = df_session["high"].max()

        if price_max <= price_min:
            return self._default_profile()

        # Create price buckets
        price_range = price_max - price_min
        bucket_size = price_range / self.price_buckets

        # Initialize volume buckets
        volume_buckets = np.zeros(self.price_buckets)
        bucket_prices = []

        for i in range(self.price_buckets):
            bucket_price = price_min + (i + 0.5) * bucket_size
            bucket_prices.append(bucket_price)

        # Distribute volume to buckets
        for _, row in df_session.iterrows():
            high = row["high"]
            low = row["low"]
            volume = row["volume"]

            # Find buckets this bar spans
            low_bucket = int((low - price_min) / bucket_size)
            high_bucket = int((high - price_min) / bucket_size)

            # Clamp to valid range
            low_bucket = max(0, min(self.price_buckets - 1, low_bucket))
            high_bucket = max(0, min(self.price_buckets - 1, high_bucket))

            # Distribute volume evenly across spanned buckets
            if high_bucket > low_bucket:
                volume_per_bucket = volume / (high_bucket - low_bucket + 1)
                for bucket_idx in range(low_bucket, high_bucket + 1):
                    volume_buckets[bucket_idx] += volume_per_bucket
            else:
                # Single bucket
                volume_buckets[low_bucket] += volume

        # Find POC (Point of Control - price with highest volume)
        poc_idx = np.argmax(volume_buckets)
        poc = bucket_prices[poc_idx]

        # Calculate value area (70% of volume)
        total_volume = volume_buckets.sum()
        if total_volume == 0:
            return self._default_profile()

        target_volume = total_volume * 0.70

        # Find value area bounds
        # Start from POC and expand outward until we have 70% of volume
        value_area_high_idx = poc_idx
        value_area_low_idx = poc_idx
        accumulated_volume = volume_buckets[poc_idx]

        while accumulated_volume < target_volume:
            # Check which direction to expand
            high_volume = volume_buckets[value_area_high_idx + 1] if value_area_high_idx + 1 < self.price_buckets else 0
            low_volume = volume_buckets[value_area_low_idx - 1] if value_area_low_idx - 1 >= 0 else 0

            if high_volume > low_volume and value_area_high_idx + 1 < self.price_buckets:
                value_area_high_idx += 1
                accumulated_volume += volume_buckets[value_area_high_idx]
            elif value_area_low_idx - 1 >= 0:
                value_area_low_idx -= 1
                accumulated_volume += volume_buckets[value_area_low_idx]
            else:
                # Can't expand further
                break

        value_area_high = bucket_prices[value_area_high_idx]
        value_area_low = bucket_prices[value_area_low_idx]

        # Build profile list
        profile = []
        for i in range(self.price_buckets):
            profile.append({
                "price": bucket_prices[i],
                "volume": float(volume_buckets[i]),
            })

        result = {
            "poc": float(poc),
            "value_area_high": float(value_area_high),
            "value_area_low": float(value_area_low),
            "profile": profile,
            "total_volume": float(total_volume),
        }

        # Cache for session
        self._session_profile = result

        return result

    def _filter_session_data(self, df: pd.DataFrame, session_start: datetime) -> pd.DataFrame:
        """Filter DataFrame to session data."""
        if df.empty:
            return df

        if "timestamp" in df.columns:
            df_filtered = df[df["timestamp"] >= session_start].copy()
        elif df.index.name == "timestamp" or isinstance(df.index, pd.DatetimeIndex):
            df_filtered = df[df.index >= session_start].copy()
        else:
            # No timestamp - assume all data is from current session
            df_filtered = df.copy()

        return df_filtered

    def get_proximity_to_key_levels(
        self,
        price: float,
        profile: Dict,
    ) -> Dict:
        """
        Calculate proximity to key volume profile levels.
        
        Args:
            price: Current price
            profile: Volume profile from calculate_profile()
            
        Returns:
            Dictionary with proximity information:
            {
                "near_poc": bool,
                "near_value_area": bool,
                "distance_to_poc": float,
                "distance_to_poc_pct": float,
                "in_value_area": bool,
            }
        """
        poc = profile.get("poc", 0)
        value_area_high = profile.get("value_area_high", 0)
        value_area_low = profile.get("value_area_low", 0)

        if poc == 0:
            return {
                "near_poc": False,
                "near_value_area": False,
                "distance_to_poc": 0.0,
                "distance_to_poc_pct": 0.0,
                "in_value_area": False,
            }

        distance_to_poc = abs(price - poc)
        distance_to_poc_pct = (distance_to_poc / poc) * 100 if poc > 0 else 0.0

        # Near POC if within 0.1% of price
        near_poc = distance_to_poc_pct < 0.1

        # In value area
        in_value_area = value_area_low <= price <= value_area_high

        # Near value area (within 0.2% of bounds)
        near_value_area = in_value_area
        if not near_value_area:
            if value_area_high > 0:
                dist_to_high = abs(price - value_area_high) / value_area_high * 100
                dist_to_low = abs(price - value_area_low) / value_area_low * 100 if value_area_low > 0 else 999
                near_value_area = dist_to_high < 0.2 or dist_to_low < 0.2

        return {
            "near_poc": near_poc,
            "near_value_area": near_value_area,
            "distance_to_poc": float(distance_to_poc),
            "distance_to_poc_pct": float(distance_to_poc_pct),
            "in_value_area": in_value_area,
        }

    def adjust_confidence_by_proximity(
        self,
        signal_confidence: float,
        proximity: Dict,
    ) -> float:
        """
        Adjust signal confidence based on proximity to key volume profile levels.
        
        Args:
            signal_confidence: Base signal confidence (0-1)
            proximity: Proximity data from get_proximity_to_key_levels()
            
        Returns:
            Adjusted confidence (0-1)
        """
        adjusted = signal_confidence

        # Signals near POC get confidence boost (high liquidity area)
        if proximity.get("near_poc", False):
            adjusted += 0.08

        # Signals near value area edges get boost (potential reversal to value)
        if proximity.get("near_value_area", False) and not proximity.get("in_value_area", False):
            adjusted += 0.05

        # Signals in value area get slight boost (trading in value)
        if proximity.get("in_value_area", False):
            adjusted += 0.03

        # Clamp to [0, 1]
        return max(0.0, min(1.0, adjusted))

    def _default_profile(self) -> Dict:
        """Return default profile when data is insufficient."""
        return {
            "poc": 0.0,
            "value_area_high": 0.0,
            "value_area_low": 0.0,
            "profile": [],
            "total_volume": 0.0,
        }



