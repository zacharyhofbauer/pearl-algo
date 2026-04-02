"""
Config management API endpoints for the PEARL settings dashboard.

The dashboard now reads and writes the single canonical runtime config:
``config/live/tradovate_paper.yaml``.
"""

from __future__ import annotations

import collections
import hashlib
import logging
import os
import subprocess
import threading
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pearlalgo.config.runtime_validation import (
    collect_runtime_config_warnings,
    validate_runtime_config,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
LIVE_YAML_PATH = PROJECT_ROOT / "config" / "live" / "tradovate_paper.yaml"

# ---------------------------------------------------------------------------
# Rate limiting (mirrors server.py pattern)
# ---------------------------------------------------------------------------
_rate_limit_window: float = 60.0
_rate_limit_max: int = 5
_rate_limit_buckets: Dict[str, collections.deque] = {}
_rate_limit_lock = threading.Lock()


def _check_rate_limit(endpoint: str) -> None:
    now = time.monotonic()
    with _rate_limit_lock:
        bucket = _rate_limit_buckets.setdefault(endpoint, collections.deque())
        while bucket and bucket[0] < now - _rate_limit_window:
            bucket.popleft()
        if len(bucket) >= _rate_limit_max:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {endpoint}. Max {_rate_limit_max} requests per {_rate_limit_window}s.",
            )
        bucket.append(now)


FORBIDDEN_KEYS = frozenset({
    "execution.adapter",
    "virtual_pnl.enabled",
    "account.name",
})


def _strategy_field(description: str, *, field_type: str = "number", min_val: float | None = None,
                    max_val: float | None = None, options: List[str] | None = None,
                    dangerous: bool = False) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": field_type,
        "dangerous": dangerous,
        "description": description,
        "category": "Trading",
        "yaml_section": "strategies.composite_intraday",
    }
    if min_val is not None:
        schema["min"] = min_val
    if max_val is not None:
        schema["max"] = max_val
    if options is not None:
        schema["options"] = options
    return schema


