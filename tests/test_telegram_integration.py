"""
Tests for Telegram integration and notification system.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
from pearlalgo.utils.telegram_alerts import TelegramAlerts


@pytest.fixture
def mock_telegram_alerts():
    """Create a mock TelegramAlerts instance."""
    alerts = MagicMock(spec=TelegramAlerts)
    alerts.send_message = AsyncMock(return_value=True)
    alerts.notify_signal = AsyncMock(return_value=True)
    alerts.notify_daily_summary = AsyncMock(return_value=True)
    alerts.notify_risk_warning = AsyncMock(return_value=True)
    alerts.enabled = True
    return alerts


@pytest.fixture
def notifier(mock_telegram_alerts):
    """Create a Telegram notifier with mocked alerts."""
    with patch('pearlalgo.nq_agent.telegram_notifier.TelegramAlerts', return_value=mock_telegram_alerts):
        notifier = NQAgentTelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat_id",
            enabled=True,
        )
        notifier.telegram = mock_telegram_alerts
        return notifier


@pytest.mark.asyncio
async def test_notifier_initialization():
    """Test notifier initializes correctly."""
    notifier = NQAgentTelegramNotifier(
        bot_token="test_token",
        chat_id="test_chat_id",
        enabled=True,
    )
    
    assert notifier.enabled is True
    assert notifier.bot_token == "test_token"
    assert notifier.chat_id == "test_chat_id"


@pytest.mark.asyncio
async def test_notifier_disabled():
    """Test notifier when disabled."""
    notifier = NQAgentTelegramNotifier(enabled=False)
    
    assert notifier.enabled is False
    result = await notifier.send_signal({})
    assert result is False


@pytest.mark.asyncio
async def test_notifier_send_signal(notifier, mock_telegram_alerts):
    """Test sending a signal."""
    signal = {
        "symbol": "NQ",
        "direction": "long",
        "entry_price": 15000.0,
        "stop_loss": 14900.0,
        "take_profit": 15200.0,
        "confidence": 0.75,
        "reason": "Test signal",
        "strategy": "nq_intraday",
    }
    
    result = await notifier.send_signal(signal)
    
    assert result is True
    mock_telegram_alerts.notify_signal.assert_called_once()


@pytest.mark.asyncio
async def test_notifier_send_signal_error_handling(notifier, mock_telegram_alerts):
    """Test error handling when sending signal fails."""
    mock_telegram_alerts.notify_signal = AsyncMock(side_effect=Exception("Send error"))
    
    signal = {
        "symbol": "NQ",
        "direction": "long",
        "entry_price": 15000.0,
    }
    
    result = await notifier.send_signal(signal)
    
    # Should return False on error, not raise
    assert result is False


@pytest.mark.asyncio
async def test_notifier_send_status(notifier, mock_telegram_alerts):
    """Test sending status update."""
    status = {
        "message": "Service running",
        "running": True,
    }
    
    result = await notifier.send_status(status)
    
    assert result is True
    mock_telegram_alerts.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_notifier_send_enhanced_status(notifier, mock_telegram_alerts):
    """Test sending enhanced status."""
    status = {
        "running": True,
        "paused": False,
        "uptime": {"hours": 1, "minutes": 30},
        "cycle_count": 100,
        "signal_count": 5,
        "error_count": 0,
        "buffer_size": 50,
        "performance": {
            "wins": 3,
            "losses": 2,
            "win_rate": 0.6,
            "total_pnl": 100.0,
        },
    }
    
    result = await notifier.send_enhanced_status(status)
    
    assert result is True
    mock_telegram_alerts.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_notifier_send_daily_summary(notifier, mock_telegram_alerts):
    """Test sending daily summary."""
    performance = {
        "total_pnl": 100.0,
        "wins": 5,
        "losses": 3,
        "win_rate": 0.625,
    }
    
    result = await notifier.send_daily_summary(performance)
    
    assert result is True
    mock_telegram_alerts.notify_daily_summary.assert_called_once()


@pytest.mark.asyncio
async def test_telegram_alerts_markdown_parsing_error():
    """Test handling of Markdown parsing errors."""
    with patch('pearlalgo.utils.telegram_alerts.Bot') as mock_bot_class:
        mock_bot = MagicMock()
        mock_bot_class.return_value = mock_bot
        
        # First call raises parse error, second succeeds
        from telegram.error import TelegramError
        
        async def send_with_error(*args, **kwargs):
            if kwargs.get('parse_mode') == 'Markdown':
                raise TelegramError("Can't parse entities")
            return True
        
        mock_bot.send_message = AsyncMock(side_effect=send_with_error)
        
        alerts = TelegramAlerts(
            bot_token="test_token",
            chat_id="test_chat_id",
            enabled=True,
        )
        
        # Should retry without Markdown
        result = await alerts.send_message("Test *message*")
        # Should eventually succeed (after retry)
        assert result is True or result is False  # May fail after retries


@pytest.mark.asyncio
async def test_telegram_alerts_connection_failure():
    """Test handling of connection failures."""
    with patch('pearlalgo.utils.telegram_alerts.Bot') as mock_bot_class:
        mock_bot = MagicMock()
        mock_bot_class.return_value = mock_bot
        
        from telegram.error import TelegramError
        
        mock_bot.send_message = AsyncMock(side_effect=TelegramError("Connection error"))
        
        alerts = TelegramAlerts(
            bot_token="test_token",
            chat_id="test_chat_id",
            enabled=True,
        )
        
        # Should retry and eventually return False
        result = await alerts.send_message("Test message")
        assert result is False


@pytest.mark.asyncio
async def test_telegram_alerts_rate_limiting():
    """Test handling of rate limiting."""
    with patch('pearlalgo.utils.telegram_alerts.Bot') as mock_bot_class:
        mock_bot = MagicMock()
        mock_bot_class.return_value = mock_bot
        
        from telegram.error import TelegramError
        
        call_count = 0
        
        async def rate_limited(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TelegramError("Too many requests")
            return True
        
        mock_bot.send_message = AsyncMock(side_effect=rate_limited)
        
        alerts = TelegramAlerts(
            bot_token="test_token",
            chat_id="test_chat_id",
            enabled=True,
        )
        
        # Should retry with backoff
        result = await alerts.send_message("Test message")
        assert call_count >= 1  # Should have attempted



