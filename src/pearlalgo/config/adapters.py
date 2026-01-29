"""
Configuration adapters for mapping config.yaml to domain-specific configurations.

This module contains the business logic for translating generic config.yaml 
settings into domain-specific configuration structures (strategy config, 
execution config, etc.).

**Purpose**: Extract domain knowledge from the generic config loader to 
improve separation of concerns. The config_loader module handles loading 
and merging; this module handles semantic translation.

**Usage**:
    ```python
    from pearlalgo.config.adapters import build_strategy_config_from_yaml
    
    strategy = build_strategy_config_from_yaml(base_strategy, config_data)
    ```
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.time_utils import parse_hhmm


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


def _coerce_bool(v: Any) -> bool:
    """Coerce a value to boolean with tolerant parsing for strings."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ("1", "true", "yes", "y", "on"):
            return True
        if t in ("0", "false", "no", "n", "off"):
            return False
    return bool(v)


def build_strategy_config_from_yaml(
    base_strategy: Dict[str, Any],
    config_data: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    Build a strategy config dict from base + config.yaml overrides.

    This maps config.yaml sections into the keys expected by
    `pearlalgo.trading_bots.pearl_bot_auto`.
    
    Args:
        base_strategy: Base strategy configuration (from pearl_bot_auto.CONFIG)
        config_data: Loaded config.yaml data
        
    Returns:
        Merged strategy configuration dictionary
    """
    strategy = dict(base_strategy or {})

    # Top-level overrides
    for key in ("symbol", "timeframe", "scan_interval"):
        if key in config_data and config_data.get(key) is not None:
            strategy[key] = config_data.get(key)

    # Session window (HH:MM strings -> hour/minute ints)
    session_cfg = config_data.get("session", {}) or {}
    start = session_cfg.get("start_time")
    end = session_cfg.get("end_time")
    if isinstance(start, str):
        parsed = parse_hhmm(start)
        if parsed:
            strategy["start_hour"], strategy["start_minute"] = parsed
    if isinstance(end, str):
        parsed = parse_hhmm(end)
        if parsed:
            strategy["end_hour"], strategy["end_minute"] = parsed

    # Signal thresholds
    signals_cfg = config_data.get("signals", {}) or {}
    if "min_confidence" in signals_cfg:
        try:
            strategy["min_confidence"] = float(signals_cfg["min_confidence"])
        except Exception:
            pass
    if "min_risk_reward" in signals_cfg:
        try:
            strategy["min_risk_reward"] = float(signals_cfg["min_risk_reward"])
        except Exception:
            pass

    # Risk mapping: keep telemetry keys + derive ATR target multiplier
    risk_cfg = config_data.get("risk", {}) or {}
    stop_mult = risk_cfg.get("stop_loss_atr_multiplier")
    if stop_mult is not None:
        try:
            stop_mult_f = float(stop_mult)
            strategy["stop_loss_atr_mult"] = stop_mult_f
            strategy["stop_loss_atr_multiplier"] = stop_mult_f
        except Exception:
            pass
    rr = risk_cfg.get("take_profit_risk_reward")
    if rr is not None:
        try:
            rr_f = float(rr)
            strategy["take_profit_risk_reward"] = rr_f
            if "stop_loss_atr_mult" in strategy:
                strategy["take_profit_atr_mult"] = float(strategy["stop_loss_atr_mult"]) * rr_f
        except Exception:
            pass

    if "max_risk_per_trade" in risk_cfg:
        try:
            strategy["max_risk_per_trade"] = float(risk_cfg["max_risk_per_trade"])
        except Exception:
            pass

    # Strategy-specific overrides for pearl_bot_auto (indicator knobs, etc.)
    # These keys map 1:1 to `pearlalgo.trading_bots.pearl_bot_auto.CONFIG`.
    bot_cfg = config_data.get("pearl_bot_auto", {}) or {}
    if isinstance(bot_cfg, dict):
        casts: Dict[str, Any] = {
            # Core indicators
            "ema_fast": int,
            "ema_slow": int,
            "volume_ma_length": int,
            "vwap_std_dev": float,
            "vwap_bands": int,
            # Aggressive trigger knobs
            "allow_vwap_cross_entries": _coerce_bool,
            "allow_vwap_retest_entries": _coerce_bool,
            "allow_trend_momentum_entries": _coerce_bool,
            "trend_momentum_atr_mult": float,
            "allow_trend_breakout_entries": _coerce_bool,
            "trend_breakout_lookback_bars": int,
            # Extended indicators
            "sr_length": int,
            "sr_extend": int,
            "sr_atr_mult": float,
            "tbt_period": int,
            "tbt_trend_type": str,
            "tbt_extend": int,
            "sd_threshold_pct": float,
            "sd_resolution": int,
            # Key levels
            "key_level_proximity_pct": float,
            "key_level_breakout_pct": float,
            "key_level_bounce_confidence": float,
            "key_level_breakout_confidence": float,
            "key_level_rejection_penalty": float,
        }

        for k, caster in casts.items():
            if k not in bot_cfg:
                continue
            v = bot_cfg.get(k)
            if v is None:
                continue
            try:
                strategy[k] = caster(v)
            except Exception:
                # Best-effort: ignore invalid overrides.
                pass

    # Virtual PnL grading (strategy config keys used by pearl_bot_auto + MarketAgentService)
    vp_cfg = config_data.get("virtual_pnl", {}) or {}
    if isinstance(vp_cfg, dict):
        try:
            if "enabled" in vp_cfg and vp_cfg.get("enabled") is not None:
                strategy["virtual_pnl_enabled"] = bool(vp_cfg.get("enabled"))
        except Exception:
            pass
        try:
            if "notify_entry" in vp_cfg and vp_cfg.get("notify_entry") is not None:
                strategy["virtual_pnl_notify_entry"] = bool(vp_cfg.get("notify_entry"))
        except Exception:
            pass
        try:
            if "notify_exit" in vp_cfg and vp_cfg.get("notify_exit") is not None:
                strategy["virtual_pnl_notify_exit"] = bool(vp_cfg.get("notify_exit"))
        except Exception:
            pass
        try:
            # Strategy key is `virtual_pnl_tiebreak`, config uses `intrabar_tiebreak`.
            tiebreak = vp_cfg.get("intrabar_tiebreak")
            if tiebreak is not None:
                strategy["virtual_pnl_tiebreak"] = str(tiebreak)
        except Exception:
            pass

    return strategy


def apply_execution_env_overrides(execution_cfg: Dict[str, Any]) -> None:
    """
    Apply safe, typed environment overrides for execution rollout.

    This avoids YAML `${ENV_VAR}` substitution for booleans, which would produce strings.
    Environment variables take precedence over config.yaml values.
    
    Environment variables checked:
        - PEARLALGO_EXECUTION_ENABLED: bool (enable/disable execution)
        - PEARLALGO_EXECUTION_ARMED: bool (arm/disarm for live trading)
        - PEARLALGO_EXECUTION_MODE: str (dry_run|paper|live)
        
    Args:
        execution_cfg: Execution configuration dict (mutated in place)
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


def apply_learning_env_overrides(learning_cfg: Dict[str, Any]) -> None:
    """
    Apply safe, typed environment overrides for learning layer.

    Environment variables checked:
        - PEARLALGO_LEARNING_ENABLED: bool (enable/disable learning)
        - PEARLALGO_LEARNING_MODE: str (shadow|live)
        
    Args:
        learning_cfg: Learning configuration dict (mutated in place)
    """
    enabled = _get_env_bool("PEARLALGO_LEARNING_ENABLED")
    if enabled is not None:
        learning_cfg["enabled"] = enabled

    mode = _get_env_str("PEARLALGO_LEARNING_MODE")
    if mode:
        mode_norm = mode.lower()
        if mode_norm in ("shadow", "live"):
            learning_cfg["mode"] = mode_norm
        else:
            logger.warning(
                f"Invalid PEARLALGO_LEARNING_MODE={mode!r} (expected: shadow|live); ignoring"
            )
