"""Tests for Issue 14-A — auto-flatten on reconnect-giveup + orphaned-stop
retry exhaustion.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 0.

The Tradovate adapter's ``_reconnect_loop`` used to exit with
``_reconnect_gave_up = True`` and a CRITICAL log, leaving any open
position unprotected through the next ~72 minutes until manual
intervention. Same for ``_reattach_orphaned_stop_on_connect_with_retry``
after 10 attempts. 14-A adds an auto-response: disarm + write
``kill_request.flag`` so the agent's execution_flags watcher calls
``flatten_all_positions()`` on its next cycle, even across a disconnect
period.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pearlalgo.execution.base import ExecutionConfig, ExecutionMode
from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter
from pearlalgo.execution.tradovate.config import TradovateConfig


@pytest.fixture
def adapter(monkeypatch, tmp_path: Path) -> TradovateExecutionAdapter:
    """Return an adapter with a tmp state_dir wired through PEARLALGO_STATE_DIR."""
    monkeypatch.setenv("PEARLALGO_STATE_DIR", str(tmp_path))
    exec_cfg = ExecutionConfig(
        enabled=True,
        armed=True,
        mode=ExecutionMode.PAPER,
        max_positions=1,
    )
    tv_cfg = TradovateConfig(
        username="u",
        password="p",
        cid=1,
        sec="sec",
        env="demo",
        account_name="DEMO1",
    )
    return TradovateExecutionAdapter(exec_cfg, tv_cfg)


def _read_flag(tmp_path: Path) -> dict[str, Any]:
    flag = tmp_path / "kill_request.flag"
    assert flag.exists(), f"kill_request.flag not written under {tmp_path}"
    return json.loads(flag.read_text())


def test_request_kill_switch_writes_flag_and_disarms(adapter, tmp_path: Path):
    adapter._armed = True  # ensure starting state
    adapter._request_kill_switch_on_failure(
        reason="tradovate_reconnect_gave_up",
        source="_reconnect_loop",
        context={"max_attempts": 20},
    )
    assert adapter.armed is False, "adapter must disarm before writing the flag"
    payload = _read_flag(tmp_path)
    assert payload["reason"] == "tradovate_reconnect_gave_up"
    assert payload["source"] == "_reconnect_loop"
    assert payload["context"] == {"max_attempts": 20}
    assert "requested_at_utc" in payload
    # Timestamp is ISO UTC
    assert payload["requested_at_utc"].endswith("+00:00") or "T" in payload["requested_at_utc"]


def test_request_kill_switch_without_context_field(adapter, tmp_path: Path):
    adapter._request_kill_switch_on_failure(
        reason="orphaned_stop_retry_exhausted",
        source="_reattach_orphaned_stop_on_connect_with_retry",
    )
    payload = _read_flag(tmp_path)
    assert payload["reason"] == "orphaned_stop_retry_exhausted"
    assert payload["source"] == "_reattach_orphaned_stop_on_connect_with_retry"
    assert "context" not in payload  # context not set → key omitted


def test_request_kill_switch_disarms_even_if_flag_write_fails(
    adapter, tmp_path: Path, monkeypatch
):
    """If the state_dir write fails, the adapter must still be disarmed."""
    adapter._armed = True

    from pearlalgo.utils import paths as paths_module

    def _boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(paths_module, "ensure_state_dir", _boom)

    adapter._request_kill_switch_on_failure(
        reason="simulated_disk_full", source="test"
    )
    assert adapter.armed is False, (
        "disarm must happen before the flag write; a disk error must not leave "
        "the adapter armed"
    )
    assert not (tmp_path / "kill_request.flag").exists()


def test_request_kill_switch_resilient_to_disarm_failure(
    adapter, tmp_path: Path, monkeypatch
):
    """Even if disarm() raises, the flag must still be written."""
    def _disarm_boom(self):
        raise RuntimeError("disarm blew up")

    monkeypatch.setattr(
        TradovateExecutionAdapter, "disarm", _disarm_boom, raising=True
    )
    adapter._request_kill_switch_on_failure(
        reason="simulated_disarm_failure", source="test"
    )
    payload = _read_flag(tmp_path)
    assert payload["reason"] == "simulated_disarm_failure"


def test_flag_payload_is_valid_json(adapter, tmp_path: Path):
    adapter._request_kill_switch_on_failure(
        reason="json_shape", source="test"
    )
    raw = (tmp_path / "kill_request.flag").read_text()
    # Must round-trip through json.loads without errors.
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_reconnect_loop_writes_kill_flag_on_give_up(adapter, tmp_path: Path):
    """When _reconnect_loop exhausts all attempts, the kill flag is written."""
    adapter._armed = True
    adapter._connected = False
    adapter._client = MagicMock()
    adapter._client.is_authenticated = False

    # Make every connect attempt fail; use short delays so the test is fast.
    async def _connect_fail(self) -> bool:
        return False

    async def _fast_sleep(_seconds: float) -> None:
        return None

    # Monkey-patch both asyncio.sleep and self.connect for fast execution.
    import asyncio as _asyncio_mod

    original_sleep = _asyncio_mod.sleep
    _asyncio_mod.sleep = _fast_sleep  # type: ignore[assignment]
    try:
        # Bind the patched connect to the instance.
        bound = _connect_fail.__get__(adapter, TradovateExecutionAdapter)
        adapter.connect = bound  # type: ignore[method-assign]

        await adapter._reconnect_loop()
    finally:
        _asyncio_mod.sleep = original_sleep  # type: ignore[assignment]

    assert adapter._reconnect_gave_up is True
    assert adapter.armed is False
    payload = _read_flag(tmp_path)
    assert payload["reason"] == "tradovate_reconnect_gave_up"
    assert payload["source"] == "_reconnect_loop"
    assert payload["context"] == {"max_attempts": 20}


@pytest.mark.asyncio
async def test_orphaned_stop_retry_exhaustion_writes_kill_flag(
    adapter, tmp_path: Path, monkeypatch
):
    """When orphaned-stop retry exhausts max_attempts, kill flag is written."""
    from pearlalgo.execution.tradovate.client import TradovateAPIError

    adapter._armed = True

    async def _always_503(self) -> None:
        raise TradovateAPIError("503 Service Unavailable")

    async def _fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        TradovateExecutionAdapter,
        "_reattach_orphaned_stop_on_connect",
        _always_503,
        raising=True,
    )
    import asyncio as _asyncio_mod

    original_sleep = _asyncio_mod.sleep
    _asyncio_mod.sleep = _fast_sleep  # type: ignore[assignment]
    try:
        result = await adapter._reattach_orphaned_stop_on_connect_with_retry(
            max_attempts=3, base_delay=0.0
        )
    finally:
        _asyncio_mod.sleep = original_sleep  # type: ignore[assignment]

    assert result is False
    assert adapter.armed is False
    payload = _read_flag(tmp_path)
    assert payload["reason"] == "orphaned_stop_retry_exhausted"
    assert payload["source"] == "_reattach_orphaned_stop_on_connect_with_retry"
    assert payload["context"] == {"max_attempts": 3}
