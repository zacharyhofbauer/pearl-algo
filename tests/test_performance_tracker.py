"""
Unit tests for PerformanceTracker.

Covers:
- record_trade() / track_signal_generated(): recording winning trade, losing trade, P&L tracking
- track_exit(): P&L calculation for long win, long loss, short win, short loss
- load_performance_data(): loading from file, empty file, missing file
- get_performance_metrics(): rolling lookback, win rate, by-type breakdown
- Persistence: data survives save/load cycle
- Edge cases: first day (no history), no trades, test signals skipped
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pearlalgo.utils.paths import get_utc_timestamp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_performance_tracker(state_dir: Path):
    """Create a PerformanceTracker pointed at state_dir with config mocked."""
    with patch("pearlalgo.market_agent.performance_tracker.load_service_config") as mock_cfg:
        mock_cfg.return_value = {
            "storage": {"sqlite_enabled": False},
            "data": {"performance_history_limit": 1000},
            "performance": {"max_records": 1000, "default_lookback_days": 7},
        }
        from pearlalgo.market_agent.performance_tracker import PerformanceTracker
        return PerformanceTracker(state_dir=state_dir, state_manager=None)


def _make_signal(
    signal_type: str = "momentum",
    direction: str = "long",
    entry_price: float = 17500.0,
    stop_loss: float = 17480.0,
    take_profit: float = 17540.0,
    tick_value: float = 2.0,
    position_size: float = 1.0,
    **extra,
) -> dict:
    """Build a minimal signal dict."""
    sig = {
        "type": signal_type,
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "tick_value": tick_value,
        "position_size": position_size,
        "confidence": 0.75,
        "timestamp": get_utc_timestamp(),
    }
    sig.update(extra)
    return sig


def _write_signal_record(signals_file: Path, signal_id: str, signal: dict, status: str = "entered", entry_time: str | None = None) -> None:
    """Write a signal record directly to signals.jsonl."""
    record = {
        "signal_id": signal_id,
        "timestamp": get_utc_timestamp(),
        "status": status,
        "signal": signal,
    }
    if entry_time:
        record["entry_time"] = entry_time
    with open(signals_file, "a") as f:
        f.write(json.dumps(record) + "\n")


# ===================================================================
# track_signal_generated
# ===================================================================

class TestTrackSignalGenerated:
    """Tests for track_signal_generated()."""

    def test_generates_signal_id(self, tmp_path: Path) -> None:
        """track_signal_generated returns a non-empty signal_id."""
        pt = _make_performance_tracker(tmp_path)
        sig = _make_signal()

        signal_id = pt.track_signal_generated(sig)

        assert signal_id
        assert "momentum" in signal_id

    def test_writes_to_signals_file(self, tmp_path: Path) -> None:
        """Without state_manager, writes directly to signals.jsonl."""
        pt = _make_performance_tracker(tmp_path)
        sig = _make_signal()

        pt.track_signal_generated(sig)

        assert pt.signals_file.exists()
        lines = pt.signals_file.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["status"] == "generated"

    def test_track_signal_generated_skips_test_flagged_signals(self, tmp_path: Path) -> None:
        """Signals with _is_test=True return empty string and are not persisted."""
        pt = _make_performance_tracker(tmp_path)
        sig = _make_signal(_is_test=True)

        signal_id = pt.track_signal_generated(sig)

        assert signal_id == ""
        if pt.signals_file.exists():
            assert pt.signals_file.read_text().strip() == ""

    def test_delegates_to_state_manager(self, tmp_path: Path) -> None:
        """When state_manager is provided, delegates to save_signal."""
        pt = _make_performance_tracker(tmp_path)
        mock_sm = MagicMock()
        pt.state_manager = mock_sm
        sig = _make_signal()

        pt.track_signal_generated(sig)

        mock_sm.save_signal.assert_called_once()


class TestUpdateSignalExecutionMetadata:
    def test_updates_nested_signal_with_execution_ids(self, tmp_path: Path) -> None:
        pt = _make_performance_tracker(tmp_path)
        signal = _make_signal()
        signal_id = pt.track_signal_generated(signal)

        signal["_execution_status"] = "placed"
        signal["_execution_order_id"] = "ORD-100"
        signal["_execution_stop_order_id"] = "ORD-101"
        signal["_execution_take_profit_order_id"] = "ORD-102"

        pt.update_signal_execution_metadata(signal_id, signal)

        record = json.loads(pt.signals_file.read_text(encoding="utf-8").strip())
        nested = record["signal"]
        assert nested["_execution_status"] == "placed"
        assert nested["_execution_order_id"] == "ORD-100"
        assert nested["_execution_stop_order_id"] == "ORD-101"
        assert nested["_execution_take_profit_order_id"] == "ORD-102"


# ===================================================================
# track_exit – P&L calculations
# ===================================================================

class TestTrackExit:
    """Tests for track_exit() with various P&L scenarios."""

    def test_long_win(self, tmp_path: Path) -> None:
        """Long trade with exit above entry is a win."""
        pt = _make_performance_tracker(tmp_path)
        entry_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        sig = _make_signal(direction="long", entry_price=17500.0, tick_value=2.0, position_size=1.0)
        _write_signal_record(pt.signals_file, "long_win", sig, status="entered", entry_time=entry_time)

        result = pt.track_exit("long_win", exit_price=17540.0, exit_reason="take_profit")

        assert result is not None
        assert result["is_win"] is True
        assert result["pnl"] == 80.0  # (17540 - 17500) * 2.0 * 1.0
        assert result["direction"] == "long"
        assert result["exit_reason"] == "take_profit"

    def test_long_loss(self, tmp_path: Path) -> None:
        """Long trade with exit below entry is a loss."""
        pt = _make_performance_tracker(tmp_path)
        entry_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        sig = _make_signal(direction="long", entry_price=17500.0, tick_value=2.0, position_size=1.0)
        _write_signal_record(pt.signals_file, "long_loss", sig, status="entered", entry_time=entry_time)

        result = pt.track_exit("long_loss", exit_price=17480.0, exit_reason="stop_loss")

        assert result is not None
        assert result["is_win"] is False
        assert result["pnl"] == -40.0  # (17480 - 17500) * 2.0 * 1.0

    def test_short_win(self, tmp_path: Path) -> None:
        """Short trade with exit below entry is a win."""
        pt = _make_performance_tracker(tmp_path)
        entry_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        sig = _make_signal(direction="short", entry_price=17500.0, tick_value=2.0, position_size=1.0)
        _write_signal_record(pt.signals_file, "short_win", sig, status="entered", entry_time=entry_time)

        result = pt.track_exit("short_win", exit_price=17460.0, exit_reason="take_profit")

        assert result is not None
        assert result["is_win"] is True
        assert result["pnl"] == 80.0  # (17500 - 17460) * 2.0 * 1.0

    def test_short_loss(self, tmp_path: Path) -> None:
        """Short trade with exit above entry is a loss."""
        pt = _make_performance_tracker(tmp_path)
        entry_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        sig = _make_signal(direction="short", entry_price=17500.0, tick_value=2.0, position_size=1.0)
        _write_signal_record(pt.signals_file, "short_loss", sig, status="entered", entry_time=entry_time)

        result = pt.track_exit("short_loss", exit_price=17520.0, exit_reason="stop_loss")

        assert result is not None
        assert result["is_win"] is False
        assert result["pnl"] == -40.0  # (17500 - 17520) * 2.0 * 1.0

    def test_exit_nonexistent_signal_returns_none(self, tmp_path: Path) -> None:
        """Exiting a signal that doesn't exist returns None."""
        pt = _make_performance_tracker(tmp_path)
        # Create empty signals file
        pt.signals_file.write_text("", encoding="utf-8")

        result = pt.track_exit("ghost_signal", exit_price=17500.0, exit_reason="manual")

        assert result is None

    def test_pnl_with_position_size(self, tmp_path: Path) -> None:
        """P&L scales with position_size."""
        pt = _make_performance_tracker(tmp_path)
        entry_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        sig = _make_signal(direction="long", entry_price=17500.0, tick_value=2.0, position_size=3.0)
        _write_signal_record(pt.signals_file, "size_test", sig, status="entered", entry_time=entry_time)

        result = pt.track_exit("size_test", exit_price=17510.0, exit_reason="take_profit")

        assert result is not None
        assert result["pnl"] == 60.0  # (17510 - 17500) * 2.0 * 3.0

    def test_hold_duration_calculated(self, tmp_path: Path) -> None:
        """Hold duration is calculated in minutes."""
        pt = _make_performance_tracker(tmp_path)
        entry_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        sig = _make_signal(direction="long", entry_price=17500.0)
        _write_signal_record(pt.signals_file, "hold_test", sig, status="entered", entry_time=entry_time)

        result = pt.track_exit("hold_test", exit_price=17510.0, exit_reason="take_profit")

        assert result is not None
        assert result["hold_duration_minutes"] is not None
        assert result["hold_duration_minutes"] >= 44.0  # Allow slight timing variance


