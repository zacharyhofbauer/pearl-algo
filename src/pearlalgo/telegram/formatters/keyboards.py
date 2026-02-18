"""
Inline keyboard builders for Telegram bot responses.

Layout mirrors the web app dashboard panels:
  Monitoring:  Status | Trades | Stats
  Diagnostics: Health | Doctor | Signals
  Controls:    Start/Stop | Settings
  Emergency:   Kill Switch | Flatten All
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
        InlineKeyboardButton("📈 Stats", callback_data="cmd:stats"),
        InlineKeyboardButton("📋 Trades", callback_data="cmd:trades"),
    ]

    row2 = [
        InlineKeyboardButton("💚 Health", callback_data="cmd:health"),
        InlineKeyboardButton("🩺 Doctor", callback_data="cmd:doctor"),
        InlineKeyboardButton("🧠 Signals", callback_data="cmd:signals"),
    ]

    row3 = []
    if is_running:
        row3.append(InlineKeyboardButton("⏹ Stop", callback_data="cmd:stop"))
    else:
        row3.append(InlineKeyboardButton("▶️ Start", callback_data="cmd:start"))
    row3.append(InlineKeyboardButton("⚙️ Settings", callback_data="cmd:settings"))

    row4 = [
        InlineKeyboardButton("🚨 Kill Switch", callback_data="cmd:kill_switch"),
        InlineKeyboardButton("📋 Flatten All", callback_data="cmd:flatten"),
    ]

    return InlineKeyboardMarkup([row1, row2, row3, row4])


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
