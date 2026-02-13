"""
Tests for stats_computation - Shared statistics computation module.

Tests cover:
- get_trading_day_start: weekday before/after 6pm ET, Saturday, Sunday, timezone
- compute_daily_stats: no signals, empty file, normal signals, Tradovate mode
- compute_performance_stats: rolling windows (24h/72h/30d), no data, mixed data
- clear_stats_cache: cache invalidation
- Cache TTL behavior: cached results returned within TTL, refreshed after
"""

from __future__ import annotations

import json
import time
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from pearlalgo.market_agent.stats_computation import (
    get_trading_day_start,
    compute_daily_stats,
    compute_performance_stats,
    clear_stats_cache,
    _get_cached,
    _set_cached,
    _cache,
    _DEFAULT_CACHE_TTL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _et_tz():
    """Return the America/New_York timezone."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore
    return ZoneInfo("America/New_York")


def _make_et_now(year=2025, month=6, day=10, hour=14, minute=0):
    """Build a timezone-aware ET datetime for patching datetime.now(et_tz)."""
    et_tz = _et_tz()
    return datetime(year, month, day, hour, minute, 0, 0, tzinfo=et_tz)


def _write_signals_jsonl(state_dir: Path, signals: list) -> None:
    """Write a signals.jsonl file from a list of dicts."""
    sig_file = state_dir / "signals.jsonl"
    lines = [json.dumps(s) for s in signals]
    sig_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_performance_json(state_dir: Path, trades: list) -> None:
    """Write a performance.json file from a list of dicts."""
    perf_file = state_dir / "performance.json"
    perf_file.write_text(json.dumps(trades), encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """Ensure the module-level cache is cleared between tests."""
    clear_stats_cache()
    yield
    clear_stats_cache()


# =========================================================================
# get_trading_day_start
# =========================================================================


class TestGetTradingDayStart:
    """Tests for get_trading_day_start()."""

    def test_weekday_before_6pm_uses_yesterday(self):
        """Before 6pm ET, the trading day started yesterday at 6pm ET."""
        fake_now = _make_et_now(hour=14)  # 2pm ET on a Tuesday
        with patch("pearlalgo.market_agent.stats_computation.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_trading_day_start()

        # Result should be 6pm ET on the previous day, in UTC
        et_tz = _et_tz()
        expected = datetime(2025, 6, 9, 18, 0, 0, 0, tzinfo=et_tz).astimezone(timezone.utc)
        assert result == expected

    def test_weekday_after_6pm_uses_today(self):
        """After 6pm ET, the trading day started today at 6pm ET."""
        fake_now = _make_et_now(hour=19)  # 7pm ET on a Tuesday
        with patch("pearlalgo.market_agent.stats_computation.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_trading_day_start()

        et_tz = _et_tz()
        expected = datetime(2025, 6, 10, 18, 0, 0, 0, tzinfo=et_tz).astimezone(timezone.utc)
        assert result == expected

    def test_exactly_at_6pm(self):
        """At exactly 6pm ET, the new trading day has started."""
        fake_now = _make_et_now(hour=18, minute=0)
        with patch("pearlalgo.market_agent.stats_computation.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_trading_day_start()

        et_tz = _et_tz()
        expected = datetime(2025, 6, 10, 18, 0, 0, 0, tzinfo=et_tz).astimezone(timezone.utc)
        assert result == expected

    def test_saturday_before_6pm(self):
        """On Saturday before 6pm, trading day started Friday at 6pm."""
        # June 14, 2025 is a Saturday
        fake_now = _make_et_now(year=2025, month=6, day=14, hour=10)
        with patch("pearlalgo.market_agent.stats_computation.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_trading_day_start()

        et_tz = _et_tz()
        expected = datetime(2025, 6, 13, 18, 0, 0, 0, tzinfo=et_tz).astimezone(timezone.utc)
        assert result == expected

    def test_sunday_before_6pm(self):
        """On Sunday before 6pm, trading day started Saturday at 6pm."""
        # June 15, 2025 is a Sunday
        fake_now = _make_et_now(year=2025, month=6, day=15, hour=12)
        with patch("pearlalgo.market_agent.stats_computation.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_trading_day_start()

        et_tz = _et_tz()
        expected = datetime(2025, 6, 14, 18, 0, 0, 0, tzinfo=et_tz).astimezone(timezone.utc)
        assert result == expected

    def test_result_is_utc(self):
        """Result should always be in UTC timezone."""
        fake_now = _make_et_now(hour=14)
        with patch("pearlalgo.market_agent.stats_computation.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_trading_day_start()

        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)

    def test_midnight_et(self):
        """At midnight ET, trading day started yesterday at 6pm."""
        fake_now = _make_et_now(hour=0, minute=0)
        with patch("pearlalgo.market_agent.stats_computation.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_trading_day_start()

        et_tz = _et_tz()
        expected = datetime(2025, 6, 9, 18, 0, 0, 0, tzinfo=et_tz).astimezone(timezone.utc)
        assert result == expected


# =========================================================================
# compute_daily_stats
# =========================================================================


class TestComputeDailyStats:
    """Tests for compute_daily_stats()."""

    def test_no_signals_file(self, tmp_state_dir):
        """Should return zeros when signals.jsonl doesn't exist."""
        result = compute_daily_stats(tmp_state_dir, use_cache=False)
        assert result["daily_pnl"] == 0.0
        assert result["daily_trades"] == 0
        assert result["daily_wins"] == 0
        assert result["daily_losses"] == 0
        assert result["win_rate"] == 0.0

    def test_empty_signals_file(self, tmp_state_dir):
        """Should return zeros when signals.jsonl is empty."""
        (tmp_state_dir / "signals.jsonl").write_text("", encoding="utf-8")
        result = compute_daily_stats(tmp_state_dir, use_cache=False)
        assert result["daily_trades"] == 0

    def test_signals_with_wins_and_losses(self, tmp_state_dir):
        """Should correctly compute stats with mixed wins and losses."""
        now_utc = datetime.now(timezone.utc)
        recent_ts = (now_utc + timedelta(minutes=1)).isoformat()

        signals = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 150.0},
            {"status": "exited", "exit_time": recent_ts, "pnl": -50.0},
            {"status": "exited", "exit_time": recent_ts, "pnl": 200.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        result = compute_daily_stats(tmp_state_dir, use_cache=False)
        assert result["daily_pnl"] == 300.0
        assert result["daily_trades"] == 3
        assert result["daily_wins"] == 2
        assert result["daily_losses"] == 1
        assert result["win_rate"] == pytest.approx(66.7, abs=0.1)

    def test_filters_non_exited_signals(self, tmp_state_dir):
        """Should only count signals with status='exited'."""
        now_utc = datetime.now(timezone.utc)
        recent_ts = (now_utc + timedelta(minutes=1)).isoformat()

        signals = [
            {"status": "active", "exit_time": recent_ts, "pnl": 100.0},
            {"status": "exited", "exit_time": recent_ts, "pnl": 50.0},
            {"status": "cancelled", "exit_time": recent_ts, "pnl": -25.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        result = compute_daily_stats(tmp_state_dir, use_cache=False)
        assert result["daily_trades"] == 1
        assert result["daily_pnl"] == 50.0

    def test_filters_old_signals(self, tmp_state_dir):
        """Should only include signals from the current trading day."""
        # A signal from 3 days ago should not be included
        old_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        recent_ts = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()

        signals = [
            {"status": "exited", "exit_time": old_ts, "pnl": 999.0},
            {"status": "exited", "exit_time": recent_ts, "pnl": 42.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        result = compute_daily_stats(tmp_state_dir, use_cache=False)
        assert result["daily_pnl"] == 42.0
        assert result["daily_trades"] == 1

    def test_handles_z_suffix_timestamps(self, tmp_state_dir):
        """Should parse timestamps with Z suffix correctly."""
        now_utc = datetime.now(timezone.utc)
        recent_ts = (now_utc + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        signals = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 100.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        result = compute_daily_stats(tmp_state_dir, use_cache=False)
        assert result["daily_trades"] == 1
        assert result["daily_pnl"] == 100.0

    def test_handles_malformed_lines(self, tmp_state_dir):
        """Should skip malformed JSONL lines gracefully."""
        now_utc = datetime.now(timezone.utc)
        recent_ts = (now_utc + timedelta(minutes=1)).isoformat()

        lines = [
            "not valid json",
            json.dumps({"status": "exited", "exit_time": recent_ts, "pnl": 75.0}),
            "{broken json",
        ]
        (tmp_state_dir / "signals.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = compute_daily_stats(tmp_state_dir, use_cache=False)
        assert result["daily_pnl"] == 75.0

    def test_pnl_is_rounded(self, tmp_state_dir):
        """Should round daily_pnl to 2 decimal places."""
        now_utc = datetime.now(timezone.utc)
        recent_ts = (now_utc + timedelta(minutes=1)).isoformat()

        signals = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 33.333},
            {"status": "exited", "exit_time": recent_ts, "pnl": 66.666},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        result = compute_daily_stats(tmp_state_dir, use_cache=False)
        # 33.333 + 66.666 = 99.999, rounded to 100.0
        assert result["daily_pnl"] == 100.0

    def test_zero_pnl_counted_as_win(self, tmp_state_dir):
        """Should count zero P&L as a win (pnl >= 0)."""
        now_utc = datetime.now(timezone.utc)
        recent_ts = (now_utc + timedelta(minutes=1)).isoformat()

        signals = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 0.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        result = compute_daily_stats(tmp_state_dir, use_cache=False)
        assert result["daily_wins"] == 1
        assert result["daily_losses"] == 0


# =========================================================================
# compute_performance_stats
# =========================================================================


class TestComputePerformanceStats:
    """Tests for compute_performance_stats()."""

    def test_no_performance_file(self, tmp_state_dir):
        """Should return empty stats when performance.json doesn't exist."""
        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["24h"]["pnl"] == 0.0
        assert result["24h"]["trades"] == 0
        assert result["24h"]["streak"] == 0
        assert result["24h"]["streak_type"] == "none"
        assert result["72h"]["trades"] == 0
        assert result["30d"]["trades"] == 0

    def test_empty_performance_file(self, tmp_state_dir):
        """Should return empty stats when performance.json is empty dict."""
        (tmp_state_dir / "performance.json").write_text("{}", encoding="utf-8")
        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["24h"]["trades"] == 0

    def test_rolling_24h_window(self, tmp_state_dir):
        """Should only count trades within the last 24 hours for 24h period."""
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now - timedelta(hours=12)).isoformat(), "pnl": 100, "is_win": True},
            {"exit_time": (now - timedelta(hours=30)).isoformat(), "pnl": 200, "is_win": True},
        ]
        _write_performance_json(tmp_state_dir, trades)

        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["24h"]["trades"] == 1
        assert result["24h"]["pnl"] == 100.0

    def test_rolling_72h_window(self, tmp_state_dir):
        """Should include trades within 72 hours for 72h period."""
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now - timedelta(hours=12)).isoformat(), "pnl": 100, "is_win": True},
            {"exit_time": (now - timedelta(hours=48)).isoformat(), "pnl": 200, "is_win": True},
            {"exit_time": (now - timedelta(hours=80)).isoformat(), "pnl": 300, "is_win": True},
        ]
        _write_performance_json(tmp_state_dir, trades)

        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["72h"]["trades"] == 2
        assert result["72h"]["pnl"] == 300.0

    def test_rolling_30d_window(self, tmp_state_dir):
        """Should include trades within 30 days for 30d period."""
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now - timedelta(days=5)).isoformat(), "pnl": 100, "is_win": True},
            {"exit_time": (now - timedelta(days=20)).isoformat(), "pnl": 200, "is_win": True},
            {"exit_time": (now - timedelta(days=45)).isoformat(), "pnl": 500, "is_win": True},
        ]
        _write_performance_json(tmp_state_dir, trades)

        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["30d"]["trades"] == 2
        assert result["30d"]["pnl"] == 300.0

    def test_mixed_wins_and_losses(self, tmp_state_dir):
        """Should correctly separate wins and losses."""
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now + timedelta(minutes=2)).isoformat(), "pnl": 100, "is_win": True},
            {"exit_time": (now + timedelta(minutes=4)).isoformat(), "pnl": -50, "is_win": False},
            {"exit_time": (now + timedelta(minutes=6)).isoformat(), "pnl": -25, "is_win": False},
        ]
        _write_performance_json(tmp_state_dir, trades)

        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["24h"]["wins"] == 1
        assert result["24h"]["losses"] == 2
        assert result["24h"]["pnl"] == 25.0
        assert result["24h"]["win_rate"] == pytest.approx(33.3, abs=0.1)

    def test_win_streak(self, tmp_state_dir):
        """Should compute a winning streak from most recent trades."""
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now + timedelta(minutes=1)).isoformat(), "pnl": -30, "is_win": False},
            {"exit_time": (now + timedelta(minutes=2)).isoformat(), "pnl": 100, "is_win": True},
            {"exit_time": (now + timedelta(minutes=3)).isoformat(), "pnl": 50, "is_win": True},
            {"exit_time": (now + timedelta(minutes=4)).isoformat(), "pnl": 75, "is_win": True},
        ]
        _write_performance_json(tmp_state_dir, trades)

        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["24h"]["streak"] == 3
        assert result["24h"]["streak_type"] == "win"

    def test_loss_streak(self, tmp_state_dir):
        """Should compute a losing streak from most recent trades."""
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now + timedelta(minutes=1)).isoformat(), "pnl": 100, "is_win": True},
            {"exit_time": (now + timedelta(minutes=2)).isoformat(), "pnl": -30, "is_win": False},
            {"exit_time": (now + timedelta(minutes=3)).isoformat(), "pnl": -20, "is_win": False},
        ]
        _write_performance_json(tmp_state_dir, trades)

        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["24h"]["streak"] == 2
        assert result["24h"]["streak_type"] == "loss"

    def test_trades_missing_exit_time_skipped(self, tmp_state_dir):
        """Should skip trades without exit_time."""
        now = datetime.now(timezone.utc)
        trades = [
            {"pnl": 100, "is_win": True},  # no exit_time
            {"exit_time": (now + timedelta(minutes=1)).isoformat(), "pnl": 50, "is_win": True},
        ]
        _write_performance_json(tmp_state_dir, trades)

        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["24h"]["trades"] == 1

    def test_pnl_is_rounded(self, tmp_state_dir):
        """Should round P&L to 2 decimal places."""
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now + timedelta(minutes=1)).isoformat(), "pnl": 33.333, "is_win": True},
            {"exit_time": (now + timedelta(minutes=2)).isoformat(), "pnl": 66.666, "is_win": True},
        ]
        _write_performance_json(tmp_state_dir, trades)

        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["24h"]["pnl"] == 100.0  # 33.333 + 66.666 = 99.999, rounded

    def test_trade_counts_across_windows(self, tmp_state_dir):
        """A recent trade should appear in all three windows."""
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now + timedelta(minutes=1)).isoformat(), "pnl": 100, "is_win": True},
        ]
        _write_performance_json(tmp_state_dir, trades)

        result = compute_performance_stats(tmp_state_dir, use_cache=False)
        assert result["24h"]["trades"] == 1
        assert result["72h"]["trades"] == 1
        assert result["30d"]["trades"] == 1


