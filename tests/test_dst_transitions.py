"""
Tests for DST (Daylight Saving Time) transition handling.

Validates that market hours and strategy session gating behave correctly
during the Spring Forward and Fall Back transitions.

US DST transitions:
- Spring Forward: 2nd Sunday in March at 2:00 AM (clocks move to 3:00 AM)
- Fall Back: 1st Sunday in November at 2:00 AM (clocks move to 1:00 AM)

These tests use specific dates to test edge cases:
- 2025 Spring: Sunday, March 9, 2025
- 2025 Fall: Sunday, November 2, 2025
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from pearlalgo.utils.market_hours import MarketHours
from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
from pearlalgo.config.config_loader import load_service_config
from pearlalgo.strategies.nq_intraday.scanner import NQScanner


def _to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build an ET datetime and convert to UTC for stable assertions."""
    et = ZoneInfo("America/New_York")
    return datetime(year, month, day, hour, minute, tzinfo=et).astimezone(timezone.utc)


def _to_utc_from_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build a UTC datetime directly."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestMarketHoursDSTSpringForward:
    """
    Tests for DST Spring Forward transition (March).
    
    On 2025-03-09 at 2:00 AM ET, clocks spring forward to 3:00 AM ET.
    This means 2:00-2:59 AM ET doesn't exist that day.
    
    In UTC terms:
    - Before DST: 1:59 AM ET = 6:59 AM UTC (EST = UTC-5)
    - After DST: 3:00 AM ET = 7:00 AM UTC (EDT = UTC-4)
    
    The transition happens at 7:00 AM UTC.
    """

    def test_spring_forward_sunday_open(self) -> None:
        """Sunday market open should work correctly around DST transition."""
        mh = MarketHours()
        
        # March 9, 2025 is a Sunday (DST Spring Forward)
        # Sunday before 6 PM ET is closed
        
        # 5:30 PM ET = 10:30 PM UTC (on DST day, now EDT so UTC-4)
        assert mh.is_market_open(_to_utc(2025, 3, 9, 17, 30)) is False
        
        # 6:00 PM ET = 10:00 PM UTC - should be open
        assert mh.is_market_open(_to_utc(2025, 3, 9, 18, 0)) is True
        
        # 7:00 PM ET = 11:00 PM UTC - should be open
        assert mh.is_market_open(_to_utc(2025, 3, 9, 19, 0)) is True

    def test_spring_forward_early_morning(self) -> None:
        """Early morning hours around DST transition should be open (Monday)."""
        mh = MarketHours()
        
        # March 10, 2025 (Monday, day after Spring Forward)
        # 1:00 AM ET = 5:00 AM UTC (EDT = UTC-4)
        assert mh.is_market_open(_to_utc(2025, 3, 10, 1, 0)) is True
        
        # 3:00 AM ET = 7:00 AM UTC - should be open
        assert mh.is_market_open(_to_utc(2025, 3, 10, 3, 0)) is True

    def test_spring_forward_maintenance_break(self) -> None:
        """Maintenance break timing should be correct after DST."""
        mh = MarketHours()
        
        # March 10, 2025 (Monday after Spring Forward)
        # 17:00 ET = 21:00 UTC (EDT = UTC-4) - maintenance break
        assert mh.is_market_open(_to_utc(2025, 3, 10, 17, 0)) is False
        
        # 17:59 ET still in maintenance break
        assert mh.is_market_open(_to_utc(2025, 3, 10, 17, 59)) is False
        
        # 18:00 ET = 22:00 UTC - should be open again
        assert mh.is_market_open(_to_utc(2025, 3, 10, 18, 0)) is True


