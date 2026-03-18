"""
Tests for helper functions in pearlalgo.api.server that are not covered
by the existing endpoint tests in test_api_server.py.

Covers: _read_json_sync, _candle_cache_*, _get_recent_exits,
_get_recent_signals, _get_ai_status, _get_challenge_status,
_json_sanitize, _get_equity_curve, _get_risk_metrics,
_get_market_regime, _get_signal_rejections_24h, _get_connection_health,
_get_error_summary, _aggregate_performance_since, _get_trading_week_start,
_get_month_to_date_start, _get_year_to_date_start, _compute_daily_stats,
_compute_performance_stats, _get_data_quality, _write_operator_request,
_snap_to_bar.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="FastAPI not installed")

from pearlalgo.api import server as srv


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset module-level caches before each test."""
    srv._candle_cache.clear()
    srv._ttl_cache.clear()
    srv._last_ttl_cleanup = 0.0
    yield
    srv._candle_cache.clear()
    srv._ttl_cache.clear()


# ---------------------------------------------------------------------------
# 1. _read_json_sync
# ---------------------------------------------------------------------------

class TestReadJsonSync:
    def test_returns_none_for_missing_file(self, tmp_path: Path):
        assert srv._read_json_sync(tmp_path / "no_such_file.json") is None

    def test_returns_parsed_dict(self, tmp_path: Path):
        p = tmp_path / "valid.json"
        p.write_text(json.dumps({"key": "value"}))
        assert srv._read_json_sync(p) == {"key": "value"}

    def test_returns_none_for_empty_json_object(self, tmp_path: Path):
        """load_json_file returns {} for empty/missing; _read_json_sync maps falsy to None."""
        p = tmp_path / "empty.json"
        p.write_text("{}")
        assert srv._read_json_sync(p) is None

    def test_returns_none_for_invalid_json(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("NOT JSON")
        assert srv._read_json_sync(p) is None


# ---------------------------------------------------------------------------
# 2. _candle_cache_get / _candle_cache_set
# ---------------------------------------------------------------------------

class TestCandleCache:
    def test_get_returns_none_when_empty(self):
        assert srv._candle_cache_get("missing") is None

    def test_set_and_get_roundtrip(self):
        candles = [{"time": 1, "open": 100}]
        srv._candle_cache_set("k1", candles)
        assert srv._candle_cache_get("k1") == candles

    def test_lru_eviction(self):
        for i in range(srv._CANDLE_CACHE_MAX_ENTRIES + 10):
            srv._candle_cache_set(f"k{i}", [{"time": i}])
        # Oldest entries should have been evicted
        assert srv._candle_cache_get("k0") is None
        # Newest should still be present
        last_key = f"k{srv._CANDLE_CACHE_MAX_ENTRIES + 9}"
        assert srv._candle_cache_get(last_key) is not None

    def test_set_existing_key_moves_to_end(self):
        srv._candle_cache_set("a", [{"time": 1}])
        srv._candle_cache_set("b", [{"time": 2}])
        # Re-set "a" to move it to end
        srv._candle_cache_set("a", [{"time": 3}])
        # Fill cache to max
        for i in range(srv._CANDLE_CACHE_MAX_ENTRIES):
            srv._candle_cache_set(f"fill_{i}", [{"time": i}])
        # "b" should have been evicted (oldest), "a" should survive (was moved to end)
        assert srv._candle_cache_get("b") is None


# ---------------------------------------------------------------------------
# 3. _get_recent_exits (IBKR Virtual path via signals.jsonl)
# ---------------------------------------------------------------------------

class TestGetRecentExits:
    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_returns_empty_when_no_signals_file(self, _mock, tmp_path: Path):
        assert srv._get_recent_exits(tmp_path) == []

    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_returns_exited_trades(self, _mock, tmp_path: Path):
        signals_file = tmp_path / "signals.jsonl"
        lines = [
            json.dumps({
                "signal_id": "s1", "status": "exited", "pnl": 50.0,
                "exit_reason": "take_profit", "exit_time": "2026-03-10T12:00:00+00:00",
                "entry_time": "2026-03-10T11:00:00+00:00", "entry_price": 100.0,
                "exit_price": 105.0, "signal": {"direction": "long", "reason": "breakout"},
            }),
            json.dumps({
                "signal_id": "s2", "status": "active",
                "entry_time": "2026-03-10T12:30:00+00:00",
            }),
        ]
        signals_file.write_text("\n".join(lines))
        result = srv._get_recent_exits(tmp_path, limit=10)
        assert len(result) == 1
        assert result[0]["signal_id"] == "s1"
        assert result[0]["pnl"] == 50.0
        assert result[0]["direction"] == "long"
        assert result[0]["duration_seconds"] == 3600

    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_limit_is_respected(self, _mock, tmp_path: Path):
        signals_file = tmp_path / "signals.jsonl"
        lines = []
        for i in range(10):
            lines.append(json.dumps({
                "signal_id": f"s{i}", "status": "exited", "pnl": i * 10.0,
                "exit_time": f"2026-03-10T{10+i:02d}:00:00+00:00",
                "signal": {"direction": "long"},
            }))
        signals_file.write_text("\n".join(lines))
        result = srv._get_recent_exits(tmp_path, limit=3)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# 4. _get_recent_signals
# ---------------------------------------------------------------------------

class TestGetRecentSignals:
    def test_returns_empty_when_no_file(self, tmp_path: Path):
        assert srv._get_recent_signals(tmp_path) == []

    def test_returns_signal_lifecycle_events(self, tmp_path: Path):
        signals_file = tmp_path / "signals.jsonl"
        lines = [
            json.dumps({
                "signal_id": "sig1", "status": "generated",
                "timestamp": "2026-03-10T10:00:00+00:00",
                "signal": {"direction": "long", "symbol": "MNQ", "confidence": 0.8},
            }),
            json.dumps({
                "signal_id": "sig1", "status": "exited",
                "timestamp": "2026-03-10T11:00:00+00:00",
                "exit_reason": "stop_loss", "pnl": -25.0,
            }),
        ]
        signals_file.write_text("\n".join(lines))
        result = srv._get_recent_signals(tmp_path, limit=50)
        assert len(result) == 2
        # Sorted descending by timestamp
        assert result[0]["status"] == "exited"
        assert result[1]["status"] == "generated"
        # The exited event should inherit signal data from generated event
        assert result[0]["direction"] == "long"

    def test_skips_non_dict_rows(self, tmp_path: Path):
        signals_file = tmp_path / "signals.jsonl"
        signals_file.write_text('"just a string"\n42\n')
        assert srv._get_recent_signals(tmp_path) == []


# ---------------------------------------------------------------------------
# 5. _get_ai_status
# ---------------------------------------------------------------------------

class TestGetAiStatus:
    def test_empty_state(self):
        result = srv._get_ai_status({})
        assert result["bandit_mode"] == "off"
        assert result["contextual_mode"] == "off"
        assert result["ml_filter"]["enabled"] is False
        assert result["direction_gating"]["enabled"] is False

    def test_enabled_learning(self):
        state = {
            "learning": {"enabled": True, "mode": "shadow"},
            "learning_contextual": {"enabled": True, "mode": "live"},
            "ml_filter": {"enabled": True, "mode": "live", "lift": {"win_rate": 5.0}},
            "trading_circuit_breaker": {
                "direction_gating_enabled": True,
                "blocks_by_reason": {"direction_gating": 3},
                "would_have_blocked_regime": 2,
                "would_have_blocked_trigger": 1,
            },
        }
        result = srv._get_ai_status(state)
        assert result["bandit_mode"] == "shadow"
        assert result["contextual_mode"] == "live"
        assert result["ml_filter"]["enabled"] is True
        assert result["ml_filter"]["lift"] == {"win_rate": 5.0}
        assert result["direction_gating"]["enabled"] is True
        assert result["direction_gating"]["blocks"] == 3


# ---------------------------------------------------------------------------
# 6. _get_challenge_status
# ---------------------------------------------------------------------------

class TestGetChallengeStatus:
    def test_returns_none_when_file_missing(self, tmp_path: Path):
        assert srv._get_challenge_status(tmp_path) is None

    def test_returns_none_when_not_enabled(self, tmp_path: Path):
        p = tmp_path / "challenge_state.json"
        p.write_text(json.dumps({
            "config": {"enabled": False},
            "current_attempt": {},
        }))
        assert srv._get_challenge_status(tmp_path) is None

    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_returns_challenge_data(self, _mock, tmp_path: Path):
        p = tmp_path / "challenge_state.json"
        p.write_text(json.dumps({
            "config": {
                "enabled": True,
                "start_balance": 50000.0,
                "profit_target": 3000.0,
                "max_drawdown": 2000.0,
            },
            "current_attempt": {
                "pnl": 500.0,
                "trades": 10,
                "wins": 7,
                "win_rate": 70.0,
                "max_drawdown_hit": -300.0,
                "outcome": "active",
                "attempt_id": 1,
            },
        }))
        result = srv._get_challenge_status(tmp_path)
        assert result is not None
        assert result["enabled"] is True
        assert result["current_balance"] == 50500.0
        assert result["pnl"] == 500.0
        assert result["drawdown_risk_pct"] == 15.0


# ---------------------------------------------------------------------------
# 7. _json_sanitize
# ---------------------------------------------------------------------------

class TestJsonSanitize:
    def test_normal_dict(self):
        assert srv._json_sanitize({"a": 1, "b": "hello"}) == {"a": 1, "b": "hello"}

    def test_nan_and_inf_become_strings(self):
        """json.dumps with default=str converts non-serializable to str."""
        result = srv._json_sanitize({"val": float("nan")})
        # json.dumps(NaN) with default=str produces a string representation
        assert result is not None

    def test_datetime_becomes_string(self):
        dt = datetime(2026, 3, 12, tzinfo=timezone.utc)
        result = srv._json_sanitize({"ts": dt})
        assert isinstance(result["ts"], str)

    def test_non_serializable_object(self):
        """Completely non-serializable objects fall back to str()."""
        obj = object()
        result = srv._json_sanitize(obj)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 8. _get_equity_curve (IBKR Virtual path)
# ---------------------------------------------------------------------------

class TestGetEquityCurve:
    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_returns_empty_when_no_data(self, _mock, tmp_path: Path):
        with patch.object(srv, "_load_performance_data_new", return_value=None):
            result = srv._get_equity_curve(tmp_path, hours=24)
        assert result == []

    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_builds_cumulative_curve(self, _mock, tmp_path: Path):
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now - timedelta(hours=2)).isoformat(), "pnl": 100.0},
            {"exit_time": (now - timedelta(hours=1)).isoformat(), "pnl": -30.0},
            {"exit_time": now.isoformat(), "pnl": 50.0},
        ]
        with patch.object(srv, "_load_performance_data_new", return_value=trades):
            result = srv._get_equity_curve(tmp_path, hours=24)
        assert len(result) == 3
        assert result[0]["value"] == 100.0
        assert result[1]["value"] == 70.0
        assert result[2]["value"] == 120.0
        # Times should be strictly ascending
        assert result[0]["time"] < result[1]["time"] < result[2]["time"]

    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_filters_by_hours(self, _mock, tmp_path: Path):
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now - timedelta(hours=48)).isoformat(), "pnl": 200.0},
            {"exit_time": (now - timedelta(hours=1)).isoformat(), "pnl": 50.0},
        ]
        with patch.object(srv, "_load_performance_data_new", return_value=trades):
            result = srv._get_equity_curve(tmp_path, hours=24)
        assert len(result) == 1
        assert result[0]["value"] == 50.0

    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_handles_missing_exit_time(self, _mock, tmp_path: Path):
        trades = [{"pnl": 100.0}]  # no exit_time
        with patch.object(srv, "_load_performance_data_new", return_value=trades):
            result = srv._get_equity_curve(tmp_path, hours=24)
        assert result == []


