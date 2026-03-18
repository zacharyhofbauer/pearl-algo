"""Shared test helpers for Telegram handler tests.

Extracted from test_telegram_handlers.py for reuse across handler test files.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


class _FakeResp:
    """Minimal response object for aiohttp mock."""

    def __init__(self, status: int, json_data: dict | None = None, text: str = ""):
        self.status = status
        self._json_data = json_data or {}
        self._text = text

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text


class _AsyncCtx:
    """Async context manager that yields a value."""

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        pass


def _make_update_and_context(has_callback_query: bool = False):
    """Build minimal update and context for handler tests."""
    update = MagicMock()
    update.callback_query = MagicMock() if has_callback_query else None
    update.message = None if has_callback_query else MagicMock()
    update.effective_chat = MagicMock()

    context = MagicMock()
    context.bot_data = {"api_url": "http://localhost:8001", "api_key": "test-key"}
    return update, context


def make_mock_session(resp: _FakeResp, method: str = "get"):
    """Create a mocked aiohttp.ClientSession with a given response."""
    session = MagicMock()
    mock_method = MagicMock(return_value=_AsyncCtx(resp))
    setattr(session, method, mock_method)
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)
    return session_cm