class TestMarketHoursDSTFallBack:
    """
    Tests for DST Fall Back transition (November).
    
    On 2025-11-02 at 2:00 AM EDT, clocks fall back to 1:00 AM EST.
    This means 1:00-1:59 AM happens twice that day.
    
    In UTC terms:
    - Before Fall Back: 1:59 AM EDT = 5:59 AM UTC (EDT = UTC-4)
    - After Fall Back: 1:00 AM EST = 6:00 AM UTC (EST = UTC-5)
    
    The transition happens at 6:00 AM UTC.
    """

    def test_fall_back_sunday_open(self) -> None:
        """Sunday market open should work correctly around Fall Back."""
        mh = MarketHours()
        
        # November 2, 2025 is a Sunday (DST Fall Back)
        # Sunday before 6 PM ET is closed
        
        # 5:30 PM ET = 21:30 UTC (after Fall Back, EST = UTC-5)
        assert mh.is_market_open(_to_utc(2025, 11, 2, 17, 30)) is False
        
        # 6:00 PM ET = 23:00 UTC - should be open
        assert mh.is_market_open(_to_utc(2025, 11, 2, 18, 0)) is True
        
        # 7:00 PM ET = 00:00 UTC (next day) - should be open
        assert mh.is_market_open(_to_utc(2025, 11, 2, 19, 0)) is True

    def test_fall_back_ambiguous_hour(self) -> None:
        """
        The 1:00-1:59 AM hour occurs twice during Fall Back.
        We test using UTC to be unambiguous.
        
        Key insight: The market opens Sunday at 6 PM ET.
        On November 2, 2025 (Fall Back day):
        - 6 PM ET = 23:00 UTC (after Fall Back, EST = UTC-5)
        
        Before 6 PM ET Sunday, the market is closed (it closed Friday evening).
        """
        mh = MarketHours()
        
        # November 2, 2025 at 5:30 AM UTC
        # This converts to 1:30 AM EDT (before Fall Back at 6 AM UTC)
        # This is Sunday early morning, BEFORE 6 PM ET market open
        dt_before_open = _to_utc_from_utc(2025, 11, 2, 5, 30)
        assert mh.is_market_open(dt_before_open) is False  # Market still closed (Sunday before 6 PM)
        
        # November 2 at 23:00 UTC = 6 PM EST (after Fall Back, EST = UTC-5)
        # This is when the market opens for the week
        dt_market_open = _to_utc_from_utc(2025, 11, 2, 23, 0)
        assert mh.is_market_open(dt_market_open) is True

    def test_fall_back_maintenance_break(self) -> None:
        """Maintenance break timing should be correct after Fall Back."""
        mh = MarketHours()
        
        # November 3, 2025 (Monday after Fall Back)
        # 17:00 EST = 22:00 UTC (EST = UTC-5) - maintenance break
        assert mh.is_market_open(_to_utc(2025, 11, 3, 17, 0)) is False
        
        # 18:00 EST = 23:00 UTC - should be open again
        assert mh.is_market_open(_to_utc(2025, 11, 3, 18, 0)) is True


class TestStrategySessionDST:
    """Tests for strategy session gating during DST transitions."""

    @pytest.fixture
    def scanner(self) -> NQScanner:
        """Create scanner with prop-firm session times."""
        cfg = PEARL_BOT_CONFIG.copy()
        cfg.start_time = "18:00"  # type: ignore[assignment]
        cfg.end_time = "16:10"  # type: ignore[assignment]
        return NQScanner(config=cfg)

    def test_spring_forward_session_open(self, scanner) -> None:
        """Strategy session should work correctly around Spring Forward."""
        # March 9, 2025 (Sunday, DST Spring Forward)
        # Session opens at 18:00 ET
        
        # 17:30 ET - session closed (before 18:00)
        assert scanner.is_market_hours(_to_utc(2025, 3, 9, 17, 30)) is False
        
        # 18:30 ET - session open
        assert scanner.is_market_hours(_to_utc(2025, 3, 9, 18, 30)) is True
        
        # March 10, 2025 (Monday after Spring Forward)
        # 10:00 AM ET - session open (middle of trading day)
        assert scanner.is_market_hours(_to_utc(2025, 3, 10, 10, 0)) is True
        
        # 16:15 ET - session closed (after 16:10)
        assert scanner.is_market_hours(_to_utc(2025, 3, 10, 16, 15)) is False
        
        # 18:05 ET - session reopened
        assert scanner.is_market_hours(_to_utc(2025, 3, 10, 18, 5)) is True

    def test_fall_back_session_open(self, scanner) -> None:
        """Strategy session should work correctly around Fall Back."""
        # November 2, 2025 (Sunday, DST Fall Back)
        # Session opens at 18:00 ET
        
        # 17:30 ET - session closed
        assert scanner.is_market_hours(_to_utc(2025, 11, 2, 17, 30)) is False
        
        # 18:30 ET - session open
        assert scanner.is_market_hours(_to_utc(2025, 11, 2, 18, 30)) is True
        
        # November 3, 2025 (Monday after Fall Back)
        # 10:00 AM EST - session open
        assert scanner.is_market_hours(_to_utc(2025, 11, 3, 10, 0)) is True
        
        # 16:15 EST - session closed
        assert scanner.is_market_hours(_to_utc(2025, 11, 3, 16, 15)) is False