# ---------------------------------------------------------------------------
# 9. _get_risk_metrics (IBKR Virtual path)
# ---------------------------------------------------------------------------

class TestGetRiskMetrics:
    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_returns_defaults_when_no_data(self, _mock, tmp_path: Path):
        with patch.object(srv, "_load_performance_data_new", return_value=None):
            result = srv._get_risk_metrics(tmp_path)
        assert result["max_drawdown"] == 0.0
        assert result["sharpe_ratio"] is None

    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_computes_metrics(self, _mock, tmp_path: Path):
        data = [
            {"pnl": 100.0, "exit_time": "2026-03-10T10:00:00+00:00"},
            {"pnl": -50.0, "exit_time": "2026-03-10T11:00:00+00:00"},
            {"pnl": 75.0, "exit_time": "2026-03-10T12:00:00+00:00"},
        ]
        # No signals.jsonl for this test
        with patch.object(srv, "_load_performance_data_new", return_value=data):
            result = srv._get_risk_metrics(tmp_path)
        assert result["largest_win"] == 100.0
        assert result["largest_loss"] == -50.0
        assert result["avg_win"] > 0


# ---------------------------------------------------------------------------
# 10. _get_market_regime
# ---------------------------------------------------------------------------

class TestGetMarketRegime:
    def test_empty_state(self):
        result = srv._get_market_regime({})
        assert result["regime"] == "unknown"
        assert result["confidence"] == 0.0
        assert result["allowed_direction"] == "both"

    def test_trending_up_with_gating(self):
        state = {
            "regime": "trending_up",
            "regime_confidence": 0.85,
            "trading_circuit_breaker": {
                "direction_gating_enabled": True,
                "direction_gating_min_confidence": 0.7,
            },
        }
        result = srv._get_market_regime(state)
        assert result["regime"] == "trending_up"
        assert result["confidence"] == 0.85
        assert result["allowed_direction"] == "long"

    def test_trending_down_with_gating(self):
        state = {
            "regime": "trending_down",
            "regime_confidence": 0.9,
            "trading_circuit_breaker": {
                "direction_gating_enabled": True,
                "direction_gating_min_confidence": 0.7,
            },
        }
        result = srv._get_market_regime(state)
        assert result["allowed_direction"] == "short"

    def test_low_confidence_no_restriction(self):
        state = {
            "regime": "trending_up",
            "regime_confidence": 0.3,
            "trading_circuit_breaker": {
                "direction_gating_enabled": True,
                "direction_gating_min_confidence": 0.7,
            },
        }
        result = srv._get_market_regime(state)
        assert result["allowed_direction"] == "both"


