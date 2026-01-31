"""
Service-level configuration loader.

Loads configuration from config.yaml for service intervals, circuit breaker,
data settings, signals, performance tracking, execution (ATS), and learning.

**Purpose**: This module handles service behavior configuration (how the service operates).

**When to use `load_service_config()`:**
- For service-level settings (intervals, circuit breaker thresholds)
- For data fetching configuration (buffer sizes, thresholds)
- For signal generation settings (duplicate windows, thresholds)
- For performance tracking configuration

**When to use `settings.py` instead:**
- For infrastructure configuration (IBKR connection settings, environment variables)
- For deployment-specific settings (hosts, ports, API keys)
- For Pydantic-validated environment-based configuration

**When to use strategy config (`trading_bots/pearl_bot_auto.py` CONFIG):**
- For strategy-specific parameters (symbol, timeframe, risk parameters)
- For strategy behavior configuration (ATR multipliers, R:R ratios)

**Example usage:**
    ```python
    from pearlalgo.config.config_loader import load_service_config
    
    config = load_service_config()
    service_settings = config.get("service", {})
    status_update_interval = service_settings.get("status_update_interval", 1800)
    ```
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from pearlalgo.config.config_file import load_config_yaml, log_config_warnings
from pearlalgo.config.config_view import ConfigView
from pearlalgo.config import defaults
from pearlalgo.config.adapters import (
    build_strategy_config_from_yaml,
    apply_execution_env_overrides as _apply_execution_env_overrides,
)
from pearlalgo.utils.dict_utils import deep_merge_inplace as _deep_merge_dict
from pearlalgo.utils.logger import logger

# Schema validation (optional - only validates if explicitly requested)
try:
    from pearlalgo.config.config_schema import validate_config, FullServiceConfig
    SCHEMA_VALIDATION_AVAILABLE = True
except ImportError:
    SCHEMA_VALIDATION_AVAILABLE = False
    validate_config = None  # type: ignore
    FullServiceConfig = None  # type: ignore

# Optional per-call override (used for experiments/backtests; never persisted).
# ContextVar keeps this safe across async tasks. It does NOT affect other processes.
_SERVICE_CONFIG_OVERRIDE: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "SERVICE_CONFIG_OVERRIDE",
    default=None,
)


@contextlib.contextmanager
def service_config_override(overrides: Dict[str, Any]):
    """
    Temporarily override the service config returned by load_service_config().

    This is intended for safe experiments (e.g., "variant" backtests) without
    writing to config.yaml or changing the running trading agent.
    """
    token = _SERVICE_CONFIG_OVERRIDE.set(overrides or {})
    try:
        yield
    finally:
        try:
            _SERVICE_CONFIG_OVERRIDE.reset(token)
        except Exception:
            _SERVICE_CONFIG_OVERRIDE.set(None)


# Delegate to adapters module for strategy config building
# (kept here for backward compatibility)
def build_strategy_config(
    base_strategy: Dict[str, Any],
    config_data: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    Build a strategy config dict from base + config.yaml overrides.

    This maps config.yaml sections into the keys expected by
    `pearlalgo.trading_bots.pearl_bot_auto`.
    
    Note: Implementation delegated to pearlalgo.config.adapters module.
    """
    return build_strategy_config_from_yaml(base_strategy, config_data)


