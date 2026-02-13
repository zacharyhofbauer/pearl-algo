"""
Tests for Strategy Report Module

Tests the business logic for strategy analysis and reporting.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from pearlalgo.analytics.strategy_report import (
    StrategyTradeRecord,
    SummaryRow,
    iter_exited_signals,
    compute_drawdown,
    summarize,
    rank_rows,
    build_report,
)


class TestStrategyTradeRecord:
    """Tests for StrategyTradeRecord dataclass."""

    def test_hold_minutes_calculation(self):
        """Hold minutes should be correctly calculated from entry/exit times."""
        entry = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        exit_time = datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc)

        record = StrategyTradeRecord(
            signal_type="test",
            direction="long",
            pnl=100.0,
            is_win=True,
            exit_time=exit_time,
            entry_time=entry,
            session="US",
            regime="bullish",
            volatility="normal",
        )

        assert record.hold_minutes == 30.0

    def test_hold_minutes_none_when_missing_times(self):
        """Hold minutes should be None if entry or exit time is missing."""
        record = StrategyTradeRecord(
            signal_type="test",
            direction="long",
            pnl=100.0,
            is_win=True,
            exit_time=None,
            entry_time=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            session="US",
            regime="bullish",
            volatility="normal",
        )

        assert record.hold_minutes is None

    def test_hold_minutes_non_negative(self):
        """Hold minutes should never be negative."""
        # Even with reversed times, should return 0
        entry = datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        exit_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

        record = StrategyTradeRecord(
            signal_type="test",
            direction="long",
            pnl=-50.0,
            is_win=False,
            exit_time=exit_time,
            entry_time=entry,
            session="US",
            regime="bearish",
            volatility="high",
        )

        assert record.hold_minutes == 0.0


class TestSummaryRow:
    """Tests for SummaryRow dataclass."""

    def test_to_dict_returns_all_fields(self):
        """to_dict should return all fields as a dictionary."""
        row = SummaryRow(
            key="test_key",
            count=10,
            wins=6,
            losses=4,
            win_rate=0.6,
            total_pnl=500.0,
            avg_pnl=50.0,
            max_drawdown=100.0,
            avg_hold_minutes=15.5,
        )

        d = row.to_dict()

        assert d["key"] == "test_key"
        assert d["count"] == 10
        assert d["wins"] == 6
        assert d["losses"] == 4
        assert d["win_rate"] == 0.6
        assert d["total_pnl"] == 500.0
        assert d["avg_pnl"] == 50.0
        assert d["max_drawdown"] == 100.0
        assert d["avg_hold_minutes"] == 15.5


class TestComputeDrawdown:
    """Tests for compute_drawdown function."""

    def test_no_drawdown_always_winning(self):
        """No drawdown when equity only goes up."""
        pnls = [
            (datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc), 100.0),
            (datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc), 100.0),
            (datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc), 100.0),
        ]

        dd = compute_drawdown(pnls)

        assert dd == 0.0

    def test_simple_drawdown(self):
        """Drawdown should equal peak minus trough."""
        pnls = [
            (datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc), 100.0),   # equity = 100
            (datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc), 100.0),   # equity = 200 (peak)
            (datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc), -150.0),  # equity = 50 (trough)
        ]

        dd = compute_drawdown(pnls)

        assert dd == 150.0  # 200 - 50 = 150

    def test_empty_pnls(self):
        """Empty PnL list should return zero drawdown."""
        dd = compute_drawdown([])
        assert dd == 0.0

    def test_handles_none_timestamps(self):
        """Should handle None timestamps gracefully."""
        pnls = [
            (None, 100.0),
            (None, -50.0),
        ]

        dd = compute_drawdown(pnls)

        assert dd == 50.0


class TestSummarize:
    """Tests for summarize function."""

    def test_empty_records(self):
        """Empty records should return zeroed summary."""
        result = summarize([])

        assert result.count == 0
        assert result.wins == 0
        assert result.losses == 0
        assert result.win_rate == 0.0
        assert result.total_pnl == 0.0
        assert result.avg_pnl == 0.0
        assert result.max_drawdown == 0.0
        assert result.avg_hold_minutes is None

    def test_single_winning_trade(self):
        """Single winning trade should compute correctly."""
        records = [
            StrategyTradeRecord(
                signal_type="test",
                direction="long",
                pnl=100.0,
                is_win=True,
                exit_time=datetime(2024, 1, 1, 10, 30, tzinfo=timezone.utc),
                entry_time=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                session="US",
                regime="bullish",
                volatility="normal",
            )
        ]

        result = summarize(records)

        assert result.count == 1
        assert result.wins == 1
        assert result.losses == 0
        assert result.win_rate == 1.0
        assert result.total_pnl == 100.0
        assert result.avg_pnl == 100.0
        assert result.avg_hold_minutes == 30.0

    def test_mixed_trades(self):
        """Mixed winning and losing trades should aggregate correctly."""
        records = [
            StrategyTradeRecord(
                signal_type="test",
                direction="long",
                pnl=100.0,
                is_win=True,
                exit_time=datetime(2024, 1, 1, 10, 30, tzinfo=timezone.utc),
                entry_time=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                session="US",
                regime="bullish",
                volatility="normal",
            ),
            StrategyTradeRecord(
                signal_type="test",
                direction="short",
                pnl=-50.0,
                is_win=False,
                exit_time=datetime(2024, 1, 1, 11, 15, tzinfo=timezone.utc),
                entry_time=datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
                session="US",
                regime="bearish",
                volatility="high",
            ),
        ]

        result = summarize(records)

        assert result.count == 2
        assert result.wins == 1
        assert result.losses == 1
        assert result.win_rate == 0.5
        assert result.total_pnl == 50.0
        assert result.avg_pnl == 25.0


class TestRankRows:
    """Tests for rank_rows function."""

    def test_ranking_by_score(self):
        """Rows should be ranked by drawdown-penalized score."""
        rows = [
            SummaryRow(key="low_pnl", count=10, wins=5, losses=5, win_rate=0.5,
                      total_pnl=100.0, avg_pnl=10.0, max_drawdown=50.0, avg_hold_minutes=10.0),
            SummaryRow(key="high_pnl", count=10, wins=7, losses=3, win_rate=0.7,
                      total_pnl=500.0, avg_pnl=50.0, max_drawdown=100.0, avg_hold_minutes=10.0),
        ]

        ranked = rank_rows(rows)

        # high_pnl score: 500 - 0.75*100 = 425
        # low_pnl score: 100 - 0.75*50 = 62.5
        assert ranked[0]["key"] == "high_pnl"
        assert ranked[0]["score"] == 425.0
        assert ranked[1]["key"] == "low_pnl"
        assert ranked[1]["score"] == 62.5

    def test_drawdown_penalty_matters(self):
        """High drawdown should penalize even high PnL strategies."""
        rows = [
            SummaryRow(key="steady", count=10, wins=5, losses=5, win_rate=0.5,
                      total_pnl=200.0, avg_pnl=20.0, max_drawdown=10.0, avg_hold_minutes=10.0),
            SummaryRow(key="volatile", count=10, wins=7, losses=3, win_rate=0.7,
                      total_pnl=250.0, avg_pnl=25.0, max_drawdown=200.0, avg_hold_minutes=10.0),
        ]

        ranked = rank_rows(rows)

        # steady score: 200 - 0.75*10 = 192.5
        # volatile score: 250 - 0.75*200 = 100
        assert ranked[0]["key"] == "steady"


class TestIterExitedSignals:
    """Tests for iter_exited_signals function."""

    def test_parses_exited_signals(self):
        """Should correctly parse exited signals from JSONL."""
        with TemporaryDirectory() as tmpdir:
            signals_path = Path(tmpdir) / "signals.jsonl"
            signals_path.write_text(
                '{"status": "exited", "signal_type": "momentum", "pnl": 100.0, "is_win": true, '
                '"signal": {"direction": "long", "regime": {"session": "US", "regime": "bullish", "volatility": "normal"}}}\n'
                '{"status": "entered", "signal_type": "other"}\n'  # Should be skipped
                '{"status": "exited", "signal_type": "reversal", "pnl": -50.0, "is_win": false, '
                '"signal": {"direction": "short", "regime": {"session": "EU", "regime": "bearish", "volatility": "high"}}}\n'
            )

            records = list(iter_exited_signals(signals_path))

            assert len(records) == 2
            assert records[0].signal_type == "momentum"
            assert records[0].pnl == 100.0
            assert records[0].is_win is True
            assert records[0].direction == "long"
            assert records[0].session == "US"
            assert records[1].signal_type == "reversal"
            assert records[1].pnl == -50.0
            assert records[1].is_win is False

    def test_handles_malformed_lines(self):
        """Should skip malformed JSON lines."""
        with TemporaryDirectory() as tmpdir:
            signals_path = Path(tmpdir) / "signals.jsonl"
            signals_path.write_text(
                '{"status": "exited", "signal_type": "test", "pnl": 100.0, "is_win": true, "signal": {}}\n'
                'not valid json\n'
                '{"status": "exited", "signal_type": "test2", "pnl": 50.0, "is_win": true, "signal": {}}\n'
            )

            records = list(iter_exited_signals(signals_path))

            assert len(records) == 2


class TestBuildReport:
    """Tests for build_report function."""

    def test_builds_complete_report(self):
        """Should build a complete report with all sections."""
        with TemporaryDirectory() as tmpdir:
            signals_path = Path(tmpdir) / "signals.jsonl"
            signals_path.write_text(
                '{"status": "exited", "signal_type": "momentum", "pnl": 100.0, "is_win": true, '
                '"signal": {"direction": "long", "regime": {"session": "US", "regime": "bullish", "volatility": "normal"}}}\n'
                '{"status": "exited", "signal_type": "momentum", "pnl": -30.0, "is_win": false, '
                '"signal": {"direction": "short", "regime": {"session": "US", "regime": "bearish", "volatility": "high"}}}\n'
                '{"status": "exited", "signal_type": "reversal", "pnl": 50.0, "is_win": true, '
                '"signal": {"direction": "long", "regime": {"session": "EU", "regime": "range", "volatility": "low"}}}\n'
            )

            report = build_report(signals_path)

            assert "generated_at" in report
            assert "signals_path" in report
            assert "overall" in report
            assert "ranked_by_type" in report
            assert "ranked_by_type_direction" in report
            assert "ranked_by_session" in report
            assert "ranked_by_regime" in report
            assert "ranked_by_volatility" in report
            assert "ranked_by_session_regime" in report

            # Check overall stats
            assert report["overall"]["count"] == 3
            assert report["overall"]["wins"] == 2
            assert report["overall"]["total_pnl"] == 120.0

    def test_empty_signals_file(self):
        """Should handle empty signals file."""
        with TemporaryDirectory() as tmpdir:
            signals_path = Path(tmpdir) / "signals.jsonl"
            signals_path.write_text("")

            report = build_report(signals_path)

            assert report["overall"]["count"] == 0
            assert report["ranked_by_type"] == []
