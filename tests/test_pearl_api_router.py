"""
Tests for Pearl AI API router configuration and endpoint handlers.

Covers:
- Route registration (uniqueness, correct methods)
- Each endpoint handler with mocked brain
- Error handling (brain failures -> 500)
- Authentication enforcement (401 / 403 / 200)
"""

import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pearlalgo.pearl_ai.api_router import create_pearl_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_brain():
    """Return a MagicMock that satisfies PearlBrain's public interface."""
    brain = MagicMock()

    # Async endpoints
    brain.chat = AsyncMock(return_value="Hello from Pearl")
    brain.generate_insight = AsyncMock(return_value=None)
    brain.daily_review = AsyncMock(return_value=None)

    # Sync helpers used by route handlers
    brain._classify_query.return_value = MagicMock(value="quick")
    brain.get_last_response_source.return_value = "local"
    brain.get_trading_context_summary.return_value = {"daily_pnl": 0.0}
    brain.explain_rejections.return_value = "No rejections today"
    brain._current_state = {}

    brain.get_metrics_summary.return_value = {
        "period_hours": 24,
        "total_requests": 10,
        "total_tokens": 500,
        "total_cost_usd": 0.05,
        "avg_latency_ms": 200.0,
        "p50_latency_ms": 180.0,
        "p95_latency_ms": 400.0,
        "p99_latency_ms": 500.0,
        "cache_hit_rate": 0.3,
        "error_rate": 0.01,
        "fallback_rate": 0.05,
        "by_endpoint": {},
        "by_model": {},
    }
    brain.get_cost_summary.return_value = {
        "today_usd": 0.12,
        "month_usd": 2.50,
        "limit_usd": 10.0,
    }
    brain.get_ml_lift_metrics.return_value = {"lift_pct": 5.0}
    brain.record_suggestion_feedback.return_value = {"recorded": True}

    # Metrics sub-object
    brain.metrics = MagicMock()
    brain.metrics.get_recent_requests.return_value = []
    brain.metrics.get_error_summary.return_value = {}
    brain.metrics.get_response_source_distribution.return_value = {}
    brain.metrics.get_feedback_stats.return_value = {}
    brain.metrics.get_recent_feedback.return_value = []

    # Memory sub-object
    brain.memory = MagicMock()
    brain.memory.pearl_messages = []
    brain.memory.conversation_history = []
    brain.memory.user_patterns = []
    brain.memory.session_id = "test-session-id"
    brain.memory.get_recent_messages.return_value = []

    # LLM backends
    brain.local_llm = None
    brain.claude_llm = None
    brain.enable_tools = False
    brain.cache = None
    brain.data_access = MagicMock()
    brain.data_access.is_available.return_value = False

    return brain


_CLEAN_ENV = {
    "PEARL_API_AUTH_ENABLED": "false",
    "PEARL_API_KEY": "",
    "PEARL_API_KEY_FILE": "",
}


def _make_router(brain):
    """Create the Pearl router with auth disabled."""
    with patch.dict(os.environ, _CLEAN_ENV, clear=False):
        return create_pearl_router(brain)


def _build_app(brain, *, auth_enabled="false", api_key=None):
    """Create a FastAPI app with the Pearl router mounted at /api/pearl."""
    env = {
        "PEARL_API_AUTH_ENABLED": auth_enabled,
        "PEARL_API_KEY": api_key or "",
        "PEARL_API_KEY_FILE": "",
    }
    with patch.dict(os.environ, env, clear=False):
        app = FastAPI()
        app.include_router(create_pearl_router(brain), prefix="/api/pearl")
    return app


# ==========================================================================
# 1-3  Route registration
# ==========================================================================


def test_metrics_sources_route_unique():
    """Ensure /metrics/sources is defined exactly once."""
    router = _make_router(_make_mock_brain())
    matching = [
        r
        for r in router.routes
        if getattr(r, "path", None) == "/metrics/sources"
        and "GET" in getattr(r, "methods", set())
    ]
    assert len(matching) == 1


def test_all_routes_are_unique():
    """No two routes share the same (path, method) combination."""
    router = _make_router(_make_mock_brain())
    seen = set()
    for route in router.routes:
        path = getattr(route, "path", None)
        for method in getattr(route, "methods", []):
            key = (path, method)
            assert key not in seen, f"Duplicate route: {method} {path}"
            seen.add(key)


