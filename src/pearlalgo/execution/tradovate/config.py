"""
Tradovate configuration loaded from environment variables.

All secrets should be in ~/.config/pearlalgo/secrets.env or a .env file,
never committed to source control.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TradovateConfig:
    """Configuration for the Tradovate REST + WebSocket client."""

    # Credentials
    username: str = ""
    password: str = ""
    app_id: str = "PearlAlgo"
    app_version: str = "1.0"

    # API key (cid + sec) provided by Tradovate
    cid: int = 0
    sec: str = ""

    # Unique device identifier (persisted per installation)
    device_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Environment: "demo" or "live"
    env: str = "demo"

    # Derived base URLs
    @property
    def rest_url(self) -> str:
        if self.env == "live":
            return "https://live.tradovateapi.com/v1"
        return "https://demo.tradovateapi.com/v1"

    @property
    def ws_url(self) -> str:
        if self.env == "live":
            return "wss://live.tradovateapi.com/v1/websocket"
        return "wss://demo.tradovateapi.com/v1/websocket"

    @property
    def md_url(self) -> str:
        return "wss://md.tradovateapi.com/v1/websocket"

    # Token renewal interval in seconds (renew 15 min before 90 min expiry)
    token_renewal_seconds: int = 75 * 60  # 75 minutes

    # Account selection: if set, use this account name (e.g. "DEMO6315448")
    # otherwise auto-select the first demo account from /account/list
    account_name: Optional[str] = None

    @classmethod
    def from_env(cls) -> "TradovateConfig":
        """Load configuration from environment variables."""
        # Try to generate a stable device ID from hostname
        default_device_id = os.getenv(
            "TRADOVATE_DEVICE_ID",
            str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pearlalgo-{os.uname().nodename}")),
        )

        return cls(
            username=os.getenv("TRADOVATE_USERNAME", ""),
            password=os.getenv("TRADOVATE_PASSWORD", ""),
            app_id=os.getenv("TRADOVATE_APP_ID", "PearlAlgo"),
            app_version=os.getenv("TRADOVATE_APP_VERSION", "1.0"),
            cid=int(os.getenv("TRADOVATE_CID", "0")),
            sec=os.getenv("TRADOVATE_SEC", ""),
            device_id=default_device_id,
            env=os.getenv("TRADOVATE_ENV", "demo"),
            account_name=os.getenv("TRADOVATE_ACCOUNT_NAME") or None,
        )

    def validate(self) -> None:
        """Raise ValueError if required fields are missing."""
        missing = []
        if not self.username:
            missing.append("TRADOVATE_USERNAME")
        if not self.password:
            missing.append("TRADOVATE_PASSWORD")
        if not self.cid:
            missing.append("TRADOVATE_CID")
        if not self.sec:
            missing.append("TRADOVATE_SEC")
        if missing:
            raise ValueError(
                f"Missing Tradovate credentials: {', '.join(missing)}. "
                "Set them as environment variables or in secrets.env."
            )
