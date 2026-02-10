"""
Pydantic schema for config.yaml validation.

This module provides type-safe validation for the service configuration file.
It catches configuration errors at startup rather than at runtime.

Usage:
    from pearlalgo.config.config_schema import validate_config, ServiceConfig

    # Validate a config dict
    config = validate_config(config_dict)

    # Access typed fields
    print(config.signals.min_confidence)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pearlalgo.config import defaults


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""
    enabled: bool = True
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


class TelegramUIConfig(BaseModel):
    """Telegram UI display settings."""
    compact_metrics_enabled: bool = defaults.TELEGRAM_UI_COMPACT_METRICS
    show_progress_bars: bool = defaults.TELEGRAM_UI_SHOW_PROGRESS_BARS
    show_volume_metrics: bool = defaults.TELEGRAM_UI_SHOW_VOLUME_METRICS
    compact_metric_width: int = Field(default=defaults.TELEGRAM_UI_COMPACT_METRIC_WIDTH, ge=5, le=20)


class SessionConfig(BaseModel):
    """Trading session time window."""
    start_time: str = "18:00"
    end_time: str = "16:10"


class RiskConfig(BaseModel):
    """Risk management configuration."""
    max_risk_per_trade: float = Field(default=defaults.MAX_RISK_PER_TRADE, ge=0.001, le=0.1)
    max_drawdown: float = Field(default=defaults.MAX_DRAWDOWN, ge=0.01, le=0.5)
    stop_loss_atr_multiplier: float = Field(default=defaults.STOP_LOSS_ATR_MULTIPLIER, ge=0.5, le=10.0)
    take_profit_risk_reward: float = Field(default=defaults.TAKE_PROFIT_RISK_REWARD, ge=0.5, le=10.0)
    min_position_size: int = Field(default=defaults.MIN_POSITION_SIZE, ge=1)
    max_position_size: int = Field(default=defaults.MAX_POSITION_SIZE, ge=1)
    signal_type_size_multipliers: Dict[str, float] = Field(default_factory=dict)
    signal_type_max_contracts: Dict[str, int] = Field(default_factory=dict)


class ServiceConfig(BaseModel):
    """Service operation configuration."""
    status_update_interval: int = Field(default=defaults.STATUS_UPDATE_INTERVAL, ge=60)
    heartbeat_interval: int = Field(default=defaults.HEARTBEAT_INTERVAL, ge=60)
    state_save_interval: int = Field(default=defaults.STATE_SAVE_INTERVAL, ge=1)
    connection_failure_alert_interval: int = Field(default=defaults.CONNECTION_FAILURE_ALERT_INTERVAL, ge=60)
    data_quality_alert_interval: int = Field(default=defaults.DATA_QUALITY_ALERT_INTERVAL, ge=60)
    dashboard_chart_enabled: bool = defaults.DASHBOARD_CHART_ENABLED
    dashboard_chart_interval: int = Field(default=defaults.DASHBOARD_CHART_INTERVAL, ge=300)
    dashboard_chart_timeframe: str = defaults.DASHBOARD_CHART_TIMEFRAME
    dashboard_chart_lookback_hours: int = Field(default=defaults.DASHBOARD_CHART_LOOKBACK_HOURS, ge=1, le=48)
    enable_new_bar_gating: bool = defaults.ENABLE_NEW_BAR_GATING
    adaptive_cadence_enabled: bool = True
    scan_interval_active_seconds: float = Field(default=5, ge=1)
    scan_interval_idle_seconds: float = Field(default=30, ge=5)
    scan_interval_market_closed_seconds: float = Field(default=300, ge=60)
    scan_interval_paused_seconds: float = Field(default=60, ge=10)
    scan_interval_velocity_seconds: float = Field(default=1.5, ge=0.5)
    velocity_mode_enabled: bool = True
    velocity_atr_expansion_threshold: float = Field(default=1.2, ge=1.0)
    velocity_volume_spike_threshold: float = Field(default=2.0, ge=1.0)


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration for error handling."""
    max_consecutive_errors: int = Field(default=defaults.MAX_CONSECUTIVE_ERRORS, ge=1)
    max_connection_failures: int = Field(default=defaults.MAX_CONNECTION_FAILURES, ge=1)
    max_data_fetch_errors: int = Field(default=defaults.MAX_DATA_FETCH_ERRORS, ge=1)


