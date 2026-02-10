"""
Telegram Message Builder.

Handles the message lifecycle for Telegram notifications:
- Markdown escaping (v1 and MarkdownV2)
- Message truncation (respecting Telegram's 4096-char limit)
- Splitting long messages at logical boundaries
- Assembling and sending composed messages

This module centralises all the text-manipulation logic that was previously
scattered across ``telegram_notifier.py`` and ``telegram_alerts.py``, making
it easier to test and reuse.

Architecture Note:
------------------
``TelegramMessageBuilder`` is designed to be *instantiated* (optionally with a
``TelegramAlerts`` instance for sending) or used via its ``@staticmethod`` /
``@classmethod`` helpers for pure text manipulation.
"""

from __future__ import annotations

import re
from typing import List, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger

# Re-export the canonical constants so callers don't need a second import.
from pearlalgo.utils.telegram_markdown import (
    PEARL_EMOJI_ID,
    escape_markdown,
    escape_markdown_v2,
    safe_label,
    convert_to_markdown_v2_with_pearl,
)

if TYPE_CHECKING:
    from pearlalgo.utils.telegram_alerts import TelegramAlerts

# ---------------------------------------------------------------------------
# Telegram hard limits
# ---------------------------------------------------------------------------
TELEGRAM_MESSAGE_LIMIT = 4096
"""Maximum characters for a single Telegram text message."""

TELEGRAM_CAPTION_LIMIT = 1024
"""Maximum characters for a photo/document caption."""

_TRUNCATION_SUFFIX = "\n\n…(truncated)"
"""Suffix appended when a message is truncated to fit the limit."""

_SPLIT_OVERHEAD = 40
"""Reserved characters per chunk for ``[1/N]`` headers when splitting."""


