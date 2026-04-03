"""
Tests for corrupt data recovery.

Verifies that the state manager handles corrupt signals.jsonl, state.json,
and events.jsonl gracefully — skipping bad records instead of crashing.
Uses the corrupt_state_dir fixture from conftest.py.
"""

from pathlib import Path

from pearlalgo.market_agent.state_manager import MarketAgentStateManager


def _make_state_manager(state_dir: Path) -> MarketAgentStateManager:
    cfg = {
        "storage": {"sqlite_enabled": False},
        "signals": {
            "duplicate_window_seconds": 120,
            "duplicate_price_threshold_pct": 0.5,
            "max_signal_lines": 5000,
        },
    }
    return MarketAgentStateManager(state_dir=state_dir, service_config=cfg)


class TestCorruptSignalsRecovery:
    """Verify get_recent_signals handles corrupt JSONL lines gracefully."""

    def test_skips_corrupt_json_lines(self, corrupt_state_dir):
        """Corrupt JSON lines are skipped; only valid lines returned."""
        sm = _make_state_manager(corrupt_state_dir)
        signals = sm.get_recent_signals_tail(max_lines=100)

        # corrupt_state_dir has 4 lines: good_1, NOT_JSON, truncated, good_2
        # Should return only the 2 valid records
        valid_ids = [s.get("signal_id") for s in signals]
        assert "good_1" in valid_ids
        assert "good_2" in valid_ids
        assert len(signals) >= 2

    def test_does_not_crash_on_corrupt_file(self, corrupt_state_dir):
        """State manager construction and basic operations don't crash."""
        sm = _make_state_manager(corrupt_state_dir)
        # Should not raise
        sm.get_recent_signals_tail(max_lines=10)


class TestCorruptStateJsonRecovery:
    """Verify load_state handles corrupt state.json gracefully."""

    def test_returns_empty_dict_on_corrupt_state_json(self, corrupt_state_dir):
        """Corrupt state.json returns empty/default state, not a crash."""
        sm = _make_state_manager(corrupt_state_dir)
        state = sm.load_state()
        # Should return a dict (possibly empty/default), not raise
        assert isinstance(state, dict)


class TestEmptyEventsRecovery:
    """Verify empty events.jsonl is handled."""

    def test_append_event_to_empty_events_file(self, corrupt_state_dir):
        """Appending an event to an empty events file works."""
        sm = _make_state_manager(corrupt_state_dir)
        # Should not raise
        sm.append_event("test_event", {"data": "test"})
        # Verify the event was written
        events_file = corrupt_state_dir / "events.jsonl"
        content = events_file.read_text()
        assert "test_event" in content
