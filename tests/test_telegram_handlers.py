"""
Tests for Telegram Action Handlers.

Tests the TelegramHandlersMixin class which provides action handling utilities
for the Telegram bot interface.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path
from datetime import datetime, timezone
import tempfile
import asyncio


@pytest.fixture
def temp_state_dir():
    """Create a temporary state directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        yield state_dir


@pytest.fixture
def handlers_mixin(temp_state_dir):
    """Create a TelegramHandlersMixin instance for testing."""
    from pearlalgo.market_agent.telegram_handlers import TelegramHandlersMixin

    class TestHandler(TelegramHandlersMixin):
        """Test handler class using the mixin."""

        def __init__(self, state_dir):
            self.state_dir = state_dir
            self.active_market = "NQ"
            self.service_controller = None

        def _nav_back_row(self):
            return []

        async def _safe_edit_or_send(self, query, text, reply_markup=None, parse_mode=None):
            self.last_message = text
            self.last_reply_markup = reply_markup

    return TestHandler(temp_state_dir)


def write_state_file(state_dir: Path, state: dict) -> Path:
    """Helper to write a state.json file."""
    state_file = state_dir / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state_file


class TestExecuteServiceAction:
    """Tests for _execute_service_action method."""

    @pytest.mark.asyncio
    async def test_start_agent(self, handlers_mixin):
        """Should start agent via service controller."""
        mock_sc = MagicMock()
        mock_sc.start_agent = AsyncMock(return_value={"message": "Agent started"})
        handlers_mixin.service_controller = mock_sc

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="start",
            service="agent",
        )

        assert result["success"] is True
        assert "Agent started" in result["message"]
        mock_sc.start_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_agent(self, handlers_mixin):
        """Should stop agent via service controller."""
        mock_sc = MagicMock()
        mock_sc.stop_agent = AsyncMock(return_value={"message": "Agent stopped"})
        handlers_mixin.service_controller = mock_sc

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="stop",
            service="agent",
        )

        assert result["success"] is True
        mock_sc.stop_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_agent(self, handlers_mixin):
        """Should restart agent via service controller."""
        mock_sc = MagicMock()
        mock_sc.restart_agent = AsyncMock(return_value={"message": "Agent restarted"})
        handlers_mixin.service_controller = mock_sc

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="restart",
            service="agent",
        )

        assert result["success"] is True
        mock_sc.restart_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_gateway(self, handlers_mixin):
        """Should start gateway via service controller."""
        mock_sc = MagicMock()
        mock_sc.start_gateway = AsyncMock(return_value={"message": "Gateway started"})
        handlers_mixin.service_controller = mock_sc

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="start",
            service="gateway",
        )

        assert result["success"] is True
        mock_sc.start_gateway.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_gateway(self, handlers_mixin):
        """Should stop gateway via service controller."""
        mock_sc = MagicMock()
        mock_sc.stop_gateway = AsyncMock(return_value={"message": "Gateway stopped"})
        handlers_mixin.service_controller = mock_sc

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="stop",
            service="gateway",
        )

        assert result["success"] is True
        mock_sc.stop_gateway.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_gateway(self, handlers_mixin):
        """Should restart gateway via service controller."""
        mock_sc = MagicMock()
        mock_sc.restart_gateway = AsyncMock(return_value={"message": "Gateway restarted"})
        handlers_mixin.service_controller = mock_sc

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="restart",
            service="gateway",
        )

        assert result["success"] is True
        mock_sc.restart_gateway.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_error_without_controller(self, handlers_mixin):
        """Should return error when no service controller."""
        handlers_mixin.service_controller = None

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="start",
            service="agent",
        )

        assert result["success"] is False
        assert "not available" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_action(self, handlers_mixin):
        """Should return error for unknown action."""
        mock_sc = MagicMock()
        handlers_mixin.service_controller = mock_sc

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="unknown",
            service="agent",
        )

        assert result["success"] is False
        assert "Unknown action" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_service(self, handlers_mixin):
        """Should return error for unknown service."""
        mock_sc = MagicMock()
        handlers_mixin.service_controller = mock_sc

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="start",
            service="unknown",
        )

        assert result["success"] is False
        assert "Unknown service" in result["message"]

    @pytest.mark.asyncio
    async def test_handles_exceptions(self, handlers_mixin):
        """Should handle exceptions gracefully."""
        mock_sc = MagicMock()
        mock_sc.start_agent = AsyncMock(side_effect=Exception("Connection error"))
        handlers_mixin.service_controller = mock_sc

        result = await handlers_mixin._execute_service_action(
            query=MagicMock(),
            action="start",
            service="agent",
        )

        assert result["success"] is False
        assert "Connection error" in result["message"]


