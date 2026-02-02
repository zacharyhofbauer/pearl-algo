"""
Tests for Telegram Message Formatters.

Tests the TelegramFormattersMixin class which provides message formatting utilities
for the Telegram bot interface.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime, timezone, timedelta


@pytest.fixture
def formatters_mixin():
    """Create a TelegramFormattersMixin instance for testing."""
    from pearlalgo.market_agent.telegram_formatters import TelegramFormattersMixin

    class TestHandler(TelegramFormattersMixin):
        """Test handler class using the mixin."""

        def __init__(self):
            self.state_dir = Path("/tmp/test_state")
            self.active_market = "NQ"

        def _is_agent_process_running(self):
            return True

        def _get_gateway_status(self):
            return {"is_healthy": True, "process_running": True, "port_listening": True}

        def _extract_data_age_minutes(self, state):
            return 2.5

    return TestHandler()


class TestFormatSupportDuration:
    """Tests for _format_support_duration method."""

    def test_formats_seconds(self, formatters_mixin):
        """Should format seconds properly."""
        assert formatters_mixin._format_support_duration(30) == "30s"
        assert formatters_mixin._format_support_duration(59) == "59s"

    def test_formats_minutes(self, formatters_mixin):
        """Should format minutes properly."""
        assert formatters_mixin._format_support_duration(60) == "1m"
        assert formatters_mixin._format_support_duration(120) == "2m"
        assert formatters_mixin._format_support_duration(3599) == "59m"

    def test_formats_hours(self, formatters_mixin):
        """Should format hours properly."""
        assert formatters_mixin._format_support_duration(3600) == "1h"
        assert formatters_mixin._format_support_duration(7200) == "2h"
        assert formatters_mixin._format_support_duration(3660) == "1h 1m"
        assert formatters_mixin._format_support_duration(5400) == "1h 30m"

    def test_formats_days(self, formatters_mixin):
        """Should format days properly."""
        assert formatters_mixin._format_support_duration(86400) == "1d"
        assert formatters_mixin._format_support_duration(172800) == "2d"
        assert formatters_mixin._format_support_duration(90000) == "1d 1h"

    def test_handles_none(self, formatters_mixin):
        """Should return ? for None."""
        assert formatters_mixin._format_support_duration(None) == "?"

    def test_handles_negative(self, formatters_mixin):
        """Should return ? for negative values."""
        assert formatters_mixin._format_support_duration(-10) == "?"


class TestGetChartUrl:
    """Tests for _get_chart_url method."""

    def test_returns_url_from_env(self, formatters_mixin):
        """Should return URL from environment variable."""
        with patch.dict('os.environ', {'PEARL_LIVE_CHART_URL': 'https://chart.example.com'}):
            url = formatters_mixin._get_chart_url()
            assert url == 'https://chart.example.com'

    def test_returns_none_for_empty_env(self, formatters_mixin):
        """Should return None for empty environment variable."""
        with patch.dict('os.environ', {'PEARL_LIVE_CHART_URL': ''}, clear=False):
            url = formatters_mixin._get_chart_url()
            assert url is None

    def test_returns_none_for_invalid_url(self, formatters_mixin):
        """Should return None for non-URL strings."""
        with patch.dict('os.environ', {'PEARL_LIVE_CHART_URL': 'not-a-url'}):
            url = formatters_mixin._get_chart_url()
            assert url is None

    def test_accepts_http_urls(self, formatters_mixin):
        """Should accept http:// URLs."""
        with patch.dict('os.environ', {'PEARL_LIVE_CHART_URL': 'http://localhost:3001'}):
            url = formatters_mixin._get_chart_url()
            assert url == 'http://localhost:3001'

    def test_accepts_https_urls(self, formatters_mixin):
        """Should accept https:// URLs."""
        with patch.dict('os.environ', {'PEARL_LIVE_CHART_URL': 'https://secure.example.com'}):
            url = formatters_mixin._get_chart_url()
            assert url == 'https://secure.example.com'


