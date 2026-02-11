"""Tests for AuditLogger -- persistent audit event logging."""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from pearlalgo.market_agent.audit_logger import AuditLogger, AuditEventType


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "test_audit.db"


@pytest.fixture
def logger_started(tmp_db):
    """Create and start an AuditLogger."""
    al = AuditLogger(db_path=tmp_db, account="test_account")
    al.start()
    yield al
    al.stop(timeout=3.0)


class TestAuditLoggerSchema:
    """Test audit_events table creation and schema."""

    def test_table_exists(self, tmp_db):
        """audit_events table should be created on init."""
        AuditLogger(db_path=tmp_db, account="test")
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_indexes_exist(self, tmp_db):
        """Composite indexes should be created."""
        AuditLogger(db_path=tmp_db, account="test")
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_audit%'"
        )
        indexes = [row[0] for row in cursor.fetchall()]
        assert "idx_audit_ts_account_type" in indexes
        assert "idx_audit_type_ts" in indexes
        conn.close()

    def test_columns(self, tmp_db):
        """Table should have expected columns."""
        AuditLogger(db_path=tmp_db, account="test")
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.execute("PRAGMA table_info(audit_events)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {"id", "timestamp", "event_type", "account", "data_json", "source"}
        conn.close()


class TestAuditLoggerSignalEvents:
    """Test signal-related audit events."""

    def test_log_signal_generated(self, logger_started):
        """Signal generated events should be persisted."""
        logger_started.log_signal_generated({
            "signal_id": "sig_001",
            "direction": "long",
            "symbol": "MNQ",
            "entry_price": 18500.0,
            "stop_loss": 18480.0,
            "take_profit": 18540.0,
            "confidence": 0.75,
            "trade_type": "scalp",
        })
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.SIGNAL_GENERATED)
        assert len(events) >= 1
        data = events[0].get("data", {})
        assert data["signal_id"] == "sig_001"
        assert data["direction"] == "long"
        assert data["entry_price"] == 18500.0

    def test_log_signal_rejected(self, logger_started):
        """Signal rejected events should include reason and details."""
        logger_started.log_signal_rejected(
            "sig_002", "circuit_breaker:consecutive_losses",
            {"consecutive_losses": 3, "max_allowed": 3},
        )
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.SIGNAL_REJECTED)
        assert len(events) >= 1
        data = events[0].get("data", {})
        assert data["reason"] == "circuit_breaker:consecutive_losses"
        assert data["details"]["consecutive_losses"] == 3


class TestAuditLoggerTradeEvents:
    """Test trade-related audit events."""

    def test_log_trade_entered(self, logger_started):
        """Trade entry events should be persisted."""
        logger_started.log_trade_entered("sig_003", {
            "entry_price": 18500.0,
            "direction": "short",
            "position_size": 2,
            "execution_status": "placed",
        })
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.TRADE_ENTERED)
        assert len(events) >= 1
        assert events[0]["data"]["direction"] == "short"

    def test_log_trade_exited(self, logger_started):
        """Trade exit events should include P&L."""
        logger_started.log_trade_exited("sig_003", {
            "exit_price": 18480.0,
            "exit_reason": "take_profit",
            "pnl": 40.0,
            "is_win": True,
            "hold_duration_minutes": 12.5,
            "direction": "short",
        })
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.TRADE_EXITED)
        assert len(events) >= 1
        assert events[0]["data"]["pnl"] == 40.0
        assert events[0]["data"]["is_win"] is True


