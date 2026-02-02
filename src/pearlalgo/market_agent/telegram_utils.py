"""
Telegram Markdown Utilities

Re-exports from pearlalgo.utils.telegram_markdown for backwards compatibility.
The actual implementations are in utils/ to maintain proper architecture boundaries.

For callback data helpers, see: pearlalgo.utils.telegram_ui_contract
"""

from __future__ import annotations

# Re-export all utilities from utils layer for backwards compatibility
from pearlalgo.utils.telegram_markdown import (
    PEARL_EMOJI_ID,
    escape_markdown,
    escape_markdown_v2,
    safe_label,
    convert_to_markdown_v2_with_pearl,
)

__all__ = [
    "PEARL_EMOJI_ID",
    "escape_markdown",
    "escape_markdown_v2",
    "safe_label",
    "convert_to_markdown_v2_with_pearl",
]