def test_expected_routes_registered():
    """All expected endpoints are present with correct HTTP methods."""
    router = _make_router(_make_mock_brain())

    pairs = set()
    for route in router.routes:
        path = getattr(route, "path", None)
        if path:
            for m in getattr(route, "methods", []):
                pairs.add((m, path))

    expected = [
        ("POST", "/chat"),
        ("POST", "/chat/stream"),
        ("GET", "/feed"),
        ("POST", "/insight"),
        ("POST", "/daily-review"),
        ("GET", "/status"),
        ("GET", "/conversation"),
        ("DELETE", "/conversation"),
        ("GET", "/context"),
        ("GET", "/rejections"),
        ("GET", "/metrics"),
        ("GET", "/metrics/cost"),
        ("GET", "/metrics/recent"),
        ("GET", "/metrics/errors"),
        ("GET", "/metrics/sources"),
        ("POST", "/cache/clear"),
        ("GET", "/cache/stats"),
        ("GET", "/ml-status"),
        ("POST", "/feedback"),
        ("GET", "/feedback/stats"),
        ("GET", "/feedback/recent"),
    ]
    for method, path in expected:
        assert (method, path) in pairs, f"Missing route: {method} {path}"


# ==========================================================================
# 4-14  Endpoint handler tests (auth disabled)
# ==========================================================================


def test_chat_endpoint_success():
    """POST /chat returns ChatResponse with expected fields."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.post("/api/pearl/chat", json={"message": "How am I doing?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "Hello from Pearl"
    assert body["complexity"] == "quick"
    assert body["source"] == "local"
    assert "timestamp" in body


def test_chat_endpoint_error_returns_500():
    """POST /chat returns 500 when brain.chat raises an exception."""
    brain = _make_mock_brain()
    brain.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
    client = TestClient(_build_app(brain))

    resp = client.post("/api/pearl/chat", json={"message": "fail"})
    assert resp.status_code == 500
    assert "LLM down" in resp.json()["detail"]


def test_feed_endpoint_returns_messages():
    """GET /feed returns formatted FeedMessage list from memory."""
    brain = _make_mock_brain()
    msg = MagicMock()
    msg.content = "Market update"
    msg.message_type = "narration"
    msg.priority = "normal"
    msg.timestamp = datetime(2025, 1, 15, 10, 0)
    msg.related_trade_id = None
    msg.metadata = {}
    brain.memory.pearl_messages = [msg]
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/feed")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["content"] == "Market update"
    assert data[0]["type"] == "narration"


def test_feed_endpoint_respects_limit():
    """GET /feed?limit=1 returns at most 1 message."""
    brain = _make_mock_brain()
    messages = []
    for i in range(5):
        m = MagicMock()
        m.content = f"msg-{i}"
        m.message_type = "narration"
        m.priority = "normal"
        m.timestamp = datetime(2025, 1, 15, 10, i)
        m.related_trade_id = None
        m.metadata = {}
        messages.append(m)
    brain.memory.pearl_messages = messages
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/feed?limit=1")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_insight_endpoint_generated():
    """POST /insight returns the generated insight when available."""
    brain = _make_mock_brain()
    insight = MagicMock()
    insight.content = "You are cutting winners short"
    insight.timestamp = datetime(2025, 1, 15, 12, 0)
    brain.generate_insight = AsyncMock(return_value=insight)
    client = TestClient(_build_app(brain))

    resp = client.post("/api/pearl/insight")
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated"] is True
    assert body["content"] == "You are cutting winners short"


def test_insight_endpoint_no_data():
    """POST /insight returns generated=False when no insight is available."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.post("/api/pearl/insight")
    assert resp.status_code == 200
    assert resp.json()["generated"] is False
    assert "reason" in resp.json()


def test_daily_review_success():
    """POST /daily-review returns the review content on success."""
    brain = _make_mock_brain()
    review = MagicMock()
    review.content = "Strong session today."
    review.timestamp = datetime(2025, 1, 15, 17, 0)
    brain.daily_review = AsyncMock(return_value=review)
    client = TestClient(_build_app(brain))

    resp = client.post("/api/pearl/daily-review")
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated"] is True
    assert body["content"] == "Strong session today."


