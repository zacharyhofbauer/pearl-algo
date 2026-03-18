"""Tests for pearlalgo.telegram.handlers.doctor (handle_doctor)."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from tests.telegram_test_helpers import _FakeResp, _make_update_and_context, make_mock_session


@pytest.mark.asyncio
async def test_handle_doctor_success():
    from pearlalgo.telegram.handlers.doctor import handle_doctor

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    state_data = {"agent_state": "running", "risk": {"drawdown": 0.02}}
    resp = _FakeResp(200, state_data)
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.doctor.format_doctor_message", return_value="<b>Doctor</b>") as fmt, \
         patch("pearlalgo.telegram.handlers.doctor.back_to_menu_keyboard", return_value=None), \
         patch("pearlalgo.telegram.handlers.doctor._reply", new_callable=AsyncMock) as mock_reply:
        await handle_doctor(update, context)

    mock_reply.assert_called_once()
    assert mock_reply.call_args[0][1] == "<b>Doctor</b>"
    fmt.assert_called_once_with(state_data)


@pytest.mark.asyncio
async def test_handle_doctor_api_error():
    from pearlalgo.telegram.handlers.doctor import handle_doctor

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    resp = _FakeResp(500, text="server error")
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.doctor.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.doctor._reply", new_callable=AsyncMock) as mock_reply:
        await handle_doctor(update, context)

    mock_reply.assert_called_once()
    fmt_err.assert_called_once()
    assert "500" in fmt_err.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_doctor_connection_error():
    from pearlalgo.telegram.handlers.doctor import handle_doctor

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    with patch("aiohttp.ClientSession", side_effect=Exception("Connection refused")), \
         patch("pearlalgo.telegram.handlers.doctor.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.doctor._reply", new_callable=AsyncMock) as mock_reply:
        await handle_doctor(update, context)

    mock_reply.assert_called_once()
    assert "Unable to reach agent" in fmt_err.call_args[0][0]
