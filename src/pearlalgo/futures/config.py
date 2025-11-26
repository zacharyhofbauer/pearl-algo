from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


CONFIG_PATHS = [
    Path("config/prop_profile.yaml"),
    Path("config/prop_profile.yml"),
    Path("config/prop_profile.json"),
]


@dataclass
class PropProfile:
    """
    Prop-style account constraints and per-symbol limits.
    """

    name: str = "default"
    starting_balance: float = 50000.0
    daily_loss_limit: float = 2500.0
    target_profit: float = 5000.0
    max_contracts_by_symbol: dict[str, int] = field(
        default_factory=lambda: {"ES": 2, "NQ": 2, "GC": 1}
    )
    tick_values_by_symbol: dict[str, float] = field(
        default_factory=lambda: {"ES": 50.0, "NQ": 20.0, "GC": 100.0}
    )

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "PropProfile":
        merged = {
            "name": data.get("name", "default"),
            "starting_balance": float(data.get("starting_balance", 50000.0)),
            "daily_loss_limit": float(data.get("daily_loss_limit", 2500.0)),
            "target_profit": float(data.get("target_profit", 5000.0)),
            "max_contracts_by_symbol": data.get("max_contracts_by_symbol", {}) or {},
            "tick_values_by_symbol": data.get("tick_values_by_symbol", {}) or {},
        }
        return cls(**merged)


def _load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if path.suffix.lower() in {".json"}:
        return json.loads(path.read_text())
    if path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise ImportError("PyYAML required to load YAML config")
        return yaml.safe_load(path.read_text()) or {}
    return {}


def load_profile(config_path: str | Path | None = None) -> PropProfile:
    """
    Load a PropProfile from YAML/JSON if present; fallback to defaults.
    """
    if config_path:
        data = _load_config_file(Path(config_path))
        if data:
            return PropProfile.from_mapping(data)

    for candidate in CONFIG_PATHS:
        data = _load_config_file(candidate)
        if data:
            return PropProfile.from_mapping(data)
    return PropProfile()
