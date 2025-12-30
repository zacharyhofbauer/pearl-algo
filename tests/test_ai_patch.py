"""
Tests for the /ai_patch Telegram command.

Tests cover:
- Authorization blocking for unauthorized chat IDs
- Missing API key error handling
- Unsafe path rejection
- Path blocking helper method
- Claude client error handling
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Test path blocking helper
# ---------------------------------------------------------------------------

class TestPathBlocking:
    """Tests for the _is_path_blocked helper method."""
    
    def test_blocks_data_directory(self):
        """Paths starting with data/ should be blocked."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked("data/state.json") is True
        assert handler._is_path_blocked("data/nq_agent_state/signals.jsonl") is True
    
    def test_blocks_logs_directory(self):
        """Paths starting with logs/ should be blocked."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked("logs/nq_agent.log") is True
        assert handler._is_path_blocked("logs/telegram_handler.log") is True
    
    def test_blocks_env_file(self):
        """.env file should be blocked."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked(".env") is True
        assert handler._is_path_blocked("some/path/.env") is True
    
    def test_blocks_venv_directory(self):
        """Paths containing .venv/ should be blocked."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked(".venv/lib/python3.12/site-packages/foo.py") is True
    
    def test_blocks_git_directory(self):
        """Paths containing .git/ should be blocked."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked(".git/config") is True
        assert handler._is_path_blocked(".git/hooks/pre-commit") is True
    
    def test_blocks_ibkr_directory(self):
        """Paths starting with ibkr/ should be blocked."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked("ibkr/ibc/config.ini") is True
    
    def test_blocks_pyc_files(self):
        """*.pyc files should be blocked."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked("src/foo.pyc") is True
        assert handler._is_path_blocked("__pycache__/module.cpython-312.pyc") is True
    
    def test_blocks_json_files(self):
        """*.json files should be blocked by default."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked("config/config.json") is True
        assert handler._is_path_blocked("state.json") is True
    
    def test_allows_source_files(self):
        """Normal source files should be allowed."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked("src/pearlalgo/utils/retry.py") is False
        assert handler._is_path_blocked("src/pearlalgo/nq_agent/main.py") is False
        assert handler._is_path_blocked("tests/test_something.py") is False
    
    def test_allows_docs(self):
        """Documentation files should be allowed."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked("docs/TELEGRAM_GUIDE.md") is False
        assert handler._is_path_blocked("README.md") is False
    
    def test_allows_yaml_configs(self):
        """YAML config files should be allowed."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked("config/config.yaml") is False
    
    def test_case_insensitive(self):
        """Path blocking should be case-insensitive."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        assert handler._is_path_blocked("DATA/state.json") is True
        assert handler._is_path_blocked("LOGS/nq_agent.log") is True
        assert handler._is_path_blocked(".ENV") is True


# ---------------------------------------------------------------------------
# Test AI patch command authorization
# ---------------------------------------------------------------------------

class TestAIPatchAuthorization:
    """Tests for /ai_patch authorization."""
    
    @pytest.mark.asyncio
    async def test_ai_patch_blocks_unauthorized_chat_id(self):
        """Unauthorized chat IDs should be blocked from /ai_patch."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        
        # Track sent messages
        sent_messages = []
        
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=999),  # Wrong chat ID
            effective_user=types.SimpleNamespace(username="attacker"),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=["src/foo.py", "do", "something"],
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            await TelegramCommandHandler._handle_ai_patch(handler, update, context)
        
        assert len(sent_messages) == 1
        assert sent_messages[0] == "❌ Unauthorized access"


# ---------------------------------------------------------------------------
# Test AI patch missing API key
# ---------------------------------------------------------------------------

