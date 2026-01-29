"""
Tests for Trade Database

Tests the SQLite-based trade history storage system including:
- TradeRecord dataclass operations
- Database initialization and schema creation
- Trade CRUD operations with filtering
- Performance analytics by signal type, regime, and hour
- Signal events tracking
- Cycle diagnostics aggregation
- Challenge attempt records
- Regime history snapshots
"""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from pearlalgo.learning.trade_database import TradeDatabase, TradeRecord


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database path for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_trades.db"


@pytest.fixture
def db(temp_db_path):
    """Create a test database instance."""
    database = TradeDatabase(db_path=temp_db_path)
    yield database
    database.close()


@pytest.fixture
def cached_db(temp_db_path):
    """Create a test database with connection caching enabled."""
    database = TradeDatabase(db_path=temp_db_path, cache_connection=True)
    yield database
    database.close()


@pytest.fixture
def sample_trade_data():
    """Sample trade data for testing."""
    return {
        "trade_id": "trade_001",
        "signal_id": "sig_001",
        "signal_type": "ema_crossover",
        "direction": "long",
        "entry_price": 100.0,
        "exit_price": 105.0,
        "pnl": 50.0,
        "is_win": True,
        "entry_time": "2024-01-15T10:00:00Z",
        "exit_time": "2024-01-15T11:30:00Z",
        "stop_loss": 98.0,
        "take_profit": 106.0,
        "exit_reason": "take_profit",
        "hold_duration_minutes": 90.0,
        "regime": "trending_up",
        "context_key": "trending_up_high_vol",
        "volatility_percentile": 75.0,
        "volume_percentile": 60.0,
        "features": {"rsi": 55.0, "ema_slope": 0.05, "volume_ratio": 1.2},
    }


# =============================================================================
# TradeRecord Tests
# =============================================================================


class TestTradeRecord:
    """Tests for TradeRecord dataclass."""

    def test_to_dict_basic(self):
        """Test basic conversion to dictionary."""
        record = TradeRecord(
            trade_id="t001",
            signal_id="s001",
            signal_type="ema_crossover",
            direction="long",
            entry_price=100.0,
            exit_price=105.0,
            stop_loss=98.0,
            take_profit=110.0,
            pnl=50.0,
            is_win=True,
            exit_reason="take_profit",
            entry_time="2024-01-15T10:00:00Z",
            exit_time="2024-01-15T11:00:00Z",
            hold_duration_minutes=60.0,
            regime="trending_up",
            context_key="ctx_001",
            volatility_percentile=70.0,
            volume_percentile=65.0,
            features_json='{"rsi": 55}',
            created_at="2024-01-15T11:05:00Z",
        )

        result = record.to_dict()

        assert result["trade_id"] == "t001"
        assert result["signal_type"] == "ema_crossover"
        assert result["direction"] == "long"
        assert result["pnl"] == 50.0
        assert result["is_win"] is True
        assert result["features"] == {"rsi": 55}

    def test_to_dict_with_empty_features(self):
        """Test to_dict with empty features JSON."""
        record = TradeRecord(
            trade_id="t002",
            signal_id="s002",
            signal_type="vwap_bounce",
            direction="short",
            entry_price=200.0,
            exit_price=195.0,
            stop_loss=205.0,
            take_profit=190.0,
            pnl=25.0,
            is_win=True,
            exit_reason="take_profit",
            entry_time="2024-01-15T12:00:00Z",
            exit_time="2024-01-15T13:00:00Z",
            hold_duration_minutes=60.0,
            regime="trending_down",
            context_key="ctx_002",
            volatility_percentile=50.0,
            volume_percentile=40.0,
            features_json="",
            created_at="2024-01-15T13:05:00Z",
        )

        result = record.to_dict()
        assert result["features"] == {}

    def test_to_dict_with_null_features(self):
        """Test to_dict with null features JSON."""
        record = TradeRecord(
            trade_id="t003",
            signal_id="s003",
            signal_type="breakout",
            direction="long",
            entry_price=150.0,
            exit_price=145.0,
            stop_loss=148.0,
            take_profit=160.0,
            pnl=-25.0,
            is_win=False,
            exit_reason="stop_loss",
            entry_time="2024-01-15T14:00:00Z",
            exit_time="2024-01-15T14:30:00Z",
            hold_duration_minutes=30.0,
            regime="ranging",
            context_key="ctx_003",
            volatility_percentile=30.0,
            volume_percentile=20.0,
            features_json=None,
            created_at="2024-01-15T14:35:00Z",
        )

        result = record.to_dict()
        assert result["features"] == {}


