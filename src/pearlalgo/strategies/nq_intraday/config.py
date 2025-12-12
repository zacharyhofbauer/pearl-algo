"""
NQ Intraday Strategy Configuration

Configuration settings for NQ intraday trading strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class NQIntradayConfig:
    """Configuration for NQ intraday strategy."""
    
    # Symbol
    symbol: str = "NQ"
    
    # Timeframe
    timeframe: str = "1m"  # 1-minute bars for intraday
    
    # Scanning interval (seconds)
    scan_interval: int = 60  # Scan every 60 seconds
    
    # Signal parameters
    lookback_periods: int = 20  # Number of bars for indicators
    min_volume: int = 100  # Minimum volume threshold
    volatility_threshold: float = 0.001  # Minimum volatility (1% of price)
    
    # Risk parameters
    max_position_size: int = 1  # Maximum contracts
    stop_loss_ticks: int = 20  # Stop loss in ticks (5 points = 100 ticks)
    take_profit_ticks: int = 40  # Take profit in ticks (10 points = 200 ticks)
    
    # Time filters
    start_time: str = "09:30"  # Market open (ET)
    end_time: str = "16:00"  # Market close (ET)
    
    # Enable/disable features
    enable_momentum: bool = True
    enable_mean_reversion: bool = True
    enable_breakout: bool = True
