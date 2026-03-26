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
    """Legacy UTC Z-suffix timestamps are converted to naive ET."""
    dt = parse_utc_timestamp("2026-01-01T12:34:56Z")
    # Z-suffix (UTC) is converted to naive ET (UTC-5 in EST)
    assert dt.tzinfo is None
    assert dt.hour == 7  # 12:34 UTC = 07:34 EST


def test_parse_utc_timestamp_treats_naive_as_et() -> None:
    """Naive timestamps are now ET (post-migration) — returned as-is."""
    dt = parse_utc_timestamp("2026-01-01T12:34:56")
    assert dt.tzinfo is None
    assert dt.hour == 12  # Already ET, no conversion