class TestBuildSupportFooter:
    """Tests for _build_support_footer method."""

    def test_includes_time(self, formatters_mixin):
        """Should include current time."""
        footer = formatters_mixin._build_support_footer()

        assert "🕐" in footer
        # Should have ET or UTC time
        assert "ET" in footer or "UTC" in footer

    def test_includes_market(self, formatters_mixin):
        """Should include market symbol."""
        footer = formatters_mixin._build_support_footer()

        assert "🌐" in footer
        assert "NQ" in footer

    def test_includes_agent_status(self, formatters_mixin):
        """Should include agent status."""
        footer = formatters_mixin._build_support_footer()

        assert "🤖" in footer
        assert "ON" in footer or "OFF" in footer

    def test_includes_gateway_status(self, formatters_mixin):
        """Should include gateway status."""
        footer = formatters_mixin._build_support_footer()

        assert "🔌" in footer

    def test_includes_data_age_when_state_provided(self, formatters_mixin):
        """Should include data age when state is provided."""
        state = {"latest_bar": {"timestamp": datetime.now(timezone.utc).isoformat()}}
        footer = formatters_mixin._build_support_footer(state)

        assert "📡" in footer

    def test_includes_uptime_when_available(self, formatters_mixin):
        """Should include uptime when start_time is in state."""
        start_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        state = {"start_time": start_time}

        footer = formatters_mixin._build_support_footer(state)

        assert "⏱️" in footer or "Uptime" in footer


class TestWithSupportFooter:
    """Tests for _with_support_footer method."""

    def test_appends_footer_to_text(self, formatters_mixin):
        """Should append footer to text."""
        text = "Test message"
        result = formatters_mixin._with_support_footer(text)

        assert text in result
        assert "───" in result  # Footer separator

    def test_respects_max_chars_limit(self, formatters_mixin):
        """Should not append footer if it would exceed limit."""
        # Create a very long message
        text = "X" * 4000
        result = formatters_mixin._with_support_footer(text, max_chars=4096)

        # Should be within limit
        assert len(result) <= 4096

    def test_includes_chart_link_when_available(self, formatters_mixin):
        """Should include chart link when configured."""
        with patch.dict('os.environ', {'PEARL_LIVE_CHART_URL': 'https://chart.example.com'}):
            text = "Test message"
            result = formatters_mixin._with_support_footer(text, include_chart_link=True)

            assert "Live Chart" in result

    def test_excludes_chart_link_when_disabled(self, formatters_mixin):
        """Should exclude chart link when include_chart_link=False."""
        with patch.dict('os.environ', {'PEARL_LIVE_CHART_URL': 'https://chart.example.com'}):
            text = "Test message"
            result = formatters_mixin._with_support_footer(text, include_chart_link=False)

            assert "Live Chart" not in result