SCHEMA: Dict[str, Dict[str, Any]] = {
    # -- Strategy runtime --
    "strategy.active": {
        "type": "select",
        "options": ["composite_intraday"],
        "dangerous": False,
        "description": "Active live strategy bundle",
        "category": "Trading",
        "yaml_section": "strategy",
    },
    "strategy.enforce_session_window": {
        "type": "boolean",
        "dangerous": False,
        "description": "Enforce the strategy-level session window",
        "category": "Trading",
        "yaml_section": "strategy",
    },
    "strategies.composite_intraday.stop_loss_atr_mult": _strategy_field("Stop-loss ATR multiplier", min_val=0.1, max_val=10),
    "strategies.composite_intraday.take_profit_atr_mult": _strategy_field("Take-profit ATR multiplier", min_val=0.1, max_val=10),
    "strategies.composite_intraday.min_confidence": _strategy_field("Minimum confidence threshold", min_val=0, max_val=1),
    "strategies.composite_intraday.min_confidence_long": _strategy_field("Minimum confidence (long)", min_val=0, max_val=1),
    "strategies.composite_intraday.min_confidence_short": _strategy_field("Minimum confidence (short)", min_val=0, max_val=1),
    "strategies.composite_intraday.ema_fast": _strategy_field("EMA fast period", min_val=1, max_val=50),
    "strategies.composite_intraday.ema_slow": _strategy_field("EMA slow period", min_val=1, max_val=100),
    "strategies.composite_intraday.volatile_sl_mult": _strategy_field("Volatile regime SL multiplier", min_val=0.1, max_val=5),
    "strategies.composite_intraday.volatile_tp_mult": _strategy_field("Volatile regime TP multiplier", min_val=0.1, max_val=5),
    "strategies.composite_intraday.ranging_sl_mult": _strategy_field("Ranging regime SL multiplier", min_val=0.1, max_val=5),
    "strategies.composite_intraday.ranging_tp_mult": _strategy_field("Ranging regime TP multiplier", min_val=0.1, max_val=5),
    "strategies.composite_intraday.allow_vwap_cross_entries": _strategy_field("Allow VWAP cross entries", field_type="boolean"),
    "strategies.composite_intraday.allow_vwap_retest_entries": _strategy_field("Allow VWAP retest entries", field_type="boolean"),
    "strategies.composite_intraday.allow_trend_momentum_entries": _strategy_field("Allow trend momentum entries", field_type="boolean"),
    "strategies.composite_intraday.allow_trend_breakout_entries": _strategy_field("Allow trend breakout entries", field_type="boolean"),
    "strategies.composite_intraday.allow_orb_entries": _strategy_field("Allow opening range breakout entries", field_type="boolean"),
    "strategies.composite_intraday.allow_vwap_2sd_entries": _strategy_field("Allow VWAP 2SD entries", field_type="boolean"),
    "strategies.composite_intraday.allow_smc_entries": _strategy_field("Allow SMC entries", field_type="boolean"),
    "strategies.composite_intraday.vwap_std_dev": _strategy_field("VWAP standard deviation band", min_val=0.5, max_val=3.0),
    "strategies.composite_intraday.volume_ma_length": _strategy_field("Volume moving average length", min_val=5, max_val=100),
    "strategies.composite_intraday.sr_length": _strategy_field("Support/resistance lookback length", min_val=10, max_val=500),
    "strategies.composite_intraday.sr_atr_mult": _strategy_field("S/R ATR zone multiplier", min_val=0.1, max_val=3.0),
    "strategies.composite_intraday.trend_momentum_atr_mult": _strategy_field("Trend momentum ATR multiplier", min_val=0.1, max_val=3.0),
    "strategies.composite_intraday.trend_breakout_lookback_bars": _strategy_field("Trend breakout lookback bars", min_val=1, max_val=50),
    "strategies.composite_intraday.tbt_period": _strategy_field("TBT trendline period", min_val=1, max_val=50),
    "strategies.composite_intraday.tbt_trend_type": _strategy_field("TBT trend type", field_type="select", options=["wicks", "bodies"]),
    "strategies.composite_intraday.adx_period": _strategy_field("ADX period", min_val=5, max_val=50),
    "strategies.composite_intraday.adx_trending_threshold": _strategy_field("ADX trending threshold", min_val=10, max_val=50),
    "strategies.composite_intraday.adx_ranging_threshold": _strategy_field("ADX ranging threshold", min_val=5, max_val=40),

    # -- Signals --
    "signals.max_stop_points": {
        "type": "number", "min": 5, "max": 200,
        "dangerous": False, "description": "Max stop loss distance (points)",
        "category": "Trading", "yaml_section": "signals",
    },
    "signals.min_risk_reward": {
        "type": "number", "min": 0.5, "max": 10,
        "dangerous": False, "description": "Minimum risk/reward ratio",
        "category": "Trading", "yaml_section": "signals",
    },

    # -- Execution --
    "execution.armed": {
        "type": "boolean",
        "dangerous": True, "description": "Arm order submission",
        "category": "Execution", "yaml_section": "execution",
    },
    "execution.enabled": {
        "type": "boolean",
        "dangerous": True, "description": "Master execution switch",
        "category": "Execution", "yaml_section": "execution",
    },
    "execution.mode": {
        "type": "select", "options": ["paper", "dry_run"],
        "dangerous": True, "description": "Execution mode",
        "category": "Execution", "yaml_section": "execution",
    },
    "execution.max_positions": {
        "type": "number", "min": 1, "max": 10,
        "dangerous": True, "description": "Max concurrent positions",
        "category": "Execution", "yaml_section": "execution",
    },
    "execution.max_position_size_per_order": {
        "type": "number", "min": 1, "max": 5,
        "dangerous": True, "description": "Max contracts per order",
        "category": "Execution", "yaml_section": "execution",
    },
    "execution.cooldown_seconds": {
        "type": "number", "min": 0, "max": 600,
        "dangerous": False, "description": "Cooldown between orders (seconds)",
        "category": "Execution", "yaml_section": "execution",
    },
    "execution.max_orders_per_day": {
        "type": "number", "min": 1, "max": 999,
        "dangerous": False, "description": "Max orders per day",
        "category": "Execution", "yaml_section": "execution",
    },
    "execution.max_daily_loss": {
        "type": "number", "min": 1, "max": 999999,
        "dangerous": True, "description": "Hard daily loss stop",
        "category": "Execution", "yaml_section": "execution",
    },

    # -- Session --
    "session.start_time": {
        "type": "text",
        "dangerous": False, "description": "Session start time",
        "category": "Session", "yaml_section": "session",
    },
    "session.end_time": {
        "type": "text",
        "dangerous": False, "description": "Session end time",
        "category": "Session", "yaml_section": "session",
    },
    "session.timezone": {
        "type": "text",
        "dangerous": False, "description": "Session timezone",
        "category": "Session", "yaml_section": "session",
    },

    # -- Risk --
    "risk.max_position_size": {
        "type": "number", "min": 1, "max": 50,
        "dangerous": True, "description": "Max position size (contracts)",
        "category": "Risk", "yaml_section": "risk",
    },
    "risk.max_drawdown": {
        "type": "number", "min": 0, "max": 1,
        "dangerous": True, "description": "Max drawdown ratio",
        "category": "Risk", "yaml_section": "risk",
    },
    "risk.max_risk_per_trade": {
        "type": "number", "min": 0, "max": 1,
        "dangerous": True, "description": "Max risk per trade ratio",
        "category": "Risk", "yaml_section": "risk",
    },

    # -- Guardrails --
    "guardrails.signal_gate_enabled": {
        "type": "boolean",
        "dangerous": True,
        "description": "Re-enable the legacy signal veto layer",
        "category": "Guardrails",
        "yaml_section": "guardrails",
    },
    "guardrails.max_consecutive_losses": {
        "type": "number", "min": 1, "max": 20,
        "dangerous": True,
        "description": "Legacy signal gate: max consecutive losses",
        "category": "Guardrails",
        "yaml_section": "guardrails",
    },
    "guardrails.max_session_drawdown": {
        "type": "number", "min": 100, "max": 99999,
        "dangerous": True,
        "description": "Legacy signal gate: max session drawdown ($)",
        "category": "Guardrails",
        "yaml_section": "guardrails",
    },
    "guardrails.max_daily_drawdown": {
        "type": "number", "min": 100, "max": 99999,
        "dangerous": True,
        "description": "Legacy signal gate: max daily drawdown ($)",
        "category": "Guardrails",
        "yaml_section": "guardrails",
    },

    # -- Trailing Stop --
    "trailing_stop.enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Trailing stop enabled",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },
    "trailing_stop.min_move_points": {
        "type": "number", "min": 0.1, "max": 10,
        "dangerous": False, "description": "Min move points to activate",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },
    "trailing_stop.regime_adaptive": {
        "type": "boolean",
        "dangerous": False, "description": "Regime-adaptive trailing stop",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },
    "trailing_stop.allow_external_override": {
        "type": "boolean",
        "dangerous": False, "description": "Allow external trailing stop override",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },
    "trailing_stop.max_override_ttl_minutes": {
        "type": "number", "min": 1, "max": 600,
        "dangerous": False, "description": "Max override TTL (minutes)",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },

    # -- Auto Flat --
    "auto_flat.enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Auto-flat enabled",
        "category": "Auto Flat", "yaml_section": "auto_flat",
    },
    "auto_flat.daily_enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Daily auto-flat enabled",
        "category": "Auto Flat", "yaml_section": "auto_flat",
    },
    "auto_flat.daily_time": {
        "type": "text",
        "dangerous": False, "description": "Daily auto-flat time",
        "category": "Auto Flat", "yaml_section": "auto_flat",
    },
    "auto_flat.friday_enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Friday auto-flat enabled",
        "category": "Auto Flat", "yaml_section": "auto_flat",
    },
    "auto_flat.friday_time": {
        "type": "text",
        "dangerous": False, "description": "Friday auto-flat time",
        "category": "Auto Flat", "yaml_section": "auto_flat",
    },

    # -- Advanced Exits --
    "advanced_exits.quick_exit.enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Quick exit enabled",
        "category": "Advanced Exits", "yaml_section": "advanced_exits.quick_exit",
    },
    "advanced_exits.quick_exit.min_duration_minutes": {
        "type": "number", "min": 1, "max": 120,
        "dangerous": False, "description": "Quick exit min duration (min)",
        "category": "Advanced Exits", "yaml_section": "advanced_exits.quick_exit",
    },
    "advanced_exits.quick_exit.max_mfe_threshold": {
        "type": "number", "min": 1, "max": 200,
        "dangerous": False, "description": "Quick exit max MFE threshold",
        "category": "Advanced Exits", "yaml_section": "advanced_exits.quick_exit",
    },
    "advanced_exits.quick_exit.min_mae_threshold": {
        "type": "number", "min": 1, "max": 200,
        "dangerous": False, "description": "Quick exit min MAE threshold",
        "category": "Advanced Exits", "yaml_section": "advanced_exits.quick_exit",
    },
    "advanced_exits.time_based_exit.enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Time-based exit enabled",
        "category": "Advanced Exits", "yaml_section": "advanced_exits.time_based_exit",
    },
    "advanced_exits.time_based_exit.min_duration_minutes": {
        "type": "number", "min": 1, "max": 120,
        "dangerous": False, "description": "Time-based exit min duration (min)",
        "category": "Advanced Exits", "yaml_section": "advanced_exits.time_based_exit",
    },
    "advanced_exits.time_based_exit.min_profit_threshold": {
        "type": "number", "min": 1, "max": 500,
        "dangerous": False, "description": "Time-based exit min profit threshold",
        "category": "Advanced Exits", "yaml_section": "advanced_exits.time_based_exit",
    },
    "advanced_exits.time_based_exit.take_percentage": {
        "type": "number", "min": 0.1, "max": 1.0,
        "dangerous": False, "description": "Time-based exit take percentage",
        "category": "Advanced Exits", "yaml_section": "advanced_exits.time_based_exit",
    },
    "advanced_exits.stop_optimization.enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Stop optimization enabled",
        "category": "Advanced Exits", "yaml_section": "advanced_exits.stop_optimization",
    },

    # -- Service --
    "scan_interval": {
        "type": "number", "min": 5, "max": 300,
        "dangerous": False, "description": "Base scan interval (seconds)",
        "category": "Service", "yaml_section": "",
    },
    "service.velocity_mode_enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Velocity mode (fast scanning on momentum)",
        "category": "Service", "yaml_section": "service",
    },
    "service.scan_interval_active_seconds": {
        "type": "number", "min": 1, "max": 120,
        "dangerous": False, "description": "Active market scan interval (seconds)",
        "category": "Service", "yaml_section": "service",
    },
    "service.scan_interval_idle_seconds": {
        "type": "number", "min": 10, "max": 600,
        "dangerous": False, "description": "Idle market scan interval (seconds)",
        "category": "Service", "yaml_section": "service",
    },
    "service.scan_interval_market_closed_seconds": {
        "type": "number", "min": 30, "max": 3600,
        "dangerous": False, "description": "Market closed scan interval (seconds)",
        "category": "Service", "yaml_section": "service",
    },
    "service.enable_new_bar_gating": {
        "type": "boolean",
        "dangerous": False, "description": "Only process signals on new bar close",
        "category": "Service", "yaml_section": "service",
    },
    "service.dashboard_chart_enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Dashboard chart generation",
        "category": "Service", "yaml_section": "service",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _get_nested(d: dict, dotted_path: str, default: Any = None) -> Any:
    keys = dotted_path.split(".")
    current = d
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _set_nested(d: dict, dotted_path: str, value: Any) -> None:
    keys = dotted_path.split(".")
    current = d
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def _compute_override_keys(base: dict, override: dict, prefix: str = "") -> List[str]:
    keys = []
    for key, value in override.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in base:
            keys.append(path)
        elif isinstance(value, dict) and isinstance(base.get(key), dict):
            keys.extend(_compute_override_keys(base[key], value, path))
        elif base.get(key) != value:
            keys.append(path)
    return keys


