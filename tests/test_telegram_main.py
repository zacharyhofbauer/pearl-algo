"""Tests for pearlalgo.telegram.main (_register_handlers, _handle_help, _handle_callback)."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock, call

import pytest

from tests.telegram_test_helpers import _make_update_and_context


# ---------------------------------------------------------------------------
# _register_handlers
# ---------------------------------------------------------------------------

def test_register_handlers_adds_all_commands():
    """Verify _register_handlers registers all expected command handlers."""
    from pearlalgo.telegram.main import _register_handlers

    app = MagicMock()
    app.add_handler = MagicMock()

    # CommandHandler and CallbackQueryHandler are imported inside the function,
    # so we patch them at the source module level.
    with patch("telegram.ext.CommandHandler") as MockCH, \
         patch("telegram.ext.CallbackQueryHandler") as MockCQH:
        MockCH.side_effect = lambda cmd, fn: (cmd, fn)
        MockCQH.side_effect = lambda fn: ("callback", fn)

        _register_handlers(app)

    # Check that add_handler was called for each command
    assert app.add_handler.call_count >= 12  # 11 commands + 1 callback query handler

    # Extract registered command names
    registered_cmds = set()
    for c in app.add_handler.call_args_list:
        handler = c[0][0]
        if isinstance(handler, tuple) and handler[0] != "callback":
            registered_cmds.add(handler[0])

    expected = {"start", "menu", "status", "stats", "trades", "performance",
                "health", "doctor", "signals", "settings", "help"}
    assert expected.issubset(registered_cmds)


# ---------------------------------------------------------------------------
# _handle_help
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_help():
    from pearlalgo.telegram.main import _handle_help

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    await _handle_help(update, context)

    update.message.reply_html.assert_called_once()
    msg = update.message.reply_html.call_args[0][0]
    assert "/status" in msg
    assert "/help" in msg
    assert "Commands" in msg


# ---------------------------------------------------------------------------
# _handle_callback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_callback_known_route():
    from pearlalgo.telegram.main import _handle_callback

    update, context = _make_update_and_context(has_callback_query=True)
    update.callback_query.data = "cmd:menu"
    update.callback_query.answer = AsyncMock()

    with patch("pearlalgo.telegram.handlers.status.handle_menu", new_callable=AsyncMock) as mock_menu:
        await _handle_callback(update, context)

    update.callback_query.answer.assert_called_once()
    mock_menu.assert_called_once_with(update, context)


@pytest.mark.asyncio
async def test_handle_callback_unknown_route():
    from pearlalgo.telegram.main import _handle_callback

    update, context = _make_update_and_context(has_callback_query=True)
    update.callback_query.data = "cmd:nonexistent"
    update.callback_query.answer = AsyncMock()

    # Should not raise, just log a warning
    await _handle_callback(update, context)

    update.callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_handle_callback_no_query():
    from pearlalgo.telegram.main import _handle_callback

    update, context = _make_update_and_context()
    update.callback_query = None

    # Should return early without error
    await _handle_callback(update, context)


@pytest.mark.asyncio
async def test_handle_callback_empty_data():
    from pearlalgo.telegram.main import _handle_callback

    update, context = _make_update_and_context(has_callback_query=True)
    update.callback_query.data = ""
    update.callback_query.answer = AsyncMock()

    # Empty data => early return (falsy string)
    await _handle_callback(update, context)
