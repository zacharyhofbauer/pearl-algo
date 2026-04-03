"""
Notification Queue Stub.

Telegram has been removed. This module preserves the public interface
(Priority, NotificationTier, NotificationQueue) so that callers in the
service layer don't need to be rewritten. All enqueue methods are no-ops.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Dict, Optional

from pearlalgo.utils.logger import logger


class Priority(IntEnum):
    """Notification priority levels (retained for callers)."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    MEDIUM = 2  # Legacy alias retained for older callers.
    LOW = 3


class NotificationTier(IntEnum):
    """Notification importance tiers (retained for callers)."""
    CRITICAL = 0
    IMPORTANT = 1
    DEBUG = 2


class NotificationQueue:
    """No-op notification queue (Telegram removed)."""

    def __init__(self, **kwargs):
        self.enabled = False
        self._stats: Dict[str, int] = {
            "enqueued": 0, "delivered": 0, "failed": 0,
            "dropped": 0, "retried": 0,
        }

    async def start(self) -> None:
        logger.info("Notification queue started (no-op, Telegram removed)")

    async def stop(self, timeout: float = 5.0) -> None:
        logger.info("Notification queue stopped: %s", self._stats)

    def get_stats(self) -> Dict[str, Any]:
        return {**self._stats, "pending": 0}

    # ── enqueue stubs (all no-ops) ──────────────────────────────────

    async def enqueue_entry(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_exit(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_status(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_enhanced_status(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_heartbeat(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_dashboard(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_startup(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_shutdown(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_circuit_breaker(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_data_quality(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_data_quality_alert(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_recovery(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_risk_warning(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_raw_message(self, *args, **kwargs) -> bool:
        return True

    async def enqueue_message(self, *args, **kwargs) -> bool:
        return True
