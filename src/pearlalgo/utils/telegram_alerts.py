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

    async def send_message(
        self, message: str, parse_mode: str = "Markdown", max_retries: int = 3
    ) -> bool:
        """
        Send a message to Telegram with retry logic.

        Args:
            message: Message text
            parse_mode: Telegram parse mode (default: Markdown)
            max_retries: Maximum retry attempts (default: 3)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled or not self.bot:
            return False

        import asyncio

        for attempt in range(max_retries):
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode=parse_mode,
                )
                return True
            except TelegramError as e:
                error_msg = str(e)
                # "Not Found" usually means invalid chat_id or bot not started
                if "Not Found" in error_msg or "404" in error_msg:
                    logger.error(
                        f"Telegram chat not found. This usually means:\n"
                        f"  1. Chat ID is incorrect: {self.chat_id}\n"
                        f"  2. Bot hasn't been started (send /start to your bot first)\n"
                        f"  3. Bot doesn't have permission to send to this chat\n"
                        f"  Error: {e}"
                    )
                    # Don't retry on 404 - it won't work
                    return False
                
                # Markdown parsing errors - try sending as plain text
                if "parse entities" in error_msg.lower() or "can't parse" in error_msg.lower():
                    logger.warning(f"Markdown parsing error, retrying as plain text: {e}")
                    if attempt == max_retries - 1:
                        # Last attempt - try without Markdown
                        try:
                            await self.bot.send_message(
                                chat_id=self.chat_id,
                                text=message.replace('*', '').replace('_', '').replace('`', ''),
                                parse_mode=None,
                            )
                            return True
                        except Exception as plain_error:
                            logger.error(f"Failed to send as plain text: {plain_error}")
                            return False
                
                if attempt < max_retries - 1:
                    # Exponential backoff
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"Telegram send failed (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {wait_time}s: {e}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Failed to send Telegram message after {max_retries} attempts: {e}")
                    return False
            except Exception as e:
                logger.error(f"Unexpected error sending Telegram message: {e}")
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
        """
        Notify about a new trading signal with rich formatting.

        Args:
            symbol: Trading symbol
            side: "long" or "short"
            price: Current market price
            strategy: Strategy name
            confidence: Signal confidence (0-1)
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            reasoning: LLM reasoning (optional)
        """
        side_emoji = "🟢" if side.lower() == "long" else "🔴"
        side_text = side.upper()
        
        message = f"{side_emoji} *NEW SIGNAL*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Direction:* {side_text}\n"
        message += f"*Price:* ${price:,.2f}\n"
        message += f"*Strategy:* {strategy}\n"
        
        if confidence is not None:
            confidence_pct = confidence * 100
            confidence_bar = "█" * int(confidence_pct / 10) + "░" * (10 - int(confidence_pct / 10))
            message += f"*Confidence:* {confidence_pct:.0f}% {confidence_bar}\n"
        
        if entry_price:
            message += f"*Entry:* ${entry_price:,.2f}\n"
        
        if stop_loss:
            stop_pct = ((stop_loss - price) / price * 100) if side.lower() == "long" else ((price - stop_loss) / price * 100)
            message += f"*Stop Loss:* ${stop_loss:,.2f} ({stop_pct:.2f}%)\n"
        
        if take_profit:
            tp_pct = ((take_profit - price) / price * 100) if side.lower() == "long" else ((price - take_profit) / price * 100)
            message += f"*Take Profit:* ${take_profit:,.2f} ({tp_pct:.2f}%)\n"
        
        if reasoning:
            # Truncate reasoning if too long
            if len(reasoning) > 200:
                reasoning = reasoning[:200] + "..."
            message += f"\n*Reasoning:*\n{reasoning}\n"
        
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
        """
        Notify about a signal being logged with P&L.

        Args:
            symbol: Trading symbol
            side: "long" or "short"
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            unrealized_pnl: Unrealized P&L
            risk_amount: Risk amount in dollars
        """
        side_emoji = "📈" if side.lower() == "long" else "📉"
        pnl_emoji = "💰" if unrealized_pnl and unrealized_pnl >= 0 else "💸"
        
        message = f"{side_emoji} *Signal Logged*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Side:* {side.upper()}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"
        
        if stop_loss:
            message += f"*Stop Loss:* ${stop_loss:,.2f}\n"
        
        if take_profit:
            message += f"*Take Profit:* ${take_profit:,.2f}\n"
        
        if unrealized_pnl is not None:
            message += f"\n{pnl_emoji} *Unrealized P&L:* ${unrealized_pnl:,.2f}\n"
        
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
        """
        Notify about a position exit with P&L.

        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            entry_price: Entry price
            exit_price: Exit price
            size: Position size
            realized_pnl: Realized profit/loss
            hold_duration: How long position was held (optional)
            exit_reason: Reason for exit (optional)
        """
        pnl_emoji = "💰" if realized_pnl >= 0 else "💸"
        direction_emoji = "📈" if direction.lower() == "long" else "📉"
        
        message = f"{pnl_emoji} *Position Exited*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Direction:* {direction.upper()} {direction_emoji}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"
        message += f"*Exit:* ${exit_price:,.2f}\n"
        message += f"*Size:* {size} contracts\n"
        
        if hold_duration:
            message += f"*Hold Duration:* {hold_duration}\n"
        
        message += f"\n*Realized P&L:* ${realized_pnl:,.2f}\n"
        
        if exit_reason:
            message += f"\n*Exit Reason:* {exit_reason}\n"
        
        await self.send_message(message)

    async def notify_stop_loss(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_price: float,
        size: int,
        realized_pnl: float,
    ) -> None:
        """
        Notify about a stop loss hit.

        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            entry_price: Entry price
            stop_price: Stop loss price
            size: Position size
            realized_pnl: Realized loss
        """
        loss_pct = abs((stop_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        
        message = f"🛑 *Stop Loss Hit*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Direction:* {direction.upper()}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"
        message += f"*Stop:* ${stop_price:,.2f} ({loss_pct:.2f}%)\n"
        message += f"*Size:* {size} contracts\n"
        message += f"\n*Realized Loss:* ${realized_pnl:,.2f}\n"
        
        await self.send_message(message)

    async def notify_take_profit(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        target_price: float,
        size: int,
        realized_pnl: float,
    ) -> None:
        """
        Notify about a take profit hit.

        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            entry_price: Entry price
            target_price: Take profit price
            size: Position size
            realized_pnl: Realized profit
        """
        profit_pct = abs((target_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        
        message = f"🎯 *Take Profit Hit*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Direction:* {direction.upper()}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"
        message += f"*Target:* ${target_price:,.2f} ({profit_pct:.2f}%)\n"
        message += f"*Size:* {size} contracts\n"
        message += f"\n*Realized Profit:* ${realized_pnl:,.2f}\n"
        
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
        """
        Notify about a position update (mark-to-market).

        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            entry_price: Entry price
            current_price: Current market price
            size: Position size
            unrealized_pnl: Unrealized profit/loss
        """
        pnl_emoji = "📈" if unrealized_pnl >= 0 else "📉"
        pnl_pct = abs((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        
        message = f"{pnl_emoji} *Position Update*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Direction:* {direction.upper()}\n"
        message += f"*Entry:* ${entry_price:,.2f}\n"
        message += f"*Current:* ${current_price:,.2f} ({pnl_pct:.2f}%)\n"
        message += f"*Size:* {size} contracts\n"
        message += f"\n*Unrealized P&L:* ${unrealized_pnl:,.2f}\n"
        
        await self.send_message(message)
