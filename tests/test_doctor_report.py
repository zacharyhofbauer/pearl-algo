"""
Tests for Doctor Report Module

Tests the business logic for doctor rollup and formatting.
"""

import pytest
from unittest.mock import MagicMock, patch

from pearlalgo.analytics.doctor_report import (
    build_doctor_rollup,
    format_doctor_rollup_text,
    _fmt_pct,
)


class TestFmtPct:
    """Tests for _fmt_pct helper function."""

    def test_formats_percentage(self):
        """Should format float as percentage."""
        assert _fmt_pct(0.5) == "50%"
        assert _fmt_pct(0.75) == "75%"
        assert _fmt_pct(1.0) == "100%"

    def test_handles_zero(self):
        """Should handle zero."""
        assert _fmt_pct(0.0) == "0%"

    def test_handles_invalid_input(self):
        """Should return 0% for invalid input."""
        assert _fmt_pct("invalid") == "0%"
        assert _fmt_pct(None) == "0%"


class TestFormatDoctorRollupText:
    """Tests for format_doctor_rollup_text function."""

    def test_formats_basic_rollup(self):
        """Should format a basic rollup with all sections."""
        rollup = {
            "window_hours": 24.0,
            "cutoff": "2024-01-01T00:00:00+00:00",
            "events": {
                "generated": 100,
                "entered": 50,
                "exited": 45,
                "expired": 5,
            },
            "trade_summary": {
                "total": 45,
                "win_rate": 0.6,
                "total_pnl": 1500.0,
                "avg_hold_minutes": 12.5,
            },
            "cycle_diagnostics": {
                "rejected_market_hours": 10,
                "rejected_confidence": 5,
            },
            "quiet_reasons_top": {
                "market_closed": 50,
                "low_confidence": 20,
            },
            "stop_bins": {"<5": 10, "5-10": 20, "10-15": 15, "15-20": 5, "20-25": 2, ">25": 1},
            "size_bins": {"1": 30, "2-3": 10, "4-5": 5, "6-8": 2, "9-12": 1, "13-15": 0, ">15": 0},
            "stop_avg": 8.5,
            "stop_median": 7.0,
            "size_avg": 1.8,
            "size_median": 1.0,
            "brain": {},
        }

        text = format_doctor_rollup_text(rollup)

        assert "Doctor (last 24h)" in text
        assert "Signals (events):" in text
        assert "- generated: 100" in text
        assert "- entered: 50" in text
        assert "- exited: 45" in text
        assert "Trades (exited):" in text
        assert "- total: 45" in text
        assert "- WR: 60%" in text
        assert "- P&L: +$1,500" in text
        assert "Rejections (cycle totals):" in text
        assert "- market hours: 10" in text
        assert "Stops (pts):" in text
        assert "Size (cts):" in text
        assert "Quiet reasons (top):" in text

    def test_formats_fractional_hours(self):
        """Should handle fractional hours in label."""
        rollup = {
            "window_hours": 6.5,
            "events": {},
            "trade_summary": {"total": 0},
            "cycle_diagnostics": {},
            "quiet_reasons_top": {},
            "stop_bins": {},
            "size_bins": {},
            "stop_avg": None,
            "stop_median": None,
            "size_avg": None,
            "size_median": None,
            "brain": {},
        }

        text = format_doctor_rollup_text(rollup)

        assert "Doctor (last 6.5h)" in text

    def test_formats_negative_pnl(self):
        """Should format negative P&L correctly."""
        rollup = {
            "window_hours": 24.0,
            "events": {},
            "trade_summary": {
                "total": 10,
                "win_rate": 0.3,
                "total_pnl": -500.0,
            },
            "cycle_diagnostics": {},
            "quiet_reasons_top": {},
            "stop_bins": {},
            "size_bins": {},
            "stop_avg": None,
            "stop_median": None,
            "size_avg": None,
            "size_median": None,
            "brain": {},
        }

        text = format_doctor_rollup_text(rollup)

        assert "- P&L: -$500" in text

    def test_formats_brain_section(self):
        """Should format brain/learning section when present."""
        rollup = {
            "window_hours": 24.0,
            "events": {},
            "trade_summary": {"total": 0},
            "cycle_diagnostics": {},
            "quiet_reasons_top": {},
            "stop_bins": {},
            "size_bins": {},
            "stop_avg": None,
            "stop_median": None,
            "size_avg": None,
            "size_median": None,
            "brain": {
                "bandit": {
                    "mode": "shadow",
                    "total_decisions": 100,
                    "total_outcomes": 50,
                    "avg_expected_win_rate": 0.55,
                    "avg_uncertainty": 0.08,
                },
                "ml": {
                    "predictions": 80,
                    "min_probability": 0.55,
                    "passed": 60,
                    "fallbacks": 5,
                },
            },
        }

        text = format_doctor_rollup_text(rollup)

        assert "Brain (learning):" in text
        assert "Bandit: mode=shadow" in text
        assert "decisions=100" in text
        assert "ML: preds=80" in text

    def test_handles_empty_events(self):
        """Should handle empty events gracefully."""
        rollup = {
            "window_hours": 24.0,
            "events": {},
            "trade_summary": {"total": 0},
            "cycle_diagnostics": {},
            "quiet_reasons_top": {},
            "stop_bins": {},
            "size_bins": {},
            "stop_avg": None,
            "stop_median": None,
            "size_avg": None,
            "size_median": None,
            "brain": {},
        }

        text = format_doctor_rollup_text(rollup)

        assert "- (no events)" in text

    def test_handles_no_rejections(self):
        """Should indicate when no rejection data."""
        rollup = {
            "window_hours": 24.0,
            "events": {},
            "trade_summary": {"total": 0},
            "cycle_diagnostics": {},
            "quiet_reasons_top": {},
            "stop_bins": {},
            "size_bins": {},
            "stop_avg": None,
            "stop_median": None,
            "size_avg": None,
            "size_median": None,
            "brain": {},
        }

        text = format_doctor_rollup_text(rollup)

        assert "- (no rejection data)" in text


