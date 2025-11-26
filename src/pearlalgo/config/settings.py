from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def _load_config_file(path: str | Path | None) -> Dict[str, Any]:
    if not path:
        return {}
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    if path.suffix.lower() in {".json"}:
        return json.loads(path.read_text())
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ImportError("PyYAML is required to load YAML config files") from exc
        return yaml.safe_load(path.read_text()) or {}
    raise ValueError(f"Unsupported config file type: {path.suffix}")


class Settings(BaseSettings):
    """Centralized settings loaded from env plus optional config file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PEARLALGO_", extra="ignore")

    profile: str = Field(default="backtest")
    data_dir: str = Field(default="data")
    data_api_key: str | None = None
    vendor_api_key: str | None = None
    vendor_api_base: str | None = None
    broker_api_key: str | None = None
    broker_api_secret: str | None = None
    broker_base_url: str | None = None
    ib_enable: bool = False
    ib_host: str = "127.0.0.1"
    # Default to IB Gateway paper port; TWS default is 7497.
    ib_port: int = 4002
    ib_client_id: int = 1
    # Optional separate client id for market data to avoid clashes with brokers/orders.
    ib_data_client_id: int | None = None
    allow_live_trading: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_profile(cls: type[Self], profile: str | None = None, config_file: str | Path | None = None) -> Self:
        """
        Load settings from env with optional overrides from a config file.
        Precedence: explicit profile arg > config profile > env default.
        File values only fill missing env-derived values.
        """
        env_settings = cls()
        merged: Dict[str, Any] = env_settings.model_dump()

        file_data = _load_config_file(config_file)
        file_profile = (profile or file_data.get("profile") or env_settings.profile).lower()

        profiles_section = file_data.get("profiles", {})
        profile_values = profiles_section.get(file_profile, {})

        for key, val in {**file_data, **profile_values}.items():
            if key in merged and merged[key] is not None:
                continue
            merged[key] = val

        merged["profile"] = file_profile
        try:
            return cls(**merged)
        except ValidationError as exc:
            raise ValueError(f"Invalid settings: {exc}") from exc


def get_settings(profile: str | None = None, config_file: str | Path | None = None) -> Settings:
    """Public helper to load settings with profile/config file support."""
    return Settings.from_profile(profile=profile, config_file=config_file)


settings = get_settings()


def require_keys(settings: Settings, required: list[str]) -> None:
    """Raise if any required settings are missing/falsey."""
    missing = [k for k in required if not getattr(settings, k)]
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")
