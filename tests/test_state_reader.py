"""
Tests for StateReader - safe concurrent reading of agent state files.

Validates:
1. read_state() returns state dict or empty dict if missing
2. read_signals() returns signal list and respects max_lines
3. read_challenge_state() returns None if missing, dict if present
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pearlalgo.market_agent.state_reader import StateReader


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """Create a temporary state directory for StateReader."""
    d = tmp_path / "agent_state"
    d.mkdir()
    return d


@pytest.fixture
def reader(state_dir: Path) -> StateReader:
    """Return a StateReader pointed at the temp state directory."""
    return StateReader(state_dir)


# ---------------------------------------------------------------------------
# read_state
# ---------------------------------------------------------------------------

class TestReadState:
    """Tests for StateReader.read_state."""

    def test_returns_state_dict(self, state_dir: Path, reader: StateReader) -> None:
        """Existing state.json is read and returned as dict."""
        payload = {"status": "running", "pnl": 123.45}
        (state_dir / "state.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        result = reader.read_state()

        assert result == payload

    def test_missing_file_returns_empty_dict(self, reader: StateReader) -> None:
        """Missing state.json returns empty dict without raising."""
        result = reader.read_state()

        assert result == {}

    def test_corrupt_file_returns_empty_dict(
        self, state_dir: Path, reader: StateReader
    ) -> None:
        """Malformed state.json returns empty dict."""
        (state_dir / "state.json").write_text("{{bad json", encoding="utf-8")

        result = reader.read_state()

        assert result == {}


# ---------------------------------------------------------------------------
# read_signals
# ---------------------------------------------------------------------------

class TestReadSignals:
    """Tests for StateReader.read_signals."""

    def test_returns_signal_list(
        self, state_dir: Path, reader: StateReader
    ) -> None:
        """Existing signals.jsonl is parsed into a list of dicts."""
        rows = [{"signal": "buy", "ts": 1}, {"signal": "sell", "ts": 2}]
        (state_dir / "signals.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows),
            encoding="utf-8",
        )

        result = reader.read_signals()

        assert result == rows

    def test_missing_file_returns_empty_list(self, reader: StateReader) -> None:
        """Missing signals.jsonl returns empty list."""
        result = reader.read_signals()

        assert result == []

    def test_max_lines_respected(
        self, state_dir: Path, reader: StateReader
    ) -> None:
        """Only the last max_lines entries are returned."""
        rows = [{"i": i} for i in range(20)]
        (state_dir / "signals.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows),
            encoding="utf-8",
        )

        result = reader.read_signals(max_lines=5)

        assert len(result) == 5
        assert result == [{"i": i} for i in range(15, 20)]

    def test_default_max_lines_is_2000(
        self, state_dir: Path, reader: StateReader
    ) -> None:
        """Default max_lines=2000 returns all rows when file is smaller."""
        rows = [{"n": n} for n in range(10)]
        (state_dir / "signals.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows),
            encoding="utf-8",
        )

        result = reader.read_signals()

        assert len(result) == 10


# ---------------------------------------------------------------------------
# read_challenge_state
# ---------------------------------------------------------------------------

class TestReadChallengeState:
    """Tests for StateReader.read_challenge_state."""

    def test_missing_file_returns_none(self, reader: StateReader) -> None:
        """Missing challenge_state.json returns None."""
        result = reader.read_challenge_state()

        assert result is None

    def test_existing_file_returns_dict(
        self, state_dir: Path, reader: StateReader
    ) -> None:
        """Valid challenge_state.json is parsed and returned."""
        payload = {"challenge": "active", "target_pnl": 500}
        (state_dir / "challenge_state.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        result = reader.read_challenge_state()

        assert result == payload

    def test_corrupt_file_returns_none(
        self, state_dir: Path, reader: StateReader
    ) -> None:
        """Corrupt challenge_state.json returns None (empty dict -> None)."""
        (state_dir / "challenge_state.json").write_text(
            "not json", encoding="utf-8"
        )

        result = reader.read_challenge_state()

        # load_json_file returns {} on corrupt, then read_challenge_state
        # converts falsy result to None.
        assert result is None

    def test_empty_file_returns_none(
        self, state_dir: Path, reader: StateReader
    ) -> None:
        """Empty challenge_state.json returns None."""
        (state_dir / "challenge_state.json").write_text("", encoding="utf-8")

        result = reader.read_challenge_state()

        assert result is None
