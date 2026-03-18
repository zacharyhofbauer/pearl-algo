"""Tests for pearlalgo.telegram.utils."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.telegram.utils import (
    check_authorized,
    split_message,
    escape_html,
    safe_send,
    reply_html,
    MAX_MESSAGE_LENGTH,
)


# ---------------------------------------------------------------------------
# check_authorized
# ---------------------------------------------------------------------------

class TestCheckAuthorized:
    def test_matching_int(self):
        assert check_authorized(12345, 12345) is True

    def test_matching_string(self):
        assert check_authorized(12345, "12345") is True

    def test_non_matching(self):
        assert check_authorized(12345, 99999) is False

    def test_string_chat_id(self):
        assert check_authorized(12345, "12345") is True

    def test_both_strings(self):
        # chat_id is typed as int, but coercion should still work
        assert check_authorized(100, "100") is True

    def test_invalid_authorized_id(self):
        assert check_authorized(12345, "not-a-number") is False

    def test_none_authorized_id(self):
        assert check_authorized(12345, None) is False

    def test_empty_string(self):
        assert check_authorized(12345, "") is False


# ---------------------------------------------------------------------------
# split_message
# ---------------------------------------------------------------------------

class TestSplitMessage:
    def test_short_message_no_split(self):
        msg = "Hello, world!"
        parts = split_message(msg)
        assert parts == [msg]

    def test_exact_limit(self):
        msg = "a" * MAX_MESSAGE_LENGTH
        parts = split_message(msg)
        assert parts == [msg]

    def test_long_message_splits_at_newline(self):
        # Build a message that exceeds MAX_MESSAGE_LENGTH with newlines
        line = "x" * 100 + "\n"
        msg = line * 50  # 50 * 101 = 5050 chars > 4096
        parts = split_message(msg)
        assert len(parts) >= 2
        # Each part should be <= MAX_MESSAGE_LENGTH
        for part in parts:
            assert len(part) <= MAX_MESSAGE_LENGTH

    def test_long_message_no_newlines_hard_split(self):
        msg = "a" * (MAX_MESSAGE_LENGTH + 500)
        parts = split_message(msg)
        assert len(parts) == 2
        assert len(parts[0]) == MAX_MESSAGE_LENGTH
        assert len(parts[1]) == 500

    def test_empty_message(self):
        parts = split_message("")
        assert parts == [""]

    def test_custom_max_len(self):
        msg = "abcdefghij"  # 10 chars
        parts = split_message(msg, max_len=5)
        assert len(parts) == 2
        assert parts[0] == "abcde"
        assert parts[1] == "fghij"


# ---------------------------------------------------------------------------
# escape_html
# ---------------------------------------------------------------------------

class TestEscapeHtml:
    def test_ampersand(self):
        assert escape_html("A & B") == "A &amp; B"

    def test_angle_brackets(self):
        assert escape_html("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"

    def test_normal_text(self):
        assert escape_html("Hello World 123") == "Hello World 123"

    def test_mixed(self):
        assert escape_html("x < y & z > w") == "x &lt; y &amp; z &gt; w"

    def test_empty(self):
        assert escape_html("") == ""

    def test_already_escaped_double_escapes(self):
        # Calling escape_html on already-escaped text should double-escape
        assert escape_html("&amp;") == "&amp;amp;"


# ---------------------------------------------------------------------------
# safe_send
# ---------------------------------------------------------------------------

class TestSafeSend:
    @pytest.mark.asyncio
    async def test_success(self):
        send_fn = AsyncMock(return_value="sent_msg")
        result = await safe_send(send_fn, "Hello")
        send_fn.assert_called_once_with(text="Hello", parse_mode="HTML")
        assert result == "sent_msg"

    @pytest.mark.asyncio
    async def test_success_no_parse_mode(self):
        send_fn = AsyncMock(return_value="sent_msg")
        result = await safe_send(send_fn, "Hello", use_parse_mode=False)
        send_fn.assert_called_once_with(text="Hello")

    @pytest.mark.asyncio
    async def test_rate_limit_retry(self):
        send_fn = AsyncMock(side_effect=[
            Exception("429 Too Many Requests"),
            "sent_msg",
        ])
        with patch("pearlalgo.telegram.utils.asyncio.sleep", new_callable=AsyncMock):
            result = await safe_send(send_fn, "Hello", max_retries=3)
        assert result == "sent_msg"
        assert send_fn.call_count == 2

    @pytest.mark.asyncio
    async def test_message_not_modified_ignored(self):
        send_fn = AsyncMock(side_effect=Exception("Message is not modified"))
        result = await safe_send(send_fn, "Hello")
        # Should not raise, returns None (last_msg stays None)
        assert result is None

    @pytest.mark.asyncio
    async def test_network_error_all_retries_exhausted(self):
        send_fn = AsyncMock(side_effect=Exception("Network error"))
        with patch("pearlalgo.telegram.utils.asyncio.sleep", new_callable=AsyncMock):
            result = await safe_send(send_fn, "Hello", max_retries=2)
        assert send_fn.call_count == 2
        assert result is None

    @pytest.mark.asyncio
    async def test_splits_long_message(self):
        send_fn = AsyncMock(return_value="ok")
        long_text = "a" * (MAX_MESSAGE_LENGTH + 100)
        await safe_send(send_fn, long_text)
        assert send_fn.call_count == 2


# ---------------------------------------------------------------------------
# reply_html
# ---------------------------------------------------------------------------

class TestReplyHtml:
    @pytest.mark.asyncio
    async def test_callback_query_path(self):
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.message = None

        await reply_html(update, "<b>Hello</b>")

        update.callback_query.edit_message_text.assert_called_once_with(
            text="<b>Hello</b>", parse_mode="HTML",
        )

    @pytest.mark.asyncio
    async def test_message_path(self):
        update = MagicMock()
        update.callback_query = None
        update.message = MagicMock()
        update.message.reply_html = AsyncMock(return_value="ok")

        with patch("pearlalgo.telegram.utils.safe_send", new_callable=AsyncMock) as mock_safe:
            await reply_html(update, "Hello")

        mock_safe.assert_called_once_with(
            update.message.reply_html, "Hello", use_parse_mode=False,
        )

    @pytest.mark.asyncio
    async def test_callback_query_not_modified_falls_back(self):
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=Exception("Bad Request: message is not modified")
        )
        update.effective_chat = MagicMock()
        update.effective_chat.send_message = AsyncMock()

        with patch("pearlalgo.telegram.utils.safe_send", new_callable=AsyncMock):
            await reply_html(update, "Hello")

        # Should NOT fall back since "message is not modified" is silenced
        # (the condition checks if NOT in error string => skip fallback)

    @pytest.mark.asyncio
    async def test_callback_query_other_error_falls_back(self):
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=Exception("Some other error")
        )
        update.effective_chat = MagicMock()
        update.effective_chat.send_message = AsyncMock()

        with patch("pearlalgo.telegram.utils.safe_send", new_callable=AsyncMock) as mock_safe:
            await reply_html(update, "Hello")

        # Falls back to safe_send via effective_chat.send_message
        mock_safe.assert_called_once_with(
            update.effective_chat.send_message, "Hello",
        )

    @pytest.mark.asyncio
    async def test_no_callback_no_message(self):
        update = MagicMock()
        update.callback_query = None
        update.message = None

        # Should not raise
        await reply_html(update, "Hello")
