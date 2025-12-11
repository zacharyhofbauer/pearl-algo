"""
Options Trading Strategies

Implements options-specific strategies for swing trading:
- Volatility compression + breakout
- Earnings plays
- Support/resistance levels
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class OptionsStrategy:
    """
    Base class for options trading strategies.
    """
    
    def __init__(self, name: str, params: Optional[Dict] = None):
        """
        Initialize strategy.
        
        Args:
            name: Strategy name
            params: Strategy parameters
        """
        self.name = name
        self.params = params or {}
    
    def analyze(self, options_chain: List[Dict], underlying_price: float) -> Dict:
        """
        Analyze options chain and generate signal.
        
        Args:
            options_chain: List of option contracts
            underlying_price: Current underlying price
            
        Returns:
            Signal dict with side, confidence, strike, expiration, etc.
        """
        raise NotImplementedError("Subclasses must implement analyze()")


class SwingMomentumStrategy(OptionsStrategy):
    """
    Swing momentum strategy: Volatility compression + breakout detection.
    """
    
    def __init__(self, params: Optional[Dict] = None):
        super().__init__("swing_momentum", params)
        self.volatility_threshold = self.params.get("volatility_threshold", 0.20)  # 20% IV
        self.min_volume = self.params.get("min_volume", 100)
        self.min_open_interest = self.params.get("min_open_interest", 500)
    
    def analyze(self, options_chain: List[Dict], underlying_price: float) -> Dict:
        """
        Analyze for volatility compression and breakout setups.
        
        Returns signal if:
        - IV is compressed (low relative to historical)
        - Volume/OI indicates interest
        - Price near key levels
        """
        if not options_chain:
            return {"side": "flat", "confidence": 0.0}
        
        # Filter options by volume and OI
        filtered_options = [
            opt for opt in options_chain
            if opt.get("volume", 0) >= self.min_volume
            and opt.get("open_interest", 0) >= self.min_open_interest
        ]
        
        if not filtered_options:
            return {"side": "flat", "confidence": 0.0}
        
        # Calculate average IV (simplified - would need IV data)
        # For now, use bid-ask spread as proxy for volatility
        avg_spread = sum(
            (opt.get("ask", 0) - opt.get("bid", 0)) / max(opt.get("last_price", 0.01), 0.01)
            for opt in filtered_options
        ) / len(filtered_options)
        
        # Low spread indicates compression
        if avg_spread < self.volatility_threshold:
            # Look for call options near current price (breakout play)
            at_the_money_calls = [
                opt for opt in filtered_options
                if opt.get("option_type") == "call"
                and abs(opt.get("strike", 0) - underlying_price) / underlying_price < 0.05
            ]
            
            if at_the_money_calls:
                best_option = max(at_the_money_calls, key=lambda x: x.get("volume", 0))
                return {
                    "side": "long",
                    "confidence": 0.7,
                    "option_symbol": best_option.get("symbol"),
                    "strike": best_option.get("strike"),
                    "expiration": best_option.get("expiration"),
                    "option_type": "call",
                    "reasoning": f"Volatility compression detected (spread: {avg_spread:.2%})",
                }
        
        return {"side": "flat", "confidence": 0.0}


class EarningsPlayStrategy(OptionsStrategy):
    """
    Earnings play strategy: Pre-earnings volatility expansion.
    """
    
    def __init__(self, params: Optional[Dict] = None):
        super().__init__("earnings_play", params)
        self.days_before_earnings = self.params.get("days_before_earnings", 7)
        self.min_iv_rank = self.params.get("min_iv_rank", 70)  # 70th percentile
    
    def analyze(self, options_chain: List[Dict], underlying_price: float) -> Dict:
        """
        Analyze for earnings play setups.
        
        Returns signal if:
        - Earnings within N days
        - IV rank is high
        - Volume increasing
        """
        # Simplified - would need earnings calendar and IV rank data
        return {"side": "flat", "confidence": 0.0}


class SupportResistanceStrategy(OptionsStrategy):
    """
    Support/resistance strategy: Options at key price levels.
    """
    
    def __init__(self, params: Optional[Dict] = None):
        super().__init__("support_resistance", params)
        self.level_tolerance = self.params.get("level_tolerance", 0.02)  # 2%
    
    def analyze(self, options_chain: List[Dict], underlying_price: float) -> Dict:
        """
        Analyze for support/resistance setups.
        
        Returns signal if:
        - Price near key support/resistance
        - Options show interest at those levels
        """
        # Simplified - would need support/resistance calculation
        return {"side": "flat", "confidence": 0.0}


class CompressionBreakoutStrategy(OptionsStrategy):
    """
    Compression breakout strategy: Detects multi-day volatility compression
    followed by breakouts with volume confirmation.
    """
    
    def __init__(self, params: Optional[Dict] = None):
        super().__init__("compression_breakout", params)
        self.compression_days = self.params.get("compression_days", 5)
        self.breakout_threshold = self.params.get("breakout_threshold", 0.02)  # 2%
        self.volume_multiplier = self.params.get("volume_multiplier", 1.5)  # 50% above average
        self.min_volume = self.params.get("min_volume", 50)
        self.min_open_interest = self.params.get("min_open_interest", 200)
    
    def analyze(
        self, 
        options_chain: List[Dict], 
        underlying_price: float,
        historical_data: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Analyze for compression and breakout patterns.
        
        Args:
            options_chain: List of option contracts
            underlying_price: Current underlying price
            historical_data: Historical price data for pattern detection (optional)
        
        Returns signal if:
        - Multi-day compression detected (low ATR/volatility)
        - Price breaks above/below compression range with volume
        """
        if not options_chain:
            return {"side": "flat", "confidence": 0.0}
        
        # Filter options by volume and OI
        filtered_options = [
            opt for opt in options_chain
            if opt.get("volume", 0) >= self.min_volume
            and opt.get("open_interest", 0) >= self.min_open_interest
        ]
        
        if not filtered_options:
            return {"side": "flat", "confidence": 0.0}
        
        # Check for compression pattern if historical data available
        compression_detected = False
        breakout_direction = None
        
        if historical_data and len(historical_data) >= self.compression_days:
            # Calculate ATR or price range over compression period
            recent_prices = [bar.get("close", 0) for bar in historical_data[-self.compression_days:]]
            recent_highs = [bar.get("high", 0) for bar in historical_data[-self.compression_days:]]
            recent_lows = [bar.get("low", 0) for bar in historical_data[-self.compression_days:]]
            recent_volumes = [bar.get("volume", 0) for bar in historical_data[-self.compression_days:]]
            
            if recent_prices and all(p > 0 for p in recent_prices):
                # Calculate compression (narrowing range)
                price_range = max(recent_highs) - min(recent_lows)
                range_pct = price_range / recent_prices[0] if recent_prices[0] > 0 else 0
                
                # Compression: range is small relative to price
                compression_threshold = self.params.get("compression_threshold", 0.03)  # 3%
                if range_pct < compression_threshold:
                    compression_detected = True
                    
                    # Check for breakout
                    compression_high = max(recent_highs)
                    compression_low = min(recent_lows)
                    avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
                    current_volume = recent_volumes[-1] if recent_volumes else 0
                    
                    # Upward breakout
                    if underlying_price > compression_high * (1 + self.breakout_threshold):
                        if current_volume > avg_volume * self.volume_multiplier:
                            breakout_direction = "up"
                    
                    # Downward breakout
                    elif underlying_price < compression_low * (1 - self.breakout_threshold):
                        if current_volume > avg_volume * self.volume_multiplier:
                            breakout_direction = "down"
        
        if compression_detected and breakout_direction:
            # Select appropriate option based on breakout direction
            if breakout_direction == "up":
                # Look for ATM/OTM calls
                calls = [
                    opt for opt in filtered_options
                    if opt.get("option_type") == "call"
                    and opt.get("strike", 0) >= underlying_price * 0.98  # Near or above current price
                ]
                if calls:
                    best_option = max(calls, key=lambda x: x.get("volume", 0))
                    return {
                        "side": "long",
                        "confidence": 0.75,
                        "option_symbol": best_option.get("symbol"),
                        "strike": best_option.get("strike"),
                        "expiration": best_option.get("expiration"),
                        "option_type": "call",
                        "reasoning": f"Compression breakout: {breakout_direction} with volume confirmation",
                    }
            else:  # down
                # Look for ATM/OTM puts
                puts = [
                    opt for opt in filtered_options
                    if opt.get("option_type") == "put"
                    and opt.get("strike", 0) <= underlying_price * 1.02  # Near or below current price
                ]
                if puts:
                    best_option = max(puts, key=lambda x: x.get("volume", 0))
                    return {
                        "side": "long",  # Long put
                        "confidence": 0.75,
                        "option_symbol": best_option.get("symbol"),
                        "strike": best_option.get("strike"),
                        "expiration": best_option.get("expiration"),
                        "option_type": "put",
                        "reasoning": f"Compression breakout: {breakout_direction} with volume confirmation",
                    }
        
        return {"side": "flat", "confidence": 0.0}


