"""Tests for pearlalgo.telegram.handlers.analytics (handle_trades, handle_performance)."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from tests.telegram_test_helpers import _FakeResp, _AsyncCtx, _make_update_and_context, make_mock_session


# ---------------------------------------------------------------------------
# handle_trades
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_trades_success():
    from pearlalgo.telegram.handlers.analytics import handle_trades

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    trades_data = [{"symbol": "MNQ", "pnl": 50.0}, {"symbol": "MNQ", "pnl": -20.0}]
    resp = _FakeResp(200, trades_data)
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.analytics.format_trades_message", return_value="<b>Trades</b>") as fmt, \
         patch("pearlalgo.telegram.handlers.analytics.back_to_menu_keyboard", return_value=None), \
         patch("pearlalgo.telegram.handlers.analytics._reply", new_callable=AsyncMock) as mock_reply:
        await handle_trades(update, context)

    mock_reply.assert_called_once()
    call_args = mock_reply.call_args
    assert call_args[0][1] == "<b>Trades</b>"


@pytest.mark.asyncio
async def test_handle_trades_api_error():
    from pearlalgo.telegram.handlers.analytics import handle_trades

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    resp = _FakeResp(500, text="Internal Server Error")
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.analytics.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.analytics._reply", new_callable=AsyncMock) as mock_reply:
        await handle_trades(update, context)

    mock_reply.assert_called_once()
    fmt_err.assert_called_once()


@pytest.mark.asyncio
async def test_handle_trades_connection_error():
    from pearlalgo.telegram.handlers.analytics import handle_trades

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    with patch("aiohttp.ClientSession", side_effect=Exception("Connection refused")), \
         patch("pearlalgo.telegram.handlers.analytics.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.analytics._reply", new_callable=AsyncMock) as mock_reply:
        await handle_trades(update, context)

    mock_reply.assert_called_once()
    assert "Unable to fetch trades" in fmt_err.call_args[0][0]


# ---------------------------------------------------------------------------
# handle_performance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_performance_success():
    from pearlalgo.telegram.handlers.analytics import handle_performance

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    perf_data = {
        "total_pnl": 150.0,
        "wins": 8,
        "losses": 2,
        "avg_pnl": 15.0,
        "exited_signals": 10,
        "by_signal_type": {},
    }
    resp = _FakeResp(200, perf_data)
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.analytics.back_to_menu_keyboard", return_value=None), \
         patch("pearlalgo.telegram.handlers.analytics._reply", new_callable=AsyncMock) as mock_reply:
        await handle_performance(update, context)

    mock_reply.assert_called_once()
    msg = mock_reply.call_args[0][1]
    assert "Performance Summary" in msg


@pytest.mark.asyncio
async def test_handle_performance_api_error():
    from pearlalgo.telegram.handlers.analytics import handle_performance

    update, context = _make_update_and_context()
    update.message.reply_html = AsyncMock()

    resp = _FakeResp(500)
    session_cm = make_mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session_cm), \
         patch("aiohttp.ClientTimeout", return_value=None), \
         patch("pearlalgo.telegram.handlers.analytics.format_error_message", return_value="Error") as fmt_err, \
         patch("pearlalgo.telegram.handlers.analytics._reply", new_callable=AsyncMock) as mock_reply:
        await handle_performance(update, context)

    mock_reply.assert_called_once()
    fmt_err.assert_called_once()
