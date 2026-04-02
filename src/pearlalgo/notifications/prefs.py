"""
Telegram UI preferences - Persistent settings for the Telegram bot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.state_io import load_json_file, atomic_write_json


class TelegramPrefs:
    """
    Persistent UI preferences for Telegram bot.

    Stored as JSON in the state directory. All settings default to current
    calm-minimal behavior so existing users see no change until they opt-in.
    """

    DEFAULTS = {
        "dashboard_buttons": True,
        "dashboard_edit_in_place": False,
        "dashboard_message_id": None,
        "last_dashboard_sent_at": None,
        "signal_detail_expanded": False,
        "auto_chart_on_signal": False,
        "snooze_noncritical_alerts": False,
        "snooze_until": None,
        "interval_notifications": True,
        "pearl_suggestions_enabled": False,
        "pearl_suggestion_cooldown_minutes": 30,
        "pearl_greeting_enabled": False,
        "pearl_review_enabled": False,
        "pearl_review_interval_minutes": 60,
        "pearl_review_last_sent_at": None,
    }

    LABELS = {
        "dashboard_buttons": "Dashboard Buttons",
        "dashboard_edit_in_place": "Pinned Dashboard (Edit-in-Place)",
        "signal_detail_expanded": "Expanded Signal Details",
        "auto_chart_on_signal": "Auto-Chart on Signal",
        "snooze_noncritical_alerts": "Snooze Non-Critical Alerts",
        "interval_notifications": "Interval Notifications",
        "pearl_suggestions_enabled": "Pearl Suggestions",
        "pearl_greeting_enabled": "Pearl Greetings",
        "pearl_review_enabled": "PEARL Reviews",
    }

    DESCRIPTIONS = {
        "dashboard_buttons": "Always show Menu navigation buttons on dashboards & alerts",
        "dashboard_edit_in_place": "Reduce chat spam by updating one dashboard message instead of sending new ones",
        "signal_detail_expanded": "Show full context (regime, MTF, VWAP) in signal details by default",
        "auto_chart_on_signal": "Automatically generate and send chart with each signal alert",
        "snooze_noncritical_alerts": "Temporarily suppress non-critical data quality alerts (1 hour)",
        "interval_notifications": "Hourly chart + status notifications (toggle off to disable)",
        "pearl_suggestions_enabled": "Pearl proactively offers help on dashboard (dismissible)",
        "pearl_greeting_enabled": "Pearl greets you in the morning with overnight summary",
        "pearl_review_enabled": "PEARL sends hourly check-ins with insights",
    }

    def __init__(self, state_dir: Optional[Path] = None):
        if state_dir is None:
            try:
                from pearlalgo.utils.paths import ensure_state_dir
                state_dir = Path(ensure_state_dir())
            except ImportError:
                state_dir = Path("data/agent_state/MNQ")
        self._prefs_file = Path(state_dir) / "telegram_prefs.json"
        self._prefs = dict(self.DEFAULTS)
        self._load()

    def _load(self) -> None:
        raw = load_json_file(self._prefs_file)
        if isinstance(raw, dict):
            for key in self.DEFAULTS:
                if key in raw:
                    self._prefs[key] = raw[key]
        try:
            if self._prefs.get("dashboard_buttons") is not True:
                self._prefs["dashboard_buttons"] = True
                self._save()
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self._prefs_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self._prefs_file, self._prefs, default=str)
        except Exception as e:
            logger.warning("Could not save Telegram prefs: %s", e)

    def get(self, key: str, default=None):
        return self._prefs.get(key, default if default is not None else self.DEFAULTS.get(key))

    def set(self, key: str, value) -> bool:
        if key not in self.DEFAULTS:
            return False
        self._prefs[key] = value
        self._save()
        return True

    def toggle(self, key: str) -> bool:
        if key not in self.DEFAULTS:
            return False
        current = self._prefs.get(key, self.DEFAULTS.get(key))
        if isinstance(current, bool):
            self._prefs[key] = not current
            self._save()
            return self._prefs[key]
        return False

    def reset(self) -> None:
        self._prefs = dict(self.DEFAULTS)
        self._save()

    def all(self) -> dict:
        return dict(self._prefs)

    @property
    def dashboard_buttons(self) -> bool:
        return self._prefs.get("dashboard_buttons", True)

    @property
    def dashboard_edit_in_place(self) -> bool:
        return self._prefs.get("dashboard_edit_in_place", False)

    @property
    def signal_detail_expanded(self) -> bool:
        return self._prefs.get("signal_detail_expanded", False)

    @property
    def auto_chart_on_signal(self) -> bool:
        return self._prefs.get("auto_chart_on_signal", False)

    @property
    def snooze_noncritical_alerts(self) -> bool:
        if not self._prefs.get("snooze_noncritical_alerts", False):
            return False
        snooze_until = self._prefs.get("snooze_until")
        if snooze_until:
            try:
                from datetime import datetime, timezone
                expiry = datetime.fromisoformat(str(snooze_until).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expiry:
                    self._prefs["snooze_noncritical_alerts"] = False
                    self._prefs["snooze_until"] = None
                    self._save()
                    return False
            except Exception:
                pass
        return True

    def enable_snooze(self, hours: float = 1.0) -> None:
        from datetime import datetime, timezone, timedelta
        expiry = datetime.now(timezone.utc) + timedelta(hours=hours)
        self._prefs["snooze_noncritical_alerts"] = True
        self._prefs["snooze_until"] = expiry.isoformat()
        self._save()

    def disable_snooze(self) -> None:
        self._prefs["snooze_noncritical_alerts"] = False
        self._prefs["snooze_until"] = None
        self._save()

    @property
    def pearl_suggestions_enabled(self) -> bool:
        return self._prefs.get("pearl_suggestions_enabled", True)

    @property
    def pearl_suggestion_cooldown_minutes(self) -> int:
        return self._prefs.get("pearl_suggestion_cooldown_minutes", 30)

    @property
    def pearl_greeting_enabled(self) -> bool:
        return self._prefs.get("pearl_greeting_enabled", True)

    def get_pearl_prefs(self) -> dict:
        return {
            "pearl_suggestions_enabled": self.pearl_suggestions_enabled,
            "pearl_suggestion_cooldown_minutes": self.pearl_suggestion_cooldown_minutes,
            "pearl_greeting_enabled": self.pearl_greeting_enabled,
        }
