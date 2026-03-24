"""
OpenClaw Guard — interface to the OpenClaw AI agent on the Mac gateway.

OpenClaw replaces the old autonomous ML/CB layer (XGBoost, Thompson Sampling,
consecutive-loss/drawdown circuit breaker) as the judgment layer for PearlAlgo.

OpenClaw runs on the Mac gateway and communicates via HTTP.  This module
provides a lightweight health-check / status interface so the API server
and signal handler can report OpenClaw availability.

NOTE: OpenClaw does NOT gate signals inside px-core.  It runs its own
decision loop on the gateway side.  This guard simply tracks whether the
OpenClaw node is reachable and healthy for observability / dashboard display.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class OpenClawStatus:
    """Snapshot of OpenClaw agent health."""
    reachable: bool = False
    healthy: bool = False
    last_check: Optional[str] = None
    last_decision: Optional[str] = None
    version: Optional[str] = None
    uptime_seconds: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reachable": self.reachable,
            "healthy": self.healthy,
            "last_check": self.last_check,
            "last_decision": self.last_decision,
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
            "error": self.error,
        }


class OpenClawGuard:
    """
    Lightweight interface to the OpenClaw AI agent.

    Responsibilities:
    - Track whether OpenClaw is reachable (health endpoint)
    - Expose status for /api/state and dashboards
    - Does NOT gate signals — OpenClaw decides on the gateway side
    """

    def __init__(self, *, openclaw_url: Optional[str] = None, config: dict = None):
        """
        Args:
            openclaw_url: Base URL of the OpenClaw agent (e.g. http://mac-gateway:8100).
                          If None, status is reported as "not_configured".
            config: Legacy config dict (ignored, kept for compat).
        """
        self._url = openclaw_url
        self._status = OpenClawStatus()
        self._configured = openclaw_url is not None
        self.enabled = True
        self.mode = "openclaw"

        if self._configured:
            logger.info(f"OpenClawGuard initialized: url={openclaw_url}")
        else:
            logger.info("OpenClawGuard initialized: not configured (no URL)")

    @property
    def is_configured(self) -> bool:
        return self._configured

    @property
    def is_healthy(self) -> bool:
        return self._status.healthy

    def check_signal(self, signal: dict) -> dict:
        """Passthrough — OpenClaw decides on the gateway side."""
        return {"approved": True, "reason": "openclaw_managed", "score": 1.0}

    def get_status(self) -> Dict[str, Any]:
        """Return current OpenClaw status for API/dashboard."""
        return {
            "configured": self._configured,
            "mode": self.mode,
            "enabled": self.enabled,
            **self._status.to_dict(),
        }

    async def check_health(self) -> OpenClawStatus:
        """Ping the OpenClaw health endpoint (non-blocking).

        Updates internal status and returns it.
        """
        if not self._configured or not self._url:
            self._status = OpenClawStatus(
                reachable=False,
                healthy=False,
                last_check=datetime.now(timezone.utc).isoformat(),
                error="not_configured",
            )
            return self._status

        import aiohttp

        try:
            url = f"{self._url.rstrip('/')}/health"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._status = OpenClawStatus(
                            reachable=True,
                            healthy=bool(data.get("healthy", True)),
                            last_check=datetime.now(timezone.utc).isoformat(),
                            last_decision=data.get("last_decision"),
                            version=data.get("version"),
                            uptime_seconds=data.get("uptime_seconds"),
                        )
                    else:
                        self._status = OpenClawStatus(
                            reachable=True,
                            healthy=False,
                            last_check=datetime.now(timezone.utc).isoformat(),
                            error=f"http_{resp.status}",
                        )
        except Exception as e:
            self._status = OpenClawStatus(
                reachable=False,
                healthy=False,
                last_check=datetime.now(timezone.utc).isoformat(),
                error=str(e)[:120],
            )
            logger.debug(f"OpenClaw health check failed: {e}")

        return self._status