# ===================================================================
# load_performance_data
# ===================================================================

class TestLoadPerformanceData:
    """Tests for load_performance_data()."""

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        """Non-existent performance.json returns empty list."""
        pt = _make_performance_tracker(tmp_path)
        result = pt.load_performance_data()
        assert result == []

    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        """Empty performance.json returns empty list."""
        pt = _make_performance_tracker(tmp_path)
        pt.performance_file.write_text("", encoding="utf-8")

        result = pt.load_performance_data()
        assert result == []

    def test_corrupt_file_returns_empty_list(self, tmp_path: Path) -> None:
        """Corrupt performance.json returns empty list."""
        pt = _make_performance_tracker(tmp_path)
        pt.performance_file.write_text("{{CORRUPT}}", encoding="utf-8")

        result = pt.load_performance_data()
        assert result == []

    def test_valid_file_returns_records(self, tmp_path: Path) -> None:
        """Valid performance.json returns list of records."""
        pt = _make_performance_tracker(tmp_path)
        records = [
            {"signal_id": "a", "pnl": 100.0, "is_win": True},
            {"signal_id": "b", "pnl": -50.0, "is_win": False},
        ]
        pt.performance_file.write_text(json.dumps(records), encoding="utf-8")

        result = pt.load_performance_data()
        assert len(result) == 2
        assert result[0]["pnl"] == 100.0

    def test_non_list_returns_empty(self, tmp_path: Path) -> None:
        """performance.json with a top-level dict returns empty list."""
        pt = _make_performance_tracker(tmp_path)
        pt.performance_file.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

        result = pt.load_performance_data()
        assert result == []