class TrendContinuationStrategy(OptionsStrategy):
    """
    Trend continuation strategy: Detects strong trends with higher highs/lower lows
    and options flow confirming the trend.
    """
    
    def __init__(self, params: Optional[Dict] = None):
        super().__init__("trend_continuation", params)
        self.lookback_days = self.params.get("lookback_days", 10)
        self.min_trend_strength = self.params.get("min_trend_strength", 0.05)  # 5% move
        self.min_volume = self.params.get("min_volume", 50)
        self.min_open_interest = self.params.get("min_open_interest", 200)
    
    def analyze(
        self,
        options_chain: List[Dict],
        underlying_price: float,
        historical_data: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Analyze for trend continuation patterns.
        
        Args:
            options_chain: List of option contracts
            underlying_price: Current underlying price
            historical_data: Historical price data for trend detection (optional)
        
        Returns signal if:
        - Strong uptrend (higher highs, higher lows) or downtrend
        - Options flow confirms trend direction
        """
        if not options_chain:
            return {"side": "flat", "confidence": 0.0}
        
        # Filter options by volume and OI
        filtered_options = [
            opt for opt in options_chain
            if opt.get("volume", 0) >= self.min_volume
            and opt.get("open_interest", 0) >= self.min_open_interest
        ]
        
        if not filtered_options:
            return {"side": "flat", "confidence": 0.0}
        
        trend_direction = None
        trend_strength = 0.0
        
        if historical_data and len(historical_data) >= self.lookback_days:
            # Calculate trend
            recent_prices = [bar.get("close", 0) for bar in historical_data[-self.lookback_days:]]
            recent_highs = [bar.get("high", 0) for bar in historical_data[-self.lookback_days:]]
            recent_lows = [bar.get("low", 0) for bar in historical_data[-self.lookback_days:]]
            
            if recent_prices and all(p > 0 for p in recent_prices):
                start_price = recent_prices[0]
                end_price = recent_prices[-1]
                price_change = (end_price - start_price) / start_price if start_price > 0 else 0
                
                # Check for higher highs and higher lows (uptrend)
                if (max(recent_highs[-5:]) > max(recent_highs[:-5]) and
                    min(recent_lows[-5:]) > min(recent_lows[:-5]) and
                    price_change > self.min_trend_strength):
                    trend_direction = "up"
                    trend_strength = abs(price_change)
                
                # Check for lower highs and lower lows (downtrend)
                elif (max(recent_highs[-5:]) < max(recent_highs[:-5]) and
                      min(recent_lows[-5:]) < min(recent_lows[:-5]) and
                      price_change < -self.min_trend_strength):
                    trend_direction = "down"
                    trend_strength = abs(price_change)
        
        if trend_direction and trend_strength > self.min_trend_strength:
            # Check options flow to confirm trend
            if trend_direction == "up":
                # Look for call options with high volume/OI
                calls = [
                    opt for opt in filtered_options
                    if opt.get("option_type") == "call"
                ]
                if calls:
                    # Prefer options with high activity
                    best_option = max(
                        calls,
                        key=lambda x: x.get("volume", 0) * x.get("open_interest", 0)
                    )
                    return {
                        "side": "long",
                        "confidence": min(0.85, 0.6 + trend_strength * 5),
                        "option_symbol": best_option.get("symbol"),
                        "strike": best_option.get("strike"),
                        "expiration": best_option.get("expiration"),
                        "option_type": "call",
                        "reasoning": f"Trend continuation: {trend_direction} trend ({trend_strength:.2%})",
                    }
            else:  # down
                # Look for put options with high volume/OI
                puts = [
                    opt for opt in filtered_options
                    if opt.get("option_type") == "put"
                ]
                if puts:
                    best_option = max(
                        puts,
                        key=lambda x: x.get("volume", 0) * x.get("open_interest", 0)
                    )
                    return {
                        "side": "long",  # Long put
                        "confidence": min(0.85, 0.6 + trend_strength * 5),
                        "option_symbol": best_option.get("symbol"),
                        "strike": best_option.get("strike"),
                        "expiration": best_option.get("expiration"),
                        "option_type": "put",
                        "reasoning": f"Trend continuation: {trend_direction} trend ({trend_strength:.2%})",
                    }
        
        return {"side": "flat", "confidence": 0.0}


def create_strategy(name: str, params: Optional[Dict] = None) -> OptionsStrategy:
    """
    Factory function to create strategy instances.
    
    Args:
        name: Strategy name
        params: Strategy parameters
        
    Returns:
        OptionsStrategy instance
    """
    strategies = {
        "swing_momentum": SwingMomentumStrategy,
        "earnings_play": EarningsPlayStrategy,
        "support_resistance": SupportResistanceStrategy,
        "compression_breakout": CompressionBreakoutStrategy,
        "trend_continuation": TrendContinuationStrategy,
    }
    
    strategy_class = strategies.get(name)
    if not strategy_class:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(strategies.keys())}")
    
    return strategy_class(params)
