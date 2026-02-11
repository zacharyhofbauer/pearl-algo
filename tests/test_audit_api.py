"""Tests for audit API endpoints."""

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pearlalgo.market_agent.audit_logger import AuditLogger, AuditEventType


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_api_audit.db"


@pytest.fixture
def populated_logger(tmp_db):
    """Create an AuditLogger with test events pre-populated."""
    al = AuditLogger(db_path=tmp_db, account="test_account")
    al.start()

    # Insert test events directly for deterministic testing
    now = datetime.now(timezone.utc)
    for i in range(10):
        ts = (now - timedelta(hours=i)).isoformat()
        al.log_signal_generated({
            "signal_id": f"sig_{i:03d}",
            "direction": "long" if i % 2 == 0 else "short",
            "entry_price": 18500.0 + i,
        })
    for i in range(5):
        ts = (now - timedelta(hours=i)).isoformat()
        al.log_signal_rejected(f"rej_{i:03d}", f"reason_{i}", {"detail": i})

    for i in range(3):
        al.log_equity_snapshot(
            account="test_account",
            equity=50000.0 + i * 100,
            cash_balance=50000.0,
            open_pnl=i * 50.0,
            realized_pnl=i * 50.0,
        )

    al.log_reconciliation(
        account="test_account",
        agent_pnl=500.0,
        broker_pnl=495.0,
        drift=5.0,
    )

    time.sleep(3)  # Wait for background writes
    yield al
    al.stop(timeout=3.0)


class TestAuditEventsPagination:
    """Test /api/audit/events pagination logic."""

    def test_first_page(self, populated_logger):
        events = populated_logger.query_events(limit=5, offset=0)
        assert len(events) <= 5

    def test_second_page(self, populated_logger):
        page1 = populated_logger.query_events(limit=5, offset=0)
        page2 = populated_logger.query_events(limit=5, offset=5)
        ids_1 = {e["id"] for e in page1}
        ids_2 = {e["id"] for e in page2}
        assert ids_1.isdisjoint(ids_2)

    def test_past_end_returns_empty(self, populated_logger):
        events = populated_logger.query_events(limit=5, offset=10000)
        assert events == []


class TestAuditEventsFiltering:
    """Test event filtering."""

    def test_filter_by_event_type(self, populated_logger):
        generated = populated_logger.query_events(event_type=AuditEventType.SIGNAL_GENERATED)
        rejected = populated_logger.query_events(event_type=AuditEventType.SIGNAL_REJECTED)
        assert len(generated) >= 10
        assert len(rejected) >= 5

    def test_filter_by_account(self, populated_logger):
        events = populated_logger.query_events(account="test_account")
        assert len(events) > 0
        events_other = populated_logger.query_events(account="nonexistent")
        assert len(events_other) == 0


class TestAuditEquityHistory:
    """Test equity history queries."""

    def test_equity_snapshots_returned(self, populated_logger):
        snapshots = populated_logger.query_equity_history()
        assert len(snapshots) >= 3

    def test_equity_data_fields(self, populated_logger):
        snapshots = populated_logger.query_equity_history()
        if snapshots:
            data = snapshots[0].get("data", {})
            assert "equity" in data
            assert "cash_balance" in data


class TestAuditReconciliation:
    """Test reconciliation queries."""

    def test_reconciliation_returned(self, populated_logger):
        results = populated_logger.query_reconciliation()
        assert len(results) >= 1

    def test_reconciliation_data_fields(self, populated_logger):
        results = populated_logger.query_reconciliation()
        if results:
            data = results[0].get("data", {})
            assert "agent_pnl" in data
            assert "broker_pnl" in data
            assert "drift" in data


class TestAuditEventCount:
    """Test count functionality."""

    def test_total_count(self, populated_logger):
        total = populated_logger.count_events()
        assert total > 0

    def test_filtered_count(self, populated_logger):
        gen_count = populated_logger.count_events(event_type=AuditEventType.SIGNAL_GENERATED)
        rej_count = populated_logger.count_events(event_type=AuditEventType.SIGNAL_REJECTED)
        assert gen_count >= 10
        assert rej_count >= 5


class TestAuditIndexUsage:
    """Test that queries use indexes (not full table scans)."""

    def test_composite_index_exists(self, tmp_db, populated_logger):
        conn = sqlite3.connect(str(tmp_db))
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM audit_events "
            "WHERE timestamp > '2020-01-01' AND account = 'test' AND event_type = 'test'"
        ).fetchall()
        conn.close()
        plan_text = str(plan)
        # Should use the composite index, not a full scan
        assert "idx_audit" in plan_text.lower() or "SEARCH" in plan_text
