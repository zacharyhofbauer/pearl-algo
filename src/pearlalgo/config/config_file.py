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
from typing import Any, Dict, Optional, Union


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
) -> Dict[str, Any]:
    """
    Load configuration from config.yaml with optional environment variable substitution.
    
    Args:
        config_path: Path to config.yaml. Defaults to config/config.yaml relative to project root.
        substitute_env: Whether to substitute ${ENV_VAR} patterns. Default True.
        
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