class TestAuditLoggerSystemEvents:
    """Test system-related audit events."""

    def test_log_system_start(self, logger_started):
        logger_started.log_system_event(AuditEventType.SYSTEM_START, {"symbol": "MNQ"})
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.SYSTEM_START)
        assert len(events) >= 1

    def test_log_system_stop(self, logger_started):
        logger_started.log_system_event(AuditEventType.SYSTEM_STOP, {"reason": "shutdown"})
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.SYSTEM_STOP)
        assert len(events) >= 1
        assert events[0]["data"]["reason"] == "shutdown"

    def test_log_connection_drop(self, logger_started):
        logger_started.log_system_event(
            AuditEventType.CONNECTION_DROP,
            {"connection_failures": 5, "cycle": 100},
        )
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.CONNECTION_DROP)
        assert len(events) >= 1

    def test_log_equity_snapshot(self, logger_started):
        logger_started.log_equity_snapshot(
            account="tradovate_paper", equity=50250.0,
            cash_balance=50000.0, open_pnl=250.0, realized_pnl=150.0,
        )
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.EQUITY_SNAPSHOT)
        assert len(events) >= 1
        assert events[0]["data"]["equity"] == 50250.0

    def test_log_reconciliation(self, logger_started):
        logger_started.log_reconciliation(
            account="tradovate_paper", agent_pnl=500.0,
            broker_pnl=495.0, drift=5.0, details={"threshold": 10.0},
        )
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.RECONCILIATION)
        assert len(events) >= 1
        assert events[0]["data"]["drift"] == 5.0


class TestAuditLoggerEdgeCases:
    """Test edge cases and error handling."""

    def test_null_signal_id(self, logger_started):
        logger_started.log_signal_generated({"signal_id": None})
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.SIGNAL_GENERATED)
        assert len(events) >= 1

    def test_empty_details(self, logger_started):
        logger_started.log_signal_rejected("sig_005", "test_reason", {})
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.SIGNAL_REJECTED)
        assert len(events) >= 1

    def test_none_details(self, logger_started):
        logger_started.log_signal_rejected("sig_006", "test_reason", None)
        logger_started.flush()
        events = logger_started.query_events(event_type=AuditEventType.SIGNAL_REJECTED)
        assert len(events) >= 1

    def test_not_started_drops_events(self, tmp_db):
        al = AuditLogger(db_path=tmp_db, account="test")
        al.log_signal_generated({"signal_id": "dropped"})
        assert al._total_drops >= 1

    def test_account_field_populated(self, logger_started):
        logger_started.log_system_event("test_event", {})
        logger_started.flush()
        events = logger_started.query_events()
        assert len(events) >= 1
        assert events[0]["account"] == "test_account"


class TestAuditLoggerQuery:
    """Test query functionality."""

    def test_query_with_account_filter(self, logger_started):
        logger_started.log_system_event("test", {"data": 1})
        logger_started.flush()
        events = logger_started.query_events(account="test_account")
        assert len(events) >= 1
        events_other = logger_started.query_events(account="other_account")
        assert len(events_other) == 0

    def test_query_pagination(self, logger_started):
        for i in range(10):
            logger_started.log_system_event("paginate_test", {"i": i})
        logger_started.flush()

        page1 = logger_started.query_events(event_type="paginate_test", limit=3, offset=0)
        page2 = logger_started.query_events(event_type="paginate_test", limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        ids_p1 = {e["id"] for e in page1}
        ids_p2 = {e["id"] for e in page2}
        assert ids_p1.isdisjoint(ids_p2)

    def test_count_events(self, logger_started):
        for i in range(5):
            logger_started.log_system_event("count_test", {"i": i})
        logger_started.flush()
        count = logger_started.count_events(event_type="count_test")
        assert count >= 5


class TestAuditLoggerRetention:
    """Test retention policy."""

    def test_retention_deletes_old_events(self, tmp_db):
        al = AuditLogger(db_path=tmp_db, account="test", retention_days=0)
        al.start()
        al.log_system_event("old_event", {})
        al.flush()
        result = al.run_retention()
        assert result["deleted_general"] >= 1
        al.stop(timeout=2.0)


class TestAuditLoggerMetrics:
    """Test observability metrics."""

    def test_metrics_structure(self, logger_started):
        metrics = logger_started.get_metrics()
        assert "queue_depth" in metrics
        assert "total_writes" in metrics
        assert "total_drops" in metrics
        assert "total_errors" in metrics
        assert "worker_running" in metrics
        assert metrics["worker_running"] is True


class TestAuditLoggerRapidWrites:
    """Test high-throughput write scenarios."""

    def test_rapid_writes_persisted(self, logger_started):
        for i in range(100):
            logger_started.log_system_event("rapid_test", {"i": i})
        logger_started.flush()
        count = logger_started.count_events(event_type="rapid_test")
        assert count == 100, f"Expected 100 events, got {count}"