# =============================================================================
# Database Initialization Tests
# =============================================================================


class TestDatabaseInitialization:
    """Tests for database initialization."""

    def test_creates_database_file(self, temp_db_path):
        """Test that database file is created."""
        db = TradeDatabase(db_path=temp_db_path)
        assert temp_db_path.exists()
        db.close()

    def test_creates_parent_directories(self):
        """Test that parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = Path(tmpdir) / "nested" / "dir" / "trades.db"
            db = TradeDatabase(db_path=nested_path)
            assert nested_path.parent.exists()
            db.close()

    def test_schema_creates_tables(self, db, temp_db_path):
        """Test that all required tables are created."""
        import sqlite3

        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}

        assert "trades" in tables
        assert "trade_features" in tables
        assert "regime_history" in tables
        assert "signal_events" in tables
        assert "cycle_diagnostics" in tables
        assert "challenge_attempts" in tables

        conn.close()

    def test_wal_mode_enabled(self, db, temp_db_path):
        """Test that WAL mode is enabled."""
        import sqlite3

        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal"
        conn.close()

    def test_cached_connection_mode(self, cached_db):
        """Test that cached connection mode works."""
        assert cached_db._cache_connection is True

        # First operation should create cached connection
        cached_db.get_trade_count()
        assert cached_db._cached_conn is not None

        # Subsequent operations reuse connection
        conn_id = id(cached_db._cached_conn)
        cached_db.get_trade_count()
        assert id(cached_db._cached_conn) == conn_id


# =============================================================================
# Trade CRUD Tests
# =============================================================================


class TestTradeOperations:
    """Tests for trade CRUD operations."""

    def test_add_trade_basic(self, db, sample_trade_data):
        """Test adding a basic trade."""
        db.add_trade(**sample_trade_data)

        assert db.get_trade_count() == 1

    def test_add_trade_with_features_stored_separately(self, db, sample_trade_data):
        """Test that features are stored in trade_features table."""
        db.add_trade(**sample_trade_data)

        trades = db.get_trades()
        assert len(trades) == 1
        assert trades[0].features_json is not None
        features = json.loads(trades[0].features_json)
        assert "rsi" in features

    def test_add_trade_without_optional_fields(self, db):
        """Test adding trade with only required fields."""
        db.add_trade(
            trade_id="t001",
            signal_id="s001",
            signal_type="test",
            direction="long",
            entry_price=100.0,
            exit_price=105.0,
            pnl=50.0,
            is_win=True,
            entry_time="2024-01-15T10:00:00Z",
            exit_time="2024-01-15T11:00:00Z",
        )

        trades = db.get_trades()
        assert len(trades) == 1
        assert trades[0].stop_loss is None
        assert trades[0].regime is None

    def test_get_trades_no_filter(self, db, sample_trade_data):
        """Test getting all trades without filters."""
        db.add_trade(**sample_trade_data)
        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["signal_id"] = "sig_002"
        db.add_trade(**sample_trade_data)

        trades = db.get_trades()
        assert len(trades) == 2

    def test_get_trades_filter_by_signal_type(self, db, sample_trade_data):
        """Test filtering trades by signal type."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["signal_type"] = "vwap_bounce"
        db.add_trade(**sample_trade_data)

        trades = db.get_trades(signal_type="ema_crossover")
        assert len(trades) == 1
        assert trades[0].signal_type == "ema_crossover"

    def test_get_trades_filter_by_regime(self, db, sample_trade_data):
        """Test filtering trades by regime."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["regime"] = "ranging"
        db.add_trade(**sample_trade_data)

        trades = db.get_trades(regime="trending_up")
        assert len(trades) == 1
        assert trades[0].regime == "trending_up"

    def test_get_trades_filter_by_direction(self, db, sample_trade_data):
        """Test filtering trades by direction."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["direction"] = "short"
        db.add_trade(**sample_trade_data)

        trades = db.get_trades(direction="long")
        assert len(trades) == 1
        assert trades[0].direction == "long"

    def test_get_trades_filter_by_win_status(self, db, sample_trade_data):
        """Test filtering trades by win/loss."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["is_win"] = False
        sample_trade_data["pnl"] = -30.0
        db.add_trade(**sample_trade_data)

        wins = db.get_trades(is_win=True)
        losses = db.get_trades(is_win=False)

        assert len(wins) == 1
        assert len(losses) == 1

    def test_get_trades_filter_by_time_range(self, db, sample_trade_data):
        """Test filtering trades by time range."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["entry_time"] = "2024-01-20T10:00:00Z"
        sample_trade_data["exit_time"] = "2024-01-20T11:00:00Z"
        db.add_trade(**sample_trade_data)

        trades = db.get_trades(from_time="2024-01-16T00:00:00Z")
        assert len(trades) == 1
        assert trades[0].trade_id == "trade_002"

    def test_get_trades_filter_by_pnl_range(self, db, sample_trade_data):
        """Test filtering trades by P&L range."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["pnl"] = -20.0
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_003"
        sample_trade_data["pnl"] = 100.0
        db.add_trade(**sample_trade_data)

        trades = db.get_trades(min_pnl=0.0, max_pnl=60.0)
        assert len(trades) == 1
        assert trades[0].pnl == 50.0

    def test_get_trades_with_limit_and_offset(self, db, sample_trade_data):
        """Test pagination with limit and offset."""
        for i in range(5):
            sample_trade_data["trade_id"] = f"trade_{i:03d}"
            sample_trade_data["entry_time"] = f"2024-01-{15+i:02d}T10:00:00Z"
            db.add_trade(**sample_trade_data)

        trades = db.get_trades(limit=2, offset=1)
        assert len(trades) == 2

    def test_trade_replace_on_duplicate_id(self, db, sample_trade_data):
        """Test that duplicate trade_id replaces existing trade."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["pnl"] = 100.0
        db.add_trade(**sample_trade_data)

        assert db.get_trade_count() == 1
        trades = db.get_trades()
        assert trades[0].pnl == 100.0


