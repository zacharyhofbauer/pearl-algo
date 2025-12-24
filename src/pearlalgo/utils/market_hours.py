"""
Market Hours - Check if futures markets are open.

Supports CME (ES, NQ, MES, MNQ) and NYMEX (CL, GC) futures markets.
Futures markets are generally 24/5 (Sunday 6pm ET - Friday 5pm ET).
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Iterable, Mapping, Optional

import pytz

from pearlalgo.utils.logger import logger

# Market timezones
ET = pytz.timezone("America/New_York")
UTC = pytz.UTC


class MarketHours:
    """
    Check if futures markets are open.

    Futures markets (CME, NYMEX) are generally:
    - Open: Sunday 6:00 PM ET - Friday 5:00 PM ET
    - Closed: Friday 5:00 PM ET - Sunday 6:00 PM ET
    - Also closed on certain holidays

    KNOWN LIMITATIONS:
    - Holiday coverage is intentionally incomplete (fixed-date list only)
    - Does not handle: Good Friday, Memorial Day, Labor Day, Thanksgiving
    - Does not handle early closes (e.g., day before holidays)
    
    For accurate holiday handling, consider integrating with CME holiday calendar
    or using the optional `holiday_overrides` parameter.
    """

    # Market holidays (approximate - check exchange calendar for exact dates)
    # NOTE: This is a STATIC list and does not account for:
    # - Variable holidays (Thanksgiving, Easter, etc.)
    # - Holiday observance rules (weekend → Monday)
    # - Early closes
    MARKET_HOLIDAYS = [
        # New Year's Day
        (1, 1),
        # Independence Day
        (7, 4),
        # Christmas
        (12, 25),
    ]

    def __init__(
        self,
        timezone_str: str = "America/New_York",
        holiday_overrides: Optional[list] = None,
        early_closes: Optional[dict] = None,
    ):
        """
        Initialize market hours checker.

        Args:
            timezone_str: Timezone string (default: America/New_York)
            holiday_overrides: Optional list of (year, month, day) tuples for
                               additional holidays to treat as closed.
                               Example: [(2025, 11, 27), (2025, 3, 28)]
            early_closes: Optional dict mapping (year, month, day) to close_hour (int).
                          Example: {(2025, 11, 26): 13} for 1 PM close
        """
        self.tz = pytz.timezone(timezone_str)
        self.holiday_overrides = set(holiday_overrides or [])
        self.early_closes = early_closes or {}

    def is_market_open(
        self, dt: Optional[datetime] = None, symbol: Optional[str] = None
    ) -> bool:
        """
        Check if market is open.

        Args:
            dt: Datetime to check (default: now)
            symbol: Trading symbol (optional, for symbol-specific hours)

        Returns:
            True if market is open, False otherwise
        """
        if dt is None:
            dt = datetime.now(UTC)
        else:
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = UTC.localize(dt)
            else:
                dt = dt.astimezone(UTC)

        # Convert to ET
        et_dt = dt.astimezone(self.tz)
        et_date = et_dt.date()
        et_time = et_dt.time()
        weekday = et_dt.weekday()  # 0=Monday, 6=Sunday

        # Check if it's a static holiday (month, day)
        if (et_date.month, et_date.day) in self.MARKET_HOLIDAYS:
            logger.debug(f"Market closed: Holiday ({et_date.month}/{et_date.day})")
            return False

        # Check if it's in the holiday overrides (year, month, day)
        if (et_date.year, et_date.month, et_date.day) in self.holiday_overrides:
            logger.debug(f"Market closed: Holiday override ({et_date.year}-{et_date.month}-{et_date.day})")
            return False

        # Check for early close
        early_close_hour = self.early_closes.get((et_date.year, et_date.month, et_date.day))
        if early_close_hour is not None:
            if et_time >= time(early_close_hour, 0):
                logger.debug(f"Market closed: Early close at {early_close_hour}:00 ET")
                return False

        # CME futures daily maintenance break (Mon–Thu 17:00–18:00 ET).
        # This primarily affects data freshness expectations and Error 354 interpretation.
        if 0 <= weekday <= 3 and time(17, 0) <= et_time < time(18, 0):
            logger.debug("Market closed: CME maintenance break (17:00-18:00 ET)")
            return False

        # Friday after 5 PM ET - market closed
        if weekday == 4 and et_time >= time(17, 0):  # Friday 5:00 PM
            logger.debug("Market closed: Friday after 5 PM ET")
            return False

        # Saturday - market closed
        if weekday == 5:  # Saturday
            logger.debug("Market closed: Saturday")
            return False

        # Sunday before 6 PM ET - market closed
        if weekday == 6 and et_time < time(18, 0):  # Sunday before 6:00 PM
            logger.debug("Market closed: Sunday before 6 PM ET")
            return False

        # Sunday 6 PM ET onwards - market open
        if weekday == 6 and et_time >= time(18, 0):  # Sunday 6:00 PM
            return True

        # Monday-Thursday - market open
        if 0 <= weekday <= 3:  # Monday-Thursday
            return True

        # Friday before 5 PM ET - market open
        if weekday == 4 and et_time < time(17, 0):  # Friday before 5:00 PM
            return True

        # Default: closed
        return False

    def get_next_market_open(self, dt: Optional[datetime] = None) -> datetime:
        """
        Get next market open time.

        Args:
            dt: Starting datetime (default: now)

        Returns:
            Next market open datetime (UTC)
        """
        if dt is None:
            dt = datetime.now(UTC)
        else:
            if dt.tzinfo is None:
                dt = UTC.localize(dt)
            else:
                dt = dt.astimezone(UTC)

        et_dt = dt.astimezone(self.tz)
        et_date = et_dt.date()
        et_time = et_dt.time()
        weekday = et_dt.weekday()

        # If market is open, return next day's open
        if self.is_market_open(dt):
            # Move to next day
            from datetime import timedelta

            et_dt = et_dt + timedelta(days=1)

        # Find next market open
        while not self.is_market_open(et_dt.astimezone(UTC)):
            from datetime import timedelta

            et_dt = et_dt + timedelta(hours=1)

        return et_dt.astimezone(UTC)

    def get_market_status(self, dt: Optional[datetime] = None) -> dict:
        """
        Get detailed market status.

        Args:
            dt: Datetime to check (default: now)

        Returns:
            Dictionary with market status information
        """
        if dt is None:
            dt = datetime.now(UTC)

        is_open = self.is_market_open(dt)
        et_dt = dt.astimezone(self.tz)

        status = {
            "is_open": is_open,
            "current_time_et": et_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "current_time_utc": dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "weekday": et_dt.strftime("%A"),
        }

        if not is_open:
            next_open = self.get_next_market_open(dt)
            status["next_open_utc"] = next_open.strftime("%Y-%m-%d %H:%M:%S %Z")
            next_open_et = next_open.astimezone(self.tz)
            status["next_open_et"] = next_open_et.strftime("%Y-%m-%d %H:%M:%S %Z")

        return status


# Global instance
_market_hours = None


_market_hours_holiday_overrides: set[tuple[int, int, int]] = set()
_market_hours_early_closes: dict[tuple[int, int, int], int] = {}


def configure_market_hours(
    *,
    holiday_overrides: Optional[Iterable[tuple[int, int, int]]] = None,
    early_closes: Optional[Mapping[tuple[int, int, int], int]] = None,
) -> None:
    """
    Configure the global MarketHours instance with optional overrides.

    This function exists to keep `utils` boundary-clean: config-driven behavior is wired
    by higher layers (e.g., `nq_agent`), then injected here.
    """
    global _market_hours, _market_hours_holiday_overrides, _market_hours_early_closes
    _market_hours_holiday_overrides = set(holiday_overrides or [])
    _market_hours_early_closes = dict(early_closes or {})
    _market_hours = None
    if _market_hours_holiday_overrides or _market_hours_early_closes:
        logger.info(
            "Configured market hours overrides: "
            f"{len(_market_hours_holiday_overrides)} holidays, {len(_market_hours_early_closes)} early closes"
        )


def get_market_hours() -> MarketHours:
    """
    Get global market hours instance.
    
    Market-hours overrides (holidays/early closes) must be configured by a higher layer
    (e.g., `pearlalgo.nq_agent.service`) via `configure_market_hours()`.
    """
    global _market_hours
    if _market_hours is None:
        holiday_overrides = _market_hours_holiday_overrides
        early_closes = _market_hours_early_closes

        _market_hours = MarketHours(
            holiday_overrides=list(holiday_overrides) if holiday_overrides else None,
            early_closes=dict(early_closes) if early_closes else None,
        )
    return _market_hours


def reset_market_hours() -> None:
    """
    Reset the global market hours instance.
    
    Useful for tests or when config changes require reloading.
    """
    global _market_hours
    _market_hours = None


def is_market_open(dt: Optional[datetime] = None) -> bool:
    """Convenience function to check if market is open."""
    return get_market_hours().is_market_open(dt)

