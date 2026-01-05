from __future__ import annotations

from typing import Any, Dict, Optional


def make_service_config_override(config_path: str, new_value: Any) -> Optional[Dict[str, Any]]:
    """Build a service_config_override dict for paths like `signals.*`."""
    path = str(config_path or "").strip()
    if not path.startswith("signals."):
        return None
    key = path.split("signals.", 1)[1]
    if not key:
        return None
    return {"signals": {key: new_value}}


def apply_nq_intraday_config_override(config: Any, config_path: str, new_value: Any) -> Any:
    """
    Apply a config_path override to an NQIntradayConfig instance (best-effort).

    This supports a small mapping of YAML-ish paths to NQIntradayConfig fields,
    plus direct field names.
    """
    path = str(config_path or "").strip()
    if not path:
        return config

    mapping = {
        # session.*
        "session.start_time": "start_time",
        "session.end_time": "end_time",
        # risk.*
        "risk.stop_loss_atr_multiplier": "stop_loss_atr_multiplier",
        "risk.take_profit_risk_reward": "take_profit_risk_reward",
        "risk.max_risk_per_trade": "max_risk_per_trade",
        "risk.max_position_size": "max_position_size",
        "risk.min_position_size": "min_position_size",
        "risk.stop_loss_ticks": "stop_loss_ticks",
        "risk.take_profit_ticks": "take_profit_ticks",
        # strategy.*
        "strategy.enable_dynamic_sizing": "enable_dynamic_sizing",
        "strategy.base_contracts": "base_contracts",
        "strategy.high_conf_contracts": "high_conf_contracts",
        "strategy.max_conf_contracts": "max_conf_contracts",
        "strategy.enabled_signals": "enabled_signals",
        "strategy.disabled_signals": "disabled_signals",
        # hud.*
        "hud.enabled": "hud_enabled",
        "hud.compact_labels": "hud_compact_labels",
        "hud.mobile_enhanced_fonts": "hud_mobile_enhanced_fonts",
    }

    attr = mapping.get(path)
    if not attr and "." not in path:
        # allow direct field names like stop_loss_ticks
        attr = path

    if not attr or not hasattr(config, attr):
        return config

    try:
        current = getattr(config, attr)
        if isinstance(current, bool):
            val = bool(new_value)
        elif isinstance(current, int):
            val = int(new_value)
        elif isinstance(current, float):
            val = float(new_value)
        elif isinstance(current, list):
            val = list(new_value) if isinstance(new_value, (list, tuple)) else [str(new_value)]
        else:
            val = new_value
        setattr(config, attr, val)
    except Exception:
        # Best-effort: ignore if coercion fails
        return config

    return config