class TestMarketHoursDocumentation:
    """
    Documentation tests for market hours limitations.
    
    These tests document known limitations and expected behavior.
    """

    def test_holiday_coverage_is_limited(self) -> None:
        """
        DOCUMENTED LIMITATION: Holiday coverage is intentionally incomplete.
        
        The MarketHours class only checks for a fixed list of holidays:
        - New Year's Day (Jan 1)
        - Independence Day (Jul 4)
        - Christmas (Dec 25)
        
        NOT covered (would require exchange calendar integration):
        - Good Friday (varies by year)
        - Memorial Day (last Monday of May)
        - Labor Day (1st Monday of September)
        - Thanksgiving (4th Thursday of November)
        - Early closes (day before holidays)
        - Half-day sessions
        
        For accurate holiday handling, integrate with the CME holiday calendar.
        """
        mh = MarketHours()
        
        # Verify known holidays are caught
        assert mh.is_market_open(_to_utc(2025, 1, 1, 12, 0)) is False  # New Year's
        assert mh.is_market_open(_to_utc(2025, 7, 4, 12, 0)) is False  # Independence Day
        assert mh.is_market_open(_to_utc(2025, 12, 25, 12, 0)) is False  # Christmas
        
        # Thanksgiving NOT caught (would be Nov 27, 2025 - 4th Thursday)
        # This is a known limitation
        thanksgiving_2025 = _to_utc(2025, 11, 27, 12, 0)  # Thursday
        # Intentionally not asserting - just documenting the limitation

    def test_early_close_not_supported(self) -> None:
        """
        DOCUMENTED LIMITATION: Early closes are not supported by default.
        
        Days like the day before Thanksgiving typically have early closes
        (e.g., 1:00 PM ET instead of 5:00 PM ET), but this is not implemented
        in the default configuration.
        
        However, you CAN use the optional parameters to configure:
        1. holiday_overrides: List of (year, month, day) for additional closures
        2. early_closes: Dict mapping (year, month, day) to close hour
        """
        # Just documentation - no assertion needed
        pass


class TestHolidayOverrides:
    """Tests for the optional holiday override feature."""

    def test_holiday_override_closes_market(self) -> None:
        """Holiday overrides should close the market on specified dates."""
        # Create MarketHours with Thanksgiving 2025 as an override
        mh = MarketHours(
            holiday_overrides=[
                (2025, 11, 27),  # Thanksgiving 2025
            ]
        )
        
        # Thanksgiving 2025 (Thursday Nov 27) should now be closed
        thanksgiving = _to_utc(2025, 11, 27, 12, 0)
        assert mh.is_market_open(thanksgiving) is False

    def test_early_close_override(self) -> None:
        """Early close overrides should close the market at specified hour."""
        # Create MarketHours with day-before-Thanksgiving early close
        mh = MarketHours(
            early_closes={
                (2025, 11, 26): 13,  # 1 PM close on Wed before Thanksgiving
            }
        )
        
        # Wednesday Nov 26, 2025
        # 12:00 PM ET should still be open
        assert mh.is_market_open(_to_utc(2025, 11, 26, 12, 0)) is True
        
        # 1:30 PM ET should be closed
        assert mh.is_market_open(_to_utc(2025, 11, 26, 13, 30)) is False
        
        # Regular Thursday should still work normally
        assert mh.is_market_open(_to_utc(2025, 11, 20, 13, 30)) is True

    def test_combined_overrides(self) -> None:
        """Holiday and early close overrides can be combined."""
        mh = MarketHours(
            holiday_overrides=[
                (2025, 4, 18),  # Good Friday 2025
            ],
            early_closes={
                (2025, 4, 17): 13,  # Thursday before Good Friday, early close
            }
        )
        
        # Good Friday closed
        assert mh.is_market_open(_to_utc(2025, 4, 18, 12, 0)) is False
        
        # Thursday before, early close at 1 PM
        assert mh.is_market_open(_to_utc(2025, 4, 17, 12, 0)) is True
        assert mh.is_market_open(_to_utc(2025, 4, 17, 14, 0)) is False

