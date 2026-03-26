"""
Telegram alert sender - Send notifications for trades and major events.
"""

from __future__ import annotations

import re
from typing import Optional

from pearlalgo.utils.formatting import fmt_currency, fmt_pct_direct
from pearlalgo.utils.logger import logger

from .formats import sanitize_telegram_markdown, _truncate_telegram_text

try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:
    Bot = None
    TelegramError = Exception


class TelegramAlerts:
    """Telegram alert sender for trading notifications."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
        message_thread_id: Optional[int] = None,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self.message_thread_id = message_thread_id
        self.last_error: Optional[str] = None

        self.bot = None
        if enabled and Bot:
            try:
                self.bot = Bot(token=bot_token)
                logger.info("Telegram alerts initialized")
            except Exception as e:
                logger.warning("Failed to initialize Telegram bot: %s", e)
                self.last_error = str(e)
                self.enabled = False
        elif enabled and not Bot:
            logger.warning(
                "python-telegram-bot not installed, Telegram alerts disabled"
            )
            self.last_error = "python-telegram-bot not installed"
            self.enabled = False

    async def send_message(
        self,
        message: str,
        parse_mode: str | None = "Markdown",
        max_retries: int = 3,
        reply_markup=None,
        dedupe: bool = True,
    ) -> bool:
        if not self.enabled or not self.bot:
            self.last_error = "Telegram disabled or bot not initialized"
            return False

        import asyncio
        import hashlib
        import time

        message_raw = message
        message_markdown = message_raw
        if parse_mode and str(parse_mode).lower() == "markdown":
            message_markdown = sanitize_telegram_markdown(message_markdown)

        original_len = len(message_markdown)
        message_markdown = _truncate_telegram_text(message_markdown)
        if len(message_markdown) != original_len:
            logger.warning(
                "Telegram message truncated (len=%s -> %s)",
                original_len, len(message_markdown),
            )

        normalized_message = message_markdown
        normalized_message = re.sub(r'\d+\.\d+ minutes old', 'X.X minutes old', normalized_message)
        normalized_message = re.sub(r'\*Age:\* \d+\.\d+ minutes', '*Age:* X.X minutes', normalized_message)
        normalized_message = re.sub(r'\d+:\d+:\d+ [AP]M ET', 'XX:XX:XX XM ET', normalized_message)
        normalized_message = re.sub(r'\d+\.\d+%', 'X.X%', normalized_message)
        normalized_message = re.sub(r'\$\d+,\d+\.\d+', '$X,XXX.XX', normalized_message)

        message_hash = hashlib.md5(normalized_message.encode()).hexdigest()
        current_time = time.time()

        if not hasattr(self, '_last_message_hash'):
            self._last_message_hash = None
            self._last_message_time = 0

        if dedupe:
            if (self._last_message_hash == message_hash and
                    current_time - self._last_message_time < 120.0):
                logger.debug(
                    "Skipping duplicate message (sent %.1fs ago)",
                    current_time - self._last_message_time,
                )
                self.last_error = None
                return True

        for attempt in range(max_retries):
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message_markdown,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    message_thread_id=self.message_thread_id,
                )
                self._last_message_hash = message_hash
                self._last_message_time = current_time
                self.last_error = None
                return True
            except TelegramError as e:
                error_msg = str(e)
                self.last_error = error_msg
                if "Not Found" in error_msg or "404" in error_msg:
                    logger.error(
                        "Telegram chat not found. Chat ID: %s Error: %s",
                        self.chat_id, e,
                    )
                    return False

                if "parse entities" in error_msg.lower() or "can't parse" in error_msg.lower():
                    logger.debug("Markdown parsing error, retrying as plain text: %s", e)
                    if attempt < max_retries - 1:
                        try:
                            message_plain = _truncate_telegram_text(message_raw)
                            await self.bot.send_message(
                                chat_id=self.chat_id,
                                text=message_plain,
                                parse_mode=None,
                                reply_markup=reply_markup,
                                message_thread_id=self.message_thread_id,
                            )
                            self._last_message_hash = message_hash
                            self._last_message_time = current_time
                            self.last_error = None
                            return True
                        except Exception as e2:
                            logger.debug("Plain text send also failed: %s", e2)
                            self.last_error = str(e2)
                    elif attempt == max_retries - 1:
                        try:
                            await self.bot.send_message(
                                chat_id=self.chat_id,
                                text=_truncate_telegram_text(
                                    message_raw.replace('*', '').replace('_', '').replace('`', '')
                                ),
                                parse_mode=None,
                                reply_markup=reply_markup,
                                message_thread_id=self.message_thread_id,
                            )
                            self._last_message_hash = message_hash
                            self._last_message_time = current_time
                            self.last_error = None
                            return True
                        except Exception as plain_error:
                            logger.error("Failed to send as plain text: %s", plain_error)
                            self.last_error = str(plain_error)
                            return False

                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(
                        "Telegram send failed (attempt %s/%s), retrying in %ss: %s",
                        attempt + 1, max_retries, wait_time, e,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "Failed to send Telegram message after %s attempts: %s",
                        max_retries, e,
                    )
                    return False
            except Exception as e:
                logger.error("Unexpected error sending Telegram message: %s", e)
                self.last_error = str(e)
                return False

        return False

    async def notify_trade(
        self,
        symbol: str,
        side: str,
        size: int,
        price: float,
        order_id: Optional[str] = None,
    ) -> None:
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
        if "Risk Warning" not in message and "*Risk Warning*" not in message:
            alert = f"⚠️ *Risk Warning*\n\n{message}"
        else:
            alert = message
        if risk_status:
            alert += f"\n*Status:* {risk_status}"
        await self.send_message(alert)

    async def notify_daily_summary(
        self,
        daily_pnl: float,
        total_trades: int,
        win_rate: Optional[float] = None,
    ) -> None:
        pnl_icon = "📈" if daily_pnl >= 0 else "📉"
        trend_emoji = "↗️" if daily_pnl >= 0 else "↘️"
        trend_text = "Profitable" if daily_pnl >= 0 else "Loss"
        message = f"{pnl_icon} *Daily Summary*\n\n"
        message += f"💰 *P&L:* {fmt_currency(daily_pnl)}\n"
        if win_rate is not None:
            message += f"📊 *Trades:* {total_trades} ({fmt_pct_direct(win_rate * 100)} WR)\n"
        else:
            message += f"📊 *Trades:* {total_trades}\n"
        message += f"📈 *Trend:* {trend_emoji} {trend_text}\n"
        await self.send_message(message)

    async def notify_kill_switch(self, reason: str) -> None:
        await self.send_message(f"🛑 *KILL-SWITCH ACTIVATED*\n\n{reason}")

    async def notify_signal(
        self,
        symbol: str,
        side: str,
        price: float,
        strategy: str,
        confidence: Optional[float] = None,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reasoning: Optional[str] = None,
    ) -> None:
        side_emoji = "🟢" if side.lower() == "long" else "🔴"
        side_text = side.upper()
        message = f"{side_emoji} *NEW SIGNAL*\n*{symbol} {side_text}*\n\n"
        entry = entry_price if entry_price else price
        if entry:
            stop_pct_str = ""
            tp_pct_str = ""
            rr_ratio = None
            if stop_loss and entry:
                stop_pct = ((stop_loss - entry) / entry) * 100 if side.lower() == "long" else ((entry - stop_loss) / entry) * 100
                stop_pct_str = f" ({stop_pct:+.2f}%)"
            if take_profit and entry:
                tp_pct = ((take_profit - entry) / entry) * 100 if side.lower() == "long" else ((entry - take_profit) / entry) * 100
                tp_pct_str = f" ({tp_pct:+.2f}%)"
            if stop_loss and take_profit and entry:
                risk = abs(entry - stop_loss)
                reward = abs(take_profit - entry) if side.lower() == "long" else abs(entry - take_profit)
                rr_ratio = reward / risk if risk > 0 else None
            message += f"Entry:    {fmt_currency(entry)}\n"
            if stop_loss:
                message += f"Stop:     {fmt_currency(stop_loss)}{stop_pct_str}\n"
            if take_profit:
                message += f"Target:   {fmt_currency(take_profit)}{tp_pct_str}"
                if rr_ratio is not None:
                    message += f"  R:R {rr_ratio:.1f}:1"
                message += "\n"
        if confidence is not None:
            confidence_pct = confidence * 100
            bar = "█" * int(confidence_pct / 10) + "░" * (10 - int(confidence_pct / 10))
            message += f"\n*Confidence:* {confidence_pct:.0f}% {bar}\n"
        message += f"\n*Strategy:* {strategy}\n"
        if reasoning:
            message += f"\n*Reason:*\n{reasoning[:117] + '...' if len(reasoning) > 120 else reasoning}\n"
        await self.send_message(message)

    async def notify_signal_logged(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        unrealized_pnl: Optional[float] = None,
        risk_amount: Optional[float] = None,
    ) -> None:
        side_emoji = "📈" if side.lower() == "long" else "📉"
        pnl_icon = "💰" if unrealized_pnl and unrealized_pnl >= 0 else "💸"
        message = f"{side_emoji} *Signal Logged*\n\n*Symbol:* {symbol}\n*Side:* {side.upper()}\n*Entry:* ${entry_price:,.2f}\n"
        if stop_loss:
            message += f"*Stop Loss:* ${stop_loss:,.2f}\n"
        if take_profit:
            message += f"*Take Profit:* ${take_profit:,.2f}\n"
        if unrealized_pnl is not None:
            message += f"\n{pnl_icon} *Unrealized P&L:* ${unrealized_pnl:,.2f}\n"
        if risk_amount:
            message += f"*Risk:* ${risk_amount:,.2f}\n"
        await self.send_message(message)

    async def notify_exit(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        size: int,
        realized_pnl: float,
        hold_duration: Optional[str] = None,
        exit_reason: Optional[str] = None,
    ) -> None:
        pnl_icon = "💰" if realized_pnl >= 0 else "💸"
        direction_emoji = "📈" if direction.lower() == "long" else "📉"
        message = f"{pnl_icon} *Position Exited*\n\n*Symbol:* {symbol}\n*Direction:* {direction.upper()} {direction_emoji}\n*Entry:* ${entry_price:,.2f}\n*Exit:* ${exit_price:,.2f}\n*Size:* {size} contracts\n"
        if hold_duration:
            message += f"*Hold Duration:* {hold_duration}\n"
        message += f"\n*Realized P&L:* ${realized_pnl:,.2f}\n"
        if exit_reason:
            message += f"\n*Exit Reason:* {exit_reason}\n"
        await self.send_message(message)

    async def notify_stop_loss(
        self, symbol: str, direction: str, entry_price: float, stop_price: float, size: int, realized_pnl: float,
    ) -> None:
        loss_pct = abs((stop_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        message = f"🛑 *Stop Loss Hit*\n\n*Symbol:* {symbol}\n*Direction:* {direction.upper()}\n*Entry:* ${entry_price:,.2f}\n*Stop:* ${stop_price:,.2f} ({loss_pct:.2f}%)\n*Size:* {size} contracts\n\n*Realized Loss:* ${realized_pnl:,.2f}\n"
        await self.send_message(message)

    async def notify_take_profit(
        self, symbol: str, direction: str, entry_price: float, target_price: float, size: int, realized_pnl: float,
    ) -> None:
        profit_pct = abs((target_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        message = f"🎯 *Take Profit Hit*\n\n*Symbol:* {symbol}\n*Direction:* {direction.upper()}\n*Entry:* ${entry_price:,.2f}\n*Target:* ${target_price:,.2f} ({profit_pct:.2f}%)\n*Size:* {size} contracts\n\n*Realized Profit:* ${realized_pnl:,.2f}\n"
        await self.send_message(message)

    async def notify_position_update(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        current_price: float,
        size: int,
        unrealized_pnl: float,
    ) -> None:
        pnl_icon = "📈" if unrealized_pnl >= 0 else "📉"
        pnl_pct = abs((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        message = f"{pnl_icon} *Position Update*\n\n*Symbol:* {symbol}\n*Direction:* {direction.upper()}\n*Entry:* ${entry_price:,.2f}\n*Current:* ${current_price:,.2f} ({pnl_pct:.2f}%)\n*Size:* {size} contracts\n\n*Unrealized P&L:* ${unrealized_pnl:,.2f}\n"
        await self.send_message(message)
