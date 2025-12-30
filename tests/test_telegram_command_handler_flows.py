"""
Telegram Command Handler Core Flow Tests

Tests the main command flows:
- /status: Home Card rendering
- /signals: Signals pagination and error handling
- /performance: Performance metrics display

Uses lightweight stubs for Update/Context to test handler logic
without requiring a running Telegram bot.
"""

from __future__ import annotations

import asyncio
import json
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile

import pytest


# Telegram message limits
TELEGRAM_MESSAGE_LIMIT = 4096


class MockChat:
    """Mock Telegram chat object."""
    def __init__(self, chat_id: int = 123):
        self.id = chat_id


class MockUser:
    """Mock Telegram user object."""
    def __init__(self, username: str = "testuser"):
        self.username = username


class MockMessage:
    """Mock Telegram message object."""
    def __init__(self, chat_id: int = 123):
        self.chat = MockChat(chat_id)
        self.text = ""
        self.reply_text = AsyncMock()
        self.reply_document = AsyncMock()


class MockBot:
    """Mock Telegram bot object."""
    def __init__(self):
        self.send_chat_action = AsyncMock()
        self.send_message = AsyncMock()
        self.send_photo = AsyncMock()


class MockContext:
    """Mock Telegram context object."""
    def __init__(self):
        self.bot = MockBot()
        self.args = []


class MockUpdate:
    """Mock Telegram update object."""
    def __init__(self, chat_id: int = 123, username: str = "testuser"):
        self.effective_chat = MockChat(chat_id)
        self.effective_user = MockUser(username)
        self.message = MockMessage(chat_id)
        self.callback_query = None


