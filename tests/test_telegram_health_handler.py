"""Tests for pearlalgo.telegram.handlers.health (handle_health)."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from tests.telegram_test_helpers import _FakeResp, _make_update_and_context, make_mock_session


@pytest.mark.asyncio
async def test_handle_health_success():
    from pearlalgo.telegram.handlers.health import handle_health

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    state_data = {"agent_state": "running", "connectivity": {"ibkr": True}}
    resp = _FakeResp(200, state_data)
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.health.format_health_message", return_value="<b>Health OK</b>") as fmt, \
         patch("pearlalgo.telegram.handlers.health.back_to_menu_keyboard", return_value=None), \
         patch("pearlalgo.telegram.handlers.health._reply", new_callable=AsyncMock) as mock_reply:
        await handle_health(update, context)

    mock_reply.assert_called_once()
    assert mock_reply.call_args[0][1] == "<b>Health OK</b>"
    fmt.assert_called_once_with(state_data)


@pytest.mark.asyncio
async def test_handle_health_api_error():
    from pearlalgo.telegram.handlers.health import handle_health

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    resp = _FakeResp(502, text="Bad Gateway")
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.health.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.health._reply", new_callable=AsyncMock) as mock_reply:
        await handle_health(update, context)

    mock_reply.assert_called_once()
    fmt_err.assert_called_once()
    assert "502" in fmt_err.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_health_connection_error():
    from pearlalgo.telegram.handlers.health import handle_health

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    with patch("aiohttp.ClientSession", side_effect=Exception("Timeout")), \
         patch("pearlalgo.telegram.handlers.health.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.health._reply", new_callable=AsyncMock) as mock_reply:
        await handle_health(update, context)

    mock_reply.assert_called_once()
    assert "Unable to reach agent" in fmt_err.call_args[0][0]
