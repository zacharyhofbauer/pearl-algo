"""
Unified configuration file loader.

Provides a single source for loading config/config.yaml with 
consistent environment variable substitution.

**Purpose**: This module is the canonical way to load the config.yaml file.
All other configuration loaders should use this module to get raw config data.

**Environment variable substitution**:
- Values like `${ENV_VAR}` are replaced with the environment variable value
- Default values are supported: `${ENV_VAR:default_value}`
- If env var is not set and no default provided, the original string is kept

**Config validation**:
- Warns about string booleans/ints from env substitution (e.g., "true" instead of true)
- Warns about unknown top-level config keys
- Does NOT fail startup - only logs warnings for awareness

**Usage**:
    ```python
    from pearlalgo.config.config_file import load_config_yaml
    
    # Load full config with env substitution
    config = load_config_yaml()
    
    # Access sections
    telegram_config = config.get("telegram", {})
    risk_config = config.get("risk", {})
    ```
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


def _substitute_env_vars(value: Any) -> Any:
    """
    Recursively substitute ${ENV_VAR} and ${ENV_VAR:default} patterns.
    
    Args:
        value: Any value (string, dict, list, or primitive)
        
    Returns:
        Value with environment variables substituted
    """
    if isinstance(value, str):
        # Pattern: ${VAR_NAME} or ${VAR_NAME:default_value}
        pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'
        
        def replace_env(match):
            env_var = match.group(1)
            default = match.group(2)  # None if no default specified
            env_value = os.getenv(env_var)
            if env_value is not None:
                return env_value
            if default is not None:
                return default
            # If no env var and no default, keep original (for debugging)
            return match.group(0)
        
        return re.sub(pattern, replace_env, value)
    
    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    
    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    
    else:
        return value


def load_config_yaml(
    config_path: Optional[Union[str, Path]] = None,
    *,
    substitute_env: bool = True,
    validate: bool = False,
) -> Dict[str, Any]:
    """
    Load configuration from config.yaml with optional environment variable substitution.
    
    Args:
        config_path: Path to config.yaml. Defaults to config/config.yaml relative to project root.
        substitute_env: Whether to substitute ${ENV_VAR} patterns. Default True.
        validate: Whether to validate config and log warnings. Default False.
                  Set to True during service startup to surface potential issues.
        
    Returns:
        Dictionary with full configuration data.
        Returns empty dict if file doesn't exist or fails to load.
    """
    if config_path is None:
        # Find project root (4 levels up from this file: config_file.py -> config -> pearlalgo -> src -> project)
        project_root = Path(__file__).parent.parent.parent.parent
        config_path = project_root / "config" / "config.yaml"
    else:
        config_path = Path(config_path)
    
    if not config_path.exists():
        return {}
    
    try:
        import yaml
        with open(config_path) as f:
            config_data = yaml.safe_load(f) or {}
        
        if substitute_env:
            config_data = _substitute_env_vars(config_data)
        
        if validate:
            log_config_warnings(config_data)
        
        return config_data
    
    except Exception as e:
        # Use logger if available, otherwise just return empty
        try:
            from pearlalgo.utils.logger import logger
            logger.warning(f"Could not load config from {config_path}: {e}")
        except ImportError:
            pass
        return {}


@lru_cache(maxsize=1)
def get_config_yaml() -> Dict[str, Any]:
    """
    Get cached configuration data.
    
    This function caches the result of load_config_yaml() for repeated calls.
    Use load_config_yaml() directly if you need to reload the config.
    
    Returns:
        Cached dictionary with full configuration data.
    """
    return load_config_yaml()


def clear_config_cache() -> None:
    """Clear the cached configuration. Useful for testing."""
    get_config_yaml.cache_clear()


# Known top-level config sections (for unknown key detection)
_KNOWN_CONFIG_SECTIONS = frozenset({
    "symbol",
    "timeframe",
    "scan_interval",
    "session",
    "telegram",
    "telegram_ui",  # Home Card / dashboard UI formatting options
    "risk",
    "service",
    "circuit_breaker",
    "data",
    "storage",
    "signals",
    "performance",
    "virtual_pnl",
    "hud",
    "sessions",
    # Strategy-level extensions
    "indicators",
    "prop_firm",
    "strategy",
    "strategy_variants",
    "trailing_stop",
    "swing_trading",
    "market_hours",
    # ATS execution + learning layers (kept separate from strategy logic)
    "execution",
    "learning",
    # Adaptive risk management (stops/sizing/ML filter)
    "adaptive_stops",
    "adaptive_sizing",
    "ml_filter",
    "drift_guard",
    # LLM features (signal annotation, risk checks, post-mortems, tuning)
    # 50k challenge tracker
    "challenge",
    # PEARL automated bots (formerly lux_algo_bots)
    "pearl_bots",
    # Backward compatibility (deprecated)
    "lux_algo_bots",
})

# Config keys expected to be specific types after env substitution
# Format: (section, key, expected_type_name)
_TYPE_EXPECTATIONS: List[Tuple[str, str, str]] = [
    ("telegram", "enabled", "bool"),
    ("virtual_pnl", "enabled", "bool"),
    ("hud", "enabled", "bool"),
    ("hud", "show_rr_box", "bool"),
    ("hud", "show_sessions", "bool"),
    ("hud", "show_session_names", "bool"),
    ("hud", "show_session_oc", "bool"),
    ("hud", "show_session_tick_range", "bool"),
    ("hud", "show_session_average", "bool"),
    ("hud", "show_supply_demand", "bool"),
    ("hud", "show_power_channel", "bool"),
    ("hud", "show_tbt_targets", "bool"),
    ("hud", "show_key_levels", "bool"),
    ("hud", "show_right_labels", "bool"),
    ("hud", "show_rsi", "bool"),
    ("service", "status_update_interval", "int"),
    ("service", "heartbeat_interval", "int"),
    ("service", "state_save_interval", "int"),
    ("data", "buffer_size", "int"),
    ("data", "historical_hours", "int"),
    ("storage", "sqlite_enabled", "bool"),
    ("signals", "duplicate_window_seconds", "int"),
    ("risk", "max_risk_per_trade", "float"),
    ("risk", "max_drawdown", "float"),
    ("risk", "stop_loss_atr_multiplier", "float"),
    ("risk", "take_profit_risk_reward", "float"),
    ("signals", "min_confidence", "float"),
    ("signals", "min_risk_reward", "float"),
]


def _is_string_bool(value: Any) -> bool:
    """Check if a value is a string that looks like a boolean."""
    if not isinstance(value, str):
        return False
    return value.lower() in ("true", "false", "yes", "no", "on", "off", "1", "0")


def _is_string_number(value: Any) -> bool:
    """Check if a value is a string that looks like a number."""
    if not isinstance(value, str):
        return False
    try:
        float(value)
        return True
    except ValueError:
        return False


def validate_config(config: Dict[str, Any], *, warn_unknown: bool = True) -> List[str]:
    """
    Validate configuration and return a list of warning messages.
    
    This function does NOT raise exceptions - it only identifies potential issues
    for operator awareness. The service will still start even with warnings.
    
    Checks for:
    1. Unknown top-level config sections (possible typos)
    2. String booleans (e.g., "true" instead of true) from env substitution
    3. String numbers (e.g., "100" instead of 100) from env substitution
    
    Args:
        config: Configuration dictionary to validate
        warn_unknown: Whether to warn about unknown top-level keys
        
    Returns:
        List of warning messages (empty if no issues found)
    """
    warnings: List[str] = []
    
    # Check for unknown top-level keys
    if warn_unknown:
        unknown_keys = set(config.keys()) - _KNOWN_CONFIG_SECTIONS
        for key in sorted(unknown_keys):
            warnings.append(
                f"Unknown config section '{key}' - possible typo? "
                f"Known sections: {', '.join(sorted(_KNOWN_CONFIG_SECTIONS))}"
            )
    
    # Check for type mismatches (string bools/numbers from env substitution)
    for section, key, expected_type in _TYPE_EXPECTATIONS:
        section_data = config.get(section, {})
        if not isinstance(section_data, dict):
            continue
        value = section_data.get(key)
        if value is None:
            continue
        
        if expected_type == "bool":
            if _is_string_bool(value):
                warnings.append(
                    f"Config {section}.{key}=\"{value}\" is a string that looks like a boolean. "
                    f"If set via ${{ENV_VAR}}, YAML will treat it as a string. "
                    f"Consider using ${{ENV_VAR:true}} or ${{ENV_VAR:false}} for clarity."
                )
        elif expected_type in ("int", "float"):
            if _is_string_number(value):
                warnings.append(
                    f"Config {section}.{key}=\"{value}\" is a string that looks like a number. "
                    f"If set via ${{ENV_VAR}}, YAML will treat it as a string. "
                    f"Some code may handle this, but explicit typing is safer."
                )
    
    return warnings


def log_config_warnings(config: Dict[str, Any]) -> None:
    """
    Validate config and log any warnings.
    
    This is a convenience function that validates the config and logs
    any warnings using the centralized logger. Safe to call even if
    the logger isn't fully configured yet.
    
    Args:
        config: Configuration dictionary to validate
    """
    warnings = validate_config(config)
    if not warnings:
        return
    
    try:
        from pearlalgo.utils.logger import logger
        for warning in warnings:
            logger.warning(f"Config validation: {warning}")
    except ImportError:
        # Logger not available, just print to stderr
        import sys
        for warning in warnings:
            print(f"[CONFIG WARNING] {warning}", file=sys.stderr)
