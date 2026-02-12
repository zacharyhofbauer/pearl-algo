"""
Inline keyboard builders for Telegram bot responses.
"""

from __future__ import annotations

from typing import Optional

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    InlineKeyboardButton = None  # type: ignore
    InlineKeyboardMarkup = None  # type: ignore


def main_menu_keyboard(agent_state: str = "unknown") -> Optional["InlineKeyboardMarkup"]:
    """Build the main menu inline keyboard."""
    if not TELEGRAM_AVAILABLE:
        return None

    is_running = agent_state == "running"

    row1 = [
        InlineKeyboardButton("📊 Status", callback_data="cmd:status"),
        InlineKeyboardButton("📈 Trades", callback_data="cmd:trades"),
    ]

    row2 = []
    if is_running:
        row2.append(InlineKeyboardButton("⏹️ Stop", callback_data="cmd:stop"))
    else:
        row2.append(InlineKeyboardButton("▶️ Start", callback_data="cmd:start"))
    row2.append(InlineKeyboardButton("⚙️ Settings", callback_data="cmd:settings"))

    row3 = [
        InlineKeyboardButton("🚨 Kill Switch", callback_data="cmd:kill_switch"),
        InlineKeyboardButton("📋 Flatten All", callback_data="cmd:flatten"),
    ]

    return InlineKeyboardMarkup([row1, row2, row3])


def confirm_keyboard(action: str) -> Optional["InlineKeyboardMarkup"]:
    """Build a confirmation keyboard for dangerous actions."""
    if not TELEGRAM_AVAILABLE:
        return None

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"confirm:{action}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cmd:menu"),
        ]
    ])


def back_to_menu_keyboard() -> Optional["InlineKeyboardMarkup"]:
    """Build a 'back to menu' keyboard."""
    if not TELEGRAM_AVAILABLE:
        return None

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Menu", callback_data="cmd:menu")]
    ])
