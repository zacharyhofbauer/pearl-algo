"""
NQ Intraday Strategy Configuration

Configuration settings for NQ intraday trading strategy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class NQIntradayConfig:
    """Configuration for NQ intraday strategy."""

    # Symbol
    symbol: str = "NQ"  # E-mini NASDAQ-100 futures (using NQ with scaled contract sizes to match MNQ exposure)

    # Timeframe
    timeframe: str = "1m"  # 1-minute bars for intraday scalping/swings

    # Scanning interval (seconds)
    scan_interval: int = 30  # Scan every 30 seconds (faster for scalping)

    # Signal parameters
    lookback_periods: int = 20  # Number of bars for indicators
    min_volume: int = 100  # Minimum volume threshold
    volatility_threshold: float = 0.001  # Minimum volatility (1% of price)

    # Risk parameters (Prop Firm Style)
    max_position_size: int = 10  # Maximum contracts (5-15 range for prop firms)
    min_position_size: int = 5  # Minimum contracts per trade
    stop_loss_ticks: int = 15  # Tighter stops for scalping (15 ticks = 3.75 points)
    take_profit_ticks: int = 22  # Quick profit targets (22 ticks = 5.5 points, 1.5:1 R/R)
    stop_loss_atr_multiplier: float = 1.5  # Tighter stops for scalping (was 2.0)
    take_profit_risk_reward: float = 1.5  # 1.5:1 R/R for quick scalps (was 2.0)
    max_risk_per_trade: float = 0.01  # 1% max risk per trade (prop firm conservative)
    # NQ contract specs: $20 per point (MNQ is $2 per point, 1/10th size)
    # Using NQ but scaling contract sizes by 0.1 to match MNQ exposure
    tick_value: float = 20.0  # NQ tick value in dollars

    # Time filters (Prop Firm Trading Hours)
    start_time: str = "09:30"  # Market open (ET)
    end_time: str = "16:00"  # Market close (ET)
    # Avoid lunch lull for scalping (11:30-13:00 ET)
    avoid_lunch_lull: bool = True  # Skip signals during low volume period

    # Enable/disable features
    enable_momentum: bool = True
    enable_mean_reversion: bool = True
    enable_breakout: bool = True

    @classmethod
    def from_config_file(cls, config_path: Optional[Path] = None) -> "NQIntradayConfig":
        """
        Load configuration from config.yaml file.
        
        Args:
            config_path: Path to config.yaml (defaults to config/config.yaml)
            
        Returns:
            NQIntradayConfig instance
        """
        if config_path is None:
            # Try to find config.yaml relative to project root
            project_root = Path(__file__).parent.parent.parent.parent.parent
            config_path = project_root / "config" / "config.yaml"

        # Start with defaults
        config = cls()

        # Load from file if exists
        if config_path and config_path.exists():
            try:
                import yaml
                with open(config_path) as f:
                    config_data = yaml.safe_load(f) or {}

                    # Load symbol and timeframe
                    if "symbol" in config_data:
                        config.symbol = config_data["symbol"]
                    if "timeframe" in config_data:
                        config.timeframe = config_data["timeframe"]
                    if "scan_interval" in config_data:
                        config.scan_interval = config_data["scan_interval"]

                    # Load risk parameters
                    risk_config = config_data.get("risk", {})
                    if "stop_loss_atr_multiplier" in risk_config:
                        config.stop_loss_atr_multiplier = risk_config["stop_loss_atr_multiplier"]
                    if "take_profit_risk_reward" in risk_config:
                        config.take_profit_risk_reward = risk_config["take_profit_risk_reward"]
                    if "max_risk_per_trade" in risk_config:
                        config.max_risk_per_trade = risk_config["max_risk_per_trade"]
                    if "max_position_size" in risk_config:
                        config.max_position_size = risk_config["max_position_size"]
                    if "min_position_size" in risk_config:
                        config.min_position_size = risk_config["min_position_size"]

                    # Support environment variable substitution
                    def substitute_env(value):
                        if isinstance(value, str) and value.startswith("${"):
                            env_var = value[2:-1].split(":")[0]
                            default = value.split(":")[1][:-1] if ":" in value else None
                            return os.getenv(env_var, default)
                        return value

                    # Substitute any env vars in config values
                    config.symbol = substitute_env(config.symbol) or config.symbol
                    config.timeframe = substitute_env(config.timeframe) or config.timeframe

            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Could not load config from {config_path}: {e}")

        return config
