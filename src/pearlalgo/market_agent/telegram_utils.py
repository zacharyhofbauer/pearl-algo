"""
Telegram Markdown Utilities

Static utilities for Telegram message formatting and markdown escaping.
Extracted from telegram_command_handler.py to reduce file size and
improve maintainability.

For callback data helpers, see: pearlalgo.utils.telegram_ui_contract
"""

from __future__ import annotations

import re


# Custom PEARL emoji ID (created via @PEARLalgobot sticker pack)
PEARL_EMOJI_ID = "5177134388684523561"


def escape_markdown(text: str) -> str:
    """
    Escape characters that have special meaning in Telegram Markdown (v1).

    Escapes: _ * ` [
    For Markdown mode (not MarkdownV2), primarily _ and * matter.

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for Markdown parsing
    """
    if not text:
        return ""
    result = str(text)
    result = result.replace("_", "\\_")
    result = result.replace("*", "\\*")
    result = result.replace("`", "\\`")
    result = result.replace("[", "\\[")
    return result


def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2.

    This is more comprehensive than escape_markdown() as MarkdownV2
    has more special characters that need escaping.

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for MarkdownV2 parsing
    """
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    result = ""
    for char in text:
        if char in escape_chars:
            result += f"\\{char}"
        else:
            result += char
    return result


def safe_label(text: str) -> str:
    """
    Make a dynamic string safe for Telegram Markdown labels.

    Replaces underscores with spaces (more readable than escaping).

    Args:
        text: Text to make safe

    Returns:
        Safe text with underscores replaced by spaces
    """
    if not text:
        return ""
    return str(text).replace("_", " ")


def convert_to_markdown_v2_with_pearl(text: str) -> str:
    """
    Convert Markdown text to MarkdownV2 with custom PEARL emoji header.

    Handles:
    - Custom emoji syntax ![...](tg://emoji?id=...)
    - Markdown links [text](url)
    - Special character escaping

    Args:
        text: Markdown text to convert

    Returns:
        MarkdownV2-compatible text
    """
    # Custom PEARL emoji header
    pearl_header = f"![🐚](tg://emoji?id={PEARL_EMOJI_ID}) *PEARL*"

    # Replace the shell emoji PEARL header with custom emoji version
    text = re.sub(r'🐚 \*PEARL\*', pearl_header, text)

    # Escape special characters for MarkdownV2, preserving * and ` formatting
    escape_chars = r'_[]()~>#+-=|{}.!'

    result = []
    i = 0
    while i < len(text):
        char = text[i]

        # Skip already-escaped chars
        if char == '\\' and i + 1 < len(text):
            result.append(char)
            result.append(text[i + 1])
            i += 2
            continue

        # Don't escape inside the emoji syntax ![...](tg://emoji?id=...)
        if text[i:i+2] == '![':
            end = text.find(')', i)
            if end != -1:
                result.append(text[i:end+1])
                i = end + 1
                continue

        # Don't escape inside markdown links [text](url)
        if char == '[' and text[i:i+2] != '![':
            # Find matching ] and then (url)
            bracket_end = text.find(']', i)
            if bracket_end != -1 and bracket_end + 1 < len(text) and text[bracket_end + 1] == '(':
                paren_end = text.find(')', bracket_end + 1)
                if paren_end != -1:
                    result.append(text[i:paren_end+1])
                    i = paren_end + 1
                    continue

        # Escape special chars
        if char in escape_chars:
            result.append(f"\\{char}")
        else:
            result.append(char)
        i += 1

    return "".join(result)
