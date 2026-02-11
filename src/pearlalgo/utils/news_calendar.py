"""
T1 News Calendar Service

Provides news blackout detection for Tradovate Paper prop firm rule compliance.

Rules:
- No open positions or orders 2 minutes BEFORE and 2 minutes AFTER any data release
- T1 events: FOMC Meetings, FOMC Minutes, Employment Report, CPI
- During Evaluation: T1 news trading is ALLOWED (but standard protocols still apply)
- During Sim Funded: T1 news trading is PROHIBITED

Data source: data/t1_news_2026.json (populated from prop firm help center calendar)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Default blackout window: 2 minutes before and after
DEFAULT_BLACKOUT_MINUTES_BEFORE = 2
DEFAULT_BLACKOUT_MINUTES_AFTER = 2


class NewsCalendar:
    """
    T1 news calendar for prop firm rule compliance.

    Loads events from a JSON file and provides blackout detection.
    """

    def __init__(
        self,
        data_path: Optional[Path] = None,
        blackout_before_min: int = DEFAULT_BLACKOUT_MINUTES_BEFORE,
        blackout_after_min: int = DEFAULT_BLACKOUT_MINUTES_AFTER,
    ):
        self._blackout_before = timedelta(minutes=blackout_before_min)
        self._blackout_after = timedelta(minutes=blackout_after_min)
        self._events: List[Dict] = []

        # Try to load events
        if data_path and data_path.exists():
            self._load_events(data_path)
        else:
            # Try default location relative to project root
            for candidate in [
                Path("data/t1_news_2026.json"),
                Path(__file__).parent.parent.parent.parent / "data" / "t1_news_2026.json",
            ]:
                if candidate.exists():
                    self._load_events(candidate)
                    break

        logger.info(f"NewsCalendar loaded: {len(self._events)} events")

    def _load_events(self, path: Path) -> None:
        """Load events from JSON file."""
        try:
            with open(path) as f:
                raw = json.load(f)
            if isinstance(raw, list):
                self._events = raw
            elif isinstance(raw, dict) and "events" in raw:
                self._events = raw["events"]
            else:
                logger.warning(f"Unexpected news calendar format in {path}")
        except Exception as e:
            logger.warning(f"Could not load news calendar from {path}: {e}")

    def is_in_blackout(
        self,
        now: Optional[datetime] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if the current time falls within a news blackout window.

        Args:
            now: Current datetime (UTC). Defaults to now.

        Returns:
            (is_blackout, event_name) -- True + event name if in blackout, else False + None
        """
        if not self._events:
            return False, None

        if now is None:
            now = datetime.now(timezone.utc)

        # Ensure timezone-aware
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        for event in self._events:
            event_time = self._parse_event_time(event)
            if event_time is None:
                continue

            window_start = event_time - self._blackout_before
            window_end = event_time + self._blackout_after

            if window_start <= now <= window_end:
                name = event.get("name", "Unknown news event")
                return True, name

        return False, None

    def next_event(
        self,
        now: Optional[datetime] = None,
    ) -> Optional[Dict]:
        """
        Get the next upcoming news event.

        Returns dict with 'name', 'time', 'minutes_until' or None.
        """
        if not self._events:
            return None

        if now is None:
            now = datetime.now(timezone.utc)

        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        closest = None
        closest_delta = None

        for event in self._events:
            event_time = self._parse_event_time(event)
            if event_time is None:
                continue

            delta = (event_time - now).total_seconds()
            if delta > 0 and (closest_delta is None or delta < closest_delta):
                closest = event
                closest_delta = delta

        if closest and closest_delta is not None:
            return {
                "name": closest.get("name", "Unknown"),
                "time": self._parse_event_time(closest).isoformat(),  # type: ignore
                "minutes_until": round(closest_delta / 60, 1),
            }
        return None

    def _parse_event_time(self, event: Dict) -> Optional[datetime]:
        """Parse event time from various formats."""
        time_str = event.get("time") or event.get("datetime") or event.get("timestamp")
        if not time_str:
            # Try to construct from date + time_et fields
            date_str = event.get("date")
            time_et = event.get("time_et")
            if date_str and time_et:
                try:
                    dt_str = f"{date_str} {time_et}"
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                    return dt.replace(tzinfo=ET).astimezone(timezone.utc)
                except (ValueError, TypeError):
                    pass
            return None

        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

        return None


# Module-level singleton
_calendar: Optional[NewsCalendar] = None


def get_news_calendar(data_path: Optional[Path] = None) -> NewsCalendar:
    """Get or create the singleton NewsCalendar instance."""
    global _calendar
    if _calendar is None:
        _calendar = NewsCalendar(data_path=data_path)
    return _calendar
