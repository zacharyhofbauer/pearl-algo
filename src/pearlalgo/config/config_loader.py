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
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from pearlalgo.config.config_file import load_config_yaml, log_config_warnings
from pearlalgo.config.config_view import ConfigView
from pearlalgo.config import defaults
from pearlalgo.utils.dict_utils import deep_merge_inplace as _deep_merge_dict
from pearlalgo.utils.logger import logger


# Schema validation: use schema_v2 for the --config path.
def validate_config(data):
    """Delegate to schema_v2 for type-checked validation."""
    from pearlalgo.config import schema_v2
    return schema_v2.validate_config(data)

def build_strategy_config_from_yaml(base, config_data):
    """Merge YAML config sections and pearl_bot_auto overrides into the strategy config dict.

    Section merges are shallow (nested dicts are replaced, not deep-merged).
    """
    result = dict(base)
    for section in ("strategy", "signals", "risk", "data", "service", "execution",
                    "session", "challenge", "performance", "virtual_pnl", "auto_flat",
                    "learning", "ml_filter", "swing_trading", "trading_circuit_breaker",
                    "circuit_breaker", "hud", "indicators", "telegram", "telegram_ui",
                    "storage", "audit", "accounts"):
        if section in config_data:
            if isinstance(config_data[section], dict) and isinstance(result.get(section), dict):
                result[section] = {**result.get(section, {}), **config_data[section]}
            else:
                result[section] = config_data[section]
    # Top-level scalar overrides
    for key in ("symbol", "timeframe", "scan_interval"):
        if key in config_data:
            result[key] = config_data[key]
    # pearl_bot_auto section: flatten only StrategyParams keys to top-level
    # so generate_signals() / StrategyParams can read them; unknown keys are ignored.
    from pearlalgo.trading_bots.pearl_bot_auto import StrategyParams
    allowed_keys = set(StrategyParams.model_fields.keys())
    pba = config_data.get("pearl_bot_auto")
    if isinstance(pba, dict):
        for key, value in pba.items():
            if key in allowed_keys:
                result[key] = value
            else:
                logger.warning(
                    "pearl_bot_auto key '%s' is not a StrategyParams field; ignoring", key
                )
    return result

def _apply_execution_env_overrides(execution_config):
    """Apply environment variable overrides for execution settings."""
    import os
    for env_key, config_key, conv in [
        ("IBKR_HOST", "ibkr_host", str),
        ("IBKR_PORT", "ibkr_port", int),
        ("IBKR_CLIENT_ID", "ibkr_trading_client_id", int),
    ]:
        val = os.getenv(env_key)
        if val is not None:
            try:
                execution_config[config_key] = conv(val)
            except (ValueError, TypeError):
                pass

def _apply_learning_env_overrides(learning_config):
    """No-op stub: learning env overrides removed."""
    pass

# Optional per-call override (used for experiments/backtests; never persisted).
# ContextVar keeps this safe across async tasks. It does NOT affect other processes.
_SERVICE_CONFIG_OVERRIDE: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "SERVICE_CONFIG_OVERRIDE",
    default=None,
)

# ── mtime-based config cache ────────────────────────────────────────────────
# Avoids re-parsing YAML on every call when the config file hasn't changed.
_config_cache: Optional[Dict[str, Any]] = None
_config_cache_mtime: float = 0.0
_config_cache_path: Optional[str] = None


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
        except Exception as e:
            logger.debug("ContextVar reset failed, clearing override: %s", e)
            _SERVICE_CONFIG_OVERRIDE.set(None)


def _resolve_config_path(config_path: Optional[Path] = None) -> str:
    """Resolve the effective config file path for mtime-based caching."""
    if config_path is not None:
        return str(Path(config_path).resolve())
    project_root = Path(__file__).parent.parent.parent.parent
    return str((project_root / "config" / "config.yaml").resolve())


def clear_config_cache() -> None:
    """Clear the mtime-based config cache.

    Call this in tests or whenever you need to force a full reload
    on the next ``load_service_config()`` call.
    """
    global _config_cache, _config_cache_mtime, _config_cache_path
    _config_cache = None
    _config_cache_mtime = 0.0
    _config_cache_path = None


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


