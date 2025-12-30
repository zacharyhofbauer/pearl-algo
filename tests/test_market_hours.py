from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pearlalgo.utils.market_hours import MarketHours


def _to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build an ET datetime and convert to UTC for stable assertions."""
    et = ZoneInfo("America/New_York")
    return datetime(year, month, day, hour, minute, tzinfo=et).astimezone(timezone.utc)


def test_market_hours_sunday_open_transition() -> None:
    mh = MarketHours()

    # Sunday before 6 PM ET is closed.
    assert mh.is_market_open(_to_utc(2025, 6, 1, 17, 59)) is False

    # Sunday at/after 6 PM ET is open.
    assert mh.is_market_open(_to_utc(2025, 6, 1, 18, 0)) is True


def test_market_hours_cme_maintenance_break_closed() -> None:
    mh = MarketHours()

    # Monday 17:30 ET should be closed (CME maintenance break).
    assert mh.is_market_open(_to_utc(2025, 6, 2, 17, 30)) is False

    # Monday 16:30 ET should be open.
    assert mh.is_market_open(_to_utc(2025, 6, 2, 16, 30)) is True

    # Monday 18:00 ET should be open again.
    assert mh.is_market_open(_to_utc(2025, 6, 2, 18, 0)) is True


def test_market_hours_friday_close() -> None:
    mh = MarketHours()

    # Friday just before 5 PM ET is open.
    assert mh.is_market_open(_to_utc(2025, 6, 6, 16, 59)) is True

    # Friday at/after 5 PM ET is closed for the weekend.
    assert mh.is_market_open(_to_utc(2025, 6, 6, 17, 0)) is False












