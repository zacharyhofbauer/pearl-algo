"""
Service-level configuration loader.

Loads configuration from config.yaml for service intervals, circuit breaker,
alerts, data settings, signals, and performance tracking.

**Purpose**: This module handles service behavior configuration (how the service operates).

**When to use `load_service_config()`:**
- For service-level settings (intervals, circuit breaker, alerts)
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
    scan_interval = service_settings.get("status_update_interval", 1800)
    ```
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


def load_service_config(config_path: Optional[Path] = None) -> Dict:
    """
    Load service configuration from config.yaml.
    
    Args:
        config_path: Path to config.yaml (defaults to config/config.yaml)
        
    Returns:
        Dictionary with service configuration sections
    """
    if config_path is None:
        # Try to find config.yaml relative to project root
        project_root = Path(__file__).parent.parent.parent.parent
        config_path = project_root / "config" / "config.yaml"
    
    defaults = {
        "service": {
            "status_update_interval": 1800,
            "heartbeat_interval": 3600,
            "state_save_interval": 10,
        },
        "circuit_breaker": {
            "max_consecutive_errors": 10,
            "max_connection_failures": 10,
            "max_data_fetch_errors": 5,
        },
        "alerts": {
            "connection_failure_interval": 600,
            "data_quality_interval": 300,
        },
        "data": {
            "buffer_size": 100,
            "historical_hours": 2,
            "multitimeframe_5m_hours": 4,
            "multitimeframe_15m_hours": 12,
            "use_level2_data": True,
            "order_book_depth": 10,
            "order_book_analysis": True,
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
    
    if config_path and config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                config_data = yaml.safe_load(f) or {}
                
                # Merge config sections with defaults
                result = {}
                for section in defaults:
                    result[section] = {**defaults[section], **config_data.get(section, {})}
                
                return result
        except Exception as e:
            from pearlalgo.utils.logger import logger
            logger.warning(f"Could not load service config from {config_path}: {e}")
            return defaults
    
    return defaults




