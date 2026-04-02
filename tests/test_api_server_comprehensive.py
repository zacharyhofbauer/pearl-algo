"""
Comprehensive tests for the PearlAlgo API server to boost coverage.

Targets:
  - src/pearlalgo/api/server.py (route handlers + helper functions)
  - src/pearlalgo/api/server_core.py (core logic methods)
  - src/pearlalgo/api/data_layer.py (data loading)

All external I/O (state files, signals.jsonl, data providers) is mocked so
tests don't need real data.
"""

from __future__ import annotations

import collections
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Skip if FastAPI is not installed
fastapi = pytest.importorskip("fastapi", reason="FastAPI not installed")

from fastapi import HTTPException
from fastapi.testclient import TestClient  # noqa: E402

import pearlalgo.api.server as server_mod  # noqa: E402
core_mod = server_mod  # server_core merged into server
import pearlalgo.api.data_layer as data_layer_mod  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_API_KEY = "test-comprehensive-key-99999"
INVALID_API_KEY = "wrong-key-00000"
OPERATOR_PASS = "test-operator-pass"

SAMPLE_STATE: Dict[str, Any] = {
    "running": True,
    "paused": False,
    "futures_market_open": True,
    "data_fresh": True,
    "active_trades_count": 1,
    "active_trades_unrealized_pnl": 25.50,
    "learning": {"enabled": True, "mode": "shadow", "total_skips": 3, "total_decisions": 10, "execute_rate": 0.7},
    "learning_contextual": {"enabled": False},
    "ml_filter": {"enabled": True, "mode": "shadow", "lift": {"win_rate": 0.05}},
    "trading_circuit_breaker": {
        "direction_gating_enabled": True,
        "direction_gating_min_confidence": 0.7,
        "blocks_by_reason": {"direction_gating": 2, "consecutive_losses": 1, "rolling_win_rate": 0, "max_positions": 0},
        "would_block_by_reason": {"direction_gating": 1, "consecutive_losses": 0, "rolling_win_rate": 0, "max_positions": 0, "in_cooldown:consecutive_losses": 0, "in_cooldown:rolling_win_rate": 0},
        "would_block_total": 5,
        "would_have_blocked_regime": 1,
        "would_have_blocked_trigger": 0,
        "shadow_outcomes": {
            "blocked_wins": 1, "blocked_losses": 2, "blocked_total": 3, "blocked_pnl": -50.0,
            "allowed_wins": 5, "allowed_losses": 3, "allowed_total": 8, "allowed_pnl": 150.0,
            "net_saved": 50.0,
        },
    },
    "buy_sell_pressure_raw": {"buy": 0.6, "sell": 0.4},
    "cadence_metrics": {
        "cycle_duration_ms": 100,
        "duration_p50_ms": 90,
        "duration_p95_ms": 200,
        "velocity_mode_active": False,
        "velocity_reason": "",
        "missed_cycles": 0,
        "current_interval_seconds": 30,
        "cadence_lag_ms": 10,
    },
    "regime": "trending_up",
    "regime_confidence": 0.85,
    "connection": {"failures": 0, "data_fetch_errors": 0, "consecutive_errors": 0, "last_successful_fetch": "2025-06-01T12:00:00Z"},
    "data_provider": {"data_level": "FULL", "buffer_size": 500, "buffer_target": 500, "latest_bar_age_minutes": 0.5},
    "data_quality": {"latest_bar_age_minutes": 0.5, "stale_threshold_minutes": 2.0, "buffer_size": 500, "buffer_target": 500},
    "session_error_count": 0,
    "config": {"symbol": "MNQ", "market": "NQ", "timeframe": "5m", "scan_interval": 30},
    "shadow_mode": False,
    "tradovate_account": {"equity": 52000.0, "open_pnl": 50.0, "position_count": 1, "positions": [], "account_name": "DEMO123"},
}