# Default values for service configuration sections
_SERVICE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "service": {
        "status_update_interval": 1800,
        "heartbeat_interval": 3600,
        "state_save_interval": 10,
        # Cadence mode: "fixed" (start-to-start timing) or "sleep_after" (legacy)
        "cadence_mode": "fixed",
        # New-bar gating (skip redundant analysis when bar hasn't advanced)
        "enable_new_bar_gating": True,
        # Dashboard observability (15m push)
        "pressure_lookback_bars": 24,   # ~2h on 5m bars
        "pressure_baseline_bars": 120,  # ~10h on 5m bars
        # Dashboard chart (hourly image)
        "dashboard_chart_enabled": True,       # set False to disable automatic chart pushes
        "dashboard_chart_interval": 3600,      # 1 hour between dashboard chart pushes
        "dashboard_chart_lookback_hours": 8,  # default notification chart window (8h for cleaner charts)
        "dashboard_chart_timeframe": "auto",   # "auto" | "5m" | "15m" | "30m" | "1h"
        "dashboard_chart_max_bars": 420,       # cap candles for readability/Telegram
        "dashboard_chart_show_pressure": True, # show signed-volume pressure panel
        # Alert throttling
        "connection_failure_alert_interval": 600,  # 10 minutes
        "data_quality_alert_interval": 300,        # 5 minutes
    },
    # Telegram UI (Home Card / dashboards): compact, mobile-friendly telemetry
    "telegram_ui": {
        "compact_metrics_enabled": True,
        "show_progress_bars": False,
        "show_volume_metrics": True,
        "compact_metric_width": 10,
    },
    "circuit_breaker": {
        "max_consecutive_errors": 10,
        "max_connection_failures": 10,
        "max_data_fetch_errors": 5,
    },
    # ==========================================================================
    # TRADING CIRCUIT BREAKER (Loss-based risk controls + session filter)
    # ==========================================================================
    # IMPORTANT: This section MUST be present here so `trading_circuit_breaker:` in
    # config.yaml / market overlays actually affects the running agent (otherwise
    # it is silently ignored and the circuit breaker runs on hardcoded defaults).
    "trading_circuit_breaker": {
        "enabled": True,
        # Consecutive loss limits
        "max_consecutive_losses": 5,
        "consecutive_loss_cooldown_minutes": 30,
        # Drawdown limits
        "max_session_drawdown": 500.0,
        "max_daily_drawdown": 1000.0,
        "drawdown_cooldown_minutes": 60,
        # Rolling win rate filter
        "rolling_window_trades": 20,
        "min_rolling_win_rate": 0.30,
        "win_rate_cooldown_minutes": 30,
        # Position limits / clustering
        "max_concurrent_positions": 5,
        "min_price_distance_pct": 0.5,
        # Volatility/chop filter
        "enable_volatility_filter": True,
        "min_atr_ratio": 0.8,
        "max_atr_ratio": 2.5,
        "chop_detection_window": 10,
        "chop_win_rate_threshold": 0.35,
        # Auto-recovery
        "auto_resume_after_cooldown": True,
        "require_winning_trade_to_resume": False,
        # Session filter (time-of-day)
        "enable_session_filter": True,
        "allowed_sessions": ["overnight", "midday", "close"],
    },
    "data": {
        "buffer_size": 100,
        "buffer_size_5m": 50,
        "buffer_size_15m": 50,
        "historical_hours": 2,
        "multitimeframe_5m_hours": 4,
        "multitimeframe_15m_hours": 12,
        "performance_history_limit": 1000,
        "stale_data_threshold_minutes": 10,
        "connection_timeout_minutes": 30,
        # Base historical fetch caching (default OFF).
        # When enabled, 1m history is refreshed on a TTL rather than every cycle.
        # Level 1 real-time data is still fetched every cycle for latest bar freshness.
        "enable_base_cache": False,
        "base_refresh_seconds": 60,  # 1 minute TTL when enabled
        # Multi-timeframe fetch caching (default OFF).
        # When enabled, 5m/15m history is refreshed on a TTL rather than every cycle.
        "enable_mtf_cache": False,
        "mtf_refresh_seconds_5m": 300,
        "mtf_refresh_seconds_15m": 900,
        # IBKR executor logging verbosity (default OFF).
        # When enabled, logs step-by-step tracing at INFO level.
        # When disabled, step-by-step tracing is at DEBUG level (actionable events stay at INFO/WARN).
        "ibkr_verbose_logging": False,
    },
    # ==========================================================================
    # STORAGE (Platform memory)
    # ==========================================================================
    # Dual-write state to SQLite for queryable history + ML datasets.
    # JSON/JSONL files remain for backward compatibility with Telegram/mobile tooling.
    "storage": {
        "sqlite_enabled": False,
        "db_path": "data/agent_state/NQ/trades.db",
        "dual_write_files": True,
    },
    "ml_filter": {
        "enabled": False,
        "model_path": None,
        "model_version": "v1.0.0",
        "min_probability": 0.55,
        "high_probability": 0.70,
        "adjust_sizing": False,
        "size_multiplier_min": 1.0,
        "size_multiplier_max": 1.5,
        "min_training_samples": 30,
        "retrain_interval_days": 7,
        "n_estimators": 100,
        "max_depth": 6,
        "learning_rate": 0.1,
        "calibrate_probabilities": True,
    },
    # ==========================================================================
    # RISK (Sizing + Risk Controls)
    # ==========================================================================
    # NOTE: This section MUST be present here so `risk:` in config.yaml
    # actually affects the running agent (otherwise it is silently ignored).
    "risk": {
        "max_risk_per_trade": 0.01,
        "max_drawdown": 0.10,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_risk_reward": 1.5,
        "min_position_size": 5,
        "max_position_size": 25,
        # Per-signal-type sizing overrides (Option A / risk shaping).
        # Example:
        #   signal_type_size_multipliers: { sr_bounce: 0.25 }
        #   signal_type_max_contracts: { sr_bounce: 2 }
        "signal_type_size_multipliers": {},
        "signal_type_max_contracts": {},
    },
    "signals": {
        "duplicate_window_seconds": 300,
        "min_confidence": 0.50,
        "min_risk_reward": 1.5,
    },
    "performance": {
        "max_records": 1000,
        "default_lookback_days": 7,
    },
    "virtual_pnl": {
        "enabled": True,
        "intrabar_tiebreak": "stop_loss",
        "notify_entry": False,
        "notify_exit": False,
    },
    "auto_flat": {
        "enabled": True,
        "friday_enabled": True,
        "friday_time": "16:55",
        "weekend_enabled": True,
        "timezone": "America/New_York",
        "notify": True,
    },
    # Market hours configuration (for holiday/early-close overrides)
    # Disabled by default to preserve current behavior.
    # Enable by setting enable_config_overrides: true and providing dates.
    "market_hours": {
        "enable_config_overrides": False,  # Set to true to load overrides from config
        # holiday_overrides: list of (year, month, day) tuples for full-day closures
        # Example: [[2025, 11, 27], [2025, 3, 28]]  # Thanksgiving, Good Friday
        "holiday_overrides": [],
        # early_closes: dict mapping (year, month, day) to close_hour (24h format)
        # Example: {"2025-11-26": 13, "2025-12-24": 13}  # Day before Thanksgiving, Christmas Eve
        "early_closes": {},
    },
    # ==========================================================================
    # EXECUTION (ATS - Automated Trading System)
    # ==========================================================================
    # Controls automated order placement via IBKR.
    # SAFETY: Default is disabled + disarmed. Must explicitly enable and /arm to trade.
    # NOTE: Canonical defaults are in pearlalgo.config.defaults module.
    "execution": {
        "enabled": defaults.EXECUTION_ENABLED,
        "armed": defaults.EXECUTION_ARMED,
        "mode": defaults.EXECUTION_MODE,
        "adapter": "ibkr",
        # Risk limits (hard caps)
        "max_positions": defaults.MAX_POSITIONS,
        "max_orders_per_day": defaults.MAX_ORDERS_PER_DAY,
        "max_daily_loss": defaults.MAX_DAILY_LOSS,
        "cooldown_seconds": defaults.COOLDOWN_SECONDS,
        # Symbol whitelist (empty = all symbols allowed)
        "symbol_whitelist": defaults.DEFAULT_SYMBOL_WHITELIST.copy(),
        # IBKR connection (separate client_id from data to avoid conflicts)
        "ibkr_trading_client_id": defaults.IBKR_TRADING_CLIENT_ID,
        "ibkr_host": defaults.IBKR_HOST,
        "ibkr_port": defaults.IBKR_PORT,
    },
    # ==========================================================================
    # LEARNING (Adaptive Bandit Policy)
    # ==========================================================================
    # Adjusts execution decisions based on observed signal type performance.
    # Uses Thompson sampling (Beta-Bernoulli) per signal type.
    # SAFETY: Default is shadow mode - learns but does NOT affect execution.
    # NOTE: Canonical defaults are in pearlalgo.config.defaults module.
    "learning": {
        "enabled": defaults.LEARNING_ENABLED,
        "mode": defaults.LEARNING_MODE,
        # Bandit configuration
        "min_samples_per_type": defaults.MIN_SAMPLES_PER_TYPE,
        "explore_rate": defaults.EXPLORE_RATE,
        "decision_threshold": defaults.DECISION_THRESHOLD,
        # Position sizing adjustment (when mode=live)
        "max_size_multiplier": defaults.MAX_SIZE_MULTIPLIER,
        "min_size_multiplier": defaults.MIN_SIZE_MULTIPLIER,
        # Prior distribution (Beta distribution parameters)
        "prior_alpha": defaults.PRIOR_ALPHA,
        "prior_beta": defaults.PRIOR_BETA,
        # Decay factor for older observations (0 = no decay)
        "decay_factor": defaults.DECAY_FACTOR,
    },
    # ==========================================================================
    # 50K CHALLENGE TRACKER (Pass/Fail Rules)
    # ==========================================================================
    # NOTE: Canonical defaults are in pearlalgo.config.defaults module.
    "challenge": {
        "enabled": defaults.CHALLENGE_ENABLED,
        "start_balance": defaults.CHALLENGE_START_BALANCE,
        "max_drawdown": defaults.CHALLENGE_MAX_DRAWDOWN,
        "profit_target": defaults.CHALLENGE_PROFIT_TARGET,
        "auto_reset_on_pass": defaults.CHALLENGE_AUTO_RESET_ON_PASS,
        "auto_reset_on_fail": defaults.CHALLENGE_AUTO_RESET_ON_FAIL,
    },
}


