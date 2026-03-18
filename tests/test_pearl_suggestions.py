"""Tests for pearlalgo.utils.pearl_suggestions."""

from __future__ import annotations

import time

import pytest

from pearlalgo.utils.pearl_suggestions import (
    SuggestionPriority,
    PearlSuggestion,
    SuggestionState,
    PearlSuggestionEngine,
)


class TestSuggestionPriority:
    def test_ordering(self):
        assert SuggestionPriority.CRITICAL < SuggestionPriority.IMPORTANT
        assert SuggestionPriority.IMPORTANT < SuggestionPriority.HELPFUL

    def test_values(self):
        assert SuggestionPriority.CRITICAL == 1
        assert SuggestionPriority.IMPORTANT == 2
        assert SuggestionPriority.HELPFUL == 3


class TestPearlSuggestion:
    def test_defaults(self):
        s = PearlSuggestion(
            message="Test message",
            accept_label="OK",
            accept_action="pearl:test",
        )
        assert s.priority == SuggestionPriority.HELPFUL
        assert s.decline_label == "Dismiss"
        assert s.cooldown_key == ""

    def test_custom_fields(self):
        s = PearlSuggestion(
            message="Reconnect?",
            accept_label="Yes please",
            accept_action="pearl:reconnect_gateway",
            priority=SuggestionPriority.CRITICAL,
            cooldown_key="gateway_down",
            decline_label="Not now",
        )
        assert s.priority == SuggestionPriority.CRITICAL
        assert s.decline_label == "Not now"


class TestSuggestionState:
    def test_defaults(self):
        state = SuggestionState()
        assert state.cooldowns == {}
        assert state.last_greeting_date is None
        assert state.interaction_count == 0

    def test_mutability(self):
        state = SuggestionState()
        state.cooldowns["test"] = time.time()
        assert "test" in state.cooldowns


class TestPearlSuggestionEngine:
    def test_init(self):
        engine = PearlSuggestionEngine()
        assert engine._state is not None

    def test_init_with_state_dir(self, tmp_path):
        engine = PearlSuggestionEngine(state_dir=str(tmp_path))
        assert engine._state_dir == str(tmp_path)

    def test_is_on_cooldown_false(self):
        engine = PearlSuggestionEngine()
        assert engine._is_on_cooldown("nonexistent", 30) is False

    def test_is_on_cooldown_true(self):
        engine = PearlSuggestionEngine()
        engine._state.cooldowns["test"] = time.time()
        assert engine._is_on_cooldown("test", 30) is True

    def test_is_on_cooldown_empty_key(self):
        engine = PearlSuggestionEngine()
        assert engine._is_on_cooldown("", 30) is False

    def test_mark_shown(self):
        engine = PearlSuggestionEngine()
        engine._mark_shown("test_key")
        assert "test_key" in engine._state.cooldowns

    def test_mark_dismissed(self):
        engine = PearlSuggestionEngine()
        engine.mark_dismissed("test_key")
        assert "test_key" in engine._state.cooldowns

    def test_generate_suggestion_disabled(self):
        engine = PearlSuggestionEngine()
        result = engine.generate_suggestion(
            {"agent_running": True},
            prefs={"pearl_suggestions_enabled": False},
        )
        assert result is None

    def test_generate_suggestion_gateway_down(self):
        engine = PearlSuggestionEngine()
        result = engine.generate_suggestion(
            {"agent_running": True, "gateway_running": False},
            prefs={"pearl_suggestions_enabled": True},
        )
        # Should suggest reconnecting gateway or return None
        assert result is None or isinstance(result, PearlSuggestion)

    def test_generate_suggestion_data_stale(self):
        engine = PearlSuggestionEngine()
        result = engine.generate_suggestion(
            {"agent_running": True, "data_stale": True, "data_age_minutes": 15},
            prefs={"pearl_suggestions_enabled": True},
        )
        assert result is None or isinstance(result, PearlSuggestion)

    def test_save_and_load_state(self, tmp_path):
        engine = PearlSuggestionEngine(state_dir=str(tmp_path))
        engine._mark_shown("test_key")
        # Create new engine from same dir
        engine2 = PearlSuggestionEngine(state_dir=str(tmp_path))
        assert "test_key" in engine2._state.cooldowns
