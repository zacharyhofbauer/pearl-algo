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
    }
    
    strategy_class = strategies.get(name)
    if not strategy_class:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(strategies.keys())}")
    
    return strategy_class(params)
