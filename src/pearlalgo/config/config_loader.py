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

**When to use strategy config (`strategies/nq_intraday/config.py`):**
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
from pearlalgo.utils.logger import logger

# Optional per-call override (used for experiments/backtests; never persisted).
# ContextVar keeps this safe across async tasks. It does NOT affect other processes.
_SERVICE_CONFIG_OVERRIDE: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "SERVICE_CONFIG_OVERRIDE",
    default=None,
)


def _deep_merge_dict(dst: Dict[str, Any], src: Mapping[str, Any]) -> Dict[str, Any]:
    """Recursively merge src into dst (mutates dst)."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge_dict(dst[k], v)  # type: ignore[index]
        else:
            dst[k] = v
    return dst


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


# Environment override helpers (typed)
_ENV_TRUE = {"1", "true", "yes", "y", "on"}
_ENV_FALSE = {"0", "false", "no", "n", "off"}


def _get_env_bool(name: str) -> Optional[bool]:
    """
    Read a boolean from the environment using tolerant parsing.

    Returns None if the env var is not set (so config.yaml/defaults remain in control).
    """
    raw = os.getenv(name)
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in _ENV_TRUE:
        return True
    if v in _ENV_FALSE:
        return False
    logger.warning(f"Invalid boolean for {name}={raw!r} (expected one of: {sorted(_ENV_TRUE | _ENV_FALSE)})")
    return None


def _get_env_str(name: str) -> Optional[str]:
    raw = os.getenv(name)
    if raw is None:
        return None
    v = raw.strip()
    return v if v else None


def _apply_execution_env_overrides(execution_cfg: Dict[str, Any]) -> None:
    """
    Apply safe, typed environment overrides for execution rollout.

    This avoids YAML `${ENV_VAR}` substitution for booleans, which would produce strings.
    """
    enabled = _get_env_bool("PEARLALGO_EXECUTION_ENABLED")
    if enabled is not None:
        execution_cfg["enabled"] = enabled

    armed = _get_env_bool("PEARLALGO_EXECUTION_ARMED")
    if armed is not None:
        execution_cfg["armed"] = armed

    mode = _get_env_str("PEARLALGO_EXECUTION_MODE")
    if mode:
        mode_norm = mode.lower()
        if mode_norm in ("dry_run", "paper", "live"):
            execution_cfg["mode"] = mode_norm
        else:
            logger.warning(
                f"Invalid PEARLALGO_EXECUTION_MODE={mode!r} (expected: dry_run|paper|live); ignoring"
            )

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
        "dashboard_chart_lookback_hours": 12,  # default notification chart window (12h)
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
        "db_path": "data/nq_agent_state/trades.db",
        "dual_write_files": True,
    },
    # ==========================================================================
    # ADAPTIVE RISK MANAGEMENT (v2.0)
    # ==========================================================================
    "adaptive_stops": {
        "enabled": False,
        "use_structure_stops": True,
        "use_level2_zones": True,  # approximated zones when only L1 is available
        "min_stop_points": 5.0,
        "regime_multipliers": {
            "ranging": 1.0,
            "trending_bullish": 1.2,
            "trending_bearish": 1.2,
        },
        "session_multipliers": {
            "tokyo": 0.8,
            "london": 0.9,
            "new_york": 1.0,
        },
        "volatility_multipliers": {
            "low": 0.9,
            "normal": 1.0,
            "high": 1.3,
        },
        "performance_adjustment": True,
    },
    "adaptive_sizing": {
        "enabled": False,
        "method": "kelly_criterion",
        "kelly_fraction": 0.25,
        "min_contracts": 1,
        "max_contracts": 15,
        "confidence_scaling": True,
        "regime_scaling": True,
        "session_scaling": True,
        "streak_adjustment": True,
    },
    "ml_filter": {
        "enabled": False,
        "model_path": None,
        "model_version": "v1.0.0",
        "min_probability": 0.55,
        "high_probability": 0.70,
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
        "max_position_size": 15,
        # Per-signal-type sizing overrides (Option A / risk shaping).
        # Example:
        #   signal_type_size_multipliers: { sr_bounce: 0.25 }
        #   signal_type_max_contracts: { sr_bounce: 2 }
        "signal_type_size_multipliers": {},
        "signal_type_max_contracts": {},
    },
    # ==========================================================================
    # TRAILING STOP LOSS (Profit Protection)
    # ==========================================================================
    # Enables breakeven + dynamic trailing stop management in TradeManager.
    # NOTE: This section MUST be present here so `trailing_stop:` in config.yaml
    # actually affects the running agent (otherwise it is silently ignored).
    "trailing_stop": {
        "enabled": False,
        "breakeven_immediate": True,
        "trail_method": "dynamic",
        "early_profit_trail_atr": 0.5,
        "medium_profit_trail_atr": 1.0,
        "large_profit_trail_atr": 1.5,
        "update_frequency_bars": 1,
        "never_widen": True,
        "min_profit_before_be": 2.0,
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
    "prop_firm": {
        "mnq_tick_value": 2.0,
        "nq_tick_value": 20.0,
        "min_contracts": 5,
        "max_contracts": 15,
        "default_contracts": 10,
        "max_risk_per_trade_pct": 1.0,
        "max_drawdown_pct": 10.0,
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
    "execution": {
        "enabled": False,                   # Master toggle - must be true for any execution
        "armed": False,                     # Runtime toggle - must be true to place orders
        "mode": "dry_run",                  # "dry_run" (log only), "paper", or "live"
        "adapter": "ibkr",                  # "ibkr" | "tradovate"
        # Risk limits (hard caps)
        "max_positions": 1,                 # Maximum concurrent positions
        "max_orders_per_day": 20,           # Maximum orders per trading day
        "max_daily_loss": 500.0,            # Kill switch: max daily loss in dollars
        "cooldown_seconds": 60,             # Minimum seconds between orders for same signal type
        # Symbol whitelist (empty = all symbols allowed)
        "symbol_whitelist": ["MNQ"],
        # IBKR connection (separate client_id from data to avoid conflicts)
        "ibkr_trading_client_id": 20,
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 4002,
    },
    # ==========================================================================
    # LEARNING (Adaptive Bandit Policy)
    # ==========================================================================
    # Adjusts execution decisions based on observed signal type performance.
    # Uses Thompson sampling (Beta-Bernoulli) per signal type.
    # SAFETY: Default is shadow mode - learns but does NOT affect execution.
    "learning": {
        "enabled": True,                    # Master toggle for adaptive policy
        "mode": "shadow",                   # "shadow" (observe only) or "live" (affects execution)
        # Bandit configuration
        "min_samples_per_type": 10,         # Minimum samples before policy has opinion
        "explore_rate": 0.1,                # Random explore rate (epsilon-greedy component)
        "decision_threshold": 0.3,          # Skip signal if P(win) < threshold
        # Position sizing adjustment (when mode=live)
        "max_size_multiplier": 1.5,         # Maximum size boost for high-confidence types
        "min_size_multiplier": 0.5,         # Minimum size reduction for low-confidence types
        # Prior distribution (Beta distribution parameters)
        # Start optimistic: alpha=2, beta=2 gives mean=0.5 with some uncertainty
        "prior_alpha": 2.0,
        "prior_beta": 2.0,
        # Decay factor for older observations (0 = no decay, 1 = full weight to recent)
        "decay_factor": 0.0,                # Disabled for now - all observations equal weight
    },
    # ==========================================================================
    # LLM FEATURES (optional)
    # ==========================================================================
    # These sections are used by the NQ agent to enrich signals with AI analysis and safety checks.
    # They are merged into the service config so they can be read via load_service_config().
    "llm_signal_annotation": {
        "enabled": False,
        "model": "claude-sonnet-4-20250514",
        "timeout_seconds": 5,
        "batch_mode": False,
    },
    "llm_risk_assessment": {
        "enabled": False,
        "model": "claude-sonnet-4-20250514",
        "timeout_seconds": 3,
        "block_on_critical": False,
        "consider_recent_trades": 20,
    },
    "llm_trade_postmortem": {
        "enabled": False,
        "model": "claude-sonnet-4-20250514",
        "timeout_seconds": 10,
        "min_pnl_threshold": 50,
        "send_to_telegram": False,
        "batch_analysis_count": 10,
    },
    "llm_pattern_recognition": {
        "enabled": False,
        "model": "claude-sonnet-4-20250514",
        "timeout_seconds": 30,
        "batch_size": 10,
        "lookback_trades": 50,
        "min_pattern_confidence": 0.7,
        "send_to_telegram": True,
    },
    "llm_adaptive_tuning": {
        "enabled": False,
        "model": "claude-sonnet-4-20250514",
        "timeout_seconds": 60,
        "analysis_interval_hours": 24,
        "auto_apply": False,
        "min_sample_size": 30,
        "conservative_mode": True,
    },
    # ==========================================================================
    # DRIFT GUARD (Risk-Off Cooldown)
    # ==========================================================================
    # IMPORTANT: This section must be present here so drift_guard settings in
    # config/config.yaml actually affect the running agent.
    "drift_guard": {
        "enabled": True,
        "lookback_trades": 20,
        "min_trades": 10,
        "win_rate_floor": 0.40,
        "volatility_spike_enabled": True,
        "volatility_levels": ["high", "extreme"],
        "require_atr_expansion": True,
        "cooldown_minutes": 60,
        "tighten_min_confidence_delta": 0.05,
        "tighten_min_risk_reward_delta": 0.20,
        "size_multiplier": 0.50,
    },
    # ==========================================================================
    # 50K CHALLENGE TRACKER (Pass/Fail Rules)
    # ==========================================================================
    "challenge": {
        "enabled": False,
        "start_balance": 50000.0,
        "max_drawdown": 2000.0,
        "profit_target": 3000.0,
        "auto_reset_on_pass": True,
        "auto_reset_on_fail": True,
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
    
    return result


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






