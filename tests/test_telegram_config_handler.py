"""Tests for pearlalgo.telegram.handlers.config (handle_settings)."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from tests.telegram_test_helpers import _FakeResp, _make_update_and_context, make_mock_session


@pytest.mark.asyncio
async def test_handle_settings_success():
    from pearlalgo.telegram.handlers.config import handle_settings

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    state_data = {
        "symbol": "MNQ",
        "timeframe": "1m",
        "agent_state": "running",
        "config": {
            "execution": {
                "adapter": "tradovate",
                "enabled": True,
                "armed": True,
                "mode": "paper",
            },
            "strategy": {
                "enabled_signals": ["pearl_bot_auto"],
            },
            "min_confidence": 0.7,
        },
    }
    resp = _FakeResp(200, state_data)
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.config.back_to_menu_keyboard", return_value=None), \
         patch("pearlalgo.telegram.handlers.config._reply", new_callable=AsyncMock) as mock_reply:
        await handle_settings(update, context)

    mock_reply.assert_called_once()
    msg = mock_reply.call_args[0][1]
    assert "Agent Configuration" in msg
    assert "MNQ" in msg
    assert "tradovate" in msg


@pytest.mark.asyncio
async def test_handle_settings_api_error():
    from pearlalgo.telegram.handlers.config import handle_settings

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    resp = _FakeResp(503)
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.config.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.config._reply", new_callable=AsyncMock) as mock_reply:
        await handle_settings(update, context)

    mock_reply.assert_called_once()
    fmt_err.assert_called_once()


@pytest.mark.asyncio
async def test_handle_settings_connection_error():
    from pearlalgo.telegram.handlers.config import handle_settings

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    with patch("aiohttp.ClientSession", side_effect=Exception("Connection refused")), \
         patch("pearlalgo.telegram.handlers.config.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.config._reply", new_callable=AsyncMock) as mock_reply:
        await handle_settings(update, context)

    mock_reply.assert_called_once()
    assert "Unable to fetch config" in fmt_err.call_args[0][0]
