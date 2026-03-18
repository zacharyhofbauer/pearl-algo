"""Tests for pearlalgo.telegram.handlers.status (handle_status, handle_menu)."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from tests.telegram_test_helpers import _FakeResp, _make_update_and_context, make_mock_session


# ---------------------------------------------------------------------------
# handle_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_status_success():
    from pearlalgo.telegram.handlers.status import handle_status

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    state_data = {"agent_state": "running", "balance": 50000, "positions": []}
    resp = _FakeResp(200, state_data)
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.status.format_status_message", return_value="<b>Status</b>") as fmt, \
         patch("pearlalgo.telegram.handlers.status.back_to_menu_keyboard", return_value=None), \
         patch("pearlalgo.telegram.handlers.status._reply", new_callable=AsyncMock) as mock_reply:
        await handle_status(update, context)

    mock_reply.assert_called_once()
    assert mock_reply.call_args[0][1] == "<b>Status</b>"
    fmt.assert_called_once_with(state_data)


@pytest.mark.asyncio
async def test_handle_status_api_error():
    from pearlalgo.telegram.handlers.status import handle_status

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    resp = _FakeResp(500, text="error")
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.status.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.status._reply", new_callable=AsyncMock) as mock_reply:
        await handle_status(update, context)

    mock_reply.assert_called_once()
    fmt_err.assert_called_once()
    assert "500" in fmt_err.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_status_connection_error():
    from pearlalgo.telegram.handlers.status import handle_status

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    with patch("aiohttp.ClientSession", side_effect=Exception("Connection reset")), \
         patch("pearlalgo.telegram.handlers.status.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.status._reply", new_callable=AsyncMock) as mock_reply:
        await handle_status(update, context)

    mock_reply.assert_called_once()
    assert "Unable to reach agent" in fmt_err.call_args[0][0]


# ---------------------------------------------------------------------------
# handle_menu
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_menu_success():
    from pearlalgo.telegram.handlers.status import handle_menu

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    with patch("pearlalgo.telegram.handlers.status.main_menu_keyboard", return_value=None), \
         patch("pearlalgo.telegram.handlers.status._reply", new_callable=AsyncMock) as mock_reply:
        await handle_menu(update, context)

    mock_reply.assert_called_once()
    msg = mock_reply.call_args[0][1]
    assert "PearlAlgo" in msg
    assert "Status" in msg


@pytest.mark.asyncio
async def test_handle_menu_via_callback_query():
    from pearlalgo.telegram.handlers.status import handle_menu

    update, context = _make_update_and_context(has_callback_query=True)
    update.callback_query.edit_message_text = AsyncMock()

    with patch("pearlalgo.telegram.handlers.status.main_menu_keyboard", return_value=None), \
         patch("pearlalgo.telegram.handlers.status._reply", new_callable=AsyncMock) as mock_reply:
        await handle_menu(update, context)

    mock_reply.assert_called_once()