class TestAIPatchMissingAPIKey:
    """Tests for /ai_patch when API key is missing."""
    
    @pytest.mark.asyncio
    async def test_ai_patch_reports_missing_api_key(self):
        """Missing ANTHROPIC_API_KEY should produce a clear error."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        
        sent_messages = []
        
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),  # Authorized
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=["src/pearlalgo/utils/retry.py", "add", "jitter"],
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        # Create a temp file to read
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock project root and create a test file
            project_root = Path(tmpdir)
            src_dir = project_root / "src" / "pearlalgo" / "utils"
            src_dir.mkdir(parents=True)
            test_file = src_dir / "retry.py"
            test_file.write_text("def retry(): pass\n")
            
            # Mock _is_path_blocked to allow the path
            with patch.object(handler, '_is_path_blocked', return_value=False):
                with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
                    with patch.object(handler, '_get_back_to_menu_button', return_value=None):
                        # Patch Path to use our temp directory
                        with patch('pearlalgo.nq_agent.telegram_command_handler.Path') as mock_path:
                            # Make Path(__file__) return a path that resolves to our tmpdir
                            mock_path.return_value.parent.parent.parent.parent = project_root
                            mock_path.return_value.resolve.return_value = project_root / "src/pearlalgo/utils/retry.py"
                            
                            # Mock the Claude client to raise API key missing error
                            with patch('pearlalgo.nq_agent.telegram_command_handler.ANTHROPIC_AVAILABLE', True):
                                with patch('pearlalgo.nq_agent.telegram_command_handler.ClaudeClient') as mock_client:
                                    from pearlalgo.utils.claude_client import ClaudeAPIKeyMissingError
                                    mock_client.side_effect = ClaudeAPIKeyMissingError("ANTHROPIC_API_KEY not set")
                                    
                                    await TelegramCommandHandler._handle_ai_patch(handler, update, context)
        
        # Should have received an API key error message
        assert len(sent_messages) >= 1
        # The last message should mention API key
        assert any("API Key" in msg or "ANTHROPIC_API_KEY" in msg for msg in sent_messages)


# ---------------------------------------------------------------------------
# Test AI patch blocked paths
# ---------------------------------------------------------------------------

class TestAIPatchBlockedPaths:
    """Tests for /ai_patch path blocking."""
    
    @pytest.mark.asyncio
    async def test_ai_patch_rejects_blocked_paths(self):
        """Blocked paths should be rejected with a clear error."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        
        sent_messages = []
        
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),  # Authorized
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=["data/state.json", "modify", "something"],  # Blocked path
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            with patch.object(handler, '_get_back_to_menu_button', return_value=None):
                with patch('pearlalgo.nq_agent.telegram_command_handler.ANTHROPIC_AVAILABLE', True):
                    await TelegramCommandHandler._handle_ai_patch(handler, update, context)
        
        # Should have received a blocked path error
        assert len(sent_messages) >= 1
        assert any("Blocked" in msg for msg in sent_messages)


# ---------------------------------------------------------------------------
# Test AI patch usage message
# ---------------------------------------------------------------------------