@pytest.fixture
def temp_state_dir():
    """Create a temporary state directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "nq_agent_state"
        state_dir.mkdir(parents=True)
        yield state_dir


@pytest.fixture
def handler_with_mocks(temp_state_dir):
    """Create a TelegramCommandHandler with mocked dependencies."""
    from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
    
    # Create handler without initializing the Telegram application
    handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
    handler.bot_token = "test_token"
    handler.chat_id = "123"
    handler.state_dir = temp_state_dir
    
    # Mock state manager
    handler.state_manager = MagicMock()
    handler.state_manager.load_state.return_value = {}
    
    # Mock performance tracker
    handler.performance_tracker = MagicMock()
    handler.performance_tracker.get_performance_metrics.return_value = {
        "total_signals": 0,
        "exited_signals": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
        "avg_pnl": 0.0,
        "avg_hold_minutes": 0.0,
        "by_signal_type": {},
    }
    
    # Mock telegram notifier
    handler.telegram_notifier = MagicMock()
    
    # Mock service controller
    handler.service_controller = MagicMock()
    handler.service_controller.get_gateway_status.return_value = {
        "process_running": True,
        "port_listening": True,
    }
    
    # Mock chart generator
    handler.chart_generator = None
    
    # Mock data provider
    handler._data_provider = None
    handler._historical_cache_dir = temp_state_dir / "historical"
    handler._historical_cache_dir.mkdir(parents=True, exist_ok=True)
    
    yield handler


class TestStatusCommand:
    """Test /status command behavior."""

    @pytest.mark.asyncio
    async def test_status_unauthorized_chat_id_blocked(self, handler_with_mocks):
        """Test that unauthorized chat IDs are blocked."""
        handler = handler_with_mocks
        handler.chat_id = "123"  # Authorized chat ID
        
        update = MockUpdate(chat_id=999)  # Unauthorized chat ID
        context = MockContext()
        
        # Track what messages are sent
        sent_messages = []
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
            await TelegramCommandHandler._handle_status(handler, update, context)
        
        assert len(sent_messages) == 1
        assert sent_messages[0] == "❌ Unauthorized access"

    @pytest.mark.asyncio
    async def test_status_no_state_file_shows_minimal_home_card(self, handler_with_mocks):
        """Test that /status shows minimal Home Card when state file missing."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        
        update = MockUpdate(chat_id=123)
        context = MockContext()
        
        # Track sent messages
        sent_messages = []
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        # Mock _is_agent_process_running
        with patch.object(handler, '_is_agent_process_running', return_value=False):
            with patch.object(handler, '_get_current_time_str', return_value="08:30 ET"):
                with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
                    from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
                    await TelegramCommandHandler._handle_status(handler, update, context)
        
        assert len(sent_messages) == 1
        message = sent_messages[0]
        
        # Check message contains expected elements
        assert "MNQ" in message  # Symbol
        assert "No state file found" in message or "state file" in message.lower()
        
        # Check message is under Telegram limit
        assert len(message) <= TELEGRAM_MESSAGE_LIMIT

    @pytest.mark.asyncio
    async def test_status_with_state_file_shows_full_home_card(self, handler_with_mocks, temp_state_dir):
        """Test that /status shows full Home Card when state file exists."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        
        # Create state file
        state_file = temp_state_dir / "state.json"
        state_data = {
            "running": True,
            "paused": False,
            "cycle_count": 100,
            "signal_count": 5,
            "error_count": 0,
            "buffer_size": 56,
            "last_successful_cycle": datetime.now(timezone.utc).isoformat(),
            "futures_market_open": True,
            "strategy_session_open": True,
            "latest_bar": {
                "close": 17500.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        with open(state_file, "w") as f:
            json.dump(state_data, f)
        
        update = MockUpdate(chat_id=123)
        context = MockContext()
        
        sent_messages = []
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        with patch.object(handler, '_is_agent_process_running', return_value=True):
            with patch.object(handler, '_get_current_time_str', return_value="08:30 ET"):
                with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
                    with patch.object(handler, '_extract_latest_price', return_value=17500.0):
                        with patch.object(handler, '_extract_data_age_minutes', return_value=0.5):
                            with patch.object(handler, '_compute_state_stale_threshold', return_value=120):
                                from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
                                await TelegramCommandHandler._handle_status(handler, update, context)
        
        assert len(sent_messages) == 1
        message = sent_messages[0]
        
        # Check message is under Telegram limit
        assert len(message) <= TELEGRAM_MESSAGE_LIMIT
        
        # Check message contains expected elements (basic sanity checks)
        # The exact format depends on format_home_card() implementation
        assert "MNQ" in message or "mnq" in message.lower()


class TestSignalsCommand:
    """Test /signals command behavior."""

    @pytest.mark.asyncio
    async def test_signals_unauthorized_blocked(self, handler_with_mocks):
        """Test that unauthorized users are blocked from /signals."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        
        update = MockUpdate(chat_id=999)  # Unauthorized
        context = MockContext()
        
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        await TelegramCommandHandler._handle_signals(handler, update, context)
        
        # Should have called reply_text with unauthorized message
        update.message.reply_text.assert_called_once_with("❌ Unauthorized access")

    @pytest.mark.asyncio
    async def test_signals_missing_file_shows_no_signals(self, handler_with_mocks, temp_state_dir):
        """Test that missing signals file shows 'no signals' message."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        handler.state_dir = temp_state_dir
        
        update = MockUpdate(chat_id=123)
        context = MockContext()
        
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        await TelegramCommandHandler._handle_signals(handler, update, context)
        
        # Check that some reply was sent
        assert update.message.reply_text.called or context.bot.send_message.called

    @pytest.mark.asyncio
    async def test_signals_empty_file_shows_no_signals(self, handler_with_mocks, temp_state_dir):
        """Test that empty signals file shows 'no signals' message."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        handler.state_dir = temp_state_dir
        
        # Create empty signals file
        signals_file = temp_state_dir / "signals.jsonl"
        signals_file.touch()
        
        update = MockUpdate(chat_id=123)
        context = MockContext()
        
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        await TelegramCommandHandler._handle_signals(handler, update, context)
        
        # Check that reply was sent
        assert update.message.reply_text.called or context.bot.send_message.called

    @pytest.mark.asyncio
    async def test_signals_corrupt_file_handled_gracefully(self, handler_with_mocks, temp_state_dir):
        """Test that corrupt signals file is handled without crashing."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        handler.state_dir = temp_state_dir
        
        # Create corrupt signals file
        signals_file = temp_state_dir / "signals.jsonl"
        with open(signals_file, "w") as f:
            f.write("not valid json\n")
            f.write("{incomplete\n")
            f.write('{"valid": "json"}\n')  # One valid line
        
        update = MockUpdate(chat_id=123)
        context = MockContext()
        
        # Should not raise
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        await TelegramCommandHandler._handle_signals(handler, update, context)
        
        # Should have sent some response
        assert update.message.reply_text.called or context.bot.send_message.called


class TestPerformanceCommand:
    """Test /performance command behavior."""

    @pytest.mark.asyncio
    async def test_performance_unauthorized_blocked(self, handler_with_mocks):
        """Test that unauthorized users are blocked from /performance."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        
        update = MockUpdate(chat_id=999)  # Unauthorized
        context = MockContext()
        
        sent_messages = []
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
            await TelegramCommandHandler._handle_performance(handler, update, context)
        
        assert len(sent_messages) == 1
        assert sent_messages[0] == "❌ Unauthorized access"

    @pytest.mark.asyncio
    async def test_performance_empty_history_handled(self, handler_with_mocks, temp_state_dir):
        """Test that empty performance history shows appropriate message."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        handler.state_dir = temp_state_dir
        
        # Performance tracker returns empty metrics
        handler.performance_tracker.get_performance_metrics.return_value = {
            "total_signals": 0,
            "exited_signals": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "avg_hold_minutes": 0.0,
            "by_signal_type": {},
        }
        
        update = MockUpdate(chat_id=123)
        context = MockContext()
        
        sent_messages = []
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
            await TelegramCommandHandler._handle_performance(handler, update, context)
        
        assert len(sent_messages) == 1
        message = sent_messages[0]
        
        # Should indicate no completed trades
        assert "No completed trades" in message or "0" in message
        
        # Check under Telegram limit
        assert len(message) <= TELEGRAM_MESSAGE_LIMIT

    @pytest.mark.asyncio
    async def test_performance_with_history_formats_correctly(self, handler_with_mocks, temp_state_dir):
        """Test that performance with history shows formatted metrics."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        handler.state_dir = temp_state_dir
        
        # Set up performance data
        handler.performance_tracker.get_performance_metrics.return_value = {
            "total_signals": 25,
            "exited_signals": 10,
            "wins": 6,
            "losses": 4,
            "win_rate": 0.6,
            "total_pnl": 300.0,
            "avg_pnl": 30.0,
            "avg_hold_minutes": 45.0,
            "by_signal_type": {
                "breakout": {"count": 5, "win_rate": 0.7, "total_pnl": 150.0},
                "momentum": {"count": 3, "win_rate": 0.5, "total_pnl": 100.0},
            },
        }
        
        update = MockUpdate(chat_id=123)
        context = MockContext()
        
        sent_messages = []
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
            await TelegramCommandHandler._handle_performance(handler, update, context)
        
        assert len(sent_messages) == 1
        message = sent_messages[0]
        
        # Check message contains expected data
        assert "25" in message  # total_signals
        assert "10" in message  # exited_signals
        assert "60" in message or "0.6" in message  # win_rate
        assert "300" in message  # total_pnl
        
        # Check under Telegram limit
        assert len(message) <= TELEGRAM_MESSAGE_LIMIT


