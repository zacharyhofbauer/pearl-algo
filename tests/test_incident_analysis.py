"""Tests for pearlalgo.analytics.incident_analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from pearlalgo.analytics.incident_analysis import (
    IncidentTradeRecord,
    _safe_float,
    _percentile,
    load_trades,
    load_events,
    compute_exposure,
    group_stats,
    build_incident_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(**overrides) -> IncidentTradeRecord:
    defaults = dict(
        signal_id="sig-001",
        exit_time=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
        entry_time=datetime(2026, 3, 10, 11, 0, tzinfo=timezone.utc),
        direction="long",
        entry_price=17500.0,
        exit_price=17520.0,
        pnl=40.0,
        is_win=True,
        exit_reason="take_profit",
        position_size=1.0,
        tick_value=2.0,
        stop_loss=17480.0,
        take_profit=17540.0,
        entry_trigger="ema_cross",
        regime="trending",
        confidence=0.75,
        risk_reward=2.0,
        duplicate=False,
    )
    defaults.update(overrides)
    return IncidentTradeRecord(**defaults)


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_valid(self):
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_string(self):
        assert _safe_float("42") == pytest.approx(42.0)

    def test_invalid(self):
        assert _safe_float("abc", 0.0) == 0.0

    def test_none(self):
        assert _safe_float(None, -1.0) == -1.0


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_empty(self):
        assert _percentile([], 0.5) is None

    def test_min(self):
        assert _percentile([1, 2, 3, 4, 5], 0.0) == 1

    def test_max(self):
        assert _percentile([1, 2, 3, 4, 5], 1.0) == 5

    def test_median(self):
        result = _percentile([1, 2, 3, 4, 5], 0.5)
        assert result == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# load_trades
# ---------------------------------------------------------------------------

class TestLoadTrades:
    def test_loads_exited_trades(self, tmp_path):
        signals_file = tmp_path / "signals.jsonl"
        records = [
            {
                "signal_id": "sig1",
                "status": "exited",
                "exit_time": "2026-03-10T12:00:00Z",
                "exit_price": 17520,
                "pnl": 40,
                "is_win": True,
                "exit_reason": "take_profit",
                "signal": {
                    "direction": "long",
                    "entry_price": 17500,
                    "stop_loss": 17480,
                    "take_profit": 17540,
                },
            },
        ]
        signals_file.write_text("\n".join(json.dumps(r) for r in records))
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        trades, raw = load_trades(signals_file, start)
        assert len(trades) == 1
        assert trades[0].pnl == 40.0

    def test_skips_non_exited(self, tmp_path):
        signals_file = tmp_path / "signals.jsonl"
        records = [
            {"signal_id": "sig1", "status": "generated", "signal": {}},
        ]
        signals_file.write_text("\n".join(json.dumps(r) for r in records))
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trades, _ = load_trades(signals_file, start)
        assert len(trades) == 0

    def test_skips_before_start(self, tmp_path):
        signals_file = tmp_path / "signals.jsonl"
        records = [
            {
                "signal_id": "sig1",
                "status": "exited",
                "exit_time": "2026-01-01T00:00:00Z",
                "exit_price": 17500,
                "pnl": 10,
                "signal": {"direction": "long", "entry_price": 17490},
            },
        ]
        signals_file.write_text("\n".join(json.dumps(r) for r in records))
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        trades, _ = load_trades(signals_file, start)
        assert len(trades) == 0

    def test_nonexistent_file(self, tmp_path):
        trades, _ = load_trades(tmp_path / "nope.jsonl", datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert len(trades) == 0

    def test_invalid_json_lines_skipped(self, tmp_path):
        signals_file = tmp_path / "signals.jsonl"
        signals_file.write_text("not json\n{}")
        trades, _ = load_trades(signals_file, datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert len(trades) == 0


# ---------------------------------------------------------------------------
# load_events
# ---------------------------------------------------------------------------

class TestLoadEvents:
    def test_loads_events(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        records = [
            {"type": "signal_generated", "timestamp": "2026-03-10T12:00:00Z"},
            {"type": "signal_generated", "timestamp": "2026-03-10T13:00:00Z"},
            {"type": "trade_executed", "timestamp": "2026-03-10T14:00:00Z"},
        ]
        events_file.write_text("\n".join(json.dumps(r) for r in records))
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        counts = load_events(events_file, start)
        assert counts["signal_generated"] == 2
        assert counts["trade_executed"] == 1

    def test_nonexistent_file(self, tmp_path):
        counts = load_events(tmp_path / "nope.jsonl", datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert len(counts) == 0


# ---------------------------------------------------------------------------
# compute_exposure
# ---------------------------------------------------------------------------

class TestComputeExposure:
    def test_empty(self):
        result = compute_exposure([])
        assert result["max_concurrent_positions"] == 0

    def test_single_trade(self):
        trade = _make_trade()
        result = compute_exposure([trade])
        assert result["max_concurrent_positions"] == 1
        assert result["stop_points_stats"]["count"] == 1

    def test_concurrent_positions(self):
        t1 = _make_trade(
            entry_time=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
        )
        t2 = _make_trade(
            signal_id="sig-002",
            entry_time=datetime(2026, 3, 10, 11, 0, tzinfo=timezone.utc),
            exit_time=datetime(2026, 3, 10, 13, 0, tzinfo=timezone.utc),
        )
        result = compute_exposure([t1, t2])
        assert result["max_concurrent_positions"] == 2


# ---------------------------------------------------------------------------
# group_stats
# ---------------------------------------------------------------------------

class TestGroupStats:
    def test_by_direction(self):
        trades = [
            _make_trade(direction="long", pnl=40, is_win=True),
            _make_trade(direction="long", pnl=-20, is_win=False),
            _make_trade(direction="short", pnl=30, is_win=True),
        ]
        result = group_stats(trades, lambda t: t.direction)
        assert result["long"]["count"] == 2
        assert result["short"]["count"] == 1
        assert result["long"]["wins"] == 1

    def test_empty(self):
        result = group_stats([], lambda t: t.direction)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# build_incident_report
# ---------------------------------------------------------------------------

class TestBuildIncidentReport:
    def test_report_structure(self):
        trades = [_make_trade(), _make_trade(pnl=-20, is_win=False)]
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        report = build_incident_report(trades, start, {"signal": 5})
        assert "summary" in report
        assert report["summary"]["total_trades"] == 2
        assert "breakdown" in report
        assert "exposure" in report
        assert "events" in report
        assert report["events"]["signal"] == 5

    def test_empty_trades(self):
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        report = build_incident_report([], start, {})
        assert report["summary"]["total_trades"] == 0
        assert report["summary"]["total_pnl"] == 0

    def test_biggest_losses(self):
        trades = [
            _make_trade(pnl=-100, is_win=False),
            _make_trade(pnl=-50, is_win=False),
            _make_trade(pnl=30, is_win=True),
        ]
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        report = build_incident_report(trades, start, {})
        assert len(report["biggest_losses"]) == 2
        assert report["biggest_losses"][0]["pnl"] == -100