def load_service_config(
    config_path: Optional[Path] = None,
    *,
    validate: bool = True,
) -> Dict[str, Any]:
    """
    Load service configuration from config.yaml.

    Uses the unified config loader with environment variable substitution.

    Args:
        config_path: Path to config.yaml (defaults to config/config.yaml)
        validate: Whether to validate config and log warnings. Default True.
                  Set to False in tests or when loading config multiple times.

    Returns:
        Dictionary with service configuration sections merged with defaults
    """
    # Load raw config using unified loader
    config_data = load_config_yaml(config_path)

    # Validate config (logs warnings, does not fail)
    if validate and config_data:
        log_config_warnings(config_data)

        # Run full schema validation if available (logs errors but doesn't fail startup)
        if SCHEMA_VALIDATION_AVAILABLE:
            try:
                validate_config(config_data)
                logger.debug("Config schema validation passed")
            except Exception as e:
                logger.warning(f"Config schema validation failed: {e}")
    
    # Merge config sections with defaults
    result = {}
    for section, defaults in _SERVICE_DEFAULTS.items():
        result[section] = {**defaults, **config_data.get(section, {})}

    # Apply optional in-process overrides (best-effort).
    # This allows experiments/backtests to tweak config without editing files.
    override = _SERVICE_CONFIG_OVERRIDE.get()
    if override:
        try:
            _deep_merge_dict(result, override)
        except Exception as e:
            logger.warning(f"Could not apply service config override: {e}")

    # Safe environment overrides for controlled rollouts (do not rely on YAML substitution)
    try:
        _apply_execution_env_overrides(result.get("execution", {}))
    except Exception as e:
        logger.warning(f"Could not apply execution env overrides: {e}")
    
    # Flatten virtual_pnl fields for legacy attribute access
    vp_cfg = result.get("virtual_pnl", {}) or {}
    result["virtual_pnl_enabled"] = bool(vp_cfg.get("enabled", True))
    result["virtual_pnl_notify_entry"] = bool(vp_cfg.get("notify_entry", False))
    result["virtual_pnl_notify_exit"] = bool(vp_cfg.get("notify_exit", False))
    result["virtual_pnl_tiebreak"] = vp_cfg.get("intrabar_tiebreak", "stop_loss")
    return ConfigView(result)


