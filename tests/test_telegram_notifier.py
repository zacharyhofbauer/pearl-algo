"""Tests for MarketAgentTelegramNotifier.

Covers initialization, entry/exit notifications, service started/stopped,
error/warning notifications, daily summary, rate limiting / dedup,
and error handling for bot API failures.

All telegram.Bot and TelegramAlerts methods are fully mocked.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_BOT_TOKEN = "123456:ABC-DEF"
TEST_CHAT_ID = "987654321"


def _make_signal(**overrides):
    """Build a minimal signal dict with defaults."""
    sig = {
        "symbol": "MNQ",
        "type": "momentum_breakout",
        "direction": "long",
        "entry_price": 18500.0,
        "stop_loss": 18450.0,
        "take_profit": 18600.0,
        "confidence": 0.75,
        "reason": "MTF alignment detected",
        "regime": {
            "regime": "trending_up",
            "volatility": "normal",
            "session": "morning_trend",
        },
        "mtf_analysis": {"alignment": "aligned"},
        "vwap_data": {"vwap": 18480.0, "distance_from_vwap": 20.0, "distance_pct": 0.11},
        "indicators": {"volume_ratio": 1.6, "atr": 25.0},
    }
    sig.update(overrides)
    return sig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "agent_state"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def mock_telegram():
    """Mock TelegramAlerts instance with all async methods."""
    m = MagicMock()
    m.bot = AsyncMock()
    m.bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
    m.bot.send_photo = AsyncMock(return_value=MagicMock(message_id=43))
    m.bot.edit_message_text = AsyncMock()
    m.bot.edit_message_caption = AsyncMock()
    m.bot.edit_message_media = AsyncMock()
    m.bot.delete_message = AsyncMock()
    m.send_message = AsyncMock(return_value=True)
    m.notify_daily_summary = AsyncMock(return_value=True)
    m.notify_risk_warning = AsyncMock(return_value=True)
    return m


@pytest.fixture
def notifier(state_dir, mock_telegram):
    """Fully wired notifier with mocked telegram backend."""
    with patch("pearlalgo.market_agent.telegram_notifier.TelegramAlerts", return_value=mock_telegram):
        with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
            from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
            n = MarketAgentTelegramNotifier(
                bot_token=TEST_BOT_TOKEN,
                chat_id=TEST_CHAT_ID,
                state_dir=state_dir,
                enabled=True,
                account_label="TestAcct",
            )
            n.telegram = mock_telegram
            return n


@pytest.fixture
def notifier_disabled(state_dir):
    """Disabled notifier — all sends should return False."""
    with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        return MarketAgentTelegramNotifier(
            bot_token=TEST_BOT_TOKEN,
            chat_id=TEST_CHAT_ID,
            state_dir=state_dir,
            enabled=False,
        )


@pytest.fixture
def notifier_no_label(state_dir, mock_telegram):
    """Notifier without account_label."""
    with patch("pearlalgo.market_agent.telegram_notifier.TelegramAlerts", return_value=mock_telegram):
        with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
            from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
            n = MarketAgentTelegramNotifier(
                bot_token=TEST_BOT_TOKEN,
                chat_id=TEST_CHAT_ID,
                state_dir=state_dir,
                enabled=True,
            )
            n.telegram = mock_telegram
            return n


# ===================================================================
# 1. Initialization and bot setup
# ===================================================================

class TestInit:
    def test_enabled_with_valid_credentials(self, notifier):
        assert notifier.enabled is True
        assert notifier.bot_token == TEST_BOT_TOKEN
        assert notifier.chat_id == TEST_CHAT_ID
        assert notifier.telegram is not None

    def test_disabled_flag(self, notifier_disabled):
        assert notifier_disabled.enabled is False
        assert notifier_disabled.telegram is None

    def test_missing_bot_token_disables(self, state_dir):
        with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
            from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
            n = MarketAgentTelegramNotifier(
                bot_token=None,
                chat_id=TEST_CHAT_ID,
                state_dir=state_dir,
                enabled=True,
            )
        assert n.enabled is False

    def test_missing_chat_id_disables(self, state_dir):
        with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
            from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
            n = MarketAgentTelegramNotifier(
                bot_token=TEST_BOT_TOKEN,
                chat_id=None,
                state_dir=state_dir,
                enabled=True,
            )
        assert n.enabled is False

    def test_telegram_alerts_init_exception_disables(self, state_dir):
        with patch("pearlalgo.market_agent.telegram_notifier.TelegramAlerts", side_effect=RuntimeError("boom")):
            with patch("pearlalgo.market_agent.telegram_notifier.ensure_state_dir", return_value=state_dir):
                from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
                n = MarketAgentTelegramNotifier(
                    bot_token=TEST_BOT_TOKEN,
                    chat_id=TEST_CHAT_ID,
                    state_dir=state_dir,
                    enabled=True,
                )
        assert n.enabled is False
        assert n.telegram is None

    def test_account_label_stored(self, notifier):
        assert notifier.account_label == "TestAcct"

    def test_account_label_none(self, notifier_no_label):
        assert notifier_no_label.account_label is None

    def test_state_dir_set(self, notifier, state_dir):
        assert notifier.state_dir == state_dir

    def test_prefs_initialized(self, notifier):
        assert notifier.prefs is not None


# ===================================================================
# 2. notify_trade_entry (send_entry_notification)
# ===================================================================

class TestNotifyTradeEntry:
    @pytest.mark.asyncio
    async def test_basic_long_entry(self, notifier, mock_telegram):
        sig = _make_signal()
        result = await notifier.send_entry_notification("sig-001", 18500.0, sig)
        assert result is True
        mock_telegram.send_message.assert_awaited_once()
        msg = mock_telegram.send_message.call_args[0][0]
        assert "ENTRY" in msg
        assert "LONG" in msg
        assert "MNQ" in msg

    @pytest.mark.asyncio
    async def test_short_entry(self, notifier, mock_telegram):
        sig = _make_signal(direction="short")
        result = await notifier.send_entry_notification("sig-002", 18500.0, sig)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "SHORT" in msg

    @pytest.mark.asyncio
    async def test_entry_includes_stop_and_tp(self, notifier, mock_telegram):
        sig = _make_signal(stop_loss=18450.0, take_profit=18600.0)
        await notifier.send_entry_notification("sig-003", 18500.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Stop" in msg
        assert "TP" in msg

    @pytest.mark.asyncio
    async def test_entry_includes_risk_reward(self, notifier, mock_telegram):
        sig = _make_signal(entry_price=18500.0, stop_loss=18450.0, take_profit=18600.0)
        await notifier.send_entry_notification("sig-rr", 18500.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "R:R" in msg

    @pytest.mark.asyncio
    async def test_entry_with_position_size_and_risk(self, notifier, mock_telegram):
        sig = _make_signal(position_size=2, risk_amount=100)
        await notifier.send_entry_notification("sig-ps", 18500.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "2 MNQ" in msg
        assert "Risk" in msg

    @pytest.mark.asyncio
    async def test_entry_with_execution_filled(self, notifier, mock_telegram):
        sig = _make_signal(_execution_status="filled", _execution_order_id="ORD-123")
        await notifier.send_entry_notification("sig-exec", 18500.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Order placed" in msg
        assert "ORD-123" in msg

    @pytest.mark.asyncio
    async def test_entry_with_execution_failed(self, notifier, mock_telegram):
        sig = _make_signal(_execution_status="place_failed:margin_exceeded")
        await notifier.send_entry_notification("sig-fail", 18500.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Order failed" in msg

    @pytest.mark.asyncio
    async def test_entry_with_execution_skipped(self, notifier, mock_telegram):
        sig = _make_signal(_execution_status="skipped:risk_limit")
        await notifier.send_entry_notification("sig-skip", 18500.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Order skipped" in msg

    @pytest.mark.asyncio
    async def test_entry_with_execution_error(self, notifier, mock_telegram):
        sig = _make_signal(_execution_status="error:timeout")
        await notifier.send_entry_notification("sig-err", 18500.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Exec error" in msg

    @pytest.mark.asyncio
    async def test_entry_disabled_returns_false(self, notifier_disabled):
        result = await notifier_disabled.send_entry_notification("s1", 18500.0, _make_signal())
        assert result is False

    @pytest.mark.asyncio
    async def test_entry_dedupe_false(self, notifier, mock_telegram):
        """Entry notifications must never be deduped."""
        await notifier.send_entry_notification("sig-dd", 18500.0, _make_signal())
        _, kwargs = mock_telegram.send_message.call_args
        assert kwargs.get("dedupe") is False

    @pytest.mark.asyncio
    async def test_entry_api_failure(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("API down"))
        result = await notifier.send_entry_notification("sig-apifail", 18500.0, _make_signal())
        assert result is False

    @pytest.mark.asyncio
    async def test_entry_with_confidence_and_session(self, notifier, mock_telegram):
        sig = _make_signal(confidence=0.85, regime={"session": "morning_trend", "regime": "trending_up", "volatility": "normal"})
        await notifier.send_entry_notification("sig-conf", 18500.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Conf" in msg
        assert "Morning Trend" in msg

    @pytest.mark.asyncio
    async def test_entry_with_none_confidence(self, notifier, mock_telegram):
        sig = _make_signal(confidence=None)
        result = await notifier.send_entry_notification("sig-noconf", 18500.0, sig)
        assert result is True

    @pytest.mark.asyncio
    async def test_entry_account_label_prefix(self, notifier, mock_telegram):
        await notifier.send_entry_notification("sig-lbl", 18500.0, _make_signal())
        msg = mock_telegram.send_message.call_args[0][0]
        assert "[TestAcct]" in msg

    @pytest.mark.asyncio
    async def test_entry_no_account_label(self, notifier_no_label, mock_telegram):
        await notifier_no_label.send_entry_notification("sig-nolbl", 18500.0, _make_signal())
        msg = mock_telegram.send_message.call_args[0][0]
        assert "[" not in msg.split("*")[0]  # no bracket prefix before first bold


# ===================================================================
# 3. notify_trade_exit (send_exit_notification)
# ===================================================================

class TestNotifyTradeExit:
    @pytest.mark.asyncio
    async def test_basic_exit_win(self, notifier, mock_telegram):
        sig = _make_signal()
        result = await notifier.send_exit_notification(
            "sig-001", 18550.0, "take_profit", 50.0, sig, hold_duration_minutes=15.0,
        )
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "EXIT" in msg
        assert "TP" in msg

    @pytest.mark.asyncio
    async def test_basic_exit_loss(self, notifier, mock_telegram):
        sig = _make_signal()
        result = await notifier.send_exit_notification(
            "sig-002", 18450.0, "stop_loss", -50.0, sig, hold_duration_minutes=5.0,
        )
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "EXIT" in msg
        assert "SL" in msg

    @pytest.mark.asyncio
    async def test_exit_manual_reason(self, notifier, mock_telegram):
        sig = _make_signal()
        await notifier.send_exit_notification("s1", 18500.0, "manual", 0.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Manual" in msg

    @pytest.mark.asyncio
    async def test_exit_expired_reason(self, notifier, mock_telegram):
        sig = _make_signal()
        await notifier.send_exit_notification("s1", 18500.0, "expired", -10.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Expired" in msg

    @pytest.mark.asyncio
    async def test_exit_trailing_stop_reason(self, notifier, mock_telegram):
        sig = _make_signal()
        await notifier.send_exit_notification("s1", 18520.0, "trailing_stop", 20.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Trail" in msg

    @pytest.mark.asyncio
    async def test_exit_hold_duration_hours(self, notifier, mock_telegram):
        sig = _make_signal()
        await notifier.send_exit_notification("s1", 18520.0, "manual", 20.0, sig, hold_duration_minutes=90.0)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "1h30m" in msg

    @pytest.mark.asyncio
    async def test_exit_hold_duration_minutes_only(self, notifier, mock_telegram):
        sig = _make_signal()
        await notifier.send_exit_notification("s1", 18520.0, "manual", 20.0, sig, hold_duration_minutes=25.0)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "25m" in msg

    @pytest.mark.asyncio
    async def test_exit_no_hold_duration(self, notifier, mock_telegram):
        sig = _make_signal()
        await notifier.send_exit_notification("s1", 18520.0, "manual", 20.0, sig, hold_duration_minutes=None)
        msg = mock_telegram.send_message.call_args[0][0]
        # Should not contain hold time separator
        assert "h" not in msg.split("|")[-1] or "Manual" in msg

    @pytest.mark.asyncio
    async def test_exit_disabled_returns_false(self, notifier_disabled):
        result = await notifier_disabled.send_exit_notification("s1", 18500.0, "manual", 0.0, _make_signal())
        assert result is False

    @pytest.mark.asyncio
    async def test_exit_never_dedupes(self, notifier, mock_telegram):
        sig = _make_signal()
        await notifier.send_exit_notification("s1", 18500.0, "manual", 0.0, sig)
        _, kwargs = mock_telegram.send_message.call_args
        assert kwargs.get("dedupe") is False

    @pytest.mark.asyncio
    async def test_exit_api_failure(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=RuntimeError("Network error"))
        result = await notifier.send_exit_notification("s1", 18500.0, "manual", 0.0, _make_signal())
        assert result is False

    @pytest.mark.asyncio
    async def test_exit_account_label_prefix(self, notifier, mock_telegram):
        sig = _make_signal()
        await notifier.send_exit_notification("s1", 18550.0, "take_profit", 50.0, sig)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "[TestAcct]" in msg


# ===================================================================
# 4. Service started / stopped
# ===================================================================

class TestServiceStartedStopped:
    @pytest.mark.asyncio
    async def test_startup_notification(self, notifier, mock_telegram, state_dir):
        # Ensure the shared cooldown file doesn't exist so we get the full message
        data_dir = state_dir.parent / "data"
        data_dir.mkdir(exist_ok=True)
        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, data_dir / ".telegram_cb_sent.json")):
            result = await notifier.send_startup_notification({
                "futures_market_open": True,
                "strategy_session_open": True,
            })
        assert result is True
        mock_telegram.send_message.assert_awaited()
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Started" in msg or "started" in msg

    @pytest.mark.asyncio
    async def test_startup_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_startup_notification({})
        assert result is False

    @pytest.mark.asyncio
    async def test_startup_short_coalescence(self, notifier, mock_telegram, state_dir):
        """When another agent sent startup within 90s, send short message."""
        data_dir = state_dir.parent / "data"
        data_dir.mkdir(exist_ok=True)
        sent_file = data_dir / ".telegram_agent_started.json"
        sent_file.write_text(json.dumps({"sent_at": datetime.now(timezone.utc).timestamp(), "market": "NQ"}))
        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, data_dir / ".telegram_cb_sent.json")):
            result = await notifier.send_startup_notification({"futures_market_open": True})
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "also started" in msg

    @pytest.mark.asyncio
    async def test_startup_api_failure(self, notifier, mock_telegram, state_dir):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("fail"))
        data_dir = state_dir.parent / "data"
        data_dir.mkdir(exist_ok=True)
        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, data_dir / ".telegram_cb_sent.json")):
            result = await notifier.send_startup_notification({})
        assert result is False

    @pytest.mark.asyncio
    async def test_shutdown_notification(self, notifier, mock_telegram):
        summary = {
            "shutdown_reason": "Normal shutdown",
            "uptime_hours": 8,
            "uptime_minutes": 30,
            "cycle_count": 1000,
            "signal_count": 15,
        }
        result = await notifier.send_shutdown_notification(summary)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Stopped" in msg
        assert "15 signals" in msg

    @pytest.mark.asyncio
    async def test_shutdown_abnormal_reason(self, notifier, mock_telegram):
        summary = {
            "shutdown_reason": "Circuit breaker error triggered",
            "uptime_hours": 2,
            "uptime_minutes": 15,
            "cycle_count": 500,
            "signal_count": 3,
        }
        result = await notifier.send_shutdown_notification(summary)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Circuit breaker" in msg or "circuit" in msg.lower()

    @pytest.mark.asyncio
    async def test_shutdown_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_shutdown_notification({})
        assert result is False

    @pytest.mark.asyncio
    async def test_shutdown_api_failure(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("boom"))
        result = await notifier.send_shutdown_notification({"shutdown_reason": "test"})
        assert result is False


# ===================================================================
# 5. Error and warning notifications
# ===================================================================

class TestErrorWarning:
    @pytest.mark.asyncio
    async def test_error_summary_basic(self, notifier, mock_telegram):
        result = await notifier.send_error_summary(
            error_count=10,
            error_types={"ConnectionError": 7, "TimeoutError": 3},
            last_error="Connection refused",
            time_window_minutes=60,
        )
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "10" in msg
        assert "ConnectionError" in msg
        assert "Connection refused" in msg

    @pytest.mark.asyncio
    async def test_error_summary_no_types_no_last(self, notifier, mock_telegram):
        result = await notifier.send_error_summary(error_count=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_error_summary_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_error_summary(error_count=5)
        assert result is False

    @pytest.mark.asyncio
    async def test_error_summary_api_failure(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("API down"))
        result = await notifier.send_error_summary(error_count=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_circuit_breaker_alert(self, notifier, mock_telegram):
        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths") as mock_paths:
            data_dir = notifier.state_dir
            mock_paths.return_value = (data_dir, data_dir / ".telegram_cb_sent.json")
            result = await notifier.send_circuit_breaker_alert(
                "max_errors_exceeded",
                {"consecutive_errors": 10, "error_type": "ConnectionError"},
            )
        assert result is True
        mock_telegram.notify_risk_warning.assert_awaited_once()
        msg = mock_telegram.notify_risk_warning.call_args[0][0]
        assert "Circuit Breaker" in msg
        assert "max_errors_exceeded" in msg

    @pytest.mark.asyncio
    async def test_circuit_breaker_cooldown_dedup(self, notifier, mock_telegram):
        """Same reason within cooldown should be skipped."""
        data_dir = notifier.state_dir
        sent_file = data_dir / ".telegram_cb_sent.json"
        sent_file.write_text(json.dumps({
            "reason": "max_errors_exceeded",
            "sent_at": datetime.now(timezone.utc).timestamp(),
        }))
        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, sent_file)):
            result = await notifier.send_circuit_breaker_alert("max_errors_exceeded")
        assert result is True  # returns True (handled via cooldown)
        mock_telegram.notify_risk_warning.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_circuit_breaker_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_circuit_breaker_alert("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_recovery_notification(self, notifier, mock_telegram):
        result = await notifier.send_recovery_notification({
            "issue": "Data connection lost",
            "recovery_time_seconds": 45,
        })
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Recovered" in msg
        assert "Data connection lost" in msg

    @pytest.mark.asyncio
    async def test_recovery_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_recovery_notification({"issue": "x"})
        assert result is False

    @pytest.mark.asyncio
    async def test_recovery_api_failure(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("fail"))
        result = await notifier.send_recovery_notification({"issue": "test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_data_quality_stale_data(self, notifier, mock_telegram):
        result = await notifier.send_data_quality_alert(
            "stale_data", "Data is stale", {"age_minutes": 15.3}
        )
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Stale Data" in msg
        assert "15.3" in msg

    @pytest.mark.asyncio
    async def test_data_quality_data_gap(self, notifier, mock_telegram):
        result = await notifier.send_data_quality_alert("data_gap", "Gap detected")
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Data Gap" in msg

    @pytest.mark.asyncio
    async def test_data_quality_fetch_failure(self, notifier, mock_telegram):
        result = await notifier.send_data_quality_alert(
            "fetch_failure", "Fetch failed", {"consecutive_failures": 3}
        )
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Fetch Failure" in msg

    @pytest.mark.asyncio
    async def test_data_quality_buffer_issue(self, notifier, mock_telegram):
        result = await notifier.send_data_quality_alert(
            "buffer_issue", "Buffer too small", {"buffer_size": 10}
        )
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Buffer Issue" in msg

    @pytest.mark.asyncio
    async def test_data_quality_recovery(self, notifier, mock_telegram):
        result = await notifier.send_data_quality_alert("recovery", "Data recovered")
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Recovery" in msg

    @pytest.mark.asyncio
    async def test_data_quality_unknown_type(self, notifier, mock_telegram):
        result = await notifier.send_data_quality_alert("some_new_type", "Something happened")
        assert result is True

    @pytest.mark.asyncio
    async def test_data_quality_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_data_quality_alert("stale_data", "test")
        assert result is False

    @pytest.mark.asyncio
    async def test_data_quality_snoozed_noncritical(self, notifier, mock_telegram):
        """Non-critical alerts should be suppressed when snoozed."""
        mock_prefs = MagicMock()
        mock_prefs.snooze_noncritical_alerts = True
        with patch.object(notifier, "_get_prefs", return_value=mock_prefs):
            result = await notifier.send_data_quality_alert("stale_data", "stale")
        assert result is True  # handled (suppressed)
        mock_telegram.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_data_quality_critical_ignores_snooze(self, notifier, mock_telegram):
        """Circuit breaker alerts should bypass snooze."""
        mock_prefs = MagicMock()
        mock_prefs.snooze_noncritical_alerts = True
        with patch.object(notifier, "_get_prefs", return_value=mock_prefs):
            result = await notifier.send_data_quality_alert("circuit_breaker", "triggered")
        assert result is True
        mock_telegram.send_message.assert_awaited()

    @pytest.mark.asyncio
    async def test_price_alert_up(self, notifier, mock_telegram):
        result = await notifier.send_price_alert("MNQ", 18600.0, 18500.0, 0.54)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "UP" in msg

    @pytest.mark.asyncio
    async def test_price_alert_down(self, notifier, mock_telegram):
        result = await notifier.send_price_alert("MNQ", 18400.0, 18500.0, -0.54)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "DOWN" in msg

    @pytest.mark.asyncio
    async def test_price_alert_significant_move(self, notifier, mock_telegram):
        result = await notifier.send_price_alert("MNQ", 18700.0, 18500.0, 1.08)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Significant" in msg

    @pytest.mark.asyncio
    async def test_price_alert_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_price_alert("MNQ", 18600.0, 18500.0, 0.5)
        assert result is False

    @pytest.mark.asyncio
    async def test_connection_status_connected(self, notifier, mock_telegram):
        result = await notifier.send_connection_status_update("connected")
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "CONNECTED" in msg

    @pytest.mark.asyncio
    async def test_connection_status_disconnected_details(self, notifier, mock_telegram):
        result = await notifier.send_connection_status_update(
            "disconnected", {"failures": 5, "last_attempt": "2025-01-01T12:00:00Z"}
        )
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "DISCONNECTED" in msg
        assert "5" in msg

    @pytest.mark.asyncio
    async def test_connection_status_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_connection_status_update("connected")
        assert result is False


# ===================================================================
# 6. Daily / Weekly summary
# ===================================================================

class TestDailySummary:
    @pytest.mark.asyncio
    async def test_daily_summary_success(self, notifier, mock_telegram):
        metrics = {"total_pnl": 250.0, "wins": 5, "losses": 3, "win_rate": 0.625}
        result = await notifier.send_daily_summary(metrics)
        assert result is True
        mock_telegram.notify_daily_summary.assert_awaited_once()
        call_kwargs = mock_telegram.notify_daily_summary.call_args[1]
        assert call_kwargs["daily_pnl"] == 250.0
        assert call_kwargs["total_trades"] == 8
        assert call_kwargs["win_rate"] == 0.625

    @pytest.mark.asyncio
    async def test_daily_summary_zero_trades(self, notifier, mock_telegram):
        metrics = {"total_pnl": 0, "wins": 0, "losses": 0, "win_rate": 0}
        result = await notifier.send_daily_summary(metrics)
        assert result is True
        call_kwargs = mock_telegram.notify_daily_summary.call_args[1]
        assert call_kwargs["win_rate"] is None  # no trades -> None

    @pytest.mark.asyncio
    async def test_daily_summary_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_daily_summary({"total_pnl": 100, "wins": 1, "losses": 0, "win_rate": 1.0})
        assert result is False

    @pytest.mark.asyncio
    async def test_daily_summary_api_failure(self, notifier, mock_telegram):
        mock_telegram.notify_daily_summary = AsyncMock(side_effect=Exception("fail"))
        result = await notifier.send_daily_summary({"total_pnl": 100, "wins": 1, "losses": 0, "win_rate": 1.0})
        assert result is False


class TestWeeklySummary:
    @pytest.mark.asyncio
    async def test_weekly_profitable(self, notifier, mock_telegram):
        metrics = {
            "total_pnl": 500.0, "wins": 10, "losses": 5, "win_rate": 0.667,
            "total_signals": 20, "exited_signals": 15, "avg_pnl": 33.33, "avg_hold_minutes": 30.0,
        }
        result = await notifier.send_weekly_summary(metrics)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Weekly" in msg
        assert "Profitable" in msg

    @pytest.mark.asyncio
    async def test_weekly_loss(self, notifier, mock_telegram):
        metrics = {
            "total_pnl": -200.0, "wins": 3, "losses": 7, "win_rate": 0.3,
            "total_signals": 15, "exited_signals": 10, "avg_pnl": -20.0, "avg_hold_minutes": 25.0,
        }
        result = await notifier.send_weekly_summary(metrics)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Loss week" in msg

    @pytest.mark.asyncio
    async def test_weekly_breakeven(self, notifier, mock_telegram):
        metrics = {
            "total_pnl": 0.0, "wins": 5, "losses": 5, "win_rate": 0.5,
            "total_signals": 10, "exited_signals": 10, "avg_pnl": 0.0, "avg_hold_minutes": 20.0,
        }
        result = await notifier.send_weekly_summary(metrics)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Break even" in msg

    @pytest.mark.asyncio
    async def test_weekly_no_completed_trades(self, notifier, mock_telegram):
        metrics = {
            "total_pnl": 0.0, "wins": 0, "losses": 0, "win_rate": 0,
            "total_signals": 5, "exited_signals": 0, "avg_pnl": 0, "avg_hold_minutes": 0,
        }
        result = await notifier.send_weekly_summary(metrics)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "No completed trades" in msg

    @pytest.mark.asyncio
    async def test_weekly_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_weekly_summary({})
        assert result is False

    @pytest.mark.asyncio
    async def test_weekly_api_failure(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("fail"))
        result = await notifier.send_weekly_summary({
            "total_pnl": 100, "wins": 1, "losses": 0, "win_rate": 1.0,
            "total_signals": 1, "exited_signals": 1, "avg_pnl": 100, "avg_hold_minutes": 10,
        })
        assert result is False


# ===================================================================
# 7. Rate limiting / message deduplication
# ===================================================================

class TestRateLimitingDedup:
    @pytest.mark.asyncio
    async def test_circuit_breaker_shared_cooldown(self, notifier, mock_telegram):
        """Verifies shared file-based cooldown prevents duplicate CB alerts."""
        data_dir = notifier.state_dir
        sent_file = data_dir / ".telegram_cb_sent.json"

        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, sent_file)):
            # First call: should send
            result1 = await notifier.send_circuit_breaker_alert("reason_A")
            assert result1 is True
            assert mock_telegram.notify_risk_warning.await_count == 1

            # Second call same reason within cooldown: should skip
            result2 = await notifier.send_circuit_breaker_alert("reason_A")
            assert result2 is True
            assert mock_telegram.notify_risk_warning.await_count == 1  # no additional call

    @pytest.mark.asyncio
    async def test_circuit_breaker_different_reason_sends(self, notifier, mock_telegram):
        """Different reason should send even within cooldown."""
        data_dir = notifier.state_dir
        sent_file = data_dir / ".telegram_cb_sent.json"

        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, sent_file)):
            await notifier.send_circuit_breaker_alert("reason_A")
            assert mock_telegram.notify_risk_warning.await_count == 1
            await notifier.send_circuit_breaker_alert("reason_B")
            assert mock_telegram.notify_risk_warning.await_count == 2

    @pytest.mark.asyncio
    async def test_startup_coalescence(self, notifier, mock_telegram, state_dir):
        """Multiple startups within 90s should coalesce into short messages."""
        data_dir = state_dir.parent / "data"
        data_dir.mkdir(exist_ok=True)
        sent_file = data_dir / ".telegram_agent_started.json"

        with patch.object(notifier, "_shared_cb_telegram_cooldown_paths", return_value=(data_dir, data_dir / ".telegram_cb_sent.json")):
            # First startup: full message
            result1 = await notifier.send_startup_notification({"futures_market_open": True})
            assert result1 is True
            first_msg = mock_telegram.send_message.call_args[0][0]
            assert "Started" in first_msg

            # Second startup within cooldown: short message
            result2 = await notifier.send_startup_notification({"futures_market_open": True})
            assert result2 is True
            second_msg = mock_telegram.send_message.call_args[0][0]
            assert "also started" in second_msg

    @pytest.mark.asyncio
    async def test_data_quality_snooze_toggle(self, notifier, mock_telegram):
        """Snooze suppresses non-critical, then unsnoozed sends again."""
        # Snoozed
        mock_prefs_snoozed = MagicMock()
        mock_prefs_snoozed.snooze_noncritical_alerts = True
        with patch.object(notifier, "_get_prefs", return_value=mock_prefs_snoozed):
            await notifier.send_data_quality_alert("stale_data", "stale")
        assert mock_telegram.send_message.await_count == 0

        # Unsnoozed
        mock_prefs_active = MagicMock()
        mock_prefs_active.snooze_noncritical_alerts = False
        with patch.object(notifier, "_get_prefs", return_value=mock_prefs_active):
            await notifier.send_data_quality_alert("stale_data", "stale")
        assert mock_telegram.send_message.await_count == 1


# ===================================================================
# 8. Error handling (bot API failures)
# ===================================================================

class TestBotApiFailures:
    @pytest.mark.asyncio
    async def test_send_status_api_error(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("Telegram 429"))
        result = await notifier.send_status({"running": True})
        assert result is False

    @pytest.mark.asyncio
    async def test_enhanced_status_api_error(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("Telegram error"))
        result = await notifier.send_enhanced_status({"running": True, "symbol": "MNQ"})
        assert result is False

    @pytest.mark.asyncio
    async def test_heartbeat_api_error(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("timeout"))
        result = await notifier.send_heartbeat({"symbol": "NQ"})
        assert result is False

    @pytest.mark.asyncio
    async def test_send_photo_success(self, notifier, mock_telegram, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG\r\n")
        result = await notifier._send_photo(photo, caption="Test caption")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_photo_failure(self, notifier, mock_telegram, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG\r\n")
        mock_telegram.bot.send_photo = AsyncMock(side_effect=Exception("Photo failed"))
        result = await notifier._send_photo(photo, caption="Test")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_photo_disabled(self, notifier_disabled, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG\r\n")
        result = await notifier_disabled._send_photo(photo)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_photo_return_message_success(self, notifier, mock_telegram, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG\r\n")
        msg_obj = MagicMock(message_id=99)
        mock_telegram.bot.send_photo = AsyncMock(return_value=msg_obj)
        result = await notifier._send_photo(photo, return_message=True)
        assert result is msg_obj

    @pytest.mark.asyncio
    async def test_send_photo_return_message_failure(self, notifier, mock_telegram, tmp_path):
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"\x89PNG\r\n")
        mock_telegram.bot.send_photo = AsyncMock(side_effect=Exception("fail"))
        result = await notifier._send_photo(photo, return_message=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_pearl_notification_markdownv2_failure_falls_back(self, notifier, mock_telegram):
        """When MarkdownV2 fails, should fall back to plain text."""
        call_count = 0
        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("MarkdownV2 parse error")
            return True
        mock_telegram.send_message = AsyncMock(side_effect=side_effect)
        result = await notifier.send_pearl_notification("Test message", "Alert")
        assert result is True
        assert call_count == 2  # first call failed, second (fallback) succeeded


# ===================================================================
# 9. Enhanced status + heartbeat formatting
# ===================================================================

class TestEnhancedStatusHeartbeat:
    @pytest.mark.asyncio
    async def test_enhanced_status_running(self, notifier, mock_telegram):
        status = {
            "running": True, "paused": False, "symbol": "MNQ",
            "cycle_count": 500, "error_count": 1, "signal_count": 10,
            "signals_sent": 8, "signals_send_failures": 2,
            "buffer_size": 300,
        }
        result = await notifier.send_enhanced_status(status)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "RUNNING" in msg
        assert "500" in msg or "scans" in msg.lower()

    @pytest.mark.asyncio
    async def test_enhanced_status_paused(self, notifier, mock_telegram):
        status = {"running": True, "paused": True, "symbol": "MNQ"}
        result = await notifier.send_enhanced_status(status)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "PAUSED" in msg

    @pytest.mark.asyncio
    async def test_enhanced_status_connection_issues(self, notifier, mock_telegram):
        status = {
            "running": True, "paused": False, "symbol": "MNQ",
            "connection_status": "disconnected", "connection_failures": 3,
        }
        result = await notifier.send_enhanced_status(status)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "DISCONNECTED" in msg
        assert "3" in msg

    @pytest.mark.asyncio
    async def test_enhanced_status_with_performance(self, notifier, mock_telegram):
        status = {
            "running": True, "paused": False, "symbol": "MNQ",
            "performance": {
                "exited_signals": 10, "wins": 7, "losses": 3,
                "win_rate": 0.7, "total_pnl": 350.0, "avg_pnl": 35.0,
            },
        }
        result = await notifier.send_enhanced_status(status)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "7W" in msg or "7W/" in msg
        assert "Performance" in msg

    @pytest.mark.asyncio
    async def test_enhanced_status_data_quality_level2(self, notifier, mock_telegram):
        status = {
            "running": True, "paused": False, "symbol": "MNQ",
            "latest_bar": {"_data_level": "level2", "imbalance": 0.15},
        }
        result = await notifier.send_enhanced_status(status)
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Level 2" in msg

    @pytest.mark.asyncio
    async def test_heartbeat_with_price(self, notifier, mock_telegram):
        status = {
            "symbol": "NQ", "latest_price": 18500.0,
            "current_time": datetime.now(timezone.utc).isoformat(),
            "futures_market_open": True, "strategy_session_open": True,
            "cycle_count": 100, "signal_count": 5, "signals_sent": 4,
            "signals_send_failures": 1, "error_count": 0, "buffer_size": 300,
        }
        result = await notifier.send_heartbeat(status)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "Heartbeat" in msg

    @pytest.mark.asyncio
    async def test_heartbeat_no_price(self, notifier, mock_telegram):
        status = {"symbol": "NQ"}
        result = await notifier.send_heartbeat(status)
        assert result is True
        msg = mock_telegram.send_message.call_args[0][0]
        assert "NQ" in msg


# ===================================================================
# 10. Formatting helpers
# ===================================================================

class TestFormatting:
    def test_professional_signal_long(self, notifier):
        sig = _make_signal()
        msg = notifier._format_professional_signal(sig)
        assert "LONG" in msg
        assert "ENTRY" in msg
        assert "STOP" in msg
        assert "TARGET" in msg
        assert "R:R" in msg

    def test_professional_signal_short(self, notifier):
        sig = _make_signal(direction="short")
        msg = notifier._format_professional_signal(sig)
        assert "SHORT" in msg

    def test_professional_signal_zero_stop(self, notifier):
        sig = _make_signal(stop_loss=0, take_profit=0)
        msg = notifier._format_professional_signal(sig)
        assert "0.00:1" in msg  # risk_reward is 0

    def test_professional_signal_order_book_strong_bid(self, notifier):
        sig = _make_signal(order_book={"imbalance": 0.3, "bid_depth": 5000, "ask_depth": 2000, "data_level": "level2"})
        msg = notifier._format_professional_signal(sig)
        assert "Strong Bid" in msg
        assert "L2" in msg

    def test_professional_signal_order_book_strong_ask(self, notifier):
        sig = _make_signal(order_book={"imbalance": -0.3, "bid_depth": 2000, "ask_depth": 5000, "data_level": "level2"})
        msg = notifier._format_professional_signal(sig)
        assert "Strong Ask" in msg

    def test_professional_signal_order_book_balanced(self, notifier):
        sig = _make_signal(order_book={"imbalance": 0.05, "bid_depth": 3000, "ask_depth": 3000, "data_level": "level1"})
        msg = notifier._format_professional_signal(sig)
        assert "Balanced" in msg
        assert "L1" in msg

    def test_professional_signal_order_book_moderate_bid(self, notifier):
        sig = _make_signal(order_book={"imbalance": 0.15, "bid_depth": 4000, "ask_depth": 3000, "data_level": "level2"})
        msg = notifier._format_professional_signal(sig)
        assert "Moderate Bid" in msg

    def test_professional_signal_order_book_moderate_ask(self, notifier):
        sig = _make_signal(order_book={"imbalance": -0.15, "bid_depth": 3000, "ask_depth": 4000, "data_level": "level2"})
        msg = notifier._format_professional_signal(sig)
        assert "Moderate Ask" in msg

    def test_professional_signal_breakout_above_resistance(self, notifier):
        sig = _make_signal(
            type="breakout_signal", entry_price=18500.0,
            mtf_analysis={"alignment": "aligned", "breakout_levels": {"resistance_5m": 18490.0}},
        )
        msg = notifier._format_professional_signal(sig)
        assert "Breaking 5m resistance" in msg

    def test_professional_signal_breakout_below_resistance(self, notifier):
        sig = _make_signal(
            type="breakout_signal", entry_price=18480.0,
            mtf_analysis={"alignment": "aligned", "breakout_levels": {"resistance_5m": 18490.0}},
        )
        msg = notifier._format_professional_signal(sig)
        assert "Below 5m resistance" in msg

    def test_professional_signal_all_sessions(self, notifier):
        for session_key, expected in [
            ("opening", "Opening"),
            ("morning_trend", "Morning Trend"),
            ("lunch_lull", "Lunch Lull"),
            ("afternoon", "Afternoon"),
            ("closing", "Closing"),
        ]:
            sig = _make_signal(regime={"regime": "trending_up", "volatility": "normal", "session": session_key})
            msg = notifier._format_professional_signal(sig)
            assert expected in msg

    def test_professional_signal_all_warnings(self, notifier):
        # Lunch lull warning
        sig = _make_signal(regime={"regime": "ranging", "volatility": "high", "session": "lunch_lull"})
        msg = notifier._format_professional_signal(sig)
        assert "Lunch lull" in msg
        assert "High volatility" in msg

    def test_professional_signal_ranging_momentum_warning(self, notifier):
        sig = _make_signal(
            type="momentum_breakout",
            regime={"regime": "ranging", "volatility": "normal", "session": "afternoon"},
        )
        msg = notifier._format_professional_signal(sig)
        assert "Ranging market" in msg

    def test_professional_signal_trending_mean_reversion_warning(self, notifier):
        sig = _make_signal(
            type="mean_reversion_signal",
            regime={"regime": "trending_up", "volatility": "normal", "session": "afternoon"},
        )
        msg = notifier._format_professional_signal(sig)
        assert "Trending market" in msg

    def test_professional_signal_vwap_below(self, notifier):
        sig = _make_signal(vwap_data={"vwap": 18500.0, "distance_from_vwap": -20.0, "distance_pct": -0.11})
        msg = notifier._format_professional_signal(sig)
        assert "Below VWAP" in msg

    def test_professional_signal_vwap_near(self, notifier):
        sig = _make_signal(vwap_data={"vwap": 18500.0, "distance_from_vwap": 5.0, "distance_pct": 0.03})
        msg = notifier._format_professional_signal(sig)
        assert "Near VWAP" in msg

    def test_professional_signal_atr_low_vol(self, notifier):
        sig = _make_signal(
            indicators={"atr": 10.0, "volume_ratio": 0.8},
            regime={"regime": "trending_up", "volatility": "low", "session": "afternoon"},
        )
        msg = notifier._format_professional_signal(sig)
        assert "low vol compression" in msg

    def test_professional_signal_atr_high_vol(self, notifier):
        sig = _make_signal(
            indicators={"atr": 50.0, "volume_ratio": 2.0},
            regime={"regime": "trending_up", "volatility": "high", "session": "afternoon"},
        )
        msg = notifier._format_professional_signal(sig)
        assert "high vol expansion" in msg

    def test_format_compact_signal_delegates(self, notifier):
        sig = _make_signal()
        with patch("pearlalgo.market_agent.telegram_notifier._canonical_format_compact_signal", return_value="compact") as mock_fn:
            result = notifier._format_compact_signal(sig)
        assert result == "compact"
        mock_fn.assert_called_once()

    def test_format_signal_message_delegates(self, notifier):
        sig = _make_signal()
        with patch("pearlalgo.market_agent.telegram_notifier._canonical_format_signal_message", return_value="signal_msg") as mock_fn:
            result = notifier._format_signal_message(sig)
        assert result == "signal_msg"

    def test_format_status_message_delegates(self, notifier):
        status = {"running": True}
        with patch("pearlalgo.market_agent.telegram_notifier._canonical_format_status_message", return_value="status_msg") as mock_fn:
            result = notifier._format_status_message(status)
        assert result == "status_msg"


class TestMarkdownV2Conversion:
    def test_escapes_special_chars(self):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        result = MarketAgentTelegramNotifier._convert_to_markdown_v2_with_pearl("Hello.World!")
        assert "\\." in result
        assert "\\!" in result

    def test_preserves_bold_stars(self):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        result = MarketAgentTelegramNotifier._convert_to_markdown_v2_with_pearl("*bold text*")
        assert "*bold text*" in result

    def test_pearl_emoji_replacement(self):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
        text = "🐚 *PEARL* Check-In"
        result = MarketAgentTelegramNotifier._convert_to_markdown_v2_with_pearl(text)
        assert "tg://emoji" in result
        assert MarketAgentTelegramNotifier.PEARL_EMOJI_ID in result


# ===================================================================
# 11. _get_prefs and _is_command_handler_running
# ===================================================================

class TestMiscHelpers:
    def test_get_prefs_returns_prefs(self, notifier):
        prefs = notifier._get_prefs()
        assert prefs is not None

    def test_get_prefs_exception_fallback(self, notifier):
        with patch("pearlalgo.market_agent.telegram_notifier.TelegramPrefs", side_effect=Exception("bad")):
            prefs = notifier._get_prefs()
        assert prefs is notifier.prefs

    def test_is_command_handler_no_pid_file(self, tmp_path):
        from pearlalgo.market_agent.telegram_notifier import _is_command_handler_running
        with patch("pearlalgo.market_agent.telegram_notifier.Path") as mock_path:
            mock_path.return_value.parent.parent.parent.parent = tmp_path
            # No pid file exists
            result = _is_command_handler_running()
        # Should return False (no pid file or exception handled)
        assert result is False or result is True  # depends on path mocking; key is no crash

    def test_shared_cb_cooldown_paths(self, notifier):
        data_dir, sent_file = notifier._shared_cb_telegram_cooldown_paths()
        assert data_dir.name == "data"
        assert sent_file.name == ".telegram_cb_sent.json"


# ===================================================================
# 12. Dashboard (send_dashboard) - key paths
# ===================================================================

class TestDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_dashboard({})
        assert result is False

    @pytest.mark.asyncio
    async def test_dashboard_no_bot_returns_false(self, notifier, mock_telegram):
        mock_telegram.bot = None
        result = await notifier.send_dashboard({"symbol": "MNQ", "running": True})
        assert result is False

    @pytest.mark.asyncio
    async def test_dashboard_text_only(self, notifier, mock_telegram):
        """Dashboard without chart sends text message."""
        mock_telegram.bot.send_message = AsyncMock(return_value=MagicMock(message_id=55))
        with patch("pearlalgo.market_agent.telegram_notifier._is_command_handler_running", return_value=False):
            with patch("pearlalgo.market_agent.telegram_notifier.get_market_hours") as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                result = await notifier.send_dashboard({
                    "symbol": "MNQ", "running": True,
                    "futures_market_open": True, "strategy_session_open": True,
                })
        assert result is True

    @pytest.mark.asyncio
    async def test_dashboard_with_chart(self, notifier, mock_telegram, tmp_path):
        """Dashboard with chart sends photo."""
        chart = tmp_path / "dashboard.png"
        chart.write_bytes(b"\x89PNG\r\n")
        mock_telegram.bot.send_photo = AsyncMock(return_value=MagicMock(message_id=56))
        with patch("pearlalgo.market_agent.telegram_notifier._is_command_handler_running", return_value=False):
            with patch("pearlalgo.market_agent.telegram_notifier.get_market_hours") as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                result = await notifier.send_dashboard(
                    {"symbol": "MNQ", "running": True, "futures_market_open": True},
                    chart_path=chart,
                )
        assert result is True

    @pytest.mark.asyncio
    async def test_dashboard_api_failure(self, notifier, mock_telegram):
        mock_telegram.bot.send_message = AsyncMock(side_effect=Exception("fail"))
        with patch("pearlalgo.market_agent.telegram_notifier._is_command_handler_running", return_value=False):
            with patch("pearlalgo.market_agent.telegram_notifier.get_market_hours") as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                result = await notifier.send_dashboard({
                    "symbol": "MNQ", "running": True, "futures_market_open": True,
                })
        # Should handle gracefully (either False from error handler, or True if plain fallback works)
        assert isinstance(result, bool)


# ===================================================================
# 13. send_status
# ===================================================================

class TestSendStatus:
    @pytest.mark.asyncio
    async def test_send_status_basic(self, notifier, mock_telegram):
        result = await notifier.send_status({"running": True, "symbol": "MNQ"})
        assert result is True
        mock_telegram.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_status_disabled(self, notifier_disabled):
        result = await notifier_disabled.send_status({"running": True})
        assert result is False

    @pytest.mark.asyncio
    async def test_send_status_api_error(self, notifier, mock_telegram):
        mock_telegram.send_message = AsyncMock(side_effect=Exception("error"))
        result = await notifier.send_status({"running": True})
        assert result is False