# ===================================================================
# Persistence: save/load cycle
# ===================================================================

class TestPerformancePersistence:
    """Tests for performance data persistence across save/load."""

    def test_track_exit_saves_to_performance_file(self, tmp_path: Path) -> None:
        """track_exit writes a record to performance.json."""
        pt = _make_performance_tracker(tmp_path)
        entry_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        sig = _make_signal(direction="long", entry_price=17500.0)
        _write_signal_record(pt.signals_file, "persist_1", sig, status="entered", entry_time=entry_time)

        pt.track_exit("persist_1", exit_price=17520.0, exit_reason="take_profit")

        data = pt.load_performance_data()
        assert len(data) == 1
        assert data[0]["signal_id"] == "persist_1"
        assert data[0]["pnl"] == 40.0

    def test_multiple_trades_persist(self, tmp_path: Path) -> None:
        """Multiple exits accumulate in performance.json."""
        pt = _make_performance_tracker(tmp_path)

        for i in range(3):
            entry_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            sig = _make_signal(direction="long", entry_price=17500.0)
            _write_signal_record(pt.signals_file, f"multi_{i}", sig, status="entered", entry_time=entry_time)
            pt.track_exit(f"multi_{i}", exit_price=17510.0, exit_reason="take_profit")

        data = pt.load_performance_data()
        assert len(data) == 3

    def test_data_survives_reload(self, tmp_path: Path) -> None:
        """Performance data survives creating a new tracker instance."""
        pt1 = _make_performance_tracker(tmp_path)
        entry_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        sig = _make_signal(direction="long", entry_price=17500.0)
        _write_signal_record(pt1.signals_file, "survive_1", sig, status="entered", entry_time=entry_time)
        pt1.track_exit("survive_1", exit_price=17520.0, exit_reason="take_profit")

        # Create a fresh tracker pointing at the same directory
        pt2 = _make_performance_tracker(tmp_path)
        data = pt2.load_performance_data()

        assert len(data) == 1
        assert data[0]["signal_id"] == "survive_1"


# ===================================================================
# get_performance_metrics
# ===================================================================