class TradingCircuitBreakerConfig(BaseModel):
    """Trading circuit breaker configuration (risk management)."""
    enabled: bool = True
    mode: Literal["warn_only", "enforce"] = "enforce"
    max_consecutive_losses: int = Field(default=5, ge=1)
    consecutive_loss_cooldown_minutes: int = Field(default=30, ge=1)
    max_session_drawdown: float = Field(default=500.0, ge=0)
    max_daily_drawdown: float = Field(default=1000.0, ge=0)
    drawdown_cooldown_minutes: int = Field(default=60, ge=1)
    rolling_window_trades: int = Field(default=20, ge=1)
    min_rolling_win_rate: float = Field(default=0.30, ge=0, le=1)
    win_rate_cooldown_minutes: int = Field(default=30, ge=1)
    max_concurrent_positions: int = Field(default=5, ge=1)
    min_price_distance_pct: float = Field(default=0.5, ge=0)
    enable_volatility_filter: bool = True
    min_atr_ratio: float = Field(default=0.8, ge=0)
    max_atr_ratio: float = Field(default=2.5, ge=0)
    chop_detection_window: int = Field(default=10, ge=1)
    chop_win_rate_threshold: float = Field(default=0.35, ge=0, le=1)
    auto_resume_after_cooldown: bool = True
    require_winning_trade_to_resume: bool = False
    enable_session_filter: bool = True
    allowed_sessions: List[str] = Field(default_factory=lambda: ["overnight", "midday", "close"])
    enable_direction_gating: bool = True
    direction_gating_min_confidence: float = Field(default=0.70, ge=0, le=1)
    enable_regime_avoidance: bool = False
    blocked_regimes: List[str] = Field(default_factory=lambda: ["ranging", "volatile"])
    regime_avoidance_min_confidence: float = Field(default=0.70, ge=0, le=1)
    enable_trigger_filters: bool = False
    ema_cross_require_volume: bool = True
    low_regime_require_volume: bool = True
    enable_ml_chop_shield: bool = False
    ml_min_scored_trades: int = Field(default=50, ge=1)
    ml_min_winrate_delta: float = Field(default=0.15, ge=0, le=1)
    ml_chop_shield_regimes: List[str] = Field(default_factory=lambda: ["ranging", "volatile"])


class DataConfig(BaseModel):
    """Data fetching and caching configuration."""
    buffer_size: int = Field(default=defaults.DATA_BUFFER_SIZE, ge=10)
    buffer_size_5m: int = Field(default=defaults.DATA_BUFFER_SIZE_5M, ge=10)
    buffer_size_15m: int = Field(default=defaults.DATA_BUFFER_SIZE_15M, ge=10)
    historical_hours: int = Field(default=defaults.HISTORICAL_HOURS, ge=1)
    multitimeframe_5m_hours: int = Field(default=defaults.MULTITIMEFRAME_5M_HOURS, ge=1)
    multitimeframe_15m_hours: int = Field(default=defaults.MULTITIMEFRAME_15M_HOURS, ge=1)
    performance_history_limit: int = Field(default=defaults.PERFORMANCE_HISTORY_LIMIT, ge=100)
    stale_data_threshold_minutes: int = Field(default=int(defaults.STALE_DATA_THRESHOLD_MINUTES), ge=1)
    connection_timeout_minutes: int = Field(default=int(defaults.CONNECTION_TIMEOUT_MINUTES), ge=5)
    enable_base_cache: bool = defaults.ENABLE_BASE_CACHE
    base_refresh_seconds: int = Field(default=defaults.BASE_REFRESH_SECONDS, ge=10)
    enable_mtf_cache: bool = defaults.ENABLE_MTF_CACHE
    mtf_refresh_seconds_5m: int = Field(default=defaults.MTF_REFRESH_SECONDS_5M, ge=60)
    mtf_refresh_seconds_15m: int = Field(default=defaults.MTF_REFRESH_SECONDS_15M, ge=60)