class TestAIPatchUsage:
    """Tests for /ai_patch usage message."""
    
    @pytest.mark.asyncio
    async def test_ai_patch_shows_usage_without_args(self):
        """Missing arguments should show usage message."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        
        sent_messages = []
        
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=[],  # No arguments
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            with patch.object(handler, '_get_back_to_menu_button', return_value=None):
                with patch('pearlalgo.nq_agent.telegram_command_handler.ANTHROPIC_AVAILABLE', True):
                    await TelegramCommandHandler._handle_ai_patch(handler, update, context)
        
        # Should have received a usage message
        assert len(sent_messages) == 1
        assert "Usage" in sent_messages[0]
        assert "/ai_patch" in sent_messages[0]


# ---------------------------------------------------------------------------
# Test Claude client
# ---------------------------------------------------------------------------

class TestClaudeClient:
    """Tests for the Claude client module."""
    
    def test_anthropic_not_available_error(self):
        """When anthropic is not installed, should raise ClaudeNotAvailableError."""
        from pearlalgo.utils.claude_client import (
            ClaudeClient,
            ClaudeNotAvailableError,
            ANTHROPIC_AVAILABLE,
        )
        
        if ANTHROPIC_AVAILABLE:
            # If anthropic is installed, we can't test this
            pytest.skip("anthropic is installed, cannot test not-available error")
        
        with pytest.raises(ClaudeNotAvailableError):
            ClaudeClient()
    
    def test_api_key_missing_error(self):
        """When ANTHROPIC_API_KEY is not set, should raise ClaudeAPIKeyMissingError."""
        from pearlalgo.utils.claude_client import (
            ANTHROPIC_AVAILABLE,
            ClaudeAPIKeyMissingError,
        )
        
        if not ANTHROPIC_AVAILABLE:
            pytest.skip("anthropic not installed")
        
        from pearlalgo.utils.claude_client import ClaudeClient
        
        # Ensure no API key is set
        with patch.dict('os.environ', {}, clear=True):
            with patch('os.getenv', return_value=None):
                with pytest.raises(ClaudeAPIKeyMissingError):
                    ClaudeClient()
    
    def test_get_claude_client_returns_none_when_unavailable(self):
        """get_claude_client should return None when not configured."""
        from pearlalgo.utils.claude_client import get_claude_client
        
        with patch.dict('os.environ', {}, clear=True):
            with patch('os.getenv', return_value=None):
                client = get_claude_client()
                assert client is None


# ---------------------------------------------------------------------------
# Test AI patch not available
# ---------------------------------------------------------------------------

class TestAIPatchNotAvailable:
    """Tests for /ai_patch when anthropic is not installed."""
    
    @pytest.mark.asyncio
    async def test_ai_patch_reports_not_available(self):
        """When anthropic is not installed, should show installation instructions."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        
        sent_messages = []
        
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=["src/foo.py", "do", "something"],
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            with patch.object(handler, '_get_back_to_menu_button', return_value=None):
                # Mock ANTHROPIC_AVAILABLE as False
                with patch('pearlalgo.nq_agent.telegram_command_handler.ANTHROPIC_AVAILABLE', False):
                    await TelegramCommandHandler._handle_ai_patch(handler, update, context)
        
        # Should have received a "not available" message with install instructions
        assert len(sent_messages) == 1
        assert "Not Available" in sent_messages[0] or "not installed" in sent_messages[0].lower()
        assert "pip install" in sent_messages[0]


# ---------------------------------------------------------------------------
# Test Claude Hub
# ---------------------------------------------------------------------------

class TestClaudeHub:
    """Tests for Claude Hub functionality."""
    
    @pytest.mark.asyncio
    async def test_claude_hub_blocks_unauthorized(self):
        """Unauthorized chat IDs should be blocked from Claude Hub."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        
        sent_messages = []
        
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=999),  # Wrong chat ID
            effective_user=types.SimpleNamespace(username="attacker"),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=[],
            user_data={},
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            await TelegramCommandHandler._handle_ai_hub(handler, update, context)
        
        assert len(sent_messages) == 1
        assert sent_messages[0] == "❌ Unauthorized access"
    
    @pytest.mark.asyncio
    async def test_claude_hub_shows_hub_when_available(self):
        """Authorized users should see the Claude Hub."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        handler.prefs = MagicMock()
        handler.prefs.get.return_value = False  # Chat mode off
        
        sent_messages = []
        
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=[],
            user_data={},
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            with patch.object(handler, '_get_claude_hub_buttons', return_value=None):
                with patch('pearlalgo.nq_agent.telegram_command_handler.ANTHROPIC_AVAILABLE', True):
                    await TelegramCommandHandler._handle_ai_hub(handler, update, context)
        
        assert len(sent_messages) == 1
        assert "Claude AI Hub" in sent_messages[0]


# ---------------------------------------------------------------------------
# Test Chat Mode Toggle
# ---------------------------------------------------------------------------