# =========================================================================
# clear_stats_cache
# =========================================================================


class TestClearStatsCache:
    """Tests for clear_stats_cache()."""

    def test_clears_all_cached_entries(self):
        """Should empty the entire cache dict."""
        _set_cached("test_key_1", {"data": 1})
        _set_cached("test_key_2", {"data": 2})

        clear_stats_cache()

        assert _get_cached("test_key_1") is None
        assert _get_cached("test_key_2") is None

    def test_clears_after_computation(self, tmp_state_dir):
        """Should force recomputation after cache clear."""
        now = datetime.now(timezone.utc)
        recent_ts = (now + timedelta(minutes=1)).isoformat()
        signals = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 100.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        # First call populates cache
        r1 = compute_daily_stats(tmp_state_dir, use_cache=True)
        assert r1["daily_pnl"] == 100.0

        # Now change the data and clear cache
        signals.append({"status": "exited", "exit_time": recent_ts, "pnl": 200.0})
        _write_signals_jsonl(tmp_state_dir, signals)
        clear_stats_cache()

        # Should recompute from disk
        r2 = compute_daily_stats(tmp_state_dir, use_cache=True)
        assert r2["daily_pnl"] == 300.0


# =========================================================================
# Cache TTL Behavior
# =========================================================================


class TestCacheTTL:
    """Tests for caching and TTL behavior."""

    def test_cached_result_returned_within_ttl(self, tmp_state_dir):
        """Should return cached result when within TTL."""
        now = datetime.now(timezone.utc)
        recent_ts = (now + timedelta(minutes=1)).isoformat()
        signals = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 100.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        r1 = compute_daily_stats(tmp_state_dir, use_cache=True)

        # Overwrite the file with new data
        signals_new = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 999.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals_new)

        # Second call should still return cached (old) data
        r2 = compute_daily_stats(tmp_state_dir, use_cache=True)
        assert r2["daily_pnl"] == r1["daily_pnl"]

    def test_cache_refreshed_after_ttl(self, tmp_state_dir):
        """Should recompute after the cache TTL expires."""
        now = datetime.now(timezone.utc)
        recent_ts = (now + timedelta(minutes=1)).isoformat()
        signals = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 100.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        r1 = compute_daily_stats(tmp_state_dir, use_cache=True, cache_ttl=0.1)

        # Overwrite with new data
        signals_new = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 500.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals_new)

        # Wait for TTL to expire
        time.sleep(0.15)

        r2 = compute_daily_stats(tmp_state_dir, use_cache=True, cache_ttl=0.1)
        assert r2["daily_pnl"] == 500.0

    def test_use_cache_false_bypasses_cache(self, tmp_state_dir):
        """Should always recompute when use_cache=False."""
        now = datetime.now(timezone.utc)
        recent_ts = (now + timedelta(minutes=1)).isoformat()
        signals = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 100.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals)

        compute_daily_stats(tmp_state_dir, use_cache=True)

        signals_new = [
            {"status": "exited", "exit_time": recent_ts, "pnl": 42.0},
        ]
        _write_signals_jsonl(tmp_state_dir, signals_new)

        r2 = compute_daily_stats(tmp_state_dir, use_cache=False)
        assert r2["daily_pnl"] == 42.0

    def test_performance_stats_caching(self, tmp_state_dir):
        """Should cache compute_performance_stats results too."""
        now = datetime.now(timezone.utc)
        trades = [
            {"exit_time": (now + timedelta(minutes=1)).isoformat(), "pnl": 100, "is_win": True},
        ]
        _write_performance_json(tmp_state_dir, trades)

        r1 = compute_performance_stats(tmp_state_dir, use_cache=True)

        # Overwrite with new data
        trades_new = [
            {"exit_time": (now + timedelta(minutes=1)).isoformat(), "pnl": 999, "is_win": True},
        ]
        _write_performance_json(tmp_state_dir, trades_new)

        # Should still return old cached result
        r2 = compute_performance_stats(tmp_state_dir, use_cache=True)
        assert r2["24h"]["pnl"] == r1["24h"]["pnl"]

    def test_set_and_get_cached(self):
        """Basic test of _set_cached and _get_cached helpers."""
        _set_cached("mykey", {"value": 42})
        result = _get_cached("mykey", ttl=10.0)
        assert result == {"value": 42}

    def test_get_cached_returns_none_after_ttl(self):
        """_get_cached should return None after TTL expires."""
        _set_cached("expire_key", {"value": 1})
        time.sleep(0.15)
        result = _get_cached("expire_key", ttl=0.1)
        assert result is None