class StorageConfig(BaseModel):
    """Data persistence configuration."""
    sqlite_enabled: bool = defaults.STORAGE_SQLITE_ENABLED
    db_path: str = defaults.STORAGE_DB_PATH
    async_writes_enabled: bool = True
    async_queue_max_size: int = Field(default=1000, ge=100)
    async_queue_priority_trades: bool = True
    dual_write_files: bool = defaults.STORAGE_DUAL_WRITE_FILES


class ChallengeConfig(BaseModel):
    """Prop firm challenge tracking configuration."""
    enabled: bool = defaults.CHALLENGE_ENABLED
    start_balance: float = Field(default=defaults.CHALLENGE_START_BALANCE, ge=1000)
    max_drawdown: float = Field(default=defaults.CHALLENGE_MAX_DRAWDOWN, ge=100)
    profit_target: float = Field(default=defaults.CHALLENGE_PROFIT_TARGET, ge=100)
    auto_reset_on_pass: bool = defaults.CHALLENGE_AUTO_RESET_ON_PASS
    auto_reset_on_fail: bool = defaults.CHALLENGE_AUTO_RESET_ON_FAIL


class QualityScoreFactors(BaseModel):
    """Signal quality score factor weights."""
    confidence_weight: float = Field(default=0.3, ge=0, le=1)
    risk_reward_weight: float = Field(default=0.25, ge=0, le=1)
    regime_alignment_weight: float = Field(default=0.2, ge=0, le=1)
    volume_profile_weight: float = Field(default=0.15, ge=0, le=1)
    mtf_alignment_weight: float = Field(default=0.1, ge=0, le=1)


class QualityScoreConfig(BaseModel):
    """Signal quality scoring configuration."""
    enabled: bool = True
    threshold: float = Field(default=0.35, ge=0, le=1)
    factors: QualityScoreFactors = Field(default_factory=QualityScoreFactors)


class RegimeFilterConfig(BaseModel):
    """Regime filter for a specific signal type."""
    allowed_regimes: List[str] = Field(default_factory=list)


class ExploreConfig(BaseModel):
    """Explore mode configuration for testing new signals."""
    enabled: bool = False
    min_confidence: float = Field(default=0.75, ge=0, le=1)
    min_risk_reward: float = Field(default=2.0, ge=0.5)
    include_quality_rejects: bool = False
    bypass_regime_filters: bool = False


class AdaptiveVolatilityFilterConfig(BaseModel):
    """Adaptive volatility filter configuration."""
    enabled: bool = False
    expansion_requirement: float = Field(default=2.0, ge=1.0)
    median_atr_threshold: float = Field(default=0.0003, ge=0)


class SignalsConfig(BaseModel):
    """Signal generation configuration."""
    duplicate_window_seconds: int = Field(default=defaults.DUPLICATE_WINDOW_SECONDS, ge=10)
    min_confidence: float = Field(default=defaults.MIN_CONFIDENCE, ge=0, le=1)
    min_risk_reward: float = Field(default=defaults.MIN_RISK_REWARD, ge=0.5)
    duplicate_price_threshold_pct: float = Field(default=0.5, ge=0)
    volatility_threshold: float = Field(default=0.0001, ge=0)
    avoid_lunch_lull: bool = False
    skip_overnight: bool = True
    quality_score: QualityScoreConfig = Field(default_factory=QualityScoreConfig)
    prioritize_ny_session: bool = False
    min_volume: int = Field(default=10, ge=0)
    explore: ExploreConfig = Field(default_factory=ExploreConfig)
    max_stop_points: float = Field(default=45.0, ge=1)
    adaptive_volatility_filter: AdaptiveVolatilityFilterConfig = Field(
        default_factory=AdaptiveVolatilityFilterConfig
    )
    regime_filters: Dict[str, RegimeFilterConfig] = Field(default_factory=dict)