def _config_hash(merged: dict) -> str:
    yaml_str = yaml.dump(merged, default_flow_style=False, sort_keys=True)
    return hashlib.sha256(yaml_str.encode("utf-8")).hexdigest()


def _validate_runtime_candidate(config: dict) -> List[str]:
    try:
        validate_runtime_config(
            config,
            strict_non_enforced=True,
            warn_unknown=False,
        )
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Runtime config validation failed: {str(e)[:300]}",
        ) from e

    return collect_runtime_config_warnings(config, warn_unknown=True)


def _validate_value(dotted_path: str, value: Any, field_schema: Dict[str, Any]) -> Any:
    field_type = field_schema["type"]

    if field_type == "boolean":
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=422,
                detail=f"Field '{dotted_path}' must be a boolean, got {type(value).__name__}",
            )
        return value

    if field_type == "number":
        if isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"Field '{dotted_path}' must be a number, got boolean")
        if not isinstance(value, (int, float)):
            raise HTTPException(
                status_code=422,
                detail=f"Field '{dotted_path}' must be a number, got {type(value).__name__}",
            )
        min_val = field_schema.get("min")
        max_val = field_schema.get("max")
        if min_val is not None and value < min_val:
            raise HTTPException(status_code=422, detail=f"Field '{dotted_path}' value {value} is below minimum {min_val}")
        if max_val is not None and value > max_val:
            raise HTTPException(status_code=422, detail=f"Field '{dotted_path}' value {value} is above maximum {max_val}")
        return value

    if field_type == "select":
        options = field_schema.get("options", [])
        if value not in options:
            raise HTTPException(status_code=422, detail=f"Field '{dotted_path}' must be one of {options}, got '{value}'")
        return value

    if field_type == "text":
        if not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail=f"Field '{dotted_path}' must be a string, got {type(value).__name__}",
            )
        return value

    raise HTTPException(status_code=422, detail=f"Unknown field type '{field_type}' for '{dotted_path}'")


