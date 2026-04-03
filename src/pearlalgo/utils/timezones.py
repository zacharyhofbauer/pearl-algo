"""Canonical timezone constants for PearlAlgo.

Import ``ET`` from this module instead of creating local ``ZoneInfo``
instances. This centralises future timezone-related changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Eastern Time — used throughout for market hours, timestamps, display
ET = ZoneInfo("America/New_York")

# UTC shorthand
UTC = timezone.utc


def now_et() -> datetime:
    """Return the current time as an aware datetime in Eastern Time."""
    return datetime.now(ET)
