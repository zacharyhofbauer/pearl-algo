"""
Tests for TradeDatabase — targets uncovered lines to raise coverage above 57%.

Covers: add_trade, get_recent_trades_by_exit, add_signal_event,
get_signal_event_by_id, get_signal_events, get_recent_signal_events,
get_signal_event_counts, get_all_signal_ids, add_cycle_diagnostics,
get_cycle_diagnostics_aggregate, get_quiet_reason_counts,
add_regime_snapshot, get_summary, get_performance_by_signal_type,
get_trade_summary, get_trade_count, schema migration, edge cases.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pearlalgo.storage.trade_database import TradeDatabase, TradeRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> TradeDatabase:
    """Fresh database per test."""
    d = TradeDatabase(db_path=tmp_path / "test.db")
    yield d
    d.close()


@pytest.fixture
def db_cached(tmp_path: Path) -> TradeDatabase:
    """Database with cached connection mode."""
    d = TradeDatabase(db_path=tmp_path / "test_cached.db", cache_connection=True)
    yield d
    d.close()


def _add_sample_trade(
    db: TradeDatabase,
    trade_id: str = "t-1",
    signal_id: str = "sig-1",
    signal_type: str = "smc_fvg",
    direction: str = "long",
    entry_price: float = 21000.0,
    exit_price: float = 21050.0,
    pnl: float = 10.0,
    is_win: bool = True,
    entry_time: str = "2026-04-01T10:00:00",
    exit_time: str = "2026-04-01T10:30:00",
    **kwargs,
) -> None:
    db.add_trade(
        trade_id=trade_id,
        signal_id=signal_id,
        signal_type=signal_type,
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
        is_win=is_win,
        entry_time=entry_time,
        exit_time=exit_time,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. add_trade and retrieval
# ---------------------------------------------------------------------------

class TestAddTradeAndRetrieval:
    def test_add_and_count(self, db: TradeDatabase) -> None:
        assert db.get_trade_count() == 0
        _add_sample_trade(db)
        assert db.get_trade_count() == 1

    def test_add_trade_with_all_optional_fields(self, db: TradeDatabase) -> None:
        _add_sample_trade(
            db,
            stop_loss=20950.0,
            take_profit=21100.0,
            exit_reason="tp_hit",
            hold_duration_minutes=30.0,
            regime="trending",
            context_key="ctx-1",
            volatility_percentile=0.75,
            volume_percentile=0.6,
            features={"rsi": 55.0, "atr": 12.5},
            max_price=21060.0,
            min_price=20990.0,
            mfe_points=60.0,
            mae_points=-10.0,
        )
        assert db.get_trade_count() == 1
        trades = db.get_recent_trades_by_exit(limit=1)
        assert len(trades) == 1
        assert trades[0]["signal_type"] == "smc_fvg"
        assert trades[0]["features"]["rsi"] == 55.0

    def test_add_trade_replaces_on_duplicate_trade_id(self, db: TradeDatabase) -> None:
        _add_sample_trade(db, pnl=10.0)
        _add_sample_trade(db, pnl=20.0)  # same trade_id
        assert db.get_trade_count() == 1
        summary = db.get_summary()
        assert summary["total_pnl"] == 20.0

    def test_add_trade_with_features_replaces_old_features(self, db: TradeDatabase) -> None:
        _add_sample_trade(db, features={"rsi": 50.0})
        _add_sample_trade(db, features={"rsi": 70.0, "atr": 15.0})
        # Verify via raw SQL that trade_features only has current features
        conn = sqlite3.connect(str(db.db_path))
        rows = conn.execute("SELECT feature_name, feature_value FROM trade_features WHERE trade_id='t-1'").fetchall()
        conn.close()
        features = {r[0]: r[1] for r in rows}
        assert features == {"rsi": 70.0, "atr": 15.0}

    def test_add_trade_without_features(self, db: TradeDatabase) -> None:
        _add_sample_trade(db, features=None)
        assert db.get_trade_count() == 1

    def test_get_recent_trades_by_exit_with_from_time(self, db: TradeDatabase) -> None:
        _add_sample_trade(db, trade_id="t-old", exit_time="2026-03-01T10:00:00")
        _add_sample_trade(db, trade_id="t-new", exit_time="2026-04-01T10:00:00")
        trades = db.get_recent_trades_by_exit(from_exit_time="2026-04-01T00:00:00")
        assert len(trades) == 1
        assert trades[0]["signal_id"] == "sig-1"

    def test_get_recent_trades_by_exit_limit(self, db: TradeDatabase) -> None:
        for i in range(5):
            _add_sample_trade(db, trade_id=f"t-{i}", exit_time=f"2026-04-01T10:{i:02d}:00")
        trades = db.get_recent_trades_by_exit(limit=3)
        assert len(trades) == 3


# ---------------------------------------------------------------------------
# 2. Signal events
# ---------------------------------------------------------------------------

class TestSignalEvents:
    def test_add_and_get_by_id(self, db: TradeDatabase) -> None:
        db.add_signal_event(
            signal_id="sig-100",
            status="generated",
            timestamp="2026-04-01T10:00:00",
            payload={"confidence": 0.8},
        )
        result = db.get_signal_event_by_id("sig-100")
        assert result is not None
        assert result["signal_id"] == "sig-100"
        assert result["status"] == "generated"
        assert result["confidence"] == 0.8

    def test_get_signal_event_by_id_returns_latest(self, db: TradeDatabase) -> None:
        db.add_signal_event("sig-1", "generated", "2026-04-01T10:00:00")
        db.add_signal_event("sig-1", "executed", "2026-04-01T10:05:00")
        result = db.get_signal_event_by_id("sig-1")
        assert result["status"] == "executed"

    def test_get_signal_event_by_id_missing(self, db: TradeDatabase) -> None:
        assert db.get_signal_event_by_id("nonexistent") is None

    def test_get_recent_signal_events(self, db: TradeDatabase) -> None:
        for i in range(5):
            db.add_signal_event(f"sig-{i}", "generated", f"2026-04-01T10:{i:02d}:00")
        events = db.get_recent_signal_events(limit=3)
        assert len(events) == 3
        # Most recent first
        assert events[0]["signal_id"] == "sig-4"

    def test_get_signal_events_filter_by_status(self, db: TradeDatabase) -> None:
        db.add_signal_event("s1", "generated", "2026-04-01T10:00:00")
        db.add_signal_event("s2", "executed", "2026-04-01T10:01:00")
        db.add_signal_event("s3", "generated", "2026-04-01T10:02:00")
        events = db.get_signal_events(status="generated")
        assert len(events) == 2

    def test_get_signal_events_filter_by_from_time(self, db: TradeDatabase) -> None:
        db.add_signal_event("s1", "generated", "2026-03-01T10:00:00")
        db.add_signal_event("s2", "generated", "2026-04-01T10:00:00")
        events = db.get_signal_events(from_time="2026-04-01T00:00:00")
        assert len(events) == 1

    def test_get_signal_event_counts(self, db: TradeDatabase) -> None:
        db.add_signal_event("s1", "generated", "2026-04-01T10:00:00")
        db.add_signal_event("s2", "generated", "2026-04-01T10:01:00")
        db.add_signal_event("s3", "executed", "2026-04-01T10:02:00")
        counts = db.get_signal_event_counts()
        assert counts["generated"] == 2
        assert counts["executed"] == 1

    def test_get_signal_event_counts_with_from_time(self, db: TradeDatabase) -> None:
        db.add_signal_event("s1", "generated", "2026-03-01T10:00:00")
        db.add_signal_event("s2", "generated", "2026-04-01T10:00:00")
        counts = db.get_signal_event_counts(from_time="2026-04-01T00:00:00")
        assert counts["generated"] == 1

    def test_get_all_signal_ids(self, db: TradeDatabase) -> None:
        db.add_signal_event("s1", "generated", "2026-04-01T10:00:00")
        db.add_signal_event("s2", "executed", "2026-04-01T10:01:00")
        db.add_signal_event("s1", "executed", "2026-04-01T10:02:00")
        ids = db.get_all_signal_ids()
        assert ids == {"s1", "s2"}

    def test_add_signal_event_with_none_payload(self, db: TradeDatabase) -> None:
        db.add_signal_event("s1", "generated", "2026-04-01T10:00:00", payload=None)
        result = db.get_signal_event_by_id("s1")
        assert result is not None
        assert result["signal_id"] == "s1"


# ---------------------------------------------------------------------------
# 3. Cycle diagnostics
# ---------------------------------------------------------------------------

class TestCycleDiagnostics:
    def test_add_cycle_diagnostics_minimal(self, db: TradeDatabase) -> None:
        db.add_cycle_diagnostics(timestamp="2026-04-01T10:00:00")
        agg = db.get_cycle_diagnostics_aggregate()
        assert agg["cycles"] == 1

    def test_add_cycle_diagnostics_with_all_fields(self, db: TradeDatabase) -> None:
        db.add_cycle_diagnostics(
            timestamp="2026-04-01T10:00:00",
            cycle_count=42,
            quiet_reason="no_signals",
            diagnostics={
                "raw_signals": 10,
                "validated_signals": 8,
                "actionable_signals": 3,
                "explore_signals": 1,
                "duplicates_filtered": 2,
                "stop_cap_applied": 0,
                "session_scaling_applied": 1,
                "rejected_market_hours": 0,
                "rejected_confidence": 1,
                "rejected_risk_reward": 2,
                "rejected_quality_scorer": 0,
                "rejected_order_book": 0,
                "rejected_invalid_prices": 1,
                "rejected_regime_filter": 0,
                "adaptive_sizing_applied": 1,
            },
        )
        agg = db.get_cycle_diagnostics_aggregate()
        assert agg["raw_signals"] == 10
        assert agg["validated_signals"] == 8
        assert agg["actionable_signals"] == 3

    def test_cycle_diagnostics_aggregate_with_from_time(self, db: TradeDatabase) -> None:
        db.add_cycle_diagnostics(timestamp="2026-03-01T10:00:00", diagnostics={"raw_signals": 5})
        db.add_cycle_diagnostics(timestamp="2026-04-01T10:00:00", diagnostics={"raw_signals": 10})
        agg = db.get_cycle_diagnostics_aggregate(from_time="2026-04-01T00:00:00")
        assert agg["cycles"] == 1
        assert agg["raw_signals"] == 10

    def test_cycle_diagnostics_aggregate_empty(self, db: TradeDatabase) -> None:
        agg = db.get_cycle_diagnostics_aggregate()
        assert agg["cycles"] == 0

    def test_quiet_reason_counts(self, db: TradeDatabase) -> None:
        db.add_cycle_diagnostics(timestamp="2026-04-01T10:00:00", quiet_reason="no_signals")
        db.add_cycle_diagnostics(timestamp="2026-04-01T10:01:00", quiet_reason="no_signals")
        db.add_cycle_diagnostics(timestamp="2026-04-01T10:02:00", quiet_reason="market_closed")
        db.add_cycle_diagnostics(timestamp="2026-04-01T10:03:00", quiet_reason=None)
        counts = db.get_quiet_reason_counts()
        assert counts["no_signals"] == 2
        assert counts["market_closed"] == 1
        assert "None" not in counts  # None rows excluded

    def test_quiet_reason_counts_with_from_time(self, db: TradeDatabase) -> None:
        db.add_cycle_diagnostics(timestamp="2026-03-01T10:00:00", quiet_reason="old")
        db.add_cycle_diagnostics(timestamp="2026-04-01T10:00:00", quiet_reason="new")
        counts = db.get_quiet_reason_counts(from_time="2026-04-01T00:00:00")
        assert "old" not in counts
        assert counts["new"] == 1

    def test_cycle_diagnostics_non_int_value_handled(self, db: TradeDatabase) -> None:
        """Non-integer values in diagnostics should be handled gracefully."""
        db.add_cycle_diagnostics(
            timestamp="2026-04-01T10:00:00",
            diagnostics={"raw_signals": "not_a_number"},
        )
        # Should not raise; the _int helper logs and returns None
        agg = db.get_cycle_diagnostics_aggregate()
        assert agg["cycles"] == 1


# ---------------------------------------------------------------------------
# 4. Regime snapshots
# ---------------------------------------------------------------------------

class TestRegimeSnapshots:
    def test_add_regime_snapshot_minimal(self, db: TradeDatabase) -> None:
        db.add_regime_snapshot(regime="trending", confidence=0.85)
        conn = sqlite3.connect(str(db.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM regime_history ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row["regime"] == "trending"
        assert row["confidence"] == 0.85
        assert row["timestamp"] is not None  # auto-filled

    def test_add_regime_snapshot_all_fields(self, db: TradeDatabase) -> None:
        db.add_regime_snapshot(
            regime="mean_reverting",
            confidence=0.72,
            timestamp="2026-04-01T10:00:00",
            volatility_percentile=0.55,
            trend_strength=0.3,
        )
        conn = sqlite3.connect(str(db.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM regime_history ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row["regime"] == "mean_reverting"
        assert row["volatility_percentile"] == 0.55
        assert row["trend_strength"] == 0.3


# ---------------------------------------------------------------------------
# 5. Schema migration (ALTER TABLE ADD COLUMN for existing columns)
# ---------------------------------------------------------------------------

class TestSchemaMigration:
    def test_migration_adds_columns_to_existing_table(self, tmp_path: Path) -> None:
        """Create a trades table WITHOUT migration columns, then open TradeDatabase
        which should ALTER TABLE without error."""
        db_path = tmp_path / "migrate.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE trades (
                trade_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                stop_loss REAL,
                take_profit REAL,
                pnl REAL NOT NULL,
                is_win INTEGER NOT NULL,
                exit_reason TEXT,
                entry_time TEXT NOT NULL,
                exit_time TEXT NOT NULL,
                hold_duration_minutes REAL,
                regime TEXT,
                context_key TEXT,
                volatility_percentile REAL,
                volume_percentile REAL,
                features_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        # Opening TradeDatabase should add max_price, min_price, mfe_points, mae_points
        db = TradeDatabase(db_path=db_path)
        _add_sample_trade(db, max_price=21060.0, min_price=20990.0, mfe_points=60.0, mae_points=-10.0)
        db.close()

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT max_price, min_price, mfe_points, mae_points FROM trades WHERE trade_id='t-1'").fetchone()
        conn.close()
        assert row == (21060.0, 20990.0, 60.0, -10.0)

    def test_migration_idempotent_columns_already_exist(self, tmp_path: Path) -> None:
        """If columns already exist, migration should silently succeed."""
        db_path = tmp_path / "already.db"
        db1 = TradeDatabase(db_path=db_path)
        db1.close()
        # Re-open — columns already present, ALTER should be a no-op
        db2 = TradeDatabase(db_path=db_path)
        db2.close()


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_db_summary(self, db: TradeDatabase) -> None:
        summary = db.get_summary()
        assert summary["total_trades"] == 0
        assert summary["wins"] == 0
        assert summary["losses"] == 0
        assert summary["win_rate"] == 0.0
        assert summary["total_pnl"] == 0.0
        assert summary["avg_pnl"] == 0.0
        assert summary["first_trade"] is None
        assert summary["last_trade"] is None

    def test_empty_db_trade_summary(self, db: TradeDatabase) -> None:
        ts = db.get_trade_summary()
        assert ts["total"] == 0
        assert ts["avg_hold_minutes"] is None

    def test_empty_db_trade_count(self, db: TradeDatabase) -> None:
        assert db.get_trade_count() == 0

    def test_empty_db_performance_by_signal_type(self, db: TradeDatabase) -> None:
        perf = db.get_performance_by_signal_type()
        assert perf == {}

    def test_empty_db_recent_trades(self, db: TradeDatabase) -> None:
        assert db.get_recent_trades_by_exit() == []

    def test_empty_db_signal_events(self, db: TradeDatabase) -> None:
        assert db.get_recent_signal_events() == []
        assert db.get_signal_events() == []
        assert db.get_signal_event_counts() == {}
        assert db.get_all_signal_ids() == set()

    def test_none_values_in_trade_optional_fields(self, db: TradeDatabase) -> None:
        _add_sample_trade(
            db,
            stop_loss=None,
            take_profit=None,
            exit_reason=None,
            hold_duration_minutes=None,
            regime=None,
            context_key=None,
            volatility_percentile=None,
            volume_percentile=None,
            features=None,
            max_price=None,
            min_price=None,
            mfe_points=None,
            mae_points=None,
        )
        assert db.get_trade_count() == 1

    def test_cached_connection_mode(self, db_cached: TradeDatabase) -> None:
        _add_sample_trade(db_cached)
        assert db_cached.get_trade_count() == 1
        db_cached.add_signal_event("s1", "generated", "2026-04-01T10:00:00")
        assert db_cached.get_signal_event_by_id("s1") is not None

    def test_close_idempotent(self, db: TradeDatabase) -> None:
        db.close()
        db.close()  # Should not raise

    def test_close_cached_connection(self, db_cached: TradeDatabase) -> None:
        _add_sample_trade(db_cached)
        db_cached.close()
        assert db_cached._cached_conn is None


# ---------------------------------------------------------------------------
# 7. get_summary and get_performance_by_signal_type
# ---------------------------------------------------------------------------

class TestSummaryAndPerformance:
    def test_get_summary_with_trades(self, db: TradeDatabase) -> None:
        _add_sample_trade(db, trade_id="t-1", pnl=10.0, is_win=True, signal_type="smc_fvg")
        _add_sample_trade(db, trade_id="t-2", pnl=-5.0, is_win=False, signal_type="vwap_reversion")
        _add_sample_trade(db, trade_id="t-3", pnl=3.0, is_win=True, signal_type="smc_fvg")
        summary = db.get_summary()
        assert summary["total_trades"] == 3
        assert summary["wins"] == 2
        assert summary["losses"] == 1
        assert summary["win_rate"] == round(2 / 3, 4)
        assert summary["total_pnl"] == 8.0
        assert summary["avg_pnl"] == round(8.0 / 3, 2)
        assert summary["signal_types"] == 2

    def test_get_performance_by_signal_type(self, db: TradeDatabase) -> None:
        _add_sample_trade(db, trade_id="t-1", pnl=10.0, is_win=True, signal_type="smc_fvg")
        _add_sample_trade(db, trade_id="t-2", pnl=-5.0, is_win=False, signal_type="smc_fvg")
        _add_sample_trade(db, trade_id="t-3", pnl=20.0, is_win=True, signal_type="vwap_reversion")
        perf = db.get_performance_by_signal_type()
        assert "smc_fvg" in perf
        assert "vwap_reversion" in perf
        smc = perf["smc_fvg"]
        assert smc["count"] == 2
        assert smc["wins"] == 1
        assert smc["losses"] == 1
        assert smc["win_rate"] == 0.5
        assert smc["total_pnl"] == 5.0
        assert smc["avg_pnl"] == 2.5
        vwap = perf["vwap_reversion"]
        assert vwap["count"] == 1
        assert vwap["wins"] == 1
        assert vwap["total_pnl"] == 20.0

    def test_get_performance_by_signal_type_with_days(self, db: TradeDatabase) -> None:
        # Old trade that should be excluded with days=1
        _add_sample_trade(db, trade_id="t-old", entry_time="2020-01-01T10:00:00", signal_type="old")
        # Recent trade
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%dT%H:%M:%S")
        _add_sample_trade(db, trade_id="t-new", entry_time=now, signal_type="new")
        perf = db.get_performance_by_signal_type(days=1)
        assert "new" in perf
        assert "old" not in perf

    def test_get_trade_summary_with_from_exit_time(self, db: TradeDatabase) -> None:
        _add_sample_trade(db, trade_id="t-1", exit_time="2026-03-01T10:00:00", pnl=10.0, is_win=True)
        _add_sample_trade(db, trade_id="t-2", exit_time="2026-04-01T10:00:00", pnl=-5.0, is_win=False)
        ts = db.get_trade_summary(from_exit_time="2026-04-01T00:00:00")
        assert ts["total"] == 1
        assert ts["total_pnl"] == -5.0


# ---------------------------------------------------------------------------
# TradeRecord.to_dict
# ---------------------------------------------------------------------------

class TestTradeRecord:
    def test_to_dict_normal(self) -> None:
        rec = TradeRecord(
            trade_id="t-1",
            signal_id="sig-1",
            signal_type="smc_fvg",
            direction="long",
            entry_price=21000.0,
            exit_price=21050.0,
            stop_loss=20950.0,
            take_profit=21100.0,
            pnl=10.0,
            is_win=True,
            exit_reason="tp_hit",
            entry_time="2026-04-01T10:00:00",
            exit_time="2026-04-01T10:30:00",
            hold_duration_minutes=30.0,
            regime="trending",
            context_key="ctx-1",
            volatility_percentile=0.75,
            volume_percentile=0.6,
            features_json='{"rsi": 55.0}',
            created_at="2026-04-01T10:30:00",
        )
        d = rec.to_dict()
        assert d["trade_id"] == "t-1"
        assert d["features"] == {"rsi": 55.0}

    def test_to_dict_none_features(self) -> None:
        rec = TradeRecord(
            trade_id="t-1", signal_id="sig-1", signal_type="x", direction="long",
            entry_price=100.0, exit_price=110.0, stop_loss=None, take_profit=None,
            pnl=10.0, is_win=True, exit_reason=None,
            entry_time="t", exit_time="t", hold_duration_minutes=None,
            regime=None, context_key=None, volatility_percentile=None,
            volume_percentile=None, features_json=None, created_at="t",
        )
        assert rec.to_dict()["features"] == {}

    def test_to_dict_invalid_features_json(self) -> None:
        rec = TradeRecord(
            trade_id="t-1", signal_id="sig-1", signal_type="x", direction="long",
            entry_price=100.0, exit_price=110.0, stop_loss=None, take_profit=None,
            pnl=10.0, is_win=True, exit_reason=None,
            entry_time="t", exit_time="t", hold_duration_minutes=None,
            regime=None, context_key=None, volatility_percentile=None,
            volume_percentile=None, features_json="not json", created_at="t",
        )
        assert rec.to_dict()["features"] == {}

    def test_to_dict_non_dict_features_json(self) -> None:
        rec = TradeRecord(
            trade_id="t-1", signal_id="sig-1", signal_type="x", direction="long",
            entry_price=100.0, exit_price=110.0, stop_loss=None, take_profit=None,
            pnl=10.0, is_win=True, exit_reason=None,
            entry_time="t", exit_time="t", hold_duration_minutes=None,
            regime=None, context_key=None, volatility_percentile=None,
            volume_percentile=None, features_json="[1,2,3]", created_at="t",
        )
        assert rec.to_dict()["features"] == {}


# ---------------------------------------------------------------------------
# Static / utility methods
# ---------------------------------------------------------------------------

class TestStaticMethods:
    def test_json_dumps_none(self) -> None:
        result = TradeDatabase._json_dumps(None)
        assert result == "{}"

    def test_json_dumps_normal(self) -> None:
        result = TradeDatabase._json_dumps({"key": "value"})
        assert '"key"' in result

    def test_json_loads_none(self) -> None:
        assert TradeDatabase._json_loads(None) == {}

    def test_json_loads_empty(self) -> None:
        assert TradeDatabase._json_loads("") == {}

    def test_json_loads_valid(self) -> None:
        assert TradeDatabase._json_loads('{"a": 1}') == {"a": 1}

    def test_json_loads_invalid(self) -> None:
        assert TradeDatabase._json_loads("not json") == {}

    def test_json_loads_non_dict(self) -> None:
        assert TradeDatabase._json_loads("[1,2]") == {}

    def test_now_et_format(self) -> None:
        result = TradeDatabase._now_et()
        # Should be YYYY-MM-DDTHH:MM:SS format
        assert len(result) == 19
        assert result[4] == "-"
        assert result[10] == "T"
