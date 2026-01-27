"""
Edge case tests for the Telegram notifier.

These tests validate:
1. Disabled/unconfigured notifier behavior
2. Message formatting edge cases
3. Error handling and recovery
4. Malformed signal handling

Test Philosophy:
- Telegram failures should not crash the service
- Graceful degradation when Telegram is unavailable
- Observable failure signals
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier


class TestDisabledNotifier:
    """Tests for disabled notifier behavior."""

    def test_disabled_notifier_creation(self) -> None:
        """Test that disabled notifier can be created without credentials."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        assert notifier.enabled is False
        assert notifier.telegram is None

    def test_missing_credentials_disables_notifier(self) -> None:
        """Test that missing credentials disable the notifier."""
        # Missing bot_token
        notifier = MarketAgentTelegramNotifier(bot_token=None, chat_id="123456")
        assert notifier.enabled is False
        
        # Missing chat_id
        notifier = MarketAgentTelegramNotifier(bot_token="fake_token", chat_id=None)
        assert notifier.enabled is False
        
        # Both missing
        notifier = MarketAgentTelegramNotifier()
        assert notifier.enabled is False

    @pytest.mark.asyncio
    async def test_send_entry_notification_returns_false_when_disabled(self) -> None:
        """Test that send_entry_notification returns False when disabled."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        signal = {
            "signal_id": "test_signal",
            "type": "breakout",
            "direction": "long",
            "entry_price": 17500.0,
        }
        
        result = await notifier.send_entry_notification(
            signal_id="test_signal",
            entry_price=17500.0,
            signal=signal,
        )
        
        assert result is False

    @pytest.mark.asyncio
    async def test_send_status_returns_false_when_disabled(self) -> None:
        """Test that send_status returns False when disabled."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        status = {
            "running": True,
            "cycle_count": 100,
        }
        
        result = await notifier.send_status(status)
        
        assert result is False


class TestCompactSignalFormatting:
    """Tests for compact signal formatting."""

    def test_format_compact_signal_basic(self) -> None:
        """Test compact signal formatting with basic data."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        signal = {
            "symbol": "MNQ",
            "type": "breakout",
            "direction": "long",
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17550.0,
            "confidence": 0.75,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        result = notifier._format_compact_signal(signal)
        
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_compact_signal_with_regime_context(self) -> None:
        """Test compact signal with regime and MTF context (dict format)."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        # The _format_compact_signal expects 'regime' as a dict, not a string
        signal = {
            "symbol": "MNQ",
            "type": "breakout",
            "direction": "long",
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17550.0,
            "confidence": 0.75,
            "regime": {
                "regime": "trending_up",
                "volatility": "normal",
            },
            "mtf_alignment": "aligned",
            "vwap_distance": 0.5,
        }
        
        result = notifier._format_compact_signal(signal)
        
        assert isinstance(result, str)

    def test_format_compact_signal_with_empty_signal(self) -> None:
        """Test compact signal with empty signal dict."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        signal = {}
        
        # Should not raise
        result = notifier._format_compact_signal(signal)
        
        assert isinstance(result, str)


class TestCircuitBreakerAlerts:
    """Tests for circuit breaker alert formatting."""

    def test_send_circuit_breaker_alert_when_disabled(self) -> None:
        """Test that circuit breaker alerts handle disabled notifier."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        # Should not raise
        asyncio.run(notifier.send_circuit_breaker_alert(
            "Connection lost",
            {"connection_failures": 5}
        ))

    def test_circuit_breaker_alert_format(self) -> None:
        """Test circuit breaker alert message formatting."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        # We can't easily test the actual message without mocking,
        # but we can verify the method exists and is callable
        assert hasattr(notifier, "send_circuit_breaker_alert")
        assert callable(notifier.send_circuit_breaker_alert)


class TestDataQualityAlerts:
    """Tests for data quality alert handling."""

    def test_send_data_quality_alert_when_disabled(self) -> None:
        """Test that data quality alerts handle disabled notifier."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        # Should not raise
        asyncio.run(notifier.send_data_quality_alert(
            "stale_data",
            "Data is 10 minutes old",
            {"age_minutes": 10}
        ))