class TelegramMessageBuilder:
    """Handles escaping, truncation, splitting, and sending of Telegram messages.

    Typical usage::

        builder = TelegramMessageBuilder(telegram=my_alerts_instance)

        # Pure text helpers (no network)
        safe = builder.escape_markdown("price_change_pct")
        short = builder.truncate_message(very_long_text)
        parts = builder.split_long_message(very_long_text)

        # Assemble + send
        await builder.build_and_send("Hello *world*!")

    All static/class methods can also be used without instantiation::

        safe = TelegramMessageBuilder.escape_markdown("hello_world")
    """

    def __init__(
        self,
        telegram: Optional["TelegramAlerts"] = None,
        *,
        default_parse_mode: str = "Markdown",
    ) -> None:
        """Initialise the builder.

        Args:
            telegram: Optional ``TelegramAlerts`` instance used by
                      :meth:`build_and_send`.  If *None*, sending is
                      disabled and only text-manipulation helpers work.
            default_parse_mode: Parse mode to use when sending
                                (``'Markdown'`` or ``'MarkdownV2'``).
        """
        self.telegram = telegram
        self.default_parse_mode = default_parse_mode

    # ------------------------------------------------------------------
    # Escaping
    # ------------------------------------------------------------------

    @staticmethod
    def escape_markdown(text: str) -> str:
        """Escape special characters for Telegram's legacy Markdown (v1).

        Escapes: ``_``, ``*``, `` ` ``, ``[``

        Args:
            text: Raw text.

        Returns:
            Escaped text safe for ``parse_mode='Markdown'``.
        """
        return escape_markdown(text)

    @staticmethod
    def escape_markdown_v2(text: str) -> str:
        """Escape special characters for Telegram MarkdownV2.

        MarkdownV2 requires escaping of many more characters than v1:
        ``_ * [ ] ( ) ~ ` > # + - = | { } . !``

        Args:
            text: Raw text.

        Returns:
            Escaped text safe for ``parse_mode='MarkdownV2'``.
        """
        return escape_markdown_v2(text)

    @staticmethod
    def safe_label(text: str) -> str:
        """Make a dynamic string safe for Telegram Markdown labels.

        Replaces underscores with spaces (more readable than escaping).

        Args:
            text: Raw label text.

        Returns:
            Sanitised label string.
        """
        return safe_label(text)

    @classmethod
    def convert_to_markdown_v2_with_pearl(cls, text: str) -> str:
        """Convert legacy-Markdown text to MarkdownV2 with PEARL emoji header.

        Handles:
        - Custom emoji syntax ``![...](tg://emoji?id=...)``
        - Markdown links ``[text](url)``
        - Special character escaping while preserving ``*bold*`` and
          `` `code` `` formatting.

        Args:
            text: Legacy Markdown text.

        Returns:
            MarkdownV2-compatible text with PEARL branding.
        """
        return convert_to_markdown_v2_with_pearl(text)

    @staticmethod
    def sanitize_markdown(text: str) -> str:
        """Sanitize a message for Telegram's legacy Markdown parse mode.

        Escapes underscores inside identifiers (``foo_bar``) while
        preserving intentional ``*bold*``, ``_italic_``, and `` `code` ``
        formatting.

        Args:
            text: Message text.

        Returns:
            Sanitised text.
        """
        from pearlalgo.utils.telegram_alerts import sanitize_telegram_markdown

        return sanitize_telegram_markdown(text)

    # ------------------------------------------------------------------
    # Truncation
    # ------------------------------------------------------------------

    @staticmethod
    def truncate_message(
        text: str,
        *,
        limit: int = TELEGRAM_MESSAGE_LIMIT,
        suffix: str = _TRUNCATION_SUFFIX,
    ) -> str:
        """Truncate a message to fit within Telegram's character limit.

        If ``text`` already fits, it is returned unchanged.  Otherwise it
        is cut at ``limit - len(suffix)`` characters and ``suffix`` is
        appended so the total length equals *limit*.

        Args:
            text: Message text.
            limit: Maximum allowed length (default 4096).
            suffix: Truncation indicator appended at the end.

        Returns:
            Text guaranteed to be ``<= limit`` characters.
        """
        if not text or len(text) <= limit:
            return text
        keep = max(0, limit - len(suffix))
        return text[:keep] + suffix

    @classmethod
    def truncate_caption(cls, text: str) -> str:
        """Truncate text for use as a Telegram photo/document caption.

        Captions have a stricter 1024-character limit.

        Args:
            text: Caption text.

        Returns:
            Text guaranteed to be ``<= 1024`` characters.
        """
        return cls.truncate_message(text, limit=TELEGRAM_CAPTION_LIMIT)

    # ------------------------------------------------------------------
    # Splitting
    # ------------------------------------------------------------------

    @staticmethod
    def split_long_message(
        text: str,
        *,
        limit: int = TELEGRAM_MESSAGE_LIMIT,
        add_part_headers: bool = True,
    ) -> List[str]:
        """Split a long message into multiple chunks that each fit Telegram's limit.

        Splitting is performed at *logical boundaries* (double-newlines
        first, then single newlines) so that formatted blocks stay intact
        whenever possible.

        If ``add_part_headers`` is *True*, each chunk is prefixed with a
        ``[1/N]`` indicator (the overhead is accounted for automatically).

        Args:
            text: Full message text.
            limit: Per-chunk character limit (default 4096).
            add_part_headers: Whether to prepend ``[n/N]`` headers.

        Returns:
            List of message chunks, each ``<= limit`` characters.
            If the input is empty, returns ``['']``.
        """
        if not text:
            return [""]

        effective_limit = limit - _SPLIT_OVERHEAD if add_part_headers else limit
        # Ensure we always have a meaningful budget.
        effective_limit = max(effective_limit, 200)

        if len(text) <= effective_limit:
            return [text]

        # ----- Phase 1: split on double-newlines (paragraph boundaries) -----
        paragraphs = text.split("\n\n")
        chunks: List[str] = []
        current_chunk = ""

        for para in paragraphs:
            candidate = f"{current_chunk}\n\n{para}" if current_chunk else para

            if len(candidate) <= effective_limit:
                current_chunk = candidate
            else:
                # Flush current chunk if non-empty.
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""

                # If this single paragraph exceeds the limit, sub-split on newlines.
                if len(para) > effective_limit:
                    sub_lines = para.split("\n")
                    for line in sub_lines:
                        sub_candidate = f"{current_chunk}\n{line}" if current_chunk else line
                        if len(sub_candidate) <= effective_limit:
                            current_chunk = sub_candidate
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            # If a *single line* is still over the limit, hard-cut it.
                            if len(line) > effective_limit:
                                while line:
                                    chunks.append(line[:effective_limit])
                                    line = line[effective_limit:]
                                current_chunk = ""
                            else:
                                current_chunk = line
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        # ----- Phase 2: add [n/N] headers -----
        if add_part_headers and len(chunks) > 1:
            total = len(chunks)
            chunks = [f"[{i + 1}/{total}]\n{chunk}" for i, chunk in enumerate(chunks)]

        return chunks if chunks else [""]

    # ------------------------------------------------------------------
    # Build & Send
    # ------------------------------------------------------------------

    async def build_and_send(
        self,
        text: str,
        *,
        parse_mode: Optional[str] = None,
        sanitize: bool = True,
        use_pearl_header: bool = False,
        reply_markup: object = None,
        dedupe: bool = True,
    ) -> bool:
        """Sanitise, truncate, and send a message via Telegram.

        If the message exceeds the Telegram limit it is automatically
        split into multiple chunks and each chunk is sent sequentially.

        Args:
            text: Raw message text.
            parse_mode: Override the default parse mode (``'Markdown'``
                        or ``'MarkdownV2'``).  ``None`` uses the
                        builder's ``default_parse_mode``.
            sanitize: If *True*, apply markdown sanitisation.
            use_pearl_header: If *True* and ``parse_mode`` is
                              ``'MarkdownV2'``, wrap the text with the
                              PEARL custom-emoji header.
            reply_markup: Optional inline keyboard markup (only attached
                          to the *last* chunk when splitting).
            dedupe: Whether to enable deduplication on the underlying
                    ``TelegramAlerts.send_message`` call.

        Returns:
            *True* if all chunks were sent successfully.
        """
        if not self.telegram:
            logger.warning("TelegramMessageBuilder.build_and_send called without a TelegramAlerts instance")
            return False

        pm = parse_mode or self.default_parse_mode

        # Step 1: sanitise
        if sanitize:
            if pm == "MarkdownV2":
                text = self.escape_markdown_v2(text)
            else:
                text = self.sanitize_markdown(text)

        # Step 2: optional PEARL header
        if use_pearl_header and pm == "MarkdownV2":
            text = self.convert_to_markdown_v2_with_pearl(text)

        # Step 3: split if necessary
        chunks = self.split_long_message(text, limit=TELEGRAM_MESSAGE_LIMIT)

        # Step 4: send
        all_ok = True
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            try:
                ok = await self.telegram.send_message(
                    chunk,
                    parse_mode=pm,
                    reply_markup=reply_markup if is_last else None,
                    dedupe=dedupe,
                )
                if not ok:
                    all_ok = False
            except Exception as exc:
                logger.warning(f"TelegramMessageBuilder: failed to send chunk {i + 1}/{len(chunks)}: {exc}")
                all_ok = False

                # Fallback: strip formatting and retry as plain text.
                try:
                    plain = self._strip_markdown(chunk)
                    await self.telegram.send_message(
                        plain,
                        parse_mode=None,
                        reply_markup=reply_markup if is_last else None,
                        dedupe=dedupe,
                    )
                except Exception as fallback_exc:
                    logger.warning(f"TelegramMessageBuilder: plain-text fallback also failed: {fallback_exc}")

        return all_ok

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove Markdown/MarkdownV2 formatting from text for plain-text fallback.

        This is a best-effort strip; it removes common formatting markers
        and the custom emoji syntax.

        Args:
            text: Markdown-formatted text.

        Returns:
            Plain text with formatting removed.
        """
        # Remove custom emoji syntax ![alt](tg://emoji?id=...)
        result = re.sub(r'!\[.*?\]\(.*?\)', '🐚', text)
        # Remove escape backslashes
        result = result.replace("\\", "")
        # Remove bold/italic/code markers
        result = result.replace("*", "").replace("_", "").replace("`", "")
        return result
