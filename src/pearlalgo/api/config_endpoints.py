"""
Config management API endpoints for the PearlAlgo settings dashboard.

Provides GET/POST endpoints for reading and writing YAML configuration
with validation, backup, atomic writes, and optional service restart.
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
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

BASE_YAML_PATH = PROJECT_ROOT / "config" / "base.yaml"
OVERRIDE_YAML_PATH = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"

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


# ---------------------------------------------------------------------------
# Forbidden keys — never writable via the API
# ---------------------------------------------------------------------------
FORBIDDEN_KEYS = frozenset({
    "execution.adapter",
    "virtual_pnl.enabled",
    "account.name",
})

# ---------------------------------------------------------------------------
# Schema registry
# ---------------------------------------------------------------------------
SCHEMA: Dict[str, Dict[str, Any]] = {
    # -- Trading (pearl_bot_auto) --
    "pearl_bot_auto.stop_loss_atr_mult": {
        "type": "number", "min": 0.1, "max": 10,
        "dangerous": False, "description": "Stop-loss ATR multiplier",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.take_profit_atr_mult": {
        "type": "number", "min": 0.1, "max": 10,
        "dangerous": False, "description": "Take-profit ATR multiplier",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.min_confidence": {
        "type": "number", "min": 0, "max": 1,
        "dangerous": False, "description": "Minimum confidence threshold",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.min_confidence_long": {
        "type": "number", "min": 0, "max": 1,
        "dangerous": False, "description": "Minimum confidence (long)",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.min_confidence_short": {
        "type": "number", "min": 0, "max": 1,
        "dangerous": False, "description": "Minimum confidence (short)",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.ema_fast": {
        "type": "number", "min": 1, "max": 50,
        "dangerous": False, "description": "EMA fast period",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.ema_slow": {
        "type": "number", "min": 1, "max": 100,
        "dangerous": False, "description": "EMA slow period",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.volatile_sl_mult": {
        "type": "number", "min": 0.1, "max": 5,
        "dangerous": False, "description": "Volatile regime SL multiplier",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.volatile_tp_mult": {
        "type": "number", "min": 0.1, "max": 5,
        "dangerous": False, "description": "Volatile regime TP multiplier",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.ranging_sl_mult": {
        "type": "number", "min": 0.1, "max": 5,
        "dangerous": False, "description": "Ranging regime SL multiplier",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.ranging_tp_mult": {
        "type": "number", "min": 0.1, "max": 5,
        "dangerous": False, "description": "Ranging regime TP multiplier",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.allow_vwap_cross_entries": {
        "type": "boolean",
        "dangerous": False, "description": "Allow VWAP cross entries",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.allow_vwap_retest_entries": {
        "type": "boolean",
        "dangerous": False, "description": "Allow VWAP retest entries",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.allow_trend_momentum_entries": {
        "type": "boolean",
        "dangerous": False, "description": "Allow trend momentum entries",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.allow_trend_breakout_entries": {
        "type": "boolean",
        "dangerous": False, "description": "Allow trend breakout entries",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.allow_orb_entries": {
        "type": "boolean",
        "dangerous": False, "description": "Allow opening range breakout entries",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.allow_vwap_2sd_entries": {
        "type": "boolean",
        "dangerous": False, "description": "Allow VWAP 2 std dev entries",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.vwap_std_dev": {
        "type": "number", "min": 0.5, "max": 3.0,
        "dangerous": False, "description": "VWAP standard deviation band",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.volume_ma_length": {
        "type": "number", "min": 5, "max": 100,
        "dangerous": False, "description": "Volume moving average length",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.sr_length": {
        "type": "number", "min": 10, "max": 500,
        "dangerous": False, "description": "Support/resistance lookback length",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.sr_atr_mult": {
        "type": "number", "min": 0.1, "max": 3.0,
        "dangerous": False, "description": "S/R ATR zone multiplier",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.trend_momentum_atr_mult": {
        "type": "number", "min": 0.1, "max": 3.0,
        "dangerous": False, "description": "Trend momentum ATR multiplier",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.trend_breakout_lookback_bars": {
        "type": "number", "min": 1, "max": 50,
        "dangerous": False, "description": "Trend breakout lookback bars",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.tbt_period": {
        "type": "number", "min": 1, "max": 50,
        "dangerous": False, "description": "TBT trendline period",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.tbt_trend_type": {
        "type": "select", "options": ["wicks", "bodies"],
        "dangerous": False, "description": "TBT trend type",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.adx_period": {
        "type": "number", "min": 5, "max": 50,
        "dangerous": False, "description": "ADX period",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.adx_trending_threshold": {
        "type": "number", "min": 10, "max": 50,
        "dangerous": False, "description": "ADX trending threshold",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },
    "pearl_bot_auto.adx_ranging_threshold": {
        "type": "number", "min": 5, "max": 40,
        "dangerous": False, "description": "ADX ranging threshold",
        "category": "Trading", "yaml_section": "pearl_bot_auto",
    },

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

    # -- Circuit Breaker --
    "trading_circuit_breaker.enabled": {
        "type": "boolean",
        "dangerous": True, "description": "Circuit breaker enabled",
        "category": "Circuit Breaker", "yaml_section": "trading_circuit_breaker",
    },
    "trading_circuit_breaker.mode": {
        "type": "select", "options": ["shadow", "warn_only", "enforce"],
        "dangerous": True, "description": "Circuit breaker mode",
        "category": "Circuit Breaker", "yaml_section": "trading_circuit_breaker",
    },
    "trading_circuit_breaker.max_consecutive_losses": {
        "type": "number", "min": 1, "max": 20,
        "dangerous": True, "description": "Max consecutive losses",
        "category": "Circuit Breaker", "yaml_section": "trading_circuit_breaker",
    },
    "trading_circuit_breaker.max_session_drawdown": {
        "type": "number", "min": 100, "max": 99999,
        "dangerous": True, "description": "Max session drawdown ($)",
        "category": "Circuit Breaker", "yaml_section": "trading_circuit_breaker",
    },
    "trading_circuit_breaker.max_daily_drawdown": {
        "type": "number", "min": 100, "max": 99999,
        "dangerous": True, "description": "Max daily drawdown ($)",
        "category": "Circuit Breaker", "yaml_section": "trading_circuit_breaker",
    },
    "trading_circuit_breaker.max_concurrent_positions": {
        "type": "number", "min": 1, "max": 10,
        "dangerous": True, "description": "Max concurrent positions (CB)",
        "category": "Circuit Breaker", "yaml_section": "trading_circuit_breaker",
    },
    "trading_circuit_breaker.enable_session_filter": {
        "type": "boolean",
        "dangerous": False, "description": "Enable session filter",
        "category": "Circuit Breaker", "yaml_section": "trading_circuit_breaker",
    },
    "trading_circuit_breaker.enable_direction_gating": {
        "type": "boolean",
        "dangerous": False, "description": "Enable direction gating",
        "category": "Circuit Breaker", "yaml_section": "trading_circuit_breaker",
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
    "trailing_stop.phases.0.activation_atr": {
        "type": "number", "min": 0.1, "max": 10,
        "dangerous": False, "description": "Breakeven: activation ATR",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },
    "trailing_stop.phases.0.trail_atr": {
        "type": "number", "min": 0, "max": 10,
        "dangerous": False, "description": "Breakeven: trail ATR (0 = entry)",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },
    "trailing_stop.phases.1.activation_atr": {
        "type": "number", "min": 0.1, "max": 10,
        "dangerous": False, "description": "Lock profit: activation ATR",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },
    "trailing_stop.phases.1.trail_atr": {
        "type": "number", "min": 0.1, "max": 10,
        "dangerous": False, "description": "Lock profit: trail ATR",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },
    "trailing_stop.phases.2.activation_atr": {
        "type": "number", "min": 0.1, "max": 10,
        "dangerous": False, "description": "Tight trail: activation ATR",
        "category": "Trailing Stop", "yaml_section": "trailing_stop",
    },
    "trailing_stop.phases.2.trail_atr": {
        "type": "number", "min": 0.1, "max": 10,
        "dangerous": False, "description": "Tight trail: trail ATR",
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
        "category": "Advanced Exits", "yaml_section": "advanced_exits",
    },
    "advanced_exits.quick_exit.min_duration_minutes": {
        "type": "number", "min": 1, "max": 120,
        "dangerous": False, "description": "Quick exit min duration (min)",
        "category": "Advanced Exits", "yaml_section": "advanced_exits",
    },
    "advanced_exits.quick_exit.max_mfe_threshold": {
        "type": "number", "min": 1, "max": 200,
        "dangerous": False, "description": "Quick exit max MFE threshold",
        "category": "Advanced Exits", "yaml_section": "advanced_exits",
    },
    "advanced_exits.quick_exit.min_mae_threshold": {
        "type": "number", "min": 1, "max": 200,
        "dangerous": False, "description": "Quick exit min MAE threshold",
        "category": "Advanced Exits", "yaml_section": "advanced_exits",
    },
    "advanced_exits.time_based_exit.enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Time-based exit enabled",
        "category": "Advanced Exits", "yaml_section": "advanced_exits",
    },
    "advanced_exits.time_based_exit.min_duration_minutes": {
        "type": "number", "min": 1, "max": 120,
        "dangerous": False, "description": "Time-based exit min duration (min)",
        "category": "Advanced Exits", "yaml_section": "advanced_exits",
    },
    "advanced_exits.time_based_exit.min_profit_threshold": {
        "type": "number", "min": 1, "max": 500,
        "dangerous": False, "description": "Time-based exit min profit threshold",
        "category": "Advanced Exits", "yaml_section": "advanced_exits",
    },
    "advanced_exits.time_based_exit.take_percentage": {
        "type": "number", "min": 0.1, "max": 1.0,
        "dangerous": False, "description": "Time-based exit take percentage",
        "category": "Advanced Exits", "yaml_section": "advanced_exits",
    },
    "advanced_exits.stop_optimization.enabled": {
        "type": "boolean",
        "dangerous": False, "description": "Stop optimization enabled",
        "category": "Advanced Exits", "yaml_section": "advanced_exits",
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _get_nested(d: dict, dotted_path: str, default: Any = None) -> Any:
    """Get a value from a nested dict using dotted path notation."""
    keys = dotted_path.split(".")
    current = d
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _set_nested(d: dict, dotted_path: str, value: Any) -> None:
    """Set a value in a nested dict using dotted path notation, creating intermediate dicts."""
    keys = dotted_path.split(".")
    current = d
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def _compute_override_keys(base: dict, override: dict, prefix: str = "") -> List[str]:
    """Return list of dotted paths where override differs from base."""
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
    """Compute SHA-256 hash of the merged config as YAML string."""
    yaml_str = yaml.dump(merged, default_flow_style=False, sort_keys=True)
    return hashlib.sha256(yaml_str.encode("utf-8")).hexdigest()


def _validate_value(dotted_path: str, value: Any, field_schema: Dict[str, Any]) -> Any:
    """Validate and coerce a value against its schema definition. Returns the validated value."""
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
            raise HTTPException(
                status_code=422,
                detail=f"Field '{dotted_path}' must be a number, got boolean",
            )
        if not isinstance(value, (int, float)):
            raise HTTPException(
                status_code=422,
                detail=f"Field '{dotted_path}' must be a number, got {type(value).__name__}",
            )
        min_val = field_schema.get("min")
        max_val = field_schema.get("max")
        if min_val is not None and value < min_val:
            raise HTTPException(
                status_code=422,
                detail=f"Field '{dotted_path}' value {value} is below minimum {min_val}",
            )
        if max_val is not None and value > max_val:
            raise HTTPException(
                status_code=422,
                detail=f"Field '{dotted_path}' value {value} is above maximum {max_val}",
            )
        return value

    if field_type == "select":
        options = field_schema.get("options", [])
        if value not in options:
            raise HTTPException(
                status_code=422,
                detail=f"Field '{dotted_path}' must be one of {options}, got '{value}'",
            )
        return value

    if field_type == "text":
        if not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail=f"Field '{dotted_path}' must be a string, got {type(value).__name__}",
            )
        return value

    raise HTTPException(status_code=422, detail=f"Unknown field type '{field_type}' for '{dotted_path}'")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ConfigUpdateRequest(BaseModel):
    changes: Dict[str, Any]
    config_hash: str
    restart: bool = False


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
config_router = APIRouter(tags=["config"])


@config_router.get("/api/config")
async def get_config():
    """Read and merge base + override YAML configs, returning merged values and schema."""
    try:
        base_text = BASE_YAML_PATH.read_text(encoding="utf-8")
        base = yaml.safe_load(base_text) or {}
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Base config file not found")
    except yaml.YAMLError as e:
        raise HTTPException(status_code=500, detail=f"Base config YAML parse error: {str(e)[:200]}")

    try:
        override_text = OVERRIDE_YAML_PATH.read_text(encoding="utf-8")
        overrides = yaml.safe_load(override_text) or {}
    except FileNotFoundError:
        overrides = {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=500, detail=f"Override config YAML parse error: {str(e)[:200]}")

    merged = _deep_merge(base, overrides)
    override_keys = _compute_override_keys(base, overrides)
    ch = _config_hash(merged)

    return {
        "merged": merged,
        "overrides": overrides,
        "override_keys": override_keys,
        "schema": SCHEMA,
        "config_hash": ch,
    }


@config_router.post("/api/config")
async def update_config(body: ConfigUpdateRequest):
    """
    Apply config changes to the override YAML file with validation, backup, and atomic write.
    """
    _check_rate_limit("config-update")

    changes = body.changes
    request_hash = body.config_hash
    restart = body.restart

    if not changes:
        raise HTTPException(status_code=422, detail="No changes provided")

    # --- Load current config to verify hash ---
    try:
        base_text = BASE_YAML_PATH.read_text(encoding="utf-8")
        base = yaml.safe_load(base_text) or {}
    except (FileNotFoundError, yaml.YAMLError) as e:
        raise HTTPException(status_code=500, detail=f"Cannot read base config: {str(e)[:200]}")

    try:
        override_text = OVERRIDE_YAML_PATH.read_text(encoding="utf-8")
        overrides = yaml.safe_load(override_text) or {}
    except FileNotFoundError:
        overrides = {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=500, detail=f"Cannot read override config: {str(e)[:200]}")

    merged = _deep_merge(base, overrides)
    current_hash = _config_hash(merged)

    if request_hash != current_hash:
        raise HTTPException(
            status_code=409,
            detail="Config has been modified since you loaded it. Reload and try again.",
        )

    # --- Validate all changes ---
    validated_changes: Dict[str, Any] = {}
    for dotted_path, value in changes.items():
        # Check forbidden keys
        if dotted_path in FORBIDDEN_KEYS:
            raise HTTPException(
                status_code=403,
                detail=f"Field '{dotted_path}' cannot be modified via the API",
            )

        # Check schema exists
        field_schema = SCHEMA.get(dotted_path)
        if field_schema is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown config field: '{dotted_path}'",
            )

        # Validate value
        validated_value = _validate_value(dotted_path, value, field_schema)
        validated_changes[dotted_path] = validated_value

    # --- Backup current override file ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = OVERRIDE_YAML_PATH.parent / f"{OVERRIDE_YAML_PATH.name}.backup.{timestamp}"
    try:
        if OVERRIDE_YAML_PATH.exists():
            backup_path.write_text(
                OVERRIDE_YAML_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            logger.info("config-update: backup written to %s", backup_path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {str(e)[:200]}")

    # --- Apply changes to the override dict ---
    updated_overrides = deepcopy(overrides)
    changes_applied = []
    for dotted_path, value in validated_changes.items():
        old_value = _get_nested(updated_overrides, dotted_path)
        _set_nested(updated_overrides, dotted_path, value)
        changes_applied.append({
            "path": dotted_path,
            "old_value": old_value,
            "new_value": value,
        })
        logger.info("config-update: %s: %r -> %r", dotted_path, old_value, value)

    # --- Atomic write ---
    new_yaml = yaml.dump(updated_overrides, default_flow_style=False, sort_keys=False)
    tmp_path = OVERRIDE_YAML_PATH.parent / f".{OVERRIDE_YAML_PATH.name}.tmp"
    try:
        tmp_path.write_text(new_yaml, encoding="utf-8")
        os.rename(str(tmp_path), str(OVERRIDE_YAML_PATH))
    except OSError as e:
        # Clean up tmp file on failure
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to write config: {str(e)[:200]}")

    # --- Validate round-trip ---
    try:
        roundtrip = yaml.safe_load(OVERRIDE_YAML_PATH.read_text(encoding="utf-8"))
        if not isinstance(roundtrip, dict):
            raise ValueError("Round-trip parse did not produce a dict")
    except Exception as e:
        # Restore from backup
        logger.error("config-update: round-trip validation failed, restoring backup: %s", e)
        try:
            if backup_path.exists():
                os.rename(str(backup_path), str(OVERRIDE_YAML_PATH))
        except OSError:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Config validation failed after write (backup restored): {str(e)[:200]}",
        )

    # --- Optional restart ---
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
    }