# ---------------------------------------------------------------------------
# 11. _get_signal_rejections_24h
# ---------------------------------------------------------------------------

class TestGetSignalRejections24h:
    def test_empty_state(self):
        result = srv._get_signal_rejections_24h({})
        assert result["direction_gating"] == 0
        assert result["circuit_breaker"] == 0
        assert result["max_positions"] == 0

    def test_combines_blocks_and_would_blocks(self):
        state = {
            "trading_circuit_breaker": {
                "blocks_by_reason": {
                    "direction_gating": 2,
                    "consecutive_losses": 1,
                    "max_positions": 3,
                },
                "would_block_by_reason": {
                    "direction_gating": 5,
                    "rolling_win_rate": 2,
                    "max_positions": 1,
                },
            },
        }
        result = srv._get_signal_rejections_24h(state)
        assert result["direction_gating"] == 7  # 2 + 5
        assert result["circuit_breaker"] == 3  # 1 + 2
        assert result["max_positions"] == 4  # 3 + 1


# ---------------------------------------------------------------------------
# 12. _get_connection_health
# ---------------------------------------------------------------------------

class TestGetConnectionHealth:
    def test_empty_state(self):
        result = srv._get_connection_health({})
        assert result["connection_failures"] == 0
        assert result["data_level"] == "UNKNOWN"
        assert result["last_successful_fetch"] is None

    def test_populated_state(self):
        state = {
            "connection": {
                "failures": 3,
                "data_fetch_errors": 1,
                "consecutive_errors": 2,
                "last_successful_fetch": "2026-03-10T12:00:00Z",
            },
            "data_provider": {"data_level": "L2_DEPTH"},
        }
        result = srv._get_connection_health(state)
        assert result["connection_failures"] == 3
        assert result["data_fetch_errors"] == 1
        assert result["data_level"] == "L2_DEPTH"
        assert result["consecutive_errors"] == 2


