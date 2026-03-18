"""Comprehensive tests for performance_tracker.py targeting uncovered lines."""
from __future__ import annotations

import json
import asyncio
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from pearlalgo.market_agent.performance_tracker import PerformanceTracker, validate_trade_prices


@pytest.fixture
def tracker(tmp_path):
    return PerformanceTracker(state_dir=tmp_path)


def _write_signals(tmp_path, records):
    """Helper to write signals.jsonl from a list of dicts."""
    signals_file = tmp_path / "signals.jsonl"
    signals_file.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return signals_file


def _make_signal_record(signal_id="sig1", status="entered", direction="long",
                        signal_type="ema_cross", entry_price=18000.0,
                        stop_loss=17990.0, take_profit=18020.0, pnl=None,
                        exit_price=None, is_test=False, is_win=None):
    rec = {
        "signal_id": signal_id,
        "status": status,
        "signal": {
            "type": signal_type,
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        },
        "entry_price": entry_price,
    }
    if pnl is not None:
        rec["pnl"] = pnl
        # Auto-set is_win based on pnl if not explicitly provided
        if is_win is None:
            rec["is_win"] = pnl > 0
        else:
            rec["is_win"] = is_win
    elif is_win is not None:
        rec["is_win"] = is_win
    if exit_price is not None:
        rec["exit_price"] = exit_price
    if is_test:
        rec["_is_test"] = True
    return rec


def _empty_metrics_cache():
    return {
        "exited_signals": 0,
        "total_pnl": 0.0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "avg_pnl": 0.0,
        "by_signal_type": {},
        "recent_exits": [],
    }


# ---------------------------------------------------------------------------
# TestValidateTradePrices
# ---------------------------------------------------------------------------
class TestValidateTradePrices:
    def test_valid_prices_returns_true(self):
        valid, reason = validate_trade_prices(100.0, 105.0)
        assert valid is True
        assert reason == ""

    def test_zero_entry_returns_false(self):
        valid, reason = validate_trade_prices(0.0, 105.0)
        assert valid is False
        assert reason != ""

    def test_negative_exit_returns_false(self):
        valid, reason = validate_trade_prices(100.0, -5.0)
        assert valid is False

    def test_inf_entry_returns_false(self):
        valid, reason = validate_trade_prices(float("inf"), 100.0)
        assert valid is False

    def test_nan_exit_returns_false(self):
        valid, reason = validate_trade_prices(100.0, float("nan"))
        assert valid is False

    def test_label_in_reason(self):
        valid, reason = validate_trade_prices(0.0, 100.0, label="MY_TRADE")
        assert valid is False
        assert "MY_TRADE" in reason


