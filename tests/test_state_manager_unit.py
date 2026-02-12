"""
Unit tests for MarketAgentStateManager.

Covers:
- save_signal(): basic save, duplicate detection, different signals pass dedup,
  payload serialization, file locking
- get_recent_signals(): empty file, multiple signals, max_lines limit
- save_state() / load_state(): round-trip, empty state, corrupt file recovery
- append_event() / get_recent_events(): basic append, event rotation at 20 MB
- _is_duplicate_signal(): time-based dedup, price-based dedup
- _rotate_signals_file(): rotation at max_lines, archive creation
- Edge cases: corrupt JSON line in signals.jsonl, empty file, missing file
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pearlalgo.market_agent.state_manager import MarketAgentStateManager, _to_json_safe
from pearlalgo.utils.paths import get_utc_timestamp, parse_utc_timestamp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state_manager(state_dir: Path, **overrides) -> MarketAgentStateManager:
    """Create a StateManager pointed at *state_dir* with SQLite disabled."""
    cfg: dict = {
        "storage": {"sqlite_enabled": False},
        "signals": {
            "duplicate_window_seconds": 120,
            "duplicate_price_threshold_pct": 0.5,
            "max_signal_lines": 5000,
        },
    }
    cfg.update(overrides)
    return MarketAgentStateManager(state_dir=state_dir, service_config=cfg)


def _make_signal(
    signal_type: str = "momentum",
    direction: str = "long",
    entry_price: float = 17500.0,
    timestamp: str | None = None,
    signal_id: str | None = None,
    **extra,
) -> dict:
    """Build a minimal signal dict suitable for save_signal()."""
    sig = {
        "type": signal_type,
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": entry_price - 20.0,
        "take_profit": entry_price + 40.0,
        "confidence": 0.75,
        "timestamp": timestamp or get_utc_timestamp(),
    }
    if signal_id:
        sig["signal_id"] = signal_id
    sig.update(extra)
    return sig


# ===================================================================
# save_signal
# ===================================================================

class TestSaveSignal:
    """Tests for MarketAgentStateManager.save_signal()."""

    def test_save_signal_creates_jsonl_with_one_record(self, tmp_path: Path) -> None:
        """A single save_signal call creates signals.jsonl with one record."""
        sm = _make_state_manager(tmp_path)
        sig = _make_signal(signal_id="sig_1")

        sm.save_signal(sig)

        assert sm.signals_file.exists()
        lines = sm.signals_file.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["signal_id"] == "sig_1"
        assert record["status"] == "generated"

    def test_save_wraps_signal_in_record(self, tmp_path: Path) -> None:
        """Saved record wraps the signal under a 'signal' key."""
        sm = _make_state_manager(tmp_path)
        sig = _make_signal(signal_id="wrap_test")

        sm.save_signal(sig)

        record = json.loads(sm.signals_file.read_text().strip())
        assert "signal" in record
        assert record["signal"]["type"] == "momentum"
        assert record["signal"]["direction"] == "long"

    def test_duplicate_signal_tagged_but_persisted(self, tmp_path: Path) -> None:
        """Duplicate signal within time+price window is tagged but still persisted."""
        sm = _make_state_manager(tmp_path)
        ts = get_utc_timestamp()
        sig1 = _make_signal(signal_id="dup_1", timestamp=ts, entry_price=17500.0)
        sig2 = _make_signal(signal_id="dup_2", timestamp=ts, entry_price=17500.0)

        sm.save_signal(sig1)
        sm.save_signal(sig2)

        lines = sm.signals_file.read_text().strip().splitlines()
        assert len(lines) == 2  # Both persisted
        rec2 = json.loads(lines[1])
        assert rec2.get("duplicate") is True

    def test_different_type_passes_dedup(self, tmp_path: Path) -> None:
        """Signals with different types are not considered duplicates."""
        sm = _make_state_manager(tmp_path)
        ts = get_utc_timestamp()
        sig1 = _make_signal(signal_id="a", signal_type="momentum", timestamp=ts)
        sig2 = _make_signal(signal_id="b", signal_type="reversal", timestamp=ts)

        sm.save_signal(sig1)
        sm.save_signal(sig2)

        lines = sm.signals_file.read_text().strip().splitlines()
        rec2 = json.loads(lines[1])
        assert rec2.get("duplicate") is not True

    def test_different_direction_passes_dedup(self, tmp_path: Path) -> None:
        """Signals with different directions are not considered duplicates."""
        sm = _make_state_manager(tmp_path)
        ts = get_utc_timestamp()
        sig1 = _make_signal(signal_id="x", direction="long", timestamp=ts)
        sig2 = _make_signal(signal_id="y", direction="short", timestamp=ts)

        sm.save_signal(sig1)
        sm.save_signal(sig2)

        lines = sm.signals_file.read_text().strip().splitlines()
        rec2 = json.loads(lines[1])
        assert rec2.get("duplicate") is not True

    def test_payload_serialization_with_nested_types(self, tmp_path: Path) -> None:
        """Signal with datetime and Path objects serializes to valid JSON."""
        sm = _make_state_manager(tmp_path)
        sig = _make_signal(signal_id="serial_test")
        sig["created_at"] = datetime(2025, 1, 1, tzinfo=timezone.utc)
        sig["config_path"] = Path("/tmp/test.yaml")

        sm.save_signal(sig)

        record = json.loads(sm.signals_file.read_text().strip())
        inner = record["signal"]
        assert isinstance(inner["created_at"], str)
        assert isinstance(inner["config_path"], str)

    def test_test_signals_not_persisted(self, tmp_path: Path) -> None:
        """Signals with _is_test=True are never persisted."""
        sm = _make_state_manager(tmp_path)
        sig = _make_signal(signal_id="test_sig", _is_test=True)

        sm.save_signal(sig)

        # File should not exist or be empty
        if sm.signals_file.exists():
            assert sm.signals_file.read_text().strip() == ""

    def test_signal_id_auto_generated_when_missing(self, tmp_path: Path) -> None:
        """If signal has no signal_id, one is auto-generated."""
        sm = _make_state_manager(tmp_path)
        sig = _make_signal()  # No signal_id

        sm.save_signal(sig)

        record = json.loads(sm.signals_file.read_text().strip())
        assert record["signal_id"]  # Non-empty
        assert "momentum" in record["signal_id"]

    def test_file_locking_allows_sequential_writes(self, tmp_path: Path) -> None:
        """Multiple sequential saves do not corrupt the file."""
        sm = _make_state_manager(tmp_path)

        for i in range(10):
            sm.save_signal(_make_signal(signal_id=f"seq_{i}"))

        lines = sm.signals_file.read_text().strip().splitlines()
        assert len(lines) == 10
        for line in lines:
            json.loads(line)  # Must be valid JSON


# ===================================================================
# get_recent_signals
# ===================================================================

class TestGetRecentSignals:
    """Tests for MarketAgentStateManager.get_recent_signals()."""

    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        """Empty signals file returns an empty list."""
        sm = _make_state_manager(tmp_path)
        sm.signals_file.write_text("", encoding="utf-8")

        result = sm.get_recent_signals()
        assert result == []

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        """Non-existent signals file returns an empty list."""
        sm = _make_state_manager(tmp_path)
        # Don't create the file
        assert not sm.signals_file.exists()

        result = sm.get_recent_signals()
        assert result == []

    def test_multiple_signals_returned(self, tmp_path: Path) -> None:
        """All saved signals are returned."""
        sm = _make_state_manager(tmp_path)
        for i in range(5):
            sm.save_signal(_make_signal(signal_id=f"multi_{i}"))

        result = sm.get_recent_signals()
        assert len(result) == 5
        assert result[0]["signal_id"] == "multi_0"
        assert result[4]["signal_id"] == "multi_4"

    def test_limit_respected(self, tmp_path: Path) -> None:
        """Limit parameter returns only the last N signals."""
        sm = _make_state_manager(tmp_path)
        for i in range(10):
            sm.save_signal(_make_signal(signal_id=f"lim_{i}"))

        result = sm.get_recent_signals(limit=3)
        assert len(result) == 3
        assert result[0]["signal_id"] == "lim_7"

    def test_corrupt_json_lines_skipped(self, tmp_path: Path) -> None:
        """Corrupt JSON lines in signals.jsonl are silently skipped."""
        sm = _make_state_manager(tmp_path)
        good = json.dumps({"signal_id": "good", "timestamp": get_utc_timestamp(), "status": "generated", "signal": {}})
        sm.signals_file.write_text(
            good + "\n" + "NOT VALID JSON\n" + good + "\n",
            encoding="utf-8",
        )

        result = sm.get_recent_signals()
        assert len(result) == 2


# ===================================================================
# save_state / load_state
# ===================================================================

class TestSaveLoadState:
    """Tests for save_state() and load_state() round-trip."""

    def test_round_trip(self, tmp_path: Path) -> None:
        """save_state → load_state preserves data."""
        sm = _make_state_manager(tmp_path)
        state = {"status": "running", "cycle_count": 42, "nested": {"key": "val"}}

        sm.save_state(state)
        loaded = sm.load_state()

        assert loaded["status"] == "running"
        assert loaded["cycle_count"] == 42
        assert loaded["nested"]["key"] == "val"
        assert "last_updated" in loaded

    def test_empty_state_round_trip(self, tmp_path: Path) -> None:
        """Saving an empty dict works and round-trips."""
        sm = _make_state_manager(tmp_path)

        sm.save_state({})
        loaded = sm.load_state()

        assert isinstance(loaded, dict)
        assert "last_updated" in loaded

    def test_load_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Loading when no state file exists returns {}."""
        sm = _make_state_manager(tmp_path)

        loaded = sm.load_state()
        assert loaded == {}

    def test_corrupt_state_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Corrupt state.json returns empty dict without raising."""
        sm = _make_state_manager(tmp_path)
        sm.state_file.write_text("{{CORRUPT}}", encoding="utf-8")

        loaded = sm.load_state()
        assert loaded == {}

    def test_overwrite_preserves_latest(self, tmp_path: Path) -> None:
        """Saving twice overwrites the first save."""
        sm = _make_state_manager(tmp_path)

        sm.save_state({"version": 1})
        sm.save_state({"version": 2})

        loaded = sm.load_state()
        assert loaded["version"] == 2


# ===================================================================
# append_event / get_recent_events
# ===================================================================

class TestAppendEvent:
    """Tests for append_event() and get_recent_events()."""

    def test_append_event_creates_valid_jsonl_line(self, tmp_path: Path) -> None:
        """A single append_event creates a valid JSONL line."""
        sm = _make_state_manager(tmp_path)

        sm.append_event("cycle_start", {"cycle": 1})

        events = sm.get_recent_events()
        assert len(events) == 1
        assert events[0]["type"] == "cycle_start"
        assert events[0]["payload"]["cycle"] == 1

    def test_multiple_events(self, tmp_path: Path) -> None:
        """Multiple events are appended in order."""
        sm = _make_state_manager(tmp_path)

        sm.append_event("start", {"n": 1})
        sm.append_event("tick", {"n": 2})
        sm.append_event("stop", {"n": 3})

        events = sm.get_recent_events()
        assert len(events) == 3
        assert events[0]["type"] == "start"
        assert events[2]["type"] == "stop"

    def test_event_level_stored(self, tmp_path: Path) -> None:
        """Optional level parameter is stored."""
        sm = _make_state_manager(tmp_path)

        sm.append_event("error_occurred", {"msg": "fail"}, level="error")

        events = sm.get_recent_events()
        assert events[0]["level"] == "error"

    def test_get_events_limit(self, tmp_path: Path) -> None:
        """get_recent_events respects the limit parameter."""
        sm = _make_state_manager(tmp_path)
        for i in range(20):
            sm.append_event("tick", {"i": i})

        events = sm.get_recent_events(limit=5)
        assert len(events) == 5
        assert events[0]["payload"]["i"] == 15  # Last 5

    def test_get_events_missing_file(self, tmp_path: Path) -> None:
        """get_recent_events on missing file returns empty list."""
        sm = _make_state_manager(tmp_path)
        assert sm.get_recent_events() == []

    def test_event_rotation_at_max_bytes(self, tmp_path: Path) -> None:
        """Events file is rotated when it exceeds 20 MB threshold."""
        sm = _make_state_manager(tmp_path)

        # Create an events file just over the rotation threshold
        big_payload = "x" * 1024  # 1 KB per event
        record = json.dumps({
            "timestamp": get_utc_timestamp(),
            "type": "filler",
            "level": None,
            "payload": {"data": big_payload},
        })
        # Write ~21 MB of data
        n_lines = (21 * 1024 * 1024) // (len(record) + 1) + 1
        with open(sm.events_file, "w") as f:
            for _ in range(n_lines):
                f.write(record + "\n")

        assert sm.events_file.stat().st_size > sm._event_log._EVENTS_MAX_BYTES

        # Next append triggers rotation
        sm.append_event("trigger_rotation", {"test": True})

        backup = Path(str(sm.events_file) + ".1")
        assert backup.exists()
        # New events file should be small (just the new event)
        assert sm.events_file.stat().st_size < sm._event_log._EVENTS_MAX_BYTES


# ===================================================================
# _is_duplicate_signal
# ===================================================================

class TestIsDuplicateSignal:
    """Tests for _is_duplicate_signal() internal method."""

    def test_time_based_dedup_within_window(self, tmp_path: Path) -> None:
        """Signal within time window AND price threshold is duplicate."""
        sm = _make_state_manager(tmp_path)
        now = datetime.now(timezone.utc)
        ts_now = now.isoformat()
        ts_recent = (now - timedelta(seconds=30)).isoformat()

        signal = {"type": "momentum", "direction": "long", "entry_price": 17500.0, "timestamp": ts_now}
        recent = [{"signal": {"type": "momentum", "direction": "long", "entry_price": 17500.0, "timestamp": ts_recent}}]

        assert sm._is_duplicate_signal(signal, recent) is True

    def test_time_based_dedup_outside_window(self, tmp_path: Path) -> None:
        """Signal outside time window is NOT duplicate."""
        sm = _make_state_manager(tmp_path)
        now = datetime.now(timezone.utc)
        ts_now = now.isoformat()
        ts_old = (now - timedelta(seconds=300)).isoformat()  # 5 min ago (window is 120s)

        signal = {"type": "momentum", "direction": "long", "entry_price": 17500.0, "timestamp": ts_now}
        recent = [{"signal": {"type": "momentum", "direction": "long", "entry_price": 17500.0, "timestamp": ts_old}}]

        assert sm._is_duplicate_signal(signal, recent) is False

    def test_price_based_dedup_within_threshold(self, tmp_path: Path) -> None:
        """Signal within price threshold AND time window is duplicate."""
        sm = _make_state_manager(tmp_path)
        now = datetime.now(timezone.utc)
        ts = now.isoformat()

        signal = {"type": "momentum", "direction": "long", "entry_price": 17500.0, "timestamp": ts}
        # Price difference: 17500 vs 17501 = 0.006% < 0.5% threshold
        recent = [{"signal": {"type": "momentum", "direction": "long", "entry_price": 17501.0, "timestamp": ts}}]

        assert sm._is_duplicate_signal(signal, recent) is True

    def test_price_based_dedup_outside_threshold(self, tmp_path: Path) -> None:
        """Signal with price far from recent is NOT duplicate (even within time window)."""
        sm = _make_state_manager(tmp_path)
        now = datetime.now(timezone.utc)
        ts = now.isoformat()

        signal = {"type": "momentum", "direction": "long", "entry_price": 17500.0, "timestamp": ts}
        # Price difference: 17500 vs 17700 = 1.14% > 0.5% threshold
        recent = [{"signal": {"type": "momentum", "direction": "long", "entry_price": 17700.0, "timestamp": ts}}]

        assert sm._is_duplicate_signal(signal, recent) is False

    def test_no_timestamp_not_duplicate(self, tmp_path: Path) -> None:
        """Signal without timestamp is never detected as duplicate."""
        sm = _make_state_manager(tmp_path)

        signal = {"type": "momentum", "direction": "long", "entry_price": 17500.0, "timestamp": ""}
        recent = [{"signal": {"type": "momentum", "direction": "long", "entry_price": 17500.0, "timestamp": get_utc_timestamp()}}]

        assert sm._is_duplicate_signal(signal, recent) is False

    def test_empty_recent_not_duplicate(self, tmp_path: Path) -> None:
        """With no recent signals, nothing is a duplicate."""
        sm = _make_state_manager(tmp_path)

        signal = {"type": "momentum", "direction": "long", "entry_price": 17500.0, "timestamp": get_utc_timestamp()}

        assert sm._is_duplicate_signal(signal, []) is False


# ===================================================================
# _rotate_signals_file
# ===================================================================

class TestRotateSignalsFile:
    """Tests for _rotate_signals_file() internal method."""

    def test_rotation_at_max_lines(self, tmp_path: Path) -> None:
        """File with more than max_signal_lines gets truncated."""
        cfg = {
            "storage": {"sqlite_enabled": False},
            "signals": {
                "duplicate_window_seconds": 120,
                "duplicate_price_threshold_pct": 0.5,
                "max_signal_lines": 10,
            },
        }
        sm = MarketAgentStateManager(state_dir=tmp_path, service_config=cfg)

        # Write 15 lines
        records = []
        for i in range(15):
            record = {"signal_id": f"rot_{i}", "timestamp": get_utc_timestamp(), "status": "generated", "signal": {}}
            records.append(json.dumps(record))
        sm.signals_file.write_text("\n".join(records) + "\n", encoding="utf-8")

        sm._signal_store._rotate_signals_file()

        # Should keep only 10 lines
        remaining = sm.signals_file.read_text().strip().splitlines()
        assert len(remaining) == 10
        # First remaining should be rot_5
        assert json.loads(remaining[0])["signal_id"] == "rot_5"

    def test_rotation_creates_archive(self, tmp_path: Path) -> None:
        """Rotation appends old lines to signals_archive.jsonl."""
        cfg = {
            "storage": {"sqlite_enabled": False},
            "signals": {
                "duplicate_window_seconds": 120,
                "duplicate_price_threshold_pct": 0.5,
                "max_signal_lines": 5,
            },
        }
        sm = MarketAgentStateManager(state_dir=tmp_path, service_config=cfg)

        # Write 8 lines
        records = []
        for i in range(8):
            record = {"signal_id": f"arc_{i}", "timestamp": get_utc_timestamp(), "status": "generated", "signal": {}}
            records.append(json.dumps(record))
        sm.signals_file.write_text("\n".join(records) + "\n", encoding="utf-8")

        sm._signal_store._rotate_signals_file()

        archive_file = sm.signals_file.parent / "signals_archive.jsonl"
        assert archive_file.exists()
        archived = archive_file.read_text().strip().splitlines()
        assert len(archived) == 3  # 8 - 5 = 3 archived

    def test_no_rotation_under_limit(self, tmp_path: Path) -> None:
        """No rotation when line count is at or below max."""
        cfg = {
            "storage": {"sqlite_enabled": False},
            "signals": {
                "duplicate_window_seconds": 120,
                "duplicate_price_threshold_pct": 0.5,
                "max_signal_lines": 100,
            },
        }
        sm = MarketAgentStateManager(state_dir=tmp_path, service_config=cfg)

        records = []
        for i in range(50):
            record = {"signal_id": f"nr_{i}", "timestamp": get_utc_timestamp(), "status": "generated", "signal": {}}
            records.append(json.dumps(record))
        sm.signals_file.write_text("\n".join(records) + "\n", encoding="utf-8")

        sm._signal_store._rotate_signals_file()

        remaining = sm.signals_file.read_text().strip().splitlines()
        assert len(remaining) == 50  # Unchanged

    def test_rotation_missing_file(self, tmp_path: Path) -> None:
        """Rotation on missing file does not raise."""
        sm = _make_state_manager(tmp_path)
        assert not sm.signals_file.exists()
        sm._signal_store._rotate_signals_file()  # Should not raise


# ===================================================================
# _to_json_safe
# ===================================================================

class TestToJsonSafe:
    """Tests for _to_json_safe() serialization helper."""

    def test_primitives_pass_through(self) -> None:
        assert _to_json_safe(42) == 42
        assert _to_json_safe("hello") == "hello"
        assert _to_json_safe(True) is True
        assert _to_json_safe(None) is None

    def test_datetime_converted_to_iso(self) -> None:
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = _to_json_safe(dt)
        assert isinstance(result, str)
        assert "2025-06-15" in result

    def test_path_converted_to_string(self) -> None:
        p = Path("/tmp/test.json")
        result = _to_json_safe(p)
        assert result == "/tmp/test.json"

    def test_nested_dict_converted(self) -> None:
        obj = {"dt": datetime(2025, 1, 1, tzinfo=timezone.utc), "p": Path("/x")}
        result = _to_json_safe(obj)
        assert isinstance(result["dt"], str)
        assert result["p"] == "/x"

    def test_sets_converted_to_list(self) -> None:
        result = _to_json_safe({1, 2, 3})
        assert isinstance(result, list)
        assert sorted(result) == [1, 2, 3]


# ===================================================================
# Dual-write failure resilience
# ===================================================================

class TestDualWriteFailure:
    """Tests for dual-write behavior when SQLite fails but JSON succeeds.

    The save_signal() method writes to JSON first, then optionally to SQLite.
    When SQLite fails, the signal must still be persisted to JSON and a warning
    must be logged about the divergence.
    """

    @staticmethod
    def _make_sqlite_enabled_manager(state_dir: Path) -> MarketAgentStateManager:
        """Create a state manager with SQLite dual-write enabled via mock."""
        sm = _make_state_manager(state_dir)
        sm._signal_store._sqlite_enabled = True
        sm._signal_store._trade_db = MagicMock()
        sm._signal_store._async_sqlite_queue = None  # Use blocking write path
        return sm

    def test_json_persists_when_sqlite_fails(self, tmp_path: Path) -> None:
        """Signal is persisted to JSON even when SQLite write raises."""
        sm = self._make_sqlite_enabled_manager(tmp_path)
        sm._signal_store._trade_db.add_signal_event.side_effect = RuntimeError("SQLite disk error")

        sig = _make_signal(signal_id="dw_json_ok")
        sm.save_signal(sig)

        assert sm.signals_file.exists()
        lines = sm.signals_file.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["signal_id"] == "dw_json_ok"
        assert record["status"] == "generated"

    def test_warning_logged_on_sqlite_divergence(self, tmp_path: Path) -> None:
        """Warning is logged when SQLite write fails after JSON write succeeds."""
        sm = self._make_sqlite_enabled_manager(tmp_path)
        sm._signal_store._trade_db.add_signal_event.side_effect = RuntimeError("DB locked")

        sig = _make_signal(signal_id="dw_warn")
        with patch("pearlalgo.market_agent.state_manager.logger") as mock_logger:
            sm.save_signal(sig)

        debug_calls = mock_logger.debug.call_args_list
        assert any("SQLite dual-write skipped" in str(c) for c in debug_calls), \
            f"Expected 'SQLite dual-write skipped' debug message, got: {debug_calls}"

    def test_json_data_complete_after_sqlite_error(self, tmp_path: Path) -> None:
        """All signals are complete in JSON even with continuous SQLite failures."""
        sm = self._make_sqlite_enabled_manager(tmp_path)
        sm._signal_store._trade_db.add_signal_event.side_effect = RuntimeError("SQLite crash")

        for i in range(5):
            sm.save_signal(_make_signal(signal_id=f"dw_multi_{i}"))

        lines = sm.signals_file.read_text().strip().splitlines()
        assert len(lines) == 5
        signal_ids = [json.loads(line)["signal_id"] for line in lines]
        assert signal_ids == [f"dw_multi_{i}" for i in range(5)]
