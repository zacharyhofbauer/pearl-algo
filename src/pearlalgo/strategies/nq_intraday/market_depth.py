"""
Market Depth Analysis for Intelligent Stop/Entry Placement

Since Level 2 data is not available (only Level 1 subscription), this module
provides intelligent stop placement using:
- Volume profile analysis (identify support/resistance zones)
- Swing high/low detection (structure-based stops)
- Price cluster identification (avoid obvious liquidity pools)
- Recent price action analysis (identify sweep zones)

These techniques help place stops OUTSIDE predictable market maker target zones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pearlalgo.utils.logger import logger


@dataclass
class SupportResistanceZone:
    """Represents a support or resistance zone."""
    price: float
    strength: float  # 0-1, based on touches and volume
    zone_type: str  # "support" or "resistance"
    width_points: float  # Zone width in price points
    touches: int  # Number of times price touched this level
    is_recent: bool  # Within last 20 bars


@dataclass
class StopPlacementAdvice:
    """Advice for stop placement to avoid stop hunting."""
    recommended_stop: float
    original_stop: float
    adjustment_reason: str
    danger_zones: List[Tuple[float, float]]  # Price ranges to avoid
    safe_zone_confidence: float  # 0-1, how confident we are in the safe zone


class MarketDepthAnalyzer:
    """
    Analyzes market structure to provide intelligent stop/entry placement.
    
    Without Level 2 data, we use:
    1. Volume profile - identify high-volume price levels (likely support/resistance)
    2. Swing points - recent highs/lows where stops cluster
    3. Round numbers - psychological levels ($25,600, $25,650, etc.)
    4. Recent sweep zones - areas recently swept for liquidity
    """
    
    def __init__(
        self,
        lookback_periods: int = 50,
        swing_lookback: int = 5,
        round_number_interval: float = 25.0,  # MNQ round numbers at 25-point intervals
        zone_width_atr_mult: float = 0.3,  # Zone width as ATR multiplier
    ):
        """
        Initialize the market depth analyzer.
        
        Args:
            lookback_periods: Number of bars to analyze
            swing_lookback: Bars to look for swing points
            round_number_interval: Interval for psychological levels
            zone_width_atr_mult: Zone width as multiple of ATR
        """
        self.lookback_periods = lookback_periods
        self.swing_lookback = swing_lookback
        self.round_number_interval = round_number_interval
        self.zone_width_atr_mult = zone_width_atr_mult
        
        logger.debug(
            f"MarketDepthAnalyzer initialized: lookback={lookback_periods}, "
            f"swing_lookback={swing_lookback}"
        )
    
    def find_support_resistance_zones(
        self,
        df: pd.DataFrame,
        current_price: float,
        atr: float,
    ) -> List[SupportResistanceZone]:
        """
        Identify support and resistance zones from price action.
        
        Uses:
        - Swing highs/lows
        - Volume clusters
        - Round numbers
        - Recent rejection levels
        
        Args:
            df: DataFrame with OHLCV data
            current_price: Current price
            atr: Current ATR for zone width calculation
            
        Returns:
            List of SupportResistanceZone objects
        """
        if df.empty or len(df) < self.swing_lookback * 2:
            return []
        
        zones: List[SupportResistanceZone] = []
        recent_df = df.tail(self.lookback_periods).copy()
        zone_width = atr * self.zone_width_atr_mult
        
        # 1. Find swing highs (resistance)
        swing_highs = self._find_swing_highs(recent_df)
        for price, idx in swing_highs:
            is_recent = idx >= len(recent_df) - 20
            touches = self._count_touches(recent_df, price, zone_width, "high")
            strength = min(1.0, touches * 0.2 + (0.3 if is_recent else 0))
            
            zones.append(SupportResistanceZone(
                price=price,
                strength=strength,
                zone_type="resistance",
                width_points=zone_width,
                touches=touches,
                is_recent=is_recent,
            ))
        
        # 2. Find swing lows (support)
        swing_lows = self._find_swing_lows(recent_df)
        for price, idx in swing_lows:
            is_recent = idx >= len(recent_df) - 20
            touches = self._count_touches(recent_df, price, zone_width, "low")
            strength = min(1.0, touches * 0.2 + (0.3 if is_recent else 0))
            
            zones.append(SupportResistanceZone(
                price=price,
                strength=strength,
                zone_type="support",
                width_points=zone_width,
                touches=touches,
                is_recent=is_recent,
            ))
        
        # 3. Add round numbers near current price
        round_numbers = self._find_round_numbers(
            current_price, range_points=atr * 5
        )
        for rn in round_numbers:
            is_support = rn < current_price
            zones.append(SupportResistanceZone(
                price=rn,
                strength=0.4,  # Round numbers are moderate strength
                zone_type="support" if is_support else "resistance",
                width_points=zone_width * 0.5,  # Tighter zone for round numbers
                touches=0,
                is_recent=False,
            ))
        
        # 4. Add volume-weighted levels
        volume_levels = self._find_volume_clusters(recent_df, atr)
        for price, volume_strength in volume_levels:
            is_support = price < current_price
            zones.append(SupportResistanceZone(
                price=price,
                strength=volume_strength,
                zone_type="support" if is_support else "resistance",
                width_points=zone_width,
                touches=0,
                is_recent=True,
            ))
        
        # Sort by distance from current price
        zones.sort(key=lambda z: abs(z.price - current_price))
        
        return zones
    
    def _find_swing_highs(self, df: pd.DataFrame) -> List[Tuple[float, int]]:
        """Find swing high points (local maxima)."""
        highs = []
        lookback = self.swing_lookback
        
        for i in range(lookback, len(df) - lookback):
            high = df.iloc[i]["high"]
            is_swing = True
            
            # Check if this is a local maximum
            for j in range(i - lookback, i + lookback + 1):
                if j != i and df.iloc[j]["high"] > high:
                    is_swing = False
                    break
            
            if is_swing:
                highs.append((float(high), i))
        
        return highs
    
    def _find_swing_lows(self, df: pd.DataFrame) -> List[Tuple[float, int]]:
        """Find swing low points (local minima)."""
        lows = []
        lookback = self.swing_lookback
        
        for i in range(lookback, len(df) - lookback):
            low = df.iloc[i]["low"]
            is_swing = True
            
            # Check if this is a local minimum
            for j in range(i - lookback, i + lookback + 1):
                if j != i and df.iloc[j]["low"] < low:
                    is_swing = False
                    break
            
            if is_swing:
                lows.append((float(low), i))
        
        return lows
    
    def _count_touches(
        self,
        df: pd.DataFrame,
        price: float,
        zone_width: float,
        touch_type: str,
    ) -> int:
        """Count how many times price touched a level."""
        touches = 0
        half_width = zone_width / 2
        
        for _, row in df.iterrows():
            if touch_type == "high":
                # For resistance, count times high approached but didn't break through
                if abs(row["high"] - price) < half_width:
                    touches += 1
            else:
                # For support, count times low approached but didn't break through
                if abs(row["low"] - price) < half_width:
                    touches += 1
        
        return touches
    
    def _find_round_numbers(
        self,
        current_price: float,
        range_points: float,
    ) -> List[float]:
        """Find psychological round numbers near current price."""
        interval = self.round_number_interval
        
        # Find nearest round number below
        lower = (current_price // interval) * interval
        
        # Generate round numbers in range
        round_numbers = []
        price = lower - interval * 2
        while price < current_price + range_points:
            if abs(price - current_price) <= range_points:
                round_numbers.append(price)
            price += interval
        
        return round_numbers
    
    def _find_volume_clusters(
        self,
        df: pd.DataFrame,
        atr: float,
    ) -> List[Tuple[float, float]]:
        """Find price levels with high volume (likely support/resistance)."""
        if "volume" not in df.columns or df["volume"].sum() == 0:
            return []
        
        # Create price buckets
        bucket_size = atr * 0.5
        price_min = df["low"].min()
        price_max = df["high"].max()
        
        # Aggregate volume by price bucket
        buckets: Dict[float, float] = {}
        
        for _, row in df.iterrows():
            # Distribute volume across the bar's range
            bar_mid = (row["high"] + row["low"]) / 2
            bucket = round(bar_mid / bucket_size) * bucket_size
            volume = float(row["volume"])
            
            if bucket in buckets:
                buckets[bucket] += volume
            else:
                buckets[bucket] = volume
        
        if not buckets:
            return []
        
        # Find high-volume clusters (top 20%)
        volumes = list(buckets.values())
        threshold = np.percentile(volumes, 80) if len(volumes) >= 5 else max(volumes)
        
        clusters = []
        for price, volume in buckets.items():
            if volume >= threshold:
                # Normalize strength to 0-1
                strength = min(1.0, volume / max(volumes))
                clusters.append((price, strength))
        
        return clusters
    
    def get_stop_placement_advice(
        self,
        direction: str,
        entry_price: float,
        raw_stop: float,
        atr: float,
        df: pd.DataFrame,
    ) -> StopPlacementAdvice:
        """
        Get advice on stop placement to avoid obvious liquidity pools.
        
        Args:
            direction: "long" or "short"
            entry_price: Entry price
            raw_stop: Original stop loss price from ATR calculation
            atr: Current ATR
            df: DataFrame with OHLCV data
            
        Returns:
            StopPlacementAdvice with recommended stop and reasoning
        """
        zones = self.find_support_resistance_zones(df, entry_price, atr)
        
        # Identify danger zones (where stops likely cluster)
        danger_zones: List[Tuple[float, float]] = []
        recommended_stop = raw_stop
        adjustment_reason = "No adjustment needed"
        confidence = 0.8
        
        for zone in zones:
            zone_low = zone.price - zone.width_points
            zone_high = zone.price + zone.width_points
            
            if direction == "long":
                # For longs, stops are below entry - check support zones
                if zone.zone_type == "support" and zone_low < entry_price:
                    danger_zones.append((zone_low, zone_high))
                    
                    # If raw stop is INSIDE a support zone, move it OUTSIDE
                    if zone_low <= raw_stop <= zone_high:
                        # Move stop below the zone (with buffer)
                        buffer = atr * 0.3
                        recommended_stop = zone_low - buffer
                        adjustment_reason = (
                            f"Moved stop below support zone at ${zone.price:.2f} "
                            f"(strength: {zone.strength:.0%})"
                        )
                        confidence *= (1 - zone.strength * 0.3)
            
            else:  # short
                # For shorts, stops are above entry - check resistance zones
                if zone.zone_type == "resistance" and zone_high > entry_price:
                    danger_zones.append((zone_low, zone_high))
                    
                    # If raw stop is INSIDE a resistance zone, move it OUTSIDE
                    if zone_low <= raw_stop <= zone_high:
                        # Move stop above the zone (with buffer)
                        buffer = atr * 0.3
                        recommended_stop = zone_high + buffer
                        adjustment_reason = (
                            f"Moved stop above resistance zone at ${zone.price:.2f} "
                            f"(strength: {zone.strength:.0%})"
                        )
                        confidence *= (1 - zone.strength * 0.3)
        
        # Check round numbers
        round_numbers = self._find_round_numbers(entry_price, atr * 5)
        for rn in round_numbers:
            half_width = atr * 0.15  # Tight zone around round numbers
            
            if direction == "long" and rn < entry_price:
                if abs(raw_stop - rn) < half_width:
                    # Stop is too close to round number - adjust
                    recommended_stop = rn - atr * 0.3
                    adjustment_reason = (
                        f"Moved stop below round number ${rn:.2f} "
                        "(liquidity magnet)"
                    )
                    confidence *= 0.9
                    danger_zones.append((rn - half_width, rn + half_width))
            
            elif direction == "short" and rn > entry_price:
                if abs(raw_stop - rn) < half_width:
                    # Stop is too close to round number - adjust
                    recommended_stop = rn + atr * 0.3
                    adjustment_reason = (
                        f"Moved stop above round number ${rn:.2f} "
                        "(liquidity magnet)"
                    )
                    confidence *= 0.9
                    danger_zones.append((rn - half_width, rn + half_width))
        
        return StopPlacementAdvice(
            recommended_stop=recommended_stop,
            original_stop=raw_stop,
            adjustment_reason=adjustment_reason,
            danger_zones=danger_zones,
            safe_zone_confidence=max(0.3, min(1.0, confidence)),
        )
    
    def find_structure_stop(
        self,
        direction: str,
        entry_price: float,
        df: pd.DataFrame,
        atr: float,
        max_stop_distance: float = 30.0,  # Maximum stop distance in points
    ) -> Optional[float]:
        """
        Find a structure-based stop loss using swing points.
        
        Args:
            direction: "long" or "short"
            entry_price: Entry price
            df: DataFrame with OHLCV data
            atr: Current ATR
            max_stop_distance: Maximum stop distance from entry
            
        Returns:
            Structure-based stop price, or None if no suitable level found
        """
        if df.empty or len(df) < self.swing_lookback * 2:
            return None
        
        recent_df = df.tail(self.lookback_periods)
        buffer = atr * 0.3  # Buffer beyond swing point
        
        if direction == "long":
            # Find swing lows below entry
            swing_lows = self._find_swing_lows(recent_df)
            valid_lows = [
                (price, idx) for price, idx in swing_lows
                if price < entry_price and (entry_price - price) <= max_stop_distance
            ]
            
            if valid_lows:
                # Use the most recent swing low
                valid_lows.sort(key=lambda x: -x[1])  # Sort by recency
                stop_price = valid_lows[0][0] - buffer
                return stop_price
        
        else:  # short
            # Find swing highs above entry
            swing_highs = self._find_swing_highs(recent_df)
            valid_highs = [
                (price, idx) for price, idx in swing_highs
                if price > entry_price and (price - entry_price) <= max_stop_distance
            ]
            
            if valid_highs:
                # Use the most recent swing high
                valid_highs.sort(key=lambda x: -x[1])  # Sort by recency
                stop_price = valid_highs[0][0] + buffer
                return stop_price
        
        return None
    
    def calculate_order_book_imbalance_approximation(
        self,
        df: pd.DataFrame,
    ) -> Dict[str, float]:
        """
        Approximate order book imbalance from price action.
        
        Uses:
        - Recent bar direction distribution
        - Volume on up vs down bars
        - Wick analysis
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            Dictionary with imbalance metrics
        """
        if df.empty or len(df) < 5:
            return {
                "imbalance": 0.0,
                "buying_pressure": 0.5,
                "selling_pressure": 0.5,
                "confidence": 0.0,
            }
        
        recent = df.tail(20).copy()
        
        # Calculate buying/selling pressure
        recent["is_up"] = recent["close"] > recent["open"]
        recent["is_down"] = recent["close"] < recent["open"]
        recent["body_size"] = abs(recent["close"] - recent["open"])
        recent["upper_wick"] = recent["high"] - recent[["open", "close"]].max(axis=1)
        recent["lower_wick"] = recent[["open", "close"]].min(axis=1) - recent["low"]
        
        # Volume-weighted direction
        up_volume = recent[recent["is_up"]]["volume"].sum()
        down_volume = recent[recent["is_down"]]["volume"].sum()
        total_volume = up_volume + down_volume
        
        if total_volume > 0:
            volume_imbalance = (up_volume - down_volume) / total_volume
        else:
            volume_imbalance = 0.0
        
        # Bar count direction
        up_bars = recent["is_up"].sum()
        down_bars = recent["is_down"].sum()
        total_bars = len(recent)
        bar_imbalance = (up_bars - down_bars) / total_bars if total_bars > 0 else 0.0
        
        # Wick analysis (long lower wicks = buying, long upper wicks = selling)
        avg_lower_wick = recent["lower_wick"].mean()
        avg_upper_wick = recent["upper_wick"].mean()
        avg_body = recent["body_size"].mean()
        
        if avg_body > 0:
            wick_ratio = (avg_lower_wick - avg_upper_wick) / avg_body
            wick_imbalance = np.clip(wick_ratio, -1, 1)
        else:
            wick_imbalance = 0.0
        
        # Combine signals (weighted average)
        imbalance = (
            volume_imbalance * 0.5 +
            bar_imbalance * 0.3 +
            wick_imbalance * 0.2
        )
        
        buying_pressure = (1 + imbalance) / 2
        selling_pressure = 1 - buying_pressure
        
        # Confidence based on data quality
        confidence = min(1.0, len(recent) / 20) * 0.8
        
        return {
            "imbalance": float(np.clip(imbalance, -1, 1)),
            "buying_pressure": float(buying_pressure),
            "selling_pressure": float(selling_pressure),
            "confidence": float(confidence),
        }


# Factory function
def get_market_depth_analyzer(config: Optional[Dict] = None) -> MarketDepthAnalyzer:
    """
    Create a MarketDepthAnalyzer from configuration.
    
    Args:
        config: Optional configuration dictionary
        
    Returns:
        MarketDepthAnalyzer instance
    """
    if config is None:
        config = {}
    
    return MarketDepthAnalyzer(
        lookback_periods=config.get("lookback_periods", 50),
        swing_lookback=config.get("swing_lookback", 5),
        round_number_interval=config.get("round_number_interval", 25.0),
        zone_width_atr_mult=config.get("zone_width_atr_mult", 0.3),
    )