def _load_live_yaml() -> dict:
    try:
        text = LIVE_YAML_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Live config file not found")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot read live config: {str(e)[:200]}")

    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=500, detail=f"Live config YAML parse error: {str(e)[:200]}")


class ConfigUpdateRequest(BaseModel):
    changes: Dict[str, Any]
    config_hash: str
    restart: bool = False


config_router = APIRouter(tags=["config"])


@config_router.get("/api/config")
async def get_config():
    live = _load_live_yaml()
    config_hash = _config_hash(live)
    override_keys = _compute_override_keys({}, live)
    validation_warnings = _validate_runtime_candidate(live)
    return {
        "merged": live,
        "overrides": live,
        "override_keys": override_keys,
        "schema": SCHEMA,
        "config_hash": config_hash,
        "validation_warnings": validation_warnings,
    }


@config_router.post("/api/config")
async def update_config(body: ConfigUpdateRequest):
    _check_rate_limit("config-update")

    changes = body.changes
    request_hash = body.config_hash
    restart = body.restart

    if not changes:
        raise HTTPException(status_code=422, detail="No changes provided")

    live = _load_live_yaml()
    current_hash = _config_hash(live)
    if request_hash != current_hash:
        raise HTTPException(
            status_code=409,
            detail="Config has been modified since you loaded it. Reload and try again.",
        )

    validated_changes: Dict[str, Any] = {}
    for dotted_path, value in changes.items():
        if dotted_path in FORBIDDEN_KEYS:
            raise HTTPException(
                status_code=403,
                detail=f"Field '{dotted_path}' cannot be modified via the API",
            )
        field_schema = SCHEMA.get(dotted_path)
        if field_schema is None:
            raise HTTPException(status_code=422, detail=f"Unknown config field: '{dotted_path}'")
        validated_changes[dotted_path] = _validate_value(dotted_path, value, field_schema)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = LIVE_YAML_PATH.parent / f"{LIVE_YAML_PATH.name}.backup.{timestamp}"
    try:
        if LIVE_YAML_PATH.exists():
            backup_path.write_text(LIVE_YAML_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info("config-update: backup written to %s", backup_path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {str(e)[:200]}")

    updated_live = deepcopy(live)
    changes_applied = []
    for dotted_path, value in validated_changes.items():
        old_value = _get_nested(updated_live, dotted_path)
        _set_nested(updated_live, dotted_path, value)
        changes_applied.append({"path": dotted_path, "old_value": old_value, "new_value": value})
        logger.info("config-update: %s: %r -> %r", dotted_path, old_value, value)

    validation_warnings = _validate_runtime_candidate(updated_live)

    new_yaml = yaml.dump(updated_live, default_flow_style=False, sort_keys=False)
    tmp_path = LIVE_YAML_PATH.parent / f".{LIVE_YAML_PATH.name}.tmp"
    try:
        tmp_path.write_text(new_yaml, encoding="utf-8")
        os.rename(str(tmp_path), str(LIVE_YAML_PATH))
    except OSError as e:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to write config: {str(e)[:200]}")

    try:
        roundtrip = yaml.safe_load(LIVE_YAML_PATH.read_text(encoding="utf-8"))
        if not isinstance(roundtrip, dict):
            raise ValueError("Round-trip parse did not produce a dict")
        validation_warnings = _validate_runtime_candidate(roundtrip)
    except Exception as e:
        logger.error("config-update: round-trip validation failed, restoring backup: %s", e)
        try:
            if backup_path.exists():
                os.rename(str(backup_path), str(LIVE_YAML_PATH))
        except OSError:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Config validation failed after write (backup restored): {str(e)[:200]}",
        )

    restarted = False
    if restart:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "restart", "pearlalgo-agent", "pearlalgo-api"],
                capture_output=True,
                timeout=15,
            )
            restarted = result.returncode == 0
            if not restarted:
                logger.warning(
                    "config-update: systemctl restart returned %d: %s",
                    result.returncode,
                    result.stderr.decode("utf-8", errors="replace")[:200],
                )
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("config-update: restart failed: %s", e)

    return {
        "ok": True,
        "changes_applied": changes_applied,
        "backup_path": str(backup_path),
        "restarted": restarted,
        "validation_warnings": validation_warnings,
    }
