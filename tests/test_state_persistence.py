"""
State persistence tests for the NQ Agent State Manager.

These tests validate:
1. Basic save/load functionality
2. Corruption recovery (malformed JSON)
3. Missing file handling
4. Concurrent access safety
5. Edge cases in signal serialization

Test Philosophy:
- State persistence is critical for system recovery
- Corruption should not crash the system
- Data integrity is verifiable
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import pytest

from pearlalgo.nq_agent.state_manager import NQAgentStateManager, _to_json_safe


class TestToJsonSafe:
    """Tests for the _to_json_safe helper function."""

    def test_primitive_types_unchanged(self) -> None:
        """Test that JSON primitives pass through unchanged."""
        assert _to_json_safe(None) is None
        assert _to_json_safe(True) is True
        assert _to_json_safe(42) == 42
        assert _to_json_safe(3.14) == 3.14
        assert _to_json_safe("hello") == "hello"

    def test_dict_recursively_converted(self) -> None:
        """Test that dicts are recursively converted."""
        result = _to_json_safe({"a": 1, "b": {"c": 2}})
        assert result == {"a": 1, "b": {"c": 2}}

    def test_list_recursively_converted(self) -> None:
        """Test that lists are recursively converted."""
        result = _to_json_safe([1, [2, 3], {"a": 4}])
        assert result == [1, [2, 3], {"a": 4}]

    def test_datetime_to_isoformat(self) -> None:
        """Test that datetime objects are converted to ISO format."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = _to_json_safe(dt)
        assert result == "2024-01-15T10:30:00+00:00"

    def test_path_to_string(self) -> None:
        """Test that Path objects are converted to strings."""
        p = Path("/some/path/to/file.txt")
        result = _to_json_safe(p)
        assert result == "/some/path/to/file.txt"

    def test_numpy_scalar_to_python(self) -> None:
        """Test that numpy scalars are converted to Python types."""
        result = _to_json_safe(np.float64(3.14))
        assert result == 3.14
        assert isinstance(result, float)

        result = _to_json_safe(np.int64(42))
        assert result == 42
        assert isinstance(result, int)

    def test_numpy_array_to_list(self) -> None:
        """Test that numpy arrays are converted to lists."""
        arr = np.array([1, 2, 3])
        result = _to_json_safe(arr)
        assert result == [1, 2, 3]

    def test_pandas_timestamp_to_isoformat(self) -> None:
        """Test that pandas Timestamps are converted to ISO format."""
        ts = pd.Timestamp("2024-01-15 10:30:00", tz="UTC")
        result = _to_json_safe(ts)
        assert "2024-01-15" in result
        assert "10:30:00" in result

    def test_pandas_series_to_dict(self) -> None:
        """Test that pandas Series are converted to dicts."""
        s = pd.Series({"a": 1, "b": 2})
        result = _to_json_safe(s)
        assert result == {"a": 1, "b": 2}

    def test_unknown_type_to_string(self) -> None:
        """Test that unknown types are converted to strings."""
        class CustomClass:
            def __str__(self):
                return "custom_object"
        
        result = _to_json_safe(CustomClass())
        assert result == "custom_object"


class TestStateManagerBasics:
    """Basic functionality tests for NQAgentStateManager."""

    def test_init_creates_state_dir(self, tmp_path: Path) -> None:
        """Test that initialization creates the state directory."""
        state_dir = tmp_path / "new_state_dir"
        assert not state_dir.exists()
        
        manager = NQAgentStateManager(state_dir=state_dir)
        
        assert state_dir.exists()
        assert manager.state_dir == state_dir

    def test_save_and_load_state(self, tmp_path: Path) -> None:
        """Test that state can be saved and loaded."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        state = {
            "cycle_count": 100,
            "signal_count": 5,
            "running": True,
        }
        
        manager.save_state(state)
        loaded = manager.load_state()
        
        assert loaded["cycle_count"] == 100
        assert loaded["signal_count"] == 5
        assert loaded["running"] is True
        assert "last_updated" in loaded  # Automatically added

    def test_load_nonexistent_state_returns_empty(self, tmp_path: Path) -> None:
        """Test that loading non-existent state returns empty dict."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        loaded = manager.load_state()
        
        assert loaded == {}

    def test_save_signal(self, tmp_path: Path) -> None:
        """Test that signals are saved correctly."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        signal = {
            "signal_id": "test_signal_1",
            "type": "breakout",
            "direction": "long",
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17550.0,
            "confidence": 0.75,
        }
        
        manager.save_signal(signal)
        
        signals = manager.get_recent_signals()
        assert len(signals) == 1
        assert signals[0]["signal_id"] == "test_signal_1"
        assert signals[0]["status"] == "generated"
        assert signals[0]["signal"]["type"] == "breakout"

    def test_get_recent_signals_limit(self, tmp_path: Path) -> None:
        """Test that get_recent_signals respects limit."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        # Save 10 signals
        for i in range(10):
            signal = {
                "signal_id": f"signal_{i}",
                "type": "test",
                "direction": "long",
            }
            manager.save_signal(signal)
        
        # Get last 3
        signals = manager.get_recent_signals(limit=3)
        assert len(signals) == 3
        assert signals[-1]["signal_id"] == "signal_9"


