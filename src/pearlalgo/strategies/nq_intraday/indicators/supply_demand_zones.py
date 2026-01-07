"""
Supply and Demand Zones Indicator

Port of LuxAlgo-style supply/demand zone detection.

Identifies price levels where significant buying (demand) or selling (supply)
pressure occurred, creating zones that price may react to on revisits.

Features extracted:
- Distance to nearest demand zone (normalized)
- Distance to nearest supply zone (normalized)
- Zone strength (based on volume and price action)
- Number of zone touches
- Zone age (bars since formation)

Signals generated:
- sd_zone_bounce_long: Price bouncing off demand zone
- sd_zone_bounce_short: Price rejecting from supply zone
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pearlalgo.strategies.nq_intraday.indicators.base import IndicatorBase, IndicatorSignal


@dataclass
class Zone:
    """Represents a supply or demand zone."""
    type: str  # "demand" or "supply"
    upper: float
    lower: float
    strength: float  # 0-1 normalized
    volume: float
    bar_index: int  # When zone formed
    touches: int = 0
    broken: bool = False


class SupplyDemandZones(IndicatorBase):
    """
    Supply and Demand Zones indicator.
    
    Detects zones based on:
    1. Large price movements (impulse moves)
    2. Volume confirmation
    3. Candle patterns (engulfing, strong close)
    
    Configuration:
    - lookback: Bars to analyze for zone detection (default: 50)
    - min_zone_size_atr: Minimum zone size as ATR multiple (default: 0.5)
    - max_zones: Maximum zones to track per type (default: 5)
    - zone_threshold_pct: Proximity threshold for zone touches (default: 0.3%)
    """
    
    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self.lookback = int(self.config.get("lookback", 50))
        self.min_zone_size_atr = float(self.config.get("min_zone_size_atr", 0.5))
        self.max_zones = int(self.config.get("max_zones", 5))
        self.zone_threshold_pct = float(self.config.get("zone_threshold_pct", 0.3))
        
        # Track zones
        self._demand_zones: List[Zone] = []
        self._supply_zones: List[Zone] = []
    
    @property
    def name(self) -> str:
        return "supply_demand_zones"
    
    @property
    def description(self) -> str:
        return "LuxAlgo-style supply and demand zone detection for support/resistance"
    
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate supply and demand zones."""
        if not self.validate_dataframe(df):
            return df
        
        df = self.normalize_columns(df)
        
        # Ensure minimum data
        if len(df) < self.lookback:
            df["sd_nearest_demand"] = np.nan
            df["sd_nearest_supply"] = np.nan
            df["sd_zone_strength"] = 0.0
            df["sd_in_demand_zone"] = False
            df["sd_in_supply_zone"] = False
            return df
        
        # Calculate ATR for zone sizing
        atr = self._calculate_atr(df)
        
        # Detect zones
        self._detect_zones(df, atr)
        
        # Add zone columns
        df = self._add_zone_columns(df)
        
        return df
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range."""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        return tr.rolling(window=period).mean()
    
    def _detect_zones(self, df: pd.DataFrame, atr: pd.Series) -> None:
        """Detect supply and demand zones from price action."""
        self._demand_zones = []
        self._supply_zones = []
        
        close = df["close"].values
        open_ = df["open"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values
        atr_values = atr.fillna(0).values
        
        # Look for impulse moves that create zones
        for i in range(3, len(df) - 1):
            current_atr = atr_values[i] if atr_values[i] > 0 else 1.0
            
            # Bullish impulse (creates demand zone below)
            # Strong up move from consolidation
            body = close[i] - open_[i]
            body_pct = abs(body) / close[i] if close[i] > 0 else 0
            
            is_bullish_impulse = (
                body > 0 and  # Up candle
                body_pct > 0.002 and  # Significant body
                close[i] > high[i-1] and  # Broke previous high
                volume[i] > np.mean(volume[max(0, i-10):i]) * 1.2  # Above avg volume
            )
            
            if is_bullish_impulse:
                # Demand zone at the base of the impulse
                zone_low = min(low[i-1], low[i-2], open_[i])
                zone_high = zone_low + current_atr * self.min_zone_size_atr
                
                zone = Zone(
                    type="demand",
                    upper=zone_high,
                    lower=zone_low,
                    strength=min(1.0, body_pct * 100),  # Normalize
                    volume=volume[i],
                    bar_index=i,
                )
                self._demand_zones.append(zone)
            
            # Bearish impulse (creates supply zone above)
            is_bearish_impulse = (
                body < 0 and  # Down candle
                abs(body_pct) > 0.002 and  # Significant body
                close[i] < low[i-1] and  # Broke previous low
                volume[i] > np.mean(volume[max(0, i-10):i]) * 1.2
            )
            
            if is_bearish_impulse:
                # Supply zone at the top of the impulse
                zone_high = max(high[i-1], high[i-2], open_[i])
                zone_low = zone_high - current_atr * self.min_zone_size_atr
                
                zone = Zone(
                    type="supply",
                    upper=zone_high,
                    lower=zone_low,
                    strength=min(1.0, abs(body_pct) * 100),
                    volume=volume[i],
                    bar_index=i,
                )
                self._supply_zones.append(zone)
        
        # Keep only strongest, most recent zones
        self._demand_zones = sorted(
            self._demand_zones,
            key=lambda z: (z.strength, -z.bar_index),
            reverse=True
        )[:self.max_zones]
        
        self._supply_zones = sorted(
            self._supply_zones,
            key=lambda z: (z.strength, -z.bar_index),
            reverse=True
        )[:self.max_zones]
    
    def _add_zone_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add zone-related columns to DataFrame."""
        df = df.copy()
        
        close = df["close"].values
        n = len(df)
        
        # Initialize columns
        nearest_demand = np.full(n, np.nan)
        nearest_supply = np.full(n, np.nan)
        zone_strength = np.zeros(n)
        in_demand = np.zeros(n, dtype=bool)
        in_supply = np.zeros(n, dtype=bool)
        
        for i in range(n):
            price = close[i]
            
            # Find nearest demand zone (below price)
            valid_demands = [z for z in self._demand_zones if z.upper < price]
            if valid_demands:
                nearest_d = max(valid_demands, key=lambda z: z.upper)
                nearest_demand[i] = nearest_d.upper
                
                # Check if in zone
                if nearest_d.lower <= price <= nearest_d.upper * 1.002:
                    in_demand[i] = True
                    zone_strength[i] = nearest_d.strength
            
            # Find nearest supply zone (above price)
            valid_supplies = [z for z in self._supply_zones if z.lower > price]
            if valid_supplies:
                nearest_s = min(valid_supplies, key=lambda z: z.lower)
                nearest_supply[i] = nearest_s.lower
                
                # Check if in zone
                if nearest_s.lower * 0.998 <= price <= nearest_s.upper:
                    in_supply[i] = True
                    zone_strength[i] = nearest_s.strength
        
        df["sd_nearest_demand"] = nearest_demand
        df["sd_nearest_supply"] = nearest_supply
        df["sd_zone_strength"] = zone_strength
        df["sd_in_demand_zone"] = in_demand
        df["sd_in_supply_zone"] = in_supply
        
        return df
    
    def as_features(self, latest: pd.Series, df: Optional[pd.DataFrame] = None) -> Dict[str, float]:
        """Extract features for the learning system."""
        features = {}
        
        try:
            close = float(latest.get("close", 0))
            if close <= 0:
                return self._default_features()
            
            # Distance to nearest demand zone (normalized by price)
            nearest_demand = latest.get("sd_nearest_demand")
            if pd.notna(nearest_demand) and nearest_demand > 0:
                features["sd_demand_distance_pct"] = (close - nearest_demand) / close
            else:
                features["sd_demand_distance_pct"] = 0.1  # Far away
            
            # Distance to nearest supply zone
            nearest_supply = latest.get("sd_nearest_supply")
            if pd.notna(nearest_supply) and nearest_supply > 0:
                features["sd_supply_distance_pct"] = (nearest_supply - close) / close
            else:
                features["sd_supply_distance_pct"] = 0.1
            
            # Zone strength (already 0-1)
            features["sd_zone_strength"] = float(latest.get("sd_zone_strength", 0))
            
            # Boolean features as 0/1
            features["sd_in_demand_zone"] = 1.0 if latest.get("sd_in_demand_zone", False) else 0.0
            features["sd_in_supply_zone"] = 1.0 if latest.get("sd_in_supply_zone", False) else 0.0
            
            # Number of active zones (normalized)
            features["sd_demand_zone_count"] = min(len(self._demand_zones) / self.max_zones, 1.0)
            features["sd_supply_zone_count"] = min(len(self._supply_zones) / self.max_zones, 1.0)
            
        except Exception:
            return self._default_features()
        
        return features
    
    def _default_features(self) -> Dict[str, float]:
        """Return default feature values."""
        return {
            "sd_demand_distance_pct": 0.1,
            "sd_supply_distance_pct": 0.1,
            "sd_zone_strength": 0.0,
            "sd_in_demand_zone": 0.0,
            "sd_in_supply_zone": 0.0,
            "sd_demand_zone_count": 0.0,
            "sd_supply_zone_count": 0.0,
        }
    
    def generate_signal(
        self,
        latest: pd.Series,
        df: pd.DataFrame,
        atr: Optional[float] = None,
    ) -> Optional[IndicatorSignal]:
        """Generate signal when price interacts with zones."""
        try:
            close = float(latest.get("close", 0))
            open_ = float(latest.get("open", 0))
            high = float(latest.get("high", 0))
            low = float(latest.get("low", 0))
            
            if close <= 0:
                return None
            
            # Use provided ATR or calculate
            if atr is None or atr <= 0:
                atr = close * 0.005  # Default 0.5% of price
            
            # Check for demand zone bounce (long)
            if latest.get("sd_in_demand_zone", False):
                # Bullish candle bouncing off demand
                is_bounce = (
                    close > open_ and  # Up candle
                    low < latest.get("sd_nearest_demand", 0) * 1.002 and  # Touched zone
                    close > latest.get("sd_nearest_demand", 0)  # Closed above
                )
                
                if is_bounce:
                    zone_strength = float(latest.get("sd_zone_strength", 0.5))
                    confidence = 0.45 + zone_strength * 0.3  # Base + strength bonus
                    
                    return IndicatorSignal(
                        type="sd_zone_bounce_long",
                        direction="long",
                        confidence=min(confidence, 0.85),
                        entry_price=close,
                        stop_loss=low - atr * 0.5,
                        take_profit=close + atr * 2.0,
                        reason=f"Price bouncing off demand zone (strength: {zone_strength:.0%})",
                        metadata={
                            "zone_type": "demand",
                            "zone_strength": zone_strength,
                            "zone_level": float(latest.get("sd_nearest_demand", 0)),
                        },
                    )
            
            # Check for supply zone rejection (short)
            if latest.get("sd_in_supply_zone", False):
                # Bearish candle rejecting from supply
                is_rejection = (
                    close < open_ and  # Down candle
                    high > latest.get("sd_nearest_supply", float("inf")) * 0.998 and  # Touched zone
                    close < latest.get("sd_nearest_supply", float("inf"))  # Closed below
                )
                
                if is_rejection:
                    zone_strength = float(latest.get("sd_zone_strength", 0.5))
                    confidence = 0.45 + zone_strength * 0.3
                    
                    return IndicatorSignal(
                        type="sd_zone_bounce_short",
                        direction="short",
                        confidence=min(confidence, 0.85),
                        entry_price=close,
                        stop_loss=high + atr * 0.5,
                        take_profit=close - atr * 2.0,
                        reason=f"Price rejecting from supply zone (strength: {zone_strength:.0%})",
                        metadata={
                            "zone_type": "supply",
                            "zone_strength": zone_strength,
                            "zone_level": float(latest.get("sd_nearest_supply", 0)),
                        },
                    )
            
        except Exception:
            pass
        
        return None
    
    def get_signal_types(self) -> List[str]:
        """Get signal types this indicator generates."""
        return ["sd_zone_bounce_long", "sd_zone_bounce_short"]
    
    def get_zones(self) -> Tuple[List[Zone], List[Zone]]:
        """Get current demand and supply zones."""
        return self._demand_zones, self._supply_zones


