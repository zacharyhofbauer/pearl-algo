"""
Failure-mode tests for SignalForwarder (signal_forwarder.py).

Covers:
- File rotation detection (offset reset when file shrinks or inode changes)
- Follower starting before the shared file exists
- Reading from an empty file
- Inode change detection via os.replace
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from pearlalgo.market_agent.signal_forwarder import SignalForwarder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_forwarder(shared_file: Path, mode: str = "follower") -> SignalForwarder:
    """Create a SignalForwarder configured for the given shared file."""
    return SignalForwarder({
        "enabled": True,
        "mode": mode,
        "shared_file": str(shared_file),
        "max_lines": 500,
    })


def _write_signal_record(path: Path, direction: str, bar_ts: str) -> None:
    """Append a minimal valid signal record to the JSONL file."""
    record = {
        "signal_id": f"sig_{direction}_{bar_ts}",
        "bar_timestamp": bar_ts,
        "timestamp": "2025-01-01T00:00:00Z",
        "signal": {
            "direction": direction,
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17540.0,
            "position_size": 1,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignalForwarderFailures:
    """Failure-mode tests for SignalForwarder read path."""

    def test_follower_resets_offset_after_file_rotation(self, tmp_path):
        """After file rotation (shorter file replaces longer), follower resets
        offset and reads from the start of the new file."""
        shared_file = tmp_path / "shared_signals.jsonl"
        fwd = _make_forwarder(shared_file)

        # Write 5 signals and read them all so offset advances
        for i in range(5):
            _write_signal_record(shared_file, "long", f"2025-01-01T00:{i:02d}:00Z")

        first_read = fwd.read_shared_signals()
        assert len(first_read) == 5, "Should read all 5 initial signals"
        assert fwd._last_read_offset > 0, "Offset should have advanced"

        old_offset = fwd._last_read_offset

        # Simulate rotation: replace file with a shorter one (only 2 signals)
        new_file = tmp_path / "new_signals.jsonl"
        _write_signal_record(new_file, "short", "2025-02-01T00:00:00Z")
        _write_signal_record(new_file, "short", "2025-02-01T00:01:00Z")
        os.replace(str(new_file), str(shared_file))

        # The new file is shorter than old_offset, so offset must reset
        second_read = fwd.read_shared_signals()
        assert len(second_read) == 2, (
            f"After rotation, should read 2 new signals from start; got {len(second_read)}"
        )

    def test_follower_handles_file_not_found(self, tmp_path):
        """Follower returns empty list when shared_signals.jsonl doesn't exist yet."""
        nonexistent = tmp_path / "does_not_exist" / "shared_signals.jsonl"
        fwd = _make_forwarder(nonexistent)

        signals = fwd.read_shared_signals()
        assert signals == [], "Should return empty list when file doesn't exist"
        assert fwd._last_read_offset == 0, "Offset should be 0 for missing file"

    def test_follower_handles_empty_file(self, tmp_path):
        """Follower returns empty list when the file exists but is empty."""
        shared_file = tmp_path / "shared_signals.jsonl"
        shared_file.touch()  # Create empty file

        fwd = _make_forwarder(shared_file)

        signals = fwd.read_shared_signals()
        assert signals == [], "Should return empty list for empty file"

    def test_follower_detects_inode_change(self, tmp_path):
        """When os.replace swaps the file, the inode changes and
        the follower resets its read offset to 0."""
        shared_file = tmp_path / "shared_signals.jsonl"
        fwd = _make_forwarder(shared_file)

        # Write initial signals and read them
        _write_signal_record(shared_file, "long", "2025-01-01T00:00:00Z")
        _write_signal_record(shared_file, "long", "2025-01-01T00:01:00Z")
        first_read = fwd.read_shared_signals()
        assert len(first_read) == 2

        # Capture inode of original file
        original_inode = fwd._last_file_inode
        assert original_inode is not None

        # Create a new file with different content and swap via os.replace
        replacement = tmp_path / "replacement.jsonl"
        _write_signal_record(replacement, "short", "2025-03-01T00:00:00Z")
        os.replace(str(replacement), str(shared_file))

        # Verify the inode actually changed (sanity check)
        new_inode = os.stat(shared_file).st_ino
        assert new_inode != original_inode, (
            "os.replace should produce a new inode on this filesystem"
        )

        # Read again — offset should reset due to inode change
        second_read = fwd.read_shared_signals()
        assert len(second_read) == 1, (
            f"After inode change, should read 1 signal from new file; got {len(second_read)}"
        )
        assert second_read[0]["direction"] == "short"