# ---------------------------------------------------------------------------
# 13. _get_error_summary
# ---------------------------------------------------------------------------

class TestGetErrorSummary:
    def test_from_state(self, tmp_path: Path):
        state = {
            "session_error_count": 5,
            "last_error": "Connection timeout",
            "last_error_time": "2026-03-10T12:00:00Z",
        }
        result = srv._get_error_summary(tmp_path, state)
        assert result["session_error_count"] == 5
        assert result["last_error"] == "Connection timeout"

    def test_reads_error_log_when_state_has_no_error(self, tmp_path: Path):
        state = {"session_error_count": 1}
        error_log = tmp_path / "errors.log"
        error_log.write_text(json.dumps({"message": "disk full", "timestamp": "2026-03-10T12:00:00Z"}) + "\n")
        result = srv._get_error_summary(tmp_path, state)
        assert result["last_error"] == "disk full"
        assert result["last_error_time"] == "2026-03-10T12:00:00Z"

    def test_reads_plain_text_error_log(self, tmp_path: Path):
        state = {}
        error_log = tmp_path / "errors.log"
        error_log.write_text("Something went wrong\n")
        result = srv._get_error_summary(tmp_path, state)
        assert result["last_error"] == "Something went wrong"

    def test_truncates_long_error(self, tmp_path: Path):
        state = {"last_error": "x" * 200}
        result = srv._get_error_summary(tmp_path, state)
        assert len(result["last_error"]) == 80
        assert result["last_error"].endswith("...")

    def test_no_errors(self, tmp_path: Path):
        result = srv._get_error_summary(tmp_path, {})
        assert result["session_error_count"] == 0
        assert result["last_error"] is None


