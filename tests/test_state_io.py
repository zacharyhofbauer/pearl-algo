"""
Tests for shared state I/O utilities.

Validates load_json_file and load_jsonl_file handle:
- Valid files
- Missing files
- Corrupt / invalid content
- Empty files
- max_lines truncation (JSONL)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pearlalgo.utils.state_io import load_json_file, load_jsonl_file


# ---------------------------------------------------------------------------
# load_json_file
# ---------------------------------------------------------------------------

class TestLoadJsonFile:
    """Tests for load_json_file."""

    def test_valid_json_returns_dict(self, tmp_path: Path) -> None:
        """Valid JSON file is parsed and returned as a dict."""
        f = tmp_path / "data.json"
        payload = {"status": "running", "count": 42}
        f.write_text(json.dumps(payload), encoding="utf-8")

        result = load_json_file(f)

        assert result == payload

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Non-existent path returns empty dict without raising."""
        result = load_json_file(tmp_path / "does_not_exist.json")

        assert result == {}

    def test_corrupt_json_returns_empty_dict(self, tmp_path: Path) -> None:
        """Malformed JSON content returns empty dict."""
        f = tmp_path / "bad.json"
        f.write_text("{not valid json!!!", encoding="utf-8")

        result = load_json_file(f)

        assert result == {}

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """A zero-byte file returns empty dict."""
        f = tmp_path / "empty.json"
        f.write_text("", encoding="utf-8")

        result = load_json_file(f)

        assert result == {}

    def test_nested_json_preserved(self, tmp_path: Path) -> None:
        """Nested dicts / lists round-trip correctly."""
        f = tmp_path / "nested.json"
        payload = {"signals": [{"id": 1}, {"id": 2}], "meta": {"v": "1.0"}}
        f.write_text(json.dumps(payload), encoding="utf-8")

        result = load_json_file(f)

        assert result == payload

    def test_json_array_returns_as_is(self, tmp_path: Path) -> None:
        """A top-level JSON array is returned (not a dict)."""
        f = tmp_path / "array.json"
        f.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        # The function signature says Dict, but json.loads may return list.
        # Verify it does not crash.
        result = load_json_file(f)
        assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# load_jsonl_file
# ---------------------------------------------------------------------------

class TestLoadJsonlFile:
    """Tests for load_jsonl_file."""

    def test_valid_jsonl_returns_list(self, tmp_path: Path) -> None:
        """Well-formed JSONL is parsed into a list of dicts."""
        f = tmp_path / "signals.jsonl"
        rows = [{"ts": 1}, {"ts": 2}, {"ts": 3}]
        f.write_text(
            "\n".join(json.dumps(r) for r in rows),
            encoding="utf-8",
        )

        result = load_jsonl_file(f)

        assert result == rows

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        """Non-existent path returns empty list without raising."""
        result = load_jsonl_file(tmp_path / "nope.jsonl")

        assert result == []

    def test_max_lines_respected(self, tmp_path: Path) -> None:
        """Only the last max_lines entries are returned."""
        f = tmp_path / "many.jsonl"
        rows = [{"i": i} for i in range(10)]
        f.write_text(
            "\n".join(json.dumps(r) for r in rows),
            encoding="utf-8",
        )

        result = load_jsonl_file(f, max_lines=3)

        assert result == [{"i": 7}, {"i": 8}, {"i": 9}]

    def test_invalid_lines_skipped(self, tmp_path: Path) -> None:
        """Malformed lines are silently skipped; valid lines are kept."""
        f = tmp_path / "mixed.jsonl"
        lines = [
            json.dumps({"ok": 1}),
            "NOT JSON",
            json.dumps({"ok": 2}),
            "{{bad",
            json.dumps({"ok": 3}),
        ]
        f.write_text("\n".join(lines), encoding="utf-8")

        result = load_jsonl_file(f)

        assert result == [{"ok": 1}, {"ok": 2}, {"ok": 3}]

    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        """A zero-byte JSONL file returns empty list."""
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")

        result = load_jsonl_file(f)

        assert result == []

    def test_blank_lines_ignored(self, tmp_path: Path) -> None:
        """Blank / whitespace-only lines are silently skipped."""
        f = tmp_path / "blanks.jsonl"
        content = json.dumps({"a": 1}) + "\n\n  \n" + json.dumps({"b": 2}) + "\n"
        f.write_text(content, encoding="utf-8")

        result = load_jsonl_file(f)

        assert result == [{"a": 1}, {"b": 2}]

    def test_max_lines_with_fewer_entries(self, tmp_path: Path) -> None:
        """max_lines larger than file length returns all entries."""
        f = tmp_path / "few.jsonl"
        rows = [{"x": 1}, {"x": 2}]
        f.write_text(
            "\n".join(json.dumps(r) for r in rows),
            encoding="utf-8",
        )

        result = load_jsonl_file(f, max_lines=100)

        assert result == rows