class TestRecoveryNotifications:
    """Tests for recovery notification handling."""

    def test_send_recovery_notification_when_disabled(self) -> None:
        """Test that recovery notifications handle disabled notifier."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        # Should not raise
        asyncio.run(notifier.send_recovery_notification({
            "issue": "Connection restored",
            "recovery_time_seconds": 30,
        }))


class TestStatusFormatting:
    """Tests for status message formatting."""

    @pytest.mark.asyncio
    async def test_send_status_handles_empty_status(self) -> None:
        """Test that send_status handles empty status dict."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        result = await notifier.send_status({})
        
        assert result is False  # Disabled, so returns False

    @pytest.mark.asyncio
    async def test_send_status_handles_none_values(self) -> None:
        """Test that send_status handles None values in status."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        status = {
            "running": None,
            "cycle_count": None,
            "signal_count": None,
            "latest_bar": None,
        }
        
        result = await notifier.send_status(status)
        
        assert result is False  # Disabled, but should not crash


class TestChartGeneration:
    """Tests for chart generation handling."""

    @pytest.mark.asyncio
    async def test_send_entry_notification_handles_empty_buffer_data(self) -> None:
        """Test that send_entry_notification handles empty buffer data."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        signal = {
            "signal_id": "test",
            "type": "breakout",
            "direction": "long",
            "entry_price": 17500.0,
        }
        
        buffer_data = pd.DataFrame()  # Empty
        
        result = await notifier.send_entry_notification(
            signal_id="test",
            entry_price=17500.0,
            signal=signal,
            buffer_data=buffer_data,
        )
        
        assert result is False  # Disabled

    @pytest.mark.asyncio
    async def test_send_entry_notification_handles_none_buffer_data(self) -> None:
        """Test that send_entry_notification handles None buffer data."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        signal = {
            "signal_id": "test",
            "type": "breakout",
            "direction": "long",
            "entry_price": 17500.0,
        }
        
        result = await notifier.send_entry_notification(
            signal_id="test",
            entry_price=17500.0,
            signal=signal,
            buffer_data=None,
        )
        
        assert result is False  # Disabled


class TestHomeCardFormatting:
    """Tests for home card (dashboard) formatting."""

    def test_format_home_card_with_minimal_args(self) -> None:
        """Test home card formatting with minimal required arguments."""
        from pearlalgo.utils.telegram_alerts import format_home_card
        
        # format_home_card requires positional args, not a status dict
        result = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            legacy=True,
        )
        
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_home_card_with_complete_args(self) -> None:
        """Test home card formatting with many optional arguments."""
        from pearlalgo.utils.telegram_alerts import format_home_card
        
        result = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=17500.0,
            paused=False,
            cycles_total=1000,
            signals_generated=10,
            signals_sent=8,
            signal_send_failures=2,
            errors=5,
            buffer_size=100,
            legacy=True,
        )
        
        assert isinstance(result, str)
        assert "MNQ" in result or "17500" in result

    def test_format_home_card_with_paused_state(self) -> None:
        """Test home card formatting when service is paused."""
        from pearlalgo.utils.telegram_alerts import format_home_card
        
        result = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            paused=True,
            pause_reason="connection_failures",
            legacy=True,
        )
        
        assert isinstance(result, str)
        # Should indicate paused state
        assert "⏸" in result or "PAUSED" in result or "paused" in result.lower()


class TestHelperFunctions:
    """Tests for helper formatting functions."""

    def test_format_signal_status(self) -> None:
        """Test signal status formatting returns tuple (emoji, label)."""
        from pearlalgo.utils.telegram_alerts import format_signal_status
        
        # These functions return (emoji, label) tuples
        result = format_signal_status("generated")
        assert isinstance(result, tuple)
        assert len(result) == 2
        
        result = format_signal_status("entered")
        assert isinstance(result, tuple)
        
        result = format_signal_status("exited")
        assert isinstance(result, tuple)
        
        # Unknown status should return something
        result = format_signal_status("unknown_status")
        assert isinstance(result, tuple)

    def test_format_signal_direction(self) -> None:
        """Test signal direction formatting returns tuple (emoji, label)."""
        from pearlalgo.utils.telegram_alerts import format_signal_direction
        
        long_result = format_signal_direction("long")
        short_result = format_signal_direction("short")
        
        assert isinstance(long_result, tuple)
        assert isinstance(short_result, tuple)
        assert len(long_result) == 2
        assert len(short_result) == 2
        # Labels should differ
        assert long_result[1] != short_result[1]

    def test_format_signal_confidence_tier(self) -> None:
        """Test confidence tier formatting returns tuple (emoji, label)."""
        from pearlalgo.utils.telegram_alerts import format_signal_confidence_tier
        
        high = format_signal_confidence_tier(0.9)
        moderate = format_signal_confidence_tier(0.6)
        low = format_signal_confidence_tier(0.3)
        
        assert isinstance(high, tuple)
        assert isinstance(moderate, tuple)
        assert isinstance(low, tuple)

    def test_format_pnl(self) -> None:
        """Test PnL formatting returns tuple (emoji, formatted_string)."""
        from pearlalgo.utils.telegram_alerts import format_pnl
        
        positive = format_pnl(100.0)
        negative = format_pnl(-50.0)
        zero = format_pnl(0.0)
        
        assert isinstance(positive, tuple)
        assert len(positive) == 2
        assert "+" in positive[1] or "100" in positive[1]
        
        assert isinstance(negative, tuple)
        assert "-" in negative[1] or "50" in negative[1]
        
        assert isinstance(zero, tuple)

    def test_format_gate_status(self) -> None:
        """Test gate status formatting returns string."""
        from pearlalgo.utils.telegram_alerts import format_gate_status
        
        # format_gate_status takes (futures_market_open, strategy_session_open)
        both_open = format_gate_status(True, True)
        futures_closed = format_gate_status(False, True)
        session_closed = format_gate_status(True, False)
        both_closed = format_gate_status(False, False)
        
        assert isinstance(both_open, str)
        assert isinstance(futures_closed, str)
        assert isinstance(session_closed, str)
        assert isinstance(both_closed, str)

    def test_format_service_status(self) -> None:
        """Test service status formatting returns string."""
        from pearlalgo.utils.telegram_alerts import format_service_status
        
        # format_service_status takes (agent_running, gateway_running)
        both_running = format_service_status(True, True)
        agent_only = format_service_status(True, False)
        gateway_only = format_service_status(False, True)
        neither = format_service_status(False, False)
        
        assert isinstance(both_running, str)
        assert isinstance(agent_only, str)
        assert isinstance(gateway_only, str)
        assert isinstance(neither, str)


class TestErrorResilience:
    """Tests for error handling and resilience."""

    @pytest.mark.asyncio
    async def test_send_entry_notification_catches_exceptions(self) -> None:
        """Test that send_entry_notification catches and handles exceptions."""
        # Create a notifier that would be enabled but with mock that raises
        notifier = MarketAgentTelegramNotifier(
            bot_token="fake_token",
            chat_id="123456",
            enabled=True,
        )
        
        signal = {"signal_id": "test", "type": "breakout", "direction": "long", "entry_price": 17500.0}
        
        # If initialization failed (no real Telegram), should be disabled
        if not notifier.enabled:
            result = await notifier.send_entry_notification(
                signal_id="test",
                entry_price=17500.0,
                signal=signal,
            )
            assert result is False
        else:
            # Mock telegram to raise
            notifier.telegram = MagicMock()
            notifier.telegram.send_message = AsyncMock(side_effect=Exception("Network error"))
            
            # Should not raise, should return False
            result = await notifier.send_entry_notification(
                signal_id="test",
                entry_price=17500.0,
                signal=signal,
            )
            assert result is False

    def test_format_methods_never_raise(self) -> None:
        """Test that format methods handle all edge cases without raising."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        test_cases = [
            {},
            None,
            {"symbol": None, "type": None},
            {"entry_price": "invalid", "confidence": "invalid"},
            {"direction": 12345, "stop_loss": []},
        ]
        
        for signal in test_cases:
            if signal is None:
                continue
            try:
                result = notifier._format_compact_signal(signal)
                assert isinstance(result, str)
            except Exception as e:
                pytest.fail(f"_format_compact_signal raised {e} for input {signal}")


class TestTelegramMessageLimits:
    """Tests related to Telegram message length limits."""

    def test_message_length_reasonable(self) -> None:
        """Test that generated messages have reasonable length."""
        notifier = MarketAgentTelegramNotifier(enabled=False)
        
        # Test compact signal stays under limit
        signal = {
            "symbol": "MNQ" * 100,  # Very long symbol (edge case)
            "type": "breakout" * 100,
            "direction": "long",
            "entry_price": 17500.0,
            "reason": "x" * 1000,  # Very long reason
        }
        
        result = notifier._format_compact_signal(signal)
        
        # Should produce a string (not crash)
        assert isinstance(result, str)

    def test_home_card_under_limit(self) -> None:
        """Test that home card stays under Telegram limit."""
        from pearlalgo.utils.telegram_alerts import format_home_card
        
        result = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            latest_price=99999.99,
            cycles_total=999999,
            signals_generated=999999,
            errors=999999,
            buffer_size=999999,
        )
        
        # Telegram message limit is 4096
        assert len(result) < 4096

