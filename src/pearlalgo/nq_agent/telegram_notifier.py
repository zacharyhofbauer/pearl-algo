"""
NQ Agent Telegram Notifier

Sends signals and status updates to Telegram.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    import telegram
    from telegram import Bot
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed, Telegram notifications disabled")

from pearlalgo.utils.telegram_alerts import TelegramAlerts


class NQAgentTelegramNotifier:
    """
    Telegram notifier for NQ agent signals.
    
    Sends formatted signal messages to Telegram.
    """
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        """
        Initialize Telegram notifier.
        
        Args:
            bot_token: Telegram bot token (optional, uses TelegramAlerts if not provided)
            chat_id: Telegram chat ID (optional, uses TelegramAlerts if not provided)
        """
        # Use existing TelegramAlerts utility if available
        try:
            self.telegram = TelegramAlerts()
            logger.info("NQAgentTelegramNotifier initialized using TelegramAlerts")
        except Exception as e:
            logger.warning(f"Could not initialize TelegramAlerts: {e}")
            self.telegram = None
        
        # Fallback to direct bot if TelegramAlerts not available
        if self.telegram is None and TELEGRAM_AVAILABLE and bot_token and chat_id:
            self.bot = Bot(token=bot_token)
            self.chat_id = chat_id
            logger.info("NQAgentTelegramNotifier initialized with direct bot")
        else:
            self.bot = None
            self.chat_id = None
    
    def send_signal(self, signal: Dict) -> bool:
        """
        Send a trading signal to Telegram.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            True if sent successfully
        """
        message = self._format_signal_message(signal)
        
        try:
            if self.telegram:
                # Use TelegramAlerts utility
                self.telegram.send_message(message)
                return True
            elif self.bot and self.chat_id:
                # Use direct bot
                self.bot.send_message(chat_id=self.chat_id, text=message, parse_mode="Markdown")
                return True
            else:
                logger.warning("Telegram not configured, signal not sent")
                return False
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False
    
    def send_status(self, status: Dict) -> bool:
        """
        Send status update to Telegram.
        
        Args:
            status: Status dictionary
            
        Returns:
            True if sent successfully
        """
        message = self._format_status_message(status)
        
        try:
            if self.telegram:
                self.telegram.send_message(message)
                return True
            elif self.bot and self.chat_id:
                self.bot.send_message(chat_id=self.chat_id, text=message, parse_mode="Markdown")
                return True
            else:
                return False
        except Exception as e:
            logger.error(f"Error sending status update: {e}")
            return False
    
    def _format_signal_message(self, signal: Dict) -> str:
        """
        Format signal as Telegram message.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Formatted message string
        """
        symbol = signal.get("symbol", "NQ")
        signal_type = signal.get("type", "unknown")
        direction = signal.get("direction", "").upper()
        entry_price = signal.get("entry_price", 0)
        stop_loss = signal.get("stop_loss", 0)
        take_profit = signal.get("take_profit", 0)
        confidence = signal.get("confidence", 0)
        reason = signal.get("reason", "")
        
        # Calculate risk/reward
        if direction == "LONG" and stop_loss > 0 and take_profit > 0:
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
            risk_reward = reward / risk if risk > 0 else 0
        else:
            risk_reward = 0
        
        message = f"""
🔔 *NQ Intraday Signal*

*Type:* {signal_type}
*Direction:* {direction}
*Entry:* ${entry_price:.2f}
*Stop Loss:* ${stop_loss:.2f}
*Take Profit:* ${take_profit:.2f}
*R:R Ratio:* {risk_reward:.2f}
*Confidence:* {confidence:.0%}

*Reason:* {reason}
"""
        return message.strip()
    
    def _format_status_message(self, status: Dict) -> str:
        """
        Format status update as Telegram message.
        
        Args:
            status: Status dictionary
            
        Returns:
            Formatted message string
        """
        message = f"""
📊 *NQ Agent Status*

{status.get('message', 'No status available')}
"""
        return message.strip()
