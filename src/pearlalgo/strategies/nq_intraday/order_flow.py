"""
Order Flow Approximation

Approximates order flow (buying/selling pressure) from bar characteristics
when full DOM data is not available.
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from pearlalgo.utils.logger import logger


class OrderFlowApproximator:
    """
    Approximates order flow from bar characteristics.
    
    Uses:
    - Close vs Open (up bars = buying, down bars = selling)
    - High vs previous high (breakout = buying pressure)
    - Low vs previous low (breakdown = selling pressure)
    - Volume spikes on up/down bars
    - Cumulative delta approximation
    """

    def __init__(self, lookback_periods: int = 20):
        """
        Initialize order flow approximator.
        
        Args:
            lookback_periods: Number of bars to analyze for cumulative flow
        """
        self.lookback_periods = lookback_periods
        logger.info(f"OrderFlowApproximator initialized with {lookback_periods} period lookback")

    def analyze_order_flow(self, df: pd.DataFrame) -> Dict:
        """
        Analyze order flow from bar characteristics.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            Dictionary with order flow analysis:
            {
                "buying_pressure": float (0-1),  # Buying pressure strength
                "selling_pressure": float (0-1),  # Selling pressure strength
                "net_pressure": float (-1 to 1),  # Net pressure (positive = buying)
                "cumulative_delta": float,  # Approximate cumulative delta
                "recent_trend": "buying" | "selling" | "neutral",  # Recent trend
            }
        """
        if df.empty or len(df) < 2:
            return self._default_flow()

        df = df.copy()

        # Calculate bar characteristics
        df["is_up_bar"] = df["close"] > df["open"]
        df["is_down_bar"] = df["close"] < df["open"]
        df["bar_range"] = df["high"] - df["low"]
        df["body_size"] = abs(df["close"] - df["open"])
        df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
        df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]

        # Calculate price movement
        df["price_change"] = df["close"].diff()
        df["high_change"] = df["high"] - df["high"].shift(1)
        df["low_change"] = df["low"] - df["low"].shift(1)

        # Get recent bars (last N periods)
        recent = df.tail(self.lookback_periods)

        # Calculate buying pressure indicators
        up_bars = recent["is_up_bar"].sum()
        down_bars = recent["is_down_bar"].sum()
        total_bars = len(recent)

        # Volume-weighted buying/selling
        up_volume = recent[recent["is_up_bar"]]["volume"].sum()
        down_volume = recent[recent["is_down_bar"]]["volume"].sum()
        total_volume = recent["volume"].sum()

        # Price movement indicators
        positive_changes = (recent["price_change"] > 0).sum()
        negative_changes = (recent["price_change"] < 0).sum()

        # Breakout/breakdown indicators
        new_highs = (recent["high_change"] > 0).sum()
        new_lows = (recent["low_change"] < 0).sum()

        # Calculate buying pressure (0-1)
        buying_pressure = 0.0

        # Up bars ratio
        if total_bars > 0:
            buying_pressure += (up_bars / total_bars) * 0.3

        # Volume-weighted
        if total_volume > 0:
            buying_pressure += (up_volume / total_volume) * 0.3

        # Price movement
        if total_bars > 0:
            buying_pressure += (positive_changes / total_bars) * 0.2

        # New highs
        if total_bars > 0:
            buying_pressure += (new_highs / total_bars) * 0.2

        buying_pressure = min(1.0, buying_pressure)

        # Calculate selling pressure (0-1)
        selling_pressure = 0.0

        # Down bars ratio
        if total_bars > 0:
            selling_pressure += (down_bars / total_bars) * 0.3

        # Volume-weighted
        if total_volume > 0:
            selling_pressure += (down_volume / total_volume) * 0.3

        # Price movement
        if total_bars > 0:
            selling_pressure += (negative_changes / total_bars) * 0.2

        # New lows
        if total_bars > 0:
            selling_pressure += (new_lows / total_bars) * 0.2

        selling_pressure = min(1.0, selling_pressure)

        # Net pressure (-1 to 1)
        net_pressure = buying_pressure - selling_pressure

        # Cumulative delta approximation
        # Approximate: up volume - down volume (normalized)
        cumulative_delta = 0.0
        if total_volume > 0:
            cumulative_delta = (up_volume - down_volume) / total_volume

        # Recent trend
        if net_pressure > 0.2:
            recent_trend = "buying"
        elif net_pressure < -0.2:
            recent_trend = "selling"
        else:
            recent_trend = "neutral"

        return {
            "buying_pressure": float(buying_pressure),
            "selling_pressure": float(selling_pressure),
            "net_pressure": float(net_pressure),
            "cumulative_delta": float(cumulative_delta),
            "recent_trend": recent_trend,
        }

    def check_signal_alignment(
        self,
        signal_direction: str,
        order_flow: Dict,
    ) -> tuple[bool, float]:
        """
        Check if signal aligns with order flow.
        
        Args:
            signal_direction: "long" or "short"
            order_flow: Order flow analysis from analyze_order_flow()
            
        Returns:
            Tuple of (is_aligned, confidence_adjustment)
            is_aligned: True if order flow supports signal
            confidence_adjustment: Confidence adjustment (-0.15 to +0.15)
        """
        net_pressure = order_flow.get("net_pressure", 0)
        recent_trend = order_flow.get("recent_trend", "neutral")

        if signal_direction == "long":
            # Long signals need buying pressure
            if recent_trend == "buying" and net_pressure > 0.1:
                # Strong buying pressure
                return (True, +0.15)
            elif recent_trend == "buying" or net_pressure > 0:
                # Moderate buying pressure
                return (True, +0.08)
            elif recent_trend == "selling" and net_pressure < -0.1:
                # Strong selling pressure - reject
                return (False, -0.15)
            elif recent_trend == "selling":
                # Moderate selling pressure - reduce confidence
                return (True, -0.10)
            else:
                # Neutral
                return (True, 0.0)

        elif signal_direction == "short":
            # Short signals need selling pressure
            if recent_trend == "selling" and net_pressure < -0.1:
                # Strong selling pressure
                return (True, +0.15)
            elif recent_trend == "selling" or net_pressure < 0:
                # Moderate selling pressure
                return (True, +0.08)
            elif recent_trend == "buying" and net_pressure > 0.1:
                # Strong buying pressure - reject
                return (False, -0.15)
            elif recent_trend == "buying":
                # Moderate buying pressure - reduce confidence
                return (True, -0.10)
            else:
                # Neutral
                return (True, 0.0)

        # Unknown direction
        return (True, 0.0)

    def _default_flow(self) -> Dict:
        """Return default order flow when data is insufficient."""
        return {
            "buying_pressure": 0.5,
            "selling_pressure": 0.5,
            "net_pressure": 0.0,
            "cumulative_delta": 0.0,
            "recent_trend": "neutral",
        }