def test_daily_review_unavailable():
    """POST /daily-review returns generated=False when Claude is unavailable."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.post("/api/pearl/daily-review")
    assert resp.status_code == 200
    assert resp.json()["generated"] is False


def test_status_endpoint():
    """GET /status returns system status with version and LLM info."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "3.0.0"
    assert body["local_llm"]["enabled"] is False
    assert body["claude"]["enabled"] is False
    assert body["memory"]["session_id"] == "test-session-id"


def test_conversation_get_and_clear():
    """GET /conversation returns history; DELETE clears it."""
    brain = _make_mock_brain()
    brain.memory.get_recent_messages.return_value = [
        {"role": "user", "content": "hi"},
    ]
    client = TestClient(_build_app(brain))

    # GET
    resp = client.get("/api/pearl/conversation")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "test-session-id"
    assert len(resp.json()["messages"]) == 1

    # DELETE
    resp = client.delete("/api/pearl/conversation")
    assert resp.status_code == 200
    assert resp.json()["cleared"] is True
    brain.memory.clear_session.assert_called_once()


def test_context_endpoint():
    """GET /context returns the trading context summary."""
    brain = _make_mock_brain()
    brain.get_trading_context_summary.return_value = {
        "daily_pnl": 150.0,
        "win_rate": 0.65,
    }
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/context")
    assert resp.status_code == 200
    assert resp.json()["daily_pnl"] == 150.0


# ==========================================================================
# 15-17  Authentication enforcement
# ==========================================================================


def test_auth_missing_key_returns_401():
    """Request without X-API-Key header gets 401 when auth is enabled."""
    brain = _make_mock_brain()
    client = TestClient(
        _build_app(brain, auth_enabled="true", api_key="secret")
    )

    resp = client.post("/api/pearl/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_auth_invalid_key_returns_403():
    """Request with wrong X-API-Key header gets 403."""
    brain = _make_mock_brain()
    client = TestClient(
        _build_app(brain, auth_enabled="true", api_key="correct-key")
    )

    resp = client.post(
        "/api/pearl/chat",
        json={"message": "hi"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 403


def test_auth_valid_key_allows_access():
    """Request with correct X-API-Key succeeds when auth is enabled."""
    brain = _make_mock_brain()
    client = TestClient(
        _build_app(brain, auth_enabled="true", api_key="my-key")
    )

    resp = client.post(
        "/api/pearl/chat",
        json={"message": "hi"},
        headers={"X-API-Key": "my-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["response"] == "Hello from Pearl"


# ==========================================================================
# 18+  Additional endpoint handler tests
# ==========================================================================


def test_rejections_endpoint():
    """GET /rejections returns the rejection explanation."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/rejections")
    assert resp.status_code == 200
    assert resp.json()["explanation"] == "No rejections today"


def test_metrics_endpoint():
    """GET /metrics returns MetricsSummary with all expected fields."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["period_hours"] == 24
    assert body["total_requests"] == 10
    assert body["total_tokens"] == 500
    assert body["total_cost_usd"] == 0.05
    assert body["cache_hit_rate"] == 0.3
    assert body["error_rate"] == 0.01


def test_metrics_endpoint_custom_hours():
    """GET /metrics?hours=48 passes the hours parameter to the brain."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/metrics?hours=48")
    assert resp.status_code == 200
    brain.get_metrics_summary.assert_called_once_with(48)


def test_metrics_cost_endpoint():
    """GET /metrics/cost returns CostSummary with today/month/limit."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/metrics/cost")
    assert resp.status_code == 200
    body = resp.json()
    assert body["today_usd"] == 0.12
    assert body["month_usd"] == 2.50
    assert body["limit_usd"] == 10.0


def test_metrics_recent_endpoint():
    """GET /metrics/recent returns recent request list."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/metrics/recent")
    assert resp.status_code == 200
    assert resp.json() == []


def test_metrics_recent_custom_limit():
    """GET /metrics/recent?limit=5 passes the limit parameter."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/metrics/recent?limit=5")
    assert resp.status_code == 200
    brain.metrics.get_recent_requests.assert_called_once_with(5)


def test_metrics_errors_endpoint():
    """GET /metrics/errors returns error summary dict."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/metrics/errors")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_metrics_sources_endpoint():
    """GET /metrics/sources returns response source distribution."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/metrics/sources")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_cache_clear_with_cache():
    """POST /cache/clear with cache enabled removes entries and reports count."""
    brain = _make_mock_brain()
    brain.cache = MagicMock()
    brain.cache.invalidate.return_value = 5
    client = TestClient(_build_app(brain))

    resp = client.post("/api/pearl/cache/clear")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cleared"] is True
    assert body["entries_removed"] == 5


def test_cache_clear_no_cache():
    """POST /cache/clear with no cache configured returns cleared=False."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.post("/api/pearl/cache/clear")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cleared"] is False
    assert "reason" in body


def test_cache_stats_with_cache():
    """GET /cache/stats returns stats and entries when cache is enabled."""
    brain = _make_mock_brain()
    brain.cache = MagicMock()
    brain.cache.get_stats.return_value = {"hits": 10, "misses": 5}
    brain.cache.get_entries.return_value = []
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/cache/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["stats"]["hits"] == 10
    assert body["entries"] == []


def test_cache_stats_no_cache():
    """GET /cache/stats returns enabled=False when no cache configured."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/cache/stats")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_ml_status_endpoint():
    """GET /ml-status returns ML filter lift metrics."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/ml-status")
    assert resp.status_code == 200
    assert resp.json()["lift_pct"] == 5.0


def test_feedback_endpoint_accept():
    """POST /feedback records accepted suggestion feedback."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.post(
        "/api/pearl/feedback",
        json={"suggestion_id": "sug-1", "action": "accept"},
    )
    assert resp.status_code == 200
    assert resp.json()["recorded"] is True
    brain.record_suggestion_feedback.assert_called_once_with(
        suggestion_id="sug-1",
        action="accept",
        dismiss_reason=None,
        dismiss_comment=None,
    )