class TestGetPerformanceMetrics:
    """Tests for get_performance_metrics()."""

    def test_no_signals_returns_zeros(self, tmp_path: Path) -> None:
        """With no signals, all metrics are zero."""
        pt = _make_performance_tracker(tmp_path)
        metrics = pt.get_performance_metrics()

        assert metrics["total_signals"] == 0
        assert metrics["exited_signals"] == 0
        assert metrics["wins"] == 0
        assert metrics["losses"] == 0
        assert metrics["win_rate"] == 0.0
        assert metrics["total_pnl"] == 0.0

    def test_no_exited_signals(self, tmp_path: Path) -> None:
        """Generated but not exited signals have zero exit metrics."""
        pt = _make_performance_tracker(tmp_path)
        sig = _make_signal()
        _write_signal_record(pt.signals_file, "gen_only", sig, status="generated")

        metrics = pt.get_performance_metrics()
        assert metrics["total_signals"] == 1
        assert metrics["exited_signals"] == 0

    def test_win_rate_calculation(self, tmp_path: Path) -> None:
        """Win rate is calculated correctly from exited signals."""
        pt = _make_performance_tracker(tmp_path)

        # Write 3 exited signals: 2 wins, 1 loss
        for i, (is_win, pnl) in enumerate([(True, 100.0), (True, 50.0), (False, -30.0)]):
            sig = _make_signal()
            record = {
                "signal_id": f"wr_{i}",
                "timestamp": get_utc_timestamp(),
                "status": "exited",
                "pnl": pnl,
                "is_win": is_win,
                "exit_time": get_utc_timestamp(),
                "exit_reason": "take_profit" if is_win else "stop_loss",
                "signal": sig,
            }
            with open(pt.signals_file, "a") as f:
                f.write(json.dumps(record) + "\n")

        metrics = pt.get_performance_metrics()
        assert metrics["exited_signals"] == 3
        assert metrics["wins"] == 2
        assert metrics["losses"] == 1
        assert abs(metrics["win_rate"] - 2 / 3) < 0.01
        assert metrics["total_pnl"] == 120.0

    def test_by_signal_type_breakdown(self, tmp_path: Path) -> None:
        """Metrics are broken down by signal type."""
        pt = _make_performance_tracker(tmp_path)

        for i, (sig_type, is_win, pnl) in enumerate([
            ("momentum", True, 100.0),
            ("momentum", False, -50.0),
            ("reversal", True, 200.0),
        ]):
            sig = _make_signal(signal_type=sig_type)
            record = {
                "signal_id": f"bt_{i}",
                "timestamp": get_utc_timestamp(),
                "status": "exited",
                "pnl": pnl,
                "is_win": is_win,
                "exit_time": get_utc_timestamp(),
                "exit_reason": "take_profit",
                "signal": sig,
            }
            with open(pt.signals_file, "a") as f:
                f.write(json.dumps(record) + "\n")

        metrics = pt.get_performance_metrics()
        by_type = metrics["by_signal_type"]
        assert "momentum" in by_type
        assert by_type["momentum"]["count"] == 2
        assert by_type["momentum"]["wins"] == 1
        assert "reversal" in by_type
        assert by_type["reversal"]["count"] == 1

    def test_lookback_days_filter(self, tmp_path: Path) -> None:
        """Signals older than lookback window are excluded."""
        pt = _make_performance_tracker(tmp_path)

        # Write one recent and one old signal
        recent_ts = get_utc_timestamp()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        for sig_id, ts, pnl in [("recent", recent_ts, 100.0), ("old", old_ts, 200.0)]:
            sig = _make_signal()
            record = {
                "signal_id": sig_id,
                "timestamp": ts,
                "status": "exited",
                "pnl": pnl,
                "is_win": True,
                "exit_time": ts,
                "exit_reason": "take_profit",
                "signal": sig,
            }
            with open(pt.signals_file, "a") as f:
                f.write(json.dumps(record) + "\n")

        # Default lookback is 7 days
        metrics = pt.get_performance_metrics(days=7)
        assert metrics["exited_signals"] == 1  # Only the recent one
        assert metrics["total_pnl"] == 100.0

    def test_performance_metrics_excludes_test_flagged_signals(self, tmp_path: Path) -> None:
        """Test signals (_is_test=True) are excluded from P&L metrics."""
        pt = _make_performance_tracker(tmp_path)

        # Write a normal exit and a test exit
        for sig_id, is_test, pnl in [("real", False, 100.0), ("test", True, 999.0)]:
            sig = _make_signal(_is_test=is_test)
            record = {
                "signal_id": sig_id,
                "timestamp": get_utc_timestamp(),
                "status": "exited",
                "pnl": pnl,
                "is_win": True,
                "exit_time": get_utc_timestamp(),
                "exit_reason": "take_profit",
                "signal": sig,
                "_is_test": is_test,
            }
            with open(pt.signals_file, "a") as f:
                f.write(json.dumps(record) + "\n")

        metrics = pt.get_performance_metrics()
        assert metrics["exited_signals"] == 1
        assert metrics["total_pnl"] == 100.0


