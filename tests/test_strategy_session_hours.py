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



