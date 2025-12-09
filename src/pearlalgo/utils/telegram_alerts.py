"""
Telegram Alerts - Send notifications for trades and major events.
"""

from __future__ import annotations

import logging
from typing import Optional


try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:
    Bot = None
    TelegramError = Exception

logger = logging.getLogger(__name__)


class TelegramAlerts:
    """Telegram alert sender for trading notifications."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled

        self.bot = None
        if enabled and Bot:
            try:
                self.bot = Bot(token=bot_token)
                logger.info("Telegram alerts initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Telegram bot: {e}")
                self.enabled = False
        elif enabled and not Bot:
            logger.warning(
                "python-telegram-bot not installed, Telegram alerts disabled"
            )
            self.enabled = False

    async def send_message(self, message: str, parse_mode: str = "Markdown") -> bool:
        """Send a message to Telegram."""
        if not self.enabled or not self.bot:
            return False

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode
            )
            return True
        except TelegramError as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def notify_trade(
        self,
        symbol: str,
        side: str,
        size: int,
        price: float,
        order_id: Optional[str] = None,
    ) -> None:
        """Notify about a trade execution."""
        message = (
            f"🔔 *Trade Executed*\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {side.upper()}\n"
            f"Size: {size} contracts\n"
            f"Price: ${price:.2f}\n"
        )
        if order_id:
            message += f"Order ID: {order_id}"

        await self.send_message(message)

    async def notify_risk_warning(
        self,
        message: str,
        risk_status: Optional[str] = None,
    ) -> None:
        """Notify about a risk warning."""
        alert = f"⚠️ *Risk Warning*\n\n{message}"
        if risk_status:
            alert += f"\nRisk Status: {risk_status}"

        await self.send_message(alert)

    async def notify_daily_summary(
        self,
        daily_pnl: float,
        total_trades: int,
        win_rate: Optional[float] = None,
    ) -> None:
        """Send daily trading summary."""
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        message = (
            f"{pnl_emoji} *Daily Summary*\n\n"
            f"P&L: ${daily_pnl:,.2f}\n"
            f"Trades: {total_trades}\n"
        )
        if win_rate is not None:
            message += f"Win Rate: {win_rate * 100:.1f}%"

        await self.send_message(message)

    async def notify_kill_switch(self, reason: str) -> None:
        """Notify about kill-switch activation."""
        message = f"🛑 *KILL-SWITCH ACTIVATED*\n\n{reason}"
        await self.send_message(message)
