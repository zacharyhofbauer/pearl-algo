"""
Tests for the audit API router (src/pearlalgo/api/audit_router.py).

Verifies the FastAPI endpoints mounted at /api/audit/* by injecting a mock
AuditLogger so that no real database or filesystem is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="FastAPI not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pearlalgo.api.audit_router import audit_router, set_audit_logger, _cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_events(n: int, event_type: str = "signal_generated") -> List[Dict[str, Any]]:
    """Generate *n* fake audit events."""
    base = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "id": i + 1,
            "timestamp": (base + timedelta(minutes=i)).isoformat(),
            "event_type": event_type,
            "account": "test_acct",
            "source": "test",
            "data": {"detail": i},
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the module-level TTL cache between tests."""
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture()
def mock_audit_logger():
    """Return a mock AuditLogger and wire it into the router."""
    logger = MagicMock()
    logger.query_events.return_value = _make_events(5)
    logger.count_events.return_value = 5
    logger.query_equity_history.return_value = [
        {"timestamp": "2025-06-01T12:00:00+00:00", "equity": 50100.0}
    ]
    logger.query_reconciliation.return_value = [
        {"account": "test_acct", "drift": 2.5}
    ]
    set_audit_logger(logger)
    yield logger
    set_audit_logger(None)


@pytest.fixture()
def client(mock_audit_logger):
    """TestClient wired to a minimal app that includes the audit router."""
    app = FastAPI()
    app.include_router(audit_router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestListAuditEvents:
    def test_returns_events_with_pagination(self, client, mock_audit_logger):
        resp = client.get("/api/audit/events?page=1&page_size=10")
        assert resp.status_code == 200
        body = resp.json()
        assert "events" in body
        assert "total" in body
        assert body["page"] == 1
        assert len(body["events"]) == 5

    def test_filter_by_event_type(self, client, mock_audit_logger):
        # Wire up specific return for filtered call
        mock_audit_logger.query_events.return_value = _make_events(2, "signal_rejected")
        mock_audit_logger.count_events.return_value = 2

        resp = client.get("/api/audit/events?event_type=signal_rejected")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert all(e["event_type"] == "signal_rejected" for e in body["events"])

    def test_filter_by_date_range(self, client, mock_audit_logger):
        """Providing start_date and end_date should still return a valid response."""
        mock_audit_logger.query_events.return_value = []
        mock_audit_logger.count_events.return_value = 0

        resp = client.get(
            "/api/audit/events?start_date=2025-01-01T00:00:00Z&end_date=2025-01-02T00:00:00Z"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["events"] == []
        assert body["total"] == 0

    def test_no_audit_logger_returns_empty(self, client):
        """If audit logger is not set, endpoints should still return 200 with empty data."""
        set_audit_logger(None)
        resp = client.get("/api/audit/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["events"] == []
        assert body["total"] == 0


class TestEquityHistory:
    def test_returns_snapshots(self, client, mock_audit_logger):
        resp = client.get("/api/audit/equity-history")
        assert resp.status_code == 200
        body = resp.json()
        assert "snapshots" in body
        assert len(body["snapshots"]) >= 1
        assert "equity" in body["snapshots"][0]


class TestReconciliation:
    def test_returns_reconciliation_results(self, client, mock_audit_logger):
        resp = client.get("/api/audit/reconciliation")
        assert resp.status_code == 200
        body = resp.json()
        assert "reconciliations" in body
        assert len(body["reconciliations"]) >= 1
        assert "drift" in body["reconciliations"][0]