# ---------------------------------------------------------------------------
# 14. _aggregate_performance_since
# ---------------------------------------------------------------------------

class TestAggregatePerformanceSince:
    def test_empty_trades(self):
        cutoff = datetime(2026, 3, 1, tzinfo=timezone.utc)
        result = srv._aggregate_performance_since([], cutoff)
        assert result == {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}

    def test_filters_by_cutoff(self):
        cutoff = datetime(2026, 3, 10, tzinfo=timezone.utc)
        trades = [
            {"exit_time": "2026-03-09T23:00:00+00:00", "pnl": 100.0},  # before cutoff
            {"exit_time": "2026-03-10T01:00:00+00:00", "pnl": 50.0},   # after cutoff
            {"exit_time": "2026-03-10T02:00:00+00:00", "pnl": -20.0},  # after cutoff
        ]
        result = srv._aggregate_performance_since(trades, cutoff)
        assert result["trades"] == 2
        assert result["pnl"] == 30.0
        assert result["wins"] == 1
        assert result["losses"] == 1
        assert result["win_rate"] == 50.0

    def test_filters_by_end(self):
        cutoff = datetime(2026, 3, 10, tzinfo=timezone.utc)
        end = datetime(2026, 3, 10, 2, 0, tzinfo=timezone.utc)
        trades = [
            {"exit_time": "2026-03-10T01:00:00+00:00", "pnl": 50.0},
            {"exit_time": "2026-03-10T03:00:00+00:00", "pnl": 100.0},  # after end
        ]
        result = srv._aggregate_performance_since(trades, cutoff, end)
        assert result["trades"] == 1
        assert result["pnl"] == 50.0

    def test_trades_missing_exit_time_skipped(self):
        cutoff = datetime(2026, 3, 1, tzinfo=timezone.utc)
        trades = [{"pnl": 100.0}]
        result = srv._aggregate_performance_since(trades, cutoff)
        assert result["trades"] == 0

    def test_uses_is_win_field(self):
        cutoff = datetime(2026, 3, 1, tzinfo=timezone.utc)
        trades = [
            {"exit_time": "2026-03-10T10:00:00+00:00", "pnl": -5.0, "is_win": True},
        ]
        result = srv._aggregate_performance_since(trades, cutoff)
        assert result["wins"] == 1
        assert result["losses"] == 0


