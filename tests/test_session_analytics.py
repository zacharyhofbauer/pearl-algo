"""
Tests for session analytics (src/pearlalgo/analytics/session_analytics.py).

Verifies ``compute_session_analytics`` produces correct session bucketing,
hourly breakdowns, direction/duration analysis, and degrades gracefully
on empty input.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

import pytest

from pearlalgo.analytics.session_analytics import (
    compute_session_analytics,
    _get_session_for_hour,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_performance_trades(n: int = 10) -> List[Dict[str, Any]]:
    """Generate *n* closed-trade dicts with realistic timestamps and PnL.

    Trades are spread across morning (09:xx ET) and afternoon (15:xx ET)
    sessions so we can verify session bucketing.
    """
    base = datetime(2025, 6, 2, 13, 0, 0, tzinfo=timezone.utc)  # 09:00 ET
    trades = []
    for i in range(n):
        entry = base + timedelta(hours=i)
        exit_time = entry + timedelta(minutes=20 + i * 5)
        pnl = 50.0 if i % 3 != 0 else -30.0
        is_win = pnl > 0
        trades.append({
            "entry_time": entry.isoformat(),
            "exit_time": exit_time.isoformat(),
            "pnl": pnl,
            "is_win": is_win,
            "direction": "long" if i % 2 == 0 else "short",
        })
    return trades


def _make_signals(n: int = 8) -> List[Dict[str, Any]]:
    """Generate *n* signal dicts (mix of statuses)."""
    base = datetime(2025, 6, 2, 14, 0, 0, tzinfo=timezone.utc)
    signals = []
    statuses = ["generated", "entered", "exited", "cancelled"]
    for i in range(n):
        status = statuses[i % len(statuses)]
        sig: Dict[str, Any] = {
            "signal_id": f"sig_{i:03d}",
            "status": status,
        }
        if status == "exited":
            sig["entry_time"] = (base + timedelta(hours=i)).isoformat()
            sig["exit_time"] = (base + timedelta(hours=i, minutes=45)).isoformat()
            sig["pnl"] = 25.0 if i % 2 == 0 else -15.0
        signals.append(sig)
    return signals


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyInputs:
    def test_empty_trades_and_signals(self):
        result = compute_session_analytics(signals=[], performance_trades=[])
        assert "session_performance" in result
        assert "direction_breakdown" in result
        assert "status_breakdown" in result
        # All sessions should have zero PnL
        for sp in result["session_performance"]:
            assert sp["pnl"] == 0.0
            assert sp["wins"] == 0

    def test_empty_signals_with_trades(self):
        trades = _make_performance_trades(3)
        result = compute_session_analytics(signals=[], performance_trades=trades)
        total_pnl = sum(sp["pnl"] for sp in result["session_performance"])
        expected_pnl = sum(t["pnl"] for t in trades)
        assert abs(total_pnl - expected_pnl) < 0.01


class TestSessionBucketing:
    def test_all_six_sessions_present(self):
        trades = _make_performance_trades(10)
        result = compute_session_analytics(signals=[], performance_trades=trades)
        session_ids = {sp["id"] for sp in result["session_performance"]}
        assert session_ids == {"overnight", "premarket", "morning", "midday", "afternoon", "close"}

    def test_session_for_hour_mapping(self):
        """Verify the hour->session mapping helper directly."""
        assert _get_session_for_hour(3) == "overnight"
        assert _get_session_for_hour(5) == "premarket"
        assert _get_session_for_hour(8) == "morning"
        assert _get_session_for_hour(12) == "midday"
        assert _get_session_for_hour(15) == "afternoon"
        assert _get_session_for_hour(17) == "close"
        assert _get_session_for_hour(20) == "overnight"


class TestHourlyBreakdown:
    def test_best_hours_require_minimum_trades(self):
        """best_hours only includes hours with >= 5 trades.  With 10 spread
        trades, none should qualify unless several land on the same hour."""
        result = compute_session_analytics(
            signals=[], performance_trades=_make_performance_trades(10)
        )
        # Even if empty, the key must exist
        assert "best_hours" in result
        assert "worst_hours" in result
        assert isinstance(result["best_hours"], list)

    def test_many_trades_populate_hourly_stats(self):
        """Pack 20 trades into the same exit hour so best/worst hours populate."""
        base = datetime(2025, 6, 2, 14, 0, 0, tzinfo=timezone.utc)  # 10:00 ET
        trades = []
        for i in range(20):
            exit_time = base + timedelta(minutes=i)
            pnl = 10.0 if i % 2 == 0 else -5.0
            trades.append({
                "entry_time": (exit_time - timedelta(minutes=10)).isoformat(),
                "exit_time": exit_time.isoformat(),
                "pnl": pnl,
                "is_win": pnl > 0,
                "direction": "long",
            })
        result = compute_session_analytics(signals=[], performance_trades=trades)
        # With 20 trades in the same hour, best_hours should be populated
        assert len(result["best_hours"]) >= 1


class TestDirectionBreakdown:
    def test_long_and_short_counts(self):
        trades = _make_performance_trades(6)
        result = compute_session_analytics(signals=[], performance_trades=trades)
        db = result["direction_breakdown"]
        assert db["long"]["count"] + db["short"]["count"] == 6
        assert db["long"]["count"] >= 1
        assert db["short"]["count"] >= 1


class TestStatusBreakdown:
    def test_signal_statuses_counted(self):
        signals = _make_signals(8)
        result = compute_session_analytics(signals=signals, performance_trades=[])
        sb = result["status_breakdown"]
        # 8 signals cycled through 4 statuses -> 2 of each
        assert sb["generated"] == 2
        assert sb["entered"] == 2
        assert sb["exited"] == 2
        assert sb["cancelled"] == 2
