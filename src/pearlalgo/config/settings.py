from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self

# Load .env file manually to get IBKR_* vars
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not required, but helpful


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

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="PEARLALGO_", extra="ignore"
    )

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
    # Explicit dummy mode flag - when True, allows dummy data fallback
    # When False and IBKR connection fails, raises error instead of silent fallback
    dummy_mode: bool = Field(default=False, description="Enable dummy data mode (for testing/development)")
    
    @field_validator("ib_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate IBKR port is in reasonable range."""
        if not (1 <= v <= 65535):
            raise ValueError(f"IBKR port must be between 1 and 65535, got {v}")
        return v
    
    @field_validator("ib_client_id", "ib_data_client_id")
    @classmethod
    def validate_client_id(cls, v: int | None) -> int | None:
        """Validate IBKR client ID is in reasonable range."""
        if v is not None and not (0 <= v <= 100):
            raise ValueError(f"IBKR client ID must be between 0 and 100, got {v}")
        return v
    
    @field_validator("profile")
    @classmethod
    def validate_profile(cls, v: str) -> str:
        """Validate profile is one of allowed values."""
        allowed = {"paper", "live", "backtest", "dummy"}
        if v.lower() not in allowed:
            raise ValueError(
                f"Profile must be one of {allowed}, got {v}. "
                "See IBKR_CONNECTION_FIXES.md for help."
            )
        return v.lower()
    
    @model_validator(mode="after")
    def validate_ibkr_config(self) -> Self:
        """
        Validate IBKR configuration (now optional).
        
        Note: IBKR is deprecated. Use paper broker or other providers instead.
        IBKR configuration is only validated if explicitly using IBKR broker.
        """
        # IBKR is now optional - only validate if explicitly using IBKR
        # System works without IBKR using paper broker and other data providers
        if self.ib_enable:
            # Only validate if IBKR is explicitly enabled
            if not self.ib_host or self.ib_host == "":
                import warnings
                warnings.warn(
                    "IBKR is deprecated. Use paper broker instead. "
                    "See IBKR_DEPRECATION_NOTICE.md for migration guide.",
                    DeprecationWarning,
                    stacklevel=2
                )
        return self
    
    def __init__(self, **kwargs):
        """
        Override to normalize IBKR_* and PEARLALGO_* env vars.
        
        Precedence: IBKR_* > PEARLALGO_* > defaults
        """
        import os
        
        # Normalize IBKR_* and PEARLALGO_* env vars
        # IBKR_* takes precedence over PEARLALGO_*
        if "ib_host" not in kwargs:
            kwargs["ib_host"] = (
                os.getenv("IBKR_HOST") or 
                os.getenv("PEARLALGO_IB_HOST") or 
                kwargs.get("ib_host", "127.0.0.1")
            )
        
        if "ib_port" not in kwargs:
            port_str = os.getenv("IBKR_PORT") or os.getenv("PEARLALGO_IB_PORT")
            if port_str:
                kwargs["ib_port"] = int(port_str)
            elif "ib_port" not in kwargs:
                kwargs["ib_port"] = 4002
        
        if "ib_client_id" not in kwargs:
            client_id_str = (
                os.getenv("IBKR_CLIENT_ID") or 
                os.getenv("PEARLALGO_IB_CLIENT_ID")
            )
            if client_id_str:
                kwargs["ib_client_id"] = int(client_id_str)
            elif "ib_client_id" not in kwargs:
                kwargs["ib_client_id"] = 1
        
        if "ib_data_client_id" not in kwargs:
            data_client_id_str = (
                os.getenv("IBKR_DATA_CLIENT_ID") or 
                os.getenv("PEARLALGO_IB_DATA_CLIENT_ID")
            )
            if data_client_id_str:
                kwargs["ib_data_client_id"] = int(data_client_id_str)
        
        # Handle dummy_mode flag
        if "dummy_mode" not in kwargs:
            dummy_str = os.getenv("PEARLALGO_DUMMY_MODE", "").lower()
            kwargs["dummy_mode"] = dummy_str in ("true", "1", "yes", "on")
        
        super().__init__(**kwargs)

    @classmethod
    def from_profile(
        cls: type[Self],
        profile: str | None = None,
        config_file: str | Path | None = None,
    ) -> Self:
        """
        Load settings from env with optional overrides from a config file.
        Precedence: explicit profile arg > config profile > env default.
        File values only fill missing env-derived values.
        """
        # First create instance
        env_settings = cls()
        merged: Dict[str, Any] = env_settings.model_dump()

        file_data = _load_config_file(config_file)
        file_profile = (
            profile or file_data.get("profile") or env_settings.profile
        ).lower()

        profiles_section = file_data.get("profiles", {})
        profile_values = profiles_section.get(file_profile, {})

        # Merge file values, but don't override env-derived values
        for key, val in {**file_data, **profile_values}.items():
            if key in merged and merged[key] is not None:
                continue
            merged[key] = val

        merged["profile"] = file_profile
        
        # Override with IBKR_* env vars (these take precedence over PEARLALGO_*)
        # This ensures IBKR_* vars always win, even if set after config file load
        if "IBKR_HOST" in os.environ:
            merged["ib_host"] = os.getenv("IBKR_HOST")
        elif "PEARLALGO_IB_HOST" in os.environ and "ib_host" not in merged:
            merged["ib_host"] = os.getenv("PEARLALGO_IB_HOST")
            
        if "IBKR_PORT" in os.environ:
            merged["ib_port"] = int(os.getenv("IBKR_PORT"))
        elif "PEARLALGO_IB_PORT" in os.environ and "ib_port" not in merged:
            merged["ib_port"] = int(os.getenv("PEARLALGO_IB_PORT"))
            
        if "IBKR_CLIENT_ID" in os.environ:
            merged["ib_client_id"] = int(os.getenv("IBKR_CLIENT_ID"))
        elif "PEARLALGO_IB_CLIENT_ID" in os.environ and "ib_client_id" not in merged:
            merged["ib_client_id"] = int(os.getenv("PEARLALGO_IB_CLIENT_ID"))
            
        if "IBKR_DATA_CLIENT_ID" in os.environ:
            merged["ib_data_client_id"] = int(os.getenv("IBKR_DATA_CLIENT_ID"))
        elif "PEARLALGO_IB_DATA_CLIENT_ID" in os.environ and "ib_data_client_id" not in merged:
            merged["ib_data_client_id"] = int(os.getenv("PEARLALGO_IB_DATA_CLIENT_ID"))
        
        # Handle dummy_mode flag
        if "PEARLALGO_DUMMY_MODE" in os.environ:
            dummy_str = os.getenv("PEARLALGO_DUMMY_MODE", "").lower()
            merged["dummy_mode"] = dummy_str in ("true", "1", "yes", "on")
        
        try:
            return cls(**merged)
        except ValidationError as exc:
            raise ValueError(f"Invalid settings: {exc}") from exc


def get_settings(
    profile: str | None = None, config_file: str | Path | None = None
) -> Settings:
    """Public helper to load settings with profile/config file support."""
    return Settings.from_profile(profile=profile, config_file=config_file)


settings = get_settings()


def require_keys(settings: Settings, required: list[str]) -> None:
    """Raise if any required settings are missing/falsey."""
    missing = [k for k in required if not getattr(settings, k)]
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")