class TestCorruptionRecovery:
    """Tests for corruption handling and recovery."""

    def test_load_corrupted_state_returns_empty(self, tmp_path: Path) -> None:
        """
        Assumption: Corrupted state file should not crash, returns empty dict.
        Failure signal: Exception raised or non-empty corrupted data returned
        Test type: Deterministic
        """
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        # Write corrupted JSON
        with open(manager.state_file, "w") as f:
            f.write("{ this is not valid json }")
        
        loaded = manager.load_state()
        
        assert loaded == {}

    def test_load_signals_with_corrupted_lines(self, tmp_path: Path) -> None:
        """
        Assumption: Corrupted lines in signals file should be skipped.
        Failure signal: Exception or corrupted signals returned
        Test type: Deterministic
        """
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        # Write valid signal
        manager.save_signal({"signal_id": "valid_1", "type": "test"})
        
        # Append corrupted line
        with open(manager.signals_file, "a") as f:
            f.write("{ invalid json }\n")
        
        # Write another valid signal
        manager.save_signal({"signal_id": "valid_2", "type": "test"})
        
        signals = manager.get_recent_signals()
        
        # Should have 2 valid signals, corrupted line skipped
        assert len(signals) == 2
        assert signals[0]["signal_id"] == "valid_1"
        assert signals[1]["signal_id"] == "valid_2"

    def test_empty_signals_file_returns_empty(self, tmp_path: Path) -> None:
        """Test that empty signals file returns empty list."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        # Create empty file
        manager.signals_file.touch()
        
        signals = manager.get_recent_signals()
        
        assert signals == []

    def test_overwrite_corrupted_state(self, tmp_path: Path) -> None:
        """Test that saving state overwrites corrupted state."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        # Write corrupted state
        with open(manager.state_file, "w") as f:
            f.write("corrupted")
        
        # Save valid state
        manager.save_state({"cycle_count": 42})
        
        # Should be able to load it
        loaded = manager.load_state()
        assert loaded["cycle_count"] == 42