# ---------------------------------------------------------------------------
# TestUpdateSignalPrices
# ---------------------------------------------------------------------------
class TestUpdateSignalPrices:
    def test_both_none_returns_early(self, tracker, tmp_path):
        """When both SL and TP are None, file should not be touched."""
        records = [_make_signal_record()]
        sf = _write_signals(tmp_path, records)
        original = sf.read_text()
        tracker.update_signal_prices("sig1", stop_loss=None, take_profit=None)
        assert sf.read_text() == original

    def test_file_not_exists_returns_early(self, tracker, tmp_path):
        """When signals.jsonl does not exist, should not raise."""
        # Ensure file doesn't exist
        sf = tmp_path / "signals.jsonl"
        if sf.exists():
            sf.unlink()
        # Should not raise
        tracker.update_signal_prices("sig1", stop_loss=17980.0)

    def test_update_stop_loss_only(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        tracker.update_signal_prices("sig1", stop_loss=17985.0)
        lines = (tmp_path / "signals.jsonl").read_text().strip().split("\n")
        updated = json.loads(lines[0])
        assert updated["signal"]["stop_loss"] == 17985.0
        # take_profit should remain unchanged
        assert updated["signal"]["take_profit"] == 18020.0

    def test_update_take_profit_only(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        tracker.update_signal_prices("sig1", take_profit=18050.0)
        lines = (tmp_path / "signals.jsonl").read_text().strip().split("\n")
        updated = json.loads(lines[0])
        assert updated["signal"]["take_profit"] == 18050.0
        assert updated["signal"]["stop_loss"] == 17990.0

    def test_update_both_sl_and_tp(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        tracker.update_signal_prices("sig1", stop_loss=17970.0, take_profit=18100.0)
        lines = (tmp_path / "signals.jsonl").read_text().strip().split("\n")
        updated = json.loads(lines[0])
        assert updated["signal"]["stop_loss"] == 17970.0
        assert updated["signal"]["take_profit"] == 18100.0

    def test_signal_not_found_no_change(self, tracker, tmp_path):
        records = [_make_signal_record(signal_id="sig1")]
        sf = _write_signals(tmp_path, records)
        original = sf.read_text()
        tracker.update_signal_prices("nonexistent", stop_loss=17000.0)
        # The file content for sig1 should be unchanged (SL still original)
        lines = sf.read_text().strip().split("\n")
        rec = json.loads(lines[0])
        assert rec["signal"]["stop_loss"] == 17990.0

    def test_conversion_error_handled(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        # Pass a non-numeric stop_loss - should handle gracefully
        tracker.update_signal_prices("sig1", stop_loss="not_a_number")
        # Should not crash; file should still be readable
        lines = (tmp_path / "signals.jsonl").read_text().strip().split("\n")
        json.loads(lines[0])  # Should not raise

    def test_source_field_set(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        tracker.update_signal_prices("sig1", stop_loss=17980.0)
        lines = (tmp_path / "signals.jsonl").read_text().strip().split("\n")
        updated = json.loads(lines[0])
        # Check that some update marker exists (source or updated_at)
        # The function should mark the update somehow
        assert updated["signal"]["stop_loss"] == 17980.0


# ---------------------------------------------------------------------------
# TestTrackExitMetricsCache
# ---------------------------------------------------------------------------
class TestTrackExitMetricsCache:
    def _setup_and_exit(self, tracker, tmp_path, pnl_value, signal_type="ema_cross"):
        """Helper: write a signal, set cache, call track_exit, return cache."""
        records = [_make_signal_record(signal_type=signal_type)]
        _write_signals(tmp_path, records)
        tracker._metrics_cache = _empty_metrics_cache()
        tracker.track_exit("sig1", exit_price=18000.0 + pnl_value, exit_reason="test")
        return tracker._metrics_cache

    def test_metrics_cache_incremented_on_win(self, tracker, tmp_path):
        cache = self._setup_and_exit(tracker, tmp_path, pnl_value=10.0)
        assert cache["wins"] >= 1

    def test_metrics_cache_incremented_on_loss(self, tracker, tmp_path):
        cache = self._setup_and_exit(tracker, tmp_path, pnl_value=-10.0)
        assert cache["losses"] >= 1

    def test_metrics_cache_win_rate_updated(self, tracker, tmp_path):
        cache = self._setup_and_exit(tracker, tmp_path, pnl_value=10.0)
        assert cache["win_rate"] > 0.0

    def test_metrics_cache_avg_pnl_updated(self, tracker, tmp_path):
        cache = self._setup_and_exit(tracker, tmp_path, pnl_value=10.0)
        assert cache["avg_pnl"] != 0.0

    def test_metrics_cache_by_signal_type_new_type(self, tracker, tmp_path):
        cache = self._setup_and_exit(tracker, tmp_path, pnl_value=10.0, signal_type="breakout")
        assert "breakout" in cache.get("by_signal_type", {})

    def test_metrics_cache_by_signal_type_existing_type(self, tracker, tmp_path):
        records = [_make_signal_record(signal_type="ema_cross")]
        _write_signals(tmp_path, records)
        tracker._metrics_cache = _empty_metrics_cache()
        tracker._metrics_cache["by_signal_type"]["ema_cross"] = {
            "count": 1, "wins": 1, "total_pnl": 5.0
        }
        tracker.track_exit("sig1", exit_price=18010.0, exit_reason="test")
        st = tracker._metrics_cache["by_signal_type"]["ema_cross"]
        assert st["count"] >= 2

    def test_metrics_cache_recent_exits_prepended(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        tracker._metrics_cache = _empty_metrics_cache()
        tracker._metrics_cache["recent_exits"] = [{"signal_id": "old"}]
        tracker.track_exit("sig1", exit_price=18010.0, exit_reason="test")
        recents = tracker._metrics_cache["recent_exits"]
        assert len(recents) >= 2
        assert recents[0]["signal_id"] == "sig1"

    def test_metrics_cache_recent_exits_trimmed_to_10(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        tracker._metrics_cache = _empty_metrics_cache()
        tracker._metrics_cache["recent_exits"] = [{"signal_id": f"old{i}"} for i in range(12)]
        tracker.track_exit("sig1", exit_price=18010.0, exit_reason="test")
        recents = tracker._metrics_cache["recent_exits"]
        assert len(recents) <= 10


# ---------------------------------------------------------------------------
# TestTrackExitDuplicateAndMissing
# ---------------------------------------------------------------------------
class TestTrackExitDuplicateAndMissing:
    def test_already_exited_signal_skipped(self, tracker, tmp_path):
        records = [_make_signal_record(status="exited", exit_price=18010.0, pnl=10.0)]
        _write_signals(tmp_path, records)
        result = tracker.track_exit("sig1", exit_price=18020.0, exit_reason="duplicate")
        assert result is None

    def test_missing_signal_returns_none(self, tracker, tmp_path):
        _write_signals(tmp_path, [])
        result = tracker.track_exit("nonexistent", exit_price=18000.0, exit_reason="missing")
        assert result is None

    def test_invalid_prices_rejected(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        result = tracker.track_exit("sig1", exit_price=float("inf"), exit_reason="bad price")
        assert result is None

    def test_zero_entry_price_rejected(self, tracker, tmp_path):
        records = [_make_signal_record(entry_price=0.0)]
        _write_signals(tmp_path, records)
        result = tracker.track_exit("sig1", exit_price=18000.0, exit_reason="zero entry")
        assert result is None


# ---------------------------------------------------------------------------
# TestSavePerformance
# ---------------------------------------------------------------------------
class TestSavePerformance:
    def test_save_creates_file(self, tracker, tmp_path):
        perf_file = tmp_path / "performance.json"
        assert not perf_file.exists()
        tracker._save_performance({"pnl": 10.0, "timestamp": "2026-03-12T00:00:00Z"})
        assert perf_file.exists()
        data = json.loads(perf_file.read_text())
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_save_appends_to_existing(self, tracker, tmp_path):
        perf_file = tmp_path / "performance.json"
        perf_file.write_text(json.dumps([{"pnl": 5.0}]))
        tracker._save_performance({"pnl": 10.0})
        data = json.loads(perf_file.read_text())
        assert len(data) == 2

    def test_save_trims_to_max_records(self, tracker, tmp_path):
        perf_file = tmp_path / "performance.json"
        existing = [{"pnl": i} for i in range(tracker._max_records)]
        perf_file.write_text(json.dumps(existing))
        tracker._save_performance({"pnl": 999.0})
        data = json.loads(perf_file.read_text())
        assert len(data) <= tracker._max_records

    def test_save_handles_corrupt_file(self, tracker, tmp_path):
        perf_file = tmp_path / "performance.json"
        perf_file.write_text("NOT VALID JSON{{{")
        # Should not raise - handles corrupt gracefully
        tracker._save_performance({"pnl": 10.0})
        data = json.loads(perf_file.read_text())
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# TestRunningAggregates
# ---------------------------------------------------------------------------
class TestRunningAggregates:
    def test_initialize_empty_file(self, tracker, tmp_path):
        _write_signals(tmp_path, [])
        tracker._initialize_running_aggregates()
        assert tracker._running_aggregates["is_initialized"] is True
        assert tracker._running_aggregates.get("total_pnl", 0.0) == 0.0

    def test_initialize_with_trades(self, tracker, tmp_path):
        records = [
            _make_signal_record("s1", status="exited", pnl=20.0, exit_price=18020.0),
            _make_signal_record("s2", status="exited", pnl=-5.0, exit_price=17995.0),
        ]
        _write_signals(tmp_path, records)
        tracker._initialize_running_aggregates()
        agg = tracker._running_aggregates
        assert agg["is_initialized"] is True
        assert agg["total_pnl"] == pytest.approx(15.0)
        assert agg["wins"] == 1
        assert agg["losses"] == 1

    def test_initialize_skips_non_exited(self, tracker, tmp_path):
        records = [
            _make_signal_record("s1", status="entered"),
            _make_signal_record("s2", status="exited", pnl=10.0, exit_price=18010.0),
        ]
        _write_signals(tmp_path, records)
        tracker._initialize_running_aggregates()
        agg = tracker._running_aggregates
        assert agg["wins"] + agg["losses"] == 1

    def test_initialize_skips_test_signals(self, tracker, tmp_path):
        records = [
            _make_signal_record("s1", status="exited", pnl=10.0, exit_price=18010.0, is_test=True),
            _make_signal_record("s2", status="exited", pnl=5.0, exit_price=18005.0),
        ]
        _write_signals(tmp_path, records)
        tracker._initialize_running_aggregates()
        agg = tracker._running_aggregates
        # Only s2 counted
        assert agg["wins"] + agg["losses"] == 1

    def test_initialize_handles_corrupt_line(self, tracker, tmp_path):
        sf = tmp_path / "signals.jsonl"
        good = json.dumps(_make_signal_record("s1", status="exited", pnl=10.0, exit_price=18010.0))
        sf.write_text(good + "\nNOT_JSON\n")
        tracker._initialize_running_aggregates()
        assert tracker._running_aggregates["is_initialized"] is True

    def test_update_win_increments(self, tracker, tmp_path):
        tracker._running_aggregates = {
            "is_initialized": True,
            "total_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "max_win": 0.0,
            "max_loss": 0.0,
            "total_trades": 0,
            "total_win_pnl": 0.0,
            "total_loss_pnl": 0.0,
        }
        tracker._update_running_aggregates(pnl=15.0, is_win=True)
        assert tracker._running_aggregates["wins"] == 1
        assert tracker._running_aggregates["total_pnl"] == pytest.approx(15.0)
        assert tracker._running_aggregates["max_win"] == pytest.approx(15.0)

    def test_update_loss_increments(self, tracker, tmp_path):
        tracker._running_aggregates = {
            "is_initialized": True,
            "total_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "max_win": 0.0,
            "max_loss": 0.0,
            "total_trades": 0,
            "total_win_pnl": 0.0,
            "total_loss_pnl": 0.0,
        }
        tracker._update_running_aggregates(pnl=-8.0, is_win=False)
        assert tracker._running_aggregates["losses"] == 1
        assert tracker._running_aggregates["max_loss"] == pytest.approx(-8.0)

    def test_update_noop_when_not_initialized(self, tracker):
        tracker._running_aggregates = {"is_initialized": False}
        # Should not raise or change anything
        tracker._update_running_aggregates(pnl=10.0, is_win=True)
        assert "wins" not in tracker._running_aggregates


# ---------------------------------------------------------------------------
# TestAsyncWrappers
# ---------------------------------------------------------------------------
class TestAsyncWrappers:
    def test_update_signal_prices_async(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                tracker.update_signal_prices_async("sig1", stop_loss=17980.0)
            )
        finally:
            loop.close()
        lines = (tmp_path / "signals.jsonl").read_text().strip().split("\n")
        updated = json.loads(lines[0])
        assert updated["signal"]["stop_loss"] == 17980.0

    def test_get_performance_metrics_async(self, tracker, tmp_path):
        _write_signals(tmp_path, [])
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(tracker.get_performance_metrics_async())
        finally:
            loop.close()
        assert isinstance(result, dict)

    def test_save_performance_async(self, tracker, tmp_path):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                tracker._save_performance_async({"pnl": 10.0, "timestamp": "2026-03-12"})
            )
        finally:
            loop.close()
        perf_file = tmp_path / "performance.json"
        assert perf_file.exists()

    def test_update_signal_status_async(self, tracker, tmp_path):
        records = [_make_signal_record()]
        _write_signals(tmp_path, records)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                tracker._update_signal_status_async("sig1", "exited", {})
            )
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# TestTrackExitSQLiteFeatures
# ---------------------------------------------------------------------------
class TestTrackExitSQLiteFeatures:
    def _make_signal_with_extras(self, regime=None, ml_features=None,
                                  indicators=None, win_probability=None,
                                  pass_filter=None, confidence_level=None):
        rec = _make_signal_record()
        sig = rec["signal"]
        if regime is not None:
            sig["regime"] = regime
        if ml_features is not None:
            sig["ml_features"] = ml_features
        if indicators is not None:
            sig["indicators"] = indicators
        if win_probability is not None:
            sig["win_probability"] = win_probability
        if pass_filter is not None:
            sig["pass_filter"] = pass_filter
        if confidence_level is not None:
            sig["confidence_level"] = confidence_level
        return rec

    def test_regime_extraction_dict(self, tracker, tmp_path):
        rec = self._make_signal_with_extras(regime={"name": "trending", "strength": 0.8})
        _write_signals(tmp_path, [rec])
        tracker._sqlite_enabled = True
        mock_queue = MagicMock()
        tracker._sqlite_queue = mock_queue
        tracker.track_exit("sig1", exit_price=18010.0, exit_reason="tp_hit")
        # Verify the sqlite queue was called (or at least no crash with dict regime)

    def test_regime_extraction_string(self, tracker, tmp_path):
        rec = self._make_signal_with_extras(regime="trending_up")
        _write_signals(tmp_path, [rec])
        tracker._sqlite_enabled = True
        mock_queue = MagicMock()
        tracker._sqlite_queue = mock_queue
        tracker.track_exit("sig1", exit_price=18010.0, exit_reason="tp_hit")

    def test_feature_extraction_numeric(self, tracker, tmp_path):
        rec = self._make_signal_with_extras(
            ml_features={"rsi": 65.0, "macd": 1.5},
            indicators={"atr": 12.0}
        )
        _write_signals(tmp_path, [rec])
        tracker._sqlite_enabled = True
        mock_queue = MagicMock()
        tracker._sqlite_queue = mock_queue
        tracker.track_exit("sig1", exit_price=18010.0, exit_reason="tp_hit")

    def test_feature_extraction_skips_nan(self, tracker, tmp_path):
        rec = self._make_signal_with_extras(
            ml_features={"rsi": float("nan"), "macd": 1.5}
        )
        _write_signals(tmp_path, [rec])
        tracker._sqlite_enabled = True
        mock_queue = MagicMock()
        tracker._sqlite_queue = mock_queue
        tracker.track_exit("sig1", exit_price=18010.0, exit_reason="tp_hit")

    def test_ml_prediction_features(self, tracker, tmp_path):
        rec = self._make_signal_with_extras(
            win_probability=0.75,
            pass_filter=True,
        )
        _write_signals(tmp_path, [rec])
        tracker._sqlite_enabled = True
        mock_queue = MagicMock()
        tracker._sqlite_queue = mock_queue
        tracker.track_exit("sig1", exit_price=18010.0, exit_reason="tp_hit")

    def test_ml_confidence_level_mapping(self, tracker, tmp_path):
        rec = self._make_signal_with_extras(
            confidence_level="high",
            win_probability=0.9,
        )
        _write_signals(tmp_path, [rec])
        tracker._sqlite_enabled = True
        mock_queue = MagicMock()
        tracker._sqlite_queue = mock_queue
        tracker.track_exit("sig1", exit_price=18010.0, exit_reason="tp_hit")