def test_feedback_endpoint_dismiss_with_reason():
    """POST /feedback records dismissed feedback with reason and comment."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.post(
        "/api/pearl/feedback",
        json={
            "suggestion_id": "sug-2",
            "action": "dismiss",
            "dismiss_reason": "not_relevant",
            "dismiss_comment": "Already handled",
        },
    )
    assert resp.status_code == 200
    brain.record_suggestion_feedback.assert_called_once_with(
        suggestion_id="sug-2",
        action="dismiss",
        dismiss_reason="not_relevant",
        dismiss_comment="Already handled",
    )


def test_feedback_stats_endpoint():
    """GET /feedback/stats returns feedback statistics."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/feedback/stats")
    assert resp.status_code == 200
    brain.metrics.get_feedback_stats.assert_called_once()


def test_feedback_recent_endpoint():
    """GET /feedback/recent?limit=5 passes limit and returns entries."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.get("/api/pearl/feedback/recent?limit=5")
    assert resp.status_code == 200
    brain.metrics.get_recent_feedback.assert_called_once_with(5)


def test_stream_endpoint_no_claude_fallback():
    """POST /chat/stream without Claude LLM falls back to non-streaming."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    resp = client.post(
        "/api/pearl/chat/stream",
        json={"message": "hello"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


def test_auth_enforced_across_all_endpoint_types():
    """Auth is enforced on GET, POST, and DELETE endpoints uniformly."""
    brain = _make_mock_brain()
    client = TestClient(
        _build_app(brain, auth_enabled="true", api_key="secret")
    )

    # GET endpoints all require auth
    assert client.get("/api/pearl/status").status_code == 401
    assert client.get("/api/pearl/feed").status_code == 401
    assert client.get("/api/pearl/metrics").status_code == 401
    assert client.get("/api/pearl/ml-status").status_code == 401
    assert client.get("/api/pearl/context").status_code == 401
    assert client.get("/api/pearl/rejections").status_code == 401

    # POST endpoints
    assert client.post("/api/pearl/insight").status_code == 401
    assert client.post("/api/pearl/cache/clear").status_code == 401

    # DELETE endpoints
    assert client.delete("/api/pearl/conversation").status_code == 401


def test_chat_endpoint_brain_called_with_message():
    """POST /chat passes the user message to brain.chat."""
    brain = _make_mock_brain()
    client = TestClient(_build_app(brain))

    client.post("/api/pearl/chat", json={"message": "What is my PnL?"})
    brain.chat.assert_awaited_once_with("What is my PnL?")