class TestFormatSignalDetail:
    """Tests for _format_signal_detail method."""

    def test_includes_signal_id(self, formatters_mixin):
        """Should include signal ID."""
        signal = {"signal_id": "abc123"}
        result = formatters_mixin._format_signal_detail(signal)

        assert "abc123" in result

    def test_includes_direction(self, formatters_mixin):
        """Should include direction."""
        signal = {"direction": "long"}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Direction" in result or "long" in result.lower()

    def test_includes_status(self, formatters_mixin):
        """Should include status."""
        signal = {"status": "entered"}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Status" in result

    def test_includes_entry_price(self, formatters_mixin):
        """Should include entry price."""
        signal = {"entry_price": 15000.50}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Entry" in result
        assert "15,000.50" in result or "15000.50" in result

    def test_includes_exit_price(self, formatters_mixin):
        """Should include exit price when present."""
        signal = {"exit_price": 15050.00}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Exit" in result

    def test_includes_stop_loss(self, formatters_mixin):
        """Should include stop loss."""
        signal = {"stop_loss": 14950.00}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Stop" in result

    def test_includes_take_profit(self, formatters_mixin):
        """Should include take profit."""
        signal = {"take_profit": 15100.00}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Target" in result

    def test_includes_pnl(self, formatters_mixin):
        """Should include P&L when present."""
        signal = {"pnl": 250.00}
        result = formatters_mixin._format_signal_detail(signal)

        assert "P&L" in result

    def test_includes_win_indicator(self, formatters_mixin):
        """Should show win/loss indicator."""
        signal = {"pnl": 250.00, "is_win": True}
        result = formatters_mixin._format_signal_detail(signal)

        assert "WIN" in result or "✅" in result

    def test_includes_loss_indicator(self, formatters_mixin):
        """Should show loss indicator."""
        signal = {"pnl": -150.00, "is_win": False}
        result = formatters_mixin._format_signal_detail(signal)

        assert "LOSS" in result or "❌" in result

    def test_includes_confidence(self, formatters_mixin):
        """Should include confidence."""
        signal = {"confidence": 0.85}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Confidence" in result
        assert "85" in result

    def test_includes_risk_reward(self, formatters_mixin):
        """Should include risk/reward ratio."""
        signal = {"risk_reward": 2.5}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Risk/Reward" in result
        assert "2.5" in result

    def test_includes_hold_duration(self, formatters_mixin):
        """Should include hold duration."""
        signal = {"hold_duration_minutes": 45}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Hold time" in result
        assert "45m" in result

    def test_includes_reason(self, formatters_mixin):
        """Should include reason when present."""
        signal = {"reason": "Bullish divergence detected"}
        result = formatters_mixin._format_signal_detail(signal)

        assert "Reason" in result
        assert "Bullish divergence" in result


class TestFormatTradesSummary:
    """Tests for _format_trades_summary method."""

    def test_empty_trades(self, formatters_mixin):
        """Should handle empty trades list."""
        result = formatters_mixin._format_trades_summary([])

        assert "No trades found" in result

    def test_includes_total_count(self, formatters_mixin):
        """Should include total trade count."""
        trades = [
            {"pnl": 100, "is_win": True},
            {"pnl": -50, "is_win": False},
            {"pnl": 75, "is_win": True},
        ]
        result = formatters_mixin._format_trades_summary(trades)

        assert "3" in result
        assert "Total" in result

    def test_includes_win_loss_ratio(self, formatters_mixin):
        """Should include wins and losses."""
        trades = [
            {"pnl": 100, "is_win": True},
            {"pnl": -50, "is_win": False},
            {"pnl": 75, "is_win": True},
        ]
        result = formatters_mixin._format_trades_summary(trades)

        assert "2W" in result
        assert "1L" in result

    def test_includes_total_pnl(self, formatters_mixin):
        """Should include total P&L."""
        trades = [
            {"pnl": 100, "is_win": True},
            {"pnl": -50, "is_win": False},
        ]
        result = formatters_mixin._format_trades_summary(trades)

        assert "P&L" in result
        assert "50" in result  # Net P&L

    def test_includes_win_rate(self, formatters_mixin):
        """Should include win rate percentage."""
        trades = [
            {"pnl": 100, "is_win": True},
            {"pnl": -50, "is_win": False},
        ]
        result = formatters_mixin._format_trades_summary(trades)

        assert "50" in result and "%" in result or "WR" in result

    def test_shows_recent_trades(self, formatters_mixin):
        """Should show recent trades."""
        trades = [
            {"pnl": 100, "is_win": True, "direction": "long", "signal_id": "abc123"},
        ]
        result = formatters_mixin._format_trades_summary(trades)

        assert "Recent" in result

    def test_custom_title(self, formatters_mixin):
        """Should use custom title."""
        trades = [{"pnl": 100, "is_win": True}]
        result = formatters_mixin._format_trades_summary(trades, title="Today's Trades")

        assert "Today's Trades" in result