# =============================================================================
# Performance Analytics Tests
# =============================================================================


class TestPerformanceAnalytics:
    """Tests for performance analytics methods."""

    def test_get_performance_by_signal_type(self, db, sample_trade_data):
        """Test performance breakdown by signal type."""
        # Add winning ema_crossover trade
        db.add_trade(**sample_trade_data)

        # Add losing ema_crossover trade
        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["pnl"] = -30.0
        sample_trade_data["is_win"] = False
        db.add_trade(**sample_trade_data)

        # Add winning vwap_bounce trade
        sample_trade_data["trade_id"] = "trade_003"
        sample_trade_data["signal_type"] = "vwap_bounce"
        sample_trade_data["pnl"] = 40.0
        sample_trade_data["is_win"] = True
        db.add_trade(**sample_trade_data)

        perf = db.get_performance_by_signal_type()

        assert "ema_crossover" in perf
        assert perf["ema_crossover"]["count"] == 2
        assert perf["ema_crossover"]["wins"] == 1
        assert perf["ema_crossover"]["losses"] == 1
        assert perf["ema_crossover"]["win_rate"] == 0.5

        assert "vwap_bounce" in perf
        assert perf["vwap_bounce"]["count"] == 1
        assert perf["vwap_bounce"]["win_rate"] == 1.0

    def test_get_performance_by_signal_type_with_days_filter(self, db, sample_trade_data):
        """Test performance filtered by days."""
        # Use recent dates (relative to current date 2026-01-29)
        sample_trade_data["entry_time"] = "2026-01-20T10:00:00Z"
        sample_trade_data["exit_time"] = "2026-01-20T11:30:00Z"
        db.add_trade(**sample_trade_data)

        # Add old trade (outside 30-day window)
        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["entry_time"] = "2020-01-01T10:00:00Z"
        sample_trade_data["exit_time"] = "2020-01-01T11:00:00Z"
        db.add_trade(**sample_trade_data)

        perf = db.get_performance_by_signal_type(days=30)
        # Only recent trade should be included
        assert perf["ema_crossover"]["count"] == 1

    def test_get_performance_by_regime(self, db, sample_trade_data):
        """Test performance breakdown by market regime."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["regime"] = "ranging"
        sample_trade_data["pnl"] = -20.0
        sample_trade_data["is_win"] = False
        db.add_trade(**sample_trade_data)

        perf = db.get_performance_by_regime()

        assert "trending_up" in perf
        assert perf["trending_up"]["count"] == 1
        assert perf["trending_up"]["win_rate"] == 1.0

        assert "ranging" in perf
        assert perf["ranging"]["win_rate"] == 0.0

    def test_get_performance_by_hour(self, db, sample_trade_data):
        """Test performance breakdown by hour of day."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["entry_time"] = "2024-01-15T14:00:00Z"
        db.add_trade(**sample_trade_data)

        perf = db.get_performance_by_hour()

        assert 10 in perf
        assert 14 in perf

    def test_get_summary(self, db, sample_trade_data):
        """Test database summary."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["pnl"] = -30.0
        sample_trade_data["is_win"] = False
        db.add_trade(**sample_trade_data)

        summary = db.get_summary()

        assert summary["total_trades"] == 2
        assert summary["wins"] == 1
        assert summary["losses"] == 1
        assert summary["win_rate"] == 0.5
        assert summary["total_pnl"] == 20.0  # 50 - 30 = 20

    def test_get_summary_empty_db(self, db):
        """Test summary on empty database."""
        summary = db.get_summary()

        assert summary["total_trades"] == 0
        assert summary["wins"] == 0
        assert summary["win_rate"] == 0

    def test_get_trade_summary_basic(self, db, sample_trade_data):
        """Test trade summary stats."""
        db.add_trade(**sample_trade_data)

        summary = db.get_trade_summary()

        assert summary["total"] == 1
        assert summary["wins"] == 1
        assert summary["losses"] == 0
        assert summary["win_rate"] == 1.0
        assert summary["total_pnl"] == 50.0

    def test_get_trade_summary_with_time_filter(self, db, sample_trade_data):
        """Test trade summary filtered by exit time."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["exit_time"] = "2024-01-20T10:00:00Z"
        db.add_trade(**sample_trade_data)

        summary = db.get_trade_summary(from_exit_time="2024-01-16T00:00:00Z")

        assert summary["total"] == 1