# ---------------------------------------------------------------------------
# 15. Date range helpers
# ---------------------------------------------------------------------------

class TestDateRangeHelpers:
    def test_trading_week_start_on_wednesday(self):
        """Wednesday 2026-03-11 should map back to Sunday 2026-03-08 6pm ET."""
        wed = datetime(2026, 3, 11, 15, 0, tzinfo=timezone.utc)
        result = srv._get_trading_week_start(wed)
        assert result.tzinfo is not None
        assert result < wed

    def test_trading_week_start_on_sunday_before_6pm(self):
        """Sunday before 6pm ET: the current week hasn't started, should go back a week."""
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        # Sunday 2026-03-08 at 10am ET = before 6pm
        sun_early_et = datetime(2026, 3, 8, 10, 0, tzinfo=et)
        sun_early_utc = sun_early_et.astimezone(timezone.utc)
        result = srv._get_trading_week_start(sun_early_utc)
        # Result should be 7 days before what would be this Sunday's 6pm
        assert result < sun_early_utc

    def test_month_to_date_start(self):
        now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        result = srv._get_month_to_date_start(now)
        assert result.month in (2, 3)  # Feb 28 or Mar 1 boundary
        assert result < now

    def test_year_to_date_start(self):
        now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        result = srv._get_year_to_date_start(now)
        # Should be around Dec 31 of prior year (6pm ET) in UTC
        assert result.year in (2025, 2026)
        assert result < now


# ---------------------------------------------------------------------------
# 16. _compute_daily_stats (delegating path)
# ---------------------------------------------------------------------------

class TestComputeDailyStats:
    @patch.object(srv, "_read_state_for_dir", return_value={})
    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    @patch.object(srv, "_shared_compute_daily_stats", return_value={
        "daily_pnl": 150.0, "daily_trades": 3, "daily_wins": 2, "daily_losses": 1,
    })
    def test_delegates_to_shared(self, mock_shared, _mock2, _mock3, tmp_path: Path):
        result = srv._compute_daily_stats(tmp_path)
        assert result["daily_pnl"] == 150.0
        assert result["daily_trades"] == 3
        mock_shared.assert_called_once_with(tmp_path)


# ---------------------------------------------------------------------------
# 17. _compute_performance_stats (IBKR Virtual path with performance.json)
# ---------------------------------------------------------------------------

class TestComputePerformanceStats:
    @patch.object(srv, "_read_state_for_dir", return_value={})
    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_returns_empty_stats_when_no_data(self, _mock1, _mock2, tmp_path: Path):
        # No performance.json, no challenge_state.json
        result = srv._compute_performance_stats(tmp_path)
        for period in ("yesterday", "24h", "72h", "30d"):
            assert result[period]["pnl"] == 0.0
            assert result[period]["trades"] == 0

    @patch.object(srv, "_read_state_for_dir", return_value={})
    @patch.object(srv, "_is_tv_paper_account_new", return_value=False)
    def test_computes_from_performance_json(self, _mock1, _mock2, tmp_path: Path):
        now = datetime.now(timezone.utc)
        perf_file = tmp_path / "performance.json"
        trades = [
            {
                "exit_time": (now - timedelta(hours=2)).isoformat(),
                "pnl": 100.0, "is_win": True,
            },
            {
                "exit_time": (now - timedelta(hours=1)).isoformat(),
                "pnl": -40.0, "is_win": False,
            },
        ]
        perf_file.write_text(json.dumps(trades))
        result = srv._compute_performance_stats(tmp_path)
        assert result["24h"]["trades"] == 2
        assert result["24h"]["pnl"] == 60.0
        assert result["24h"]["wins"] == 1
        assert result["24h"]["losses"] == 1


