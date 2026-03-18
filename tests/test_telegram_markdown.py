"""Tests for pearlalgo.utils.telegram_markdown — pure functions, no mocking."""

from __future__ import annotations

import pytest

from pearlalgo.utils.telegram_markdown import (
    PEARL_EMOJI_ID,
    escape_markdown,
    escape_markdown_v2,
    safe_label,
    convert_to_markdown_v2_with_pearl,
)


class TestEscapeMarkdown:
    def test_empty(self):
        assert escape_markdown("") == ""

    def test_none_ish(self):
        # empty string
        assert escape_markdown("") == ""

    def test_underscores(self):
        assert escape_markdown("foo_bar") == "foo\\_bar"

    def test_asterisks(self):
        assert escape_markdown("*bold*") == "\\*bold\\*"

    def test_backticks(self):
        assert escape_markdown("`code`") == "\\`code\\`"

    def test_brackets(self):
        assert escape_markdown("[link]") == "\\[link]"

    def test_normal_text(self):
        assert escape_markdown("Hello world") == "Hello world"


class TestEscapeMarkdownV2:
    def test_empty(self):
        assert escape_markdown_v2("") == ""

    def test_special_chars(self):
        result = escape_markdown_v2("a_b*c[d]e(f)")
        assert "\\_" in result
        assert "\\*" in result
        assert "\\[" in result
        assert "\\]" in result
        assert "\\(" in result
        assert "\\)" in result

    def test_normal_text(self):
        assert escape_markdown_v2("Hello") == "Hello"

    def test_dot_and_exclamation(self):
        result = escape_markdown_v2("Hello! World.")
        assert "\\!" in result
        assert "\\." in result


class TestSafeLabel:
    def test_empty(self):
        assert safe_label("") == ""

    def test_underscores_replaced(self):
        assert safe_label("foo_bar_baz") == "foo bar baz"

    def test_no_underscores(self):
        assert safe_label("hello world") == "hello world"


class TestConvertToMarkdownV2WithPearl:
    def test_pearl_header_replacement(self):
        text = "🐚 *PEARL* Dashboard"
        result = convert_to_markdown_v2_with_pearl(text)
        assert PEARL_EMOJI_ID in result
        assert "*PEARL*" in result

    def test_preserves_escaped_chars(self):
        text = "\\_ already escaped"
        result = convert_to_markdown_v2_with_pearl(text)
        assert "\\_ already escaped" in result

    def test_preserves_emoji_syntax(self):
        text = f"![emoji](tg://emoji?id=12345) hello"
        result = convert_to_markdown_v2_with_pearl(text)
        assert "![emoji](tg://emoji?id=12345)" in result

    def test_preserves_markdown_links(self):
        text = "[Click here](https://example.com) text"
        result = convert_to_markdown_v2_with_pearl(text)
        assert "[Click here](https://example.com)" in result

    def test_escapes_special_chars(self):
        text = "Hello! World."
        result = convert_to_markdown_v2_with_pearl(text)
        assert "\\!" in result
        assert "\\." in result

    def test_plain_text(self):
        result = convert_to_markdown_v2_with_pearl("Hello world")
        assert result == "Hello world"