# =============================================================================
# Signal Events Tests
# =============================================================================


class TestSignalEvents:
    """Tests for signal events tracking."""

    def test_add_signal_event(self, db):
        """Test adding a signal event."""
        db.add_signal_event(
            signal_id="sig_001",
            status="generated",
            timestamp="2024-01-15T10:00:00Z",
            payload={"confidence": 0.85, "price": 100.0},
        )

        events = db.get_recent_signal_events(limit=10)
        assert len(events) == 1
        assert events[0]["signal_id"] == "sig_001"
        assert events[0]["status"] == "generated"
        assert events[0]["payload"]["confidence"] == 0.85

    def test_add_signal_event_without_payload(self, db):
        """Test adding signal event without payload."""
        db.add_signal_event(
            signal_id="sig_002",
            status="entered",
            timestamp="2024-01-15T10:05:00Z",
        )

        events = db.get_recent_signal_events()
        assert len(events) == 1
        assert events[0]["payload"] == {}

    def test_get_signal_events_with_status_filter(self, db):
        """Test filtering signal events by status."""
        db.add_signal_event("sig_001", "generated", "2024-01-15T10:00:00Z")
        db.add_signal_event("sig_001", "entered", "2024-01-15T10:05:00Z")
        db.add_signal_event("sig_001", "exited", "2024-01-15T11:00:00Z")

        entered = db.get_signal_events(status="entered")
        assert len(entered) == 1
        assert entered[0]["status"] == "entered"

    def test_get_signal_events_with_time_filter(self, db):
        """Test filtering signal events by time."""
        db.add_signal_event("sig_001", "generated", "2024-01-15T10:00:00Z")
        db.add_signal_event("sig_002", "generated", "2024-01-16T10:00:00Z")

        events = db.get_signal_events(from_time="2024-01-16T00:00:00Z")
        assert len(events) == 1

    def test_get_signal_event_counts(self, db):
        """Test counting signal events by status."""
        db.add_signal_event("sig_001", "generated", "2024-01-15T10:00:00Z")
        db.add_signal_event("sig_002", "generated", "2024-01-15T10:05:00Z")
        db.add_signal_event("sig_001", "entered", "2024-01-15T10:10:00Z")
        db.add_signal_event("sig_001", "exited", "2024-01-15T11:00:00Z")

        counts = db.get_signal_event_counts()

        assert counts["generated"] == 2
        assert counts["entered"] == 1
        assert counts["exited"] == 1


