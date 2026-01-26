"""
Market Hours - Check if futures markets are open.

Supports CME (ES, NQ, MES, MNQ) and NYMEX (CL, GC) futures markets.
Futures markets are generally 24/5 (Sunday 6pm ET - Friday 5pm ET).
"""

from __future__ import annotations

import calendar
from datetime import datetime, time, timedelta, date
from typing import Iterable, Mapping, Optional, Set, Dict, Tuple

import pytz

from pearlalgo.utils.logger import logger

# Market timezones
ET = pytz.timezone("America/New_York")
UTC = pytz.UTC


# ============================================================================
# HOLIDAY CALCULATION HELPERS
# ============================================================================

def _get_nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """
    Get the nth occurrence of a weekday in a month.
    
    Args:
        year: Year
        month: Month (1-12)
        weekday: Weekday (0=Monday, 6=Sunday)
        n: Occurrence (1=first, 2=second, etc.)
    
    Returns:
        Date of the nth weekday in the month
    """
    first_day = date(year, month, 1)
    first_weekday = first_day.weekday()
    
    # Days until first occurrence of target weekday
    days_until = (weekday - first_weekday + 7) % 7
    first_occurrence = first_day + timedelta(days=days_until)
    
    # Add weeks for nth occurrence
    return first_occurrence + timedelta(weeks=n - 1)


def _get_last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """
    Get the last occurrence of a weekday in a month.
    
    Args:
        year: Year
        month: Month (1-12)
        weekday: Weekday (0=Monday, 6=Sunday)
    
    Returns:
        Date of the last weekday in the month
    """
    # Get last day of month
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    last_weekday = last_day.weekday()
    
    # Days back to target weekday
    days_back = (last_weekday - weekday + 7) % 7
    return last_day - timedelta(days=days_back)


def _calculate_good_friday(year: int) -> date:
    """
    Calculate Good Friday date for a given year.
    
    Uses the Anonymous Gregorian algorithm to calculate Easter Sunday,
    then subtracts 2 days for Good Friday.
    """
    # Anonymous Gregorian algorithm for Easter
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    
    easter = date(year, month, day)
    good_friday = easter - timedelta(days=2)
    return good_friday


def _apply_observance_rule(holiday_date: date) -> date:
    """
    Apply US federal observance rule: if holiday falls on weekend,
    observe on nearest weekday (Saturday → Friday, Sunday → Monday).
    
    Note: CME doesn't always follow federal observance rules exactly.
    This is a reasonable approximation.
    """
    weekday = holiday_date.weekday()
    if weekday == 5:  # Saturday
        return holiday_date - timedelta(days=1)  # Observe Friday
    elif weekday == 6:  # Sunday
        return holiday_date + timedelta(days=1)  # Observe Monday
    return holiday_date


def get_cme_holidays_for_year(year: int) -> Set[date]:
    """
    Get CME equity futures holidays for a given year.
    
    Based on CME holiday calendar. Includes:
    - New Year's Day (observed)
    - Martin Luther King Jr. Day (3rd Monday of January)
    - Presidents Day (3rd Monday of February)
    - Good Friday
    - Memorial Day (last Monday of May)
    - Independence Day (observed)
    - Labor Day (1st Monday of September)
    - Thanksgiving Day (4th Thursday of November)
    - Christmas Day (observed)
    
    Returns:
        Set of holiday dates for the year
    """
    holidays: Set[date] = set()
    
    # Fixed holidays with observance rules
    # New Year's Day
    new_years = _apply_observance_rule(date(year, 1, 1))
    holidays.add(new_years)
    
    # Independence Day
    july_4th = _apply_observance_rule(date(year, 7, 4))
    holidays.add(july_4th)
    
    # Christmas Day
    christmas = _apply_observance_rule(date(year, 12, 25))
    holidays.add(christmas)
    
    # Variable holidays
    # MLK Day: 3rd Monday of January
    mlk_day = _get_nth_weekday_of_month(year, 1, 0, 3)  # 0=Monday
    holidays.add(mlk_day)
    
    # Presidents Day: 3rd Monday of February
    presidents_day = _get_nth_weekday_of_month(year, 2, 0, 3)
    holidays.add(presidents_day)
    
    # Good Friday
    good_friday = _calculate_good_friday(year)
    holidays.add(good_friday)
    
    # Memorial Day: Last Monday of May
    memorial_day = _get_last_weekday_of_month(year, 5, 0)
    holidays.add(memorial_day)
    
    # Labor Day: 1st Monday of September
    labor_day = _get_nth_weekday_of_month(year, 9, 0, 1)
    holidays.add(labor_day)
    
    # Thanksgiving: 4th Thursday of November
    thanksgiving = _get_nth_weekday_of_month(year, 11, 3, 4)  # 3=Thursday
    holidays.add(thanksgiving)
    
    return holidays


def get_cme_early_closes_for_year(year: int) -> Dict[date, int]:
    """
    Get CME equity futures early close times for a given year.
    
    Common early closes (12:15 PM CT = 1:15 PM ET):
    - Day before Independence Day (if weekday)
    - Day after Thanksgiving (Black Friday)
    - Christmas Eve (if weekday)
    - New Year's Eve (if weekday)
    
    Returns:
        Dict mapping dates to close hour (in ET)
    """
    early_closes: Dict[date, int] = {}
    
    # Day before Independence Day (if weekday)
    july_3rd = date(year, 7, 3)
    if july_3rd.weekday() < 5:  # Weekday
        early_closes[july_3rd] = 13  # 1:15 PM ET
    
    # Black Friday (day after Thanksgiving)
    thanksgiving = _get_nth_weekday_of_month(year, 11, 3, 4)
    black_friday = thanksgiving + timedelta(days=1)
    early_closes[black_friday] = 13
    
    # Christmas Eve (if weekday)
    christmas_eve = date(year, 12, 24)
    if christmas_eve.weekday() < 5:
        early_closes[christmas_eve] = 13
    
    # New Year's Eve (if weekday)
    new_years_eve = date(year, 12, 31)
    if new_years_eve.weekday() < 5:
        early_closes[new_years_eve] = 13
    
    return early_closes


