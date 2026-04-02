"""
Unified configuration file loader.

Provides a single source for loading runtime configuration YAML with
consistent environment variable substitution.

**Purpose**: This module is the canonical way to load the active runtime config.
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pearlalgo.config.migration import migrate_legacy_runtime_config
from pearlalgo.utils.dict_utils import deep_merge as _deep_merge


def _project_root() -> Path:
    """Return the repository root for config resolution."""
    return Path(__file__).parent.parent.parent.parent


def _canonical_live_config_path(project_root: Path) -> Path:
    """Return the canonical live runtime config path."""
    return project_root / "config" / "live" / "tradovate_paper.yaml"


def _legacy_base_config_path(project_root: Path) -> Path:
    """Return the legacy shared base config path."""
    return project_root / "config" / "base.yaml"


def _legacy_accounts_dir(project_root: Path) -> Path:
    """Return the legacy per-account overlay directory."""
    return project_root / "config" / "accounts"


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


def _load_yaml_file(path: Path, *, substitute_env: bool = True) -> Dict[str, Any]:
    """Load one YAML file with optional env substitution."""
    import yaml

    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if substitute_env:
        data = _substitute_env_vars(data)
    return data


def _resolve_default_config_source(
    project_root: Path,
    *,
    env_path: Optional[str] = None,
) -> Tuple[Optional[Path], Optional[Path]]:
    """Resolve the default runtime config source.

    Returns `(target_path, legacy_overlay_path)`.
    - `target_path` is used for explicit paths or the canonical live config.
    - `legacy_overlay_path` is used only for the compatibility fallback that
      deep-merges `config/base.yaml` with a single legacy account overlay.
    """
    canonical_live_path = _canonical_live_config_path(project_root)
    if env_path:
        return Path(env_path), None
    if canonical_live_path.exists():
        return canonical_live_path, None

    legacy_overlay_path: Optional[Path] = None
    accounts_dir = _legacy_accounts_dir(project_root)
    if accounts_dir.is_dir():
        candidates = [
            p for p in accounts_dir.iterdir()
            if p.suffix in (".yaml", ".yml")
            and not p.name.startswith(".")
            and "backup" not in p.name
        ]
        if len(candidates) == 1:
            legacy_overlay_path = candidates[0]
        elif len(candidates) > 1:
            try:
                from pearlalgo.utils.logger import logger
                logger.warning(
                    "PEARLALGO_CONFIG_PATH not set and multiple legacy account "
                    "configs found in %s: %s. Prefer config/live/tradovate_paper.yaml "
                    "or set PEARLALGO_CONFIG_PATH explicitly.",
                    accounts_dir,
                    [p.name for p in candidates],
                )
            except ImportError:
                pass

    if legacy_overlay_path is None:
        try:
            from pearlalgo.utils.logger import logger
            logger.warning(
                "No canonical live config found and no legacy overlay selected; "
                "falling back to base config only."
            )
        except ImportError:
            pass

    return None, legacy_overlay_path


def _load_legacy_merged_config(
    project_root: Path,
    legacy_overlay_path: Optional[Path],
    *,
    substitute_env: bool = True,
) -> Dict[str, Any]:
    """Load the compatibility fallback stack: base config plus optional overlay."""
    base_path = _legacy_base_config_path(project_root)
    base_config = _load_yaml_file(base_path, substitute_env=substitute_env) if base_path.exists() else {}
    overlay_config = (
        _load_yaml_file(legacy_overlay_path, substitute_env=substitute_env)
        if legacy_overlay_path and legacy_overlay_path.exists()
        else {}
    )
    if not base_config and not overlay_config:
        return {}
    return _deep_merge(base_config, overlay_config)


def load_config_yaml(
    config_path: Optional[Union[str, Path]] = None,
    *,
    substitute_env: bool = True,
    validate: bool = False,
) -> Dict[str, Any]:
    """
    Load runtime configuration with optional environment variable substitution.

    Resolution order:
    1) Explicit ``config_path`` / ``PEARLALGO_CONFIG_PATH`` when provided
    2) Canonical live config at ``config/live/tradovate_paper.yaml`` when present
    3) Legacy base + account overlay compatibility fallback
    
    Args:
        config_path: Explicit path to a runtime config file.
        substitute_env: Whether to substitute ${ENV_VAR} patterns. Default True.
        validate: Whether to validate config and log warnings. Default False.
                  Set to True during service startup to surface potential issues.
        
    Returns:
        Dictionary with full configuration data.
        Returns empty dict if file doesn't exist or fails to load.
    """
    project_root = _project_root()

    target_path: Optional[Path] = None
    legacy_overlay_path: Optional[Path] = None
    if config_path is None:
        target_path, legacy_overlay_path = _resolve_default_config_source(
            project_root,
            env_path=os.getenv("PEARLALGO_CONFIG_PATH"),
        )
    else:
        target_path = Path(config_path)

    try:
        if target_path is not None:
            resolved_target = target_path
            if not resolved_target.is_absolute():
                resolved_target = (project_root / resolved_target).resolve()
            if not resolved_target.exists():
                return {}

            if resolved_target.parent.name == "accounts":
                config_data = _load_legacy_merged_config(
                    project_root,
                    resolved_target,
                    substitute_env=substitute_env,
                )
            else:
                config_data = _load_yaml_file(
                    resolved_target,
                    substitute_env=substitute_env,
                )
        else:
            config_data = _load_legacy_merged_config(
                project_root,
                legacy_overlay_path,
                substitute_env=substitute_env,
            )
            if not config_data:
                return {}

        config_data = migrate_legacy_runtime_config(config_data)

        if validate:
            log_config_warnings(config_data)

        return config_data
    except Exception as e:
        # Use logger if available, otherwise just return empty
        try:
            from pearlalgo.utils.logger import logger
            logger.warning(f"Could not load config: {e}")
        except ImportError:
            pass
        return {}


def toggle_strategy_in_config(
    strategy_name: str,
    config_path: Optional[Union[str, Path]] = None,
) -> str:
    """Toggle a strategy on/off in a runtime config file.

    Reads the target runtime config (without env substitution, preserving raw ``${VAR}``
    tokens), flips the strategy between ``enabled_signals`` and
    ``disabled_signals``, creates a ``.yaml.backup``, and writes back.

    Args:
        strategy_name: Name of the strategy to toggle.
        config_path: Explicit path to a runtime config file. When ``None``,
            uses ``PEARLALGO_CONFIG_PATH`` or the canonical live config at
            ``config/live/tradovate_paper.yaml``.

    Returns:
        ``"enabled"`` or ``"disabled"`` — the new state of the strategy.

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    import shutil

    import yaml

    # Resolve path (mirrors load_config_yaml resolution)
    if config_path is None:
        env_path = os.getenv("PEARLALGO_CONFIG_PATH")
        if env_path:
            resolved = Path(env_path)
        else:
            project_root = _project_root()
            resolved = _canonical_live_config_path(project_root)
    else:
        resolved = Path(config_path)

    if not resolved.is_absolute():
        project_root = _project_root()
        resolved = (project_root / resolved).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Config file not found: {resolved}")

    # Read without env substitution — we write back as-is
    with open(resolved, "r") as f:
        config = yaml.safe_load(f) or {}

    if "strategy" not in config:
        config["strategy"] = {}

    strategy_config = config["strategy"]
    enabled_signals = list(strategy_config.get("enabled_signals") or [])
    disabled_signals = list(strategy_config.get("disabled_signals") or [])

    # Toggle the strategy
    if strategy_name in enabled_signals:
        enabled_signals.remove(strategy_name)
        if strategy_name not in disabled_signals:
            disabled_signals.append(strategy_name)
        action = "disabled"
    elif strategy_name in disabled_signals:
        disabled_signals.remove(strategy_name)
        if strategy_name not in enabled_signals:
            enabled_signals.append(strategy_name)
        action = "enabled"
    else:
        if strategy_name not in enabled_signals:
            enabled_signals.append(strategy_name)
        action = "enabled"

    strategy_config["enabled_signals"] = enabled_signals
    strategy_config["disabled_signals"] = disabled_signals
    config["strategy"] = strategy_config

    # Backup original config then write
    backup_path = resolved.with_suffix(".yaml.backup")
    shutil.copy2(resolved, backup_path)

    with open(resolved, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    return action


# Known top-level config sections (for unknown key detection)
_KNOWN_CONFIG_SECTIONS = frozenset({
    "account",
    "accounts",
    "audit",
    "symbol",
    "timeframe",
    "scan_interval",
    "session",
    "telegram",
    "telegram_ui",  # Home Card / dashboard UI formatting options
    "risk",
    "service",
    "circuit_breaker",
    # Trading/risk circuit breaker (loss-based risk controls + session filter)
    "trading_circuit_breaker",
    "data",
    "storage",
    "signals",
    "guardrails",
    "trailing_stop",
    "advanced_exits",
    "ml_filter",
    "composite_regime",
    "runner_mode",
    "performance",
    "virtual_pnl",
    "hud",
    "sessions",
    "auto_flat",
    # Strategy-level extensions
    "pearl_bot_auto",  # legacy compatibility overrides for strategy params
    "strategies",
    "indicators",
    "strategy",
    "strategy_variants",
    "swing_trading",
    "market_hours",
    # ATS execution layer
    "execution",
    # Repo knowledge index + RAG integration
    "knowledge",
    "challenge",
    # AI integrations
    "ai_chat",
    "ai_briefings",
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
