"""
NQ Agent Telegram Notifier

Sends signals and status updates to Telegram.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pearlalgo.utils.logger import logger

try:
    import telegram
    from telegram import Bot
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed, Telegram notifications disabled")

from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.market_hours import get_market_hours
from pearlalgo.utils.retry import async_retry_with_backoff
from pearlalgo.utils.telegram_alerts import (
    TelegramAlerts,
    _format_separator,
    _format_uptime,
    _format_currency,
    _format_percentage,
)


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

    @async_retry_with_backoff(
        max_retries=2,
        initial_delay=0.5,
        max_delay=5.0,
        exceptions=(Exception,),
    )
    async def send_signal(self, signal: Dict) -> bool:
        """
        Send a trading signal to Telegram using professional desk alert format.
        
        Args:
            signal: Signal dictionary with regime, MTF, VWAP context
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            # Format professional desk alert
            message = self._format_professional_signal(signal)
            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_signal")
            return False

    def _format_professional_signal(self, signal: Dict) -> str:
        """
        Format signal as professional desk alert.
        
        Args:
            signal: Signal dictionary with full context
            
        Returns:
            Formatted message string
        """
        symbol = signal.get("symbol", "MNQ")  # Default to MNQ for prop firm trading
        signal_type = signal.get("type", "unknown").replace("_", " ").title()
        direction = signal.get("direction", "long").upper()
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

        # Get regime context
        regime = signal.get("regime", {})
        regime_type = regime.get("regime", "ranging")
        volatility = regime.get("volatility", "normal")
        session = regime.get("session", "afternoon")

        # Get MTF context
        mtf_analysis = signal.get("mtf_analysis", {})
        mtf_alignment = mtf_analysis.get("alignment", "partial")
        mtf_score = mtf_analysis.get("alignment_score", 0.5)

        # Get VWAP context
        vwap_data = signal.get("vwap_data", {})
        vwap = vwap_data.get("vwap", 0)
        vwap_distance = vwap_data.get("distance_from_vwap", 0)
        vwap_distance_pct = vwap_data.get("distance_pct", 0)

        # Format regime string
        regime_str = f"{regime_type.replace('_', ' ').title()} | {volatility.title()} Vol"

        # Format session string
        session_map = {
            "opening": "Opening (9:30-10:00 ET)",
            "morning_trend": "Morning Trend (10:00-11:30 ET)",
            "lunch_lull": "Lunch Lull (11:30-13:00 ET)",
            "afternoon": "Afternoon (13:00-15:30 ET)",
            "closing": "Closing (15:30-16:00 ET)",
        }
        session_str = session_map.get(session, session)

        # Format MTF alignment
        if mtf_alignment == "aligned":
            mtf_indicator = "✅"
            mtf_text = "1m/5m/15m Aligned"
        elif mtf_alignment == "partial":
            mtf_indicator = "⚠️"
            mtf_text = "Partial Alignment"
        else:
            mtf_indicator = "❌"
            mtf_text = "Conflicting"

        # Confidence tier
        if confidence >= 0.70:
            conf_tier = "High"
            conf_emoji = "🟢"
        elif confidence >= 0.55:
            conf_tier = "Moderate"
            conf_emoji = "🟡"
        else:
            conf_tier = "Low"
            conf_emoji = "🔴"

        # Build message
        message = f"🎯 *{symbol} {direction} | {signal_type}*\n"
        message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

        # Regime and session context
        message += f"*REGIME:* {regime_str}\n"
        message += f"*SESSION:* {session_str}\n"
        message += f"*MTF:* {mtf_indicator} {mtf_text}\n\n"

        # Entry/Stop/Target
        message += f"*ENTRY:* {entry_price:.2f}\n"
        message += f"*STOP:* {stop_loss:.2f} ({stop_loss - entry_price:+.2f})\n"
        message += f"*TARGET:* {take_profit:.2f} ({take_profit - entry_price:+.2f})\n"
        message += f"*R:R:* {risk_reward:.2f}:1\n\n"

        # Confidence and edge
        message += f"*CONFIDENCE:* {conf_emoji} {confidence:.0%} ({conf_tier})\n"
        # TODO: Add historical edge when available
        # message += f"*EDGE:* {historical_wr:.0%} Historical WR\n\n"
        message += "\n"

        # Context section
        message += "*CONTEXT:*\n"

        # VWAP position
        if vwap > 0:
            vwap_emoji = "📈" if vwap_distance > 0 else "📉"
            vwap_text = f"Above VWAP (+{vwap_distance:.2f})" if vwap_distance > 0 else f"Below VWAP ({vwap_distance:.2f})"
            if abs(vwap_distance_pct) < 0.1:
                vwap_text += " - Near VWAP"
            elif vwap_distance > 0:
                vwap_text += " - Institutional support"
            else:
                vwap_text += " - Fighting institutions"
            message += f"• {vwap_emoji} {vwap_text}\n"

        # Volume context (from indicators if available)
        indicators = signal.get("indicators", {})
        volume_ratio = indicators.get("volume_ratio", 0)
        if volume_ratio > 0:
            if volume_ratio > 1.5:
                vol_text = f"Volume: {volume_ratio:.1f}x avg (strong)"
            elif volume_ratio > 1.2:
                vol_text = f"Volume: {volume_ratio:.1f}x avg (moderate)"
            else:
                vol_text = f"Volume: {volume_ratio:.1f}x avg"
            message += f"• 📊 {vol_text}\n"

        # ATR/Volatility
        atr = indicators.get("atr", 0)
        if atr > 0:
            atr_pct = (atr / entry_price) * 100 if entry_price > 0 else 0
            vol_text = f"ATR: {atr_pct:.2f}%"
            if volatility == "low":
                vol_text += " (low vol compression)"
            elif volatility == "high":
                vol_text += " (high vol expansion)"
            message += f"• 📉 {vol_text}\n"

        # MTF levels if breakout
        if "breakout" in signal_type.lower():
            breakout_levels = mtf_analysis.get("breakout_levels", {})
            resistance_5m = breakout_levels.get("resistance_5m")
            if resistance_5m:
                if entry_price > resistance_5m:
                    message += f"• ✅ Breaking 5m resistance ({resistance_5m:.2f})\n"
                else:
                    message += f"• ⚠️ Below 5m resistance ({resistance_5m:.2f})\n"

        message += "\n"

        # Setup description
        message += f"*SETUP:* {reason}\n\n"

        # Actionable warnings
        warnings = []

        # Session warnings
        if session == "lunch_lull":
            warnings.append("Lunch lull approaching - Consider tighter stops if choppy")
        elif session == "opening":
            warnings.append("Opening volatility - Monitor closely")
        elif session == "closing":
            warnings.append("Closing hour - Potential reversals")

        # Regime warnings
        if "ranging" in regime_type and "momentum" in signal_type.lower():
            warnings.append("Ranging market - Momentum may whipsaw")
        elif "trending" in regime_type and "mean_reversion" in signal_type.lower():
            warnings.append("Trending market - Mean reversion fighting trend")

        # Volatility warnings
        if volatility == "high":
            warnings.append("High volatility - Wider stops recommended")
        elif volatility == "low":
            warnings.append("Low volatility - Potential expansion move")

        # MTF warnings
        if mtf_alignment == "conflicting":
            warnings.append("MTF conflicting - Lower conviction")
        elif mtf_alignment == "partial":
            warnings.append("Partial MTF alignment - Monitor closely")

        if warnings:
            message += "*⚠️ WATCH:*\n"
            for warning in warnings:
                message += f"• {warning}\n"

        return message

    @async_retry_with_backoff(
        max_retries=2,
        initial_delay=0.5,
        max_delay=5.0,
        exceptions=(Exception,),
    )
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
            ErrorHandler.handle_telegram_error(e, "send_status")
            return False

    def _format_signal_message(self, signal: Dict) -> str:
        """
        Format signal as Telegram message.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Formatted message string
        """
        symbol = signal.get("symbol", "MNQ")  # Default to MNQ for prop firm trading
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

    @async_retry_with_backoff(
        max_retries=2,
        initial_delay=0.5,
        max_delay=5.0,
        exceptions=(Exception,),
    )
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
            ErrorHandler.handle_telegram_error(e, "send_daily_summary")
            return False

    @async_retry_with_backoff(
        max_retries=2,
        initial_delay=0.5,
        max_delay=5.0,
        exceptions=(Exception,),
    )
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
            message = f"📊 *NQ Agent Status*\n\n"

            # Service and market status
            status_emoji = "🟢" if status.get("running") else "🔴"
            pause_status = " ⏸️ PAUSED" if status.get("paused") else ""
            uptime_str = ""
            if "uptime" in status and status["uptime"]:
                uptime_str = f" ({_format_uptime(status['uptime'])})"

            try:
                market_hours = get_market_hours()
                is_market_open = market_hours.is_market_open()
                market_emoji = "🟢" if is_market_open else "🔴"
                market_text = "OPEN" if is_market_open else "CLOSED"
            except Exception:
                market_emoji = "⚪"
                market_text = "UNKNOWN"

            message += f"{status_emoji} *Service:* RUNNING{pause_status}{uptime_str}\n"
            message += f"{market_emoji} *Market:* {market_text}\n"

            # Connection status
            connection_status = status.get('connection_status', 'unknown')
            connection_failures = status.get('connection_failures', 0)
            if connection_status == 'disconnected' or connection_failures > 0:
                conn_emoji = "🔴" if connection_status == 'disconnected' else "🟡"
                message += f"\n*Connection:*\n"
                message += f"{conn_emoji} {connection_status.upper()}\n"
                if connection_failures > 0:
                    message += f"⚠️ {connection_failures} failures\n"

            # Activity section
            cycles = status.get('cycle_count', 0)
            signals = status.get('signal_count', 0)
            errors = status.get('error_count', 0)
            buffer = status.get('buffer_size', 0)
            message += f"\n*Activity:*\n"
            message += f"🔄 {cycles:,} cycles\n"
            message += f"🔔 {signals} signals\n"
            message += f"📊 {buffer} bars\n"
            message += f"⚠️ {errors} errors\n"

            # Performance section
            performance = status.get("performance", {})
            if performance:
                exited = performance.get("exited_signals", 0)
                if exited > 0:
                    wins = performance.get('wins', 0)
                    losses = performance.get('losses', 0)
                    win_rate = performance.get('win_rate', 0) * 100
                    total_pnl = performance.get('total_pnl', 0)
                    avg_pnl = performance.get('avg_pnl', 0)

                    message += f"\n*Performance (7d):*\n"
                    message += f"✅ {wins}W  ❌ {losses}L\n"
                    message += f"📈 {_format_percentage(win_rate)} WR\n"
                    message += f"💰 {_format_currency(total_pnl)}\n"
                    message += f"📊 {_format_currency(avg_pnl)} avg\n"
                else:
                    message += f"\n*Performance (7d):*\n"
                    message += "⏳ No completed trades yet\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_enhanced_status")
            return False

    @async_retry_with_backoff(
        max_retries=2,
        initial_delay=0.5,
        max_delay=5.0,
        exceptions=(Exception,),
    )
    async def send_heartbeat(self, status: Dict) -> bool:
        """
        Send periodic heartbeat message.
        
        Args:
            status: Status dictionary with service information
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            market_hours = get_market_hours()
            is_market_open = market_hours.is_market_open()

            # Format uptime
            uptime_str = ""
            if "uptime" in status and status["uptime"]:
                uptime_str = _format_uptime(status["uptime"])

            message = f"💓 *Heartbeat*\n*{uptime_str} uptime*\n\n"

            # Status line
            market_emoji = "🟢" if is_market_open else "🔴"
            message += f"🟢 *Service:* RUNNING\n"
            message += f"{market_emoji} *Market:* {'OPEN' if is_market_open else 'CLOSED'}\n"

            # Activity (mobile-friendly, one per line)
            cycles = status.get('cycle_count', 0)
            signals = status.get('signal_count', 0)
            errors = status.get('error_count', 0)
            buffer = status.get('buffer_size', 0)
            message += f"\n*Activity:*\n"
            message += f"🔄 {cycles:,} cycles\n"
            message += f"🔔 {signals} signals\n"
            message += f"📊 {buffer} bars\n"
            message += f"⚠️ {errors} errors\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_heartbeat")
            return False

    @async_retry_with_backoff(
        max_retries=2,
        initial_delay=0.5,
        max_delay=5.0,
        exceptions=(Exception,),
    )
    async def send_data_quality_alert(
        self,
        alert_type: str,
        message: str,
        details: Optional[Dict] = None,
    ) -> bool:
        """
        Send data quality alert.
        
        Args:
            alert_type: Type of alert (stale_data, data_gap, fetch_failure, buffer_issue)
            message: Alert message
            details: Additional details dictionary
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            emoji_map = {
                "stale_data": "⏰",
                "data_gap": "📉",
                "fetch_failure": "❌",
                "buffer_issue": "⚠️",
            }

            emoji = emoji_map.get(alert_type, "⚠️")
            alert_message = f"{emoji} *Data Quality Alert*\n\n"
            alert_message += f"*Type:* {alert_type.replace('_', ' ').title()}\n"
            alert_message += f"*Message:* {message}\n"

            if details:
                if "age_minutes" in details:
                    alert_message += f"*Age:* {details['age_minutes']:.1f} minutes\n"
                if "consecutive_failures" in details:
                    alert_message += f"*Failures:* {details['consecutive_failures']}\n"
                if "buffer_size" in details:
                    alert_message += f"*Buffer:* {details['buffer_size']} bars\n"

            await self.telegram.notify_risk_warning(alert_message, risk_status="DATA_QUALITY")
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_data_quality_alert")
            return False

    async def send_startup_notification(self, config: Dict) -> bool:
        """
        Send service startup notification with configuration.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            message = f"🚀 *NQ Agent Started*\n\n"

            # Compact config (mobile-friendly)
            symbol = config.get('symbol', 'MNQ')  # Default to MNQ for prop firm trading
            timeframe = config.get('timeframe', '1m')
            scan_interval = config.get('scan_interval', 60)
            max_risk = config.get('max_risk_per_trade', 0.02) * 100
            rr_ratio = config.get('take_profit_risk_reward', 2.0)

            message += f"*Config:*\n"
            message += f"• Symbol: {symbol}\n"
            message += f"• Timeframe: {timeframe}\n"
            message += f"• Scan: {scan_interval}s\n"
            message += f"• Risk: {max_risk:.1f}%\n"
            message += f"• R:R: {rr_ratio:.1f}:1\n"

            # Market status
            market_hours = get_market_hours()
            is_market_open = market_hours.is_market_open()
            market_emoji = "🟢" if is_market_open else "🔴"
            message += f"\n{market_emoji} *Market:* {'OPEN' if is_market_open else 'CLOSED'}\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_startup_notification")
            return False

    async def send_shutdown_notification(self, summary: Dict) -> bool:
        """
        Send service shutdown notification with summary.
        
        Args:
            summary: Summary dictionary with service statistics
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            message = f"🛑 *NQ Agent Stopped*\n\n"

            # Session summary (mobile-friendly)
            uptime_h = summary.get('uptime_hours', 0)
            uptime_m = summary.get('uptime_minutes', 0)
            cycles = summary.get('cycle_count', 0)
            signals = summary.get('signal_count', 0)
            errors = summary.get('error_count', 0)

            message += f"*Session Summary:*\n"
            message += f"⏱️ Uptime: {uptime_h:.0f}h {uptime_m:.0f}m\n"
            message += f"🔄 {cycles:,} cycles\n"
            message += f"🔔 {signals} signals\n"
            message += f"⚠️ {errors} errors\n"

            # Performance if available
            if summary.get('signal_count', 0) > 0:
                wins = summary.get('wins', 0)
                losses = summary.get('losses', 0)
                total_pnl = summary.get('total_pnl', 0)

                if wins > 0 or losses > 0:
                    message += f"\n*Performance:*\n"
                    message += f"✅ {wins}W  ❌ {losses}L\n"

                if total_pnl is not None:
                    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                    message += f"{pnl_emoji} *P&L:* {_format_currency(total_pnl)}\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_shutdown_notification")
            return False

    @async_retry_with_backoff(
        max_retries=2,
        initial_delay=0.5,
        max_delay=5.0,
        exceptions=(Exception,),
    )
    async def send_weekly_summary(self, performance_metrics: Dict) -> bool:
        """
        Send weekly performance summary.
        
        Args:
            performance_metrics: Performance metrics dictionary
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            message = f"📅 *Weekly Performance Summary*\n\n"

            total_signals = performance_metrics.get("total_signals", 0)
            exited_signals = performance_metrics.get("exited_signals", 0)
            wins = performance_metrics.get("wins", 0)
            losses = performance_metrics.get("losses", 0)
            win_rate = performance_metrics.get("win_rate", 0) * 100
            total_pnl = performance_metrics.get("total_pnl", 0)
            avg_pnl = performance_metrics.get("avg_pnl", 0)
            avg_hold = performance_metrics.get("avg_hold_minutes", 0)

            # Signal statistics (mobile-friendly)
            message += f"*Signals:*\n"
            message += f"• Total: {total_signals}\n"
            message += f"• Exited: {exited_signals}\n"
            if total_signals > 0:
                exit_rate = (exited_signals / total_signals) * 100
                message += f"• Exit Rate: {_format_percentage(exit_rate)}\n"

            if exited_signals > 0:
                message += f"\n*Trade Performance:*\n"
                message += f"✅ {wins}W  ❌ {losses}L\n"
                message += f"📈 {_format_percentage(win_rate)} WR\n"
                message += f"💰 {_format_currency(total_pnl)}\n"
                message += f"📊 {_format_currency(avg_pnl)} avg\n"
                message += f"⏱️ {avg_hold:.1f}m avg hold\n"

                # Performance trend
                if total_pnl > 0:
                    message += f"\n📈 *Trend:* ↗️ Profitable week\n"
                elif total_pnl < 0:
                    message += f"\n📉 *Trend:* ↘️ Loss week\n"
                else:
                    message += f"\n➡️ *Trend:* ➡️ Break even\n"
            else:
                message += "\n⏳ *No completed trades this week*\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_weekly_summary")
            return False

    @async_retry_with_backoff(
        max_retries=2,
        initial_delay=0.5,
        max_delay=5.0,
        exceptions=(Exception,),
    )
    async def send_circuit_breaker_alert(self, reason: str, details: Optional[Dict] = None) -> bool:
        """
        Send circuit breaker activation alert.
        
        Args:
            reason: Reason for circuit breaker activation
            details: Additional details
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            message = f"🛑 *Circuit Breaker Activated*\n\n"
            message += f"*Reason:* {reason}\n"

            if details:
                if "consecutive_errors" in details:
                    message += f"*Errors:* {details['consecutive_errors']} consecutive\n"
                if "error_type" in details:
                    message += f"*Type:* {details['error_type']}\n"
                if "action_taken" in details:
                    message += f"*Action:* {details['action_taken']}\n"

            message += "\n⚠️ *Service paused. Manual intervention required.*\n"

            await self.telegram.notify_risk_warning(message, risk_status="CRITICAL")
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_circuit_breaker_alert")
            return False

    @async_retry_with_backoff(
        max_retries=2,
        initial_delay=0.5,
        max_delay=5.0,
        exceptions=(Exception,),
    )
    async def send_recovery_notification(self, recovery_info: Dict) -> bool:
        """
        Send recovery notification after errors.
        
        Args:
            recovery_info: Recovery information dictionary
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            message = f"✅ *Service Recovered*\n\n"
            message += f"*Issue:* {recovery_info.get('issue', 'Unknown')}\n"
            message += f"*Time:* {recovery_info.get('recovery_time_seconds', 0):.0f}s\n"
            message += f"*Status:* Normal operation\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_recovery_notification")
            return False