# ===================================================================
# _get_signal_record
# ===================================================================

class TestGetSignalRecord:
    """Tests for _get_signal_record() internal method."""

    def test_finds_existing_signal(self, tmp_path: Path) -> None:
        """Returns the matching signal record."""
        pt = _make_performance_tracker(tmp_path)
        sig = _make_signal()
        _write_signal_record(pt.signals_file, "find_me", sig)

        result = pt._get_signal_record("find_me")
        assert result is not None
        assert result["signal_id"] == "find_me"

    def test_missing_signal_returns_none(self, tmp_path: Path) -> None:
        """Returns None when signal_id is not in the file."""
        pt = _make_performance_tracker(tmp_path)
        sig = _make_signal()
        _write_signal_record(pt.signals_file, "other", sig)

        result = pt._get_signal_record("nonexistent")
        assert result is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Returns None when signals file doesn't exist."""
        pt = _make_performance_tracker(tmp_path)
        result = pt._get_signal_record("anything")
        assert result is None


# ---------------------------------------------------------------------------
# signal_type root preference (append-only JSONL format)
# ---------------------------------------------------------------------------

class TestSignalTypeRootPreference:
    """Tests that get_performance_metrics prefers root-level signal_type over nested signal.type."""

    def test_signal_type_at_root_used(self, tmp_path: Path) -> None:
        """When signal_type is at root level (append-only format), it should be used."""
        pt = _make_performance_tracker(tmp_path)
        # First write an "entered" record (base), then an exited status_change
        base = {
            "signal_id": "sig_root_type",
            "status": "entered",
            "timestamp": get_utc_timestamp(),
            "signal": {"type": "momentum", "direction": "long", "entry_price": 17500},
            "entry_price": 17500,
            "entry_time": get_utc_timestamp(),
        }
        status_change = {
            "signal_id": "sig_root_type",
            "event": "status_change",
            "status": "exited",
            "timestamp": get_utc_timestamp(),  # Required for get_performance_metrics loading
            "signal_type": "momentum",
            "pnl": 50.0,
            "is_win": True,
            "exit_time": get_utc_timestamp(),
        }
        with open(pt.signals_file, "a") as f:
            f.write(json.dumps(base) + "\n")
            f.write(json.dumps(status_change) + "\n")

        result = pt.get_performance_metrics()
        assert "momentum" in result["by_signal_type"]

    def test_nested_signal_type_fallback(self, tmp_path: Path) -> None:
        """When signal_type is only under signal.type (legacy format), it should still work."""
        pt = _make_performance_tracker(tmp_path)
        record = {
            "signal_id": "sig_nested_type",
            "status": "exited",
            "timestamp": get_utc_timestamp(),
            "signal": {"type": "reversal", "direction": "short", "entry_price": 17600},
            "entry_price": 17600,
            "entry_time": get_utc_timestamp(),
            "exit_time": get_utc_timestamp(),
            "pnl": -30.0,
            "is_win": False,
        }
        with open(pt.signals_file, "a") as f:
            f.write(json.dumps(record) + "\n")

        result = pt.get_performance_metrics()
        assert "reversal" in result["by_signal_type"]


# ---------------------------------------------------------------------------
# _max_records trimming
# ---------------------------------------------------------------------------

class TestMaxRecordsTrimming:
    """Tests that performance.json is trimmed to _max_records."""

    def test_trims_old_records(self, tmp_path: Path) -> None:
        """When records exceed _max_records, oldest should be trimmed."""
        pt = _make_performance_tracker(tmp_path)
        pt._max_records = 3  # Set a low limit

        # Write 5 records (should keep only the last 3)
        for i in range(5):
            sig = _make_signal(entry_price=17500.0 + i)
            sig_id = f"sig_{i}"
            _write_signal_record(pt.signals_file, sig_id, sig, entry_time=f"2025-01-0{i+1}T14:00:00Z")
            pt.track_exit(
                signal_id=sig_id,
                exit_price=17500.0 + i + 10,
                exit_reason="take_profit",
            )

        # Read performance.json directly
        perf_data = json.loads(pt.performance_file.read_text())
        assert len(perf_data) == 3
        # The last 3 signals should be kept
        assert perf_data[0]["signal_id"] == "sig_2"
        assert perf_data[1]["signal_id"] == "sig_3"
        assert perf_data[2]["signal_id"] == "sig_4"