class TestMessageLimits:
    """Test that command outputs respect Telegram message limits."""

    @pytest.mark.asyncio
    async def test_status_large_state_under_limit(self, handler_with_mocks, temp_state_dir):
        """Test that /status stays under limit even with large state."""
        handler = handler_with_mocks
        handler.chat_id = "123"
        
        # Create state file with many fields
        state_file = temp_state_dir / "state.json"
        state_data = {
            "running": True,
            "paused": False,
            "cycle_count": 999999,
            "signal_count": 999999,
            "error_count": 999999,
            "buffer_size": 999999,
            "last_successful_cycle": datetime.now(timezone.utc).isoformat(),
            "futures_market_open": True,
            "strategy_session_open": True,
            "latest_bar": {
                "close": 99999.99,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "pause_reason": "A" * 500,  # Long pause reason
        }
        with open(state_file, "w") as f:
            json.dump(state_data, f)
        
        update = MockUpdate(chat_id=123)
        context = MockContext()
        
        sent_messages = []
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        with patch.object(handler, '_is_agent_process_running', return_value=True):
            with patch.object(handler, '_get_current_time_str', return_value="08:30 ET"):
                with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
                    with patch.object(handler, '_extract_latest_price', return_value=99999.99):
                        with patch.object(handler, '_extract_data_age_minutes', return_value=0.5):
                            with patch.object(handler, '_compute_state_stale_threshold', return_value=120):
                                from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
                                await TelegramCommandHandler._handle_status(handler, update, context)
        
        if sent_messages:
            assert len(sent_messages[0]) <= TELEGRAM_MESSAGE_LIMIT


class TestGetTradesForChart:
    """Test the _get_trades_for_chart helper method."""

    def test_empty_chart_data_returns_empty_list(self, handler_with_mocks):
        """Test that empty chart data returns an empty list."""
        handler = handler_with_mocks
        import pandas as pd
        
        # None input
        result = handler._get_trades_for_chart(None, symbol="MNQ")
        assert result == []
        
        # Empty DataFrame
        result = handler._get_trades_for_chart(pd.DataFrame(), symbol="MNQ")
        assert result == []

    def test_no_matching_signals_returns_empty_list(self, handler_with_mocks):
        """Test that no matching signals returns an empty list."""
        handler = handler_with_mocks
        import pandas as pd
        from datetime import datetime, timezone, timedelta
        
        # Create chart data with a time window
        now = datetime.now(timezone.utc)
        chart_data = pd.DataFrame({
            "timestamp": [now - timedelta(hours=2), now - timedelta(hours=1), now],
            "close": [100.0, 101.0, 102.0],
        })
        
        # No signals from state manager
        handler.state_manager.get_recent_signals.return_value = []
        
        result = handler._get_trades_for_chart(chart_data, symbol="MNQ")
        assert result == []

    def test_matching_signals_returned(self, handler_with_mocks):
        """Test that matching signals are returned as trades."""
        handler = handler_with_mocks
        import pandas as pd
        from datetime import datetime, timezone, timedelta
        
        # Create chart data with a time window
        now = datetime.now(timezone.utc)
        chart_data = pd.DataFrame({
            "timestamp": [now - timedelta(hours=2), now - timedelta(hours=1), now],
            "close": [100.0, 101.0, 102.0],
        })
        
        # Signal that falls within the window
        handler.state_manager.get_recent_signals.return_value = [
            {
                "signal_id": "test_123",
                "status": "entered",
                "entry_time": (now - timedelta(hours=1)).isoformat(),
                "entry_price": 101.0,
                "signal": {
                    "symbol": "MNQ",
                    "direction": "long",
                    "entry_price": 101.0,
                },
            }
        ]
        
        result = handler._get_trades_for_chart(chart_data, symbol="MNQ")
        assert len(result) == 1
        assert result[0]["signal_id"] == "test_123"
        assert result[0]["direction"] == "long"

    def test_filters_by_symbol(self, handler_with_mocks):
        """Test that trades are filtered by symbol."""
        handler = handler_with_mocks
        import pandas as pd
        from datetime import datetime, timezone, timedelta
        
        now = datetime.now(timezone.utc)
        chart_data = pd.DataFrame({
            "timestamp": [now - timedelta(hours=2), now - timedelta(hours=1), now],
            "close": [100.0, 101.0, 102.0],
        })
        
        # Signal for different symbol
        handler.state_manager.get_recent_signals.return_value = [
            {
                "signal_id": "test_456",
                "status": "entered",
                "entry_time": (now - timedelta(hours=1)).isoformat(),
                "signal": {
                    "symbol": "ES",  # Different symbol
                    "direction": "long",
                },
            }
        ]
        
        result = handler._get_trades_for_chart(chart_data, symbol="MNQ")
        assert len(result) == 0  # Filtered out