class MarketHours:
    """
    Check if futures markets are open.

    Futures markets (CME, NYMEX) are generally:
    - Open: Sunday 6:00 PM ET - Friday 5:00 PM ET
    - Closed: Friday 5:00 PM ET - Sunday 6:00 PM ET
    - Also closed on certain holidays

    Holiday support includes:
    - Fixed holidays with observance rules (New Year's, July 4th, Christmas)
    - Variable holidays (MLK Day, Presidents Day, Good Friday, Memorial Day,
      Labor Day, Thanksgiving)
    - Early closes (July 3rd, Black Friday, Christmas Eve, New Year's Eve)
    - Optional overrides via holiday_overrides and early_closes parameters
    """

    def __init__(
        self,
        timezone_str: str = "America/New_York",
        holiday_overrides: Optional[list] = None,
        early_closes: Optional[dict] = None,
        use_calculated_holidays: bool = True,
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
            use_calculated_holidays: If True, automatically calculate variable holidays
                                     and early closes for the current year.
        """
        self.tz = pytz.timezone(timezone_str)
        self.holiday_overrides = set(holiday_overrides or [])
        self.early_closes = dict(early_closes or {})
        
        # Cache for calculated holidays by year
        self._calculated_holidays: Dict[int, Set[date]] = {}
        self._calculated_early_closes: Dict[int, Dict[date, int]] = {}
        self._use_calculated_holidays = use_calculated_holidays
    
    def _get_holidays_for_year(self, year: int) -> Set[date]:
        """Get all holidays (calculated + overrides) for a given year."""
        if year not in self._calculated_holidays:
            if self._use_calculated_holidays:
                self._calculated_holidays[year] = get_cme_holidays_for_year(year)
            else:
                self._calculated_holidays[year] = set()
        return self._calculated_holidays[year]
    
    def _get_early_closes_for_year(self, year: int) -> Dict[date, int]:
        """Get early closes (calculated + overrides) for a given year."""
        if year not in self._calculated_early_closes:
            if self._use_calculated_holidays:
                self._calculated_early_closes[year] = get_cme_early_closes_for_year(year)
            else:
                self._calculated_early_closes[year] = {}
        return self._calculated_early_closes[year]

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

        # Check calculated holidays (includes MLK, Presidents, Good Friday, etc.)
        calculated_holidays = self._get_holidays_for_year(et_date.year)
        if et_date in calculated_holidays:
            logger.debug(f"Market closed: Holiday ({et_date})")
            return False

        # Check if it's in the holiday overrides (year, month, day)
        if (et_date.year, et_date.month, et_date.day) in self.holiday_overrides:
            logger.debug(f"Market closed: Holiday override ({et_date.year}-{et_date.month}-{et_date.day})")
            return False

        # Check for early close (calculated + overrides)
        calculated_early_closes = self._get_early_closes_for_year(et_date.year)
        early_close_hour = calculated_early_closes.get(et_date)
        if early_close_hour is None:
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


_market_hours_holiday_overrides: Set[Tuple[int, int, int]] = set()
_market_hours_early_closes: Dict[Tuple[int, int, int], int] = {}
_market_hours_use_calculated: bool = True


def configure_market_hours(
    *,
    holiday_overrides: Optional[Iterable[Tuple[int, int, int]]] = None,
    early_closes: Optional[Mapping[Tuple[int, int, int], int]] = None,
    use_calculated_holidays: bool = True,
) -> None:
    """
    Configure the global MarketHours instance with optional overrides.

    This function exists to keep `utils` boundary-clean: config-driven behavior is wired
    by higher layers (e.g., `market_agent`), then injected here.
    
    Args:
        holiday_overrides: Additional holidays as (year, month, day) tuples
        early_closes: Early close times as {(year, month, day): close_hour_et}
        use_calculated_holidays: If True (default), automatically calculate
                                 variable holidays (MLK, Thanksgiving, etc.)
    """
    global _market_hours, _market_hours_holiday_overrides, _market_hours_early_closes, _market_hours_use_calculated
    _market_hours_holiday_overrides = set(holiday_overrides or [])
    _market_hours_early_closes = dict(early_closes or {})
    _market_hours_use_calculated = use_calculated_holidays
    _market_hours = None
    if _market_hours_holiday_overrides or _market_hours_early_closes:
        logger.info(
            "Configured market hours overrides: "
            f"{len(_market_hours_holiday_overrides)} holidays, {len(_market_hours_early_closes)} early closes, "
            f"use_calculated={use_calculated_holidays}"
        )


def get_market_hours() -> MarketHours:
    """
    Get global market hours instance.
    
    Market-hours overrides (holidays/early closes) must be configured by a higher layer
    (e.g., `pearlalgo.market_agent.service`) via `configure_market_hours()`.
    """
    global _market_hours
    if _market_hours is None:
        holiday_overrides = _market_hours_holiday_overrides
        early_closes = _market_hours_early_closes
        use_calculated = _market_hours_use_calculated

        _market_hours = MarketHours(
            holiday_overrides=list(holiday_overrides) if holiday_overrides else None,
            early_closes=dict(early_closes) if early_closes else None,
            use_calculated_holidays=use_calculated,
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