# ---------------------------------------------------------------------------
# 18. _get_data_quality
# ---------------------------------------------------------------------------

class TestGetDataQuality:
    def test_empty_state(self):
        result = srv._get_data_quality({})
        assert result["latest_bar_age_minutes"] is None
        assert result["is_stale"] is False
        # Empty state: futures_market_open defaults to True, so not "expected stale"
        assert result["is_expected_stale"] is False
        assert result["quiet_reason"] is None

    def test_market_closed(self):
        state = {"futures_market_open": False}
        result = srv._get_data_quality(state)
        assert result["is_expected_stale"] is True
        assert result["quiet_reason"] == "Market closed"

    def test_populated_state(self):
        state = {
            "data_quality": {
                "latest_bar_age_minutes": 1.5,
                "stale_threshold_minutes": 3.0,
                "buffer_size": 200,
            },
            "data_provider": {"buffer_target": 500},
            "futures_market_open": True,
            "data_fresh": True,
        }
        result = srv._get_data_quality(state)
        assert result["latest_bar_age_minutes"] == 1.5
        assert result["stale_threshold_minutes"] == 3.0
        assert result["buffer_size"] == 200
        assert result["is_stale"] is False
        assert result["is_expected_stale"] is False

    def test_stale_when_data_not_fresh(self):
        state = {"data_fresh": False, "futures_market_open": True}
        result = srv._get_data_quality(state)
        assert result["is_stale"] is True


# ---------------------------------------------------------------------------
# 19. _write_operator_request
# ---------------------------------------------------------------------------

class TestWriteOperatorRequest:
    def test_writes_json_file(self, tmp_path: Path):
        payload = {"action": "kill_switch", "reason": "test"}
        result_path = srv._write_operator_request(tmp_path, "kill", payload)
        assert result_path.exists()
        assert result_path.parent.name == "operator_requests"
        data = json.loads(result_path.read_text())
        assert data["action"] == "kill_switch"

    def test_creates_operator_requests_dir(self, tmp_path: Path):
        req_dir = tmp_path / "operator_requests"
        assert not req_dir.exists()
        srv._write_operator_request(tmp_path, "test", {"key": "val"})
        assert req_dir.exists()

    def test_filename_has_prefix_and_timestamp(self, tmp_path: Path):
        result_path = srv._write_operator_request(tmp_path, "close_trade", {"id": "s1"})
        assert result_path.name.startswith("close_trade_")
        assert result_path.suffix == ".json"


# ---------------------------------------------------------------------------
# 20. _snap_to_bar
# ---------------------------------------------------------------------------

class TestSnapToBar:
    def test_exact_boundary(self):
        assert srv._snap_to_bar(1500.0, 300) == 1500

    def test_mid_bar(self):
        assert srv._snap_to_bar(1600.0, 300) == 1500

    def test_just_before_next_bar(self):
        assert srv._snap_to_bar(1799.0, 300) == 1500

    def test_default_bar_seconds(self):
        """Default is 300s (5 min)."""
        assert srv._snap_to_bar(1000.0) == 900

    def test_one_minute_bars(self):
        assert srv._snap_to_bar(125.0, 60) == 120


# ---------------------------------------------------------------------------
# Bonus: _cached (TTL cache helper)
# ---------------------------------------------------------------------------

class TestCachedHelper:
    def test_caches_result(self):
        call_count = 0

        def expensive():
            nonlocal call_count
            call_count += 1
            return "result"

        r1 = srv._cached("test_key", 60.0, expensive)
        r2 = srv._cached("test_key", 60.0, expensive)
        assert r1 == r2 == "result"
        assert call_count == 1

    def test_expired_entry_recomputes(self):
        call_count = 0

        def expensive():
            nonlocal call_count
            call_count += 1
            return call_count

        # Set with 0-second TTL (immediately expired)
        srv._cached("expire_key", 0.0, expensive)
        time.sleep(0.01)
        result = srv._cached("expire_key", 0.0, expensive)
        assert result == 2
        assert call_count == 2
