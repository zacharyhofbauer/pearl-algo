"""
NQ Intraday Strategy Configuration

Configuration settings for MNQ intraday trading strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pearlalgo.config.config_file import load_config_yaml


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
    timeframe: str = "5m"  # 5-minute bars for intraday swings (primary)

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

    # Virtual PnL tracking (signal grading without real IBKR fills)
    virtual_pnl_enabled: bool = True
    virtual_pnl_tiebreak: str = "stop_loss"  # "stop_loss" (conservative) or "take_profit"

    # HUD settings (TradingView-style chart overlays)
    hud_enabled: bool = True
    hud_show_rr_box: bool = True
    hud_rr_box_forward_bars: int = 30
    hud_right_pad_bars: int = 30
    hud_show_sessions: bool = True
    hud_show_session_names: bool = True
    hud_show_session_oc: bool = True
    hud_show_session_tick_range: bool = True
    hud_show_session_average: bool = True
    hud_show_supply_demand: bool = True
    hud_show_power_channel: bool = True
    hud_show_tbt_targets: bool = True
    hud_show_key_levels: bool = True
    hud_show_right_labels: bool = True
    hud_max_right_labels: int = 12
    hud_right_label_merge_ticks: int = 4
    hud_show_rsi: bool = True
    hud_rsi_period: int = 14

    @classmethod
    def from_config_file(cls, config_path: Optional[Path] = None) -> "NQIntradayConfig":
        """Load configuration from config.yaml file.

        Uses the unified config loader with environment variable substitution.

        Args:
            config_path: Path to config.yaml (defaults to config/config.yaml)

        Returns:
            NQIntradayConfig instance
        """
        # Start with defaults (MNQ-native)
        config = cls()

        # Load config using unified loader (handles env substitution)
        config_data = load_config_yaml(config_path)
        if not config_data:
            return config

        try:
            # Load symbol and timeframe
            if "symbol" in config_data:
                config.symbol = str(config_data["symbol"])
            if "timeframe" in config_data:
                config.timeframe = str(config_data["timeframe"])
            if "scan_interval" in config_data:
                config.scan_interval = int(config_data["scan_interval"])

            # Load strategy session window (NY time / ET).
            # Supports either:
            # - session.start_time / session.end_time (preferred)
            # - top-level start_time / end_time (backward-compatible)
            session_cfg = config_data.get("session", {}) or {}
            if "start_time" in session_cfg:
                config.start_time = str(session_cfg["start_time"])
            elif "start_time" in config_data:
                config.start_time = str(config_data["start_time"])

            if "end_time" in session_cfg:
                config.end_time = str(session_cfg["end_time"])
            elif "end_time" in config_data:
                config.end_time = str(config_data["end_time"])

            # Load risk parameters
            risk_config = config_data.get("risk", {}) or {}
            if "stop_loss_atr_multiplier" in risk_config:
                config.stop_loss_atr_multiplier = float(risk_config["stop_loss_atr_multiplier"])
            if "take_profit_risk_reward" in risk_config:
                config.take_profit_risk_reward = float(risk_config["take_profit_risk_reward"])
            if "max_risk_per_trade" in risk_config:
                config.max_risk_per_trade = float(risk_config["max_risk_per_trade"])
            if "max_position_size" in risk_config:
                config.max_position_size = int(risk_config["max_position_size"])
            if "min_position_size" in risk_config:
                config.min_position_size = int(risk_config["min_position_size"])

            # Load virtual PnL settings
            vpnl_cfg = config_data.get("virtual_pnl", {}) or {}
            if "enabled" in vpnl_cfg:
                config.virtual_pnl_enabled = bool(vpnl_cfg["enabled"])
            if "intrabar_tiebreak" in vpnl_cfg:
                config.virtual_pnl_tiebreak = str(vpnl_cfg["intrabar_tiebreak"])

            # Load HUD settings
            hud_cfg = config_data.get("hud", {}) or {}
            if "enabled" in hud_cfg:
                config.hud_enabled = bool(hud_cfg["enabled"])
            if "show_rr_box" in hud_cfg:
                config.hud_show_rr_box = bool(hud_cfg["show_rr_box"])
            if "rr_box_forward_bars" in hud_cfg:
                config.hud_rr_box_forward_bars = int(hud_cfg["rr_box_forward_bars"])
            if "right_pad_bars" in hud_cfg:
                config.hud_right_pad_bars = int(hud_cfg["right_pad_bars"])
            if "show_sessions" in hud_cfg:
                config.hud_show_sessions = bool(hud_cfg["show_sessions"])
            if "show_session_names" in hud_cfg:
                config.hud_show_session_names = bool(hud_cfg["show_session_names"])
            if "show_session_oc" in hud_cfg:
                config.hud_show_session_oc = bool(hud_cfg["show_session_oc"])
            if "show_session_tick_range" in hud_cfg:
                config.hud_show_session_tick_range = bool(hud_cfg["show_session_tick_range"])
            if "show_session_average" in hud_cfg:
                config.hud_show_session_average = bool(hud_cfg["show_session_average"])
            if "show_supply_demand" in hud_cfg:
                config.hud_show_supply_demand = bool(hud_cfg["show_supply_demand"])
            if "show_power_channel" in hud_cfg:
                config.hud_show_power_channel = bool(hud_cfg["show_power_channel"])
            if "show_tbt_targets" in hud_cfg:
                config.hud_show_tbt_targets = bool(hud_cfg["show_tbt_targets"])
            if "show_key_levels" in hud_cfg:
                config.hud_show_key_levels = bool(hud_cfg["show_key_levels"])
            if "show_right_labels" in hud_cfg:
                config.hud_show_right_labels = bool(hud_cfg["show_right_labels"])
            if "max_right_labels" in hud_cfg:
                config.hud_max_right_labels = int(hud_cfg["max_right_labels"])
            if "right_label_merge_ticks" in hud_cfg:
                config.hud_right_label_merge_ticks = int(hud_cfg["right_label_merge_ticks"])
            if "show_rsi" in hud_cfg:
                config.hud_show_rsi = bool(hud_cfg["show_rsi"])
            if "rsi_period" in hud_cfg:
                config.hud_rsi_period = int(hud_cfg["rsi_period"])

        except Exception as e:  # pragma: no cover - defensive logging
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Could not parse config data: {e}")

        return config
