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

    Override via config/prop_profile.{yaml,json} or pass a path to load_profile().
    """

    name: str = "default"
    starting_balance: float = 50000.0
    daily_loss_limit: float = 2500.0
    target_profit: float = 5000.0
    risk_taper_threshold: float = 0.3  # fraction of loss limit remaining where sizing tapers
    max_trades: int | None = None  # Max trades per session; None = unlimited
    cooldown_minutes: int = 60  # Cooldown period after HARD_STOP or max_trades reached
    min_contract_size: int = 1  # Minimum contract size (futures don't allow fractional)
    max_contracts_by_symbol: dict[str, int] = field(
        default_factory=lambda: {"ES": 2, "NQ": 2, "GC": 1}
    )
    tick_values_by_symbol: dict[str, float] = field(
        # Dollar per minimum tick move; tune per broker spec if needed.
        default_factory=lambda: {"ES": 12.5, "NQ": 20.0, "GC": 10.0}
    )

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "PropProfile":
        merged = {**DEFAULT_PROP_PROFILE.__dict__, **(data or {})}
        return cls(
            name=merged.get("name", "default"),
            starting_balance=float(merged.get("starting_balance", DEFAULT_PROP_PROFILE.starting_balance)),
            daily_loss_limit=float(merged.get("daily_loss_limit", DEFAULT_PROP_PROFILE.daily_loss_limit)),
            target_profit=float(merged.get("target_profit", DEFAULT_PROP_PROFILE.target_profit)),
            risk_taper_threshold=float(
                merged.get("risk_taper_threshold", DEFAULT_PROP_PROFILE.risk_taper_threshold)
            ),
            max_trades=merged.get("max_trades", DEFAULT_PROP_PROFILE.max_trades),
            cooldown_minutes=int(merged.get("cooldown_minutes", DEFAULT_PROP_PROFILE.cooldown_minutes)),
            min_contract_size=int(merged.get("min_contract_size", DEFAULT_PROP_PROFILE.min_contract_size)),
            max_contracts_by_symbol=merged.get("max_contracts_by_symbol", DEFAULT_PROP_PROFILE.max_contracts_by_symbol)
            or {},
            tick_values_by_symbol=merged.get("tick_values_by_symbol", DEFAULT_PROP_PROFILE.tick_values_by_symbol)
            or {},
        )


DEFAULT_PROP_PROFILE = PropProfile()


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
    Load a PropProfile from YAML/JSON if present; fallback to DEFAULT_PROP_PROFILE.
    """
    if config_path:
        data = _load_config_file(Path(config_path))
        if data:
            return PropProfile.from_mapping(data)

    for candidate in CONFIG_PATHS:
        data = _load_config_file(candidate)
        if data:
            return PropProfile.from_mapping(data)
    return DEFAULT_PROP_PROFILE