def parse_market_hours_overrides(
    config: Mapping[str, Any],
) -> tuple[set[tuple[int, int, int]], dict[tuple[int, int, int], int]]:
    """
    Parse optional market-hours overrides from a loaded service config dict.

    This lives in the `config` layer by design: configuration may depend on `utils`,
    but `utils` must never depend on configuration (see docs/PROJECT_SUMMARY.md).

    Expected schema under `market_hours`:
    - enable_config_overrides: bool (default False)
    - holiday_overrides: list of [year, month, day]
    - early_closes: dict {"YYYY-MM-DD": hour_int}
    """
    holiday_overrides: set[tuple[int, int, int]] = set()
    early_closes: dict[tuple[int, int, int], int] = {}

    mh_config = config.get("market_hours", {}) or {}
    if not isinstance(mh_config, dict):
        return holiday_overrides, early_closes

    # Only load if explicitly enabled (preserves default behavior).
    if not mh_config.get("enable_config_overrides", False):
        return holiday_overrides, early_closes

    # Parse holiday_overrides (list of [year, month, day] lists)
    raw_holidays = mh_config.get("holiday_overrides", [])
    if isinstance(raw_holidays, list):
        for item in raw_holidays:
            if isinstance(item, (list, tuple)) and len(item) == 3:
                try:
                    holiday_overrides.add((int(item[0]), int(item[1]), int(item[2])))
                except (ValueError, TypeError):
                    # Malformed entries are ignored (best-effort feature).
                    pass

    # Parse early_closes (dict with "YYYY-MM-DD": hour format)
    raw_early = mh_config.get("early_closes", {})
    if isinstance(raw_early, dict):
        for date_str, hour in raw_early.items():
            try:
                parts = str(date_str).split("-")
                if len(parts) != 3:
                    continue
                key = (int(parts[0]), int(parts[1]), int(parts[2]))
                early_closes[key] = int(hour)
            except (ValueError, TypeError):
                # Malformed entries are ignored (best-effort feature).
                pass

    return holiday_overrides, early_closes


