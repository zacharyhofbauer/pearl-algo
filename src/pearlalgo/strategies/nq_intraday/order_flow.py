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
    Analyzes order flow from bar characteristics and real order book data.
    
    When Level 2 data is available, uses real order book depth.
    Otherwise, approximates from bar characteristics:
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

    def analyze_order_book(self, order_book: Dict) -> Dict:
        """
        Analyze real Level 2 order book data.
        
        Args:
            order_book: Dictionary with order book data from latest_bar:
                {
                    "bids": [{"price": float, "size": int}, ...],
                    "asks": [{"price": float, "size": int}, ...],
                    "bid_depth": int,
                    "ask_depth": int,
                    "imbalance": float,
                    "weighted_mid": float,
                }
            
        Returns:
            Dictionary with enhanced order flow analysis:
            {
                "buying_pressure": float (0-1),
                "selling_pressure": float (0-1),
                "net_pressure": float (-1 to 1),
                "cumulative_delta": float,
                "recent_trend": "buying" | "selling" | "neutral",
                "order_book_imbalance": float,  # From order book
                "support_levels": [float, ...],  # Key bid levels
                "resistance_levels": [float, ...],  # Key ask levels
                "large_orders_detected": bool,  # Iceberg orders
            }
        """
        if not order_book or not order_book.get("bids") and not order_book.get("asks"):
            return self._default_flow()
        
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])
        bid_depth = order_book.get("bid_depth", 0)
        ask_depth = order_book.get("ask_depth", 0)
        imbalance = order_book.get("imbalance", 0.0)
        
        # Calculate buying/selling pressure from order book imbalance
        # Positive imbalance = more bids = buying pressure
        if imbalance > 0.2:
            buying_pressure = 0.5 + (imbalance * 0.5)  # Scale to 0.5-1.0
            selling_pressure = 0.5 - (imbalance * 0.5)  # Scale to 0.0-0.5
        elif imbalance < -0.2:
            buying_pressure = 0.5 + (imbalance * 0.5)  # Scale to 0.0-0.5
            selling_pressure = 0.5 - (imbalance * 0.5)  # Scale to 0.5-1.0
        else:
            # Near balance
            buying_pressure = 0.5 + (imbalance * 0.3)
            selling_pressure = 0.5 - (imbalance * 0.3)
        
        buying_pressure = max(0.0, min(1.0, buying_pressure))
        selling_pressure = max(0.0, min(1.0, selling_pressure))
        
        # Net pressure
        net_pressure = buying_pressure - selling_pressure
        
        # Recent trend from imbalance
        if imbalance > 0.15:
            recent_trend = "buying"
        elif imbalance < -0.15:
            recent_trend = "selling"
        else:
            recent_trend = "neutral"
        
        # Identify support/resistance levels from order book
        support_levels = self._extract_key_levels(bids, min_size_ratio=0.15)
        resistance_levels = self._extract_key_levels(asks, min_size_ratio=0.15)
        
        # Detect large orders (iceberg orders - unusually large size at a level)
        large_orders_detected = self._detect_large_orders(bids, asks)
        
        return {
            "buying_pressure": float(buying_pressure),
            "selling_pressure": float(selling_pressure),
            "net_pressure": float(net_pressure),
            "cumulative_delta": float(imbalance),  # Use imbalance as delta proxy
            "recent_trend": recent_trend,
            "order_book_imbalance": float(imbalance),
            "support_levels": support_levels,
            "resistance_levels": resistance_levels,
            "large_orders_detected": large_orders_detected,
        }

    def get_order_book_levels(self, order_book: Dict, num_levels: int = 5) -> Dict:
        """
        Extract key support/resistance levels from order book.
        
        Args:
            order_book: Dictionary with order book data
            num_levels: Number of key levels to extract
            
        Returns:
            Dictionary with support and resistance levels:
            {
                "support": [float, ...],  # Key bid levels (sorted descending)
                "resistance": [float, ...],  # Key ask levels (sorted ascending)
            }
        """
        if not order_book:
            return {"support": [], "resistance": []}
        
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])
        
        # Extract support levels (bids) - sorted by price descending
        support_levels = self._extract_key_levels(bids, num_levels=num_levels)
        support_levels.sort(reverse=True)  # Highest to lowest
        
        # Extract resistance levels (asks) - sorted by price ascending
        resistance_levels = self._extract_key_levels(asks, num_levels=num_levels)
        resistance_levels.sort()  # Lowest to highest
        
        return {
            "support": support_levels[:num_levels],
            "resistance": resistance_levels[:num_levels],
        }

    def _extract_key_levels(self, levels: List[Dict], num_levels: int = 5, min_size_ratio: float = 0.1) -> List[float]:
        """
        Extract key price levels with significant volume.
        
        Args:
            levels: List of level dictionaries with "price" and "size"
            num_levels: Maximum number of levels to return
            min_size_ratio: Minimum size relative to total volume
            
        Returns:
            List of price levels
        """
        if not levels:
            return []
        
        total_volume = sum(level.get("size", 0) for level in levels)
        if total_volume == 0:
            return [level.get("price", 0) for level in levels[:num_levels]]
        
        # Filter levels by minimum size
        significant_levels = [
            level for level in levels
            if level.get("size", 0) >= (total_volume * min_size_ratio)
        ]
        
        # Sort by size (largest first) and take top N
        significant_levels.sort(key=lambda x: x.get("size", 0), reverse=True)
        
        return [float(level.get("price", 0)) for level in significant_levels[:num_levels]]

    def _detect_large_orders(self, bids: List[Dict], asks: List[Dict], threshold_ratio: float = 0.3) -> bool:
        """
        Detect unusually large orders (potential iceberg orders).
        
        Args:
            bids: List of bid levels
            asks: List of ask levels
            threshold_ratio: Ratio threshold for large order detection
            
        Returns:
            True if large orders detected
        """
        if not bids and not asks:
            return False
        
        all_levels = bids + asks
        if not all_levels:
            return False
        
        total_volume = sum(level.get("size", 0) for level in all_levels)
        if total_volume == 0:
            return False
        
        # Check if any single level has unusually large volume
        for level in all_levels:
            size = level.get("size", 0)
            if size > 0 and (size / total_volume) > threshold_ratio:
                return True
        
        return False

    def _default_flow(self) -> Dict:
        """Return default order flow when data is insufficient."""
        return {
            "buying_pressure": 0.5,
            "selling_pressure": 0.5,
            "net_pressure": 0.0,
            "cumulative_delta": 0.0,
            "recent_trend": "neutral",
            "order_book_imbalance": 0.0,
            "support_levels": [],
            "resistance_levels": [],
            "large_orders_detected": False,
        }