class StrategyConfig(BaseModel):
    """Trading strategy configuration."""
    enabled_signals: List[str] = Field(default_factory=list)
    enable_dynamic_sizing: bool = True
    base_contracts: int = Field(default=3, ge=1)
    high_conf_contracts: int = Field(default=5, ge=1)
    max_conf_contracts: int = Field(default=8, ge=1)
    high_conf_threshold: float = Field(default=0.8, ge=0, le=1)
    max_conf_threshold: float = Field(default=0.9, ge=0, le=1)
    winning_signal_types: List[str] = Field(default_factory=list)
    signal_type_size_multipliers: Dict[str, float] = Field(default_factory=dict)
    use_scalp_presets: bool = False
    scalp_target_points: float = Field(default=20.0, ge=1)
    scalp_stop_points: float = Field(default=12.0, ge=1)
    session_position_scaling: Dict[str, Any] = Field(default_factory=dict)


class PerformanceConfig(BaseModel):
    """Performance tracking configuration."""
    max_records: int = Field(default=defaults.PERFORMANCE_MAX_RECORDS, ge=100)
    default_lookback_days: int = Field(default=defaults.PERFORMANCE_DEFAULT_LOOKBACK_DAYS, ge=1)


class VirtualPnLConfig(BaseModel):
    """Virtual P&L tracking configuration."""
    enabled: bool = True
    intrabar_tiebreak: Literal["take_profit", "stop_loss"] = "take_profit"
    notify_entry: bool = True
    notify_exit: bool = True


class AutoFlatConfig(BaseModel):
    """Auto-flat configuration for virtual trades."""
    enabled: bool = True
    friday_enabled: bool = True
    friday_time: str = "16:55"
    weekend_enabled: bool = True
    timezone: str = "America/New_York"
    notify: bool = True


class HUDConfig(BaseModel):
    """Heads-up display configuration for charts."""
    enabled: bool = True
    show_rr_box: bool = True
    rr_box_forward_bars: int = Field(default=30, ge=1)
    right_pad_bars: int = Field(default=30, ge=0)
    show_sessions: bool = True
    show_session_names: bool = True
    show_session_oc: bool = True
    show_session_tick_range: bool = True
    show_session_average: bool = True
    show_supply_demand: bool = True
    show_power_channel: bool = True
    show_tbt_targets: bool = True
    show_key_levels: bool = True
    show_right_labels: bool = True
    max_right_labels: int = Field(default=12, ge=1)
    right_label_merge_ticks: int = Field(default=4, ge=1)
    show_rsi: bool = True
    rsi_period: int = Field(default=14, ge=2)


class SessionDefinition(BaseModel):
    """Trading session definition."""
    name: str
    session: str
    timezone: str = "UTC"
    color: str = "#2962FF"


class IndicatorConfig(BaseModel):
    """Indicator configuration."""
    lookback: int = Field(default=50, ge=1)
    min_zone_size_atr: float = Field(default=0.5, ge=0)
    max_zones: int = Field(default=5, ge=1)
    zone_threshold_pct: float = Field(default=0.3, ge=0)
    length: int = Field(default=130, ge=1)
    atr_mult: float = Field(default=2.0, ge=0.1)
    pivot_lookback: int = Field(default=5, ge=1)
    rsi_period: int = Field(default=14, ge=2)


class IndicatorsConfig(BaseModel):
    """Indicators configuration."""
    enabled: List[str] = Field(default_factory=list)
    as_signals: bool = False
    as_features: bool = True
    supply_demand_zones: Dict[str, Any] = Field(default_factory=dict)
    power_channel: Dict[str, Any] = Field(default_factory=dict)
    smart_money_divergence: Dict[str, Any] = Field(default_factory=dict)


