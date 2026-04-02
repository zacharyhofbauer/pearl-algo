"""
Focused tests for /api/config runtime validation and write safety.
"""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
import yaml

fastapi = pytest.importorskip("fastapi", reason="FastAPI not installed")

from fastapi.testclient import TestClient  # noqa: E402

import pearlalgo.api.server as server_mod  # noqa: E402
import pearlalgo.api.config_endpoints as config_mod  # noqa: E402
from pearlalgo.config.runtime_validation import validate_runtime_config  # noqa: E402


VALID_API_KEY = "config-test-readonly-key"
OPERATOR_PASS = "config-test-operator-pass"


SAMPLE_LIVE_CONFIG = {
    "symbol": "MNQ",
    "timeframe": "5m",
    "scan_interval": 30,
    "execution": {
        "enabled": False,
        "armed": False,
        "mode": "dry_run",
        "max_positions": 1,
        "max_orders_per_day": 20,
        "max_daily_loss": 500.0,
        "cooldown_seconds": 60,
    },
    "signals": {
        "max_stop_points": 45.0,
        "min_risk_reward": 1.3,
    },
    "strategy": {
        "active": "composite_intraday",
        "enforce_session_window": False,
    },
    "strategies": {
        "composite_intraday": {
            "ema_fast": 9,
            "ema_slow": 21,
            "min_confidence": 0.4,
            "min_confidence_long": 0.4,
            "min_confidence_short": 0.4,
            "stop_loss_atr_mult": 1.5,
            "take_profit_atr_mult": 2.5,
        },
    },
}


@pytest.fixture(autouse=True, scope="module")
def _patch_broadcast_loop():
    async def _noop_broadcast(interval=2.0):
        return

    original = server_mod.ws_manager.start_broadcast_loop
    server_mod.ws_manager.start_broadcast_loop = _noop_broadcast
    yield
    server_mod.ws_manager.start_broadcast_loop = original


@pytest.fixture()
def live_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "tradovate_paper.yaml"
    path.write_text(yaml.safe_dump(SAMPLE_LIVE_CONFIG, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture()
def _patch_operator_and_config(live_yaml: Path):
    patches = [
        patch.object(server_mod, "_auth_enabled", True),
        patch.object(server_mod, "_api_keys", {VALID_API_KEY}),
        patch.object(server_mod, "_operator_enabled", True),
        patch.object(server_mod, "_operator_passphrase", OPERATOR_PASS),
        patch.object(server_mod, "_operator_failures", {}),
        patch.object(config_mod, "LIVE_YAML_PATH", live_yaml),
    ]
    config_mod._rate_limit_buckets.clear()
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()
    config_mod._rate_limit_buckets.clear()


@pytest.fixture()
def client():
    return TestClient(server_mod.app, raise_server_exceptions=False)


def _operator_headers() -> dict[str, str]:
    return {"X-PEARL-OPERATOR": OPERATOR_PASS}


class TestConfigEndpoints:
    def test_get_config_requires_operator(self, client, _patch_operator_and_config):
        resp = client.get("/api/config")
        assert resp.status_code == 403

    def test_get_config_returns_schema_hash_and_warnings(self, client, _patch_operator_and_config):
        resp = client.get("/api/config", headers=_operator_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert "config_hash" in body
        assert "schema" in body
        assert "execution.max_orders_per_day" in body["schema"]
        assert body["validation_warnings"] == []

    def test_update_config_rejects_forbidden_field(self, client, _patch_operator_and_config):
        current = client.get("/api/config", headers=_operator_headers()).json()
        resp = client.post(
            "/api/config",
            headers=_operator_headers(),
            json={
                "changes": {"execution.adapter": "ibkr"},
                "config_hash": current["config_hash"],
                "restart": False,
            },
        )
        assert resp.status_code == 403
        assert "cannot be modified" in resp.json()["detail"]

    def test_update_config_rejects_stale_hash(self, client, _patch_operator_and_config):
        resp = client.post(
            "/api/config",
            headers=_operator_headers(),
            json={
                "changes": {"execution.max_orders_per_day": 15},
                "config_hash": "stale-hash",
                "restart": False,
            },
        )
        assert resp.status_code == 409

    def test_update_config_aborts_before_write_on_runtime_validation_failure(
        self, client, _patch_operator_and_config, live_yaml, monkeypatch,
    ):
        current = client.get("/api/config", headers=_operator_headers()).json()
        original_text = live_yaml.read_text(encoding="utf-8")

        def _raise_runtime_error(*args, **kwargs):
            raise ValueError("simulated runtime validation failure")

        monkeypatch.setattr(config_mod, "validate_runtime_config", _raise_runtime_error)

        resp = client.post(
            "/api/config",
            headers=_operator_headers(),
            json={
                "changes": {"execution.max_orders_per_day": 12},
                "config_hash": current["config_hash"],
                "restart": False,
            },
        )
        assert resp.status_code == 422
        assert "Runtime config validation failed" in resp.json()["detail"]
        assert live_yaml.read_text(encoding="utf-8") == original_text

    def test_update_config_writes_validated_yaml_and_restarts_when_requested(
        self, client, _patch_operator_and_config, live_yaml, monkeypatch,
    ):
        current = client.get("/api/config", headers=_operator_headers()).json()
        restart_mock = lambda *args, **kwargs: CompletedProcess(args=args[0], returncode=0, stdout=b"", stderr=b"")
        monkeypatch.setattr(config_mod.subprocess, "run", restart_mock)

        resp = client.post(
            "/api/config",
            headers=_operator_headers(),
            json={
                "changes": {"execution.max_orders_per_day": 12},
                "config_hash": current["config_hash"],
                "restart": True,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["restarted"] is True
        assert body["validation_warnings"] == []

        updated = yaml.safe_load(live_yaml.read_text(encoding="utf-8"))
        assert updated["execution"]["max_orders_per_day"] == 12


class TestRuntimeValidation:
    def test_runtime_validation_rejects_non_enforced_signal_flags(self):
        config = json.loads(json.dumps(SAMPLE_LIVE_CONFIG))
        config.setdefault("signals", {})["skip_overnight"] = True

        with pytest.raises(ValueError, match="not enforced at runtime"):
            validate_runtime_config(config, strict_non_enforced=True)
