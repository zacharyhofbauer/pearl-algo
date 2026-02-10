"""
Tests for SignalForwarder – write/read round-trip, dedup logic,
corruption recovery, file management, market-hours filtering,
and stale signal cleanup.

Tests:
- Write/read round-trip (write signal, read back, verify fields)
- Multiple-signal write and read
- Disabled forwarder gating (writer_mode / follower_mode flags)
- Dedup: skip already-processed, allow different direction/bar_timestamp
- Dedup pruning: OrderedDict trimming at _DEDUP_MAX_KEYS boundary
- Corruption recovery: malformed JSON, empty file, missing file
- File management: parent directory creation on write
- Market hours filtering: skip processing when market is closed
- Stale signal cleanup: remove file on follower startup
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.market_agent.signal_forwarder import (
    SignalForwarder,
    _DEDUP_MAX_KEYS,
    _DEDUP_TRIM_TARGET,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _writer_config(shared_file: str) -> dict:
    """Minimal writer-mode configuration."""
    return {
        "enabled": True,
        "mode": "writer",
        "shared_file": shared_file,
        "max_lines": 500,
    }


def _follower_config(shared_file: str) -> dict:
    """Minimal follower-mode configuration."""
    return {
        "enabled": True,
        "mode": "follower",
        "shared_file": shared_file,
    }


def _make_signal(direction: str = "long", **overrides) -> dict:
    """Create a minimal signal dict with sensible defaults."""
    sig = {
        "direction": direction,
        "type": "momentum_ema_cross",
        "entry_price": 17500.0,
        "stop_loss": 17480.0,
        "take_profit": 17540.0,
        "confidence": 0.75,
        "symbol": "MNQ",
    }
    sig.update(overrides)
    return sig


def _write_jsonl_record(
    path: Path,
    *,
    direction: str = "long",
    bar_timestamp: str = "2025-06-02T14:30:00Z",
    signal_id: str = "sig-001",
    extra_signal_fields: dict | None = None,
) -> None:
    """Append a well-formed JSONL record directly (bypasses SignalForwarder.write)."""
    sig = _make_signal(direction)
    if extra_signal_fields:
        sig.update(extra_signal_fields)
    record = {
        "signal_id": signal_id,
        "bar_timestamp": bar_timestamp,
        "timestamp": "2025-06-02T14:30:05Z",
        "signal": sig,
    }
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


# =========================================================================
# Write / Read round-trip
# =========================================================================


@patch(
    "pearlalgo.market_agent.signal_forwarder.get_utc_timestamp",
    return_value="2025-06-02T14:30:05Z",
)
def test_write_and_read_round_trip(_mock_ts, tmp_path):
    """Write a signal via writer, read it back via follower, verify fields match exactly."""
    shared = tmp_path / "signals.jsonl"
    writer = SignalForwarder(_writer_config(str(shared)))
    follower = SignalForwarder(_follower_config(str(shared)))

    signal = _make_signal("long", entry_price=17550.0, confidence=0.82)
    writer.write_shared_signal(
        signal, signal_id="sig-aaa", bar_timestamp="2025-06-02T14:30:00Z"
    )

    results = follower.read_shared_signals()

    assert len(results) == 1
    s = results[0]
    assert s["direction"] == "long"
    assert s["entry_price"] == 17550.0
    assert s["confidence"] == 0.82
    assert s["symbol"] == "MNQ"
    assert s["type"] == "momentum_ema_cross"
    assert s["stop_loss"] == 17480.0
    assert s["take_profit"] == 17540.0
    # position_size defaults to 1 when not set by the strategy
    assert s["position_size"] == 1


@patch(
    "pearlalgo.market_agent.signal_forwarder.get_utc_timestamp",
    return_value="2025-06-02T14:30:05Z",
)
def test_write_multiple_signals(_mock_ts, tmp_path):
    """Write three signals with distinct (direction, bar_timestamp) pairs and read all back."""
    shared = tmp_path / "signals.jsonl"
    writer = SignalForwarder(_writer_config(str(shared)))
    follower = SignalForwarder(_follower_config(str(shared)))

    writer.write_shared_signal(
        _make_signal("long"),
        signal_id="sig-001",
        bar_timestamp="2025-06-02T14:30:00Z",
    )
    writer.write_shared_signal(
        _make_signal("short"),
        signal_id="sig-002",
        bar_timestamp="2025-06-02T14:35:00Z",
    )
    writer.write_shared_signal(
        _make_signal("long"),
        signal_id="sig-003",
        bar_timestamp="2025-06-02T14:40:00Z",
    )

    results = follower.read_shared_signals()

    assert len(results) == 3
    assert results[0]["direction"] == "long"
    assert results[1]["direction"] == "short"
    assert results[2]["direction"] == "long"


def test_disabled_forwarder_writes_nothing(tmp_path):
    """When disabled, writer_mode and follower_mode are False — write never occurs."""
    shared = tmp_path / "signals.jsonl"
    fwd = SignalForwarder(
        {"enabled": False, "mode": "writer", "shared_file": str(shared)}
    )

    assert fwd.writer_mode is False
    assert fwd.follower_mode is False
    # The shared file is never created because the service checks
    # writer_mode before calling write_shared_signal.
    assert not shared.exists()


# =========================================================================
# Dedup logic
# =========================================================================


def test_dedup_skips_already_processed_signal(tmp_path):
    """Same (direction, bar_timestamp) pair is returned only once even if duplicated in file."""
    shared = tmp_path / "signals.jsonl"
    follower = SignalForwarder(_follower_config(str(shared)))

    _write_jsonl_record(
        shared,
        direction="long",
        bar_timestamp="2025-06-02T14:30:00Z",
        signal_id="sig-001",
    )
    _write_jsonl_record(
        shared,
        direction="long",
        bar_timestamp="2025-06-02T14:30:00Z",
        signal_id="sig-002",
    )

    results = follower.read_shared_signals()

    assert len(results) == 1
    assert results[0]["direction"] == "long"


def test_dedup_allows_different_direction(tmp_path):
    """Different direction passes dedup even with the same bar_timestamp."""
    shared = tmp_path / "signals.jsonl"
    follower = SignalForwarder(_follower_config(str(shared)))

    _write_jsonl_record(
        shared,
        direction="long",
        bar_timestamp="2025-06-02T14:30:00Z",
        signal_id="sig-001",
    )
    _write_jsonl_record(
        shared,
        direction="short",
        bar_timestamp="2025-06-02T14:30:00Z",
        signal_id="sig-002",
    )

    results = follower.read_shared_signals()

    assert len(results) == 2
    directions = {s["direction"] for s in results}
    assert directions == {"long", "short"}


def test_dedup_allows_different_bar_timestamp(tmp_path):
    """Different bar_timestamp passes dedup even with the same direction."""
    shared = tmp_path / "signals.jsonl"
    follower = SignalForwarder(_follower_config(str(shared)))

    _write_jsonl_record(
        shared,
        direction="long",
        bar_timestamp="2025-06-02T14:30:00Z",
        signal_id="sig-001",
    )
    _write_jsonl_record(
        shared,
        direction="long",
        bar_timestamp="2025-06-02T14:35:00Z",
        signal_id="sig-002",
    )

    results = follower.read_shared_signals()

    assert len(results) == 2


def test_dedup_pruning_preserves_recent_history(tmp_path):
    """After exceeding _DEDUP_MAX_KEYS, oldest keys are trimmed to _DEDUP_TRIM_TARGET."""
    shared = tmp_path / "signals.jsonl"
    follower = SignalForwarder(_follower_config(str(shared)))

    total = _DEDUP_MAX_KEYS + 1  # 2001 – just enough to trigger pruning

    with open(shared, "w") as f:
        for i in range(total):
            record = {
                "signal_id": f"sig-{i:05d}",
                "bar_timestamp": f"bar-{i:05d}",
                "timestamp": "2025-06-02T00:00:00Z",
                "signal": {"direction": "long", "entry_price": 17500.0},
            }
            f.write(json.dumps(record) + "\n")

    results = follower.read_shared_signals()

    # All keys are unique → every signal is returned
    assert len(results) == total

    # Pruning should have reduced the internal dedup map to _DEDUP_TRIM_TARGET
    assert len(follower._processed_keys) == _DEDUP_TRIM_TARGET

    # Most-recent key must survive pruning
    last_bar = f"bar-{total - 1:05d}"
    assert ("long", last_bar) in follower._processed_keys

    # Oldest key must have been evicted
    assert ("long", "bar-00000") not in follower._processed_keys


def test_dedup_uses_ordered_dict(tmp_path):
    """Internal _processed_keys is an OrderedDict, not a plain dict."""
    follower = SignalForwarder(_follower_config(str(tmp_path / "signals.jsonl")))
    assert isinstance(follower._processed_keys, OrderedDict)


# =========================================================================
# Corruption recovery
# =========================================================================


def test_read_skips_malformed_json_lines(tmp_path):
    """Malformed JSON lines are silently skipped; valid lines are still returned."""
    shared = tmp_path / "signals.jsonl"
    valid_record = json.dumps(
        {
            "signal_id": "sig-ok",
            "bar_timestamp": "2025-06-02T14:30:00Z",
            "timestamp": "2025-06-02T14:30:05Z",
            "signal": {"direction": "long", "entry_price": 17500.0},
        }
    )
    shared.write_text(
        "NOT VALID JSON\n"
        '{"truncated": tru\n'
        f"{valid_record}\n"
    )

    follower = SignalForwarder(_follower_config(str(shared)))
    results = follower.read_shared_signals()

    assert len(results) == 1
    assert results[0]["direction"] == "long"
    assert results[0]["entry_price"] == 17500.0


def test_read_handles_empty_file(tmp_path):
    """Empty file returns an empty list without raising."""
    shared = tmp_path / "signals.jsonl"
    shared.write_text("")

    follower = SignalForwarder(_follower_config(str(shared)))
    results = follower.read_shared_signals()

    assert results == []


def test_read_handles_missing_file(tmp_path):
    """Missing file returns an empty list without raising."""
    shared = tmp_path / "signals.jsonl"
    assert not shared.exists()

    follower = SignalForwarder(_follower_config(str(shared)))
    results = follower.read_shared_signals()

    assert results == []


# =========================================================================
# File management
# =========================================================================


@patch(
    "pearlalgo.market_agent.signal_forwarder.get_utc_timestamp",
    return_value="2025-06-02T14:30:05Z",
)
def test_write_creates_parent_directory(_mock_ts, tmp_path):
    """Parent directories are created automatically when write_shared_signal is called."""
    shared = tmp_path / "deep" / "nested" / "dir" / "signals.jsonl"
    assert not shared.parent.exists()

    writer = SignalForwarder(_writer_config(str(shared)))
    writer.write_shared_signal(
        _make_signal("long"),
        signal_id="sig-dir",
        bar_timestamp="2025-06-02T14:30:00Z",
    )

    assert shared.exists()
    assert shared.parent.is_dir()


# =========================================================================
# Market hours filtering
# =========================================================================


def test_process_forwarded_signals_skips_when_market_closed(tmp_path):
    """No signals are processed when get_market_hours().is_market_open() returns False."""
    shared = tmp_path / "signals.jsonl"
    _write_jsonl_record(
        shared, direction="long", bar_timestamp="2025-06-02T14:30:00Z"
    )

    follower = SignalForwarder(_follower_config(str(shared)))

    mock_handler = MagicMock()
    mock_handler.process_signal = AsyncMock()
    mock_sync = MagicMock()

    mock_mh = MagicMock()
    mock_mh.is_market_open.return_value = False

    with patch(
        "pearlalgo.market_agent.signal_forwarder.get_market_hours",
        return_value=mock_mh,
    ):
        asyncio.run(follower.process_forwarded_signals(mock_handler, mock_sync))

    mock_handler.process_signal.assert_not_called()
    mock_sync.assert_not_called()


# =========================================================================
# Stale signal cleanup
# =========================================================================


def test_clear_stale_signals_removes_file(tmp_path):
    """File is removed when clear_stale_signals is called on follower startup."""
    shared = tmp_path / "signals.jsonl"
    shared.write_text('{"some": "data"}\n')
    assert shared.exists()

    follower = SignalForwarder(_follower_config(str(shared)))
    follower.clear_stale_signals()

    assert not shared.exists()


def test_clear_stale_signals_handles_missing_file(tmp_path):
    """No error raised when clear_stale_signals is called and file does not exist."""
    shared = tmp_path / "signals.jsonl"
    assert not shared.exists()

    follower = SignalForwarder(_follower_config(str(shared)))
    follower.clear_stale_signals()  # must not raise

    assert not shared.exists()