class TestFormatActivityCard:
    """Tests for _format_activity_card method."""

    def test_includes_daily_pnl(self, formatters_mixin):
        """Should include daily P&L."""
        result = formatters_mixin._format_activity_card(daily_pnl=150.00)

        assert "Today" in result
        assert "150" in result

    def test_positive_pnl_shows_green(self, formatters_mixin):
        """Should show green indicator for positive P&L."""
        result = formatters_mixin._format_activity_card(daily_pnl=100.00)

        assert "🟢" in result

    def test_negative_pnl_shows_red(self, formatters_mixin):
        """Should show red indicator for negative P&L."""
        result = formatters_mixin._format_activity_card(daily_pnl=-100.00)

        assert "🔴" in result

    def test_includes_trade_stats(self, formatters_mixin):
        """Should include trade statistics."""
        result = formatters_mixin._format_activity_card(
            daily_trades=10,
            daily_wins=7,
            daily_losses=3,
        )

        assert "10" in result  # Total trades
        assert "7W" in result or "7" in result
        assert "3L" in result or "3" in result

    def test_includes_open_positions(self, formatters_mixin):
        """Should include open positions when present."""
        result = formatters_mixin._format_activity_card(
            open_positions=2,
            unrealized_pnl=50.00,
        )

        assert "Open" in result
        assert "2" in result

    def test_includes_unrealized_pnl(self, formatters_mixin):
        """Should include unrealized P&L."""
        result = formatters_mixin._format_activity_card(
            open_positions=1,
            unrealized_pnl=-25.00,
        )

        assert "Unrealized" in result
        assert "25" in result


class TestFormatSystemStatusCard:
    """Tests for _format_system_status_card method."""

    def test_includes_market_info(self, formatters_mixin):
        """Should include market and symbol."""
        result = formatters_mixin._format_system_status_card(
            agent_running=True,
            gateway_healthy=True,
            data_fresh=True,
            market="NQ",
            symbol="MNQ",
        )

        assert "NQ" in result
        assert "MNQ" in result

    def test_agent_running_shows_green(self, formatters_mixin):
        """Should show green status for running agent."""
        result = formatters_mixin._format_system_status_card(
            agent_running=True,
            gateway_healthy=True,
            data_fresh=True,
            market="NQ",
            symbol="MNQ",
        )

        assert "🟢" in result
        assert "RUNNING" in result

    def test_agent_stopped_shows_red(self, formatters_mixin):
        """Should show red status for stopped agent."""
        result = formatters_mixin._format_system_status_card(
            agent_running=False,
            gateway_healthy=True,
            data_fresh=True,
            market="NQ",
            symbol="MNQ",
        )

        assert "STOPPED" in result

    def test_gateway_status(self, formatters_mixin):
        """Should include gateway status."""
        result = formatters_mixin._format_system_status_card(
            agent_running=True,
            gateway_healthy=True,
            data_fresh=True,
            market="NQ",
            symbol="MNQ",
        )

        assert "Gateway" in result
        assert "ONLINE" in result

    def test_data_freshness(self, formatters_mixin):
        """Should include data freshness status."""
        result = formatters_mixin._format_system_status_card(
            agent_running=True,
            gateway_healthy=True,
            data_fresh=True,
            market="NQ",
            symbol="MNQ",
        )

        assert "Data" in result
        assert "FRESH" in result


class TestFormatHealthIndicators:
    """Tests for _format_health_indicators method."""

    def test_all_healthy(self, formatters_mixin):
        """Should show all green for healthy status."""
        result = formatters_mixin._format_health_indicators(
            gateway_ok=True,
            connection_ok=True,
            data_ok=True,
        )

        assert result.count("🟢") == 3

    def test_all_unhealthy(self, formatters_mixin):
        """Should show all red for unhealthy status."""
        result = formatters_mixin._format_health_indicators(
            gateway_ok=False,
            connection_ok=False,
            data_ok=False,
        )

        assert result.count("🔴") == 3

    def test_unknown_status(self, formatters_mixin):
        """Should show white circle for unknown status."""
        result = formatters_mixin._format_health_indicators(
            gateway_ok=None,
            connection_ok=None,
            data_ok=None,
        )

        assert result.count("⚪") == 3

    def test_mixed_status(self, formatters_mixin):
        """Should show mixed indicators."""
        result = formatters_mixin._format_health_indicators(
            gateway_ok=True,
            connection_ok=False,
            data_ok=None,
        )

        assert "🟢" in result
        assert "🔴" in result
        assert "⚪" in result