class TestEdgeCaseSerialization:
    """Tests for edge cases in signal serialization."""

    def test_signal_with_numpy_types(self, tmp_path: Path) -> None:
        """Test that signals with numpy types are serialized correctly."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        signal = {
            "signal_id": "numpy_signal",
            "type": "test",
            "entry_price": np.float64(17500.25),
            "confidence": np.float32(0.75),
            "volume": np.int64(1000),
        }
        
        manager.save_signal(signal)
        signals = manager.get_recent_signals()
        
        assert len(signals) == 1
        assert signals[0]["signal"]["entry_price"] == 17500.25

    def test_signal_with_pandas_timestamp(self, tmp_path: Path) -> None:
        """Test that signals with pandas timestamps are serialized correctly."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        signal = {
            "signal_id": "timestamp_signal",
            "type": "test",
            "timestamp": pd.Timestamp("2024-01-15 10:30:00", tz="UTC"),
        }
        
        manager.save_signal(signal)
        signals = manager.get_recent_signals()
        
        assert len(signals) == 1
        assert "2024-01-15" in signals[0]["signal"]["timestamp"]

    def test_signal_with_nested_numpy_array(self, tmp_path: Path) -> None:
        """Test that signals with nested numpy arrays are serialized."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        signal = {
            "signal_id": "array_signal",
            "type": "test",
            "indicators": {
                "sma": np.array([100.0, 101.0, 102.0]),
            }
        }
        
        manager.save_signal(signal)
        signals = manager.get_recent_signals()
        
        assert len(signals) == 1
        assert signals[0]["signal"]["indicators"]["sma"] == [100.0, 101.0, 102.0]

    def test_signal_with_nan_values(self, tmp_path: Path) -> None:
        """Test that signals with NaN values don't crash serialization."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        signal = {
            "signal_id": "nan_signal",
            "type": "test",
            "value": float('nan'),  # NaN is valid JSON (null after serialization issues)
        }
        
        # Should not raise
        manager.save_signal(signal)
        signals = manager.get_recent_signals()
        
        assert len(signals) == 1

    def test_signal_with_inf_values(self, tmp_path: Path) -> None:
        """Test that signals with inf values don't crash serialization."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        signal = {
            "signal_id": "inf_signal",
            "type": "test",
            "value": float('inf'),
        }
        
        # Should not raise
        manager.save_signal(signal)
        signals = manager.get_recent_signals()
        
        # Note: JSON doesn't support inf, so it may be serialized as string or null
        assert len(signals) == 1


class TestFilePermissions:
    """Tests for file permission handling."""

    def test_read_only_signals_file_recovers(self, tmp_path: Path) -> None:
        """
        Assumption: Read-only signals file should not crash save_signal.
        Failure signal: Unhandled PermissionError
        Test type: Deterministic
        """
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        # Create signals file and make it read-only
        manager.signals_file.touch()
        os.chmod(manager.signals_file, 0o444)
        
        try:
            # Should not raise (logs error instead)
            manager.save_signal({"signal_id": "test", "type": "test"})
        finally:
            # Restore permissions for cleanup
            os.chmod(manager.signals_file, 0o644)

    def test_read_only_state_file_recovers(self, tmp_path: Path) -> None:
        """
        Assumption: Read-only state file should not crash save_state.
        Failure signal: Unhandled PermissionError
        Test type: Deterministic
        """
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        # Create state file and make it read-only
        manager.save_state({"initial": True})
        os.chmod(manager.state_file, 0o444)
        
        try:
            # Should not raise (logs error instead)
            manager.save_state({"updated": True})
        finally:
            # Restore permissions for cleanup
            os.chmod(manager.state_file, 0o644)


class TestConcurrentAccess:
    """Tests for concurrent access safety."""

    def test_multiple_signal_saves_atomic(self, tmp_path: Path) -> None:
        """
        Assumption: Multiple save_signal calls should not corrupt the file.
        Failure signal: Corrupted signals file
        Test type: Deterministic
        
        Note: This is a basic test. True concurrent access would require
        multiprocessing or threading, which is out of scope for unit tests.
        """
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        # Save many signals in sequence
        for i in range(100):
            signal = {
                "signal_id": f"signal_{i}",
                "type": "test",
                "index": i,
            }
            manager.save_signal(signal)
        
        signals = manager.get_recent_signals(limit=100)
        
        assert len(signals) == 100
        # Verify order
        for i, sig in enumerate(signals):
            assert sig["signal"]["index"] == i


class TestStateIntegrity:
    """Tests for state data integrity."""

    def test_state_preserves_all_fields(self, tmp_path: Path) -> None:
        """Test that all state fields are preserved across save/load."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        state = {
            "cycle_count": 12345,
            "signal_count": 42,
            "error_count": 3,
            "running": True,
            "paused": False,
            "start_time": "2024-01-15T10:30:00+00:00",
            "nested": {
                "deep": {
                    "value": 100
                }
            },
            "list_data": [1, 2, 3, "four"],
        }
        
        manager.save_state(state)
        loaded = manager.load_state()
        
        assert loaded["cycle_count"] == 12345
        assert loaded["signal_count"] == 42
        assert loaded["error_count"] == 3
        assert loaded["running"] is True
        assert loaded["paused"] is False
        assert loaded["nested"]["deep"]["value"] == 100
        assert loaded["list_data"] == [1, 2, 3, "four"]

    def test_signal_record_format(self, tmp_path: Path) -> None:
        """Test that signal records have expected format for /signals command."""
        manager = NQAgentStateManager(state_dir=tmp_path)
        
        signal = {
            "signal_id": "format_test",
            "type": "breakout",
            "direction": "long",
            "entry_price": 17500.0,
        }
        
        manager.save_signal(signal)
        signals = manager.get_recent_signals()
        
        record = signals[0]
        
        # Required fields for /signals command
        assert "signal_id" in record
        assert "timestamp" in record
        assert "status" in record
        assert "signal" in record
        
        # Signal dict should contain original data
        assert record["signal"]["type"] == "breakout"
        assert record["signal"]["direction"] == "long"








