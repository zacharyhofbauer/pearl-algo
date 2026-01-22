"""
Market Agent Telegram Notifier

Sends signals and status updates to Telegram.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

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
from pearlalgo.utils.paths import ensure_state_dir, parse_utc_timestamp
from pearlalgo.utils.retry import async_retry_with_backoff
from pearlalgo.utils.telegram_alerts import (
    TelegramAlerts,
    TelegramPrefs,
    _format_separator,
    _format_uptime,
    _format_currency,
    _format_percentage,
    format_signal_status,
    format_signal_direction,
    format_signal_confidence_tier,
    format_pnl,
    format_home_card,
    format_gate_status,
    format_service_status,
    format_session_window,
    safe_label,
    # New UX improvement helpers
    format_activity_pulse,
    format_next_session_time,
    format_signal_action_cue,
    format_signal_timing,
    format_performance_trend,
    # Standardized terminology constants
    LABEL_AGENT,
    LABEL_GATEWAY,
    LABEL_SCANS,
    STATE_RUNNING,
    STATE_STOPPED,
)
from pearlalgo.utils.telegram_ui_contract import (
    callback_menu,
    callback_action,
    callback_signal_detail,
    callback_confirm,
    callback_back,
    MENU_MAIN,
    MENU_SIGNALS,
    MENU_STATUS,
    ACTION_DATA_QUALITY,
    ACTION_GATEWAY_STATUS,
)

try:
    from pearlalgo.market_agent.chart_generator import ChartGenerator
    CHART_GENERATOR_AVAILABLE = True
except ImportError:
    CHART_GENERATOR_AVAILABLE = False
    ChartGenerator = None


def _is_command_handler_running() -> bool:
    """
    Check if the Telegram command handler service is running.
    
    This is used to determine whether to include deep-link buttons in push alerts.
    """
    try:
        import os
        project_root = Path(__file__).parent.parent.parent.parent
        pid_file = project_root / "logs" / "telegram_handler.pid"
        if not pid_file.exists():
            return False
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return True
    except Exception:
        return False


class MarketAgentTelegramNotifier:
    """
    Telegram notifier for NQ agent signals.
    
    Sends formatted signal messages to Telegram.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        state_dir: Optional[Path] = None,
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
        self.state_dir = ensure_state_dir(state_dir)
        self.telegram: Optional[TelegramAlerts] = None
        self.chart_generator: Optional[ChartGenerator] = None
        
        # Initialize Telegram UI preferences
        self.prefs = TelegramPrefs(state_dir=self.state_dir)

        # Initialize TelegramAlerts if credentials provided
        if enabled and bot_token and chat_id:
            try:
                self.telegram = TelegramAlerts(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    enabled=True,
                )
                logger.info(
                    f"MarketAgentTelegramNotifier initialized successfully: "
                    f"enabled={self.enabled}, telegram_instance={self.telegram is not None}"
                )
            except Exception as e:
                logger.error(
                    f"❌ Could not initialize TelegramAlerts: {e}. "
                    f"Signal messages will NOT be sent to Telegram.",
                    exc_info=True
                )
                self.telegram = None
                self.enabled = False
        elif enabled:
            logger.error(
                f"❌ Telegram enabled but credentials missing: "
                f"bot_token={'present' if bot_token else 'MISSING'}, "
                f"chat_id={'present' if chat_id else 'MISSING'}. "
                f"Signal messages will NOT be sent to Telegram."
            )
            self.enabled = False
        else:
            logger.info("Telegram notifications disabled (enabled=False)")
        
        # Initialize chart generator if available
        if CHART_GENERATOR_AVAILABLE and enabled:
            try:
                self.chart_generator = ChartGenerator()
            except Exception as e:
                logger.warning(f"Could not initialize ChartGenerator: {e}")
                self.chart_generator = None

    def _get_prefs(self) -> TelegramPrefs:
        """Load latest Telegram preferences from disk (safe, small IO)."""
        try:
            return TelegramPrefs(state_dir=self.state_dir)
        except Exception:
            # Fall back to the instance prefs (best-effort).
            return self.prefs

    async def send_signal(self, signal: Dict, buffer_data: Optional[pd.DataFrame] = None) -> bool:
        """
        Send a trading signal to Telegram using professional desk alert format.
        
        Args:
            signal: Signal dictionary with regime, MTF, VWAP context
            buffer_data: Optional DataFrame with OHLCV data for chart generation
            
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            logger.warning("Telegram notifier is disabled - signal not sent")
            return False
        
        if not self.telegram:
            logger.error(
                "Telegram notifier not initialized - signal not sent. "
                "Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables."
            )
            return False

        try:
            # Use ultra-compact 3-line format for mobile-first glanceability
            message = self._format_ultra_compact_signal(signal)
            
            # Add drill-down buttons when command handler is running
            reply_markup = None
            signal_id = str(signal.get("signal_id") or "")
            if _is_command_handler_running() and signal_id:
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    keyboard = [
                        [
                            InlineKeyboardButton("🔍 Details", callback_data=f"signal_detail:{signal_id[:8]}"),
                            InlineKeyboardButton("🏠 Menu", callback_data="back"),
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                except ImportError:
                    pass
            
            success = await self.telegram.send_message(
                message,
                parse_mode="Markdown",
                dedupe=False,
                reply_markup=reply_markup,
            )

            # Optional: send entry chart with signal (preference-gated).
            # Fire-and-forget so chart rendering doesn't block the scan loop.
            try:
                prefs = self._get_prefs()
                auto_chart = bool(getattr(prefs, "auto_chart_on_signal", False))
            except Exception:
                auto_chart = False

            if (
                auto_chart
                and self.chart_generator is not None
                and buffer_data is not None
                and not buffer_data.empty
            ):
                asyncio.create_task(self._send_signal_entry_chart(signal, buffer_data))
            
            if success:
                return True

            # Fallback: send a minimal, guaranteed-short signal summary.
            fallback = self._format_minimal_signal(signal)
            fallback_ok = await self.telegram.send_message(
                fallback,
                parse_mode=None,
                dedupe=False,
            )
            return bool(fallback_ok)
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_signal")
            return False

    async def _send_signal_entry_chart(self, signal: Dict, buffer_data: pd.DataFrame) -> None:
        """Generate + send an entry chart for a signal (best-effort, non-blocking)."""
        if not self.enabled or not self.telegram:
            return
        if self.chart_generator is None:
            return
        if buffer_data is None or buffer_data.empty:
            return

        symbol = str(signal.get("symbol") or "MNQ")
        chart_path: Optional[Path] = None
        try:
            chart_path = await asyncio.to_thread(
                self.chart_generator.generate_entry_chart,
                signal=signal,
                buffer_data=buffer_data,
                symbol=symbol,
                timeframe=None,
            )
        except Exception as e:
            logger.warning(f"Could not generate entry chart: {e}")
            return

        if not chart_path or not chart_path.exists():
            return

        try:
            await self._send_photo(chart_path)
        except Exception as e:
            logger.warning(f"Could not send entry chart: {e}")
        finally:
            try:
                chart_path.unlink()
            except Exception:
                pass

    def _format_minimal_signal(self, signal: Dict) -> str:
        """Format a minimal signal message (plain text, bounded)."""
        symbol = str(signal.get("symbol") or "MNQ")
        sig_type = str(signal.get("type") or "unknown").replace("_", " ").title()
        direction = str(signal.get("direction") or "long").upper()
        try:
            entry = float(signal.get("entry_price") or 0.0)
        except Exception:
            entry = 0.0
        try:
            stop = float(signal.get("stop_loss") or 0.0)
        except Exception:
            stop = 0.0
        try:
            target = float(signal.get("take_profit") or 0.0)
        except Exception:
            target = 0.0
        try:
            conf = float(signal.get("confidence") or 0.0)
        except Exception:
            conf = 0.0

        sid = str(signal.get("signal_id") or "")
        sid_short = (sid[:16] + "…") if sid else ""

        # Check if this is a test signal (won't be saved to database/menu)
        is_test = signal.get("_is_test", False) or str(signal.get("reason", "")).lower().startswith("test")
        test_prefix = "🧪 [TEST - NOT TRACKED] " if is_test else ""

        # Keep this compact and robust to Markdown parsing issues.
        lines = [
            f"{test_prefix}SIGNAL {symbol} {direction} | {sig_type}",
            f"entry={entry:.2f} stop={stop:.2f} target={target:.2f} conf={conf:.0%}",
        ]
        reason = str(signal.get("reason") or "").strip()
        if reason:
            # Keep only first 2 lines and hard-cap length.
            parts = [p.strip() for p in reason.splitlines() if p.strip()]
            short = " | ".join(parts[:2])
            if len(short) > 220:
                short = short[:217] + "..."
            lines.append(f"reason={short}")
        if sid_short:
            lines.append(f"id={sid_short}")
        return "\n".join(lines)

    def _format_compact_signal(self, signal: Dict) -> str:
        """
        Format signal as a calm-minimal, decision-first push alert.
        
        Layout (calm-minimal spec):
        1. Header: Symbol, direction, type
        2. Trade Plan: Entry, Stop, TP, R:R
        3. Action cue: What to do next (immediately after plan)
        4. Confidence: Single line with tier
        5. Context: Single condensed line (regime + MTF) only if informative
        6. Signal ID: Short reference for Details drill-down
        
        Full context (reason, timestamps, detailed regime) lives in Details view.
        
        Args:
            signal: Signal dictionary with full context
            
        Returns:
            Formatted message string (under ~1000 chars for mobile, fast scan)
        """
        symbol = str(signal.get("symbol") or "MNQ")
        signal_type = str(signal.get("type") or "unknown").replace("_", " ").title()
        try:
            entry_price = float(signal.get("entry_price") or 0.0)
        except Exception:
            entry_price = 0.0
        try:
            stop_loss = float(signal.get("stop_loss") or 0.0)
        except Exception:
            stop_loss = 0.0
        try:
            take_profit = float(signal.get("take_profit") or 0.0)
        except Exception:
            take_profit = 0.0
        try:
            confidence = float(signal.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        signal_id = str(signal.get("signal_id") or "")

        # Check if this is a test signal (won't be saved to database/menu)
        is_test = signal.get("_is_test", False) or str(signal.get("reason", "")).lower().startswith("test")
        test_label = "🧪 *[TEST - NOT TRACKED]*\n" if is_test else ""

        # Use shared helpers for consistent formatting
        dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))
        conf_emoji, conf_tier = format_signal_confidence_tier(confidence)

        # Calculate risk/reward
        rr = 0.0
        if entry_price > 0 and stop_loss > 0 and take_profit > 0:
            if dir_label == "LONG":
                risk = entry_price - stop_loss
                reward = take_profit - entry_price
            else:
                risk = stop_loss - entry_price
                reward = entry_price - take_profit
            if risk > 0:
                rr = reward / risk

        # Build calm-minimal message: decision-first, action-cue-early
        message = f"{test_label}🎯 *{symbol} {dir_emoji} {dir_label}* | {signal_type}\n\n"

        # Trade Plan (always first, compact)
        if entry_price:
            message += f"*Entry:* ${entry_price:.2f}"
            if rr > 0:
                message += f"  •  R:R {rr:.1f}:1"
            message += "\n"
        if stop_loss:
            stop_dist = abs(entry_price - stop_loss) if entry_price else 0
            message += f"*Stop:* ${stop_loss:.2f} ({stop_dist:.1f} pts)\n"
        if take_profit:
            tp_dist = abs(take_profit - entry_price) if entry_price else 0
            message += f"*TP:* ${take_profit:.2f} ({tp_dist:.1f} pts)\n"
        
        # Size + Risk (compact single line, only if available)
        position_size = signal.get("position_size")
        risk_amount = signal.get("risk_amount")
        if position_size or risk_amount:
            size_risk_parts = []
            if position_size:
                size_risk_parts.append(f"{position_size} MNQ")
            if risk_amount:
                size_risk_parts.append(f"Risk: ${risk_amount:,.0f}")
            message += f"*Size:* {' • '.join(size_risk_parts)}\n"

        # Action cue (immediately after plan - what to do next)
        status = str(signal.get("status") or "generated")
        direction = str(signal.get("direction") or "long")
        action_cue = format_signal_action_cue(status, direction)
        if action_cue:
            message += f"\n{action_cue}\n"

        # Confidence (single line)
        message += f"\n{conf_emoji} {confidence:.0%} confidence ({conf_tier})\n"

        # Learning / policy (compact, always safe to omit)
        policy = signal.get("_policy")
        if isinstance(policy, dict) and policy.get("signal_type"):
            try:
                mode = str(policy.get("mode") or "shadow").lower()
                mode_emoji = "👁️" if mode == "shadow" else "🔥"
                exec_emoji = "✅" if bool(policy.get("execute")) else "⏭️"
                sample_count = int(policy.get("sample_count") or 0)
                obs_wr = policy.get("observed_win_rate")
                score = policy.get("sampled_score")

                parts = [f"{mode_emoji} {mode}", f"{exec_emoji}"]
                if obs_wr is not None and sample_count > 0:
                    parts.append(f"obs {float(obs_wr) * 100:.0f}% (n={sample_count})")
                elif sample_count > 0:
                    parts.append(f"n={sample_count}")
                if score is not None:
                    parts.append(f"score {float(score):.2f}")

                message += f"🧠 Policy: {' • '.join(parts)}\n"
            except Exception:
                pass

        # Opportunity tier (A-tier actionable vs B-tier explore)
        opp_tier = str(signal.get("_opportunity_tier") or "").strip().upper()
        if opp_tier in ("A", "B"):
            try:
                label = "Actionable" if opp_tier == "A" else "Explore"
                tier_emoji = "✅" if opp_tier == "A" else "⚗️"
                extra = ""
                reason = str(signal.get("_opportunity_reason") or "").strip()
                if opp_tier == "B" and reason:
                    # Keep this short to preserve calm-minimal alerts
                    extra = f" ({reason[:60]}{'…' if len(reason) > 60 else ''})"
                message += f"{tier_emoji} Tier: `{opp_tier}` ({label}){extra}\n"
            except Exception:
                pass

        # Context: condensed single line (regime + MTF) only if both informative
        regime = signal.get("regime", {}) or {}
        mtf = signal.get("mtf_analysis", {}) or {}
        context_parts = []
        
        # Session (Asia/London/NY) - critical for 24h futures operators
        if regime.get("session"):
            r_session = str(regime.get("session", "")).replace("_", " ").title()
            context_parts.append(r_session)

        if regime.get("regime"):
            r_regime = str(regime.get("regime", "")).replace("_", " ").title()
            context_parts.append(r_regime)

        # Volatility label when informative
        vol = str(regime.get("volatility") or "").lower()
        if vol and vol not in ("unknown", "normal"):
            context_parts.append(f"{vol.title()} vol")
        
        alignment = mtf.get("alignment")
        if alignment:
            mtf_emoji = "✅" if alignment == "aligned" else "⚠️" if alignment == "partial" else "❌"
            context_parts.append(f"{mtf_emoji} MTF")
        
        if context_parts:
            message += f"🧭 {' • '.join(context_parts)}\n"

        # Signal ID for cross-referencing (compact footer)
        # Keep this only when the command handler is NOT running (no buttons available).
        if signal_id and not _is_command_handler_running():
            message += f"\n`{signal_id[:12]}`"

        return message

    def _format_ultra_compact_signal(self, signal: Dict) -> str:
        """
        Format signal as ultra-compact 3-line notification.
        
        Layout (mobile-first, glanceable):
        Line 1: DIRECTION SYMBOL @ PRICE
        Line 2: SL | TP | R:R
        Line 3: Confidence | Session
        
        Full details accessible via drill-down button.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Formatted 3-line message string
        """
        symbol = str(signal.get("symbol") or "MNQ")
        try:
            entry_price = float(signal.get("entry_price") or 0.0)
        except Exception:
            entry_price = 0.0
        try:
            stop_loss = float(signal.get("stop_loss") or 0.0)
        except Exception:
            stop_loss = 0.0
        try:
            take_profit = float(signal.get("take_profit") or 0.0)
        except Exception:
            take_profit = 0.0
        try:
            confidence = float(signal.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0

        # Direction
        dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))
        
        # Calculate R:R
        rr_str = ""
        if entry_price > 0 and stop_loss > 0 and take_profit > 0:
            if dir_label == "LONG":
                risk = entry_price - stop_loss
                reward = take_profit - entry_price
            else:
                risk = stop_loss - entry_price
                reward = entry_price - take_profit
            if risk > 0:
                rr = reward / risk
                rr_str = f"{rr:.1f}R"

        # Confidence tier
        conf_emoji, conf_tier = format_signal_confidence_tier(confidence)
        
        # Session from regime
        regime = signal.get("regime", {}) or {}
        session = str(regime.get("session", "")).replace("_", " ").title() if regime.get("session") else ""

        # Build compact message
        lines = []
        
        # Line 1: Direction + Symbol @ Price
        lines.append(f"{dir_emoji} *{dir_label} {symbol}* @ ${entry_price:,.2f}")
        
        # Line 2: SL | TP | R:R
        sl_str = f"SL ${stop_loss:,.2f}" if stop_loss else ""
        tp_str = f"TP ${take_profit:,.2f}" if take_profit else ""
        line2_parts = [p for p in [sl_str, tp_str, rr_str] if p]
        lines.append(" | ".join(line2_parts))
        
        # Line 3: Confidence | Session
        line3_parts = [f"{conf_emoji} {confidence:.0%} {conf_tier}"]
        if session:
            line3_parts.append(session)
        lines.append(" | ".join(line3_parts))

        return "\n".join(lines)
    
    async def _send_photo(
        self,
        photo_path: Path,
        caption: Optional[str] = None,
        reply_markup=None,
    ) -> bool:
        """Send photo to Telegram with optional inline buttons."""
        if not self.enabled or not self.telegram or not self.telegram.bot:
            return False
        
        try:
            with open(photo_path, 'rb') as photo:
                await self.telegram.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode="Markdown" if caption else None,
                    reply_markup=reply_markup,
                )
            return True
        except Exception as e:
            logger.warning(f"Error sending photo: {e}")
            return False

    async def _send_post_chart_nav(self) -> None:
        """
        Send a follow-up navigation message after a chart image.
        
        Provides Menu + Signals & Trades buttons so the user can navigate
        from below the chart without scrolling up.
        """
        if not _is_command_handler_running() or not self.telegram:
            return
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🏠 Menu", callback_data=callback_menu(MENU_MAIN)),
                    InlineKeyboardButton("🎯 Signals & Trades", callback_data=callback_menu(MENU_SIGNALS)),
                ],
            ])
            # Keep the follow-up message minimal; buttons provide the actions.
            await self.telegram.send_message("Menu", parse_mode=None, reply_markup=keyboard, dedupe=False)
        except Exception as e:
            logger.debug(f"Could not send post-chart nav: {e}")

    async def send_dashboard_chart(
        self,
        chart_path: Path,
        symbol: str = "MNQ",
        timeframe: str = "5m",
        range_label: str | None = None,
        current_hours: float | None = None,
    ) -> bool:
        """
        Send dashboard chart to Telegram with minimal caption and timeframe toggle buttons.
        
        Args:
            chart_path: Path to the generated chart image
            symbol: Symbol for caption
            timeframe: Timeframe for caption
            range_label: Optional range label (e.g., "24h")
            current_hours: Current lookback hours (for highlighting active toggle)
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False
        
        if not chart_path or not chart_path.exists():
            logger.warning("Dashboard chart path does not exist")
            return False
        
        try:
            # Minimal caption (dashboard text message already has full details)
            if range_label:
                caption = f"📊 *{symbol}* {range_label} ({timeframe})"
            else:
                caption = f"📊 *{symbol}* ({timeframe})"
            
            # Build navigation buttons directly on chart (no separate nav message)
            reply_markup = None
            if _is_command_handler_running():
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    
                    # Single row with Menu navigation (keep dashboards calm-minimal)
                    keyboard = [
                        [
                            InlineKeyboardButton("🏠 Menu", callback_data=callback_menu(MENU_MAIN)),
                        ],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                except Exception as e:
                    logger.debug(f"Could not build chart nav buttons: {e}")
                    reply_markup = None
            
            success = await self._send_photo(chart_path, caption=caption, reply_markup=reply_markup)
            
            if success:
                logger.debug(f"Dashboard chart sent to Telegram: {chart_path}")
            else:
                logger.warning("Failed to send dashboard chart to Telegram")
            
            return success
        except Exception as e:
            logger.error(f"Error sending dashboard chart: {e}", exc_info=True)
            return False

    def _format_professional_signal(self, signal: Dict) -> str:
        """
        Format signal as professional desk alert.
        
        Args:
            signal: Signal dictionary with full context
            
        Returns:
            Formatted message string
        """
        symbol = signal.get("symbol", "MNQ")  # Default to MNQ (micro Nasdaq)
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

        # Build message (mobile-friendly: no long separators)
        message = f"🎯 *{symbol} {direction} | {signal_type}*\n\n"

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
        
        # Order book context (Level 2 data)
        order_book = signal.get("order_book", {})
        if order_book:
            imbalance = order_book.get("imbalance", 0.0)
            bid_depth = order_book.get("bid_depth", 0)
            ask_depth = order_book.get("ask_depth", 0)
            data_level = order_book.get("data_level", "unknown")
            
            # Format imbalance with emoji
            if imbalance > 0.2:
                imbalance_emoji = "🟢"
                imbalance_text = f"Strong Bid Pressure ({imbalance:+.2f})"
            elif imbalance > 0.1:
                imbalance_emoji = "🟡"
                imbalance_text = f"Moderate Bid Pressure ({imbalance:+.2f})"
            elif imbalance < -0.2:
                imbalance_emoji = "🔴"
                imbalance_text = f"Strong Ask Pressure ({imbalance:+.2f})"
            elif imbalance < -0.1:
                imbalance_emoji = "🟠"
                imbalance_text = f"Moderate Ask Pressure ({imbalance:+.2f})"
            else:
                imbalance_emoji = "⚪"
                imbalance_text = f"Balanced ({imbalance:+.2f})"
            
            # Data level indicator
            if data_level == "level2":
                level_indicator = "📊 L2"
            elif data_level == "level1":
                level_indicator = "📈 L1"
            else:
                level_indicator = "📉 Hist"
            
            message += f"*ORDER BOOK:* {level_indicator} {imbalance_emoji} {imbalance_text}\n"
            if bid_depth > 0 or ask_depth > 0:
                message += f"  Bid Depth: {bid_depth:,} | Ask Depth: {ask_depth:,}\n"
        
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
        
        # Order book alignment context (if Level 2 available)
        order_book = signal.get("order_book", {})
        if order_book and order_book.get("imbalance") is not None:
            imbalance = order_book.get("imbalance", 0.0)
            signal_direction_lower = direction.lower()
            
            # Check if order book aligns with signal
            if signal_direction_lower == "long":
                if imbalance > 0.15:
                    message += f"• ✅ Order Book: Aligned (bid pressure supports long)\n"
                elif imbalance < -0.15:
                    message += f"• ⚠️ Order Book: Opposing (ask pressure against long)\n"
                else:
                    message += f"• ⚪ Order Book: Neutral\n"
            elif signal_direction_lower == "short":
                if imbalance < -0.15:
                    message += f"• ✅ Order Book: Aligned (ask pressure supports short)\n"
                elif imbalance > 0.15:
                    message += f"• ⚠️ Order Book: Opposing (bid pressure against short)\n"
                else:
                    message += f"• ⚪ Order Book: Neutral\n"

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

    async def send_entry_notification(
        self, 
        signal_id: str, 
        entry_price: float, 
        signal: Dict,
        buffer_data: Optional[pd.DataFrame] = None,
    ) -> bool:
        """
        Send trade entry notification to Telegram.
        
        Args:
            signal_id: Signal ID for tracking
            entry_price: Actual entry price
            signal: Original signal dictionary
            buffer_data: Optional DataFrame with OHLCV data for chart generation
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            symbol = signal.get("symbol", "MNQ")
            signal_type = signal.get("type", "unknown").replace("_", " ").title()
            stop_loss = float(signal.get("stop_loss", 0) or 0)
            take_profit = float(signal.get("take_profit", 0) or 0)
            
            # Use shared helpers
            dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))
            
            # Calculate risk/reward
            risk_reward = 0.0
            if entry_price > 0 and stop_loss > 0 and take_profit > 0:
                if dir_label == "LONG":
                    risk = entry_price - stop_loss
                    reward = take_profit - entry_price
                else:
                    risk = stop_loss - entry_price
                    reward = entry_price - take_profit
                if risk > 0:
                    risk_reward = reward / risk
            
            # Entry notification (compact, no redundant "Position ACTIVE" line)
            message = f"✅ *{symbol} {dir_emoji} {dir_label} ENTRY*\n\n"
            message += f"Entry: ${entry_price:.2f}"
            if risk_reward > 0:
                message += f" • R:R {risk_reward:.1f}:1"
            message += "\n"
            if stop_loss:
                stop_dist = abs(entry_price - stop_loss)
                message += f"Stop: ${stop_loss:.2f} ({stop_dist:.1f} pts)\n"
            if take_profit:
                tp_dist = abs(take_profit - entry_price)
                message += f"TP: ${take_profit:.2f} ({tp_dist:.1f} pts)\n"
            
            # Size + Risk (compact single line, only if available)
            position_size = signal.get("position_size")
            risk_amount = signal.get("risk_amount")
            if position_size or risk_amount:
                size_risk_parts = []
                if position_size:
                    size_risk_parts.append(f"{position_size} MNQ")
                if risk_amount:
                    size_risk_parts.append(f"Risk: ${risk_amount:,.0f}")
                message += f"Size: {' • '.join(size_risk_parts)}"
            
            # Build inline buttons (no chart, so include nav here)
            reply_markup = None
            if _is_command_handler_running():
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    keyboard = [
                        [
                            InlineKeyboardButton("ℹ️ Details", callback_data=callback_signal_detail(signal_id[:16])),
                            InlineKeyboardButton("🏠 Menu", callback_data=callback_menu(MENU_MAIN)),
                        ],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                except Exception:
                    reply_markup = None
            
            # Send message
            # Entry notifications are high-signal; never dedupe.
            success = await self.telegram.send_message(message, reply_markup=reply_markup, dedupe=False)
            
            # NOTE: Chart is intentionally skipped here to avoid duplicates.
            # The signal notification already sends a chart (when auto_chart is enabled).
            # Keeping entry notification text-only reduces Telegram clutter.
            
            return success
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_entry_notification")
            return False

    async def send_exit_notification(
        self,
        signal_id: str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        signal: Dict,
        hold_duration_minutes: Optional[float] = None,
        buffer_data: Optional[pd.DataFrame] = None,
    ) -> bool:
        """
        Send trade exit notification to Telegram with P&L.
        
        Args:
            signal_id: Signal ID for tracking
            exit_price: Exit price
            exit_reason: Reason for exit (stop_loss, take_profit, manual, etc.)
            pnl: Profit/loss amount
            signal: Original signal dictionary
            hold_duration_minutes: Hold duration in minutes (optional)
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            symbol = signal.get("symbol", "MNQ")
            signal_type = signal.get("type", "unknown").replace("_", " ").title()
            entry_price = float(signal.get("entry_price", 0) or 0)
            
            # Use shared helpers
            dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))
            is_win = pnl > 0
            status_emoji, status_label = format_signal_status("exited", is_win)
            pnl_emoji, pnl_str = format_pnl(pnl)
            
            # Format exit reason
            exit_reason_map = {
                "stop_loss": "Stop Loss",
                "take_profit": "Take Profit",
                "manual": "Manual Exit",
                "expired": "Expired",
            }
            exit_reason_display = exit_reason_map.get(exit_reason.lower(), exit_reason.title())
            
            # Exit notification (compact, P&L first)
            message = f"{status_emoji} *{symbol} {dir_emoji} {dir_label} EXIT*\n\n"
            
            # P&L + duration
            message += f"{pnl_emoji} {pnl_str}"
            if hold_duration_minutes is not None:
                hold_hours = int(hold_duration_minutes // 60)
                hold_mins = int(hold_duration_minutes % 60)
                if hold_hours > 0:
                    message += f" • {hold_hours}h {hold_mins}m"
                else:
                    message += f" • {hold_mins}m"
            message += "\n"
            
            # Price movement
            price_change = exit_price - entry_price if entry_price else 0
            pct_change = (price_change / entry_price * 100) if entry_price > 0 else 0
            message += f"${entry_price:.2f} → ${exit_price:.2f} ({price_change:+.1f} / {pct_change:+.1f}%)\n"
            
            # Exit reason
            exit_icons = {
                "stop_loss": "🛑",
                "take_profit": "🎯",
                "manual": "👤",
                "expired": "⏰",
                "trailing_stop": "📉",
            }
            reason_icon = exit_icons.get(exit_reason.lower(), "ℹ️")
            message += f"{reason_icon} {exit_reason_display}"
            
            handler_running = _is_command_handler_running()
            
            # Build inline buttons (consistent with entry notification)
            reply_markup = None
            if handler_running:
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    keyboard = [
                        [
                            InlineKeyboardButton("ℹ️ Details", callback_data=callback_signal_detail(signal_id[:16])),
                            InlineKeyboardButton("🏠 Menu", callback_data=callback_menu(MENU_MAIN)),
                        ],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                except Exception:
                    reply_markup = None
            
            # Send message
            # Exit notifications are high-signal; never dedupe.
            success = await self.telegram.send_message(message, reply_markup=reply_markup, dedupe=False)
            
            # Generate and send chart if available
            chart_path = None
            if self.chart_generator and buffer_data is not None and not buffer_data.empty:
                try:
                    chart_path = self.chart_generator.generate_exit_chart(
                        signal, exit_price, exit_reason, pnl, buffer_data, symbol
                    )
                except Exception as e:
                    logger.warning(f"Could not generate exit chart: {e}")
            
            if chart_path and chart_path.exists():
                try:
                    await self._send_photo(chart_path)
                    try:
                        chart_path.unlink()
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"Could not send exit chart: {e}")
            
            return success
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_exit_notification")
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
            # send_message already has retry logic, don't add nested retries
            return await self.telegram.send_message(message)
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
        symbol = signal.get("symbol", "MNQ")  # Default to MNQ (micro Nasdaq)
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
            ErrorHandler.handle_telegram_error(e, "send_daily_summary")
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
            message = f"📊 *NQ Agent Status*\n\n"

            # Service and market status
            status_emoji = "🟢" if status.get("running") else "🔴"
            pause_status = " ⏸️ PAUSED" if status.get("paused") else ""
            uptime_str = ""
            if "uptime" in status and status["uptime"]:
                uptime_str = f" ({_format_uptime(status['uptime'])})"

            # FuturesMarketOpen: CME ETH + maintenance break semantics (operator/data-quality relevant)
            futures_market_open = status.get("futures_market_open")
            if futures_market_open is None:
                try:
                    futures_market_open = bool(get_market_hours().is_market_open())
                except Exception:
                    futures_market_open = None
            futures_emoji = "🟢" if futures_market_open is True else "🔴" if futures_market_open is False else "⚪"
            futures_text = "OPEN" if futures_market_open is True else "CLOSED" if futures_market_open is False else "UNKNOWN"

            # StrategySessionOpen: strategy trading window (09:30–16:00 ET) for signal generation
            strategy_session_open = status.get("strategy_session_open")
            strat_emoji = "🟢" if strategy_session_open is True else "🔴" if strategy_session_open is False else "⚪"
            strat_text = "OPEN" if strategy_session_open is True else "CLOSED" if strategy_session_open is False else "UNKNOWN"

            message += f"{status_emoji} *Service:* RUNNING{pause_status}{uptime_str}\n"
            message += f"{futures_emoji} *FuturesMarketOpen:* {futures_text}\n"
            message += f"{strat_emoji} *StrategySessionOpen:* {strat_text}\n"

            # Connection status (only show if issues)
            connection_status = status.get('connection_status', 'unknown')
            connection_failures = status.get('connection_failures', 0)
            if connection_status == 'disconnected' or connection_failures > 0:
                conn_emoji = "🔴" if connection_status == 'disconnected' else "🟡"
                message += f"{conn_emoji} *Connection:* {connection_status.upper()}"
                if connection_failures > 0:
                    message += f" ({connection_failures} failures)"
                message += "\n"

            # Activity section (compact single line, using standardized "scans" terminology)
            scans_total = int(status.get("cycle_count", 0) or 0)
            scans_session = status.get("cycle_count_session")
            try:
                scans_session = int(scans_session) if scans_session is not None else None
            except Exception:
                scans_session = None

            errors = int(status.get("error_count", 0) or 0)

            buffer = int(status.get("buffer_size", 0) or 0)
            buffer_target = status.get("buffer_size_target")
            try:
                buffer_target = int(buffer_target) if buffer_target is not None else None
            except Exception:
                buffer_target = None

            scans_label = f"{scans_session:,} {LABEL_SCANS} (session) / {scans_total:,} (total)" if scans_session is not None else f"{scans_total:,} {LABEL_SCANS}"
            buffer_label = f"{buffer}/{buffer_target} bars (rolling)" if buffer_target is not None else f"{buffer} bars (rolling)"
            message += f"📊 *Activity:* {scans_label} • {buffer_label} • {errors} errors\n"

            # Signal delivery clarity: generated vs sent vs failed
            signals_generated = int(status.get("signal_count", 0) or 0)
            signals_sent = int(status.get("signals_sent", 0) or 0)
            signals_failed = int(status.get("signals_send_failures", 0) or 0)
            message += f"🔔 *Signals:* {signals_generated} generated • {signals_sent} sent • {signals_failed} failed\n"

            last_err = status.get("last_signal_send_error")
            if last_err:
                # Keep it short for mobile.
                msg_err = str(last_err)
                if len(msg_err) > 140:
                    msg_err = msg_err[:140] + "…"
                message += f"⚠️ *Last send error:* {msg_err}\n"
            
            # Data quality section (compact)
            latest_bar = status.get('latest_bar')
            if latest_bar:
                data_level = latest_bar.get('_data_level', 'unknown')
                if data_level == 'level2':
                    data_emoji = "📊"
                    data_text = "Level 2"
                    imbalance = latest_bar.get('imbalance', 0.0)
                    if imbalance is not None:
                        imbalance_pct = imbalance * 100
                        if imbalance > 0.1:
                            data_text += f" • 🟢 Bid {imbalance_pct:+.1f}%"
                        elif imbalance < -0.1:
                            data_text += f" • 🔴 Ask {imbalance_pct:+.1f}%"
                        else:
                            data_text += f" • ⚪ Balanced"
                    message += f"{data_emoji} *Data:* {data_text}\n"
                elif data_level == 'level1':
                    message += f"📈 *Data:* Level 1\n"
                else:
                    # Check if historical data is ETH (Extended Trading Hours) which includes all sessions
                    is_eth = latest_bar.get('_historical_eth', False)
                    data_emoji = "📊"
                    
                    # Calculate data age if timestamp is available
                    data_age_minutes = None
                    if 'timestamp' in latest_bar and latest_bar['timestamp']:
                        try:
                            from datetime import datetime, timezone
                            bar_time = parse_utc_timestamp(latest_bar['timestamp'])
                            if bar_time:
                                age_delta = datetime.now(timezone.utc) - bar_time
                                data_age_minutes = age_delta.total_seconds() / 60
                        except Exception:
                            pass
                    
                    if is_eth:
                        if data_age_minutes is not None and data_age_minutes > 10:
                            data_text = f"Delayed (ETH - {data_age_minutes:.0f}m)"
                            data_emoji = "📉"
                        else:
                            data_text = "Live (ETH)"
                    else:
                        if data_age_minutes is not None and data_age_minutes > 10:
                            data_text = f"Delayed ({data_age_minutes:.0f}m)"
                        else:
                            data_text = "Live"
                    message += f"{data_emoji} *Data:* {data_text}\n"

            # Performance section (compact)
            performance = status.get("performance", {})
            if performance:
                exited = performance.get("exited_signals", 0)
                if exited > 0:
                    wins = performance.get('wins', 0)
                    losses = performance.get('losses', 0)
                    win_rate = performance.get('win_rate', 0) * 100
                    total_pnl = performance.get('total_pnl', 0)
                    avg_pnl = performance.get('avg_pnl', 0)

                    message += f"📈 *Performance (7d):* {wins}W/{losses}L • {_format_percentage(win_rate)} WR • {_format_currency(total_pnl)} • {_format_currency(avg_pnl)} avg\n"
                else:
                    message += f"📈 *Performance (7d):* No completed trades yet\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_enhanced_status")
            return False

    async def send_heartbeat(self, status: Dict) -> bool:
        """
        Send periodic heartbeat message.
        
        NOTE: This is now superseded by send_dashboard() for periodic updates.
        Kept for backward compatibility but heartbeat_interval is set very high.
        
        Args:
            status: Status dictionary with service information
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            futures_market_open = status.get("futures_market_open")
            if futures_market_open is None:
                try:
                    futures_market_open = bool(get_market_hours().is_market_open())
                except Exception:
                    futures_market_open = None

            strategy_session_open = status.get("strategy_session_open")

            # Ultra-compact heartbeat: Price, Market status, Activity summary
            latest_price = status.get('latest_price')
            current_time = status.get('current_time')
            symbol = status.get('symbol', 'NQ')
            
            # Format time (compact)
            time_str = ""
            if current_time:
                try:
                    from datetime import datetime, timezone as tz
                    import pytz
                    if isinstance(current_time, str):
                        current_time = parse_utc_timestamp(current_time)
                    if current_time.tzinfo is None:
                        current_time = current_time.replace(tzinfo=tz.utc)
                    et_tz = pytz.timezone('US/Eastern')
                    et_time = current_time.astimezone(et_tz)
                    time_str = et_time.strftime("%I:%M %p ET")
                except Exception:
                    try:
                        if hasattr(current_time, 'strftime'):
                            time_str = current_time.strftime("%H:%M UTC")
                    except:
                        pass
            
            # Build compact message
            futures_emoji = "🟢" if futures_market_open is True else "🔴" if futures_market_open is False else "⚪"
            futures_text = "OPEN" if futures_market_open is True else "CLOSED" if futures_market_open is False else "UNKNOWN"
            strat_emoji = "🟢" if strategy_session_open is True else "🔴" if strategy_session_open is False else "⚪"
            strat_text = "OPEN" if strategy_session_open is True else "CLOSED" if strategy_session_open is False else "UNKNOWN"
            message = f"💓 *Heartbeat* {time_str}\n\n"
            
            if latest_price:
                message += f"💰 ${latest_price:,.2f} ({symbol})\n"
            else:
                message += f"📊 *Symbol:* {symbol}\n"

            message += f"{futures_emoji} *FuturesMarketOpen:* {futures_text}  •  {strat_emoji} *StrategySessionOpen:* {strat_text}\n"

            # Activity summary (compact single line)
            scans_total = int(status.get("cycle_count", 0) or 0)
            scans_session = status.get("cycle_count_session")
            try:
                scans_session = int(scans_session) if scans_session is not None else None
            except Exception:
                scans_session = None

            signals_generated = int(status.get("signal_count", 0) or 0)
            signals_sent = int(status.get("signals_sent", 0) or 0)
            signals_failed = int(status.get("signals_send_failures", 0) or 0)

            errors = int(status.get("error_count", 0) or 0)

            buffer = int(status.get("buffer_size", 0) or 0)
            buffer_target = status.get("buffer_size_target")
            try:
                buffer_target = int(buffer_target) if buffer_target is not None else None
            except Exception:
                buffer_target = None

            scans_part = f"{scans_session:,}/{scans_total:,} {LABEL_SCANS}" if scans_session is not None else f"{scans_total:,} {LABEL_SCANS}"
            buf_part = f"{buffer}/{buffer_target} bars" if buffer_target is not None else f"{buffer} bars"
            message += f"📊 {scans_part} • {signals_generated} gen / {signals_sent} sent / {signals_failed} fail • {buf_part} • {errors} errors\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_heartbeat")
            return False

    async def send_dashboard(self, status: Dict) -> bool:
        """
        Send consolidated dashboard message (replaces Status + Heartbeat).
        
        Uses the unified Home Card layout for consistency with interactive /status.
        Adds push-specific enhancements: sparkline, MTF snapshot.
        
        Args:
            status: Status dictionary with service information
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            from pearlalgo.utils.sparkline import (
                generate_sparkline,
                format_price_change,
                format_mtf_snapshot,
            )
        except ImportError:
            # Fallback if sparkline module not available
            generate_sparkline = lambda x, w=20: "─" * w
            format_price_change = lambda c, p: f"{((c-p)/p*100) if p else 0:.2f}%"
            format_mtf_snapshot = lambda t, **kw: "N/A"

        try:
            # Extract values from status dict
            symbol = status.get('symbol', 'MNQ')
            current_time = status.get('current_time') or datetime.now(timezone.utc)
            
            # Format ET time
            time_str = ""
            try:
                import pytz
                if isinstance(current_time, str):
                    current_time = parse_utc_timestamp(current_time)
                if current_time.tzinfo is None:
                    current_time = current_time.replace(tzinfo=timezone.utc)
                et_tz = pytz.timezone('US/Eastern')
                et_time = current_time.astimezone(et_tz)
                time_str = et_time.strftime("%I:%M %p ET")
            except Exception:
                time_str = current_time.strftime("%H:%M UTC") if hasattr(current_time, 'strftime') else ""
            
            # Extract all metrics
            latest_price = status.get('latest_price')
            paused = status.get("paused", False)
            pause_reason = status.get("pause_reason")
            
            # Gates
            futures_market_open = status.get("futures_market_open")
            if futures_market_open is None:
                try:
                    futures_market_open = bool(get_market_hours().is_market_open())
                except Exception:
                    futures_market_open = None
            strategy_session_open = status.get("strategy_session_open")
            
            # Activity metrics
            cycles_total = int(status.get("cycle_count", 0) or 0)
            cycles_session = status.get("cycle_count_session")
            try:
                cycles_session = int(cycles_session) if cycles_session is not None else None
            except Exception:
                cycles_session = None
            
            signals_generated = int(status.get("signal_count", 0) or 0)
            try:
                signals_sent = int(status.get("signals_sent", 0) or 0)
            except Exception:
                signals_sent = 0
            
            errors = int(status.get("error_count", 0) or 0)
            buffer_size = int(status.get("buffer_size", 0) or 0)
            buffer_target = status.get("buffer_size_target")
            try:
                buffer_target = int(buffer_target) if buffer_target is not None else None
            except Exception:
                buffer_target = None
            
            # Performance
            performance = status.get("performance", {})
            
            # Price change and sparkline
            price_change_str = None
            sparkline = None
            recent_closes = status.get("recent_closes", [])
            if recent_closes and len(recent_closes) >= 2 and latest_price:
                first_close = recent_closes[0]
                price_change_str = format_price_change(latest_price, first_close)
            if recent_closes and len(recent_closes) >= 5:
                sparkline = generate_sparkline(recent_closes, width=20)
            
            # Build Home Card using unified format
            # Note: Push dashboard context cannot directly measure gateway status.
            # Mark gateway_unknown=True to avoid false confidence in UI.
            # Agent is running if sending dashboards; gateway status is inferred from data flow.
            
            # Extract signal send failures from status for error cue
            signal_send_failures = 0
            try:
                signal_send_failures = int(status.get("signals_send_failures", 0) or 0)
            except Exception:
                signal_send_failures = 0
            
            # Extract quiet_reason and signal_diagnostics for observability
            quiet_reason = status.get("quiet_reason")
            signal_diagnostics = status.get("signal_diagnostics")
            buy_sell_pressure = status.get("buy_sell_pressure")
            
            # Compute data age in minutes for v2 staleness callout
            data_age_minutes = None
            latest_bar = status.get('latest_bar')
            if latest_bar and 'timestamp' in latest_bar and latest_bar['timestamp']:
                try:
                    bar_time = parse_utc_timestamp(latest_bar['timestamp'])
                    if bar_time:
                        if bar_time.tzinfo is None:
                            bar_time = bar_time.replace(tzinfo=timezone.utc)
                        age_delta = datetime.now(timezone.utc) - bar_time
                        data_age_minutes = age_delta.total_seconds() / 60.0
                except Exception:
                    pass
            
            # Get stale threshold from status or use default
            data_stale_threshold_minutes = float(status.get("data_stale_threshold_minutes", 10.0))
            is_data_stale = data_age_minutes is not None and data_age_minutes > data_stale_threshold_minutes
            
            # Determine if we can infer gateway status from data flow.
            # If data is stale or buffer is empty, we can't be confident gateway is working.
            gateway_uncertain = is_data_stale or buffer_size < 1
            
            # Compute activity pulse from last_successful_cycle (same semantics as /activity)
            last_cycle_seconds = None
            last_successful_cycle = status.get("last_successful_cycle")
            if last_successful_cycle:
                try:
                    last_cycle_dt = parse_utc_timestamp(str(last_successful_cycle))
                    if last_cycle_dt:
                        if last_cycle_dt.tzinfo is None:
                            last_cycle_dt = last_cycle_dt.replace(tzinfo=timezone.utc)
                        last_cycle_seconds = (datetime.now(timezone.utc) - last_cycle_dt).total_seconds()
                except Exception:
                    pass
            
            # Get session times from config for config-driven messaging
            config_block = status.get("config", {})
            if isinstance(config_block, dict):
                session_start = config_block.get("start_time") or config_block.get("session_start_time")
                session_end = config_block.get("end_time") or config_block.get("session_end_time")
            else:
                session_start = None
                session_end = None

            # Telegram UI formatting options (optional)
            telegram_ui = status.get("telegram_ui", {})
            if not isinstance(telegram_ui, dict):
                telegram_ui = {}
            compact_metrics_enabled = bool(telegram_ui.get("compact_metrics_enabled", True))
            show_progress_bars = bool(telegram_ui.get("show_progress_bars", False))
            show_volume_metrics = bool(telegram_ui.get("show_volume_metrics", True))
            try:
                compact_metric_width = int(telegram_ui.get("compact_metric_width", 10) or 10)
            except Exception:
                compact_metric_width = 10
            
            # Extract data level from latest_bar for IBKR data quality visibility
            data_level = None
            if latest_bar and isinstance(latest_bar, dict):
                data_level = latest_bar.get('_data_level')
            
            message = format_home_card(
                symbol=symbol,
                time_str=time_str,
                agent_running=True,  # If sending dashboard, agent is running
                gateway_running=not gateway_uncertain,  # Infer from data flow health
                futures_market_open=futures_market_open,
                strategy_session_open=strategy_session_open,
                paused=paused,
                pause_reason=pause_reason,
                cycles_session=cycles_session,
                cycles_total=cycles_total,
                signals_generated=signals_generated,
                signals_sent=signals_sent,
                errors=errors,
                buffer_size=buffer_size,
                buffer_target=buffer_target,
                latest_price=latest_price,
                performance=performance,
                sparkline=sparkline,
                price_change_str=price_change_str,
                # v2 fields for enhanced confidence/clarity
                signal_send_failures=signal_send_failures,
                # Mark gateway as unknown when we can't infer status from data flow
                gateway_unknown=gateway_uncertain,
                # v4 fields for quiet reason and signal diagnostics
                quiet_reason=quiet_reason,
                signal_diagnostics=signal_diagnostics,
                buy_sell_pressure=buy_sell_pressure,
                buy_sell_pressure_raw=status.get("buy_sell_pressure_raw"),
                # v5 fields: active trades + unrealized PnL (push dashboards)
                active_trades_count=int(status.get("active_trades_count", 0) or 0),
                active_trades_unrealized_pnl=status.get("active_trades_unrealized_pnl"),
                active_trades_price_source=status.get("latest_price_source"),
                # v6 fields for data staleness
                data_age_minutes=data_age_minutes,
                data_stale_threshold_minutes=data_stale_threshold_minutes,
                # v7 field: activity pulse for push dashboards
                last_cycle_seconds=last_cycle_seconds,
                # v8 fields: config-driven session messaging
                session_start=session_start,
                session_end=session_end,
                # v9 field: IBKR data level indicator
                data_level=data_level,
                # v10 fields: execution status (make trading state obvious)
                # Extract from nested execution dict if present
                execution_enabled=(status.get("execution") or {}).get("enabled", False),
                execution_armed=(status.get("execution") or {}).get("armed", False),
                execution_mode=(status.get("execution") or {}).get("mode"),
                # Config-driven telegram UI formatting
                compact_metrics_enabled=compact_metrics_enabled,
                show_progress_bars=show_progress_bars,
                show_volume_metrics=show_volume_metrics,
                compact_metric_width=compact_metric_width,
            )

            # Optional: recent exits (compact transparency for push dashboards).
            try:
                recent_exits = status.get("recent_exits")
                if isinstance(recent_exits, list) and recent_exits:
                    message += "\n\n*Recent exits:*"
                    for t in recent_exits[:3]:
                        try:
                            pnl_val = float(t.get("pnl") or 0.0)
                        except Exception:
                            pnl_val = 0.0
                        pnl_emoji, pnl_str = format_pnl(pnl_val)
                        dir_emoji, dir_label = format_signal_direction(t.get("direction", "long"))
                        sig_type = safe_label(str(t.get("type") or "unknown"))
                        reason = safe_label(str(t.get("exit_reason") or "")).strip()
                        # Keep each line compact for mobile.
                        line = f"\n{pnl_emoji} *{pnl_str}* • {dir_emoji} {dir_label} • {sig_type}"
                        if reason:
                            line += f" • {reason}"
                        message += line
            except Exception:
                pass
            
            # Add MTF snapshot (push-specific enhancement)
            # V2 spec: Suppress MTF when data is stale to avoid misleading derived context
            mtf_trends = status.get("mtf_trends", {})
            if mtf_trends and not is_data_stale:
                try:
                    mtf_str = format_mtf_snapshot(mtf_trends, timeframes=["5m", "15m", "1h", "4h", "1D"])
                    if mtf_str and mtf_str != "N/A":
                        message += f"\n*MTF:* {mtf_str}"
                except Exception:
                    pass
            
            # Build navigation buttons (always on when the command handler is running).
            reply_markup = None
            handler_running = _is_command_handler_running()
            if handler_running:
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                    keyboard = [
                        [
                            InlineKeyboardButton("🏠 Menu", callback_data=callback_menu(MENU_MAIN)),
                            InlineKeyboardButton("🎯 Signals & Trades", callback_data=callback_menu(MENU_SIGNALS)),
                        ],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                except Exception as e:
                    logger.debug(f"Could not build dashboard buttons: {e}")
                    reply_markup = None

            # Persist last dashboard time (used by UI Doctor).
            try:
                prefs_live = self._get_prefs()
            except Exception:
                prefs_live = self.prefs

            edit_in_place = bool(getattr(prefs_live, "dashboard_edit_in_place", False)) if prefs_live else False
            message_id = None
            try:
                message_id = prefs_live.get("dashboard_message_id") if prefs_live else None
            except Exception:
                message_id = None

            sent_at = datetime.now(timezone.utc).isoformat()

            # If pinned mode is enabled, try to edit the existing message first.
            if edit_in_place and message_id and getattr(self.telegram, "bot", None) is not None:
                try:
                    mid = int(message_id)
                    try:
                        await self.telegram.bot.edit_message_text(
                            chat_id=self.chat_id,
                            message_id=mid,
                            text=message,
                            parse_mode="Markdown",
                            reply_markup=reply_markup,
                        )
                    except Exception:
                        # Fallback to plain text if Markdown parsing fails.
                        await self.telegram.bot.edit_message_text(
                            chat_id=self.chat_id,
                            message_id=mid,
                            text=message,
                            parse_mode=None,
                            reply_markup=reply_markup,
                        )
                    try:
                        if prefs_live:
                            prefs_live.set("last_dashboard_sent_at", sent_at)
                    except Exception:
                        pass
                    return True
                except Exception:
                    # If edit fails (message deleted/too old), fall back to sending new.
                    try:
                        if prefs_live:
                            prefs_live.set("dashboard_message_id", None)
                    except Exception:
                        pass

            # Default: send a new dashboard message (store message_id if pinned mode is enabled).
            if getattr(self.telegram, "bot", None) is None:
                return False

            msg_obj = None
            try:
                msg_obj = await self.telegram.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode="Markdown",
                    reply_markup=reply_markup,
                )
            except Exception:
                msg_obj = await self.telegram.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode=None,
                    reply_markup=reply_markup,
                )

            try:
                if prefs_live:
                    prefs_live.set("last_dashboard_sent_at", sent_at)
                    if edit_in_place and msg_obj is not None and getattr(msg_obj, "message_id", None) is not None:
                        prefs_live.set("dashboard_message_id", int(msg_obj.message_id))
            except Exception:
                pass

            return msg_obj is not None
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_dashboard")
            return False

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
            is_recovery = alert_type == "recovery"
            
            # Non-critical alerts can be snoozed (except recovery and circuit_breaker)
            # Critical alerts are always sent regardless of snooze setting
            critical_types = {"recovery", "circuit_breaker"}
            is_critical = alert_type in critical_types
            
            # Reload prefs from disk so snooze set via Telegram UI is respected immediately.
            try:
                prefs = self._get_prefs()
            except Exception:
                prefs = self.prefs
            if not is_critical and prefs and prefs.snooze_noncritical_alerts:
                logger.info(f"Data quality alert '{alert_type}' suppressed (snoozed)")
                return True  # Return True to indicate "handled" (just suppressed)

            # Recovery messages should be positive + not labeled as risk warnings.
            if is_recovery:
                msg = "✅ *Recovery*\n\n"
                msg += f"{message}\n" if message else "Data quality recovered.\n"
                msg += "\n✅ Signal generation resumed\n"
                msg += "✅ Position monitoring active\n"
                msg += "\n*Status:* OK"
            else:
                # Risk warning format (mobile-friendly)
                msg = "⚠️ *Risk Warning*\n\n"

                # Add alert type with impact explanation
                if alert_type == "stale_data":
                    msg += "⏰ *Stale Data*\n"
                    msg += "\n*Impact:*\n"
                    msg += "• Signal generation paused\n"
                    msg += "• Positions still monitored\n"
                elif alert_type == "data_gap":
                    msg += "📉 *Data Gap*\n"
                    msg += "\n*Impact:*\n"
                    msg += "• Indicators may be inaccurate\n"
                    msg += "• Signal quality reduced\n"
                elif alert_type == "fetch_failure":
                    msg += "❌ *Fetch Failure*\n"
                    msg += "\n*Impact:*\n"
                    msg += "• No new data available\n"
                    msg += "• Using cached data if available\n"
                elif alert_type == "buffer_issue":
                    msg += "⚠️ *Buffer Issue*\n"
                    msg += "\n*Impact:*\n"
                    msg += "• Insufficient history for indicators\n"
                    msg += "• Signals may be delayed\n"
                else:
                    title_text = alert_type.replace('_', ' ').title()
                    msg += f"⚠️ *{title_text}*\n"

                # Add details
                msg += "\n*Details:*\n"
                if alert_type == "stale_data" and details and "age_minutes" in details:
                    age_val = details["age_minutes"]
                    msg += f"🕐 Age: {age_val:.1f} minutes\n"
                elif message and alert_type != "stale_data":
                    msg += f"{message}\n"

                if details:
                    if "consecutive_failures" in details:
                        msg += f"❌ Failures: {details['consecutive_failures']}\n"
                    if "connection_failures" in details:
                        msg += f"🔌 Connection: {details['connection_failures']} failures\n"
                    if "buffer_size" in details:
                        msg += f"📊 Buffer: {details['buffer_size']} bars\n"
                    if "severity" in details:
                        msg += f"🧭 Severity: {details['severity']}\n"
                    if "error_type" in details:
                        msg += f"⚠️ Type: {details['error_type']}\n"

                # Action guidance
                msg += "\n*What to do:*\n"
                if alert_type in ("stale_data", "fetch_failure", "data_gap"):
                    msg += "1. Check Gateway status\n"
                    msg += "2. Verify market is open\n"
                    msg += "3. Restart if needed\n"
                elif alert_type == "buffer_issue":
                    msg += "1. Wait for buffer to fill\n"
                    msg += "2. Check data connection\n"
                else:
                    if details and "suggestion" in details:
                        msg += f"💡 {details['suggestion']}\n"
                    else:
                        msg += "1. Check system status\n"
                        msg += "2. Review logs if issue persists\n"

                # Expected resolution
                if alert_type == "stale_data":
                    msg += "\n⏳ Usually resolves when market reopens\n"
                elif alert_type == "buffer_issue":
                    msg += "\n⏳ Buffer fills within 2-5 minutes\n"

                # Escape underscore in DATA_QUALITY to prevent Markdown italic parsing
                msg += "\n*Status:* DATA\\_QUALITY"

            # Tap-to-fix buttons (only if command handler is likely running)
            reply_markup = None
            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                from pathlib import Path
                import os

                project_root = Path(__file__).parent.parent.parent.parent
                pid_file = project_root / "logs" / "telegram_handler.pid"
                handler_running = False
                if pid_file.exists():
                    try:
                        pid = int(pid_file.read_text().strip())
                        os.kill(pid, 0)
                        handler_running = True
                    except Exception:
                        handler_running = False

                if handler_running:
                    keyboard = []
                    if is_recovery:
                        keyboard.append([
                            InlineKeyboardButton("🛡 Data Quality", callback_data=callback_action(ACTION_DATA_QUALITY)),
                            InlineKeyboardButton("🛡 Health", callback_data=callback_menu(MENU_STATUS)),
                        ])
                    else:
                        keyboard.append([
                            InlineKeyboardButton("🛡 Data Quality", callback_data=callback_action(ACTION_DATA_QUALITY)),
                            InlineKeyboardButton("🔁 Restart Agent", callback_data=callback_confirm("restart_agent")),
                        ])
                        if alert_type in ("stale_data", "fetch_failure", "data_gap"):
                            keyboard.append([
                                InlineKeyboardButton("🔁 Restart Gateway", callback_data=callback_confirm("restart_gateway")),
                                InlineKeyboardButton("🔌 Gateway Status", callback_data=callback_action(ACTION_GATEWAY_STATUS)),
                            ])
                        # Allow one-tap snooze for non-critical alerts (prevents alert fatigue).
                        if not is_critical:
                            keyboard.append([
                                InlineKeyboardButton(
                                    "🔕 Snooze 1h",
                                    callback_data=callback_action("toggle_pref", "snooze_noncritical_alerts"),
                                ),
                            ])

                    keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data=callback_menu(MENU_MAIN))])
                    reply_markup = InlineKeyboardMarkup(keyboard)
            except Exception:
                reply_markup = None

            # Send using send_message (includes retry + dedupe)
            await self.telegram.send_message(msg, reply_markup=reply_markup)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_data_quality_alert")
            return False

    async def send_startup_notification(self, config: Dict) -> bool:
        """
        Send service startup notification with configuration, current price, and time.
        
        Uses standardized terminology and aligns with Home Card layout.
        Avoids false confidence in timing claims.
        
        Args:
            config: Configuration dictionary (may include latest_price and current_time)
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            from datetime import datetime, timezone
            from pearlalgo.utils.telegram_alerts import (
                LABEL_FUTURES, LABEL_SESSION, GATE_OPEN, GATE_CLOSED, GATE_UNKNOWN
            )
            
            message = f"🚀 *NQ {LABEL_AGENT} Started*\n\n"

            # Show current price and time
            current_time = config.get('current_time')
            if not current_time:
                current_time = datetime.now(timezone.utc)
            if isinstance(current_time, str):
                # Parse if string
                try:
                    current_time = datetime.fromisoformat(current_time.replace('Z', '+00:00'))
                except:
                    current_time = datetime.now(timezone.utc)
            
            # Format time (ET for US market)
            try:
                import pytz
                et_tz = pytz.timezone('US/Eastern')
                if hasattr(current_time, 'astimezone'):
                    et_time = current_time.astimezone(et_tz)
                else:
                    # If timezone-naive, assume UTC
                    from datetime import timezone as tz
                    if current_time.tzinfo is None:
                        current_time = current_time.replace(tzinfo=tz.utc)
                    et_time = current_time.astimezone(et_tz)
                time_str = et_time.strftime("%I:%M:%S %p ET")
            except Exception:
                # Fallback to UTC if pytz not available or timezone conversion fails
                if hasattr(current_time, 'strftime'):
                    time_str = current_time.strftime("%H:%M:%S UTC")
                else:
                    time_str = str(current_time)
            
            latest_price = config.get('latest_price')
            symbol = config.get('symbol', 'NQ')
            
            if latest_price:
                message += f"💰 *Price:* ${latest_price:,.2f} ({symbol})\n"
            else:
                message += f"📊 *Symbol:* {symbol}\n"
            message += f"🕐 *Time:* {time_str}\n"

            # Compact config (single line)
            timeframe = config.get('timeframe', '1m')
            scan_interval = config.get('scan_interval', 60)
            message += f"⚙️ *Config:* {timeframe} timeframe, {scan_interval}s scan\n"

            # Market gates (using standardized terminology matching Home Card)
            futures_market_open = config.get("futures_market_open")
            if futures_market_open is None:
                try:
                    futures_market_open = bool(get_market_hours().is_market_open())
                except Exception:
                    futures_market_open = None
            strategy_session_open = config.get("strategy_session_open")

            # Use standardized gate status format (matches Home Card)
            message += format_gate_status(futures_market_open, strategy_session_open) + "\n"

            # What to expect (reduced false confidence in timing)
            # Get session times from config for config-driven messaging
            session_start = config.get("start_time")
            session_end = config.get("end_time")
            
            message += "\n*What's next:*\n"
            handler_running = _is_command_handler_running()
            if strategy_session_open is True:
                message += "• Scanning for signals when conditions align\n"
                if handler_running:
                    message += "• No guaranteed timing—use /start for live status\n"
                else:
                    message += "• No guaranteed timing—watch for dashboard updates\n"
            elif strategy_session_open is False:
                next_session = format_next_session_time(session_start, session_end)
                if session_start and session_end:
                    session_window = format_session_window(session_start, session_end)
                    message += f"• Session: {session_window}\n"
                message += f"• {next_session}\n"
                if handler_running:
                    message += "• Use /start for live status\n"
            else:
                message += "• Checking market conditions...\n"
            
            # Add inline text links that match the message style
            if handler_running:
                message += "\n💡 Quick access: /start"

            # Startup message does not require inline buttons.
            reply_markup = None
            await self.telegram.send_message(message, reply_markup=reply_markup)
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
            shutdown_reason = summary.get('shutdown_reason', 'Normal shutdown')
            
            # Header with reason (if abnormal)
            message = f"🛑 *Agent Stopped*\n"
            if shutdown_reason and shutdown_reason not in ("Normal shutdown", "Final cleanup"):
                reason_emoji = "⚠️" if "error" in shutdown_reason.lower() or "circuit" in shutdown_reason.lower() else "ℹ️"
                message += f"{reason_emoji} {safe_label(str(shutdown_reason))}\n"
            
            # Session stats (compact single-line style)
            uptime_h = summary.get('uptime_hours', 0)
            uptime_m = summary.get('uptime_minutes', 0)
            scans = summary.get('cycle_count', 0)
            signals = summary.get('signal_count', 0)
            errors = summary.get('error_count', 0)

            message += f"\n⏱ {uptime_h:.0f}h {uptime_m:.0f}m"
            message += f" • 🔄 {scans:,} scans"
            message += f" • 🔔 {signals} signals"
            if errors > 0:
                message += f" • ⚠️ {errors} errors"
            message += "\n"

            # Performance if available (compact)
            wins = summary.get('wins', 0)
            losses = summary.get('losses', 0)
            total_pnl = summary.get('total_pnl')

            if wins > 0 or losses > 0:
                win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
                pnl_str = ""
                if total_pnl is not None:
                    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                    pnl_str = f" • {pnl_emoji} {_format_currency(total_pnl)}"
                message += f"\n✅ {wins}W ❌ {losses}L ({win_rate:.0f}%){pnl_str}\n"
            elif total_pnl is not None:
                pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                message += f"\n{pnl_emoji} *P&L:* {_format_currency(total_pnl)}\n"

            # Restart hint
            message += f"\n💡 /start\\_agent"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_shutdown_notification")
            return False

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
            # Format message with clear explanation (escaped for markdown safety)
            message = f"🛑 *Circuit Breaker Activated*\n\n"
            message += f"*Reason:* {safe_label(str(reason))}\n"

            # What happened
            if details:
                message += "\n*What happened:*\n"
                if "consecutive_errors" in details:
                    message += f"• {details['consecutive_errors']} consecutive errors\n"
                if "connection_failures" in details:
                    message += f"• {details['connection_failures']} connection failures\n"
                if "error_type" in details:
                    message += f"• Error type: {details['error_type']}\n"
                if "action_taken" in details:
                    message += f"• Action: {details['action_taken']}\n"

            # What's safe
            message += "\n*What's safe:*\n"
            message += "✅ Existing positions are preserved\n"
            message += "✅ No new signals will be generated\n"
            message += "✅ System state is saved\n"

            # What to do
            message += "\n*What to do:*\n"
            message += "1. Check Gateway status\n"
            message += "2. Review error logs\n"
            message += "3. Restart agent when ready\n"

            message += "\n⚠️ *Manual restart required*"

            await self.telegram.notify_risk_warning(message, risk_status="CRITICAL")
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_circuit_breaker_alert")
            return False

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
            issue = safe_label(str(recovery_info.get('issue', 'Unknown')))
            message = f"✅ *Service Recovered*\n\n"
            message += f"*Issue:* {issue}\n"
            message += f"*Time:* {recovery_info.get('recovery_time_seconds', 0):.0f}s\n"
            message += f"*Status:* Normal operation\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_recovery_notification")
            return False

    async def send_error_summary(
        self,
        error_count: int,
        error_types: Optional[Dict[str, int]] = None,
        last_error: Optional[str] = None,
        time_window_minutes: int = 60,
    ) -> bool:
        """
        Send error summary notification.
        
        Args:
            error_count: Total number of errors in time window
            error_types: Dictionary of error type -> count
            last_error: Description of last error
            time_window_minutes: Time window for error summary
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            message = f"⚠️ *Error Summary ({time_window_minutes}m)*\n\n"
            message += f"*Total Errors:* {error_count}\n"

            if error_types:
                message += f"\n*By Type:*\n"
                for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
                    message += f"• {safe_label(str(error_type))}: {count}\n"

            if last_error:
                # Escape error message for markdown safety
                escaped_error = safe_label(str(last_error)[:200])
                message += f"\n*Last Error:*\n{escaped_error}\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_error_summary")
            return False

    async def send_price_alert(
        self,
        symbol: str,
        current_price: float,
        previous_price: float,
        price_change_pct: float,
        alert_type: str = "significant_move",
    ) -> bool:
        """
        Send price alert notification for significant price movements.
        
        Args:
            symbol: Trading symbol
            current_price: Current price
            previous_price: Previous price
            price_change_pct: Price change percentage
            alert_type: Type of alert (significant_move, level_reached, etc.)
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            direction = "📈" if price_change_pct > 0 else "📉"
            direction_text = "UP" if price_change_pct > 0 else "DOWN"
            
            message = f"{direction} *Price Alert: {symbol}*\n\n"
            message += f"*Price:* ${current_price:,.2f}\n"
            message += f"*Change:* {direction_text} {abs(price_change_pct):.2f}% (${abs(current_price - previous_price):,.2f})\n"
            message += f"*Previous:* ${previous_price:,.2f}\n"
            
            if alert_type == "significant_move":
                if abs(price_change_pct) > 1.0:
                    message += f"\n⚠️ Significant price movement detected\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_price_alert")
            return False

    async def send_connection_status_update(
        self,
        status: str,
        details: Optional[Dict] = None,
    ) -> bool:
        """
        Send detailed connection status update.
        
        Args:
            status: Connection status (connected, disconnected, reconnecting, etc.)
            details: Additional details (failures, last_attempt, etc.)
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            status_emoji_map = {
                "connected": "🟢",
                "disconnected": "🔴",
                "reconnecting": "🟡",
                "connection_lost": "🔴",
                "recovered": "✅",
            }
            emoji = status_emoji_map.get(status.lower(), "⚪")
            
            message = f"{emoji} *Connection Status: {status.upper()}*\n\n"

            if details:
                if "failures" in details:
                    message += f"*Failures:* {details['failures']}\n"
                if "last_attempt" in details:
                    message += f"*Last Attempt:* {details['last_attempt']}\n"
                if "recovery_time" in details:
                    message += f"*Recovery Time:* {details['recovery_time']:.1f}s\n"
                if "suggestion" in details:
                    message += f"\n*Suggestion:* {details['suggestion']}\n"

            await self.telegram.send_message(message)
            return True
        except Exception as e:
            ErrorHandler.handle_telegram_error(e, "send_connection_status_update")
            return False