class ExecutionConfig(BaseModel):
    """Order execution configuration."""
    enabled: bool = False
    armed: bool = False
    mode: Literal["dry_run", "paper", "live"] = "dry_run"
    adapter: Literal["ibkr", "tradovate"] = "ibkr"
    max_positions: int = Field(default=1, ge=1)
    max_orders_per_day: int = Field(default=20, ge=1)
    max_daily_loss: float = Field(default=500.0, ge=0)
    cooldown_seconds: int = Field(default=60, ge=0)
    symbol_whitelist: List[str] = Field(default_factory=list)
    ibkr_trading_client_id: int = Field(default=20, ge=1)
    ibkr_host: Optional[str] = None
    ibkr_port: Optional[Union[int, str]] = None  # Can be int or env var placeholder

    @field_validator("ibkr_port", mode="before")
    @classmethod
    def parse_ibkr_port(cls, v):
        """Handle env var placeholders for port."""
        if v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            # If it's an env var placeholder, return as-is (will be resolved later)
            if v.startswith("${"):
                return v
            try:
                return int(v)
            except ValueError:
                return v
        return v


class LearningFeaturesConfig(BaseModel):
    """Feature engineering configuration for learning."""
    short_window: int = Field(default=5, ge=1)
    medium_window: int = Field(default=20, ge=1)
    long_window: int = Field(default=50, ge=1)
    compute_price_action: bool = True
    compute_volume_profile: bool = True
    compute_microstructure: bool = True
    compute_time_features: bool = True
    compute_sequential: bool = True
    compute_cross_timeframe: bool = True
    normalize_features: bool = True
    clip_outliers: bool = True
    outlier_std: float = Field(default=3.0, ge=1.0)


class ContextualLearningConfig(BaseModel):
    """Contextual bandit learning configuration."""
    enabled: bool = True
    mode: Literal["shadow", "live"] = "shadow"
    explore_rate: float = Field(default=0.1, ge=0, le=1)
    min_samples_per_context: int = Field(default=5, ge=1)
    decision_threshold: float = Field(default=0.3, ge=0, le=1)
    fallback_to_global: bool = True


class LearningConfig(BaseModel):
    """Adaptive learning configuration."""
    enabled: bool = True
    mode: Literal["shadow", "live"] = "shadow"
    feature_engineer_enabled: bool = True
    features: LearningFeaturesConfig = Field(default_factory=LearningFeaturesConfig)
    min_samples_per_type: int = Field(default=10, ge=1)
    explore_rate: float = Field(default=0.1, ge=0, le=1)
    decision_threshold: float = Field(default=0.3, ge=0, le=1)
    max_size_multiplier: float = Field(default=1.5, ge=1.0)
    min_size_multiplier: float = Field(default=0.5, ge=0, le=1)
    prior_alpha: float = Field(default=2.0, ge=0.1)
    prior_beta: float = Field(default=2.0, ge=0.1)
    decay_factor: float = Field(default=0.0, ge=0, le=1)
    contextual: ContextualLearningConfig = Field(default_factory=ContextualLearningConfig)


class SwingTradingConfig(BaseModel):
    """Swing trading configuration."""
    enabled: bool = True
    min_confidence: float = Field(default=0.75, ge=0, le=1)
    min_target_points: float = Field(default=50, ge=1)
    min_mtf_alignment: float = Field(default=0.8, ge=0, le=1)
    min_volume_ratio: float = Field(default=1.2, ge=0)
    max_hold_hours: int = Field(default=24, ge=1)
    position_size_multiplier: float = Field(default=2.5, ge=0.1)


class MLFilterConfig(BaseModel):
    """ML signal filter configuration."""
    enabled: bool = True
    mode: Literal["shadow", "live"] = "live"
    require_lift_to_block: bool = True
    lift_lookback_trades: int = Field(default=200, ge=10)
    lift_min_trades: int = Field(default=50, ge=10)
    lift_min_winrate_delta: float = Field(default=0.05, ge=0)
    model_path: str = "models/signal_filter_v1.joblib"
    model_version: str = "v1.0.0"
    min_probability: float = Field(default=0.55, ge=0, le=1)
    high_probability: float = Field(default=0.7, ge=0, le=1)
    adjust_sizing: bool = False
    size_multiplier_min: float = Field(default=1.0, ge=0.1)
    size_multiplier_max: float = Field(default=1.5, ge=1.0)
    min_training_samples: int = Field(default=30, ge=10)
    retrain_interval_days: int = Field(default=7, ge=1)
    n_estimators: int = Field(default=100, ge=10)
    max_depth: int = Field(default=6, ge=1)
    learning_rate: float = Field(default=0.1, ge=0.01, le=1)
    calibrate_probabilities: bool = True
    shadow_threshold: Optional[float] = Field(default=None, ge=0, le=1, description="Shadow-mode pass/fail split for lift measurement")


