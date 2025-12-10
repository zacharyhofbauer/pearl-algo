"""
Unit tests for Telegram exit alerts.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from pearlalgo.utils.telegram_alerts import TelegramAlerts


@pytest.fixture
def telegram_alerts():
    """Create Telegram alerts instance for testing."""
    return TelegramAlerts(
        bot_token="test_token",
        chat_id="test_chat",
        enabled=True,
    )


@pytest.mark.asyncio
async def test_notify_exit(telegram_alerts):
    """Test exit notification."""
    telegram_alerts.send_message = AsyncMock(return_value=True)

    await telegram_alerts.notify_exit(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        exit_price=4520.0,
        size=1,
        realized_pnl=20.0,
        hold_duration="2 hours",
        exit_reason="Take profit hit",
    )

    telegram_alerts.send_message.assert_called_once()
    message = telegram_alerts.send_message.call_args[1]["message"]
    assert "ES" in message
    assert "4500" in message
    assert "4520" in message
    assert "20.0" in message


@pytest.mark.asyncio
async def test_notify_stop_loss(telegram_alerts):
    """Test stop loss notification."""
    telegram_alerts.send_message = AsyncMock(return_value=True)

    await telegram_alerts.notify_stop_loss(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        stop_price=4490.0,
        size=1,
        realized_pnl=-10.0,
    )

    telegram_alerts.send_message.assert_called_once()
    message = telegram_alerts.send_message.call_args[1]["message"]
    assert "Stop Loss Hit" in message
    assert "ES" in message
    assert "-10.0" in message


@pytest.mark.asyncio
async def test_notify_take_profit(telegram_alerts):
    """Test take profit notification."""
    telegram_alerts.send_message = AsyncMock(return_value=True)

    await telegram_alerts.notify_take_profit(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        target_price=4520.0,
        size=1,
        realized_pnl=20.0,
    )

    telegram_alerts.send_message.assert_called_once()
    message = telegram_alerts.send_message.call_args[1]["message"]
    assert "Take Profit Hit" in message
    assert "ES" in message
    assert "20.0" in message


@pytest.mark.asyncio
async def test_notify_position_update(telegram_alerts):
    """Test position update notification."""
    telegram_alerts.send_message = AsyncMock(return_value=True)

    await telegram_alerts.notify_position_update(
        symbol="ES",
        direction="long",
        entry_price=4500.0,
        current_price=4510.0,
        size=1,
        unrealized_pnl=10.0,
    )

    telegram_alerts.send_message.assert_called_once()
    message = telegram_alerts.send_message.call_args[1]["message"]
    assert "Position Update" in message
    assert "ES" in message
    assert "10.0" in message