def load_market_hours_overrides(
    config_path: Optional[Path] = None,
    *,
    validate: bool = False,
) -> tuple[set[tuple[int, int, int]], dict[tuple[int, int, int], int]]:
    """
    Load optional market-hours overrides from config/config.yaml.

    - Disabled by default (enable via `market_hours.enable_config_overrides: true`)
    - Never raises on parse errors; returns empty overrides instead
    """
    try:
        config = load_service_config(config_path=config_path, validate=validate)
        holiday_overrides, early_closes = parse_market_hours_overrides(config)
        if holiday_overrides or early_closes:
            logger.info(
                "Loaded market hours overrides from config: "
                f"{len(holiday_overrides)} holidays, {len(early_closes)} early closes"
            )
        return holiday_overrides, early_closes
    except ImportError:
        # Defensive: treat as optional feature.
        return set(), {}
    except Exception as e:
        logger.warning(f"Could not load market hours overrides: {e}")
        return set(), {}


def validate_service_config(
    config_path: Optional[Path] = None,
    *,
    raise_on_error: bool = True,
) -> Optional["FullServiceConfig"]:
    """
    Validate service configuration against the Pydantic schema.

    This provides comprehensive type checking and constraint validation
    for the config.yaml file. Use this at startup to catch configuration
    errors early.

    Args:
        config_path: Path to config.yaml (defaults to config/config.yaml)
        raise_on_error: If True, raises ValidationError on invalid config.
                       If False, logs warning and returns None.

    Returns:
        Validated FullServiceConfig instance, or None if validation failed
        and raise_on_error is False.

    Raises:
        ImportError: If schema validation module is not available
        pydantic.ValidationError: If config is invalid and raise_on_error is True
    """
    if not SCHEMA_VALIDATION_AVAILABLE:
        raise ImportError(
            "Schema validation requires pydantic. "
            "Install with: pip install pydantic>=2.8"
        )

    try:
        config_data = load_config_yaml(config_path)
        validated = validate_config(config_data)
        logger.info("Configuration validated successfully against schema")
        return validated
    except Exception as e:
        if raise_on_error:
            raise
        logger.warning(f"Configuration validation failed: {e}")
        return None






