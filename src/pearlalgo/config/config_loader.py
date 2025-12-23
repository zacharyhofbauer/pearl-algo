"""
Service-level configuration loader.

Loads configuration from config.yaml for service intervals, circuit breaker,
data settings, signals, and performance tracking.

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

from pathlib import Path
from typing import Any, Dict, Optional

from pearlalgo.config.config_file import load_config_yaml


# Default values for service configuration sections
_SERVICE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "service": {
        "status_update_interval": 1800,
        "heartbeat_interval": 3600,
        "state_save_interval": 10,
        # Cadence mode: "fixed" (start-to-start timing) or "sleep_after" (legacy)
        "cadence_mode": "fixed",
        # Dashboard observability (15m push)
        "pressure_lookback_bars": 24,   # ~2h on 5m bars
        "pressure_baseline_bars": 120,  # ~10h on 5m bars
        # Dashboard chart (hourly image)
        "dashboard_chart_lookback_hours": 48,  # show more context for key levels
        "dashboard_chart_timeframe": "auto",   # "auto" | "5m" | "15m" | "30m" | "1h"
        "dashboard_chart_max_bars": 420,       # cap candles for readability/Telegram
        "dashboard_chart_show_pressure": True, # show signed-volume pressure panel
    },
    "circuit_breaker": {
        "max_consecutive_errors": 10,
        "max_connection_failures": 10,
        "max_data_fetch_errors": 5,
    },
    "data": {
        "buffer_size": 100,
        "historical_hours": 2,
        "multitimeframe_5m_hours": 4,
        "multitimeframe_15m_hours": 12,
        # Multi-timeframe fetch caching (default OFF).
        # When enabled, 5m/15m history is refreshed on a TTL rather than every cycle.
        "enable_mtf_cache": False,
        "mtf_refresh_seconds_5m": 300,
        "mtf_refresh_seconds_15m": 900,
        # Default to Level 1 only unless explicitly enabled in config.yaml.
        # Most prop-firm feeds are Level 1; Level 2 requires additional entitlements.
        "use_level2_data": False,
        "order_book_depth": 10,
        "order_book_analysis": False,
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
}


def load_service_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load service configuration from config.yaml.
    
    Uses the unified config loader with environment variable substitution.
    
    Args:
        config_path: Path to config.yaml (defaults to config/config.yaml)
        
    Returns:
        Dictionary with service configuration sections merged with defaults
    """
    # Load raw config using unified loader
    config_data = load_config_yaml(config_path)
    
    # Merge config sections with defaults
    result = {}
    for section, defaults in _SERVICE_DEFAULTS.items():
        result[section] = {**defaults, **config_data.get(section, {})}
    
    return result






