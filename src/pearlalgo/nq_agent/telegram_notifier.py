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
        enabled: bool = True,
    ):
        """
        Initialize Telegram notifier.
        
        Args:
            bot_token: Telegram bot token (required if enabled)
            chat_id: Telegram chat ID (required if enabled)
            enabled: Whether Telegram notifications are enabled
        """
        self.enabled = enabled
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.telegram: Optional[TelegramAlerts] = None
        
        # Initialize TelegramAlerts if credentials provided
        if enabled and bot_token and chat_id:
            try:
                self.telegram = TelegramAlerts(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    enabled=True,
                )
                logger.info("NQAgentTelegramNotifier initialized using TelegramAlerts")
            except Exception as e:
                logger.warning(f"Could not initialize TelegramAlerts: {e}")
                self.telegram = None
                self.enabled = False
        elif enabled:
            logger.warning("Telegram enabled but bot_token or chat_id not provided")
            self.enabled = False
    
    async def send_signal(self, signal: Dict) -> bool:
        """
        Send a trading signal to Telegram using rich formatting.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False
        
        try:
            # Use TelegramAlerts.notify_signal() for rich formatting
            await self.telegram.notify_signal(
                symbol=signal.get("symbol", "NQ"),
                side=signal.get("direction", "long").lower(),
                price=signal.get("entry_price", 0),
                strategy=signal.get("strategy", "nq_intraday"),
                confidence=signal.get("confidence"),
                entry_price=signal.get("entry_price"),
                stop_loss=signal.get("stop_loss"),
                take_profit=signal.get("take_profit"),
                reasoning=signal.get("reason"),
            )
            return True
        except Exception as e:
            logger.error(f"Error sending signal to Telegram: {e}", exc_info=True)
            return False
    
    async def send_status(self, status: Dict) -> bool:
        """
        Send status update to Telegram.
        
        Args:
            status: Status dictionary
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False
        
        message = self._format_status_message(status)
        
        try:
            await self.telegram.send_message(message)
            return True
        except Exception as e:
            logger.error(f"Error sending status update: {e}", exc_info=True)
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
    
    async def send_daily_summary(self, performance_metrics: Dict) -> bool:
        """
        Send daily performance summary to Telegram.
        
        Args:
            performance_metrics: Performance metrics dictionary
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False
        
        try:
            total_pnl = performance_metrics.get("total_pnl", 0)
            wins = performance_metrics.get("wins", 0)
            losses = performance_metrics.get("losses", 0)
            total_trades = wins + losses
            win_rate = performance_metrics.get("win_rate", 0)
            
            await self.telegram.notify_daily_summary(
                daily_pnl=total_pnl,
                total_trades=total_trades,
                win_rate=win_rate if total_trades > 0 else None,
            )
            return True
        except Exception as e:
            logger.error(f"Error sending daily summary: {e}", exc_info=True)
            return False
    
    async def send_enhanced_status(self, status: Dict) -> bool:
        """
        Send enhanced status message with performance metrics.
        
        Args:
            status: Status dictionary with performance data
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False
        
        try:
            message = "📊 *NQ Agent Status*\n\n"
            
            # Service status
            if "running" in status:
                status_emoji = "🟢" if status.get("running") else "🔴"
                pause_status = " ⏸️ PAUSED" if status.get("paused") else ""
                message += f"{status_emoji} Status: {'RUNNING' if status.get('running') else 'STOPPED'}{pause_status}\n"
            
            # Uptime
            if "uptime" in status and status["uptime"]:
                uptime = status["uptime"]
                message += f"⏱️ Uptime: {uptime.get('hours', 0)}h {uptime.get('minutes', 0)}m\n"
            
            # Counts
            message += f"🔄 Cycles: {status.get('cycle_count', 0)}\n"
            message += f"🔔 Signals: {status.get('signal_count', 0)}\n"
            message += f"⚠️ Errors: {status.get('error_count', 0)}\n"
            message += f"📊 Buffer: {status.get('buffer_size', 0)} bars\n"
            
            # Performance metrics
            performance = status.get("performance", {})
            if performance:
                message += "\n*Performance (7 days):*\n"
                exited = performance.get("exited_signals", 0)
                if exited > 0:
                    message += f"✅ Wins: {performance.get('wins', 0)}\n"
                    message += f"❌ Losses: {performance.get('losses', 0)}\n"
                    message += f"📈 Win Rate: {performance.get('win_rate', 0) * 100:.1f}%\n"
                    message += f"💰 Total P&L: ${performance.get('total_pnl', 0):,.2f}\n"
                    message += f"📊 Avg P&L: ${performance.get('avg_pnl', 0):,.2f}\n"
                else:
                    message += "No completed trades yet\n"
            
            await self.telegram.send_message(message)
            return True
        except Exception as e:
            logger.error(f"Error sending enhanced status: {e}", exc_info=True)
            return False
