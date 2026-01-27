from __future__ import annotations

from pathlib import Path

import pytest

from pearlalgo.utils.paths import ensure_state_dir, parse_utc_timestamp


def test_ensure_state_dir_uses_env_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "custom_state"
    monkeypatch.setenv("PEARLALGO_STATE_DIR", str(target))
    state_dir = ensure_state_dir(None)
    assert state_dir == target
    assert state_dir.exists()


def test_ensure_state_dir_uses_market(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PEARLALGO_STATE_DIR", raising=False)
    monkeypatch.setenv("PEARLALGO_MARKET", "ES")
    state_dir = ensure_state_dir(None)
    assert state_dir == tmp_path / "data" / "agent_state" / "ES"
    assert state_dir.exists()


def test_parse_utc_timestamp_handles_z_suffix() -> None:
    dt = parse_utc_timestamp("2026-01-01T12:34:56Z")
    assert dt.tzinfo is not None
    assert dt.isoformat().endswith("+00:00")


def test_parse_utc_timestamp_treats_naive_as_utc() -> None:
    dt = parse_utc_timestamp("2026-01-01T12:34:56")
    assert dt.tzinfo is not None
    assert dt.isoformat().endswith("+00:00")
