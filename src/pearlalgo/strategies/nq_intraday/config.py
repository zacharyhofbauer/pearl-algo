"""
NQ Intraday Strategy Configuration

Configuration settings for MNQ intraday trading strategy.
Supports strategy variants for A/B testing different configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from pearlalgo.config.config_file import load_config_yaml


# Default signal types based on backtest analysis
# Winners: sr_bounce, mean_reversion, momentum_short
# Losers: momentum_long (0/5 wins), engulfing (0/3 wins)
DEFAULT_ENABLED_SIGNALS = [
    "sr_bounce",
    "mean_reversion_long",
    "mean_reversion_short",
    "momentum_short",
    "breakout_long",
    "breakout_short",
    "vwap_reversion",
]

DEFAULT_DISABLED_SIGNALS = [
    "momentum_long",      # 0/5 wins in backtest - broken
    "engulfing_short",    # 0/3 wins in backtest - broken
    "engulfing_long",     # Untested, disable for safety
]


@dataclass
class NQIntradayConfig:
    """Configuration for MNQ intraday strategy.

    This config is MNQ-native: all sizing, tick values, and risk assumptions
    are expressed directly in terms of MNQ contracts ($2/point), matching the
    production docs and `config/config.yaml`.
    
    Supports strategy variants via enabled_signals/disabled_signals for A/B testing.
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
    volatility_threshold: float = 0.0005  # Reduced from 0.001 - less restrictive

    # Risk parameters (Prop Firm Style, MNQ-native)
    max_position_size: int = 25  # Increased for $200+ scalp targets
    min_position_size: int = 5   # Minimum MNQ contracts per trade
    stop_loss_ticks: int = 15    # 15 ticks ≈ 3.75 points
    take_profit_ticks: int = 22  # 22 ticks ≈ 5.5 points (≈1.5:1 R:R)
    stop_loss_atr_multiplier: float = 1.5  # Tighter stops for scalping
    take_profit_risk_reward: float = 1.2   # Reduced from 1.5 - less restrictive
    max_risk_per_trade: float = 0.01       # 1% max risk per trade

    # MNQ contract specs
    tick_value: float = 2.0  # MNQ tick value in dollars ($2 per point)

    # Time filters (Prop Firm Trading Hours)
    start_time: str = "09:30"  # Market open (ET)
    end_time: str = "16:00"    # Market close (ET)
    # Avoid lunch lull for scalping (11:30-13:00 ET) - now optional
    avoid_lunch_lull: bool = False  # Disabled by default - was blocking 72 signals

    # Enable/disable features (legacy - use enabled_signals instead)
    enable_momentum: bool = True
    enable_mean_reversion: bool = True
    enable_breakout: bool = True

    # Strategy variant configuration (A/B testing)
    # Signal types to enable (if empty, uses legacy enable_* flags)
    enabled_signals: List[str] = field(default_factory=lambda: DEFAULT_ENABLED_SIGNALS.copy())
    # Signal types to explicitly disable (takes precedence over enabled_signals)
    disabled_signals: List[str] = field(default_factory=lambda: DEFAULT_DISABLED_SIGNALS.copy())
    
    # Dynamic position sizing (for $200+ scalp targets)
    enable_dynamic_sizing: bool = True
    base_contracts: int = 5          # Base position size
    high_conf_contracts: int = 15    # For confidence > 0.8
    max_conf_contracts: int = 25     # For confidence > 0.9 + winning signal type
    high_conf_threshold: float = 0.80
    max_conf_threshold: float = 0.90
    
    # Scalp target presets (points)
    scalp_target_points: float = 20.0   # Default target for $200 with 5 contracts
    scalp_stop_points: float = 12.0     # Default stop
    use_scalp_presets: bool = False     # Override ATR-based stops/targets
    
    # Winning signal types (get priority in dynamic sizing)
    winning_signal_types: List[str] = field(default_factory=lambda: [
        "sr_bounce",
        "mean_reversion_long",
        "momentum_short",
    ])

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

    # ==========================================================================
    # EXPERIMENTAL: Bayesian Quality Gate (non-default)
    # Uses Beta-Binomial posterior for uncertainty-aware signal filtering.
    # Enable with: bayesian_gate_enabled: true in config.yaml
    # ==========================================================================
    bayesian_gate_enabled: bool = False
    bayesian_gate_min_credible_wr: float = 0.52  # Minimum credible lower bound
    bayesian_gate_credible_level: float = 0.95   # 95% credible interval
    bayesian_gate_min_samples: int = 10          # Min samples before strict gating
    bayesian_gate_time_decay: float = 0.0        # Time decay rate (0 = none)
    bayesian_gate_max_history_days: int = 90     # Max age of historical data

    # ==========================================================================
    # EXPERIMENTAL: ML Signal Filter (non-default)
    # Uses offline-trained model for signal quality filtering.
    # Requires: pip install pearlalgo[ml]
    # Enable with: ml_filter_enabled: true in config.yaml
    # ==========================================================================
    ml_filter_enabled: bool = False
    ml_filter_model_path: Optional[str] = None   # Path to trained model (.joblib)
    ml_filter_model_version: str = "v0.0.0"      # Model version for tracking
    ml_filter_min_probability: float = 0.55      # Min P(win) to pass filter
    ml_filter_calibration_mode: bool = False     # Use for confidence calibration
    ml_filter_calibration_scaling: float = 0.5   # Scaling factor for calibration

    @classmethod
    def from_config_file(cls, config_path: Optional[Path] = None, variant: Optional[str] = None) -> "NQIntradayConfig":
        """Load configuration from config.yaml file.

        Uses the unified config loader with environment variable substitution.
        Supports strategy variants for A/B testing.

        Args:
            config_path: Path to config.yaml (defaults to config/config.yaml)
            variant: Optional variant name to load (e.g., "aggressive_scalp", "conservative")

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

            # Load signal generation settings
            signals_cfg = config_data.get("signals", {}) or {}
            if "min_risk_reward" in signals_cfg:
                config.take_profit_risk_reward = float(signals_cfg["min_risk_reward"])
            if "min_confidence" in signals_cfg:
                # Store for use in signal filtering
                pass  # Handled by signal_generator
            if "volatility_threshold" in signals_cfg:
                config.volatility_threshold = float(signals_cfg["volatility_threshold"])
            if "avoid_lunch_lull" in signals_cfg:
                config.avoid_lunch_lull = bool(signals_cfg["avoid_lunch_lull"])
            if "min_volume" in signals_cfg:
                config.min_volume = int(signals_cfg["min_volume"])

            # Load virtual PnL settings
            vpnl_cfg = config_data.get("virtual_pnl", {}) or {}
            if "enabled" in vpnl_cfg:
                config.virtual_pnl_enabled = bool(vpnl_cfg["enabled"])
            if "intrabar_tiebreak" in vpnl_cfg:
                config.virtual_pnl_tiebreak = str(vpnl_cfg["intrabar_tiebreak"])

            # Load strategy variant settings
            strategy_cfg = config_data.get("strategy", {}) or {}
            if "enabled_signals" in strategy_cfg:
                config.enabled_signals = list(strategy_cfg["enabled_signals"])
            if "disabled_signals" in strategy_cfg:
                config.disabled_signals = list(strategy_cfg["disabled_signals"])
            if "enable_dynamic_sizing" in strategy_cfg:
                config.enable_dynamic_sizing = bool(strategy_cfg["enable_dynamic_sizing"])
            if "base_contracts" in strategy_cfg:
                config.base_contracts = int(strategy_cfg["base_contracts"])
            if "high_conf_contracts" in strategy_cfg:
                config.high_conf_contracts = int(strategy_cfg["high_conf_contracts"])
            if "max_conf_contracts" in strategy_cfg:
                config.max_conf_contracts = int(strategy_cfg["max_conf_contracts"])
            if "high_conf_threshold" in strategy_cfg:
                config.high_conf_threshold = float(strategy_cfg["high_conf_threshold"])
            if "max_conf_threshold" in strategy_cfg:
                config.max_conf_threshold = float(strategy_cfg["max_conf_threshold"])
            if "winning_signal_types" in strategy_cfg:
                config.winning_signal_types = list(strategy_cfg["winning_signal_types"])
            
            # Scalp presets
            if "scalp_target_points" in strategy_cfg:
                config.scalp_target_points = float(strategy_cfg["scalp_target_points"])
            if "scalp_stop_points" in strategy_cfg:
                config.scalp_stop_points = float(strategy_cfg["scalp_stop_points"])
            if "use_scalp_presets" in strategy_cfg:
                config.use_scalp_presets = bool(strategy_cfg["use_scalp_presets"])

            # Load specific variant if requested
            if variant:
                variants_cfg = config_data.get("strategy_variants", {}) or {}
                if variant in variants_cfg:
                    config._apply_variant(variants_cfg[variant])

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

            # Load experimental Bayesian gate settings
            bayesian_cfg = config_data.get("bayesian_gate", {}) or {}
            if "enabled" in bayesian_cfg:
                config.bayesian_gate_enabled = bool(bayesian_cfg["enabled"])
            if "min_credible_wr" in bayesian_cfg:
                config.bayesian_gate_min_credible_wr = float(bayesian_cfg["min_credible_wr"])
            if "credible_level" in bayesian_cfg:
                config.bayesian_gate_credible_level = float(bayesian_cfg["credible_level"])
            if "min_samples" in bayesian_cfg:
                config.bayesian_gate_min_samples = int(bayesian_cfg["min_samples"])
            if "time_decay" in bayesian_cfg:
                config.bayesian_gate_time_decay = float(bayesian_cfg["time_decay"])
            if "max_history_days" in bayesian_cfg:
                config.bayesian_gate_max_history_days = int(bayesian_cfg["max_history_days"])

            # Load experimental ML filter settings
            ml_cfg = config_data.get("ml_filter", {}) or {}
            if "enabled" in ml_cfg:
                config.ml_filter_enabled = bool(ml_cfg["enabled"])
            if "model_path" in ml_cfg:
                config.ml_filter_model_path = str(ml_cfg["model_path"])
            if "model_version" in ml_cfg:
                config.ml_filter_model_version = str(ml_cfg["model_version"])
            if "min_probability" in ml_cfg:
                config.ml_filter_min_probability = float(ml_cfg["min_probability"])
            if "calibration_mode" in ml_cfg:
                config.ml_filter_calibration_mode = bool(ml_cfg["calibration_mode"])
            if "calibration_scaling" in ml_cfg:
                config.ml_filter_calibration_scaling = float(ml_cfg["calibration_scaling"])

        except Exception as e:  # pragma: no cover - defensive logging
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Could not parse config data: {e}")

        return config

    def _apply_variant(self, variant_cfg: dict) -> None:
        """Apply a strategy variant configuration overlay."""
        if "enabled_signals" in variant_cfg:
            self.enabled_signals = list(variant_cfg["enabled_signals"])
        if "disabled_signals" in variant_cfg:
            self.disabled_signals = list(variant_cfg["disabled_signals"])
        if "min_risk_reward" in variant_cfg:
            self.take_profit_risk_reward = float(variant_cfg["min_risk_reward"])
        if "min_confidence" in variant_cfg:
            # This would need to be passed to signal generator
            pass
        if "volatility_threshold" in variant_cfg:
            self.volatility_threshold = float(variant_cfg["volatility_threshold"])
        if "target_points" in variant_cfg:
            self.scalp_target_points = float(variant_cfg["target_points"])
            self.use_scalp_presets = True
        if "max_stop_points" in variant_cfg:
            self.scalp_stop_points = float(variant_cfg["max_stop_points"])
            self.use_scalp_presets = True
        if "position_multiplier" in variant_cfg:
            mult = float(variant_cfg["position_multiplier"])
            self.base_contracts = int(self.base_contracts * mult)
            self.high_conf_contracts = int(self.high_conf_contracts * mult)
            self.max_conf_contracts = int(self.max_conf_contracts * mult)
        if "base_contracts" in variant_cfg:
            self.base_contracts = int(variant_cfg["base_contracts"])
        if "avoid_lunch_lull" in variant_cfg:
            self.avoid_lunch_lull = bool(variant_cfg["avoid_lunch_lull"])

    def is_signal_enabled(self, signal_type: str) -> bool:
        """Check if a signal type is enabled based on configuration.
        
        Args:
            signal_type: Signal type name (e.g., "momentum_long", "sr_bounce")
            
        Returns:
            True if the signal type should be generated
        """
        # Disabled list takes precedence
        if signal_type in self.disabled_signals:
            return False
        
        # If enabled list is specified, signal must be in it
        if self.enabled_signals:
            # Check for exact match or prefix match (e.g., "sr_bounce" matches "sr_bounce_long")
            for enabled in self.enabled_signals:
                if signal_type == enabled or signal_type.startswith(enabled):
                    return True
            return False
        
        # Fall back to legacy enable_* flags
        if "momentum" in signal_type:
            return self.enable_momentum
        if "mean_reversion" in signal_type:
            return self.enable_mean_reversion
        if "breakout" in signal_type:
            return self.enable_breakout
        
        # Default: enabled
        return True

    def get_position_size(self, confidence: float, signal_type: str) -> int:
        """Calculate position size based on confidence and signal type.
        
        For $200+ scalp targets with dynamic sizing:
        - Base: 5 contracts
        - High confidence (>0.8): 10-15 contracts
        - Max confidence (>0.9) + winning type: 20-25 contracts
        
        Args:
            confidence: Signal confidence (0.0 to 1.0)
            signal_type: Signal type name
            
        Returns:
            Position size in contracts
        """
        if not self.enable_dynamic_sizing:
            return self.base_contracts
        
        # Check if winning signal type
        is_winning_type = any(
            signal_type == wt or signal_type.startswith(wt)
            for wt in self.winning_signal_types
        )
        
        # Max confidence + winning type = max contracts
        if confidence >= self.max_conf_threshold and is_winning_type:
            return self.max_conf_contracts
        
        # High confidence = high contracts
        if confidence >= self.high_conf_threshold:
            return self.high_conf_contracts
        
        # Default: base contracts
        return self.base_contracts

    @classmethod
    def get_variant_presets(cls) -> dict:
        """Get predefined strategy variant configurations.
        
        Returns:
            Dict of variant name -> variant config dict
        """
        return {
            "default": {
                "description": "Balanced default - disabled broken signals",
                "enabled_signals": DEFAULT_ENABLED_SIGNALS,
                "disabled_signals": DEFAULT_DISABLED_SIGNALS,
                "min_risk_reward": 1.2,
                "volatility_threshold": 0.0005,
            },
            "aggressive_scalp": {
                "description": "Aggressive scalping - winners only, tight targets",
                "enabled_signals": ["sr_bounce", "mean_reversion"],
                "disabled_signals": ["momentum_long", "engulfing", "breakout"],
                "min_risk_reward": 1.0,
                "target_points": 20,
                "max_stop_points": 15,
                "base_contracts": 10,
            },
            "conservative": {
                "description": "Conservative - high confidence only",
                "enabled_signals": ["sr_bounce", "mean_reversion_long", "momentum_short"],
                "disabled_signals": ["momentum_long", "engulfing", "breakout"],
                "min_risk_reward": 1.5,
                "min_confidence": 0.75,
            },
            "high_volume": {
                "description": "High volume scalping - 25 contracts on best setups",
                "enabled_signals": ["sr_bounce", "mean_reversion"],
                "disabled_signals": ["momentum_long", "engulfing"],
                "base_contracts": 15,
                "high_conf_contracts": 20,
                "max_conf_contracts": 25,
                "target_points": 10,  # Tighter target for larger size
                "max_stop_points": 8,
            },
        }