# =============================================================================
# Cycle Diagnostics Tests
# =============================================================================


class TestCycleDiagnostics:
    """Tests for cycle diagnostics tracking."""

    def test_add_cycle_diagnostics(self, db):
        """Test adding cycle diagnostics."""
        db.add_cycle_diagnostics(
            timestamp="2024-01-15T10:00:00Z",
            cycle_count=1,
            quiet_reason="Active",
            diagnostics={
                "raw_signals": 5,
                "validated_signals": 3,
                "actionable_signals": 2,
                "rejected_confidence": 1,
            },
        )

        # Verify via aggregate
        agg = db.get_cycle_diagnostics_aggregate()
        assert agg["cycles"] == 1
        assert agg["raw_signals"] == 5
        assert agg["validated_signals"] == 3

    def test_get_cycle_diagnostics_aggregate(self, db):
        """Test aggregating cycle diagnostics."""
        db.add_cycle_diagnostics(
            timestamp="2024-01-15T10:00:00Z",
            cycle_count=1,
            diagnostics={"raw_signals": 5, "actionable_signals": 2},
        )
        db.add_cycle_diagnostics(
            timestamp="2024-01-15T10:01:00Z",
            cycle_count=2,
            diagnostics={"raw_signals": 3, "actionable_signals": 1},
        )

        agg = db.get_cycle_diagnostics_aggregate()

        assert agg["cycles"] == 2
        assert agg["raw_signals"] == 8  # 5 + 3
        assert agg["actionable_signals"] == 3  # 2 + 1

    def test_get_quiet_reason_counts(self, db):
        """Test counting quiet reasons."""
        db.add_cycle_diagnostics(
            timestamp="2024-01-15T10:00:00Z",
            quiet_reason="NoOpportunity",
        )
        db.add_cycle_diagnostics(
            timestamp="2024-01-15T10:01:00Z",
            quiet_reason="NoOpportunity",
        )
        db.add_cycle_diagnostics(
            timestamp="2024-01-15T10:02:00Z",
            quiet_reason="MarketClosed",
        )

        counts = db.get_quiet_reason_counts()

        assert counts["NoOpportunity"] == 2
        assert counts["MarketClosed"] == 1


# =============================================================================
# Challenge Attempts Tests
# =============================================================================


