from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.scanner import NQScanner


def _to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build an ET datetime and convert to UTC for stable assertions."""
    et = ZoneInfo("America/New_York")
    return datetime(year, month, day, hour, minute, tzinfo=et).astimezone(timezone.utc)


def test_prop_firm_session_cross_midnight_rules() -> None:
    # Prop-firm session: open 18:00 ET, close 16:10 ET (cross-midnight).
    cfg = NQIntradayConfig()
    cfg.start_time = "18:00"  # type: ignore[assignment]
    cfg.end_time = "16:10"  # type: ignore[assignment]

    scanner = NQScanner(config=cfg)

    # Sunday evening after open should be open.
    assert scanner.is_market_hours(_to_utc(2025, 12, 21, 19, 0)) is True

    # Monday early morning should be open.
    assert scanner.is_market_hours(_to_utc(2025, 12, 22, 1, 0)) is True

    # Monday between close and reopen should be closed (16:10–18:00).
    assert scanner.is_market_hours(_to_utc(2025, 12, 22, 17, 0)) is False

    # Monday evening after reopen should be open.
    assert scanner.is_market_hours(_to_utc(2025, 12, 22, 18, 5)) is True

    # Friday morning before close should be open.
    assert scanner.is_market_hours(_to_utc(2025, 12, 26, 15, 0)) is True

    # Friday evening after close should be closed (weekend).
    assert scanner.is_market_hours(_to_utc(2025, 12, 26, 19, 0)) is False

    # Saturday always closed.
    assert scanner.is_market_hours(_to_utc(2025, 12, 27, 10, 0)) is False


def test_session_open_from_bar_timestamp() -> None:
    """
    Test that is_market_hours accepts a datetime parameter (latest_bar timestamp).
    
    This validates the session-open-from-bar-time behavior where we prefer
    the latest_bar timestamp over wall-clock time to reduce drift issues.
    """
    cfg = NQIntradayConfig()
    cfg.start_time = "18:00"  # type: ignore[assignment]
    cfg.end_time = "16:10"  # type: ignore[assignment]

    scanner = NQScanner(config=cfg)

    # Test with explicit bar timestamp during session (Monday 3:40 AM ET = inside 18:00-16:10)
    bar_time_inside = _to_utc(2025, 12, 22, 3, 40)  # Monday 3:40 AM ET
    assert scanner.is_market_hours(dt=bar_time_inside) is True

    # Test with explicit bar timestamp outside session (Monday 5:00 PM ET = outside 18:00-16:10)
    bar_time_outside = _to_utc(2025, 12, 22, 17, 0)  # Monday 5:00 PM ET  
    assert scanner.is_market_hours(dt=bar_time_outside) is False

    # Test with None (falls back to wall-clock, behavior depends on current time)
    # Just verify it doesn't crash
    result = scanner.is_market_hours(dt=None)
    assert isinstance(result, bool)


def test_session_open_timezone_handling() -> None:
    """
    Test that is_market_hours handles various timezone inputs correctly.
    """
    cfg = NQIntradayConfig()
    cfg.start_time = "18:00"  # type: ignore[assignment]
    cfg.end_time = "16:10"  # type: ignore[assignment]

    scanner = NQScanner(config=cfg)

    # UTC timestamp during session
    utc_inside = datetime(2025, 12, 22, 8, 40, tzinfo=timezone.utc)  # 3:40 AM ET
    assert scanner.is_market_hours(dt=utc_inside) is True

    # UTC timestamp outside session
    utc_outside = datetime(2025, 12, 22, 22, 0, tzinfo=timezone.utc)  # 5:00 PM ET
    assert scanner.is_market_hours(dt=utc_outside) is False

    # Naive datetime (should be treated as UTC)
    naive_inside = datetime(2025, 12, 22, 8, 40)  # 3:40 AM ET if treated as UTC
    result = scanner.is_market_hours(dt=naive_inside)
    # The scanner should handle this - verify it doesn't crash
    assert isinstance(result, bool)