class TestHandleCloseAllTrades:
    """Tests for _handle_close_all_trades method."""

    @pytest.mark.asyncio
    async def test_sets_close_all_flag(self, handlers_mixin, temp_state_dir):
        """Should set close_all_requested flag in state."""
        state = {"active_trades_count": 3}
        write_state_file(temp_state_dir, state)

        await handlers_mixin._handle_close_all_trades(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        # Read updated state
        state_file = temp_state_dir / "state.json"
        updated_state = json.loads(state_file.read_text())

        assert updated_state["close_all_requested"] is True
        assert "close_all_requested_time" in updated_state

    @pytest.mark.asyncio
    async def test_sends_confirmation_message(self, handlers_mixin, temp_state_dir):
        """Should send confirmation message."""
        state = {"active_trades_count": 2}
        write_state_file(temp_state_dir, state)

        await handlers_mixin._handle_close_all_trades(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        assert "Close All" in handlers_mixin.last_message or "2" in handlers_mixin.last_message

    @pytest.mark.asyncio
    async def test_handles_missing_state_file(self, handlers_mixin):
        """Should handle missing state file."""
        await handlers_mixin._handle_close_all_trades(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        assert "not found" in handlers_mixin.last_message or "running" in handlers_mixin.last_message.lower()


class TestHandleEmergencyStop:
    """Tests for _handle_emergency_stop method."""

    @pytest.mark.asyncio
    async def test_sets_emergency_stop_flag(self, handlers_mixin, temp_state_dir):
        """Should set emergency_stop flag in state."""
        state = {}
        write_state_file(temp_state_dir, state)

        await handlers_mixin._handle_emergency_stop(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        state_file = temp_state_dir / "state.json"
        updated_state = json.loads(state_file.read_text())

        assert updated_state["emergency_stop"] is True
        assert "emergency_stop_time" in updated_state

    @pytest.mark.asyncio
    async def test_stops_agent(self, handlers_mixin, temp_state_dir):
        """Should stop agent via service controller."""
        state = {}
        write_state_file(temp_state_dir, state)

        mock_sc = MagicMock()
        mock_sc.stop_agent = AsyncMock(return_value={"message": "Stopped"})
        handlers_mixin.service_controller = mock_sc

        await handlers_mixin._handle_emergency_stop(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        mock_sc.stop_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_sends_emergency_message(self, handlers_mixin, temp_state_dir):
        """Should send emergency stop message."""
        state = {}
        write_state_file(temp_state_dir, state)

        await handlers_mixin._handle_emergency_stop(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        assert "EMERGENCY" in handlers_mixin.last_message


class TestHandleClearCache:
    """Tests for _handle_clear_cache method."""

    @pytest.mark.asyncio
    async def test_clears_cache_directories(self, handlers_mixin, temp_state_dir):
        """Should clear cache directories."""
        # Create cache directories
        cache_dir = temp_state_dir / "cache"
        cache_dir.mkdir()
        (cache_dir / "test_file.txt").write_text("test")

        await handlers_mixin._handle_clear_cache(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        # Cache dir should be recreated empty
        assert cache_dir.exists()
        assert not (cache_dir / "test_file.txt").exists()

    @pytest.mark.asyncio
    async def test_sends_success_message(self, handlers_mixin, temp_state_dir):
        """Should send success message."""
        cache_dir = temp_state_dir / "cache"
        cache_dir.mkdir()

        await handlers_mixin._handle_clear_cache(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        assert "Clear" in handlers_mixin.last_message

    @pytest.mark.asyncio
    async def test_handles_no_cache_dirs(self, handlers_mixin):
        """Should handle case when no cache directories exist."""
        await handlers_mixin._handle_clear_cache(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        assert "Complete" in handlers_mixin.last_message or "Clear" in handlers_mixin.last_message


class TestHandleResetPerformance:
    """Tests for _handle_reset_performance method."""

    @pytest.mark.asyncio
    async def test_resets_performance_counters(self, handlers_mixin, temp_state_dir):
        """Should reset performance counters in state."""
        state = {
            "daily_pnl": 500.00,
            "daily_trades": 10,
            "daily_wins": 7,
            "daily_losses": 3,
        }
        write_state_file(temp_state_dir, state)

        await handlers_mixin._handle_reset_performance(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        state_file = temp_state_dir / "state.json"
        updated_state = json.loads(state_file.read_text())

        assert updated_state["daily_pnl"] == 0.0
        assert updated_state["daily_trades"] == 0
        assert updated_state["daily_wins"] == 0
        assert updated_state["daily_losses"] == 0
        assert "performance_reset_time" in updated_state

    @pytest.mark.asyncio
    async def test_sends_reset_message(self, handlers_mixin, temp_state_dir):
        """Should send reset confirmation message."""
        state = {"daily_pnl": 100}
        write_state_file(temp_state_dir, state)

        await handlers_mixin._handle_reset_performance(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        assert "Reset" in handlers_mixin.last_message

    @pytest.mark.asyncio
    async def test_handles_missing_state_file(self, handlers_mixin):
        """Should handle missing state file."""
        await handlers_mixin._handle_reset_performance(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        assert "not found" in handlers_mixin.last_message


class TestHandleResetChallenge:
    """Tests for _handle_reset_challenge method."""

    @pytest.mark.asyncio
    async def test_resets_challenge(self, handlers_mixin, temp_state_dir):
        """Should reset challenge via tracker."""
        with patch('pearlalgo.market_agent.challenge_tracker.ChallengeTracker') as MockTracker:
            mock_tracker = MagicMock()
            mock_attempt = MagicMock()
            mock_attempt.attempt_id = 5
            mock_attempt.starting_balance = 50000.00
            mock_tracker.manual_reset.return_value = mock_attempt
            MockTracker.return_value = mock_tracker

            await handlers_mixin._handle_reset_challenge(
                query=MagicMock(),
                reply_markup=MagicMock(),
            )

            mock_tracker.manual_reset.assert_called_once_with(reason="telegram_reset")

    @pytest.mark.asyncio
    async def test_sends_reset_message(self, handlers_mixin, temp_state_dir):
        """Should send reset confirmation message."""
        with patch('pearlalgo.market_agent.challenge_tracker.ChallengeTracker') as MockTracker:
            mock_tracker = MagicMock()
            mock_attempt = MagicMock()
            mock_attempt.attempt_id = 1
            mock_attempt.starting_balance = 50000.00
            mock_tracker.manual_reset.return_value = mock_attempt
            MockTracker.return_value = mock_tracker

            await handlers_mixin._handle_reset_challenge(
                query=MagicMock(),
                reply_markup=MagicMock(),
            )

            assert "Reset" in handlers_mixin.last_message or "attempt" in handlers_mixin.last_message.lower()


class TestApplyPreferenceToggle:
    """Tests for _apply_preference_toggle method."""

    def test_toggles_standard_boolean(self, handlers_mixin, temp_state_dir):
        """Should toggle standard boolean preferences."""
        with patch('pearlalgo.utils.telegram_alerts.TelegramPrefs') as MockPrefs:
            mock_prefs = MagicMock()
            mock_prefs.get.return_value = True
            MockPrefs.return_value = mock_prefs

            result = handlers_mixin._apply_preference_toggle("some_preference")

            mock_prefs.set.assert_called_with("some_preference", False)
            assert result is False

    def test_toggles_snooze_on(self, handlers_mixin, temp_state_dir):
        """Should enable snooze when currently disabled."""
        with patch('pearlalgo.utils.telegram_alerts.TelegramPrefs') as MockPrefs:
            mock_prefs = MagicMock()
            mock_prefs.snooze_noncritical_alerts = False
            MockPrefs.return_value = mock_prefs

            result = handlers_mixin._apply_preference_toggle("snooze_noncritical_alerts")

            mock_prefs.enable_snooze.assert_called_once()
            assert result is True

    def test_toggles_snooze_off(self, handlers_mixin, temp_state_dir):
        """Should disable snooze when currently enabled."""
        with patch('pearlalgo.utils.telegram_alerts.TelegramPrefs') as MockPrefs:
            mock_prefs = MagicMock()
            mock_prefs.snooze_noncritical_alerts = True
            MockPrefs.return_value = mock_prefs

            result = handlers_mixin._apply_preference_toggle("snooze_noncritical_alerts")

            mock_prefs.disable_snooze.assert_called_once()
            assert result is False

    def test_dashboard_buttons_always_on(self, handlers_mixin, temp_state_dir):
        """Should keep dashboard buttons always on."""
        with patch('pearlalgo.utils.telegram_alerts.TelegramPrefs') as MockPrefs:
            mock_prefs = MagicMock()
            MockPrefs.return_value = mock_prefs

            result = handlers_mixin._apply_preference_toggle("dashboard_buttons")

            mock_prefs.set.assert_called_with("dashboard_buttons", True)
            assert result is True

    def test_resets_message_id_on_dashboard_toggle(self, handlers_mixin, temp_state_dir):
        """Should reset message ID when toggling pinned dashboard."""
        with patch('pearlalgo.utils.telegram_alerts.TelegramPrefs') as MockPrefs:
            mock_prefs = MagicMock()
            mock_prefs.get.side_effect = lambda k, d=None: False if k == "dashboard_edit_in_place" else d
            MockPrefs.return_value = mock_prefs

            result = handlers_mixin._apply_preference_toggle("dashboard_edit_in_place")

            # Should have set both the preference and reset the message ID
            calls = mock_prefs.set.call_args_list
            assert any(call[0][0] == "dashboard_message_id" for call in calls)


class TestApplyAlertModePreset:
    """Tests for _apply_alert_mode_preset method."""

    def test_applies_minimal_mode(self, handlers_mixin, temp_state_dir):
        """Should apply minimal alert mode."""
        with patch('pearlalgo.utils.telegram_alerts.TelegramPrefs') as MockPrefs:
            mock_prefs = MagicMock()
            MockPrefs.return_value = mock_prefs

            handlers_mixin._apply_alert_mode_preset("minimal")

            calls = mock_prefs.set.call_args_list
            assert any(c[0] == ("auto_chart_on_signal", False) for c in calls)
            assert any(c[0] == ("interval_notifications", False) for c in calls)

    def test_applies_standard_mode(self, handlers_mixin, temp_state_dir):
        """Should apply standard alert mode."""
        with patch('pearlalgo.utils.telegram_alerts.TelegramPrefs') as MockPrefs:
            mock_prefs = MagicMock()
            MockPrefs.return_value = mock_prefs

            handlers_mixin._apply_alert_mode_preset("standard")

            calls = mock_prefs.set.call_args_list
            assert any(c[0] == ("auto_chart_on_signal", True) for c in calls)
            assert any(c[0] == ("interval_notifications", True) for c in calls)

    def test_applies_verbose_mode(self, handlers_mixin, temp_state_dir):
        """Should apply verbose alert mode."""
        with patch('pearlalgo.utils.telegram_alerts.TelegramPrefs') as MockPrefs:
            mock_prefs = MagicMock()
            MockPrefs.return_value = mock_prefs

            handlers_mixin._apply_alert_mode_preset("verbose")

            calls = mock_prefs.set.call_args_list
            assert any(c[0] == ("auto_chart_on_signal", True) for c in calls)
            assert any(c[0] == ("signal_detail_expanded", True) for c in calls)


class TestHandleToggleStrategy:
    """Tests for _handle_toggle_strategy method."""

    @pytest.mark.asyncio
    async def test_toggles_strategy_on(self, handlers_mixin, temp_state_dir, monkeypatch):
        """Should enable a disabled strategy."""
        # Create config file
        config_dir = temp_state_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.yaml"
        monkeypatch.setenv("PEARLALGO_CONFIG_PATH", str(config_file))

        config = {
            "strategy": {
                "enabled_signals": [],
                "disabled_signals": ["momentum"],
            }
        }
        import yaml
        config_file.write_text(yaml.dump(config))

        try:
            await handlers_mixin._handle_toggle_strategy(
                query=MagicMock(),
                strategy_name="momentum",
                reply_markup=MagicMock(),
            )

            # Read updated config
            updated_config = yaml.safe_load(config_file.read_text())
            assert "momentum" in updated_config["strategy"]["enabled_signals"]
            assert "momentum" not in updated_config["strategy"]["disabled_signals"]
        finally:
            # Cleanup
            if config_file.exists():
                config_file.unlink()
            if (config_dir / "config.yaml.backup").exists():
                (config_dir / "config.yaml.backup").unlink()

    @pytest.mark.asyncio
    async def test_toggles_strategy_off(self, handlers_mixin, temp_state_dir, monkeypatch):
        """Should disable an enabled strategy."""
        config_dir = temp_state_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.yaml"
        monkeypatch.setenv("PEARLALGO_CONFIG_PATH", str(config_file))

        config = {
            "strategy": {
                "enabled_signals": ["momentum"],
                "disabled_signals": [],
            }
        }
        import yaml
        config_file.write_text(yaml.dump(config))

        try:
            await handlers_mixin._handle_toggle_strategy(
                query=MagicMock(),
                strategy_name="momentum",
                reply_markup=MagicMock(),
            )

            updated_config = yaml.safe_load(config_file.read_text())
            assert "momentum" not in updated_config["strategy"]["enabled_signals"]
            assert "momentum" in updated_config["strategy"]["disabled_signals"]
        finally:
            if config_file.exists():
                config_file.unlink()
            if (config_dir / "config.yaml.backup").exists():
                (config_dir / "config.yaml.backup").unlink()

    @pytest.mark.asyncio
    async def test_creates_backup(self, handlers_mixin, temp_state_dir, monkeypatch):
        """Should create backup before modifying config."""
        config_dir = temp_state_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.yaml"
        backup_file = config_dir / "config.yaml.backup"
        monkeypatch.setenv("PEARLALGO_CONFIG_PATH", str(config_file))

        config = {"strategy": {"enabled_signals": []}}
        import yaml
        config_file.write_text(yaml.dump(config))

        try:
            await handlers_mixin._handle_toggle_strategy(
                query=MagicMock(),
                strategy_name="test",
                reply_markup=MagicMock(),
            )

            assert backup_file.exists()
        finally:
            if config_file.exists():
                config_file.unlink()
            if backup_file.exists():
                backup_file.unlink()

    @pytest.mark.asyncio
    async def test_handles_missing_config(self, handlers_mixin, temp_state_dir, monkeypatch):
        """Should handle missing config file."""
        missing_config = temp_state_dir / "config" / "does_not_exist.yaml"
        monkeypatch.setenv("PEARLALGO_CONFIG_PATH", str(missing_config))

        await handlers_mixin._handle_toggle_strategy(
            query=MagicMock(),
            strategy_name="test",
            reply_markup=MagicMock(),
        )

        assert "not found" in handlers_mixin.last_message

    @pytest.mark.asyncio
    async def test_sends_restart_reminder(self, handlers_mixin, temp_state_dir, monkeypatch):
        """Should remind user to restart agent."""
        config_dir = temp_state_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.yaml"
        monkeypatch.setenv("PEARLALGO_CONFIG_PATH", str(config_file))

        config = {"strategy": {"enabled_signals": []}}
        import yaml
        config_file.write_text(yaml.dump(config))

        try:
            await handlers_mixin._handle_toggle_strategy(
                query=MagicMock(),
                strategy_name="test",
                reply_markup=MagicMock(),
            )

            assert "Restart" in handlers_mixin.last_message or "restart" in handlers_mixin.last_message.lower()
        finally:
            if config_file.exists():
                config_file.unlink()
            if (config_dir / "config.yaml.backup").exists():
                (config_dir / "config.yaml.backup").unlink()


class TestHandlerEdgeCases:
    """Edge case tests for handlers."""

    @pytest.mark.asyncio
    async def test_handles_concurrent_state_access(self, handlers_mixin, temp_state_dir):
        """Should handle concurrent state file access."""
        state = {"daily_pnl": 100}
        write_state_file(temp_state_dir, state)

        # Simulate concurrent access by running multiple operations
        await asyncio.gather(
            handlers_mixin._handle_reset_performance(MagicMock(), MagicMock()),
            handlers_mixin._handle_reset_performance(MagicMock(), MagicMock()),
        )

        # Should not raise and final state should be reset
        state_file = temp_state_dir / "state.json"
        final_state = json.loads(state_file.read_text())
        assert final_state["daily_pnl"] == 0.0

    @pytest.mark.asyncio
    async def test_handles_unicode_in_messages(self, handlers_mixin, temp_state_dir):
        """Should handle unicode characters in state."""
        state = {"note": "测试 🚀 emoji"}
        write_state_file(temp_state_dir, state)

        await handlers_mixin._handle_reset_performance(
            query=MagicMock(),
            reply_markup=MagicMock(),
        )

        # Should complete without error
        assert "Reset" in handlers_mixin.last_message
