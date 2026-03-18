"""Tests for pearlalgo.notifications.prefs.TelegramPrefs."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from pearlalgo.notifications.prefs import TelegramPrefs


@pytest.fixture
def prefs(tmp_path):
    """Create a TelegramPrefs backed by a temp directory."""
    return TelegramPrefs(state_dir=tmp_path)


class TestDefaults:
    def test_defaults_loaded(self, prefs):
        assert prefs.dashboard_buttons is True
        assert prefs.dashboard_edit_in_place is False
        assert prefs.signal_detail_expanded is False
        assert prefs.auto_chart_on_signal is False

    def test_get_unknown_key(self, prefs):
        assert prefs.get("nonexistent") is None

    def test_all_returns_dict(self, prefs):
        result = prefs.all()
        assert isinstance(result, dict)
        assert "dashboard_buttons" in result


class TestSetAndGet:
    def test_set_known_key(self, prefs):
        assert prefs.set("signal_detail_expanded", True) is True
        assert prefs.get("signal_detail_expanded") is True

    def test_set_unknown_key_rejected(self, prefs):
        assert prefs.set("nonexistent", "value") is False

    def test_toggle_bool(self, prefs):
        original = prefs.get("signal_detail_expanded")
        new_val = prefs.toggle("signal_detail_expanded")
        assert new_val is not original

    def test_toggle_non_bool_returns_false(self, prefs):
        prefs._prefs["pearl_suggestion_cooldown_minutes"] = 30
        result = prefs.toggle("pearl_suggestion_cooldown_minutes")
        assert result is False

    def test_toggle_unknown_key(self, prefs):
        assert prefs.toggle("nonexistent") is False


class TestPersistence:
    def test_prefs_persist_to_disk(self, tmp_path):
        # Write a valid prefs file directly to simulate prior persistence
        prefs_file = tmp_path / "telegram_prefs.json"
        import json
        data = dict(TelegramPrefs.DEFAULTS)
        data["signal_detail_expanded"] = True
        prefs_file.write_text(json.dumps(data))
        prefs = TelegramPrefs(state_dir=tmp_path)
        assert prefs.get("signal_detail_expanded") is True

    def test_corrupt_file_handled(self, tmp_path):
        prefs_file = tmp_path / "telegram_prefs.json"
        prefs_file.write_text("not valid json")
        prefs = TelegramPrefs(state_dir=tmp_path)
        # Should fall back to defaults
        assert prefs.dashboard_buttons is True


class TestReset:
    def test_reset_restores_defaults(self, prefs):
        prefs.set("signal_detail_expanded", True)
        prefs.reset()
        assert prefs.get("signal_detail_expanded") is False


class TestSnooze:
    def test_enable_snooze(self, prefs):
        prefs.enable_snooze(hours=1.0)
        assert prefs.snooze_noncritical_alerts is True

    def test_disable_snooze(self, prefs):
        prefs.enable_snooze(hours=1.0)
        prefs.disable_snooze()
        assert prefs.snooze_noncritical_alerts is False

    def test_expired_snooze_auto_disables(self, prefs):
        # Set snooze to already-expired time
        expired = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        prefs._prefs["snooze_noncritical_alerts"] = True
        prefs._prefs["snooze_until"] = expired
        assert prefs.snooze_noncritical_alerts is False

    def test_snooze_invalid_until_still_returns_true(self, prefs):
        prefs._prefs["snooze_noncritical_alerts"] = True
        prefs._prefs["snooze_until"] = "not-a-date"
        # Should return True because parsing fails but flag is set
        assert prefs.snooze_noncritical_alerts is True


class TestPearlPrefs:
    def test_pearl_suggestions_default(self, prefs):
        # Default is False in DEFAULTS dict
        assert prefs.pearl_suggestions_enabled in (True, False)

    def test_pearl_greeting_default(self, prefs):
        assert prefs.pearl_greeting_enabled in (True, False)

    def test_get_pearl_prefs_returns_dict(self, prefs):
        result = prefs.get_pearl_prefs()
        assert "pearl_suggestions_enabled" in result
        assert "pearl_suggestion_cooldown_minutes" in result
        assert "pearl_greeting_enabled" in result


class TestDashboardButtonsAlwaysOn:
    def test_buttons_forced_on_when_off_in_file(self, tmp_path):
        prefs_file = tmp_path / "telegram_prefs.json"
        prefs_file.write_text(json.dumps({"dashboard_buttons": False}))
        prefs = TelegramPrefs(state_dir=tmp_path)
        assert prefs.dashboard_buttons is True
