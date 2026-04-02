"""Lightweight Pydantic schema for the canonical PEARL runtime config."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator

from pearlalgo.config.migration import migrate_legacy_runtime_config
from pearlalgo.strategies.registry import ACTIVE_STRATEGY


class AccountConfig(BaseModel):
    """Account identity (from account overlay)."""
    name: str = "default"
    display_name: str = "Agent"
    badge: str = ""
    badge_color: str = "blue"
    telegram_prefix: str = ""


class SessionConfig(BaseModel):
    """Trading session hours."""
    start_time: str = "18:00"
    end_time: str = "15:45"
    timezone: str = "America/New_York"


class RiskConfig(BaseModel):
    """Risk management parameters."""
    max_risk_per_trade: float = 0.015
    max_drawdown: float = 0.1
    min_position_size: int = 5
    max_position_size: int = 50


class ExecutionConfig(BaseModel):
    """Execution adapter configuration."""
    enabled: bool = False
    armed: bool = False
    mode: str = "dry_run"
    adapter: str = "tradovate"
    max_positions: int = 1
    max_orders_per_day: int = 20
    max_daily_loss: float = 500.0
    cooldown_seconds: int = 60
    symbol_whitelist: List[str] = Field(default_factory=lambda: ["MNQ"])


class ChallengeConfig(BaseModel):
    """Prop firm challenge/evaluation config."""
    enabled: bool = False
    stage: str = ""
    start_balance: float = 50000.0
    profit_target: float = 3000.0
    max_drawdown: float = 2000.0
    auto_reset_on_pass: bool = True
    auto_reset_on_fail: bool = True


class SignalsConfig(BaseModel):
    """Signal generation thresholds."""
    min_confidence: float = 0.55
    min_risk_reward: float = 1.3
    duplicate_window_seconds: int = 120
    min_volume: int = 10
    max_stop_points: float = 45.0


class StrategyConfig(BaseModel):
    """Top-level strategy runtime configuration."""
    active: str = ACTIVE_STRATEGY
    enforce_session_window: bool = False
    enabled_signals: List[str] = Field(default_factory=lambda: [ACTIVE_STRATEGY])
    enable_dynamic_sizing: bool = True
    base_contracts: int = 3
    high_conf_contracts: int = 5
    max_conf_contracts: int = 8


class CompositeIntradayConfig(BaseModel):
    """Canonical live strategy parameters for the composite intraday bundle."""

    model_config = {"extra": "allow"}

    ema_fast: int = 9
    ema_slow: int = 21
    min_confidence: float = 0.4
    min_confidence_long: float = 0.4
    min_confidence_short: float = 0.4
    stop_loss_atr_mult: float = 1.5
    take_profit_atr_mult: float = 2.5
    volatile_sl_mult: float = 1.3
    volatile_tp_mult: float = 1.3
    ranging_sl_mult: float = 0.8
    ranging_tp_mult: float = 0.7
    allow_vwap_cross_entries: bool = True
    allow_vwap_retest_entries: bool = True
    allow_trend_momentum_entries: bool = True
    allow_trend_breakout_entries: bool = True
    allow_orb_entries: bool = True
    allow_vwap_2sd_entries: bool = True
    allow_smc_entries: bool = True


class StrategiesConfig(BaseModel):
    """Strategy bundle registry config."""

    model_config = {"extra": "allow"}

    composite_intraday: CompositeIntradayConfig = Field(default_factory=CompositeIntradayConfig)


class GuardrailsConfig(BaseModel):
    """Minimal live safety model; execution remains the primary protection surface."""

    signal_gate_enabled: bool = False
    max_consecutive_losses: int = 3
    max_session_drawdown: float = 1800.0
    max_daily_drawdown: float = 99999.0


class AgentConfigSchema(BaseModel):
    """
    Top-level agent config schema.

    Validates the merged base.yaml + account overlay before the agent starts.
    Only validates the most critical fields -- extra keys are allowed and passed through.
    """
    model_config = {"extra": "allow"}  # Allow unknown keys (forward-compatible)

    symbol: str = "MNQ"
    timeframe: str = "1m"
    scan_interval: int = 30

    account: AccountConfig = Field(default_factory=AccountConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    challenge: ChallengeConfig = Field(default_factory=ChallengeConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)

    @field_validator("symbol")
    @classmethod
    def symbol_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("symbol cannot be empty")
        return v.strip().upper()

    @field_validator("timeframe")
    @classmethod
    def timeframe_valid(cls, v: str) -> str:
        valid = {"1m", "5m", "15m", "1h", "4h", "1d"}
        if v not in valid:
            raise ValueError(f"timeframe must be one of {valid}, got '{v}'")
        return v

    @field_validator("scan_interval")
    @classmethod
    def scan_interval_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"scan_interval must be >= 1, got {v}")
        return v


def validate_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a merged config dict and return it with defaults filled in.

    Raises ``pydantic.ValidationError`` with clear messages on invalid config.

    Returns:
        The validated config as a plain dict (compatible with ConfigView).
    """
    normalized = migrate_legacy_runtime_config(raw)
    schema = AgentConfigSchema(**normalized)
    # Convert back to dict, keeping extra keys that aren't in the schema
    validated = schema.model_dump()
    # Merge back any extra top-level keys from raw that pydantic stored
    for key, value in normalized.items():
        if key not in validated:
            validated[key] = value
    return validated
