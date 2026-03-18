"""Tests for pearlalgo.utils.news_calendar."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pearlalgo.utils.news_calendar import NewsCalendar


@pytest.fixture
def events_file(tmp_path):
    """Create a temp news calendar JSON file with test events."""
    events = [
        {
            "name": "FOMC Meeting",
            "time": "2026-03-15T18:00:00+00:00",
        },
        {
            "name": "CPI Release",
            "date": "2026-03-12",
            "time_et": "08:30",
        },
    ]
    path = tmp_path / "t1_news.json"
    path.write_text(json.dumps(events))
    return path


@pytest.fixture
def cal(events_file):
    return NewsCalendar(data_path=events_file)


class TestInit:
    def test_loads_events(self, cal):
        assert len(cal._events) == 2

    def test_no_file_uses_fallback(self, tmp_path):
        # When data_path doesn't exist, constructor falls back to default locations
        # This is expected behavior — just verify it doesn't crash
        cal = NewsCalendar(data_path=tmp_path / "nonexistent.json")
        # Events may be 0 or loaded from fallback, both are valid
        assert isinstance(cal._events, list)

    def test_dict_format(self, tmp_path):
        path = tmp_path / "cal.json"
        path.write_text(json.dumps({"events": [{"name": "Test", "time": "2026-01-01T00:00:00Z"}]}))
        cal = NewsCalendar(data_path=path)
        assert len(cal._events) == 1

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "cal.json"
        path.write_text("not json")
        cal = NewsCalendar(data_path=path)
        assert len(cal._events) == 0

    def test_custom_blackout_window(self, events_file):
        cal = NewsCalendar(data_path=events_file, blackout_before_min=5, blackout_after_min=10)
        assert cal._blackout_before == timedelta(minutes=5)
        assert cal._blackout_after == timedelta(minutes=10)


class TestIsInBlackout:
    def test_in_blackout(self, cal):
        # 1 minute before FOMC
        now = datetime(2026, 3, 15, 17, 59, tzinfo=timezone.utc)
        is_blackout, name = cal.is_in_blackout(now)
        assert is_blackout is True
        assert "FOMC" in name

    def test_not_in_blackout(self, cal):
        # Way before any event
        now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        is_blackout, name = cal.is_in_blackout(now)
        assert is_blackout is False
        assert name is None

    def test_empty_events_list(self, events_file):
        cal = NewsCalendar(data_path=events_file)
        cal._events = []  # Force empty
        is_blackout, name = cal.is_in_blackout()
        assert is_blackout is False

    def test_naive_datetime(self, cal):
        # Should handle naive datetime (treats as UTC)
        now = datetime(2026, 3, 15, 17, 59)
        is_blackout, _ = cal.is_in_blackout(now)
        assert is_blackout is True

    def test_after_blackout(self, cal):
        now = datetime(2026, 3, 15, 18, 3, tzinfo=timezone.utc)
        is_blackout, _ = cal.is_in_blackout(now)
        assert is_blackout is False


class TestNextEvent:
    def test_returns_next(self, cal):
        now = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc)
        result = cal.next_event(now)
        assert result is not None
        assert "CPI" in result["name"] or "FOMC" in result["name"]
        assert result["minutes_until"] > 0

    def test_empty_events_list(self, events_file):
        cal = NewsCalendar(data_path=events_file)
        cal._events = []  # Force empty
        assert cal.next_event() is None

    def test_all_past(self, cal):
        now = datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert cal.next_event(now) is None


class TestParseEventTime:
    def test_iso_format(self, cal):
        event = {"time": "2026-03-15T18:00:00+00:00"}
        result = cal._parse_event_time(event)
        assert result is not None
        assert result.tzinfo is not None

    def test_date_and_time_et(self, cal):
        event = {"date": "2026-03-12", "time_et": "08:30"}
        result = cal._parse_event_time(event)
        assert result is not None

    def test_no_time(self, cal):
        event = {"name": "No Time"}
        assert cal._parse_event_time(event) is None

    def test_invalid_time(self, cal):
        event = {"time": "not-a-time"}
        assert cal._parse_event_time(event) is None

    def test_naive_iso(self, cal):
        event = {"time": "2026-03-15T18:00:00"}
        result = cal._parse_event_time(event)
        assert result is not None
        assert result.tzinfo is not None