class TestFormatChallengeStatus:
    """Tests for _format_challenge_status method."""

    def test_includes_balance(self, formatters_mixin):
        """Should include current balance."""
        result = formatters_mixin._format_challenge_status(
            balance=51500.00,
            starting_balance=50000.00,
            profit_target=3000.00,
            max_drawdown=2000.00,
        )

        assert "51,500" in result or "51500" in result
        assert "Balance" in result

    def test_includes_pnl(self, formatters_mixin):
        """Should include P&L from starting."""
        result = formatters_mixin._format_challenge_status(
            balance=51500.00,
            starting_balance=50000.00,
            profit_target=3000.00,
            max_drawdown=2000.00,
        )

        assert "1,500" in result or "1500" in result
        assert "P&L" in result

    def test_positive_pnl_indicator(self, formatters_mixin):
        """Should show green for positive P&L."""
        result = formatters_mixin._format_challenge_status(
            balance=51000.00,
            starting_balance=50000.00,
            profit_target=3000.00,
            max_drawdown=2000.00,
        )

        assert "🟢" in result

    def test_negative_pnl_indicator(self, formatters_mixin):
        """Should show red for negative P&L."""
        result = formatters_mixin._format_challenge_status(
            balance=49000.00,
            starting_balance=50000.00,
            profit_target=3000.00,
            max_drawdown=2000.00,
        )

        assert "🔴" in result

    def test_includes_targets(self, formatters_mixin):
        """Should include profit target and max drawdown."""
        result = formatters_mixin._format_challenge_status(
            balance=50000.00,
            starting_balance=50000.00,
            profit_target=3000.00,
            max_drawdown=2000.00,
        )

        assert "Profit Target" in result
        assert "3,000" in result or "3000" in result
        assert "Max Drawdown" in result
        assert "2,000" in result or "2000" in result

    def test_shows_progress_when_positive(self, formatters_mixin):
        """Should show progress toward target when positive."""
        result = formatters_mixin._format_challenge_status(
            balance=51500.00,
            starting_balance=50000.00,
            profit_target=3000.00,
            max_drawdown=2000.00,
        )

        assert "Progress" in result
        assert "50" in result  # 50% progress

    def test_shows_drawdown_used_when_negative(self, formatters_mixin):
        """Should show drawdown used when negative."""
        result = formatters_mixin._format_challenge_status(
            balance=49000.00,
            starting_balance=50000.00,
            profit_target=3000.00,
            max_drawdown=2000.00,
        )

        assert "Drawdown" in result
        assert "50" in result  # 50% used

    def test_includes_trade_stats(self, formatters_mixin):
        """Should include trade statistics when provided."""
        result = formatters_mixin._format_challenge_status(
            balance=51000.00,
            starting_balance=50000.00,
            profit_target=3000.00,
            max_drawdown=2000.00,
            trades=20,
            wins=12,
        )

        assert "20" in result
        assert "60" in result  # 60% win rate


class TestFormatOnOff:
    """Tests for _format_onoff method."""

    def test_true_shows_on(self, formatters_mixin):
        """Should show ON for True."""
        result = formatters_mixin._format_onoff(True)

        assert "🟢" in result
        assert "ON" in result

    def test_false_shows_off(self, formatters_mixin):
        """Should show OFF for False."""
        result = formatters_mixin._format_onoff(False)

        assert "🔴" in result
        assert "OFF" in result
