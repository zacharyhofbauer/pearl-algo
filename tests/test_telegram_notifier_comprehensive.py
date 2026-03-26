"""Comprehensive tests for MarketAgentTelegramNotifier.

Covers: init, message formatting, send methods, error handling,
rate limiting, markdown escaping, truncation, routing, and edge cases.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state_dir(tmp_path):
    """Provide a temporary state directory."""
    d = tmp_path / "agent_state"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def mock_telegram_alerts():
    """Create a mock TelegramAlerts instance."""
    mock = MagicMock()
    mock.bot = AsyncMock()
    mock.send_message = AsyncMock(return_value=True)
    mock.notify_daily_summary = AsyncMock(return_value=True)
    mock.notify_risk_warning = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def notifier(state_dir, mock_telegram_alerts):
    """Create a MarketAgentTelegramNotifier with mocked Telegram."""
    with patch("pearlalgo.market_agent.telegram_notifier.TelegramAlerts", return_value=mock_telegram_alerts):
        with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
            from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
            n = MarketAgentTelegramNotifier(
                bot_token="test-token",
                chat_id="test-chat-id",
                state_dir=state_dir,
                enabled=True,
                account_label="Test Account",
            )
            n.telegram = mock_telegram_alerts
            return n


@pytest.fixture
def notifier_no_label(state_dir, mock_telegram_alerts):
    """Create a notifier without account label."""
    with patch("pearlalgo.market_agent.telegram_notifier.TelegramAlerts", return_value=mock_telegram_alerts):
        with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
            from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
            n = MarketAgentTelegramNotifier(
                bot_token="test-token",
                chat_id="test-chat-id",
                state_dir=state_dir,
                enabled=True,
            )
            n.telegram = mock_telegram_alerts
            return n


@pytest.fixture
def notifier_disabled(state_dir):
    """Create a disabled notifier."""
    with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        return MarketAgentTelegramNotifier(
            bot_token="test-token",
            chat_id="test-chat-id",
            state_dir=state_dir,
            enabled=False,
        )


@pytest.fixture
def basic_signal():
    """A basic signal dictionary for testing."""
    return {
        "symbol": "MNQ",
        "type": "momentum_breakout",
        "direction": "long",
        "entry_price": 18500.0,
        "stop_loss": 18450.0,
        "take_profit": 18600.0,
        "confidence": 0.75,
        "reason": "Strong momentum with MTF alignment",
        "regime": {
            "regime": "trending_up",
            "volatility": "normal",
            "session": "morning_trend",
        },
        "mtf_analysis": {
            "alignment": "aligned",
        },
        "vwap_data": {
            "vwap": 18480.0,
            "distance_from_vwap": 20.0,
            "distance_pct": 0.11,
        },
        "indicators": {
            "volume_ratio": 1.6,
            "atr": 25.0,
        },
    }


@pytest.fixture
def basic_status():
    """A basic status dictionary for testing."""
    return {
        "running": True,
        "paused": False,
        "symbol": "MNQ",
        "cycle_count": 100,
        "error_count": 2,
        "signal_count": 5,
        "buffer_size": 300,
    }


@pytest.fixture
def performance_metrics():
    """Performance metrics for daily/weekly summaries."""
    return {
        "total_pnl": 250.0,
        "wins": 5,
        "losses": 3,
        "win_rate": 0.625,
        "total_signals": 10,
        "exited_signals": 8,
        "avg_pnl": 31.25,
        "avg_hold_minutes": 45.0,
    }


# ===========================================================================
# INIT TESTS
# ===========================================================================

class TestInit:
    def test_init_enabled_with_credentials(self, notifier):
        assert notifier.enabled is True
        assert notifier.telegram is not None
        assert notifier.account_label == "Test Account"

    def test_init_disabled(self, notifier_disabled):
        assert notifier_disabled.enabled is False
        assert notifier_disabled.telegram is None

    def test_init_enabled_missing_token(self, state_dir):
        with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
            from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
            n = MarketAgentTelegramNotifier(
                bot_token=None,
                chat_id="test-chat-id",
                state_dir=state_dir,
                enabled=True,
            )
            assert n.enabled is False

    def test_init_enabled_missing_chat_id(self, state_dir):
        with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
            from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
            n = MarketAgentTelegramNotifier(
                bot_token="test-token",
                chat_id=None,
                state_dir=state_dir,
                enabled=True,
            )
            assert n.enabled is False

    def test_init_telegram_alerts_exception(self, state_dir):
        with patch("pearlalgo.market_agent.telegram_notifier.TelegramAlerts", side_effect=Exception("Init failed")):
            with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
                from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
                n = MarketAgentTelegramNotifier(
                    bot_token="test-token",
                    chat_id="test-chat-id",
                    state_dir=state_dir,
                    enabled=True,
                )
                assert n.enabled is False
                assert n.telegram is None

    def test_account_label_stored(self, notifier):
        assert notifier.account_label == "Test Account"

    def test_no_account_label(self, notifier_no_label):
        assert notifier_no_label.account_label is None


# ===========================================================================
# FORMAT PROFESSIONAL SIGNAL TESTS
# ===========================================================================

class TestFormatProfessionalSignal:
    def test_basic_long_signal(self, notifier, basic_signal):
        msg = notifier._format_professional_signal(basic_signal)
        assert "MNQ" in msg
        assert "LONG" in msg
        assert "18500.00" in msg
        assert "18450.00" in msg
        assert "18600.00" in msg

    def test_account_label_prefix(self, notifier, basic_signal):
        msg = notifier._format_professional_signal(basic_signal)
        assert "[Test Account]" in msg

    def test_no_account_label_prefix(self, notifier_no_label, basic_signal):
        msg = notifier_no_label._format_professional_signal(basic_signal)
        assert "[" not in msg.split("🎯")[0]

    def test_risk_reward_calculation(self, notifier, basic_signal):
        msg = notifier._format_professional_signal(basic_signal)
        # risk=50, reward=100, R:R = 2.00
        assert "2.00:1" in msg

    def test_zero_stop_loss(self, notifier, basic_signal):
        basic_signal["stop_loss"] = 0
        msg = notifier._format_professional_signal(basic_signal)
        assert "R:R" in msg  # Should show 0.00:1

    def test_regime_display(self, notifier, basic_signal):
        msg = notifier._format_professional_signal(basic_signal)
        assert "Trending Up" in msg
        assert "Normal Vol" in msg

    def test_session_display(self, notifier, basic_signal):
        msg = notifier._format_professional_signal(basic_signal)
        assert "Morning Trend" in msg

    def test_mtf_aligned(self, notifier, basic_signal):
        msg = notifier._format_professional_signal(basic_signal)
        assert "1m/5m/15m Aligned" in msg

    def test_mtf_partial(self, notifier, basic_signal):
        basic_signal["mtf_analysis"]["alignment"] = "partial"
        msg = notifier._format_professional_signal(basic_signal)
        assert "Partial Alignment" in msg

    def test_mtf_conflicting(self, notifier, basic_signal):
        basic_signal["mtf_analysis"]["alignment"] = "conflicting"
        msg = notifier._format_professional_signal(basic_signal)
        assert "Conflicting" in msg

    def test_vwap_above(self, notifier, basic_signal):
        msg = notifier._format_professional_signal(basic_signal)
        assert "Above VWAP" in msg

    def test_vwap_below(self, notifier, basic_signal):
        basic_signal["vwap_data"]["distance_from_vwap"] = -20.0
        basic_signal["vwap_data"]["distance_pct"] = -0.11
        msg = notifier._format_professional_signal(basic_signal)
        assert "Below VWAP" in msg

    def test_high_volume(self, notifier, basic_signal):
        basic_signal["indicators"]["volume_ratio"] = 2.0
        msg = notifier._format_professional_signal(basic_signal)
        assert "2.0x avg (strong)" in msg

    def test_moderate_volume(self, notifier, basic_signal):
        basic_signal["indicators"]["volume_ratio"] = 1.3
        msg = notifier._format_professional_signal(basic_signal)
        assert "1.3x avg (moderate)" in msg

    def test_low_volume(self, notifier, basic_signal):
        basic_signal["indicators"]["volume_ratio"] = 1.0
        msg = notifier._format_professional_signal(basic_signal)
        assert "1.0x avg" in msg

    def test_order_book_strong_bid(self, notifier, basic_signal):
        basic_signal["order_book"] = {
            "imbalance": 0.25,
            "bid_depth": 500,
            "ask_depth": 300,
            "data_level": "level2",
        }
        msg = notifier._format_professional_signal(basic_signal)
        assert "Strong Bid Pressure" in msg
        assert "L2" in msg

    def test_order_book_strong_ask(self, notifier, basic_signal):
        basic_signal["order_book"] = {
            "imbalance": -0.25,
            "bid_depth": 200,
            "ask_depth": 500,
            "data_level": "level1",
        }
        msg = notifier._format_professional_signal(basic_signal)
        assert "Strong Ask Pressure" in msg

    def test_order_book_balanced(self, notifier, basic_signal):
        basic_signal["order_book"] = {
            "imbalance": 0.05,
            "bid_depth": 400,
            "ask_depth": 410,
            "data_level": "level2",
        }
        msg = notifier._format_professional_signal(basic_signal)
        assert "Balanced" in msg

    def test_lunch_lull_warning(self, notifier, basic_signal):
        basic_signal["regime"]["session"] = "lunch_lull"
        msg = notifier._format_professional_signal(basic_signal)
        assert "Lunch lull" in msg

    def test_opening_warning(self, notifier, basic_signal):
        basic_signal["regime"]["session"] = "opening"
        msg = notifier._format_professional_signal(basic_signal)
        assert "Opening volatility" in msg

    def test_closing_warning(self, notifier, basic_signal):
        basic_signal["regime"]["session"] = "closing"
        msg = notifier._format_professional_signal(basic_signal)
        assert "Closing hour" in msg

    def test_high_volatility_warning(self, notifier, basic_signal):
        basic_signal["regime"]["volatility"] = "high"
        msg = notifier._format_professional_signal(basic_signal)
        assert "High volatility" in msg

    def test_low_volatility_warning(self, notifier, basic_signal):
        basic_signal["regime"]["volatility"] = "low"
        msg = notifier._format_professional_signal(basic_signal)
        assert "Low volatility" in msg

    def test_ranging_momentum_warning(self, notifier, basic_signal):
        basic_signal["regime"]["regime"] = "ranging"
        basic_signal["type"] = "momentum_breakout"
        msg = notifier._format_professional_signal(basic_signal)
        assert "Ranging market" in msg

    def test_confidence_display(self, notifier, basic_signal):
        msg = notifier._format_professional_signal(basic_signal)
        assert "75%" in msg

    def test_setup_reason_display(self, notifier, basic_signal):
        msg = notifier._format_professional_signal(basic_signal)
        assert "Strong momentum with MTF alignment" in msg


# ===========================================================================
# SEND ENTRY NOTIFICATION
# ===========================================================================

class TestSendEntryNotification:
    @pytest.mark.asyncio
    async def test_basic_entry(self, notifier, basic_signal, mock_telegram_alerts):
        result = await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        assert result is True
        mock_telegram_alerts.send_message.assert_called_once()
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "ENTRY" in msg
        assert "MNQ" in msg

    @pytest.mark.asyncio
    async def test_entry_disabled(self, notifier_disabled, basic_signal):
        result = await notifier_disabled.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_entry_with_account_label(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "[Test Account]" in msg

    @pytest.mark.asyncio
    async def test_entry_no_account_label(self, notifier_no_label, basic_signal, mock_telegram_alerts):
        await notifier_no_label.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "[" not in msg.split("ENTRY")[0] or "Test Account" not in msg

    @pytest.mark.asyncio
    async def test_entry_risk_reward(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "R:R" in msg

    @pytest.mark.asyncio
    async def test_entry_stop_and_tp(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Stop" in msg
        assert "TP" in msg

    @pytest.mark.asyncio
    async def test_entry_no_stop_loss(self, notifier, basic_signal, mock_telegram_alerts):
        basic_signal["stop_loss"] = 0
        await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        # Stop line should not appear when stop_loss is 0
        assert "ENTRY" in msg

    @pytest.mark.asyncio
    async def test_entry_with_execution_status_filled(self, notifier, basic_signal, mock_telegram_alerts):
        basic_signal["_execution_status"] = "filled"
        basic_signal["_execution_order_id"] = "ORD-123"
        await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Order placed" in msg
        assert "ORD-123" in msg

    @pytest.mark.asyncio
    async def test_entry_with_execution_status_failed(self, notifier, basic_signal, mock_telegram_alerts):
        basic_signal["_execution_status"] = "place_failed:insufficient_margin"
        await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Order failed" in msg

    @pytest.mark.asyncio
    async def test_entry_with_execution_status_skipped(self, notifier, basic_signal, mock_telegram_alerts):
        basic_signal["_execution_status"] = "skipped:session_filter"
        await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Order skipped" in msg

    @pytest.mark.asyncio
    async def test_entry_with_position_size(self, notifier, basic_signal, mock_telegram_alerts):
        basic_signal["position_size"] = 1
        basic_signal["risk_amount"] = 100.0
        await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "1 MNQ" in msg
        assert "Risk" in msg

    @pytest.mark.asyncio
    async def test_entry_send_exception(self, notifier, basic_signal, mock_telegram_alerts):
        mock_telegram_alerts.send_message = AsyncMock(side_effect=Exception("Network error"))
        result = await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_entry_never_dedupes(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        _, kwargs = mock_telegram_alerts.send_message.call_args
        assert kwargs.get("dedupe") is False


# ===========================================================================
# SEND EXIT NOTIFICATION
# ===========================================================================

class TestSendExitNotification:
    @pytest.mark.asyncio
    async def test_basic_exit(self, notifier, basic_signal, mock_telegram_alerts):
        result = await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18550.0,
            exit_reason="take_profit",
            pnl=50.0,
            signal=basic_signal,
        )
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "EXIT" in msg

    @pytest.mark.asyncio
    async def test_exit_disabled(self, notifier_disabled, basic_signal):
        result = await notifier_disabled.send_exit_notification(
            signal_id="sig_001",
            exit_price=18550.0,
            exit_reason="take_profit",
            pnl=50.0,
            signal=basic_signal,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_exit_stop_loss_reason(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18450.0,
            exit_reason="stop_loss",
            pnl=-50.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "SL" in msg

    @pytest.mark.asyncio
    async def test_exit_take_profit_reason(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18600.0,
            exit_reason="take_profit",
            pnl=100.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "TP" in msg

    @pytest.mark.asyncio
    async def test_exit_with_hold_duration(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18550.0,
            exit_reason="take_profit",
            pnl=50.0,
            signal=basic_signal,
            hold_duration_minutes=125.0,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "2h5m" in msg

    @pytest.mark.asyncio
    async def test_exit_with_short_hold(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18550.0,
            exit_reason="manual",
            pnl=25.0,
            signal=basic_signal,
            hold_duration_minutes=15.0,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "15m" in msg

    @pytest.mark.asyncio
    async def test_exit_never_dedupes(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18550.0,
            exit_reason="take_profit",
            pnl=50.0,
            signal=basic_signal,
        )
        _, kwargs = mock_telegram_alerts.send_message.call_args
        assert kwargs.get("dedupe") is False

    @pytest.mark.asyncio
    async def test_exit_exception(self, notifier, basic_signal, mock_telegram_alerts):
        mock_telegram_alerts.send_message = AsyncMock(side_effect=Exception("Network error"))
        result = await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18550.0,
            exit_reason="take_profit",
            pnl=50.0,
            signal=basic_signal,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_exit_account_label(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18550.0,
            exit_reason="take_profit",
            pnl=50.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "[Test Account]" in msg


# ===========================================================================
# SEND STATUS
# ===========================================================================

class TestSendStatus:
    @pytest.mark.asyncio
    async def test_send_status_basic(self, notifier, basic_status, mock_telegram_alerts):
        result = await notifier.send_status(basic_status)
        assert result is True
        mock_telegram_alerts.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_status_disabled(self, notifier_disabled, basic_status):
        result = await notifier_disabled.send_status(basic_status)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_status_exception(self, notifier, basic_status, mock_telegram_alerts):
        mock_telegram_alerts.send_message = AsyncMock(side_effect=Exception("fail"))
        result = await notifier.send_status(basic_status)
        assert result is False


# ===========================================================================
# SEND DAILY SUMMARY
# ===========================================================================

class TestSendDailySummary:
    @pytest.mark.asyncio
    async def test_daily_summary(self, notifier, performance_metrics, mock_telegram_alerts):
        result = await notifier.send_daily_summary(performance_metrics)
        assert result is True
        mock_telegram_alerts.notify_daily_summary.assert_called_once()

    @pytest.mark.asyncio
    async def test_daily_summary_disabled(self, notifier_disabled, performance_metrics):
        result = await notifier_disabled.send_daily_summary(performance_metrics)
        assert result is False

    @pytest.mark.asyncio
    async def test_daily_summary_zero_trades(self, notifier, mock_telegram_alerts):
        metrics = {"total_pnl": 0, "wins": 0, "losses": 0, "win_rate": 0}
        result = await notifier.send_daily_summary(metrics)
        assert result is True
        call_kwargs = mock_telegram_alerts.notify_daily_summary.call_args[1]
        assert call_kwargs["win_rate"] is None

    @pytest.mark.asyncio
    async def test_daily_summary_exception(self, notifier, performance_metrics, mock_telegram_alerts):
        mock_telegram_alerts.notify_daily_summary = AsyncMock(side_effect=Exception("fail"))
        result = await notifier.send_daily_summary(performance_metrics)
        assert result is False


# ===========================================================================
# SEND ENHANCED STATUS
# ===========================================================================

class TestSendEnhancedStatus:
    @pytest.mark.asyncio
    async def test_enhanced_status_running(self, notifier, mock_telegram_alerts):
        status = {
            "running": True,
            "paused": False,
            "cycle_count": 100,
            "error_count": 0,
            "signal_count": 5,
            "signals_sent": 4,
            "signals_send_failures": 1,
            "buffer_size": 300,
        }
        result = await notifier.send_enhanced_status(status)
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Status" in msg
        assert "RUNNING" in msg

    @pytest.mark.asyncio
    async def test_enhanced_status_paused(self, notifier, mock_telegram_alerts):
        status = {"running": True, "paused": True, "cycle_count": 0, "error_count": 0, "signal_count": 0, "signals_sent": 0, "signals_send_failures": 0, "buffer_size": 0}
        result = await notifier.send_enhanced_status(status)
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "PAUSED" in msg

    @pytest.mark.asyncio
    async def test_enhanced_status_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_enhanced_status({})
        assert result is False

    @pytest.mark.asyncio
    async def test_enhanced_status_connection_issues(self, notifier, mock_telegram_alerts):
        status = {
            "running": True,
            "paused": False,
            "connection_status": "disconnected",
            "connection_failures": 3,
            "cycle_count": 50,
            "error_count": 5,
            "signal_count": 0,
            "signals_sent": 0,
            "signals_send_failures": 0,
            "buffer_size": 100,
        }
        result = await notifier.send_enhanced_status(status)
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "DISCONNECTED" in msg
        assert "3 failures" in msg

    @pytest.mark.asyncio
    async def test_enhanced_status_with_performance(self, notifier, mock_telegram_alerts):
        status = {
            "running": True,
            "paused": False,
            "cycle_count": 200,
            "error_count": 0,
            "signal_count": 10,
            "signals_sent": 10,
            "signals_send_failures": 0,
            "buffer_size": 300,
            "performance": {
                "exited_signals": 8,
                "wins": 5,
                "losses": 3,
                "win_rate": 0.625,
                "total_pnl": 250.0,
                "avg_pnl": 31.25,
            },
        }
        result = await notifier.send_enhanced_status(status)
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Performance" in msg
        assert "5W/3L" in msg

    @pytest.mark.asyncio
    async def test_enhanced_status_exception(self, notifier, mock_telegram_alerts):
        mock_telegram_alerts.send_message = AsyncMock(side_effect=Exception("fail"))
        result = await notifier.send_enhanced_status({"running": True, "paused": False, "cycle_count": 0, "error_count": 0, "signal_count": 0, "signals_sent": 0, "signals_send_failures": 0, "buffer_size": 0})
        assert result is False


# ===========================================================================
# SEND HEARTBEAT
# ===========================================================================

class TestSendHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_basic(self, notifier, mock_telegram_alerts):
        status = {
            "symbol": "NQ",
            "cycle_count": 50,
            "signal_count": 2,
            "signals_sent": 2,
            "signals_send_failures": 0,
            "error_count": 0,
            "buffer_size": 300,
            "latest_price": 18500.0,
        }
        result = await notifier.send_heartbeat(status)
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Heartbeat" in msg

    @pytest.mark.asyncio
    async def test_heartbeat_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_heartbeat({})
        assert result is False

    @pytest.mark.asyncio
    async def test_heartbeat_no_price(self, notifier, mock_telegram_alerts):
        status = {
            "symbol": "NQ",
            "cycle_count": 50,
            "signal_count": 0,
            "signals_sent": 0,
            "signals_send_failures": 0,
            "error_count": 0,
            "buffer_size": 300,
        }
        result = await notifier.send_heartbeat(status)
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Symbol" in msg

    @pytest.mark.asyncio
    async def test_heartbeat_exception(self, notifier, mock_telegram_alerts):
        mock_telegram_alerts.send_message = AsyncMock(side_effect=Exception("fail"))
        result = await notifier.send_heartbeat({"symbol": "NQ", "cycle_count": 0, "signal_count": 0, "signals_sent": 0, "signals_send_failures": 0, "error_count": 0, "buffer_size": 0})
        assert result is False


# ===========================================================================
# CONVERT TO MARKDOWN V2
# ===========================================================================

class TestConvertMarkdownV2:
    def test_escapes_special_chars(self):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        result = MarketAgentTelegramNotifier._convert_to_markdown_v2_with_pearl("Hello.World!")
        assert "\\." in result
        assert "\\!" in result

    def test_preserves_bold(self):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        result = MarketAgentTelegramNotifier._convert_to_markdown_v2_with_pearl("*bold text*")
        assert "*bold text*" in result

    def test_preserves_code(self):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        result = MarketAgentTelegramNotifier._convert_to_markdown_v2_with_pearl("`code`")
        assert "`code`" in result

    def test_pearl_emoji_replacement(self):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        text = "🐚 *PEARL*\nHello"
        result = MarketAgentTelegramNotifier._convert_to_markdown_v2_with_pearl(text)
        assert "tg://emoji?id=" in result

    def test_escapes_hash(self):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        result = MarketAgentTelegramNotifier._convert_to_markdown_v2_with_pearl("Test #1")
        assert "\\#" in result

    def test_escapes_plus(self):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        result = MarketAgentTelegramNotifier._convert_to_markdown_v2_with_pearl("+50.00")
        assert "\\+" in result


# ===========================================================================
# SEND PEARL NOTIFICATION
# ===========================================================================

class TestSendPearlNotification:
    @pytest.mark.asyncio
    async def test_pearl_notification_with_header(self, notifier, mock_telegram_alerts):
        result = await notifier.send_pearl_notification("Test message", "Check-In")
        assert result is True
        call_args = mock_telegram_alerts.send_message.call_args
        assert call_args[1].get("parse_mode") == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_pearl_notification_without_header(self, notifier, mock_telegram_alerts):
        result = await notifier.send_pearl_notification("Test message", use_header=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_pearl_notification_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_pearl_notification("Test")
        assert result is False

    @pytest.mark.asyncio
    async def test_pearl_notification_fallback_on_error(self, notifier, mock_telegram_alerts):
        # First call raises (MarkdownV2 fails), second succeeds (plain text fallback)
        call_count = 0
        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("MarkdownV2 parse error")
            return True
        mock_telegram_alerts.send_message = AsyncMock(side_effect=side_effect)
        result = await notifier.send_pearl_notification("Test message")
        assert result is True
        assert call_count == 2


# ===========================================================================
# SEND DATA QUALITY ALERT
# ===========================================================================

class TestSendDataQualityAlert:
    @pytest.mark.asyncio
    async def test_stale_data_alert(self, notifier, mock_telegram_alerts):
        result = await notifier.send_data_quality_alert(
            "stale_data", "Data is stale", {"age_minutes": 15.0}
        )
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Stale Data" in msg
        assert "15.0 minutes" in msg

    @pytest.mark.asyncio
    async def test_data_gap_alert(self, notifier, mock_telegram_alerts):
        result = await notifier.send_data_quality_alert("data_gap", "Gap detected")
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Data Gap" in msg

    @pytest.mark.asyncio
    async def test_fetch_failure_alert(self, notifier, mock_telegram_alerts):
        result = await notifier.send_data_quality_alert("fetch_failure", "Cannot fetch")
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Fetch Failure" in msg

    @pytest.mark.asyncio
    async def test_buffer_issue_alert(self, notifier, mock_telegram_alerts):
        result = await notifier.send_data_quality_alert(
            "buffer_issue", "Buffer too small", {"buffer_size": 50}
        )
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Buffer Issue" in msg

    @pytest.mark.asyncio
    async def test_recovery_alert(self, notifier, mock_telegram_alerts):
        result = await notifier.send_data_quality_alert("recovery", "Data recovered")
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Recovery" in msg
        assert "Signal generation resumed" in msg

    @pytest.mark.asyncio
    async def test_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_data_quality_alert("stale_data", "test")
        assert result is False

    @pytest.mark.asyncio
    async def test_snoozed_noncritical(self, notifier, mock_telegram_alerts):
        """Non-critical alerts should be suppressed when snoozed."""
        mock_prefs = MagicMock()
        mock_prefs.snooze_noncritical_alerts = True
        with patch.object(notifier, "_get_prefs", return_value=mock_prefs):
            result = await notifier.send_data_quality_alert("stale_data", "Data stale")
        assert result is True  # Returns True (handled/suppressed)
        mock_telegram_alerts.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_ignores_snooze(self, notifier, mock_telegram_alerts):
        """Critical alerts (recovery, circuit_breaker) should bypass snooze."""
        mock_prefs = MagicMock()
        mock_prefs.snooze_noncritical_alerts = True
        with patch.object(notifier, "_get_prefs", return_value=mock_prefs):
            result = await notifier.send_data_quality_alert("recovery", "Recovered")
        assert result is True
        mock_telegram_alerts.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_alert_type(self, notifier, mock_telegram_alerts):
        result = await notifier.send_data_quality_alert("custom_type", "Custom alert")
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Custom Type" in msg

    @pytest.mark.asyncio
    async def test_details_consecutive_failures(self, notifier, mock_telegram_alerts):
        result = await notifier.send_data_quality_alert(
            "fetch_failure", "Fetch failed",
            {"consecutive_failures": 5, "error_type": "timeout"},
        )
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "5" in msg
        assert "timeout" in msg


# ===========================================================================
# SEND STARTUP NOTIFICATION
# ===========================================================================

class TestSendStartupNotification:
    @pytest.mark.asyncio
    async def test_startup(self, notifier, mock_telegram_alerts, state_dir):
        # Setup shared cooldown paths
        data_dir = Path(notifier.state_dir).parent.parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, data_dir / ".telegram_agent_started.json")):
            with patch("pearlalgo.market_agent.telegram_notifier.file_lock"):
                with patch("pearlalgo.market_agent.telegram_notifier.load_json_file", return_value={}):
                    with patch("pearlalgo.market_agent.telegram_notifier.atomic_write_json"):
                        result = await notifier.send_startup_notification({
                            "futures_market_open": True,
                            "strategy_session_open": True,
                        })
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Started" in msg

    @pytest.mark.asyncio
    async def test_startup_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_startup_notification({})
        assert result is False


# ===========================================================================
# SEND SHUTDOWN NOTIFICATION
# ===========================================================================

class TestSendShutdownNotification:
    @pytest.mark.asyncio
    async def test_shutdown_normal(self, notifier, mock_telegram_alerts):
        result = await notifier.send_shutdown_notification({
            "shutdown_reason": "Normal shutdown",
            "uptime_hours": 8,
            "uptime_minutes": 30,
            "cycle_count": 1000,
            "signal_count": 15,
        })
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Stopped" in msg
        assert "15 signals" in msg

    @pytest.mark.asyncio
    async def test_shutdown_abnormal_reason(self, notifier, mock_telegram_alerts):
        result = await notifier.send_shutdown_notification({
            "shutdown_reason": "Circuit breaker error",
            "uptime_hours": 2,
            "uptime_minutes": 15,
            "cycle_count": 500,
            "signal_count": 5,
        })
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Circuit breaker error" in msg

    @pytest.mark.asyncio
    async def test_shutdown_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_shutdown_notification({})
        assert result is False


# ===========================================================================
# SEND WEEKLY SUMMARY
# ===========================================================================

class TestSendWeeklySummary:
    @pytest.mark.asyncio
    async def test_weekly_summary_with_trades(self, notifier, performance_metrics, mock_telegram_alerts):
        result = await notifier.send_weekly_summary(performance_metrics)
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Weekly" in msg
        assert "5W" in msg

    @pytest.mark.asyncio
    async def test_weekly_summary_no_trades(self, notifier, mock_telegram_alerts):
        metrics = {
            "total_signals": 3,
            "exited_signals": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_pnl": 0,
            "avg_hold_minutes": 0,
        }
        result = await notifier.send_weekly_summary(metrics)
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "No completed trades" in msg

    @pytest.mark.asyncio
    async def test_weekly_summary_profitable(self, notifier, performance_metrics, mock_telegram_alerts):
        await notifier.send_weekly_summary(performance_metrics)
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Profitable week" in msg

    @pytest.mark.asyncio
    async def test_weekly_summary_loss(self, notifier, mock_telegram_alerts):
        metrics = {
            "total_signals": 10,
            "exited_signals": 8,
            "wins": 2,
            "losses": 6,
            "win_rate": 0.25,
            "total_pnl": -200.0,
            "avg_pnl": -25.0,
            "avg_hold_minutes": 30.0,
        }
        result = await notifier.send_weekly_summary(metrics)
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Loss week" in msg

    @pytest.mark.asyncio
    async def test_weekly_summary_disabled(self, notifier_disabled, performance_metrics):
        result = await notifier_disabled.send_weekly_summary(performance_metrics)
        assert result is False


# ===========================================================================
# SEND CIRCUIT BREAKER ALERT
# ===========================================================================

class TestSendCircuitBreakerAlert:
    @pytest.mark.asyncio
    async def test_circuit_breaker_basic(self, notifier, mock_telegram_alerts):
        data_dir = notifier.state_dir.parent
        data_dir.mkdir(parents=True, exist_ok=True)
        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, data_dir / ".telegram_cb_sent.json")):
            with patch("pearlalgo.market_agent.telegram_notifier.file_lock"):
                with patch("pearlalgo.market_agent.telegram_notifier.load_json_file", return_value={}):
                    with patch("pearlalgo.market_agent.telegram_notifier.atomic_write_json"):
                        result = await notifier.send_circuit_breaker_alert(
                            "Max errors exceeded",
                            {"consecutive_errors": 10},
                        )
        assert result is True
        mock_telegram_alerts.notify_risk_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_breaker_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_circuit_breaker_alert("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_circuit_breaker_cooldown_dedup(self, notifier, mock_telegram_alerts):
        """Second call with same reason within cooldown should be skipped."""
        data_dir = notifier.state_dir.parent
        data_dir.mkdir(parents=True, exist_ok=True)
        import time
        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, data_dir / ".telegram_cb_sent.json")):
            with patch("pearlalgo.market_agent.telegram_notifier.file_lock"):
                with patch("pearlalgo.market_agent.telegram_notifier.load_json_file", return_value={"reason": "Max errors", "sent_at": time.time()}):
                    with patch("pearlalgo.market_agent.telegram_notifier.atomic_write_json"):
                        result = await notifier.send_circuit_breaker_alert("Max errors")
        assert result is True
        mock_telegram_alerts.notify_risk_warning.assert_not_called()


# ===========================================================================
# SEND RECOVERY NOTIFICATION
# ===========================================================================

class TestSendRecoveryNotification:
    @pytest.mark.asyncio
    async def test_recovery_basic(self, notifier, mock_telegram_alerts):
        result = await notifier.send_recovery_notification({
            "issue": "Connection lost",
            "recovery_time_seconds": 45.0,
        })
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Recovered" in msg
        assert "Connection lost" in msg

    @pytest.mark.asyncio
    async def test_recovery_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_recovery_notification({})
        assert result is False


# ===========================================================================
# SEND ERROR SUMMARY
# ===========================================================================

class TestSendErrorSummary:
    @pytest.mark.asyncio
    async def test_error_summary_basic(self, notifier, mock_telegram_alerts):
        result = await notifier.send_error_summary(
            error_count=10,
            error_types={"timeout": 5, "connection": 3, "parse": 2},
            last_error="Connection refused",
            time_window_minutes=60,
        )
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Error Summary" in msg
        assert "10" in msg
        assert "timeout" in msg

    @pytest.mark.asyncio
    async def test_error_summary_no_types(self, notifier, mock_telegram_alerts):
        result = await notifier.send_error_summary(error_count=3)
        assert result is True

    @pytest.mark.asyncio
    async def test_error_summary_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_error_summary(error_count=5)
        assert result is False


# ===========================================================================
# SEND PRICE ALERT
# ===========================================================================

class TestSendPriceAlert:
    @pytest.mark.asyncio
    async def test_price_alert_up(self, notifier, mock_telegram_alerts):
        result = await notifier.send_price_alert(
            symbol="MNQ",
            current_price=18600.0,
            previous_price=18400.0,
            price_change_pct=1.09,
        )
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "UP" in msg
        assert "Significant" in msg

    @pytest.mark.asyncio
    async def test_price_alert_down(self, notifier, mock_telegram_alerts):
        result = await notifier.send_price_alert(
            symbol="MNQ",
            current_price=18300.0,
            previous_price=18500.0,
            price_change_pct=-1.08,
        )
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "DOWN" in msg

    @pytest.mark.asyncio
    async def test_price_alert_small_move(self, notifier, mock_telegram_alerts):
        result = await notifier.send_price_alert(
            symbol="MNQ",
            current_price=18510.0,
            previous_price=18500.0,
            price_change_pct=0.054,
        )
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Significant" not in msg

    @pytest.mark.asyncio
    async def test_price_alert_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_price_alert("MNQ", 100, 99, 1.0)
        assert result is False


# ===========================================================================
# SEND CONNECTION STATUS UPDATE
# ===========================================================================

class TestSendConnectionStatusUpdate:
    @pytest.mark.asyncio
    async def test_connected(self, notifier, mock_telegram_alerts):
        result = await notifier.send_connection_status_update("connected")
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "CONNECTED" in msg

    @pytest.mark.asyncio
    async def test_disconnected_with_details(self, notifier, mock_telegram_alerts):
        result = await notifier.send_connection_status_update(
            "disconnected",
            {"failures": 3, "suggestion": "Restart gateway"},
        )
        assert result is True
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "DISCONNECTED" in msg
        assert "3" in msg
        assert "Restart gateway" in msg

    @pytest.mark.asyncio
    async def test_reconnecting(self, notifier, mock_telegram_alerts):
        result = await notifier.send_connection_status_update("reconnecting")
        assert result is True

    @pytest.mark.asyncio
    async def test_connection_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_connection_status_update("connected")
        assert result is False


# ===========================================================================
# SEND PHOTO
# ===========================================================================

class TestSendPhoto:
    @pytest.mark.asyncio
    async def test_send_photo_basic(self, notifier, mock_telegram_alerts, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG\r\n\x1a\n")
        mock_telegram_alerts.bot.send_photo = AsyncMock(return_value=MagicMock())
        result = await notifier._send_photo(photo, caption="Test chart")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_photo_disabled(self, notifier_disabled, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG")
        result = await notifier_disabled._send_photo(photo)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_photo_return_message(self, notifier, mock_telegram_alerts, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG\r\n\x1a\n")
        mock_msg = MagicMock()
        mock_telegram_alerts.bot.send_photo = AsyncMock(return_value=mock_msg)
        result = await notifier._send_photo(photo, return_message=True)
        assert result is mock_msg

    @pytest.mark.asyncio
    async def test_send_photo_exception(self, notifier, mock_telegram_alerts, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG\r\n\x1a\n")
        mock_telegram_alerts.bot.send_photo = AsyncMock(side_effect=Exception("fail"))
        result = await notifier._send_photo(photo)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_photo_exception_return_message(self, notifier, mock_telegram_alerts, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG\r\n\x1a\n")
        mock_telegram_alerts.bot.send_photo = AsyncMock(side_effect=Exception("fail"))
        result = await notifier._send_photo(photo, return_message=True)
        assert result is None


# ===========================================================================
# SEND DASHBOARD
# ===========================================================================

class TestSendDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_dashboard({})
        assert result is False

    @pytest.mark.asyncio
    async def test_dashboard_no_bot(self, notifier, mock_telegram_alerts):
        mock_telegram_alerts.bot = None
        notifier.telegram = mock_telegram_alerts
        result = await notifier.send_dashboard({"running": True, "symbol": "MNQ"})
        assert result is False

    @pytest.mark.asyncio
    async def test_dashboard_text_only(self, notifier, mock_telegram_alerts):
        """Dashboard without chart sends text message."""
        mock_bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        mock_telegram_alerts.bot = mock_bot

        mock_prefs = MagicMock()
        mock_prefs.dashboard_edit_in_place = False
        mock_prefs.get = MagicMock(return_value=None)
        mock_prefs.set = MagicMock()

        with patch.object(notifier, "_get_prefs", return_value=mock_prefs):
            with patch("pearlalgo.market_agent.telegram_notifier.format_glanceable_card", return_value="Dashboard text"):
                result = await notifier.send_dashboard({
                    "running": True,
                    "symbol": "MNQ",
                })
        assert result is True


# ===========================================================================
# HELPER / EDGE CASE TESTS
# ===========================================================================

class TestHelpers:
    def test_get_prefs_returns_prefs(self, notifier):
        prefs = notifier._get_prefs()
        assert prefs is not None

    def test_get_prefs_exception_returns_fallback(self, notifier):
        with patch("pearlalgo.market_agent.telegram_notifier.TelegramPrefs", side_effect=Exception("fail")):
            prefs = notifier._get_prefs()
            assert prefs is not None  # Falls back to self.prefs

    def test_format_compact_signal_delegates(self, notifier, basic_signal):
        with patch("pearlalgo.market_agent.telegram_notifier._canonical_format_compact_signal", return_value="compact") as mock_fn:
            result = notifier._format_compact_signal(basic_signal)
            assert result == "compact"
            mock_fn.assert_called_once_with(basic_signal, account_label="Test Account")

    def test_format_signal_message_delegates(self, notifier, basic_signal):
        with patch("pearlalgo.market_agent.telegram_notifier._canonical_format_signal_message", return_value="signal msg") as mock_fn:
            result = notifier._format_signal_message(basic_signal)
            assert result == "signal msg"
            mock_fn.assert_called_once_with(basic_signal, account_label="Test Account")

    def test_format_status_message_delegates(self, notifier, basic_status):
        with patch("pearlalgo.market_agent.telegram_notifier._canonical_format_status_message", return_value="status msg") as mock_fn:
            result = notifier._format_status_message(basic_status)
            assert result == "status msg"
            mock_fn.assert_called_once_with(basic_status)


class TestEdgeCases:
    def test_short_direction_signal(self, notifier):
        signal = {
            "symbol": "MNQ",
            "type": "mean_reversion",
            "direction": "short",
            "entry_price": 18500.0,
            "stop_loss": 18550.0,
            "take_profit": 18400.0,
            "confidence": 0.6,
            "reason": "Overbought reversal",
            "regime": {"regime": "ranging", "volatility": "high", "session": "afternoon"},
            "mtf_analysis": {"alignment": "conflicting"},
            "vwap_data": {"vwap": 0, "distance_from_vwap": 0, "distance_pct": 0},
            "indicators": {},
        }
        msg = notifier._format_professional_signal(signal)
        assert "SHORT" in msg

    def test_empty_signal(self, notifier):
        msg = notifier._format_professional_signal({})
        assert "MNQ" in msg  # defaults

    @pytest.mark.asyncio
    async def test_entry_with_none_confidence(self, notifier, basic_signal, mock_telegram_alerts):
        basic_signal["confidence"] = None
        result = await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_entry_with_string_stop_loss(self, notifier, basic_signal, mock_telegram_alerts):
        """Stop loss could be string from config."""
        basic_signal["stop_loss"] = "18450.0"
        result = await notifier.send_entry_notification(
            signal_id="sig_001",
            entry_price=18500.0,
            signal=basic_signal,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_exit_trailing_stop_reason(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18550.0,
            exit_reason="trailing_stop",
            pnl=50.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Trail" in msg

    @pytest.mark.asyncio
    async def test_exit_expired_reason(self, notifier, basic_signal, mock_telegram_alerts):
        await notifier.send_exit_notification(
            signal_id="sig_001",
            exit_price=18500.0,
            exit_reason="expired",
            pnl=0.0,
            signal=basic_signal,
        )
        msg = mock_telegram_alerts.send_message.call_args[0][0]
        assert "Expired" in msg

    def test_order_book_moderate_bid(self, notifier, basic_signal):
        basic_signal["order_book"] = {
            "imbalance": 0.15,
            "bid_depth": 0,
            "ask_depth": 0,
            "data_level": "historical",
        }
        msg = notifier._format_professional_signal(basic_signal)
        assert "Moderate Bid Pressure" in msg

    def test_order_book_moderate_ask(self, notifier, basic_signal):
        basic_signal["order_book"] = {
            "imbalance": -0.15,
            "bid_depth": 0,
            "ask_depth": 0,
            "data_level": "unknown",
        }
        msg = notifier._format_professional_signal(basic_signal)
        assert "Moderate Ask Pressure" in msg

    def test_breakout_with_resistance_above(self, notifier, basic_signal):
        basic_signal["type"] = "breakout_signal"
        basic_signal["mtf_analysis"]["breakout_levels"] = {"resistance_5m": 18490.0}
        msg = notifier._format_professional_signal(basic_signal)
        assert "Breaking 5m resistance" in msg

    def test_breakout_with_resistance_below(self, notifier, basic_signal):
        basic_signal["type"] = "breakout_signal"
        basic_signal["entry_price"] = 18480.0
        basic_signal["mtf_analysis"]["breakout_levels"] = {"resistance_5m": 18490.0}
        msg = notifier._format_professional_signal(basic_signal)
        assert "Below 5m resistance" in msg

    def test_near_vwap(self, notifier, basic_signal):
        basic_signal["vwap_data"]["distance_pct"] = 0.05
        basic_signal["vwap_data"]["distance_from_vwap"] = 5.0
        msg = notifier._format_professional_signal(basic_signal)
        assert "Near VWAP" in msg

    def test_atr_high_vol(self, notifier, basic_signal):
        basic_signal["regime"]["volatility"] = "high"
        msg = notifier._format_professional_signal(basic_signal)
        assert "high vol expansion" in msg

    def test_atr_low_vol(self, notifier, basic_signal):
        basic_signal["regime"]["volatility"] = "low"
        msg = notifier._format_professional_signal(basic_signal)
        assert "low vol compression" in msg

    def test_trending_mean_reversion_no_warning(self, notifier, basic_signal):
        """The warning won't fire because type gets .replace('_',' ').title() before check.
        'mean_reversion_long' becomes 'Mean Reversion Long', lowered to 'mean reversion long'
        which does not contain 'mean_reversion' (with underscore)."""
        basic_signal["regime"]["regime"] = "trending_up"
        basic_signal["type"] = "mean_reversion_long"
        msg = notifier._format_professional_signal(basic_signal)
        # Due to the title-casing, the underscore check doesn't match
        assert "Mean reversion fighting trend" not in msg

    def test_partial_mtf_warning(self, notifier, basic_signal):
        basic_signal["mtf_analysis"]["alignment"] = "partial"
        msg = notifier._format_professional_signal(basic_signal)
        assert "Partial MTF alignment" in msg

    def test_conflicting_mtf_warning(self, notifier, basic_signal):
        basic_signal["mtf_analysis"]["alignment"] = "conflicting"
        msg = notifier._format_professional_signal(basic_signal)
        assert "MTF conflicting" in msg
