"""
Tests for the /ai_patch Telegram command.

Tests cover:
- Authorization blocking for unauthorized chat IDs
- Missing API key error handling
- Unsafe path rejection
- Path blocking helper method
- OpenAI client error handling
"""

from __future__ import annotations

import tempfile
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        """Missing OPENAI_API_KEY should produce a clear error."""
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
            project_root = Path(tmpdir)
            src_dir = project_root / "src" / "pearlalgo" / "utils"
            src_dir.mkdir(parents=True)
            test_file = src_dir / "retry.py"
            test_file.write_text("def retry(): pass\n")

            with patch.object(handler, '_send_message_or_edit', side_effect=mock_send):
                with patch.object(Path, 'resolve', return_value=project_root):
                    with patch('pearlalgo.nq_agent.telegram_command_handler.OPENAI_AVAILABLE', True):
                        with patch('pearlalgo.nq_agent.telegram_command_handler.OpenAIClient') as mock_client:
                            from pearlalgo.utils.openai_client import OpenAIAPIKeyMissingError
                            mock_client.side_effect = OpenAIAPIKeyMissingError("OPENAI_API_KEY not set")
                            await TelegramCommandHandler._handle_ai_patch(handler, update, context)

        assert any("API Key" in msg or "OPENAI_API_KEY" in msg for msg in sent_messages)


# ---------------------------------------------------------------------------
# Test AI patch not available
# ---------------------------------------------------------------------------

class TestAIPatchNotAvailable:
    """Tests for /ai_patch when OpenAI is not installed."""

    @pytest.mark.asyncio
    async def test_ai_patch_reports_not_available(self):
        """When OpenAI is not installed, should show installation instructions."""
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
                with patch('pearlalgo.nq_agent.telegram_command_handler.OPENAI_AVAILABLE', False):
                    await TelegramCommandHandler._handle_ai_patch(handler, update, context)

        assert len(sent_messages) == 1
        assert "Not Available" in sent_messages[0] or "not installed" in sent_messages[0].lower()
        assert "pip install" in sent_messages[0]
