"""
Market Hours - Check if futures markets are open.

Supports CME (ES, NQ, MES, MNQ) and NYMEX (CL, GC) futures markets.
Futures markets are generally 24/5 (Sunday 6pm ET - Friday 5pm ET).
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Optional

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
    """

    # Market holidays (approximate - check exchange calendar for exact dates)
    MARKET_HOLIDAYS = [
        # New Year's Day
        (1, 1),
        # Independence Day
        (7, 4),
        # Thanksgiving (4th Thursday of November)
        # Christmas
        (12, 25),
    ]

    def __init__(self, timezone_str: str = "America/New_York"):
        """
        Initialize market hours checker.

        Args:
            timezone_str: Timezone string (default: America/New_York)
        """
        self.tz = pytz.timezone(timezone_str)

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

        # Check if it's a holiday
        if (et_date.month, et_date.day) in self.MARKET_HOLIDAYS:
            logger.debug(f"Market closed: Holiday ({et_date.month}/{et_date.day})")
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


def get_market_hours() -> MarketHours:
    """Get global market hours instance."""
    global _market_hours
    if _market_hours is None:
        _market_hours = MarketHours()
    return _market_hours


def is_market_open(dt: Optional[datetime] = None) -> bool:
    """Convenience function to check if market is open."""
    return get_market_hours().is_market_open(dt)

