"""
Telegram Alerts - Send notifications for trades and major events.
"""

from __future__ import annotations

from typing import Optional

from pearlalgo.utils.logger import logger

try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:
    Bot = None
    TelegramError = Exception


def _format_separator(length: int = 25) -> str:
    """Create a visual separator line (mobile-friendly)."""
    # Use blank line instead of long separator for mobile compatibility
    return ""


def _format_uptime(uptime: dict) -> str:
    """Format uptime compactly."""
    hours = uptime.get('hours', 0)
    minutes = uptime.get('minutes', 0)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_number(value: float, decimals: int = 2, show_sign: bool = False) -> str:
    """Format number with commas and optional sign."""
    if value is None:
        return "N/A"
    sign = "+" if show_sign and value >= 0 else ""
    return f"{sign}{value:,.{decimals}f}"


def _format_currency(value: float, show_sign: bool = False) -> str:
    """Format currency value."""
    if value is None:
        return "$0.00"
    sign = "+" if show_sign and value >= 0 else ""
    return f"{sign}${value:,.2f}"


def _format_percentage(value: float, decimals: int = 1) -> str:
    """Format percentage."""
    if value is None:
        return "0%"
    return f"{value:.{decimals}f}%"


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
        self,
        message: str,
        parse_mode: str = "Markdown",
        max_retries: int = 3,
        reply_markup=None,
    ) -> bool:
        """
        Send a message to Telegram with retry logic and deduplication.

        Args:
            message: Message text
            parse_mode: Telegram parse mode (default: Markdown)
            max_retries: Maximum retry attempts (default: 3)
            reply_markup: Optional Telegram reply markup (inline buttons)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled or not self.bot:
            return False

        import asyncio
        import hashlib
        import time

        # Enhanced deduplication: track last message hash and timestamp
        # Prevent sending same or very similar messages within 120 seconds (2 minutes)
        # Normalize message for better duplicate detection (remove variable timestamps/ages)
        import re
        normalized_message = message
        # Normalize variable parts that might differ slightly but are essentially the same message
        # Remove age values in both "X.X minutes old" format and "*Age:* X.X minutes" format
        normalized_message = re.sub(r'\d+\.\d+ minutes old', 'X.X minutes old', normalized_message)
        normalized_message = re.sub(r'\*Age:\* \d+\.\d+ minutes', '*Age:* X.X minutes', normalized_message)
        # Remove time stamps (e.g., "01:42:20 PM ET" -> "XX:XX:XX XM ET")
        normalized_message = re.sub(r'\d+:\d+:\d+ [AP]M ET', 'XX:XX:XX XM ET', normalized_message)
        # Remove percentages
        normalized_message = re.sub(r'\d+\.\d+%', 'X.X%', normalized_message)
        # Remove price values in stale data alerts
        normalized_message = re.sub(r'\$\d+,\d+\.\d+', '$X,XXX.XX', normalized_message)
        
        message_hash = hashlib.md5(normalized_message.encode()).hexdigest()
        current_time = time.time()
        
        if not hasattr(self, '_last_message_hash'):
            self._last_message_hash = None
            self._last_message_time = 0
        
        # Skip if same/similar message sent within last 120 seconds (2 minutes)
        if (self._last_message_hash == message_hash and 
            current_time - self._last_message_time < 120.0):
            logger.debug(f"Skipping duplicate message (sent {current_time - self._last_message_time:.1f}s ago)")
            return True  # Return True since message was already sent

        for attempt in range(max_retries):
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
                # Mark as sent successfully
                self._last_message_hash = message_hash
                self._last_message_time = current_time
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

                # Markdown parsing errors - try sending as plain text immediately
                if "parse entities" in error_msg.lower() or "can't parse" in error_msg.lower():
                    logger.warning(f"Markdown parsing error, retrying as plain text: {e}")
                    # Try sending as plain text on next attempt
                    if attempt < max_retries - 1:
                        try:
                            await self.bot.send_message(
                                chat_id=self.chat_id,
                                text=message,
                                parse_mode=None,  # Plain text
                                reply_markup=reply_markup,
                            )
                            return True
                        except Exception as e2:
                            logger.debug(f"Plain text send also failed: {e2}")
                            # Continue to retry loop
                    elif attempt == max_retries - 1:
                        # Last attempt - try without Markdown
                        try:
                            await self.bot.send_message(
                                chat_id=self.chat_id,
                                text=message.replace('*', '').replace('_', '').replace('`', ''),
                                parse_mode=None,
                                reply_markup=reply_markup,
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
        """
        Notify about a risk warning (mobile-friendly).
        
        Args:
            message: Alert message (should already be formatted with emoji and title)
            risk_status: Optional status string (e.g., "DATA_QUALITY", "CRITICAL")
        """
        # Message should already be formatted, just add Risk Warning header if not present
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
        """Send daily trading summary (mobile-friendly)."""
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        trend_emoji = "↗️" if daily_pnl >= 0 else "↘️"
        trend_text = "Profitable" if daily_pnl >= 0 else "Loss"

        message = f"{pnl_emoji} *Daily Summary*\n\n"
        message += f"💰 *P&L:* {_format_currency(daily_pnl)}\n"

        if win_rate is not None:
            message += f"📊 *Trades:* {total_trades} ({_format_percentage(win_rate * 100)} WR)\n"
        else:
            message += f"📊 *Trades:* {total_trades}\n"

        message += f"📈 *Trend:* {trend_emoji} {trend_text}\n"

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
        # Options-specific parameters
        option_symbol: Optional[str] = None,
        strike: Optional[float] = None,
        expiration: Optional[str] = None,
        option_type: Optional[str] = None,  # "call" or "put"
        underlying_price: Optional[float] = None,
        delta: Optional[float] = None,
        gamma: Optional[float] = None,
        theta: Optional[float] = None,
        dte: Optional[int] = None,
    ) -> None:
        """
        Notify about a new trading signal with rich formatting.
        Supports both stock/futures and options signals.

        Args:
            symbol: Trading symbol (underlying for options)
            side: "long" or "short"
            price: Current market price (option premium for options)
            strategy: Strategy name
            confidence: Signal confidence (0-1)
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            reasoning: LLM reasoning (optional)
            option_symbol: Option contract symbol (e.g., "QQQ240119C00450")
            strike: Strike price
            expiration: Expiration date (YYYY-MM-DD)
            option_type: "call" or "put"
            underlying_price: Current underlying price
            delta: Option delta (if available)
            gamma: Option gamma (if available)
            theta: Option theta (if available)
            dte: Days to expiration
        """
        side_emoji = "🟢" if side.lower() == "long" else "🔴"
        side_text = side.upper()
        sep = _format_separator(25)

        # Check if this is an options signal
        is_options = option_symbol is not None or option_type is not None

        # Header (mobile-friendly, no long separators)
        if is_options:
            message = f"{side_emoji} *NEW OPTIONS SIGNAL*\n*{symbol} {side_text}*\n\n"
        else:
            message = f"{side_emoji} *NEW SIGNAL*\n*{symbol} {side_text}*\n\n"

        # Entry/Stop/Target section with better alignment
        entry = entry_price if entry_price else price
        if entry:
            # Calculate all values first for alignment
            stop_pct_str = ""
            tp_pct_str = ""
            rr_ratio = None

            if stop_loss and entry:
                if side.lower() == "long":
                    stop_pct = ((stop_loss - entry) / entry) * 100
                else:
                    stop_pct = ((entry - stop_loss) / entry) * 100
                stop_pct_str = f" ({stop_pct:+.2f}%)"

            if take_profit and entry:
                if side.lower() == "long":
                    tp_pct = ((take_profit - entry) / entry) * 100
                else:
                    tp_pct = ((entry - take_profit) / entry) * 100
                tp_pct_str = f" ({tp_pct:+.2f}%)"

            # Calculate R:R if we have both stop and target
            if stop_loss and take_profit and entry:
                if side.lower() == "long":
                    risk = abs(entry - stop_loss)
                    reward = abs(take_profit - entry)
                else:
                    risk = abs(entry - stop_loss)
                    reward = abs(entry - take_profit)
                if risk > 0:
                    rr_ratio = reward / risk

            # Format with consistent alignment
            message += f"Entry:    {_format_currency(entry)}\n"
            if stop_loss:
                message += f"Stop:     {_format_currency(stop_loss)}{stop_pct_str}\n"
            if take_profit:
                # Include R:R on target line if available
                if rr_ratio is not None:
                    message += f"Target:   {_format_currency(take_profit)}{tp_pct_str}  R:R {rr_ratio:.1f}:1\n"
                else:
                    message += f"Target:   {_format_currency(take_profit)}{tp_pct_str}\n"

        # Confidence bar
        if confidence is not None:
            confidence_pct = confidence * 100
            confidence_bar = "█" * int(confidence_pct / 10) + "░" * (10 - int(confidence_pct / 10))
            message += f"\n*Confidence:* {confidence_pct:.0f}% {confidence_bar}\n"

        # Strategy and reasoning
        message += f"\n*Strategy:* {strategy}\n"

        if reasoning:
            # Truncate reasoning intelligently for mobile
            if len(reasoning) > 120:
                reasoning = reasoning[:117] + "..."
            message += f"\n*Reason:*\n{reasoning}\n"

        # Options-specific info
        if is_options:
            if option_symbol:
                message += f"\nContract: `{option_symbol}`\n"
            if option_type:
                option_emoji = "📞" if option_type.lower() == "call" else "📉"
                message += f"Type: {option_emoji} {option_type.upper()}\n"
            if strike:
                message += f"Strike: {_format_currency(strike)}\n"
            if expiration:
                message += f"Expiry: {expiration}\n"
            if dte is not None:
                message += f"DTE: {dte} days\n"
            if delta is not None:
                message += f"Delta: {delta:.3f}\n"

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
