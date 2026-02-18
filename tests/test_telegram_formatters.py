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
    format_health_message,
    format_doctor_message,
    format_signals_message,
    format_stats_message,
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
    """format_status_message mirrors the dashboard AccountStrip."""

    def test_minimal_data(self):
        data = {
            "running": False,
            "paused": False,
            "futures_market_open": False,
            "active_trades_count": 0,
        }
        msg = format_status_message(data)
        assert "Tradovate Paper" in msg
        assert "Stopped" in msg
        assert "No open positions" in msg

    def test_with_challenge_and_daily(self):
        data = {
            "running": True,
            "paused": False,
            "futures_market_open": True,
            "challenge": {
                "current_balance": 52856.70,
                "pnl": 2856.70,
                "trades": 234,
                "wins": 112,
                "win_rate": 47.9,
            },
            "daily_pnl": -645.91,
            "daily_trades": 7,
            "daily_wins": 3,
            "daily_losses": 4,
            "active_trades_count": 1,
            "active_trades_unrealized_pnl": 25.50,
        }
        msg = format_status_message(data)
        assert "52,856" in msg
        assert "+$2,856.70" in msg
        assert "Today" in msg
        assert "Open" in msg


class TestFormatHealthMessage:
    """format_health_message shows system health."""

    def test_healthy_system(self):
        data = {
            "running": True,
            "paused": False,
            "data_fresh": True,
            "futures_market_open": True,
            "last_updated": "2026-02-17T20:00:00Z",
            "circuit_breaker": {"tripped": False},
        }
        msg = format_health_message(data)
        assert "System Health" in msg
        assert "Running" in msg
        assert "Circuit Breaker" in msg
        assert "OK" in msg

    def test_unhealthy_system(self):
        data = {
            "running": False,
            "data_fresh": False,
            "futures_market_open": False,
            "circuit_breaker": {"tripped": True, "reason": "max losses"},
        }
        msg = format_health_message(data)
        assert "TRIPPED" in msg


class TestFormatDoctorMessage:
    """format_doctor_message shows risk metrics and analytics."""

    def test_with_risk_metrics(self):
        data = {
            "risk_metrics": {
                "sharpe_ratio": 2.5,
                "sortino_ratio": 4.0,
                "profit_factor": 1.5,
                "expectancy": 15.0,
                "max_drawdown": 2400,
                "max_drawdown_pct": 4.8,
            },
        }
        msg = format_doctor_message(data)
        assert "Doctor" in msg
        assert "Sharpe" in msg
        assert "2.50" in msg
        assert "PF" in msg

    def test_with_direction_breakdown(self):
        data = {
            "analytics": {
                "direction_breakdown": {
                    "long": {"count": 120, "pnl": 500},
                    "short": {"count": 114, "pnl": 2300},
                }
            }
        }
        msg = format_doctor_message(data)
        assert "LONG" in msg
        assert "SHORT" in msg


class TestFormatSignalsMessage:
    """format_signals_message shows signal rejections and last decision."""

    def test_with_rejections(self):
        data = {
            "signal_rejections_24h": {
                "total": 12,
                "direction_gating": 5,
                "ml_filter": 3,
                "circuit_breaker": 2,
                "session_filter": 1,
                "max_positions": 1,
            },
        }
        msg = format_signals_message(data)
        assert "Rejections" in msg
        assert "12" in msg
        assert "Direction Gating" in msg

    def test_with_last_decision(self):
        data = {
            "last_signal_decision": {
                "action": "execute",
                "signal_type": "sr_bounce",
                "direction": "long",
                "reason": "all checks passed",
                "ml_probability": 0.72,
                "timestamp": "2026-02-17T15:30:00Z",
            },
        }
        msg = format_signals_message(data)
        assert "EXECUTE" in msg
        assert "sr_bounce" in msg
        assert "72.0%" in msg


class TestFormatStatsMessage:
    """format_stats_message shows performance by period."""

    def test_with_daily_and_challenge(self):
        data = {
            "daily_pnl": -645.91,
            "daily_trades": 7,
            "daily_wins": 3,
            "daily_losses": 4,
            "challenge": {"pnl": 2856.70, "trades": 234, "wins": 112, "win_rate": 47.9},
            "performance": {
                "24h": {"pnl": -645, "trades": 7, "win_rate": 43},
                "72h": {"pnl": 1200, "trades": 45, "win_rate": 49},
            },
        }
        msg = format_stats_message(data)
        assert "Performance" in msg
        assert "TODAY" in msg
        assert "ALL TIME" in msg


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
                "position_size": 5,
            },
        ]
        msg = format_trades_message(trades)
        assert "Recent Trades" in msg
        assert "LONG" in msg
        assert "+$40.00" in msg

    def test_with_duration(self):
        trades = [
            {
                "direction": "short",
                "entry_price": 25000,
                "exit_price": 24980,
                "pnl": 200.0,
                "is_win": True,
                "exit_reason": "take_profit",
                "position_size": 5,
                "duration_seconds": 3600,
            },
        ]
        msg = format_trades_message(trades)
        assert "1h0m" in msg


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