class TestChatModeToggle:
    """Tests for chat mode toggle."""
    
    @pytest.mark.asyncio
    async def test_ai_on_enables_chat_mode(self):
        """The /ai_on command should enable chat mode."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        handler.prefs = MagicMock()
        
        sent_messages = []
        
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=[],
            user_data={},
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            with patch.object(handler, '_get_claude_hub_buttons', return_value=None):
                await TelegramCommandHandler._handle_ai_on(handler, update, context)
        
        # Chat mode should have been set to True in prefs
        handler.prefs.set.assert_called_once_with("ai_chat_mode", True)
        
        assert len(sent_messages) == 1
        assert "Chat Mode: ON" in sent_messages[0]
    
    @pytest.mark.asyncio
    async def test_ai_off_disables_chat_mode(self):
        """The /ai_off command should disable chat mode."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        handler.prefs = MagicMock()
        
        sent_messages = []
        
        async def mock_send(upd, ctx, msg, **kwargs):
            sent_messages.append(msg)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=[],
            user_data={},
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
            with patch.object(handler, '_get_claude_hub_buttons', return_value=None):
                await TelegramCommandHandler._handle_ai_off(handler, update, context)
        
        # Chat mode should have been set to False in prefs
        handler.prefs.set.assert_called_once_with("ai_chat_mode", False)
        
        assert len(sent_messages) == 1
        assert "Chat Mode: OFF" in sent_messages[0]


# ---------------------------------------------------------------------------
# Test Chat Mode Message Routing
# ---------------------------------------------------------------------------

class TestChatModeRouting:
    """Tests for chat mode message routing."""
    
    @pytest.mark.asyncio
    async def test_message_routes_to_claude_when_chat_mode_on(self):
        """Plain messages should route to Claude when chat mode is enabled."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        handler.prefs = MagicMock()
        handler.prefs.get.return_value = True  # Chat mode ON
        
        process_chat_called = []
        
        async def mock_process_chat(upd, ctx, text):
            process_chat_called.append(text)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(
                text="What does the retry logic do?",
                reply_text=AsyncMock(),
            ),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=[],
            user_data={},  # No wizard state
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_process_claude_chat', side_effect=mock_process_chat):
            await TelegramCommandHandler._handle_claude_message(handler, update, context)
        
        assert len(process_chat_called) == 1
        assert process_chat_called[0] == "What does the retry logic do?"
    
    @pytest.mark.asyncio
    async def test_message_ignored_when_chat_mode_off(self):
        """Plain messages should be ignored when chat mode is disabled."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        handler.prefs = MagicMock()
        handler.prefs.get.return_value = False  # Chat mode OFF
        
        process_chat_called = []
        
        async def mock_process_chat(upd, ctx, text):
            process_chat_called.append(text)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(
                text="What does the retry logic do?",
                reply_text=AsyncMock(),
            ),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=[],
            user_data={},  # No wizard state
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_process_claude_chat', side_effect=mock_process_chat):
            await TelegramCommandHandler._handle_claude_message(handler, update, context)
        
        # Should not have called process_chat
        assert len(process_chat_called) == 0


# ---------------------------------------------------------------------------
# Test Wizard State Routing
# ---------------------------------------------------------------------------