# ---------------------------------------------------------------------------
# Default values for service configuration sections.
#
# ALL values are sourced from ``pearlalgo.config.defaults`` so there is a
# single source of truth.  Do NOT add literal values here — add them to
# ``defaults.py`` and reference them.
# ---------------------------------------------------------------------------
_SERVICE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "service": {
        "status_update_interval": defaults.STATUS_UPDATE_INTERVAL,
        "heartbeat_interval": defaults.HEARTBEAT_INTERVAL,
        "state_save_interval": defaults.STATE_SAVE_INTERVAL,
        "cadence_mode": defaults.CADENCE_MODE,
        "enable_new_bar_gating": defaults.ENABLE_NEW_BAR_GATING,
        "pressure_lookback_bars": defaults.PRESSURE_LOOKBACK_BARS,
        "pressure_baseline_bars": defaults.PRESSURE_BASELINE_BARS,
        "dashboard_chart_enabled": defaults.DASHBOARD_CHART_ENABLED,
        "dashboard_chart_interval": defaults.DASHBOARD_CHART_INTERVAL,
        "dashboard_chart_lookback_hours": defaults.DASHBOARD_CHART_LOOKBACK_HOURS,
        "dashboard_chart_timeframe": defaults.DASHBOARD_CHART_TIMEFRAME,
        "dashboard_chart_max_bars": defaults.DASHBOARD_CHART_MAX_BARS,
        "dashboard_chart_show_pressure": defaults.DASHBOARD_CHART_SHOW_PRESSURE,
        "connection_failure_alert_interval": defaults.CONNECTION_FAILURE_ALERT_INTERVAL,
        "data_quality_alert_interval": defaults.DATA_QUALITY_ALERT_INTERVAL,
    },
    "telegram_ui": {
        "compact_metrics_enabled": defaults.TELEGRAM_UI_COMPACT_METRICS,
        "show_progress_bars": defaults.TELEGRAM_UI_SHOW_PROGRESS_BARS,
        "show_volume_metrics": defaults.TELEGRAM_UI_SHOW_VOLUME_METRICS,
        "compact_metric_width": defaults.TELEGRAM_UI_COMPACT_METRIC_WIDTH,
    },
    "circuit_breaker": {
        "max_consecutive_errors": defaults.MAX_CONSECUTIVE_ERRORS,
        "max_connection_failures": defaults.MAX_CONNECTION_FAILURES,
        "max_data_fetch_errors": defaults.MAX_DATA_FETCH_ERRORS,
    },
    "trading_circuit_breaker": {
        "enabled": defaults.TCB_ENABLED,
        "max_consecutive_losses": defaults.TCB_MAX_CONSECUTIVE_LOSSES,
        "consecutive_loss_cooldown_minutes": defaults.TCB_CONSECUTIVE_LOSS_COOLDOWN_MINUTES,
        "max_session_drawdown": defaults.TCB_MAX_SESSION_DRAWDOWN,
        "max_daily_drawdown": defaults.TCB_MAX_DAILY_DRAWDOWN,
        "drawdown_cooldown_minutes": defaults.TCB_DRAWDOWN_COOLDOWN_MINUTES,
        "rolling_window_trades": defaults.TCB_ROLLING_WINDOW_TRADES,
        "min_rolling_win_rate": defaults.TCB_MIN_ROLLING_WIN_RATE,
        "win_rate_cooldown_minutes": defaults.TCB_WIN_RATE_COOLDOWN_MINUTES,
        "max_concurrent_positions": defaults.TCB_MAX_CONCURRENT_POSITIONS,
        "min_price_distance_pct": defaults.TCB_MIN_PRICE_DISTANCE_PCT,
        "enable_volatility_filter": defaults.TCB_ENABLE_VOLATILITY_FILTER,
        "min_atr_ratio": defaults.TCB_MIN_ATR_RATIO,
        "max_atr_ratio": defaults.TCB_MAX_ATR_RATIO,
        "chop_detection_window": defaults.TCB_CHOP_DETECTION_WINDOW,
        "chop_win_rate_threshold": defaults.TCB_CHOP_WIN_RATE_THRESHOLD,
        "auto_resume_after_cooldown": defaults.TCB_AUTO_RESUME_AFTER_COOLDOWN,
        "require_winning_trade_to_resume": defaults.TCB_REQUIRE_WINNING_TRADE_TO_RESUME,
        "enable_session_filter": defaults.TCB_ENABLE_SESSION_FILTER,
        "allowed_sessions": defaults.TCB_ALLOWED_SESSIONS.copy(),
    },
    "data": {
        "buffer_size": defaults.DATA_BUFFER_SIZE,
        "buffer_size_5m": defaults.DATA_BUFFER_SIZE_5M,
        "buffer_size_15m": defaults.DATA_BUFFER_SIZE_15M,
        "historical_hours": defaults.HISTORICAL_HOURS,
        "multitimeframe_5m_hours": defaults.MULTITIMEFRAME_5M_HOURS,
        "multitimeframe_15m_hours": defaults.MULTITIMEFRAME_15M_HOURS,
        "performance_history_limit": defaults.PERFORMANCE_HISTORY_LIMIT,
        "stale_data_threshold_minutes": defaults.STALE_DATA_THRESHOLD_MINUTES,
        "connection_timeout_minutes": defaults.CONNECTION_TIMEOUT_MINUTES,
        "enable_base_cache": defaults.ENABLE_BASE_CACHE,
        "base_refresh_seconds": defaults.BASE_REFRESH_SECONDS,
        "enable_mtf_cache": defaults.ENABLE_MTF_CACHE,
        "mtf_refresh_seconds_5m": defaults.MTF_REFRESH_SECONDS_5M,
        "mtf_refresh_seconds_15m": defaults.MTF_REFRESH_SECONDS_15M,
        "ibkr_verbose_logging": defaults.IBKR_VERBOSE_LOGGING,
    },
    "storage": {
        "sqlite_enabled": defaults.STORAGE_SQLITE_ENABLED,
        "db_path": defaults.STORAGE_DB_PATH,
        "dual_write_files": defaults.STORAGE_DUAL_WRITE_FILES,
    },
    "ml_filter": {
        "enabled": defaults.ML_FILTER_ENABLED,
        "model_path": defaults.ML_FILTER_MODEL_PATH,
        "model_version": defaults.ML_FILTER_MODEL_VERSION,
        "min_probability": defaults.ML_FILTER_MIN_PROBABILITY,
        "high_probability": defaults.ML_FILTER_HIGH_PROBABILITY,
        "adjust_sizing": defaults.ML_FILTER_ADJUST_SIZING,
        "size_multiplier_min": defaults.ML_FILTER_SIZE_MULTIPLIER_MIN,
        "size_multiplier_max": defaults.ML_FILTER_SIZE_MULTIPLIER_MAX,
        "min_training_samples": defaults.ML_FILTER_MIN_TRAINING_SAMPLES,
        "retrain_interval_days": defaults.ML_FILTER_RETRAIN_INTERVAL_DAYS,
        "n_estimators": defaults.ML_FILTER_N_ESTIMATORS,
        "max_depth": defaults.ML_FILTER_MAX_DEPTH,
        "learning_rate": defaults.ML_FILTER_LEARNING_RATE,
        "calibrate_probabilities": defaults.ML_FILTER_CALIBRATE_PROBABILITIES,
    },
    "risk": {
        "max_risk_per_trade": defaults.MAX_RISK_PER_TRADE,
        "max_drawdown": defaults.MAX_DRAWDOWN,
        "stop_loss_atr_multiplier": defaults.STOP_LOSS_ATR_MULTIPLIER,
        "take_profit_risk_reward": defaults.TAKE_PROFIT_RISK_REWARD,
        "min_position_size": defaults.MIN_POSITION_SIZE,
        "max_position_size": defaults.MAX_POSITION_SIZE,
        "signal_type_size_multipliers": {},
        "signal_type_max_contracts": {},
    },
    "signals": {
        "duplicate_window_seconds": defaults.DUPLICATE_WINDOW_SECONDS,
        "min_confidence": defaults.MIN_CONFIDENCE,
        "min_risk_reward": defaults.MIN_RISK_REWARD,
    },
    "performance": {
        "max_records": defaults.PERFORMANCE_MAX_RECORDS,
        "default_lookback_days": defaults.PERFORMANCE_DEFAULT_LOOKBACK_DAYS,
    },
    "virtual_pnl": {
        "enabled": defaults.VIRTUAL_PNL_ENABLED,
        "intrabar_tiebreak": defaults.VIRTUAL_PNL_INTRABAR_TIEBREAK,
        "notify_entry": defaults.VIRTUAL_PNL_NOTIFY_ENTRY,
        "notify_exit": defaults.VIRTUAL_PNL_NOTIFY_EXIT,
    },
    "auto_flat": {
        "enabled": defaults.AUTO_FLAT_ENABLED,
        "friday_enabled": defaults.AUTO_FLAT_FRIDAY_ENABLED,
        "friday_time": defaults.AUTO_FLAT_FRIDAY_TIME,
        "weekend_enabled": defaults.AUTO_FLAT_WEEKEND_ENABLED,
        "timezone": defaults.AUTO_FLAT_TIMEZONE,
        "notify": defaults.AUTO_FLAT_NOTIFY,
    },
    "market_hours": {
        "enable_config_overrides": defaults.MARKET_HOURS_ENABLE_CONFIG_OVERRIDES,
        "holiday_overrides": defaults.MARKET_HOURS_HOLIDAY_OVERRIDES.copy(),
        "early_closes": defaults.MARKET_HOURS_EARLY_CLOSES.copy(),
    },
    "execution": {
        "enabled": defaults.EXECUTION_ENABLED,
        "armed": defaults.EXECUTION_ARMED,
        "mode": defaults.EXECUTION_MODE,
        "adapter": "tradovate",
        "max_positions": defaults.MAX_POSITIONS,
        "max_orders_per_day": defaults.MAX_ORDERS_PER_DAY,
        "max_daily_loss": defaults.MAX_DAILY_LOSS,
        "cooldown_seconds": defaults.COOLDOWN_SECONDS,
        "symbol_whitelist": defaults.DEFAULT_SYMBOL_WHITELIST.copy(),
        "ibkr_trading_client_id": defaults.IBKR_TRADING_CLIENT_ID,
        "ibkr_host": defaults.IBKR_HOST,
        "ibkr_port": defaults.IBKR_PORT,
    },
    "learning": {
        "enabled": defaults.LEARNING_ENABLED,
        "mode": defaults.LEARNING_MODE,
        "min_samples_per_type": defaults.MIN_SAMPLES_PER_TYPE,
        "explore_rate": defaults.EXPLORE_RATE,
        "decision_threshold": defaults.DECISION_THRESHOLD,
        "max_size_multiplier": defaults.MAX_SIZE_MULTIPLIER,
        "min_size_multiplier": defaults.MIN_SIZE_MULTIPLIER,
        "prior_alpha": defaults.PRIOR_ALPHA,
        "prior_beta": defaults.PRIOR_BETA,
        "decay_factor": defaults.DECAY_FACTOR,
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
    Results are cached at the module level based on the config file's mtime,
    so repeated calls are nearly free when the file hasn't been modified.

    Args:
        config_path: Path to config.yaml (defaults to config/config.yaml)
        validate: Whether to validate config and log warnings. Default True.
                  Set to False in tests or when loading config multiple times.

    Returns:
        Dictionary with service configuration sections merged with defaults
    """
    global _config_cache, _config_cache_mtime, _config_cache_path

    effective_path = _resolve_config_path(config_path)
    override = _SERVICE_CONFIG_OVERRIDE.get()

    # ── mtime-based cache (skip when per-call override is active) ──────────
    if override is None:
        try:
            current_mtime = os.path.getmtime(effective_path)
            if (
                _config_cache is not None
                and _config_cache_path == effective_path
                and _config_cache_mtime == current_mtime
            ):
                return _config_cache
        except OSError:
            # Config file doesn't exist – fall through to normal load
            pass

    # Load raw config using unified loader
    config_data = load_config_yaml(config_path)

    # Validate config (logs warnings, does not fail)
    if validate and config_data:
        log_config_warnings(config_data)

        # Run mandatory schema validation — fail fast on invalid config
        try:
            validate_config(config_data)
            logger.debug("Config schema validation passed")
        except Exception as e:
            logger.error(f"Config schema validation FAILED: {e}")
            raise SystemExit(f"Invalid configuration — aborting startup: {e}") from e
    
    # Merge config sections with defaults
    result = {}
    for section, defaults in _SERVICE_DEFAULTS.items():
        result[section] = {**defaults, **config_data.get(section, {})}

    # Apply optional in-process overrides (best-effort).
    # This allows experiments/backtests to tweak config without editing files.
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

    try:
        _apply_learning_env_overrides(result.get("learning", {}))
    except Exception as e:
        logger.warning(f"Could not apply learning env overrides: {e}")

    # Flatten virtual_pnl fields for legacy attribute access
    vp_cfg = result.get("virtual_pnl", {}) or {}
    result["virtual_pnl_enabled"] = bool(vp_cfg.get("enabled", True))
    result["virtual_pnl_notify_entry"] = bool(vp_cfg.get("notify_entry", False))
    result["virtual_pnl_notify_exit"] = bool(vp_cfg.get("notify_exit", False))
    result["virtual_pnl_tiebreak"] = vp_cfg.get("intrabar_tiebreak", "stop_loss")

    result_view = ConfigView(result)

    # ── Update mtime cache (only when no override is active) ───────────────
    if override is None:
        try:
            _config_cache_mtime = os.path.getmtime(effective_path)
        except OSError:
            _config_cache_mtime = 0.0
        _config_cache_path = effective_path
        _config_cache = result_view

    return result_view


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





