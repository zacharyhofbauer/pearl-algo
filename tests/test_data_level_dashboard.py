"""
Tests for data level indicator in Telegram dashboard.

Verifies that format_home_card correctly displays data level status.
"""

import pytest


class TestDataLevelDashboard:
    """Tests for data level display in format_home_card."""

    def test_level1_data_not_shown_when_healthy(self):
        """Level 1 data should not show indicator (calm/minimal display)."""
        from pearlalgo.utils.telegram_alerts import format_home_card

        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=17500.0,
            data_level="level1",
        )

        # Level 1 should not add extra noise when healthy
        assert "📡 *Data:*" not in message

    def test_historical_data_shows_fallback_indicator(self):
        """Historical data level should show fallback indicator."""
        from pearlalgo.utils.telegram_alerts import format_home_card

        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=17500.0,
            data_level="historical",
        )

        assert "📡 *Data:*" in message
        assert "📜 Hist" in message

    def test_historical_fallback_shows_indicator(self):
        """historical_fallback level should also show indicator."""
        from pearlalgo.utils.telegram_alerts import format_home_card

        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=17500.0,
            data_level="historical_fallback",
        )

        assert "📡 *Data:*" in message
        assert "📜 Hist" in message

    def test_error_level_shows_error_indicator(self):
        """Error data level should show error indicator."""
        from pearlalgo.utils.telegram_alerts import format_home_card

        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=17500.0,
            data_level="error",
        )

        assert "📡 *Data:*" in message
        assert "❌ Err" in message

    def test_unknown_level_shows_unknown_indicator(self):
        """Unknown data level should show unknown indicator."""
        from pearlalgo.utils.telegram_alerts import format_home_card

        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=17500.0,
            data_level="unknown",
        )

        assert "📡 *Data:*" in message
        assert "❓ ?" in message

    def test_no_data_level_no_indicator(self):
        """When data_level is None, no indicator should be shown."""
        from pearlalgo.utils.telegram_alerts import format_home_card

        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=17500.0,
            data_level=None,
        )

        # Should not show data line when healthy/unknown
        assert "📡 *Data:*" not in message

    def test_data_level_case_insensitive(self):
        """Data level comparison should be case-insensitive."""
        from pearlalgo.utils.telegram_alerts import format_home_card

        # Test uppercase
        message_upper = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=17500.0,
            data_level="HISTORICAL",
        )

        assert "📜 Hist" in message_upper

        # Test mixed case
        message_mixed = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=17500.0,
            data_level="Level1",
        )

        # Level1 (any case) should not show extra indicator
        assert "📡 *Data:*" not in message_mixed