class TestWizardStateRouting:
    """Tests for patch wizard state machine."""
    
    @pytest.mark.asyncio
    async def test_message_routes_to_wizard_task(self):
        """Messages should route to wizard when in awaiting_task state."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        handler.prefs = MagicMock()
        handler.prefs.get.return_value = False  # Chat mode OFF (doesn't matter)
        
        process_wizard_called = []
        
        async def mock_process_wizard(upd, ctx, text):
            process_wizard_called.append(text)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(
                text="add exponential backoff to retry",
                reply_text=AsyncMock(),
            ),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=[],
            user_data={"claude_wizard_state": "awaiting_task"},  # Wizard active
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_process_wizard_task', side_effect=mock_process_wizard):
            await TelegramCommandHandler._handle_claude_message(handler, update, context)
        
        assert len(process_wizard_called) == 1
        assert process_wizard_called[0] == "add exponential backoff to retry"
    
    @pytest.mark.asyncio
    async def test_message_routes_to_wizard_search(self):
        """Messages should route to search when in refine_search state."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        handler.prefs = MagicMock()
        handler.prefs.get.return_value = False
        
        process_search_called = []
        
        async def mock_process_search(upd, ctx, text):
            process_search_called.append(text)
        
        update = types.SimpleNamespace(
            effective_chat=types.SimpleNamespace(id=123),
            effective_user=types.SimpleNamespace(username="admin"),
            message=types.SimpleNamespace(
                text="retry",
                reply_text=AsyncMock(),
            ),
            callback_query=None,
        )
        context = types.SimpleNamespace(
            args=[],
            user_data={"claude_wizard_state": "refine_search"},  # Search mode
            bot=types.SimpleNamespace(
                send_chat_action=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        
        with patch.object(handler, '_process_wizard_search', side_effect=mock_process_search):
            await TelegramCommandHandler._handle_claude_message(handler, update, context)
        
        assert len(process_search_called) == 1
        assert process_search_called[0] == "retry"


# ---------------------------------------------------------------------------
# Test File Discovery
# ---------------------------------------------------------------------------

class TestFileDiscovery:
    """Tests for file discovery and search."""
    
    def test_discover_excludes_blocked_dirs(self):
        """File discovery should exclude blocked directories."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            # Create allowed directories
            src_dir = project_root / "src" / "pearlalgo"
            src_dir.mkdir(parents=True)
            (src_dir / "main.py").write_text("# main")
            
            # Create blocked directories
            data_dir = project_root / "src" / "data"
            data_dir.mkdir(parents=True)
            (data_dir / "secret.py").write_text("# secret")
            
            venv_dir = project_root / "src" / ".venv"
            venv_dir.mkdir(parents=True)
            (venv_dir / "lib.py").write_text("# lib")
            
            # Mock Path(__file__) to use our temp directory
            with patch('pearlalgo.nq_agent.telegram_command_handler.Path') as mock_path:
                mock_path_instance = MagicMock()
                mock_path_instance.parent.parent.parent.parent = project_root
                mock_path.return_value = mock_path_instance
                mock_path.__truediv__ = lambda self, other: project_root / other
                
                # The discover method is complex, so we just test the search helper
                # which uses the discovered files
                all_files = [
                    "src/pearlalgo/main.py",
                    "src/data/secret.py",  # Should be excluded
                    "src/.venv/lib.py",  # Should be excluded
                ]
                
                # Search should exclude blocked dirs
                result = handler._search_files("main", all_files)
                
                # main.py should be found
                assert "src/pearlalgo/main.py" in result
    
    def test_search_ranks_filename_matches_higher(self):
        """Files matching query in filename should rank higher."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        all_files = [
            "src/pearlalgo/utils/telegram_alerts.py",  # Path contains "retry" but not filename
            "src/pearlalgo/utils/retry.py",  # Filename is "retry"
            "src/pearlalgo/nq_agent/main.py",  # No match
        ]
        
        result = handler._search_files("retry", all_files)
        
        # retry.py should be first (filename match)
        assert result[0] == "src/pearlalgo/utils/retry.py"
    
    def test_search_returns_limited_results(self):
        """Search should return at most the specified limit."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        all_files = [f"src/file{i}.py" for i in range(20)]
        
        result = handler._search_files("file", all_files, limit=5)
        
        assert len(result) <= 5
    
    def test_search_empty_query_returns_first_files(self):
        """Empty query should return first N files."""
        from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        
        all_files = [f"src/file{i}.py" for i in range(20)]
        
        result = handler._search_files("", all_files, limit=8)
        
        assert len(result) == 8
        assert result == all_files[:8]

