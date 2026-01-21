from __future__ import annotations

from pathlib import Path

import pytest

from pearlalgo.utils.paths import ensure_state_dir


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
