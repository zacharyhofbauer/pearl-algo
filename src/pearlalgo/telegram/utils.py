"""
Telegram utilities: auth check, safe message sending, retry logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Telegram max message length
MAX_MESSAGE_LENGTH = 4096


def check_authorized(chat_id: int, authorized_chat_id: int | str) -> bool:
    """Return True if the chat_id matches the authorized one."""
    try:
        return int(chat_id) == int(authorized_chat_id)
    except (ValueError, TypeError):
        return False


def split_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a message into chunks that fit within Telegram's character limit.

    Prefers splitting at newline boundaries to avoid breaking mid-line.
    """
    if len(text) <= max_len:
        return [text]

    parts: list[str] = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break

        # Try to split at a newline within the allowed length
        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:
            # No good newline found, hard split
            split_at = max_len

        parts.append(text[:split_at])
        text = text[split_at:]

    return parts


def escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def safe_send(
    send_fn,
    text: str,
    parse_mode: str = "HTML",
    max_retries: int = 3,
    **kwargs,
) -> Optional[object]:
    """Send a Telegram message with retry logic and message splitting.

    Handles:
    - Messages exceeding 4096 chars (splits automatically)
    - Rate limit errors (429) with exponential backoff
    - Network errors with retry
    - MessageNotModified errors (silently ignored)
    """
    parts = split_message(text)
    last_msg = None

    for part in parts:
        for attempt in range(max_retries):
            try:
                last_msg = await send_fn(
                    text=part,
                    parse_mode=parse_mode,
                    **kwargs,
                )
                break  # Success
            except Exception as e:
                error_str = str(e).lower()

                # Silently ignore "message not modified" (user clicks same button twice)
                if "message is not modified" in error_str:
                    break

                # Rate limited: wait and retry
                if "429" in error_str or "retry after" in error_str:
                    wait = min(2 ** attempt * 2, 30)
                    logger.warning(f"Telegram rate limited, waiting {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                    continue

                # Network error: retry with backoff
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"Telegram send error: {e}, retrying in {wait}s")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"Telegram send failed after {max_retries} attempts: {e}")

    return last_msg