class TestBuildDoctorRollup:
    """Tests for build_doctor_rollup function."""

    def test_builds_rollup_with_mock_db(self):
        """Should build rollup from database queries."""
        mock_db = MagicMock()
        mock_db.get_signal_event_counts.return_value = {
            "generated": 10,
            "entered": 5,
            "exited": 4,
            "expired": 1,
        }
        mock_db.get_cycle_diagnostics_aggregate.return_value = {
            "rejected_confidence": 3,
        }
        mock_db.get_quiet_reason_counts.return_value = {
            "market_closed": 5,
        }
        mock_db.get_trade_summary.return_value = {
            "total": 4,
            "win_rate": 0.5,
            "total_pnl": 200.0,
        }
        mock_db.get_signal_events.return_value = []

        rollup = build_doctor_rollup(mock_db, hours=24.0)

        assert rollup["window_hours"] == 24.0
        assert rollup["events"]["generated"] == 10
        assert rollup["trade_summary"]["total"] == 4
        assert rollup["cycle_diagnostics"]["rejected_confidence"] == 3
        assert rollup["quiet_reasons_top"]["market_closed"] == 5

    def test_computes_stop_distribution(self):
        """Should compute stop distance distribution from generated signals."""
        mock_db = MagicMock()
        mock_db.get_signal_event_counts.return_value = {}
        mock_db.get_cycle_diagnostics_aggregate.return_value = {}
        mock_db.get_quiet_reason_counts.return_value = {}
        mock_db.get_trade_summary.return_value = {"total": 0}
        mock_db.get_signal_events.return_value = [
            {"payload": {"signal": {"entry_price": 100.0, "stop_loss": 95.0, "position_size": 2.0}}},  # 5pt stop
            {"payload": {"signal": {"entry_price": 100.0, "stop_loss": 92.0, "position_size": 1.0}}},  # 8pt stop
            {"payload": {"signal": {"entry_price": 100.0, "stop_loss": 88.0, "position_size": 3.0}}},  # 12pt stop
        ]

        rollup = build_doctor_rollup(mock_db, hours=24.0)

        assert rollup["stop_bins"]["<5"] == 0
        assert rollup["stop_bins"]["5-10"] == 2  # 5pt and 8pt
        assert rollup["stop_bins"]["10-15"] == 1  # 12pt
        assert rollup["size_bins"]["1"] == 1
        assert rollup["size_bins"]["2-3"] == 2  # 2 and 3

    def test_handles_custom_hours(self):
        """Should use custom hours for cutoff."""
        mock_db = MagicMock()
        mock_db.get_signal_event_counts.return_value = {}
        mock_db.get_cycle_diagnostics_aggregate.return_value = {}
        mock_db.get_quiet_reason_counts.return_value = {}
        mock_db.get_trade_summary.return_value = {"total": 0}
        mock_db.get_signal_events.return_value = []

        rollup = build_doctor_rollup(mock_db, hours=6.0)

        assert rollup["window_hours"] == 6.0
        # Verify cutoff was passed to queries
        call_args = mock_db.get_signal_event_counts.call_args
        assert "from_time" in call_args.kwargs

    def test_handles_missing_signal_data(self):
        """Should handle signals with missing price data."""
        mock_db = MagicMock()
        mock_db.get_signal_event_counts.return_value = {}
        mock_db.get_cycle_diagnostics_aggregate.return_value = {}
        mock_db.get_quiet_reason_counts.return_value = {}
        mock_db.get_trade_summary.return_value = {"total": 0}
        mock_db.get_signal_events.return_value = [
            {"payload": {"signal": {}}},  # Missing prices
            {"payload": {"signal": {"entry_price": 0, "stop_loss": 0}}},  # Zero prices
            {"payload": {}},  # Missing signal entirely
        ]

        # Should not raise
        rollup = build_doctor_rollup(mock_db, hours=24.0)

        assert rollup["stop_bins"]["<5"] == 0
