"""
Tests for the FastAPI API Server (api_server.py).

Tests:
- Authentication: API key via header, query param, missing/invalid key
- Health endpoint: structure, no auth required
- Core data endpoints: /api/state, /api/candles, /api/trades, /api/positions,
  /api/performance-summary
- Error handling: corrupt state, missing params, internal errors
- WebSocket: connect, auth rejection, initial state delivery
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Skip entire module if FastAPI is not installed (CI marker: requires_fastapi)
# ---------------------------------------------------------------------------
fastapi = pytest.importorskip("fastapi", reason="FastAPI not installed")

# ---------------------------------------------------------------------------
# Path setup: api_server.py lives under scripts/, not src/
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import the module under test after path setup.
# We import the *module* so we can patch its globals.
import pearlalgo_web_app.api_server as api_mod  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# Constants for tests
# ---------------------------------------------------------------------------
VALID_API_KEY = "test-secret-key-12345"
INVALID_API_KEY = "wrong-key-99999"

# ---------------------------------------------------------------------------
# Sample state data
# ---------------------------------------------------------------------------

SAMPLE_STATE: Dict[str, Any] = {
    "running": True,
    "paused": False,
    "futures_market_open": True,
    "data_fresh": True,
    "active_trades_count": 1,
    "active_trades_unrealized_pnl": 25.50,
    "learning": {
        "model_loaded": True,
        "last_train": "2025-06-01T12:00:00Z",
    },
    "learning_contextual": {},
    "buy_sell_pressure_raw": {"buy": 0.6, "sell": 0.4},
}

SAMPLE_SIGNALS_JSONL = [
    {
        "signal_id": "sig_001",
        "status": "exited",
        "entry_price": 20000.0,
        "exit_price": 20030.0,
        "entry_time": "2025-06-01T14:00:00Z",
        "exit_time": "2025-06-01T14:30:00Z",
        "pnl": 30.0,
        "exit_reason": "take_profit",
        "signal": {
            "direction": "long",
            "symbol": "MNQ",
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": 1,
        },
    },
    {
        "signal_id": "sig_002",
        "status": "exited",
        "entry_price": 20100.0,
        "exit_price": 20080.0,
        "entry_time": "2025-06-01T15:00:00Z",
        "exit_time": "2025-06-01T15:20:00Z",
        "pnl": -20.0,
        "exit_reason": "stop_loss",
        "signal": {
            "direction": "long",
            "symbol": "MNQ",
            "stop_loss": 20080.0,
            "take_profit": 20130.0,
            "position_size": 1,
        },
    },
    {
        "signal_id": "sig_003",
        "status": "active",
        "entry_price": 20200.0,
        "signal": {
            "direction": "short",
            "symbol": "MNQ",
            "stop_loss": 20220.0,
            "take_profit": 20170.0,
            "position_size": 2,
        },
    },
]


def _write_jsonl(path: Path, records: List[Dict]) -> None:
    """Write a list of dicts as JSONL."""
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

    # state.json
    (d / "state.json").write_text(json.dumps(SAMPLE_STATE))

    # signals.jsonl (used by /api/trades and /api/positions)
    _write_jsonl(d / "signals.jsonl", SAMPLE_SIGNALS_JSONL)

    return d


@pytest.fixture()
def empty_state_dir(tmp_path):
    """State directory that exists but has no state.json."""
    d = tmp_path / "agent_state" / "NQ"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def _patch_globals(state_dir):
    """Patch api_server module-level globals for testing.

    Sets _state_dir, _market, disables auth by default, clears Pearl AI.
    """
    patches = [
        patch.object(api_mod, "_state_dir", state_dir),
        patch.object(api_mod, "_market", "NQ"),
        patch.object(api_mod, "_auth_enabled", False),
        patch.object(api_mod, "_api_keys", set()),
        patch.object(api_mod, "_operator_enabled", False),
        patch.object(api_mod, "_pearl_ai_mounted", False),
        patch.object(api_mod, "_pearl_brain", None),
        patch.object(api_mod, "_data_provider", None),
        patch.object(api_mod, "_data_provider_error", "mocked-away"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def _patch_globals_empty(empty_state_dir):
    """Patch globals pointing at an empty state directory."""
    patches = [
        patch.object(api_mod, "_state_dir", empty_state_dir),
        patch.object(api_mod, "_market", "NQ"),
        patch.object(api_mod, "_auth_enabled", False),
        patch.object(api_mod, "_api_keys", set()),
        patch.object(api_mod, "_operator_enabled", False),
        patch.object(api_mod, "_pearl_ai_mounted", False),
        patch.object(api_mod, "_pearl_brain", None),
        patch.object(api_mod, "_data_provider", None),
        patch.object(api_mod, "_data_provider_error", "mocked-away"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def _patch_globals_auth(state_dir):
    """Patch globals with authentication ENABLED and a known valid key."""
    patches = [
        patch.object(api_mod, "_state_dir", state_dir),
        patch.object(api_mod, "_market", "NQ"),
        patch.object(api_mod, "_auth_enabled", True),
        patch.object(api_mod, "_api_keys", {VALID_API_KEY}),
        patch.object(api_mod, "_operator_enabled", False),
        patch.object(api_mod, "_pearl_ai_mounted", False),
        patch.object(api_mod, "_pearl_brain", None),
        patch.object(api_mod, "_data_provider", None),
        patch.object(api_mod, "_data_provider_error", "mocked-away"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def client():
    """Return a TestClient for the FastAPI app (no auth)."""
    return TestClient(api_mod.app, raise_server_exceptions=False)


@pytest.fixture()
def auth_client():
    """Return a TestClient (same app, used when auth fixtures are active)."""
    return TestClient(api_mod.app, raise_server_exceptions=False)


# =========================================================================
# 1. Authentication Tests
# =========================================================================


class TestAuthentication:
    """API key authentication via header and query parameter."""

    def test_missing_api_key_returns_401(self, auth_client, _patch_globals_auth):
        """Request to a protected endpoint without API key returns 401."""
        resp = auth_client.get("/api/state")
        assert resp.status_code == 401
        body = resp.json()
        assert "detail" in body
        assert "api key" in body["detail"].lower() or "missing" in body["detail"].lower()

    def test_invalid_api_key_returns_403(self, auth_client, _patch_globals_auth):
        """Request with an incorrect API key returns 403."""
        resp = auth_client.get(
            "/api/state",
            headers={"X-API-Key": INVALID_API_KEY},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert "invalid" in body["detail"].lower()

    def test_valid_api_key_header_succeeds(self, auth_client, _patch_globals_auth):
        """Request with a valid X-API-Key header returns 200."""
        resp = auth_client.get(
            "/api/state",
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "running" in body

    def test_valid_api_key_query_param_succeeds(self, auth_client, _patch_globals_auth):
        """API key supplied via ?api_key= query parameter returns 200."""
        resp = auth_client.get("/api/state?api_key=" + VALID_API_KEY)
        assert resp.status_code == 200
        body = resp.json()
        assert "running" in body


# =========================================================================
# 2. Health Endpoint Tests
# =========================================================================


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200_with_correct_structure(self, client, _patch_globals):
        """Health endpoint returns 200 with status and market fields."""
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "market" in body
        assert body["market"] == "NQ"

    def test_health_works_without_auth(self, auth_client, _patch_globals_auth):
        """Health endpoint does NOT require authentication even when auth is enabled."""
        resp = auth_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# =========================================================================
# 3. Core Data Endpoints
# =========================================================================


class TestStateEndpoint:
    """/api/state endpoint."""

    def test_state_returns_correct_structure(self, client, _patch_globals):
        """State endpoint returns expected top-level keys when state file exists."""
        resp = client.get("/api/state")
        assert resp.status_code == 200
        body = resp.json()

        # Core required fields
        assert "running" in body
        assert body["running"] is True
        assert "paused" in body
        assert body["paused"] is False
        assert "daily_pnl" in body
        assert "daily_trades" in body
        assert "daily_wins" in body
        assert "daily_losses" in body
        assert "active_trades_count" in body
        assert "last_updated" in body
        assert "ai_status" in body
        assert "operator_lock_enabled" in body

    def test_state_handles_missing_state_file(self, client, _patch_globals_empty):
        """When state.json does not exist, endpoint still returns valid response."""
        resp = client.get("/api/state")
        assert resp.status_code == 200
        body = resp.json()
        # Should report not running
        assert body["running"] is False
        assert body["data_fresh"] is False
        assert "daily_pnl" in body

    def test_state_includes_ai_status(self, client, _patch_globals):
        """State response includes ai_status when learning data is in state."""
        resp = client.get("/api/state")
        body = resp.json()
        ai = body.get("ai_status")
        assert ai is not None
        assert isinstance(ai, dict)

    def test_state_returns_500_when_state_dir_not_configured(self, client):
        """If _state_dir is None, return 500."""
        with (
            patch.object(api_mod, "_state_dir", None),
            patch.object(api_mod, "_auth_enabled", False),
        ):
            resp = client.get("/api/state")
            assert resp.status_code == 500
            assert "not configured" in resp.json()["detail"].lower()


class TestCandlesEndpoint:
    """/api/candles endpoint."""

    def test_candles_returns_data_from_cache(self, client, _patch_globals, state_dir):
        """Candles endpoint returns cached data when no data provider."""
        # Seed the in-memory cache so the endpoint finds data
        cache_key = "MNQ_5m_72"
        sample_candles = [
            {"time": 1700000000, "open": 20000, "high": 20010, "low": 19990, "close": 20005, "volume": 1234},
            {"time": 1700000300, "open": 20005, "high": 20015, "low": 19998, "close": 20010, "volume": 987},
        ]
        with patch.dict(api_mod._candle_cache, {cache_key: sample_candles}):
            resp = client.get("/api/candles?symbol=MNQ&timeframe=5m&bars=72")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 2
        assert "time" in body[0]
        assert "open" in body[0]
        assert "close" in body[0]

    def test_candles_returns_503_when_no_data(self, client, _patch_globals):
        """When no provider and no cache exist, return 503."""
        with patch.dict(api_mod._candle_cache, {}, clear=True):
            resp = client.get("/api/candles?symbol=MNQ&timeframe=5m&bars=72")
        assert resp.status_code == 503
        body = resp.json()
        assert "data_unavailable" in body.get("detail", {}).get("error", "")

    def test_candles_validates_bars_param(self, client, _patch_globals):
        """Bars parameter below minimum (10) returns 422."""
        resp = client.get("/api/candles?bars=2")
        assert resp.status_code == 422


class TestTradesEndpoint:
    """/api/trades endpoint."""

    def test_trades_returns_list_of_exited_trades(self, client, _patch_globals):
        """Trades endpoint returns only exited signals as trade records."""
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        # Our sample data has 2 exited signals
        assert len(body) == 2

        trade = body[0]
        assert "signal_id" in trade
        assert "entry_price" in trade
        assert "exit_price" in trade
        assert "pnl" in trade
        assert "direction" in trade

    def test_trades_respects_limit_param(self, client, _patch_globals):
        """The limit query param restricts the number of returned trades."""
        resp = client.get("/api/trades?limit=1")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) <= 1

    def test_trades_returns_empty_when_no_signals(self, client, _patch_globals_empty):
        """Returns empty list when signals.jsonl does not exist."""
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 0


class TestPositionsEndpoint:
    """/api/positions endpoint."""

    def test_positions_returns_open_positions(self, client, _patch_globals):
        """Positions endpoint returns only non-exited entries with entry price."""
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        # Our sample has 1 active position (sig_003)
        assert len(body) == 1

        pos = body[0]
        assert pos["signal_id"] == "sig_003"
        assert pos["direction"] == "short"
        assert pos["entry_price"] == 20200.0
        assert pos["stop_loss"] == 20220.0
        assert pos["take_profit"] == 20170.0
        assert pos["position_size"] == 2

    def test_positions_returns_empty_when_no_signals(self, client, _patch_globals_empty):
        """Returns empty list when signals.jsonl does not exist."""
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        assert resp.json() == []


class TestPerformanceSummaryEndpoint:
    """/api/performance-summary endpoint."""

    def test_performance_summary_returns_period_buckets(
        self, client, _patch_globals, state_dir,
    ):
        """Performance summary returns td, yday, wtd, mtd, ytd, all buckets."""
        # Create a minimal performance.json (inception mode)
        perf = [
            {
                "exit_time": datetime.now(timezone.utc).isoformat(),
                "pnl": 50.0,
            }
        ]
        (state_dir / "performance.json").write_text(json.dumps(perf))

        resp = client.get("/api/performance-summary")
        assert resp.status_code == 200
        body = resp.json()
        for period in ("td", "yday", "wtd", "mtd", "ytd", "all"):
            assert period in body, "Missing period bucket: " + period

    def test_performance_summary_empty_when_no_file(self, client, _patch_globals_empty):
        """Returns zero-filled buckets when performance.json is absent."""
        resp = client.get("/api/performance-summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["all"]["pnl"] == 0.0
        assert body["all"]["trades"] == 0


# =========================================================================
# 4. Error Handling Tests
# =========================================================================


class TestErrorHandling:
    """Graceful error handling under adverse conditions."""

    def test_corrupt_state_file_returns_valid_response(
        self, client, _patch_globals, state_dir,
    ):
        """If state.json contains invalid JSON, endpoint still works gracefully."""
        (state_dir / "state.json").write_text("{invalid json <<<")
        resp = client.get("/api/state")
        # load_json_file returns {} on parse error -> endpoint treats as not running
        assert resp.status_code == 200
        body = resp.json()
        assert body["running"] is False

    def test_candles_bars_above_max_returns_422(self, client, _patch_globals):
        """Bars > 500 triggers validation error (422)."""
        resp = client.get("/api/candles?bars=9999")
        assert resp.status_code == 422

    def test_trades_limit_above_max_returns_422(self, client, _patch_globals):
        """Limit > 100 triggers validation error (422)."""
        resp = client.get("/api/trades?limit=999")
        assert resp.status_code == 422

    def test_candles_internal_error_returns_500(self, client, _patch_globals):
        """If _fetch_candles_with_source raises unexpected error, return 500."""
        with patch.object(
            api_mod,
            "_fetch_candles_with_source",
            side_effect=RuntimeError("Unexpected boom"),
        ):
            resp = client.get("/api/candles?symbol=MNQ&timeframe=5m&bars=72")
        assert resp.status_code == 500


# =========================================================================
# 5. WebSocket Tests
# =========================================================================


class TestWebSocket:
    """WebSocket endpoint at /ws."""

    def test_websocket_connect_without_auth(self, client, _patch_globals):
        """WebSocket connection succeeds when auth is disabled."""
        with client.websocket_connect("/ws") as ws:
            # Should receive initial_state message
            data = ws.receive_json()
            assert data["type"] == "initial_state"
            assert "data" in data
            inner = data["data"]
            assert "running" in inner
            assert "daily_pnl" in inner

    def test_websocket_sends_initial_state_fields(self, client, _patch_globals):
        """Initial state payload includes key dashboard fields."""
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            inner = data["data"]
            assert inner["running"] is True
            assert "active_trades_count" in inner
            assert "challenge" in inner
            assert "performance" in inner
            assert "operator_lock_enabled" in inner

    def test_websocket_responds_to_ping(self, client, _patch_globals):
        """Sending 'ping' text returns a pong JSON message."""
        with client.websocket_connect("/ws") as ws:
            # Consume initial state first
            ws.receive_json()
            # Send ping
            ws.send_text("ping")
            pong = ws.receive_json()
            assert pong["type"] == "pong"

    def test_websocket_rejects_invalid_key_via_query(self, client, _patch_globals_auth):
        """WebSocket with invalid api_key query param is closed with 1008."""
        with pytest.raises(Exception):
            # Connection should be rejected (close code 1008)
            with client.websocket_connect("/ws?api_key=" + INVALID_API_KEY) as ws:
                ws.receive_json()

    def test_websocket_accepts_valid_key_via_query(self, client, _patch_globals_auth):
        """WebSocket with valid api_key query param succeeds."""
        with client.websocket_connect("/ws?api_key=" + VALID_API_KEY) as ws:
            data = ws.receive_json()
            assert data["type"] == "initial_state"


# =========================================================================
# 6. Market Status Endpoint
# =========================================================================


class TestMarketStatusEndpoint:
    """Tests for GET /api/market-status."""

    def test_market_status_returns_200(self, client, _patch_globals):
        """Market status endpoint returns 200 with expected fields."""
        resp = client.get("/api/market-status")
        assert resp.status_code == 200
        body = resp.json()
        assert "is_open" in body
        assert isinstance(body["is_open"], bool)
        assert "current_time_et" in body


# =========================================================================
# 7. Path-Prefix Stripping (reverse-proxy support)
# =========================================================================


class TestPathPrefixStripping:
    """/mffu/ prefix should be stripped transparently."""

    def test_mffu_health_works(self, client, _patch_globals):
        """GET /mffu/health should route to /health."""
        resp = client.get("/mffu/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_mffu_api_state_works(self, client, _patch_globals):
        """GET /mffu/api/state should route to /api/state."""
        resp = client.get("/mffu/api/state")
        assert resp.status_code == 200
        assert "running" in resp.json()


# =========================================================================
# 8. Auth-Disabled Pass-Through
# =========================================================================


class TestAuthDisabledPassthrough:
    """When auth is disabled, protected endpoints should be freely accessible."""

    def test_state_accessible_without_key(self, client, _patch_globals):
        resp = client.get("/api/state")
        assert resp.status_code == 200

    def test_trades_accessible_without_key(self, client, _patch_globals):
        resp = client.get("/api/trades")
        assert resp.status_code == 200

    def test_positions_accessible_without_key(self, client, _patch_globals):
        resp = client.get("/api/positions")
        assert resp.status_code == 200

    def test_performance_accessible_without_key(self, client, _patch_globals):
        resp = client.get("/api/performance-summary")
        assert resp.status_code == 200
