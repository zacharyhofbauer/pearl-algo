"""
Tests for Telegram bot handlers (start/stop/flatten) with mocked agent API.

Handlers call the agent API over HTTP; we mock aiohttp to avoid real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.telegram.handlers import trading as trading_handlers


def _make_update_and_context(has_callback_query: bool = False):
    """Build minimal update and context for handler tests."""
    update = MagicMock()
    update.callback_query = MagicMock() if has_callback_query else None
    update.message = None if has_callback_query else MagicMock()
    update.effective_chat = MagicMock()

    context = MagicMock()
    context.bot_data = {"api_url": "http://localhost:8001", "api_key": "test-key"}
    return update, context


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


@pytest.mark.asyncio
async def test_handle_start_agent_success():
    """Start agent: API returns 200 -> user sees success message."""
    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    resp = _FakeResp(200, {"detail": "Agent started"})
    session = MagicMock()
    session.post = MagicMock(return_value=_AsyncCtx(resp))

    async def session_aenter():
        return session

    async def session_aexit(*args):
        pass

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=session_cm), patch(
        "aiohttp.ClientTimeout", return_value=None
    ):
        await trading_handlers.handle_start_agent(update, context)

    update.message.reply_html.assert_called_once()
    text = update.message.reply_html.call_args.kwargs.get("text", "") or (
        update.message.reply_html.call_args[0][0] if update.message.reply_html.call_args[0] else ""
    )
    assert "start" in text.lower()
    assert "Agent started" in text or "✅" in text


@pytest.mark.asyncio
async def test_handle_stop_agent_success():
    """Stop agent: API returns 200 -> success message."""
    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    resp = _FakeResp(200, {"message": "Stopped"})
    session = MagicMock()
    session.post = MagicMock(return_value=_AsyncCtx(resp))
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=session_cm), patch(
        "aiohttp.ClientTimeout", return_value=None
    ):
        await trading_handlers.handle_stop_agent(update, context)

    update.message.reply_html.assert_called_once()
    text = update.message.reply_html.call_args.kwargs.get("text", "") or (
        update.message.reply_html.call_args[0][0] if update.message.reply_html.call_args[0] else ""
    )
    assert "stop" in text.lower()


@pytest.mark.asyncio
async def test_handle_flatten_api_error():
    """Flatten: API returns 500 -> user sees error message."""
    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    resp = _FakeResp(500, text="Internal Server Error")
    session = MagicMock()
    session.post = MagicMock(return_value=_AsyncCtx(resp))
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=session_cm), patch(
        "aiohttp.ClientTimeout", return_value=None
    ):
        await trading_handlers.handle_flatten(update, context)

    update.message.reply_html.assert_called_once()
    text = update.message.reply_html.call_args.kwargs.get("text", "") or (
        update.message.reply_html.call_args[0][0] if update.message.reply_html.call_args[0] else ""
    )
    assert "500" in text or "Error" in text or "❌" in text


@pytest.mark.asyncio
async def test_handle_kill_switch_confirm_shows_confirmation():
    """Kill switch confirm shows confirmation message and keyboard."""
    update, context = _make_update_and_context(has_callback_query=False)
    update.message = MagicMock()
    update.message.reply_html = AsyncMock()

    await trading_handlers.handle_kill_switch_confirm(update, context)

    update.message.reply_html.assert_called()
    call = update.message.reply_html.call_args
    text = call.kwargs.get("text", call[0][0] if call[0] else "")
    assert "Kill Switch" in text
    assert "Are you sure" in text
    assert call.kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_handle_flatten_confirm_shows_confirmation():
    """Flatten confirm shows confirmation and keyboard."""
    update, context = _make_update_and_context(has_callback_query=False)
    update.message = MagicMock()
    update.message.reply_html = AsyncMock()

    await trading_handlers.handle_flatten_confirm(update, context)

    update.message.reply_html.assert_called()
    call = update.message.reply_html.call_args
    text = call.kwargs.get("text", call[0][0] if call[0] else "")
    assert "Flatten" in text
    assert "Are you sure" in text