class KnowledgeConfig(BaseModel):
    """Repo knowledge index configuration for PEARL RAG."""
    enabled: bool = True
    index_dir: str = "data/knowledge_index"
    include_paths: List[str] = Field(default_factory=lambda: ["src", "docs", "config", "scripts", "pyproject.toml"])
    exclude_globs: List[str] = Field(
        default_factory=lambda: [
            ".env*",
            "data/**",
            "logs/**",
            "tests/artifacts/**",
            ".venv/**",
            "ibkr/**",
            ".git/**",
        ]
    )
    max_file_size_kb: int = Field(default=512, ge=1)
    chunk_max_chars: int = Field(default=2000, ge=200)
    chunk_overlap_chars: int = Field(default=200, ge=0)
    embedding_provider: Literal["auto", "openai", "hash"] = "auto"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = Field(default=384, ge=32)
    use_faiss: bool = False
    top_k: int = Field(default=6, ge=1)


class FullServiceConfig(BaseModel):
    """
    Complete service configuration schema.

    This model validates the entire config.yaml file.
    """
    symbol: str = "MNQ"
    timeframe: str = "1m"
    scan_interval: int = Field(default=30, ge=1)
    session: SessionConfig = Field(default_factory=SessionConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    telegram_ui: TelegramUIConfig = Field(default_factory=TelegramUIConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    trading_circuit_breaker: TradingCircuitBreakerConfig = Field(default_factory=TradingCircuitBreakerConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    challenge: ChallengeConfig = Field(default_factory=ChallengeConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    virtual_pnl: VirtualPnLConfig = Field(default_factory=VirtualPnLConfig)
    auto_flat: AutoFlatConfig = Field(default_factory=AutoFlatConfig)
    hud: HUDConfig = Field(default_factory=HUDConfig)
    sessions: List[SessionDefinition] = Field(default_factory=list)
    indicators: IndicatorsConfig = Field(default_factory=IndicatorsConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    swing_trading: SwingTradingConfig = Field(default_factory=SwingTradingConfig)
    ml_filter: MLFilterConfig = Field(default_factory=MLFilterConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)

    @model_validator(mode="after")
    def validate_cross_field_constraints(self) -> "FullServiceConfig":
        """Validate constraints that span multiple fields."""
        # Ensure high_conf_threshold < max_conf_threshold
        if self.strategy.high_conf_threshold >= self.strategy.max_conf_threshold:
            raise ValueError(
                f"strategy.high_conf_threshold ({self.strategy.high_conf_threshold}) "
                f"must be less than strategy.max_conf_threshold ({self.strategy.max_conf_threshold})"
            )

        # Ensure risk settings are coherent
        if self.risk.min_position_size > self.risk.max_position_size:
            raise ValueError(
                f"risk.min_position_size ({self.risk.min_position_size}) "
                f"cannot exceed risk.max_position_size ({self.risk.max_position_size})"
            )

        return self

    model_config = ConfigDict(extra="allow")  # Allow extra fields for forward compatibility


def validate_config(config_dict: Dict[str, Any]) -> FullServiceConfig:
    """
    Validate a configuration dictionary against the schema.

    Args:
        config_dict: Raw configuration dictionary (e.g., from YAML)

    Returns:
        Validated FullServiceConfig instance

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return FullServiceConfig.model_validate(config_dict)


def validate_config_file(config_path: Union[str, Path]) -> FullServiceConfig:
    """
    Validate a config.yaml file.

    Args:
        config_path: Path to the config.yaml file

    Returns:
        Validated FullServiceConfig instance

    Raises:
        pydantic.ValidationError: If validation fails
        FileNotFoundError: If file doesn't exist
    """
    import yaml

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        config_dict = yaml.safe_load(f) or {}

    return validate_config(config_dict)