class TestChallengeAttempts:
    """Tests for challenge attempt tracking."""

    def test_add_challenge_attempt(self, db):
        """Test adding a challenge attempt."""
        db.add_challenge_attempt(
            attempt_id=1,
            started_at="2024-01-01T00:00:00Z",
            ended_at="2024-01-15T00:00:00Z",
            outcome="pass",
            starting_balance=50000.0,
            ending_balance=53000.0,
            pnl=3000.0,
            trades=25,
            wins=15,
            losses=10,
            max_drawdown_hit=2000.0,
            profit_peak=3500.0,
        )

        attempts = db.get_challenge_attempts()
        assert len(attempts) == 1
        assert attempts[0]["attempt_id"] == 1
        assert attempts[0]["outcome"] == "pass"
        assert attempts[0]["pnl"] == 3000.0
        assert attempts[0]["win_rate"] == 60.0  # 15/25 * 100

    def test_get_challenge_attempts_ordered(self, db):
        """Test that challenge attempts are ordered by ID descending."""
        db.add_challenge_attempt(
            attempt_id=1,
            started_at="2024-01-01T00:00:00Z",
            ended_at="2024-01-15T00:00:00Z",
            outcome="fail",
            starting_balance=50000.0,
            ending_balance=45000.0,
            pnl=-5000.0,
            trades=20,
            wins=5,
            losses=15,
        )
        db.add_challenge_attempt(
            attempt_id=2,
            started_at="2024-01-16T00:00:00Z",
            ended_at="2024-01-30T00:00:00Z",
            outcome="pass",
            starting_balance=50000.0,
            ending_balance=53000.0,
            pnl=3000.0,
            trades=25,
            wins=16,
            losses=9,
        )

        attempts = db.get_challenge_attempts()
        assert attempts[0]["attempt_id"] == 2  # Most recent first
        assert attempts[1]["attempt_id"] == 1

    def test_get_challenge_summary(self, db):
        """Test challenge summary statistics."""
        db.add_challenge_attempt(
            attempt_id=1,
            started_at="2024-01-01T00:00:00Z",
            ended_at="2024-01-15T00:00:00Z",
            outcome="fail",
            starting_balance=50000.0,
            ending_balance=45000.0,
            pnl=-5000.0,
            trades=20,
            wins=5,
            losses=15,
        )
        db.add_challenge_attempt(
            attempt_id=2,
            started_at="2024-01-16T00:00:00Z",
            ended_at="2024-01-30T00:00:00Z",
            outcome="pass",
            starting_balance=50000.0,
            ending_balance=54000.0,
            pnl=4000.0,
            trades=25,
            wins=16,
            losses=9,
        )

        summary = db.get_challenge_summary()

        assert summary["total_attempts"] == 2
        assert summary["passes"] == 1
        assert summary["fails"] == 1
        assert summary["pass_rate"] == 50.0
        assert summary["total_trades"] == 45  # 20 + 25
        assert summary["total_pnl"] == -1000.0  # -5000 + 4000

    def test_get_challenge_summary_empty(self, db):
        """Test challenge summary with no attempts."""
        summary = db.get_challenge_summary()

        assert summary["total_attempts"] == 0
        assert summary["pass_rate"] == 0.0


# =============================================================================
# Regime History Tests
# =============================================================================


class TestRegimeHistory:
    """Tests for regime history snapshots."""

    def test_add_regime_snapshot(self, db):
        """Test adding a regime snapshot."""
        db.add_regime_snapshot(
            regime="trending_up",
            confidence=0.85,
            timestamp="2024-01-15T10:00:00Z",
            volatility_percentile=70.0,
            trend_strength=0.6,
        )

        # Verify via direct query (no get method exists)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM regime_history")
            rows = cursor.fetchall()

        assert len(rows) == 1
        assert rows[0]["regime"] == "trending_up"
        assert rows[0]["confidence"] == 0.85

    def test_add_regime_snapshot_auto_timestamp(self, db):
        """Test adding regime snapshot with auto-generated timestamp."""
        db.add_regime_snapshot(regime="ranging", confidence=0.75)

        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp FROM regime_history")
            ts = cursor.fetchone()["timestamp"]

        assert ts is not None


# =============================================================================
# Feature Correlation Tests
# =============================================================================


class TestFeatureCorrelations:
    """Tests for feature correlation analysis."""

    def test_get_feature_correlations_empty(self, db):
        """Test feature correlations with no data."""
        result = db.get_feature_correlations("rsi")
        assert result["count"] == 0

    def test_get_feature_correlations_with_data(self, db, sample_trade_data):
        """Test feature correlations with trade data."""
        # Add multiple trades with varying RSI and outcomes
        for i, (rsi, is_win, pnl) in enumerate(
            [
                (30, True, 50),
                (40, True, 30),
                (50, False, -20),
                (60, False, -30),
                (70, True, 40),
            ]
        ):
            sample_trade_data["trade_id"] = f"trade_{i:03d}"
            sample_trade_data["signal_id"] = f"sig_{i:03d}"
            sample_trade_data["is_win"] = is_win
            sample_trade_data["pnl"] = pnl
            sample_trade_data["features"] = {"rsi": float(rsi)}
            db.add_trade(**sample_trade_data)

        result = db.get_feature_correlations("rsi")

        assert result["count"] == 5
        assert "win_correlation" in result
        assert "pnl_correlation" in result
        assert "mean_value" in result
        assert "std_value" in result


# =============================================================================
# Recent Trades by Exit Tests
# =============================================================================


