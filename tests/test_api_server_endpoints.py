"""
Smoke tests for the FastAPI API server endpoints (src/pearlalgo/api/server.py).

Verifies that every major endpoint returns a valid response (200 or expected
status) and that error responses use proper JSON format.  External I/O (state
files, signals.jsonl, data providers) is mocked so tests don't need real data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Skip if FastAPI is not installed
fastapi = pytest.importorskip("fastapi", reason="FastAPI not installed")

from fastapi.testclient import TestClient  # noqa: E402

import pearlalgo.api.server as server_mod  # noqa: E402
server_core_mod = server_mod  # server_core merged into server

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_API_KEY = "test-smoke-key-99999"
OPERATOR_PASS = "test-smoke-operator-pass"

# Minimal sample state that satisfies _read_state_safe / get_state
SAMPLE_STATE: Dict[str, Any] = {
    "running": True,
    "paused": False,
    "futures_market_open": True,
    "data_fresh": True,
    "active_trades_count": 0,
    "active_trades_unrealized_pnl": 0.0,
}

SAMPLE_SIGNAL_ROWS: List[Dict[str, Any]] = [
    {
        "signal_id": "smoke_001",
        "status": "exited",
        "entry_price": 18000.0,
        "exit_price": 18020.0,
        "entry_time": "2025-06-01T14:00:00Z",
        "exit_time": "2025-06-01T14:30:00Z",
        "pnl": 20.0,
        "exit_reason": "take_profit",
        "signal": {
            "direction": "long",
            "symbol": "MNQ",
            "stop_loss": 17980.0,
            "take_profit": 18020.0,
            "position_size": 1,
        },
    },
    {
        "signal_id": "smoke_002",
        "status": "active",
        "entry_price": 18100.0,
        "signal": {
            "direction": "short",
            "symbol": "MNQ",
            "stop_loss": 18120.0,
            "take_profit": 18060.0,
            "position_size": 1,
        },
    },
]


def _write_jsonl(path: Path, records: List[Dict]) -> None:
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def state_dir(tmp_path):
    """Create a temporary state directory with realistic files."""
    d = tmp_path / "agent_state" / "NQ"
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps(SAMPLE_STATE))
    _write_jsonl(d / "signals.jsonl", SAMPLE_SIGNAL_ROWS)

    # performance.json with trades list
    (d / "performance.json").write_text(json.dumps({
        "trades": [
            {
                "exit_time": "2025-06-01T14:30:00Z",
                "entry_time": "2025-06-01T14:00:00Z",
                "pnl": 20.0,
                "is_win": True,
                "direction": "long",
            }
        ]
    }))
    return d


@pytest.fixture()
def _patch_server(state_dir):
    """Patch server module globals: state dir, auth disabled, no data provider."""
    patches = [
        patch.object(server_mod, "_state_dir", state_dir),
        patch.object(server_mod, "_state_reader", None),
        patch.object(server_mod, "_market", "NQ"),
        patch.object(server_mod, "_auth_enabled", False),
        patch.object(server_mod, "_api_keys", set()),
        patch.object(server_mod, "_operator_enabled", False),
        patch.object(server_mod, "_data_provider", None),
        patch.object(server_mod, "_data_provider_error", "mocked-away"),
        # routes/health.py imports verify_api_key from server_core
        patch.object(server_core_mod, "_auth_enabled", False),
        patch.object(server_core_mod, "_api_keys", set()),
    ]
    server_mod._state_reader_cache.clear()
    server_mod.ws_manager.active_connections.clear()
    server_mod.ws_manager._cached_state = {}
    server_mod.ws_manager._last_state_hash = ""
    server_mod.ws_manager._last_state_mtime_ns = 0
    server_mod.ws_manager._last_state_size = 0
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def _patch_server_auth(state_dir):
    """Patch server globals with authentication ENABLED."""
    patches = [
        patch.object(server_mod, "_state_dir", state_dir),
        patch.object(server_mod, "_state_reader", None),
        patch.object(server_mod, "_market", "NQ"),
        patch.object(server_mod, "_auth_enabled", True),
        patch.object(server_mod, "_api_keys", {VALID_API_KEY}),
        patch.object(server_mod, "_operator_enabled", False),
        patch.object(server_mod, "_data_provider", None),
        patch.object(server_mod, "_data_provider_error", "mocked-away"),
    ]
    server_mod._state_reader_cache.clear()
    server_mod.ws_manager.active_connections.clear()
    server_mod.ws_manager._cached_state = {}
    server_mod.ws_manager._last_state_hash = ""
    server_mod.ws_manager._last_state_mtime_ns = 0
    server_mod.ws_manager._last_state_size = 0
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def _patch_server_auth_and_operator(state_dir):
    """Patch server globals with read-only auth and operator auth enabled."""
    patches = [
        patch.object(server_mod, "_state_dir", state_dir),
        patch.object(server_mod, "_state_reader", None),
        patch.object(server_mod, "_market", "NQ"),
        patch.object(server_mod, "_auth_enabled", True),
        patch.object(server_mod, "_api_keys", {VALID_API_KEY}),
        patch.object(server_mod, "_operator_enabled", True),
        patch.object(server_mod, "_operator_passphrase", OPERATOR_PASS),
        patch.object(server_mod, "_operator_failures", {}),
        patch.object(server_mod, "_data_provider", None),
        patch.object(server_mod, "_data_provider_error", "mocked-away"),
    ]
    server_mod._state_reader_cache.clear()
    server_mod.ws_manager.active_connections.clear()
    server_mod.ws_manager._cached_state = {}
    server_mod.ws_manager._last_state_hash = ""
    server_mod.ws_manager._last_state_mtime_ns = 0
    server_mod.ws_manager._last_state_size = 0
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def client():
    return TestClient(server_mod.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. GET /health — always accessible, returns {"status": "ok"}
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    @pytest.mark.usefixtures("_patch_server")
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "market" in body


# ---------------------------------------------------------------------------
# 2. GET /api/state — returns agent state dict
# ---------------------------------------------------------------------------


class TestStateEndpoint:
    @pytest.mark.usefixtures("_patch_server")
    def test_state_returns_200_with_required_keys(self, client):
        resp = client.get("/api/state")
        assert resp.status_code == 200
        body = resp.json()
        assert "running" in body
        assert "daily_pnl" in body

    @pytest.mark.usefixtures("_patch_server_auth")
    def test_state_requires_auth_when_enabled(self, client):
        """Without a key, the endpoint must reject the request."""
        resp = client.get("/api/state")
        assert resp.status_code in (401, 403)
        body = resp.json()
        assert "detail" in body


# ---------------------------------------------------------------------------
# 3. GET /api/trades — returns list of trade dicts
# ---------------------------------------------------------------------------


class TestTradesEndpoint:
    @pytest.mark.usefixtures("_patch_server")
    def test_trades_returns_list(self, client):
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        # Should contain at least the exited signal from sample data
        assert len(body) >= 1

    @pytest.mark.usefixtures("_patch_server")
    def test_trades_respects_limit_param(self, client):
        resp = client.get("/api/trades?limit=1")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) <= 1


# ---------------------------------------------------------------------------
# 4. GET /api/positions — returns list of open positions
# ---------------------------------------------------------------------------


class TestPositionsEndpoint:
    @pytest.mark.usefixtures("_patch_server")
    def test_positions_returns_list(self, client):
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)


# ---------------------------------------------------------------------------
# 5. GET /api/performance-summary — period-bucketed performance
# ---------------------------------------------------------------------------


class TestPerformanceSummaryEndpoint:
    @pytest.mark.usefixtures("_patch_server")
    def test_performance_summary_returns_periods(self, client):
        resp = client.get("/api/performance-summary")
        assert resp.status_code == 200
        body = resp.json()
        assert "as_of" in body
        # Must have at least the "all" period
        assert "all" in body
        all_period = body["all"]
        assert "pnl" in all_period
        assert "trades" in all_period


# ---------------------------------------------------------------------------
# 6. GET /api/candles — requires data provider (should 500/503 when mocked)
# ---------------------------------------------------------------------------


class TestCandlesEndpoint:
    @pytest.mark.usefixtures("_patch_server")
    def test_candles_without_provider_returns_error(self, client):
        """With data provider mocked away, candles should return 500 or 503."""
        resp = client.get("/api/candles?symbol=MNQ&timeframe=5m&bars=20")
        # Either 500 or 503 when no data provider is configured
        assert resp.status_code in (500, 503)
        body = resp.json()
        assert "detail" in body


# ---------------------------------------------------------------------------
# 8. Error response format — invalid auth returns proper JSON error
# ---------------------------------------------------------------------------


class TestErrorResponseFormat:
    @pytest.mark.usefixtures("_patch_server_auth")
    def test_invalid_api_key_returns_json_error(self, client):
        resp = client.get(
            "/api/state",
            headers={"X-API-Key": "totally-wrong-key"},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert "detail" in body
        assert isinstance(body["detail"], str)

    @pytest.mark.usefixtures("_patch_server_auth")
    def test_valid_api_key_passes_auth(self, client):
        resp = client.get(
            "/api/state",
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "running" in body


# ---------------------------------------------------------------------------
# 9. GET /api/market-status — returns market open/closed info
# ---------------------------------------------------------------------------


class TestMarketStatusEndpoint:
    @pytest.mark.usefixtures("_patch_server")
    def test_market_status_returns_200(self, client):
        resp = client.get("/api/market-status")
        assert resp.status_code == 200
        body = resp.json()
        assert "is_open" in body
        assert isinstance(body["is_open"], bool)


# ---------------------------------------------------------------------------
# 10. WebSocket /ws — basic connect/disconnect
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    @pytest.mark.usefixtures("_patch_server")
    def test_ws_connect_and_receive_initial_state(self, client):
        """WebSocket should accept connection and send an initial state frame."""
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            # The initial broadcast should be a dict with type="state_update"
            # or it sends the state directly
            assert isinstance(data, dict)
            assert "running" in data or "type" in data


@pytest.mark.e2e
class TestOperatorBoundarySmoke:
    """Minimal smoke checks for operator-only access boundaries."""

    @pytest.mark.usefixtures("_patch_server_auth_and_operator")
    def test_read_only_state_accepts_api_key_while_operator_ping_rejects_it(self, client):
        state_resp = client.get("/api/state", headers={"X-API-Key": VALID_API_KEY})
        assert state_resp.status_code == 200

        operator_resp = client.get("/api/operator/ping", headers={"X-API-Key": VALID_API_KEY})
        assert operator_resp.status_code == 403

    @pytest.mark.usefixtures("_patch_server_auth_and_operator")
    def test_operator_ping_accepts_operator_header(self, client):
        resp = client.get("/api/operator/ping", headers={"X-PEARL-OPERATOR": OPERATOR_PASS})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.usefixtures("_patch_server_auth_and_operator")
    def test_kill_switch_accepts_operator_header_and_writes_flag(self, client, state_dir):
        server_mod._rate_limit_buckets.clear()
        resp = client.post("/api/kill-switch", headers={"X-PEARL-OPERATOR": OPERATOR_PASS})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert (state_dir / "kill_request.flag").exists()
