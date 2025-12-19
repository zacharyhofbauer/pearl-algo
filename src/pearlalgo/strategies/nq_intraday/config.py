"""
NQ Intraday Strategy Configuration

Configuration settings for MNQ intraday trading strategy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class NQIntradayConfig:
    """Configuration for MNQ intraday strategy.

    This config is MNQ-native: all sizing, tick values, and risk assumptions
    are expressed directly in terms of MNQ contracts ($2/point), matching the
    production docs and `config/config.yaml`.
    """

    # Symbol
    symbol: str = "MNQ"  # Mini NQ (1/10th size of NQ, prop-firm friendly)

    # Timeframe
    timeframe: str = "1m"  # 1-minute bars for intraday scalping/swings

    # Scanning interval (seconds)
    scan_interval: int = 30  # Scan every 30 seconds (faster for scalping)

    # Signal parameters
    lookback_periods: int = 20  # Number of bars for indicators
    min_volume: int = 100  # Minimum volume threshold
    volatility_threshold: float = 0.001  # Minimum volatility (0.1% of price)

    # Risk parameters (Prop Firm Style, MNQ-native)
    max_position_size: int = 15  # Maximum MNQ contracts per trade
    min_position_size: int = 5   # Minimum MNQ contracts per trade
    stop_loss_ticks: int = 15    # 15 ticks ≈ 3.75 points
    take_profit_ticks: int = 22  # 22 ticks ≈ 5.5 points (≈1.5:1 R:R)
    stop_loss_atr_multiplier: float = 1.5  # Tighter stops for scalping
    take_profit_risk_reward: float = 1.5   # 1.5:1 R/R for quick scalps
    max_risk_per_trade: float = 0.01       # 1% max risk per trade

    # MNQ contract specs
    tick_value: float = 2.0  # MNQ tick value in dollars ($2 per point)

    # Time filters (Prop Firm Trading Hours)
    start_time: str = "09:30"  # Market open (ET)
    end_time: str = "16:00"    # Market close (ET)
    # Avoid lunch lull for scalping (11:30-13:00 ET)
    avoid_lunch_lull: bool = True

    # Enable/disable features
    enable_momentum: bool = True
    enable_mean_reversion: bool = True
    enable_breakout: bool = True

    @classmethod
    def from_config_file(cls, config_path: Optional[Path] = None) -> "NQIntradayConfig":
        """Load configuration from config.yaml file.

        Args:
            config_path: Path to config.yaml (defaults to config/config.yaml)

        Returns:
            NQIntradayConfig instance
        """
        if config_path is None:
            # Try to find config.yaml relative to project root
            project_root = Path(__file__).parent.parent.parent.parent.parent
            config_path = project_root / "config" / "config.yaml"

        # Start with defaults (MNQ-native)
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

                    # Support environment variable substitution for basic fields
                    def substitute_env(value):
                        if isinstance(value, str) and value.startswith("${"):
                            env_var = value[2:-1].split(":")[0]
                            default = value.split(":")[1][:-1] if ":" in value else None
                            return os.getenv(env_var, default)
                        return value

                    config.symbol = substitute_env(config.symbol) or config.symbol
                    config.timeframe = substitute_env(config.timeframe) or config.timeframe

            except Exception as e:  # pragma: no cover - defensive logging
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(f"Could not load config from {config_path}: {e}")

        return config