SAMPLE_SIGNAL_ROWS: List[Dict[str, Any]] = [
    {
        "signal_id": "comp_001",
        "status": "exited",
        "entry_price": 18000.0,
        "exit_price": 18030.0,
        "entry_time": "2025-06-01T14:00:00Z",
        "exit_time": "2025-06-01T14:30:00Z",
        "pnl": 30.0,
        "exit_reason": "take_profit",
        "signal": {
            "direction": "long",
            "symbol": "MNQ",
            "stop_loss": 17980.0,
            "take_profit": 18030.0,
            "position_size": 1,
            "reason": "trend_follow",
            "confidence": 0.8,
            "type": "trend",
        },
    },
    {
        "signal_id": "comp_002",
        "status": "exited",
        "entry_price": 18100.0,
        "exit_price": 18080.0,
        "entry_time": "2025-06-01T15:00:00Z",
        "exit_time": "2025-06-01T15:20:00Z",
        "pnl": -20.0,
        "exit_reason": "stop_loss",
        "signal": {"direction": "short", "symbol": "MNQ", "stop_loss": 18120.0, "take_profit": 18060.0, "position_size": 1},
    },
    {
        "signal_id": "comp_003",
        "status": "active",
        "entry_price": 18200.0,
        "entry_time": "2025-06-01T16:00:00Z",
        "signal": {"direction": "long", "symbol": "MNQ", "stop_loss": 18180.0, "take_profit": 18240.0, "position_size": 1},
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
    (d / "performance.json").write_text(json.dumps([
        {"exit_time": "2025-06-01T14:30:00Z", "entry_time": "2025-06-01T14:00:00Z", "pnl": 30.0, "is_win": True, "direction": "long"},
        {"exit_time": "2025-06-01T15:20:00Z", "entry_time": "2025-06-01T15:00:00Z", "pnl": -20.0, "is_win": False, "direction": "short"},
    ]))
    return d


@pytest.fixture()
def _patch_no_auth(state_dir):
    """Patch both server modules: auth disabled, state_dir set."""
    patches = [
        patch.object(server_mod, "_state_dir", state_dir),
        patch.object(server_mod, "_market", "NQ"),
        patch.object(server_mod, "_auth_enabled", False),
        patch.object(server_mod, "_api_keys", set()),
        patch.object(server_mod, "_operator_enabled", False),
        patch.object(server_mod, "_operator_passphrase", ""),
        patch.object(server_mod, "_data_provider", None),
        patch.object(server_mod, "_data_provider_error", "mocked-away"),
        # server_core
        patch.object(core_mod, "_state_dir", state_dir),
        patch.object(core_mod, "_market", "NQ"),
        patch.object(core_mod, "_auth_enabled", False),
        patch.object(core_mod, "_api_keys", set()),
        patch.object(core_mod, "_operator_enabled", False),
        patch.object(core_mod, "_operator_passphrase", ""),
        patch.object(core_mod, "_data_provider", None),
        patch.object(core_mod, "_data_provider_error", "mocked-away"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def _patch_auth(state_dir):
    """Patch both server modules: auth ENABLED, state_dir set."""
    patches = [
        patch.object(server_mod, "_state_dir", state_dir),
        patch.object(server_mod, "_market", "NQ"),
        patch.object(server_mod, "_auth_enabled", True),
        patch.object(server_mod, "_api_keys", {VALID_API_KEY}),
        patch.object(server_mod, "_operator_enabled", False),
        patch.object(server_mod, "_operator_passphrase", ""),
        patch.object(server_mod, "_data_provider", None),
        patch.object(server_mod, "_data_provider_error", "mocked-away"),
        # server_core
        patch.object(core_mod, "_state_dir", state_dir),
        patch.object(core_mod, "_market", "NQ"),
        patch.object(core_mod, "_auth_enabled", True),
        patch.object(core_mod, "_api_keys", {VALID_API_KEY}),
        patch.object(core_mod, "_operator_enabled", False),
        patch.object(core_mod, "_data_provider", None),
        patch.object(core_mod, "_data_provider_error", "mocked-away"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def _patch_operator(state_dir):
    """Patch: operator passphrase enabled."""
    patches = [
        patch.object(server_mod, "_state_dir", state_dir),
        patch.object(server_mod, "_market", "NQ"),
        patch.object(server_mod, "_auth_enabled", False),
        patch.object(server_mod, "_api_keys", set()),
        patch.object(server_mod, "_operator_enabled", True),
        patch.object(server_mod, "_operator_passphrase", OPERATOR_PASS),
        patch.object(server_mod, "_operator_failures", {}),
        patch.object(server_mod, "_data_provider", None),
        patch.object(server_mod, "_data_provider_error", "mocked-away"),
        # server_core
        patch.object(core_mod, "_state_dir", state_dir),
        patch.object(core_mod, "_market", "NQ"),
        patch.object(core_mod, "_auth_enabled", False),
        patch.object(core_mod, "_api_keys", set()),
        patch.object(core_mod, "_operator_enabled", True),
        patch.object(core_mod, "_operator_passphrase", OPERATOR_PASS),
        patch.object(core_mod, "_operator_failures", {}),
        patch.object(core_mod, "_data_provider", None),
        patch.object(core_mod, "_data_provider_error", "mocked-away"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture()
def _patch_auth_and_operator(state_dir):
    """Patch: read-only API auth and operator passphrase both enabled."""
    patches = [
        patch.object(server_mod, "_state_dir", state_dir),
        patch.object(server_mod, "_market", "NQ"),
        patch.object(server_mod, "_auth_enabled", True),
        patch.object(server_mod, "_api_keys", {VALID_API_KEY}),
        patch.object(server_mod, "_operator_enabled", True),
        patch.object(server_mod, "_operator_passphrase", OPERATOR_PASS),
        patch.object(server_mod, "_operator_failures", {}),
        patch.object(server_mod, "_data_provider", None),
        patch.object(server_mod, "_data_provider_error", "mocked-away"),
        patch.object(core_mod, "_state_dir", state_dir),
        patch.object(core_mod, "_market", "NQ"),
        patch.object(core_mod, "_auth_enabled", True),
        patch.object(core_mod, "_api_keys", {VALID_API_KEY}),
        patch.object(core_mod, "_operator_enabled", True),
        patch.object(core_mod, "_operator_passphrase", OPERATOR_PASS),
        patch.object(core_mod, "_operator_failures", {}),
        patch.object(core_mod, "_data_provider", None),
        patch.object(core_mod, "_data_provider_error", "mocked-away"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture(autouse=True, scope="module")
def _patch_broadcast_loop():
    """Prevent the startup event's infinite broadcast loop from hanging tests."""
    async def _noop_broadcast(interval=2.0):
        return
    original = server_mod.ws_manager.start_broadcast_loop
    server_mod.ws_manager.start_broadcast_loop = _noop_broadcast
    yield
    server_mod.ws_manager.start_broadcast_loop = original


@pytest.fixture()
def client():
    return TestClient(server_mod.app, raise_server_exceptions=False)


# ===========================================================================
# 1. HEALTH ENDPOINT
# ===========================================================================


class TestHealthEndpoint:
    @pytest.mark.usefixtures("_patch_no_auth")
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    @pytest.mark.usefixtures("_patch_auth")
    def test_health_no_auth_required(self, client):
        """Health endpoint must be accessible without API key."""
        resp = client.get("/health")
        assert resp.status_code == 200


# ===========================================================================
# 2. AUTHENTICATION
# ===========================================================================


class TestAuthentication:
    @pytest.mark.usefixtures("_patch_auth")
    def test_valid_api_key_header(self, client):
        resp = client.get("/api/state", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 200

    @pytest.mark.usefixtures("_patch_auth")
    def test_valid_api_key_query(self, client):
        resp = client.get("/api/state", params={"api_key": VALID_API_KEY})
        assert resp.status_code == 200

    @pytest.mark.usefixtures("_patch_auth")
    def test_missing_api_key(self, client):
        resp = client.get("/api/state")
        assert resp.status_code == 401

    @pytest.mark.usefixtures("_patch_auth")
    def test_invalid_api_key(self, client):
        resp = client.get("/api/state", headers={"X-API-Key": INVALID_API_KEY})
        assert resp.status_code == 403

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_no_auth_passes(self, client):
        """When auth is disabled, all endpoints should be accessible."""
        resp = client.get("/api/state")
        assert resp.status_code == 200


# ===========================================================================
# 3. OPERATOR AUTH
# ===========================================================================


class TestOperatorAuth:
    @pytest.mark.usefixtures("_patch_operator")
    def test_operator_ping_valid(self, client):
        resp = client.get("/api/operator/ping", headers={"X-PEARL-OPERATOR": OPERATOR_PASS})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.usefixtures("_patch_operator")
    def test_operator_ping_invalid(self, client):
        resp = client.get("/api/operator/ping", headers={"X-PEARL-OPERATOR": "wrong-pass"})
        assert resp.status_code == 403

    @pytest.mark.usefixtures("_patch_operator")
    def test_operator_ping_missing(self, client):
        resp = client.get("/api/operator/ping")
        assert resp.status_code == 403

    @pytest.mark.usefixtures("_patch_auth_and_operator")
    def test_operator_ping_rejects_api_key_only(self, client):
        resp = client.get("/api/operator/ping", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 403


# ===========================================================================
# 4. GET /api/state
# ===========================================================================


class TestStateEndpoint:
    @pytest.mark.usefixtures("_patch_auth_and_operator")
    def test_state_still_accepts_read_only_api_key_when_operator_enabled(self, client):
        resp = client.get("/api/state", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 200

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_state_full(self, client):
        resp = client.get("/api/state")
        assert resp.status_code == 200
        body = resp.json()
        assert "running" in body
        assert "daily_pnl" in body
        assert "ai_status" in body
        assert "market_regime" in body
        assert "cadence_metrics" in body
        assert "operator_lock_enabled" in body

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_state_includes_config(self, client):
        resp = client.get("/api/state")
        body = resp.json()
        assert "config" in body

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_state_includes_connection_health(self, client):
        resp = client.get("/api/state")
        body = resp.json()
        assert "connection_health" in body

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_state_when_empty(self, client, state_dir):
        """When state.json is empty/missing, should still return data."""
        (state_dir / "state.json").write_text("{}")
        # Clear all cached state readers to force re-read
        server_mod._state_reader_cache.clear()
        server_mod._state_reader = None
        core_mod._state_reader_cache.clear()
        core_mod._state_reader = None
        data_layer_mod._state_reader_cache.clear()
        resp = client.get("/api/state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["running"] is False


# ===========================================================================
# 5. GET /api/trades
# ===========================================================================


class TestTradesEndpoint:
    @pytest.mark.usefixtures("_patch_no_auth")
    def test_trades_returns_list(self, client):
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_trades_with_limit(self, client):
        resp = client.get("/api/trades?limit=1")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) <= 1

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_trades_exited_only(self, client):
        resp = client.get("/api/trades")
        body = resp.json()
        for trade in body:
            # Trade should have pnl (only exited trades)
            assert "pnl" in trade

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_trades_fields(self, client):
        resp = client.get("/api/trades")
        body = resp.json()
        if body:
            trade = body[0]
            for key in ("signal_id", "symbol", "direction", "entry_time", "exit_time", "pnl"):
                assert key in trade, f"Missing key: {key}"


# ===========================================================================
# 6. GET /api/signals
# ===========================================================================


class TestSignalsEndpoint:
    @pytest.mark.usefixtures("_patch_no_auth")
    def test_signals_returns_list(self, client):
        resp = client.get("/api/signals")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_signals_with_limit(self, client):
        resp = client.get("/api/signals?limit=2")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) <= 2


# ===========================================================================
# 7. GET /api/positions
# ===========================================================================


class TestPositionsEndpoint:
    @pytest.mark.usefixtures("_patch_no_auth")
    def test_positions_returns_list(self, client):
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_positions_have_entry_price(self, client):
        resp = client.get("/api/positions")
        body = resp.json()
        for pos in body:
            assert "entry_price" in pos
            assert pos["entry_price"] is not None


# ===========================================================================
# 8. GET /api/performance-summary
# ===========================================================================


class TestPerformanceSummary:
    @pytest.mark.usefixtures("_patch_no_auth")
    def test_summary_returns_periods(self, client):
        resp = client.get("/api/performance-summary")
        assert resp.status_code == 200
        body = resp.json()
        for period in ("td", "yday", "wtd", "mtd", "ytd", "all"):
            assert period in body, f"Missing period: {period}"

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_summary_period_fields(self, client):
        resp = client.get("/api/performance-summary")
        body = resp.json()
        period_data = body["all"]
        for key in ("pnl", "trades", "wins", "losses", "win_rate"):
            assert key in period_data


# ===========================================================================
# 9. GET /api/markers
# ===========================================================================


class TestMarkersEndpoint:
    @pytest.mark.usefixtures("_patch_no_auth")
    def test_markers_returns_list(self, client):
        resp = client.get("/api/markers")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_markers_with_hours(self, client):
        resp = client.get("/api/markers?hours=1")
        assert resp.status_code == 200


# ===========================================================================
# 10. GET /api/candles
# ===========================================================================


class TestCandlesEndpoint:
    @pytest.mark.usefixtures("_patch_no_auth")
    def test_candles_no_provider_no_cache(self, client):
        """Should return 503 when no data provider and no cache."""
        resp = client.get("/api/candles")
        assert resp.status_code == 503

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_candles_with_cache(self, client, state_dir):
        """Should return cached data when available."""
        cache_data = [{"time": 1706500000, "open": 26200, "high": 26210, "low": 26195, "close": 26205, "volume": 100}]
        with patch.object(server_mod, "_load_candle_cache", return_value=cache_data):
            resp = client.get("/api/candles")
            assert resp.status_code == 200


# ===========================================================================
# 11. GET /api/indicators
# ===========================================================================


class TestIndicatorsEndpoint:
    @pytest.mark.usefixtures("_patch_no_auth")
    def test_indicators_no_data(self, client):
        """Should return 503 when no candle data."""
        resp = client.get("/api/indicators")
        assert resp.status_code == 503


# ===========================================================================
# 12. POST /api/kill-switch
# ===========================================================================


class TestKillSwitch:
    @pytest.mark.usefixtures("_patch_operator")
    def test_kill_switch_with_operator(self, client, state_dir):
        # Reset rate limiter for clean test
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post(
            "/api/kill-switch",
            headers={"X-PEARL-OPERATOR": OPERATOR_PASS},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    @pytest.mark.usefixtures("_patch_operator")
    def test_kill_switch_no_operator(self, client):
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post("/api/kill-switch")
        assert resp.status_code == 403

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_kill_switch_no_operator_no_auth_requires_operator(self, client):
        """When operator is disabled and auth disabled, operator endpoints should fail."""
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post("/api/kill-switch")
        assert resp.status_code == 403

    @pytest.mark.usefixtures("_patch_auth_and_operator")
    def test_kill_switch_rejects_api_key_only_when_operator_enabled(self, client):
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post("/api/kill-switch", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 403


# ===========================================================================
# 13. POST /api/resume
# ===========================================================================


class TestResumeEndpoint:
    @pytest.mark.usefixtures("_patch_operator")
    def test_resume_with_operator(self, client, state_dir):
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post(
            "/api/resume",
            headers={"X-PEARL-OPERATOR": OPERATOR_PASS},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert (state_dir / "resume_request.flag").exists()


# ===========================================================================
# 14. POST /api/close-all-trades
# ===========================================================================


class TestCloseAllTrades:
    @pytest.mark.usefixtures("_patch_operator")
    def test_close_all_trades(self, client, state_dir):
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post(
            "/api/close-all-trades",
            headers={"X-PEARL-OPERATOR": OPERATOR_PASS},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["ok"] is True

    @pytest.mark.usefixtures("_patch_auth_and_operator")
    def test_close_all_trades_rejects_api_key_only(self, client):
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post(
            "/api/close-all-trades",
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 403


# ===========================================================================
# 15. POST /api/close-trade
# ===========================================================================


class TestCloseTrade:
    @pytest.mark.usefixtures("_patch_operator")
    def test_close_trade_valid(self, client, state_dir):
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post(
            "/api/close-trade",
            json={"signal_id": "sig_001"},
            headers={"X-PEARL-OPERATOR": OPERATOR_PASS},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["ok"] is True
        assert body["signal_id"] == "sig_001"

    @pytest.mark.usefixtures("_patch_operator")
    def test_close_trade_missing_signal_id(self, client):
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post(
            "/api/close-trade",
            json={},
            headers={"X-PEARL-OPERATOR": OPERATOR_PASS},
        )
        assert resp.status_code == 422

    @pytest.mark.usefixtures("_patch_auth_and_operator")
    def test_close_trade_rejects_api_key_only(self, client):
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post(
            "/api/close-trade",
            json={"signal_id": "sig_001"},
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 403


# ===========================================================================
# 16. RATE LIMITING
# ===========================================================================


class TestRateLimiting:
    def test_check_rate_limit_allows_under_limit(self):
        """Requests under the limit should pass."""
        server_mod._rate_limit_buckets.clear()
        # Should not raise
        server_mod._check_rate_limit("test-endpoint-a")

    def test_check_rate_limit_blocks_over_limit(self):
        """Requests over the limit should raise 429."""
        server_mod._rate_limit_buckets.clear()
        for _ in range(server_mod._rate_limit_max):
            server_mod._check_rate_limit("test-endpoint-b")
        with pytest.raises(HTTPException) as exc_info:
            server_mod._check_rate_limit("test-endpoint-b")
        assert exc_info.value.status_code == 429


# ===========================================================================
# 17. HELPER FUNCTIONS: _get_ai_status
# ===========================================================================


class TestGetAiStatus:
    def test_ai_status_with_full_state(self):
        result = server_mod._get_ai_status(SAMPLE_STATE)
        assert "bandit_mode" in result
        assert "contextual_mode" in result
        assert "ml_filter" in result
        assert "direction_gating" in result

    def test_ai_status_bandit_mode(self):
        result = server_mod._get_ai_status(SAMPLE_STATE)
        assert result["bandit_mode"] == "shadow"

    def test_ai_status_contextual_off(self):
        result = server_mod._get_ai_status(SAMPLE_STATE)
        assert result["contextual_mode"] == "off"

    def test_ai_status_empty_state(self):
        result = server_mod._get_ai_status({})
        assert result["bandit_mode"] == "off"
        assert result["contextual_mode"] == "off"


# ===========================================================================
# 18. HELPER: _get_market_regime
# ===========================================================================


class TestGetMarketRegime:
    def test_market_regime_trending_up(self):
        result = server_mod._get_market_regime(SAMPLE_STATE)
        assert result["regime"] == "trending_up"
        assert result["confidence"] == 0.85
        assert result["allowed_direction"] == "long"

    def test_market_regime_trending_down(self):
        state = {**SAMPLE_STATE, "regime": "trending_down", "regime_confidence": 0.9}
        result = server_mod._get_market_regime(state)
        assert result["allowed_direction"] == "short"

    def test_market_regime_low_confidence(self):
        state = {**SAMPLE_STATE, "regime": "trending_up", "regime_confidence": 0.3}
        result = server_mod._get_market_regime(state)
        assert result["allowed_direction"] == "both"

    def test_market_regime_unknown(self):
        result = server_mod._get_market_regime({})
        assert result["regime"] == "unknown"
        assert result["confidence"] == 0.0


# ===========================================================================
# 19. HELPER: _get_cadence_metrics_enhanced
# ===========================================================================


class TestGetCadenceMetrics:
    def test_cadence_from_state(self):
        result = server_mod._get_cadence_metrics_enhanced(SAMPLE_STATE)
        assert result["cycle_duration_ms"] == 100
        assert result["missed_cycles"] == 0

    def test_cadence_empty_state(self):
        result = server_mod._get_cadence_metrics_enhanced({})
        assert result["cycle_duration_ms"] == 0


# ===========================================================================
# 20. HELPER: _get_connection_health
# ===========================================================================


class TestGetConnectionHealth:
    def test_connection_health(self):
        result = server_mod._get_connection_health(SAMPLE_STATE)
        assert result["connection_failures"] == 0
        assert result["data_level"] == "FULL"

    def test_connection_health_empty(self):
        result = server_mod._get_connection_health({})
        assert result["connection_failures"] == 0
        assert result["data_level"] == "UNKNOWN"


# ===========================================================================
# 21. HELPER: _get_config
# ===========================================================================


class TestGetConfig:
    def test_config_fields(self):
        result = server_mod._get_config(SAMPLE_STATE)
        assert result["symbol"] == "MNQ"
        assert result["mode"] == "live"

    def test_config_paused(self):
        state = {**SAMPLE_STATE, "paused": True}
        result = server_mod._get_config(state)
        assert result["mode"] == "paused"

    def test_config_stopped(self):
        state = {**SAMPLE_STATE, "running": False}
        result = server_mod._get_config(state)
        assert result["mode"] == "stopped"

    def test_config_shadow(self):
        state = {**SAMPLE_STATE, "shadow_mode": True}
        result = server_mod._get_config(state)
        assert result["mode"] == "shadow"


# ===========================================================================
# 22. HELPER: _get_data_quality
# ===========================================================================


class TestGetDataQuality:
    def test_data_quality(self):
        result = server_mod._get_data_quality(SAMPLE_STATE)
        assert result["buffer_size"] == 500
        assert result["is_stale"] is False

    def test_data_quality_market_closed(self):
        state = {**SAMPLE_STATE, "futures_market_open": False}
        result = server_mod._get_data_quality(state)
        assert result["is_expected_stale"] is True


# ===========================================================================
# 23. HELPER: _get_error_summary
# ===========================================================================


class TestGetErrorSummary:
    def test_error_summary_no_errors(self, tmp_path):
        result = server_mod._get_error_summary(tmp_path, SAMPLE_STATE)
        assert result["session_error_count"] == 0
        assert result["last_error"] is None

    def test_error_summary_with_state_error(self, tmp_path):
        state = {**SAMPLE_STATE, "session_error_count": 5, "last_error": "Connection timeout", "last_error_time": "2025-06-01T12:00:00Z"}
        result = server_mod._get_error_summary(tmp_path, state)
        assert result["session_error_count"] == 5
        assert result["last_error"] == "Connection timeout"

    def test_error_summary_from_log_file(self, tmp_path):
        log_file = tmp_path / "errors.log"
        log_file.write_text('{"message": "Test error", "timestamp": "2025-06-01T12:00:00Z"}\n')
        result = server_mod._get_error_summary(tmp_path, {"session_error_count": 0})
        assert result["last_error"] == "Test error"

    def test_error_summary_truncates_long_messages(self, tmp_path):
        state = {**SAMPLE_STATE, "last_error": "A" * 200}
        result = server_mod._get_error_summary(tmp_path, state)
        assert len(result["last_error"]) <= 80


# ===========================================================================
# 24. HELPER: _get_signal_rejections_24h
# ===========================================================================


class TestGetSignalRejections:
    def test_rejections(self):
        result = server_mod._get_signal_rejections_24h(SAMPLE_STATE)
        assert result["direction_gating"] == 3  # 2 blocks + 1 would_block
        assert result["circuit_breaker"] == 1  # 1 consecutive_losses block

    def test_rejections_empty(self):
        result = server_mod._get_signal_rejections_24h({})
        assert result["direction_gating"] == 0


# ===========================================================================
# 25. HELPER: _get_last_signal_decision
# ===========================================================================


class TestGetLastSignalDecision:
    def test_no_decision(self):
        result = server_mod._get_last_signal_decision({})
        assert result is None

    def test_with_decision(self):
        state = {"learning": {"last_decision": {"signal_type": "long", "score": 0.8, "execute": True, "reason": "test", "at": "2025-06-01T12:00:00Z"}}}
        result = server_mod._get_last_signal_decision(state)
        assert result is not None
        assert result["action"] == "execute"
        assert result["ml_probability"] == 0.8


# ===========================================================================
# 26. HELPER: _get_shadow_counters
# ===========================================================================


class TestGetShadowCounters:
    def test_shadow_counters(self):
        result = server_mod._get_shadow_counters(SAMPLE_STATE)
        assert result["would_block_total"] == 5
        assert result["net_saved"] == 50.0

    def test_shadow_counters_empty(self):
        result = server_mod._get_shadow_counters({})
        assert result["would_block_total"] == 0


# ===========================================================================
# 27. HELPER: _json_sanitize
# ===========================================================================


class TestJsonSanitize:
    def test_sanitize_dict(self):
        result = server_mod._json_sanitize({"key": "value", "num": 42})
        assert result == {"key": "value", "num": 42}

    def test_sanitize_datetime(self):
        """Datetime objects should be converted to strings."""
        result = server_mod._json_sanitize({"time": datetime(2025, 6, 1, tzinfo=timezone.utc)})
        assert isinstance(result["time"], str)

    def test_sanitize_non_serializable(self):
        """Non-serializable objects should be stringified."""
        result = server_mod._json_sanitize({"obj": object()})
        assert isinstance(result["obj"], str)


# ===========================================================================
# 28. HELPER: _snap_to_bar
# ===========================================================================


class TestSnapToBar:
    def test_snap_exact(self):
        assert server_mod._snap_to_bar(300, 300) == 300

    def test_snap_down(self):
        assert server_mod._snap_to_bar(450, 300) == 300

    def test_snap_1m(self):
        assert server_mod._snap_to_bar(90, 60) == 60


# ===========================================================================
# 29. CANDLE CACHE (memory-level)
# ===========================================================================


class TestCandleCache:
    def test_cache_set_get(self):
        server_mod._candle_cache_set("test_key", [{"time": 1}])
        result = server_mod._candle_cache_get("test_key")
        assert result == [{"time": 1}]

    def test_cache_miss(self):
        result = server_mod._candle_cache_get("nonexistent_key_12345")
        assert result is None

    def test_cache_eviction(self):
        """LRU eviction when cache exceeds max size."""
        orig_max = server_mod._CANDLE_CACHE_MAX_ENTRIES
        try:
            server_mod._CANDLE_CACHE_MAX_ENTRIES = 2
            server_mod._candle_cache.clear()
            server_mod._candle_cache_set("evict_a", [{"time": 1}])
            server_mod._candle_cache_set("evict_b", [{"time": 2}])
            server_mod._candle_cache_set("evict_c", [{"time": 3}])
            # 'a' should have been evicted
            assert server_mod._candle_cache_get("evict_a") is None
            assert server_mod._candle_cache_get("evict_c") is not None
        finally:
            server_mod._CANDLE_CACHE_MAX_ENTRIES = orig_max


# ===========================================================================
# 30. TTL CACHE (_cached)
# ===========================================================================


class TestTtlCache:
    def test_cached_returns_fresh(self):
        server_mod._ttl_cache.clear()
        call_count = {"n": 0}

        def compute():
            call_count["n"] += 1
            return 42

        result1 = server_mod._cached("ttl_test_1", 60.0, compute)
        result2 = server_mod._cached("ttl_test_1", 60.0, compute)
        assert result1 == 42
        assert result2 == 42
        assert call_count["n"] == 1  # Only called once

    def test_cached_expired(self):
        server_mod._ttl_cache.clear()
        # Insert an expired entry
        server_mod._ttl_cache["ttl_test_2"] = ("old_value", time.monotonic() - 10)
        result = server_mod._cached("ttl_test_2", 60.0, lambda: "new_value")
        assert result == "new_value"


# ===========================================================================
# 31. _resolve_state_dir
# ===========================================================================


class TestResolveStateDir:
    def test_default_market(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PEARLALGO_STATE_DIR", None)
            result = server_mod._resolve_state_dir("NQ")
            assert "NQ" in str(result)

    def test_env_override(self):
        with patch.dict(os.environ, {"PEARLALGO_STATE_DIR": "/tmp/test_state"}):
            result = server_mod._resolve_state_dir("NQ")
            assert str(result) == "/tmp/test_state"

    def test_uppercase(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PEARLALGO_STATE_DIR", None)
            result = server_mod._resolve_state_dir("nq")
            assert "NQ" in str(result)


# ===========================================================================
# 32. _require_state_dir
# ===========================================================================


class TestRequireStateDir:
    def test_raises_when_none(self):
        with patch.object(server_mod, "_state_dir", None):
            with pytest.raises(HTTPException) as exc_info:
                server_mod._require_state_dir()
            assert exc_info.value.status_code == 500


# ===========================================================================
# 33. ConnectionManager
# ===========================================================================


class TestConnectionManager:
    def test_init(self):
        mgr = server_mod.ConnectionManager()
        assert mgr.active_connections == []

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        mgr = server_mod.ConnectionManager()
        ws = MagicMock()
        await mgr.connect(ws)
        assert ws in mgr.active_connections
        mgr.disconnect(ws)
        assert ws not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_connect_cap(self):
        mgr = server_mod.ConnectionManager()
        for i in range(server_mod._WS_MAX_CONNECTIONS):
            ws = MagicMock()
            await mgr.connect(ws)
        extra = MagicMock()
        accepted = await mgr.connect(extra)
        assert accepted is False

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self):
        mgr = server_mod.ConnectionManager()
        # Should not raise
        await mgr.broadcast({"type": "test"})

    def test_disconnect_not_connected(self):
        mgr = server_mod.ConnectionManager()
        ws = MagicMock()
        # Should not raise
        mgr.disconnect(ws)


# ===========================================================================
# 34. _aggregate_performance_since
# ===========================================================================


class TestAggregatePerformanceSince:
    def test_basic_aggregation(self):
        trades = [
            {"exit_time": "2025-06-01T14:00:00Z", "pnl": 30.0, "is_win": True},
            {"exit_time": "2025-06-01T15:00:00Z", "pnl": -10.0, "is_win": False},
        ]
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        result = server_mod._aggregate_performance_since(trades, cutoff)
        assert result["pnl"] == 20.0
        assert result["trades"] == 2
        assert result["wins"] == 1
        assert result["losses"] == 1
        assert result["win_rate"] == 50.0

    def test_with_end_filter(self):
        trades = [
            {"exit_time": "2025-06-01T14:00:00Z", "pnl": 30.0},
            {"exit_time": "2025-06-01T16:00:00Z", "pnl": -10.0},
        ]
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        end = datetime(2025, 6, 1, 15, 0, 0, tzinfo=timezone.utc)
        result = server_mod._aggregate_performance_since(trades, cutoff, end)
        assert result["trades"] == 1
        assert result["pnl"] == 30.0

    def test_empty_trades(self):
        result = server_mod._aggregate_performance_since([], datetime(2020, 1, 1, tzinfo=timezone.utc))
        assert result["trades"] == 0
        assert result["win_rate"] == 0.0

    def test_missing_exit_time(self):
        trades = [{"pnl": 10.0}]
        result = server_mod._aggregate_performance_since(trades, datetime(2020, 1, 1, tzinfo=timezone.utc))
        assert result["trades"] == 0


# ===========================================================================
# 35. _get_trading_week_start
# ===========================================================================


class TestTradingWeekStart:
    def test_returns_datetime(self):
        now = datetime(2025, 6, 4, 12, 0, 0, tzinfo=timezone.utc)  # Wednesday
        result = server_mod._get_trading_week_start(now)
        assert isinstance(result, datetime)
        # FIXED 2026-03-25: returns naive ET after timezone migration
        assert result.tzinfo is None

    def test_sunday_before_6pm(self):
        """On Sunday before 6pm ET, should return prior week's start."""
        # FIXED 2026-03-25: use naive ET for comparison after timezone migration
        sun_early_et = datetime(2025, 6, 1, 14, 0, 0)  # Sunday 2pm ET (naive)
        result = server_mod._get_trading_week_start(sun_early_et)
        # Should be a week before
        assert result < sun_early_et


# ===========================================================================
# 36. _get_month_to_date_start / _get_year_to_date_start
# ===========================================================================


class TestDateBoundaryHelpers:
    def test_mtd_start(self):
        now = datetime(2025, 6, 15, 12, 0, 0)  # FIXED 2026-03-25: naive ET
        result = server_mod._get_month_to_date_start(now)
        assert isinstance(result, datetime)
        assert result < now

    def test_ytd_start(self):
        now = datetime(2025, 6, 15, 12, 0, 0)  # FIXED 2026-03-25: naive ET
        result = server_mod._get_year_to_date_start(now)
        assert isinstance(result, datetime)
        assert result < now
        # Should be near Jan 1 boundary
        assert result.month in (1, 12)


# ===========================================================================
# 37. _get_previous_trading_day_bounds
# ===========================================================================


class TestPreviousTradingDayBounds:
    def test_returns_tuple(self):
        result = server_mod._get_previous_trading_day_bounds()
        assert isinstance(result, tuple)
        assert len(result) == 2
        start, end = result
        assert end - start == timedelta(days=1)


# ===========================================================================
# 38. MIDDLEWARE: path prefix stripping
# ===========================================================================


class TestPathPrefixStripping:
    @pytest.mark.usefixtures("_patch_no_auth")
    def test_tv_paper_prefix_stripped(self, client):
        resp = client.get("/tv_paper/health")
        assert resp.status_code == 200

    @pytest.mark.usefixtures("_patch_no_auth")
    def test_tv_paper_prefix_stripped_api(self, client):
        resp = client.get("/tv_paper/api/state")
        assert resp.status_code == 200


# ===========================================================================
# 39. MIDDLEWARE: request body size limit
# ===========================================================================


class TestRequestBodySizeLimit:
    @pytest.mark.usefixtures("_patch_operator")
    def test_large_body_rejected(self, client):
        """Requests with Content-Length > 1MB should be rejected."""
        server_mod._rate_limit_buckets.clear()
        core_mod._rate_limit_buckets.clear()
        resp = client.post(
            "/api/close-trade",
            content="x" * 100,  # small body
            headers={
                "Content-Length": str(2 * 1024 * 1024),
                "X-PEARL-OPERATOR": OPERATOR_PASS,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 413


# ===========================================================================
# 40. _load_api_keys
# ===========================================================================


class TestLoadApiKeys:
    def test_load_from_env(self):
        with patch.dict(os.environ, {"PEARL_API_KEY": "env-key-123"}):
            with patch.object(server_mod, "_auth_enabled", True):
                keys = server_mod._load_api_keys()
                assert "env-key-123" in keys

    def test_auto_generate(self, tmp_path):
        """When no keys configured, auto-generates one."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PEARL_API_KEY", None)
            os.environ.pop("PEARL_API_KEY_FILE", None)
            with patch.object(server_mod, "_auth_enabled", True):
                with patch.object(server_mod, "PROJECT_ROOT", tmp_path):
                    keys = server_mod._load_api_keys()
                    assert len(keys) == 1

    def test_load_from_file(self, tmp_path):
        key_file = tmp_path / "keys.txt"
        key_file.write_text("file-key-abc\n# comment\nfile-key-def\n")
        with patch.dict(os.environ, {"PEARL_API_KEY_FILE": str(key_file)}):
            os.environ.pop("PEARL_API_KEY", None)
            with patch.object(server_mod, "_auth_enabled", True):
                keys = server_mod._load_api_keys()
                assert "file-key-abc" in keys
                assert "file-key-def" in keys
                assert len([k for k in keys if k.startswith("#")]) == 0


# ===========================================================================
# 41. _cors_origins
# ===========================================================================


class TestCorsOrigins:
    def test_default_origins(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PEARL_LIVE_CHART_ORIGINS", None)
            origins = server_mod._cors_origins()
            assert "http://localhost:3001" in origins

    def test_custom_origins(self):
        with patch.dict(os.environ, {"PEARL_LIVE_CHART_ORIGINS": "https://example.com,https://other.com"}):
            origins = server_mod._cors_origins()
            assert "https://example.com" in origins
            assert "https://other.com" in origins


# ===========================================================================
# 42. _get_client_id
# ===========================================================================


class TestGetClientId:
    def test_forwarded_for(self):
        request = MagicMock()
        request.headers.get.return_value = "1.2.3.4, 5.6.7.8"
        result = server_mod._get_client_id(request)
        assert result == "1.2.3.4"

    def test_direct_client(self):
        request = MagicMock()
        request.headers.get.return_value = None
        request.client.host = "10.0.0.1"
        result = server_mod._get_client_id(request)
        assert result == "10.0.0.1"

    def test_no_client(self):
        request = MagicMock()
        request.headers.get.return_value = None
        request.client = None
        result = server_mod._get_client_id(request)
        assert result == "unknown"


# ===========================================================================
# 43. _write_operator_request
# ===========================================================================


class TestWriteOperatorRequest:
    def test_writes_file(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        payload = {"action": "close_trade", "signal_id": "sig_001"}
        result = server_mod._write_operator_request(state_dir, "close_trade", payload)
        assert result.exists()
        data = json.loads(result.read_text())
        assert data["signal_id"] == "sig_001"


# ===========================================================================
# 44. _wait_for_ack
# ===========================================================================


class TestWaitForAck:
    @pytest.mark.asyncio
    async def test_ack_not_found(self, tmp_path):
        flag = tmp_path / "test.flag"
        flag.write_text("{}")
        result = await server_mod._wait_for_ack(flag, timeout=0.5)
        assert result is False

    @pytest.mark.asyncio
    async def test_ack_found(self, tmp_path):
        flag = tmp_path / "test.flag"
        flag.write_text("{}")
        # Pre-create ack file
        ack = flag.with_suffix(".flag.ack")
        ack.write_text("{}")
        result = await server_mod._wait_for_ack(flag, timeout=1.0)
        assert result is True
        assert not ack.exists()  # Should be cleaned up


# ===========================================================================
# 45. DATA LAYER: cached()
# ===========================================================================


class TestDataLayerCached:
    def test_cached_fresh(self):
        data_layer_mod._ttl_cache.clear()
        result = data_layer_mod.cached("dl_test_1", 60.0, lambda: "hello")
        assert result == "hello"

    def test_cached_reuses(self):
        data_layer_mod._ttl_cache.clear()
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            return calls["n"]
        r1 = data_layer_mod.cached("dl_test_2", 60.0, fn)
        r2 = data_layer_mod.cached("dl_test_2", 60.0, fn)
        assert r1 == r2 == 1


# ===========================================================================
# 46. DATA LAYER: read_state_for_dir
# ===========================================================================


class TestDataLayerReadStateForDir:
    def test_reads_state(self, state_dir):
        data_layer_mod._state_reader_cache.clear()
        result = data_layer_mod.read_state_for_dir(state_dir)
        assert isinstance(result, dict)


# ===========================================================================
# 47. DATA LAYER: get_start_balance
# ===========================================================================


class TestDataLayerStartBalance:
    def test_default_balance(self, tmp_path):
        assert data_layer_mod.get_start_balance(tmp_path) == 50000.0

    def test_from_challenge(self, tmp_path):
        (tmp_path / "challenge_state.json").write_text(json.dumps({
            "config": {"start_balance": 75000.0}
        }))
        assert data_layer_mod.get_start_balance(tmp_path) == 75000.0


# ===========================================================================
# 48. DATA LAYER: TvPaperChallengeState
# ===========================================================================


class TestTvPaperChallengeState:
    def test_from_challenge_data_none(self):
        result = data_layer_mod.TvPaperChallengeState.from_challenge_data({})
        assert result is None

    def test_from_challenge_data_valid(self):
        data = {"tv_paper": {"stage": "verification", "eod_high_water_mark": 52000.0, "trading_days_count": 5}}
        result = data_layer_mod.TvPaperChallengeState.from_challenge_data(data)
        assert result is not None
        assert result.stage == "verification"
        assert result.eod_high_water_mark == 52000.0
        assert result.trading_days_count == 5

    def test_to_dict(self):
        state = data_layer_mod.TvPaperChallengeState(stage="evaluation", trading_days_count=3)
        d = state.to_dict()
        assert d["stage"] == "evaluation"
        assert d["trading_days_count"] == 3


# ===========================================================================
# 49. DATA LAYER: _safe_float
# ===========================================================================


class TestSafeFloat:
    def test_none(self):
        assert data_layer_mod._safe_float(None) is None

    def test_int(self):
        assert data_layer_mod._safe_float(42) == 42.0

    def test_string(self):
        assert data_layer_mod._safe_float("3.14") == 3.14

    def test_invalid(self):
        assert data_layer_mod._safe_float("abc") is None


# ===========================================================================
# 50. DATA LAYER: get_signals
# ===========================================================================


class TestDataLayerGetSignals:
    def test_get_signals(self, state_dir):
        data_layer_mod._ttl_cache.clear()
        signals = data_layer_mod.get_signals(state_dir, max_lines=100)
        assert isinstance(signals, list)
        assert len(signals) > 0

    def test_get_signals_missing_file(self, tmp_path):
        data_layer_mod._ttl_cache.clear()
        signals = data_layer_mod.get_signals(tmp_path, max_lines=100)
        assert signals == []


# ===========================================================================
# 51. DATA LAYER: load_performance_data
# ===========================================================================


class TestDataLayerLoadPerformance:
    def test_load_perf(self, state_dir):
        data_layer_mod._ttl_cache.clear()
        result = data_layer_mod.load_performance_data(state_dir)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_load_perf_missing(self, tmp_path):
        data_layer_mod._ttl_cache.clear()
        result = data_layer_mod.load_performance_data(tmp_path)
        assert result == []


# ===========================================================================
# 52. DATA LAYER: get_cached_performance_data
# ===========================================================================


class TestDataLayerGetCachedPerformance:
    def test_cached_perf_valid(self, state_dir):
        data_layer_mod._ttl_cache.clear()
        result = data_layer_mod.get_cached_performance_data(state_dir)
        assert "trades" in result
        assert len(result["trades"]) == 2

    def test_cached_perf_missing(self, tmp_path):
        data_layer_mod._ttl_cache.clear()
        result = data_layer_mod.get_cached_performance_data(tmp_path)
        assert result == {}


# ===========================================================================
# 53. DATA LAYER: _cleanup_ttl_cache
# ===========================================================================


class TestDataLayerCleanupTtlCache:
    def test_cleanup_removes_expired(self):
        data_layer_mod._ttl_cache.clear()
        now = time.monotonic()
        data_layer_mod._ttl_cache["expired_key"] = ("val", now - 10)
        data_layer_mod._ttl_cache["fresh_key"] = ("val2", now + 100)
        data_layer_mod._cleanup_ttl_cache()
        assert "expired_key" not in data_layer_mod._ttl_cache
        assert "fresh_key" in data_layer_mod._ttl_cache


# ===========================================================================
# 54. server_core HELPERS
# ===========================================================================


class TestServerCoreHelpers:
    def test_get_ai_status(self):
        result = core_mod._get_ai_status(SAMPLE_STATE)
        assert "bandit_mode" in result

    def test_get_market_regime(self):
        result = core_mod._get_market_regime(SAMPLE_STATE)
        assert result["regime"] == "trending_up"

    def test_get_cadence_metrics(self):
        result = core_mod._get_cadence_metrics_enhanced(SAMPLE_STATE)
        assert result["cycle_duration_ms"] == 100

    def test_get_connection_health(self):
        result = core_mod._get_connection_health(SAMPLE_STATE)
        assert result["data_level"] == "FULL"

    def test_get_config(self):
        result = core_mod._get_config(SAMPLE_STATE)
        assert result["mode"] == "live"

    def test_get_data_quality(self):
        result = core_mod._get_data_quality(SAMPLE_STATE)
        assert result["is_stale"] is False

    def test_get_shadow_counters(self):
        result = core_mod._get_shadow_counters(SAMPLE_STATE)
        assert result["would_block_total"] == 5

    def test_get_signal_rejections(self):
        result = core_mod._get_signal_rejections_24h(SAMPLE_STATE)
        assert result["direction_gating"] == 3

    def test_get_last_signal_decision_none(self):
        result = core_mod._get_last_signal_decision({})
        assert result is None

    def test_json_sanitize(self):
        result = core_mod._json_sanitize({"key": 123})
        assert result == {"key": 123}

    def test_snap_to_bar(self):
        assert core_mod._snap_to_bar(450, 300) == 300


# ===========================================================================
# 55. server_core: _require_state_dir
# ===========================================================================


class TestServerCoreRequireStateDir:
    def test_raises_when_none(self):
        with patch.object(core_mod, "_state_dir", None):
            with pytest.raises(HTTPException) as exc_info:
                core_mod._require_state_dir()
            assert exc_info.value.status_code == 500


# ===========================================================================
# 56. server_core: _resolve_state_dir
# ===========================================================================


class TestServerCoreResolveStateDir:
    def test_resolve(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PEARLALGO_STATE_DIR", None)
            result = core_mod._resolve_state_dir("NQ")
            assert "NQ" in str(result)


# ===========================================================================
# 57. server_core TTL cache
# ===========================================================================


class TestServerCoreTtlCache:
    def test_cached_basic(self):
        core_mod._ttl_cache.clear()
        result = core_mod._cached("sc_test_1", 60.0, lambda: 99)
        assert result == 99

    def test_cleanup_ttl_cache(self):
        core_mod._ttl_cache.clear()
        now = time.monotonic()
        core_mod._ttl_cache["sc_expired"] = ("val", now - 10)
        core_mod._cleanup_ttl_cache()
        assert "sc_expired" not in core_mod._ttl_cache


# ===========================================================================
# 58. server_core: _read_state_safe
# ===========================================================================


class TestServerCoreReadStateSafe:
    def test_with_state_dir(self, state_dir):
        with patch.object(core_mod, "_state_dir", state_dir):
            with patch.object(core_mod, "_state_reader", None):
                result = core_mod._read_state_safe()
                assert isinstance(result, dict)

    def test_without_state_dir(self):
        with patch.object(core_mod, "_state_dir", None):
            with patch.object(core_mod, "_state_reader", None):
                result = core_mod._read_state_safe()
                assert result == {}


# ===========================================================================
# 59. server_core: _get_state_reader
# ===========================================================================


class TestServerCoreGetStateReader:
    def test_returns_none_when_no_dir(self):
        with patch.object(core_mod, "_state_dir", None):
            with patch.object(core_mod, "_state_reader", None):
                result = core_mod._get_state_reader()
                assert result is None


# ===========================================================================
# 60. server_core: ConnectionManager
# ===========================================================================


class TestServerCoreConnectionManager:
    def test_init(self):
        mgr = core_mod.ConnectionManager()
        assert mgr.active_connections == []

    @pytest.mark.asyncio
    async def test_broadcast_empty(self):
        mgr = core_mod.ConnectionManager()
        await mgr.broadcast({"type": "test"})  # Should not raise


# ===========================================================================
# 61. server_core: _read_state_for_dir
# ===========================================================================


class TestServerCoreReadStateForDir:
    def test_reads_state(self, state_dir):
        core_mod._state_reader_cache.clear()
        result = core_mod._read_state_for_dir(state_dir)
        assert isinstance(result, dict)

    def test_cached_reader(self, state_dir):
        """Second call should use cached reader."""
        core_mod._state_reader_cache.clear()
        r1 = core_mod._read_state_for_dir(state_dir)
        r2 = core_mod._read_state_for_dir(state_dir)
        assert r1 == r2


# ===========================================================================
# 62. server_core: candle cache
# ===========================================================================


class TestServerCoreCandleCache:
    def test_set_get(self):
        core_mod._candle_cache_set("sc_ck", [{"t": 1}])
        assert core_mod._candle_cache_get("sc_ck") == [{"t": 1}]

    def test_miss(self):
        assert core_mod._candle_cache_get("sc_ck_missing_xyz") is None


# ===========================================================================
# 63. server_core: _aggregate_performance_since
# ===========================================================================


class TestServerCoreAggregatePerformance:
    def test_basic(self):
        trades = [{"exit_time": "2025-06-01T14:00:00Z", "pnl": 10.0}]
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        result = core_mod._aggregate_performance_since(trades, cutoff)
        assert result["pnl"] == 10.0
        assert result["trades"] == 1

    def test_empty(self):
        result = core_mod._aggregate_performance_since([], datetime(2020, 1, 1, tzinfo=timezone.utc))
        assert result["trades"] == 0


# ===========================================================================
# 64. server_core: _get_previous_trading_day_bounds
# ===========================================================================


class TestServerCorePrevTradingDay:
    def test_returns_tuple(self):
        result = core_mod._get_previous_trading_day_bounds()
        start, end = result
        assert end - start == timedelta(days=1)


# ===========================================================================
# 65. server_core: _get_trading_week_start
# ===========================================================================


class TestServerCoreTradingWeekStart:
    def test_returns_naive_et(self):  # FIXED 2026-03-25: returns naive ET after tz migration
        now = datetime(2025, 6, 4, 12, 0, 0, tzinfo=timezone.utc)
        result = core_mod._get_trading_week_start(now)
        assert result.tzinfo is None


# ===========================================================================
# 66. DATA LAYER: _signals_cursor_set
# ===========================================================================


class TestDataLayerSignalsCursor:
    def test_set_and_evict(self):
        data_layer_mod._signals_cursor.clear()
        orig_max = data_layer_mod._SIGNALS_CURSOR_MAX
        try:
            data_layer_mod._SIGNALS_CURSOR_MAX = 2
            data_layer_mod._signals_cursor_set("a", 100)
            data_layer_mod._signals_cursor_set("b", 200)
            data_layer_mod._signals_cursor_set("c", 300)
            assert "a" not in data_layer_mod._signals_cursor
            assert "c" in data_layer_mod._signals_cursor
        finally:
            data_layer_mod._SIGNALS_CURSOR_MAX = orig_max


# ===========================================================================
# 67. DATA LAYER: get_cached_challenge_state
# ===========================================================================


class TestDataLayerCachedChallengeState:
    def test_no_file(self, tmp_path):
        data_layer_mod._ttl_cache.clear()
        result = data_layer_mod.get_cached_challenge_state(tmp_path)
        assert result is None

    def test_with_file(self, tmp_path):
        data_layer_mod._ttl_cache.clear()
        (tmp_path / "challenge_state.json").write_text(json.dumps({
            "tv_paper": {"stage": "evaluation", "trading_days_count": 3}
        }))
        result = data_layer_mod.get_cached_challenge_state(tmp_path)
        assert result is not None
        assert result.stage == "evaluation"


# ===========================================================================
# 68. DATA LAYER: _detect_tv_paper_account
# ===========================================================================


class TestDetectTvPaperAccount:
    def test_from_state(self, state_dir):
        data_layer_mod._state_reader_cache.clear()
        result = data_layer_mod._detect_tv_paper_account(state_dir)
        assert result is True  # SAMPLE_STATE has tradovate_account with equity

    def test_from_fills_file(self, tmp_path):
        d = tmp_path / "no_state"
        d.mkdir()
        (d / "state.json").write_text("{}")
        (d / "tradovate_fills.json").write_text('[{"fill": "data"}]')
        data_layer_mod._state_reader_cache.clear()
        result = data_layer_mod._detect_tv_paper_account(d)
        assert result is True

    def test_no_tv_paper(self, tmp_path):
        d = tmp_path / "no_tv"
        d.mkdir()
        (d / "state.json").write_text('{"running": true}')
        data_layer_mod._state_reader_cache.clear()
        result = data_layer_mod._detect_tv_paper_account(d)
        assert result is False


# ===========================================================================
# 69. DATA LAYER: get_signals_paginated
# ===========================================================================


class TestGetSignalsPaginated:
    def test_paginated_no_file(self, tmp_path):
        result = data_layer_mod.get_signals_paginated(tmp_path)
        assert result["signals"] == []
        assert result["has_more"] is False

    def test_paginated_with_data(self, state_dir):
        result = data_layer_mod.get_signals_paginated(state_dir, limit=10)
        assert isinstance(result["signals"], list)
        assert "cursor" in result


# ===========================================================================
# 70. server.py: _get_challenge_status
# ===========================================================================


class TestGetChallengeStatus:
    def test_no_file(self, tmp_path):
        result = server_mod._get_challenge_status(tmp_path)
        assert result is None

    def test_disabled(self, tmp_path):
        (tmp_path / "challenge_state.json").write_text(json.dumps({
            "config": {"enabled": False},
            "current_attempt": {},
        }))
        result = server_mod._get_challenge_status(tmp_path)
        assert result is None

    def test_active_challenge(self, tmp_path):
        (tmp_path / "challenge_state.json").write_text(json.dumps({
            "config": {"enabled": True, "start_balance": 50000, "profit_target": 3000, "max_drawdown": 2000},
            "current_attempt": {"pnl": 500.0, "trades": 10, "wins": 6, "win_rate": 60.0, "outcome": "active", "max_drawdown_hit": -300},
        }))
        result = server_mod._get_challenge_status(tmp_path)
        assert result is not None
        assert result["enabled"] is True
        assert result["pnl"] == 500.0
        assert result["trades"] == 10


# ===========================================================================
# 71. server.py: _get_recent_exits (non-TV-paper path)
# ===========================================================================


class TestGetRecentExits:
    def test_from_signals(self, state_dir):
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            result = server_mod._get_recent_exits(state_dir, limit=5)
            assert isinstance(result, list)
            for exit_rec in result:
                assert "pnl" in exit_rec
                assert "direction" in exit_rec

    def test_no_signals_file(self, tmp_path):
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            result = server_mod._get_recent_exits(tmp_path, limit=5)
            assert result == []


# ===========================================================================
# 72. server.py: _get_recent_signals
# ===========================================================================


class TestGetRecentSignals:
    def test_from_signals(self, state_dir):
        result = server_mod._get_recent_signals(state_dir, limit=10)
        assert isinstance(result, list)

    def test_no_file(self, tmp_path):
        result = server_mod._get_recent_signals(tmp_path, limit=10)
        assert result == []


# ===========================================================================
# 73. server.py: _save_candle_cache / _load_candle_cache
# ===========================================================================


class TestSaveLoadCandleCache:
    def test_save_and_load(self, tmp_path):
        candles = [{"time": 1, "open": 100, "high": 110, "low": 90, "close": 105, "volume": 50}]
        with patch.object(server_mod, "_get_candle_cache_dir", return_value=tmp_path):
            server_mod._save_candle_cache("save_test", candles)
            # Clear memory cache to force disk read
            server_mod._candle_cache.clear()
            result = server_mod._load_candle_cache("save_test")
            assert result == candles


# ===========================================================================
# 74. server.py: _per_key_cache_path
# ===========================================================================


class TestPerKeyCachePath:
    def test_path_format(self):
        result = server_mod._per_key_cache_path("MNQ_5m_72")
        assert "candle_cache_MNQ_5m_72.json" in str(result)


# ===========================================================================
# 75. server.py: DataUnavailableError
# ===========================================================================


class TestDataUnavailableError:
    def test_is_exception(self):
        err = server_mod.DataUnavailableError("test error")
        assert isinstance(err, Exception)
        assert str(err) == "test error"


# ===========================================================================
# 76. _init_auth
# ===========================================================================


class TestInitAuth:
    def test_init_auth_disabled(self):
        with patch.object(server_mod, "_auth_enabled", False):
            server_mod._init_auth()  # Should not raise

    def test_init_auth_enabled(self, tmp_path):
        with patch.object(server_mod, "_auth_enabled", True):
            with patch.dict(os.environ, {"PEARL_API_KEY": "init-test-key"}):
                server_mod._init_auth()
                assert "init-test-key" in server_mod._api_keys


# ===========================================================================
# 77. _get_data_provider
# ===========================================================================


class TestGetDataProvider:
    def test_returns_none_on_error(self):
        """When provider creation fails, should return None on subsequent calls."""
        with patch.object(server_mod, "_data_provider", None):
            with patch.object(server_mod, "_data_provider_error", "already failed"):
                result = server_mod._get_data_provider()
                assert result is None


# ===========================================================================
# 78. _read_json_sync / _read_json_async
# ===========================================================================


class TestReadJsonSync:
    def test_read_valid(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}')
        result = server_mod._read_json_sync(f)
        assert result == {"key": "value"}

    def test_read_missing(self, tmp_path):
        result = server_mod._read_json_sync(tmp_path / "nonexistent.json")
        assert result is None


class TestReadJsonAsync:
    @pytest.mark.asyncio
    async def test_read_valid(self, tmp_path):
        f = tmp_path / "async_test.json"
        f.write_text('{"async": true}')
        result = await server_mod._read_json_async(f)
        assert result == {"async": True}

    @pytest.mark.asyncio
    async def test_read_missing(self, tmp_path):
        result = await server_mod._read_json_async(tmp_path / "missing.json")
        assert result is None


# ===========================================================================
# 79. _compute_daily_stats fallback path
# ===========================================================================


class TestComputeDailyStats:
    def test_fallback_to_shared(self, state_dir):
        """When no tradovate data, should fall back to shared compute."""
        # Write state without tradovate_account
        (state_dir / "state.json").write_text(json.dumps({"running": True}))
        server_mod._state_reader_cache.clear()
        core_mod._state_reader_cache.clear()
        data_layer_mod._state_reader_cache.clear()
        data_layer_mod._ttl_cache.clear()
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            result = server_mod._compute_daily_stats(state_dir)
            assert "daily_pnl" in result
            assert "daily_trades" in result


# ===========================================================================
# 80. _compute_performance_stats empty path
# ===========================================================================


class TestComputePerformanceStats:
    def test_empty_perf(self, tmp_path):
        """When no data at all, should return empty stats."""
        d = tmp_path / "empty_state"
        d.mkdir()
        (d / "state.json").write_text("{}")
        server_mod._state_reader_cache.clear()
        core_mod._state_reader_cache.clear()
        data_layer_mod._state_reader_cache.clear()
        data_layer_mod._ttl_cache.clear()
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            result = server_mod._compute_performance_stats(d)
            assert "yesterday" in result
            assert "24h" in result
            for period in ("yesterday", "24h", "72h", "30d"):
                assert result[period]["trades"] >= 0


# ===========================================================================
# 81. _get_equity_curve
# ===========================================================================


class TestGetEquityCurve:
    def test_empty_data(self, tmp_path):
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            with patch.object(server_mod, "_load_performance_data", return_value=None):
                server_mod._ttl_cache.clear()
                result = server_mod._get_equity_curve(tmp_path, hours=24)
                assert result == []


# ===========================================================================
# 82. _get_risk_metrics
# ===========================================================================


class TestGetRiskMetrics:
    def test_no_data(self, tmp_path):
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            with patch.object(server_mod, "_load_performance_data", return_value=None):
                server_mod._ttl_cache.clear()
                result = server_mod._get_risk_metrics(tmp_path)
                assert isinstance(result, dict)


# ===========================================================================
# 83. server_core: _compute_daily_stats
# ===========================================================================


class TestServerCoreComputeDailyStats:
    def test_fallback(self, state_dir):
        (state_dir / "state.json").write_text(json.dumps({"running": True}))
        core_mod._state_reader_cache.clear()
        data_layer_mod._state_reader_cache.clear()
        data_layer_mod._ttl_cache.clear()
        with patch.object(core_mod, "_is_tv_paper_account", return_value=False):
            result = core_mod._compute_daily_stats(state_dir)
            assert "daily_pnl" in result


# ===========================================================================
# 84. _get_positions_for_broadcast (IBKR Virtual path)
# ===========================================================================


class TestGetPositionsForBroadcast:
    def test_ibkr_virtual(self, state_dir):
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            data_layer_mod._ttl_cache.clear()
            result = server_mod._get_positions_for_broadcast(state_dir)
            assert isinstance(result, list)

    def test_exception_returns_empty(self, tmp_path):
        with patch.object(server_mod, "_is_tv_paper_account", side_effect=Exception("boom")):
            result = server_mod._get_positions_for_broadcast(tmp_path)
            assert result == []


# ===========================================================================
# 85. _get_trades_for_broadcast (IBKR Virtual path)
# ===========================================================================


class TestGetTradesForBroadcast:
    def test_ibkr_virtual(self, state_dir):
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            data_layer_mod._ttl_cache.clear()
            result = server_mod._get_trades_for_broadcast(state_dir, limit=10)
            assert isinstance(result, list)

    def test_exception_returns_empty(self, tmp_path):
        with patch.object(server_mod, "_is_tv_paper_account", side_effect=Exception("boom")):
            result = server_mod._get_trades_for_broadcast(tmp_path)
            assert result == []


# ===========================================================================
# 86. _get_performance_summary_for_broadcast
# ===========================================================================


class TestGetPerformanceSummaryBroadcast:
    def test_ibkr_virtual_no_data(self, tmp_path):
        d = tmp_path / "bc_state"
        d.mkdir()
        (d / "state.json").write_text("{}")
        server_mod._state_reader_cache.clear()
        core_mod._state_reader_cache.clear()
        data_layer_mod._state_reader_cache.clear()
        data_layer_mod._ttl_cache.clear()
        server_mod._ttl_cache.clear()
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            result = server_mod._get_performance_summary_for_broadcast(d)
            # Either returns data or None (both acceptable)
            if result is not None:
                assert "td" in result


# ===========================================================================
# 87. _get_accounts_config / _init_accounts_config
# ===========================================================================


class TestAccountsConfig:
    def test_get_accounts_config(self):
        server_mod._accounts_config_cached = None
        # _init_accounts_config imports load_service_config internally
        # so we patch the import path in the config_loader module
        with patch("pearlalgo.config.config_loader.load_service_config", side_effect=Exception("no config")):
            result = server_mod._get_accounts_config()
            assert isinstance(result, dict)
            # Should have defaults
            assert "ibkr_virtual" in result or "tv_paper" in result

    def test_init_accounts_sets_defaults(self):
        server_mod._accounts_config_cached = None
        with patch("pearlalgo.config.config_loader.load_service_config", side_effect=Exception("no config")):
            server_mod._init_accounts_config()
            assert server_mod._accounts_config_cached is not None
            assert isinstance(server_mod._accounts_config_cached, dict)


# ===========================================================================
# 88. _cleanup_ttl_cache (server.py)
# ===========================================================================


class TestServerCleanupTtlCache:
    def test_cleanup(self):
        server_mod._ttl_cache.clear()
        now = time.monotonic()
        server_mod._ttl_cache["s_expired"] = ("val", now - 10)
        server_mod._ttl_cache["s_fresh"] = ("val2", now + 100)
        server_mod._cleanup_ttl_cache()
        assert "s_expired" not in server_mod._ttl_cache
        assert "s_fresh" in server_mod._ttl_cache


# ===========================================================================
# 89. DEBUG endpoint: /api/debug/tradovate-orders
# ===========================================================================


class TestDebugTradovateOrders:
    @pytest.mark.usefixtures("_patch_operator")
    def test_non_tv_paper_returns_400(self, client, state_dir):
        """Should return 400 when not a Tradovate Paper account."""
        # Write state without TV paper
        (state_dir / "state.json").write_text(json.dumps({"running": True}))
        server_mod._state_reader_cache.clear()
        core_mod._state_reader_cache.clear()
        data_layer_mod._state_reader_cache.clear()
        data_layer_mod._ttl_cache.clear()
        with patch.object(server_mod, "_is_tv_paper_account", return_value=False):
            resp = client.get(
                "/api/debug/tradovate-orders",
                headers={"X-PEARL-OPERATOR": OPERATOR_PASS},
            )
            assert resp.status_code == 400


# ===========================================================================
# 90. _get_gateway_status_uncached
# ===========================================================================


class TestGatewayStatusUncached:
    def test_returns_dict(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            with patch("socket.socket") as mock_sock:
                mock_sock_inst = MagicMock()
                mock_sock_inst.__enter__ = MagicMock(return_value=mock_sock_inst)
                mock_sock_inst.__exit__ = MagicMock(return_value=False)
                mock_sock_inst.connect_ex.return_value = 1
                mock_sock.return_value = mock_sock_inst
                result = server_mod._get_gateway_status_uncached()
                assert result["status"] == "offline"
                assert result["process_running"] is False
                assert result["port_listening"] is False


# ===========================================================================
# 91. CORS origins in server_core
# ===========================================================================


class TestServerCoreCorsOrigins:
    def test_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PEARL_LIVE_CHART_ORIGINS", None)
            origins = core_mod._cors_origins()
            assert "http://localhost:3001" in origins


# ===========================================================================
# 92. server_core rate limiting
# ===========================================================================


class TestServerCoreRateLimiting:
    def test_allows_under_limit(self):
        core_mod._rate_limit_buckets.clear()
        core_mod._check_rate_limit("sc-test-endpoint")

    def test_blocks_over_limit(self):
        core_mod._rate_limit_buckets.clear()
        for _ in range(core_mod._rate_limit_max):
            core_mod._check_rate_limit("sc-test-endpoint-2")
        with pytest.raises(HTTPException) as exc_info:
            core_mod._check_rate_limit("sc-test-endpoint-2")
        assert exc_info.value.status_code == 429