class TestRecentTradesByExit:
    """Tests for recent trades by exit time queries."""

    def test_get_recent_trades_by_exit(self, db, sample_trade_data):
        """Test getting recent trades ordered by exit time."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["exit_time"] = "2024-01-15T14:00:00Z"
        db.add_trade(**sample_trade_data)

        trades = db.get_recent_trades_by_exit(limit=10)

        assert len(trades) == 2
        # Most recent exit first
        assert trades[0]["exit_time"] == "2024-01-15T14:00:00Z"

    def test_get_recent_trades_by_exit_with_time_filter(self, db, sample_trade_data):
        """Test filtering recent trades by exit time."""
        db.add_trade(**sample_trade_data)

        sample_trade_data["trade_id"] = "trade_002"
        sample_trade_data["exit_time"] = "2024-01-20T10:00:00Z"
        db.add_trade(**sample_trade_data)

        trades = db.get_recent_trades_by_exit(from_exit_time="2024-01-16T00:00:00Z")

        assert len(trades) == 1
        assert trades[0]["signal_id"] == "sig_001"

    def test_get_recent_trades_by_exit_includes_features(self, db, sample_trade_data):
        """Test that features are included in recent trades."""
        db.add_trade(**sample_trade_data)

        trades = db.get_recent_trades_by_exit()

        assert len(trades) == 1
        assert "features" in trades[0]
        assert trades[0]["features"]["rsi"] == 55.0


# =============================================================================
# Connection Management Tests
# =============================================================================


class TestConnectionManagement:
    """Tests for database connection management."""

    def test_close_cached_connection(self, cached_db):
        """Test closing cached connection."""
        cached_db.get_trade_count()
        assert cached_db._cached_conn is not None

        cached_db.close()
        assert cached_db._cached_conn is None

    def test_close_non_cached_is_noop(self, db):
        """Test closing non-cached database is safe."""
        db.close()  # Should not raise
        assert db._cached_conn is None

    def test_multiple_close_calls_safe(self, cached_db):
        """Test multiple close calls are safe."""
        cached_db.get_trade_count()
        cached_db.close()
        cached_db.close()  # Should not raise


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_add_trade_with_special_characters_in_exit_reason(self, db, sample_trade_data):
        """Test adding trade with special characters."""
        sample_trade_data["exit_reason"] = "Manual close: user 'John' requested"
        db.add_trade(**sample_trade_data)

        trades = db.get_trades()
        assert trades[0].exit_reason == "Manual close: user 'John' requested"

    def test_add_signal_event_with_invalid_json_payload(self, db):
        """Test that invalid payload is handled gracefully."""
        # This tests the try/except in add_signal_event
        # Create a non-serializable object
        class NonSerializable:
            pass

        # Mock json.dumps to raise
        original_dumps = json.dumps
        call_count = [0]

        def mock_dumps(obj, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise TypeError("Not serializable")
            return original_dumps(obj, **kwargs)

        with patch("pearlalgo.learning.trade_database.json.dumps", mock_dumps):
            db.add_signal_event(
                signal_id="sig_001",
                status="test",
                timestamp="2024-01-15T10:00:00Z",
                payload={"data": "test"},
            )

        events = db.get_recent_signal_events()
        assert len(events) == 1

    def test_get_trades_with_all_filters_combined(self, db, sample_trade_data):
        """Test querying with all filters applied."""
        db.add_trade(**sample_trade_data)

        trades = db.get_trades(
            signal_type="ema_crossover",
            regime="trending_up",
            direction="long",
            is_win=True,
            from_time="2024-01-01T00:00:00Z",
            to_time="2024-12-31T23:59:59Z",
            min_pnl=0.0,
            max_pnl=100.0,
            limit=10,
            offset=0,
        )

        assert len(trades) == 1

    def test_empty_database_queries(self, db):
        """Test queries on empty database return appropriate defaults."""
        assert db.get_trade_count() == 0
        assert db.get_trades() == []
        assert db.get_performance_by_signal_type() == {}
        assert db.get_performance_by_regime() == {}
        assert db.get_performance_by_hour() == {}
        assert db.get_recent_signal_events() == []
        assert db.get_signal_event_counts() == {}
        assert db.get_challenge_attempts() == []
