"""
Infrastructure and environment-based configuration.

This module provides Pydantic-validated settings loaded from environment variables
for infrastructure and deployment wiring (IBKR connectivity).

**Purpose**: This module handles infrastructure configuration (how the system connects to external services).

**When to use `Settings` or `get_settings()`:**
- For infrastructure configuration (IBKR connection settings, environment variables)
- For deployment-specific settings (hosts, ports)
- For Pydantic-validated environment-based configuration
- For settings that vary by environment (development, staging, production)

**When to use `config_loader.py` instead:**
- For service behavior configuration (intervals, circuit breaker thresholds)
- For data fetching configuration (buffer sizes, thresholds)
- For signal generation settings (duplicate windows, thresholds)
- For performance tracking configuration

**When to use strategy config (`trading_bots/pearl_bot_auto.py` CONFIG):**
- For strategy-specific parameters (symbol, timeframe, risk parameters)
- For strategy behavior configuration (ATR multipliers, R:R ratios)

**Secret Management:**
    Secrets are loaded from ~/.config/pearlalgo/secrets.env with chmod 600 permissions.
    Non-sensitive configuration remains in .env in the project root.

    Secrets include: IBKR_USERNAME, IBKR_PASSWORD, API keys (GROQ, OPENAI, ANTHROPIC),
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PEARL_API_KEY

**Example usage:**
    ```python
    from pearlalgo.config.settings import get_settings

    settings = get_settings()
    ibkr_host = settings.ib_host
    ibkr_port = settings.ib_port
    ```
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default secrets file location
SECRETS_FILE_PATH = Path.home() / ".config" / "pearlalgo" / "secrets.env"

# Load secrets from secure location first, then project .env
# This allows secrets to be stored separately with restricted permissions
try:
    from dotenv import load_dotenv
    # Load secrets first (higher priority for sensitive values)
    secrets_path = os.getenv("PEARLALGO_SECRETS_FILE", str(SECRETS_FILE_PATH))
    if Path(secrets_path).exists():
        load_dotenv(secrets_path)
    # Then load project .env (non-sensitive config, won't override secrets)
    load_dotenv()
except ImportError:
    pass  # dotenv not required, but helpful


class Settings(BaseSettings):
    """Centralized infrastructure settings loaded from environment variables.

    This module is intentionally small. Trading/service behavior belongs in:
    - `config/config.yaml` (service + strategy defaults)
    - `pearlalgo.config.config_loader` and `pearlalgo.trading_bots.pearl_bot_auto.CONFIG`

    Precedence (highest → lowest) for IBKR connectivity:
    1) `IBKR_*` (compat)
    2) `PEARLALGO_IB_*` (namespaced)
    3) code defaults
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="PEARLALGO_", extra="ignore"
    )

    # IBKR - defaults imported from centralized defaults module
    # Import here to avoid circular imports during module load
    ib_host: str = "127.0.0.1"  # See config.defaults.IBKR_HOST
    # Default to IB Gateway paper port; TWS default is 7497.
    ib_port: int = 4002  # See config.defaults.IBKR_PORT
    ib_client_id: int = 1  # See config.defaults.IBKR_CLIENT_ID
    # Optional separate client id for market data to avoid clashes with brokers/orders.
    ib_data_client_id: int | None = None
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

    def __init__(self, **kwargs):
        """
        Override to normalize IBKR_* and PEARLALGO_* env vars.

        Precedence: IBKR_* > PEARLALGO_* > defaults
        """
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

        super().__init__(**kwargs)


def get_settings(
    profile: str | None = None, config_file: str | None = None
) -> Settings:
    """Public helper to load settings.

    `profile` / `config_file` are accepted for backward compatibility but are intentionally ignored
    in this codebase. Runtime configuration lives in `.env` + `config/config.yaml`.
    """
    _ = profile, config_file
    return Settings()


settings = get_settings()


def require_keys(settings: Settings, required: list[str]) -> None:
    """Raise if any required settings are missing/falsey."""
    missing = [k for k in required if not getattr(settings, k)]
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")
