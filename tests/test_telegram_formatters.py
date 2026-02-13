"""
Tests for Telegram bot formatters (telegram/formatters/messages.py).

Pure function tests — no I/O, no mocks required.
"""

from __future__ import annotations

import pytest

from pearlalgo.telegram.formatters.messages import (
    format_pnl,
    format_win_rate,
    format_position,
    format_status_message,
    format_trades_message,
    format_error_message,
    format_control_response,
)


class TestFormatPnl:
    """format_pnl returns HTML-friendly P&L string."""

    def test_positive_pnl(self):
        assert format_pnl(125.50) == "🟢 +$125.50"

    def test_negative_pnl(self):
        assert format_pnl(-50.25) == "🔴 -$50.25"

    def test_zero_pnl(self):
        assert format_pnl(0) == "🟢 +$0.00"

    def test_large_pnl(self):
        assert format_pnl(12345.67) == "🟢 +$12,345.67"


class TestFormatWinRate:
    """format_win_rate returns percentage and W/L count."""

    def test_zero_total(self):
        assert format_win_rate(0, 0) == "N/A"

    def test_all_wins(self):
        assert format_win_rate(10, 0) == "100% (10W/0L)"

    def test_all_losses(self):
        assert format_win_rate(0, 5) == "0% (0W/5L)"

    def test_mixed(self):
        assert format_win_rate(6, 4) == "60% (6W/4L)"


class TestFormatPosition:
    """format_position formats a single position as HTML line."""

    def test_basic_position(self):
        pos = {
            "direction": "long",
            "entry_price": 18000.5,
            "position_size": 2,
            "signal_id": "sig_abc",
        }
        out = format_position(pos)
        assert "LONG" in out
        assert "2x" in out
        assert "18,000.50" in out
        assert "sig_abc" in out

    def test_missing_fields_use_defaults(self):
        pos = {}
        out = format_position(pos)
        assert "?" in out


class TestFormatStatusMessage:
    """format_status_message builds full status HTML."""

    def test_minimal_data(self):
        data = {
            "agent_state": "running",
            "symbol": "MNQ",
            "account": {"display_name": "Agent", "badge": ""},
            "pnl": {"total_pnl": 0.0, "wins": 0, "losses": 0},
            "positions": [],
        }
        msg = format_status_message(data)
        assert "running" in msg.lower()
        assert "MNQ" in msg
        assert "P&amp;L" in msg or "P&L" in msg
        assert "No open positions" in msg

    def test_with_positions(self):
        data = {
            "agent_state": "running",
            "symbol": "MNQ",
            "account": {"display_name": "Paper", "badge": "PAPER"},
            "pnl": {"total_pnl": 100.0, "wins": 2, "losses": 1},
            "positions": [
                {"direction": "long", "entry_price": 18000, "position_size": 1, "signal_id": "s1"},
            ],
        }
        msg = format_status_message(data)
        assert "Open Positions (1)" in msg
        assert "+$100.00" in msg


class TestFormatTradesMessage:
    """format_trades_message formats recent trades."""

    def test_empty_trades(self):
        assert "No recent trades" in format_trades_message([])

    def test_single_trade(self):
        trades = [
            {
                "direction": "long",
                "entry_price": 18000,
                "exit_price": 18020,
                "pnl": 40.0,
                "is_win": True,
                "exit_reason": "take_profit",
            },
        ]
        msg = format_trades_message(trades)
        assert "Recent Trades" in msg
        assert "LONG" in msg
        assert "+$40.00" in msg
        assert "take_profit" in msg


class TestFormatErrorMessage:
    """format_error_message escapes and wraps error text."""

    def test_simple_error(self):
        msg = format_error_message("Connection refused")
        assert "Error" in msg
        assert "Connection refused" in msg

    def test_html_escaped(self):
        msg = format_error_message("<script>")
        assert "<script>" not in msg or "&lt;" in msg


class TestFormatControlResponse:
    """format_control_response formats start/stop/flatten result."""

    def test_success_with_detail(self):
        msg = format_control_response("start", True, "Agent started")
        assert "start" in msg.lower()
        assert "Agent started" in msg

    def test_failure(self):
        msg = format_control_response("flatten_all", False, "Not connected")
        assert "Not connected" in msg
