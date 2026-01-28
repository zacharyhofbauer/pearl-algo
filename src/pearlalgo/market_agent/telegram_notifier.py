"""
Market Agent Telegram Notifier

Sends signals and status updates to Telegram.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from pearlalgo.utils.logger import logger

from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.market_hours import get_market_hours
from pearlalgo.utils.paths import ensure_state_dir, parse_utc_timestamp
from pearlalgo.utils.telegram_alerts import (
    TelegramAlerts,
    TelegramPrefs,
    _truncate_telegram_text,
    _format_uptime,
    _format_currency,
    _format_percentage,
    format_signal_status,
    format_signal_direction,
    format_signal_confidence_tier,
    format_pnl,
    safe_label,
    format_glanceable_card,
    # New UX improvement helpers
    format_signal_action_cue,
    sanitize_telegram_markdown,
    # Standardized terminology constants
    LABEL_SCANS,
)
from pearlalgo.utils.telegram_ui_contract import (
    callback_menu,
    callback_action,
    callback_signal_detail,
    callback_confirm,
    MENU_MAIN,
    MENU_STATUS,
    MENU_SYSTEM,
    MENU_SETTINGS,
    ACTION_REFRESH_DASHBOARD,
    ACTION_DATA_QUALITY,
    ACTION_GATEWAY_STATUS,
)

try:
    from pearlalgo.market_agent.chart_generator import ChartGenerator
    CHART_GENERATOR_AVAILABLE = True
except ImportError:
    CHART_GENERATOR_AVAILABLE = False
    ChartGenerator = None

TELEGRAM_AVAILABLE = importlib.util.find_spec("telegram") is not None
if not TELEGRAM_AVAILABLE:
    logger.warning("python-telegram-bot not installed, Telegram notifications disabled")


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

    def _trade_charts_dir(self) -> Path:
        """Directory for per-trade charts persisted to disk."""
        d = Path(self.state_dir) / "exports" / "trade_charts"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return d

    def _safe_chart_key(self, signal_id: str) -> str:
        """Make a signal_id safe for filenames (no path separators)."""
        s = str(signal_id or "").strip() or "unknown"
        s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s)
        return s[:120]

    def _persist_trade_chart(self, *, chart_path: Path, signal_id: str, kind: str) -> Optional[Path]:
        """
        Persist a generated chart under exports/trade_charts.

        Returns the persisted path, or None on failure.
        """
        try:
            if not chart_path or not Path(chart_path).exists():
                return None
            kind_norm = str(kind or "").strip().lower()
            if kind_norm not in {"entry", "exit"}:
                kind_norm = "chart"

            dest = self._trade_charts_dir() / f"{self._safe_chart_key(signal_id)}_{kind_norm}.png"
            try:
                shutil.copy2(str(chart_path), str(dest))
            except Exception:
                shutil.copyfile(str(chart_path), str(dest))
            return dest if dest.exists() else None
        except Exception:
            return None

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
    
    async def _send_photo(
        self,
        photo_path: Path,
        caption: Optional[str] = None,
        reply_markup=None,
        return_message: bool = False,
    ):
        """Send photo to Telegram with optional inline buttons.
        
        Args:
            photo_path: Path to the photo file
            caption: Optional caption text
            reply_markup: Optional inline keyboard markup
            return_message: If True, return the Message object; otherwise return bool
            
        Returns:
            Message object if return_message=True, else True on success, False on failure
        """
        if not self.enabled or not self.telegram or not self.telegram.bot:
            return None if return_message else False
        
        try:
            with open(photo_path, 'rb') as photo:
                msg = await self.telegram.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode="Markdown" if caption else None,
                    reply_markup=reply_markup,
                )
            return msg if return_message else True
        except Exception as e:
            logger.warning(f"Error sending photo: {e}")
            return None if return_message else False

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
                    message += "• ✅ Order Book: Aligned (bid pressure supports long)\n"
                elif imbalance < -0.15:
                    message += "• ⚠️ Order Book: Opposing (ask pressure against long)\n"
                else:
                    message += "• ⚪ Order Book: Neutral\n"
            elif signal_direction_lower == "short":
                if imbalance < -0.15:
                    message += "• ✅ Order Book: Aligned (ask pressure supports short)\n"
                elif imbalance > 0.15:
                    message += "• ⚠️ Order Book: Opposing (bid pressure against short)\n"
                else:
                    message += "• ⚪ Order Book: Neutral\n"

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

            # Preserve key context from the signal alert (so ENTRY can be canonical without losing info)
            try:
                confidence = float(signal.get("confidence") or 0.0)
            except Exception:
                confidence = 0.0
            try:
                conf_emoji, conf_tier = format_signal_confidence_tier(confidence)
                regime = signal.get("regime", {}) or {}
                session = (
                    str(regime.get("session", "")).replace("_", " ").title()
                    if isinstance(regime, dict) and regime.get("session")
                    else ""
                )
                if confidence > 0:
                    if not message.endswith("\n"):
                        message += "\n"
                    message += f"\n{conf_emoji} Conf: {confidence:.0%} {conf_tier}"
                    if session:
                        message += f" | {session}"
            except Exception:
                pass
            
            # Send message - no inline buttons, all actions accessible via /start menu
            # Entry notifications are high-signal; never dedupe.
            success = await self.telegram.send_message(message, dedupe=False)
            
            # Persist entry chart for later review (do NOT send charts in notifications).
            try:
                if (
                    self.chart_generator is not None
                    and buffer_data is not None
                    and not buffer_data.empty
                ):
                    chart_path = await asyncio.to_thread(
                        self.chart_generator.generate_entry_chart,
                        signal=signal,
                        buffer_data=buffer_data,
                        symbol=str(signal.get("symbol") or "MNQ"),
                        timeframe=None,
                    )
                    if chart_path and Path(chart_path).exists():
                        persisted = self._persist_trade_chart(
                            chart_path=Path(chart_path),
                            signal_id=str(signal_id),
                            kind="entry",
                        )
                        if persisted:
                            logger.debug(f"Saved entry chart: {persisted}")
                    try:
                        if chart_path and Path(chart_path).exists():
                            Path(chart_path).unlink()
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Could not persist entry chart for {str(signal_id)[:16]}: {e}")
            
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
            
            # Send message - no inline buttons, all actions accessible via /start menu
            # Exit notifications are high-signal; never dedupe.
            success = await self.telegram.send_message(message, dedupe=False)
            
            # Generate and persist exit chart if available (do NOT send charts in notifications)
            chart_path = None
            if self.chart_generator and buffer_data is not None and not buffer_data.empty:
                try:
                    chart_path = await asyncio.to_thread(
                        self.chart_generator.generate_exit_chart,
                        signal,
                        exit_price,
                        exit_reason,
                        pnl,
                        buffer_data,
                        symbol,
                    )
                except Exception as e:
                    logger.warning(f"Could not generate exit chart: {e}")
            
            if chart_path and chart_path.exists():
                try:
                    persisted = self._persist_trade_chart(
                        chart_path=chart_path,
                        signal_id=str(signal_id),
                        kind="exit",
                    )
                    if persisted:
                        logger.debug(f"Saved exit chart: {persisted}")
                    try:
                        chart_path.unlink()
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"Could not persist exit chart: {e}")
            
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
            message = "📊 *NQ Agent Status*\n\n"

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
                            data_text += " • ⚪ Balanced"
                    message += f"{data_emoji} *Data:* {data_text}\n"
                elif data_level == 'level1':
                    message += "📈 *Data:* Level 1\n"
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
                    message += "📈 *Performance (7d):* No completed trades yet\n"

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
                    from datetime import timezone as tz
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
                    except Exception:
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

    async def send_dashboard(self, status: Dict, chart_path: Optional[Path] = None) -> bool:
        """
        Send the main dashboard (canonical).

        - **Visual dashboard** (preferred): chart image + caption + the same 2x2 menu + Refresh buttons.
        - **Text-only fallback**: same caption text, no image (when chart generation is unavailable).

        This intentionally avoids the old Home Card / sparkline dashboard to prevent UI drift.
        
        Args:
            status: Status dictionary with service information
            chart_path: Optional path to chart image to embed as visual dashboard
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            # Extract values from status dict
            import os
            symbol = str(status.get("symbol") or "MNQ")
            market_label = str(os.getenv("PEARLALGO_MARKET") or "NQ").strip().upper()

            current_time = status.get("current_time") or datetime.now(timezone.utc)
            
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
                time_str = et_time.strftime("%I:%M %p ET").lstrip("0")
            except Exception:
                time_str = current_time.strftime("%H:%M UTC") if hasattr(current_time, 'strftime') else ""
            
            latest_price = status.get("latest_price")
            paused = bool(status.get("paused", False))
            
            # Gates
            futures_market_open = status.get("futures_market_open")
            if futures_market_open is None:
                try:
                    futures_market_open = bool(get_market_hours().is_market_open())
                except Exception:
                    futures_market_open = None
            strategy_session_open = status.get("strategy_session_open")
            
            # Buffer size only used for confidence cues (buttons).
            buffer_size = int(status.get("buffer_size", 0) or 0)

            # Data freshness / level
            latest_bar = status.get("latest_bar") if isinstance(status.get("latest_bar"), dict) else {}
            data_level = (latest_bar or {}).get("_data_level")
            data_age_seconds = None
            try:
                ts = (latest_bar or {}).get("timestamp")
                if ts:
                    dt = parse_utc_timestamp(str(ts))
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt:
                        data_age_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
            except Exception:
                data_age_seconds = None

            try:
                data_stale_threshold_minutes = float(status.get("data_stale_threshold_minutes", 10.0))
            except Exception:
                data_stale_threshold_minutes = 10.0

            is_data_stale = False
            if data_age_seconds is not None:
                # Only treat as stale when the agent is expected to have fresh data.
                off_hours = (futures_market_open is False and strategy_session_open is False)
                if (not paused) and (not off_hours):
                    is_data_stale = (float(data_age_seconds) / 60.0) > float(data_stale_threshold_minutes)

            # Agent health (glanceable)
            agent_running = bool(status.get("running", True))
            last_cycle_seconds = None
            try:
                ts = status.get("last_successful_cycle")
                if ts:
                    dt = parse_utc_timestamp(str(ts))
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt:
                        last_cycle_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
            except Exception:
                last_cycle_seconds = None

            agent_uptime_seconds = None
            try:
                st = status.get("start_time")
                if st:
                    dt = parse_utc_timestamp(str(st))
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt:
                        agent_uptime_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
            except Exception:
                agent_uptime_seconds = None

            # Grace period: treat missing last_successful_cycle as healthy during initial startup.
            agent_healthy: bool | None = None
            try:
                if not agent_running:
                    agent_healthy = None
                elif last_cycle_seconds is None:
                    agent_healthy = True if (agent_uptime_seconds is not None and agent_uptime_seconds < 60) else None
                else:
                    try:
                        scan_interval = float((status.get("config") or {}).get("scan_interval") or 30.0)
                    except Exception:
                        scan_interval = 30.0
                    thresh = max(90.0, scan_interval * 2.0)
                    agent_healthy = bool(last_cycle_seconds <= thresh)
            except Exception:
                agent_healthy = None

            # Gateway status: prefer explicit connection status when present.
            conn = str(status.get("connection_status") or "").lower().strip()
            if conn == "connected":
                gateway_running = True
            elif conn == "disconnected":
                gateway_running = False
            else:
                gateway_running = None

            gateway_uncertain = (gateway_running is None) or (gateway_running is False) or is_data_stale or (buffer_size < 1)

            # P&L shown on the "🎯 Active" line should reflect open positions when available.
            active_cnt = int(status.get("active_trades_count", 0) or 0)
            pnl_for_active_line = None
            if active_cnt > 0:
                unreal = status.get("active_trades_unrealized_pnl")
                if unreal is not None:
                    try:
                        pnl_for_active_line = float(unreal)
                    except (ValueError, TypeError):
                        pnl_for_active_line = None
                else:
                    try:
                        dp = float(status.get("daily_pnl", 0.0) or 0.0)
                        pnl_for_active_line = dp if dp != 0.0 else None
                    except (ValueError, TypeError):
                        pnl_for_active_line = None

            # Build the /start-style dashboard caption (glanceable card + challenge/perf blocks).
            message = format_glanceable_card(
                symbol=symbol,
                time_str=time_str,
                agent_running=agent_running,
                gateway_running=gateway_running,
                latest_price=latest_price,
                daily_pnl=pnl_for_active_line,
                active_trades_count=active_cnt,
                futures_market_open=futures_market_open,
                strategy_session_open=strategy_session_open,
                market=market_label,
                trading_bot="scanner",
                ai_ready=False,
                agent_uptime_seconds=agent_uptime_seconds,
                data_age_seconds=data_age_seconds,
                agent_healthy=agent_healthy,
                data_stale=(None if data_age_seconds is None else bool(is_data_stale)),
            )

            # ------------------------------------------------------------------
            # Transparent AI/ML status (one-liner; match /start dashboard)
            # ------------------------------------------------------------------
            try:
                # AI readiness (best-effort): informational only (does not affect trading).
                ai_ready = False
                try:
                    from pearlalgo.utils.openai_client import OPENAI_AVAILABLE, OpenAIClient

                    if OPENAI_AVAILABLE:
                        try:
                            OpenAIClient()
                            ai_ready = True
                        except Exception:
                            ai_ready = False
                except Exception:
                    ai_ready = False

                bandit = status.get("learning") or {}
                bandit_mode = str(bandit.get("mode") or "off").lower()

                ctx = status.get("learning_contextual") or {}
                ctx_mode = str(ctx.get("mode") or "off").lower() or "off"

                ml_label = "?"
                try:
                    ml_state = status.get("ml_filter") or {}
                    if isinstance(ml_state, dict) and "enabled" in ml_state:
                        if bool(ml_state.get("enabled", False)):
                            mm = str(ml_state.get("mode") or "on").lower()
                            ml_label = mm if mm in ("shadow", "live") else "on"
                        else:
                            ml_label = "off"
                except Exception:
                    ml_label = "?"

                lift_progress = ""
                try:
                    ml_state = status.get("ml_filter") or {}
                    lift = (ml_state or {}).get("lift") if isinstance(ml_state, dict) else {}
                    lift = lift or {}
                    scored = lift.get("scored_trades")
                    min_trades = lift.get("min_trades")
                    if scored is not None and min_trades:
                        lift_progress = f" • Lift {int(scored)}/{int(min_trades)}"
                        try:
                            p = lift.get("pass_trades")
                            f = lift.get("fail_trades")
                            if p is not None and f is not None:
                                lift_progress += f" ({int(p)}P/{int(f)}F)"
                        except Exception:
                            pass
                except Exception:
                    lift_progress = ""

                ai_label = "ON" if ai_ready else "OFF"
                message += f"\n🧠 AI/ML: AI {ai_label} • Bandit {bandit_mode} • Ctx {ctx_mode} • Filter {ml_label}{lift_progress}"
            except Exception:
                pass

            # ------------------------------------------------------------------
            # 24h + 72h performance (match /start dashboard semantics)
            # ------------------------------------------------------------------
            try:
                from datetime import timedelta
                import json

                daily_pnl = status.get("daily_pnl")
                daily_trades = status.get("daily_trades")
                daily_wins = status.get("daily_wins")
                daily_losses = status.get("daily_losses")

                perf_trades: list[dict] = []
                today_trades_list: list[dict] = []
                perf_file = self.state_dir / "performance.json"
                if perf_file.exists():
                    try:
                        perf_trades = json.loads(perf_file.read_text(encoding="utf-8"))
                        if not isinstance(perf_trades, list):
                            perf_trades = []
                    except Exception:
                        perf_trades = []

                # "24h" section is actually today's UTC trades (legacy label; matches existing dashboard).
                if perf_trades:
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    today_trades_list = [t for t in perf_trades if today_str in str(t.get("exit_time", "") or "")]
                    if today_trades_list and (daily_pnl is None or daily_trades is None):
                        daily_pnl = sum(float(t.get("pnl", 0) or 0) for t in today_trades_list)
                        daily_trades = len(today_trades_list)
                        daily_wins = sum(1 for t in today_trades_list if t.get("is_win"))
                        daily_losses = int(daily_trades - int(daily_wins or 0))

                # Streak (from today's trades)
                current_streak = 0
                streak_type = None  # 'win' or 'loss'
                if today_trades_list:
                    sorted_trades = sorted(today_trades_list, key=lambda t: str(t.get("exit_time", "") or ""))
                    for t in reversed(sorted_trades):
                        is_win = bool(t.get("is_win", False))
                        if streak_type is None:
                            streak_type = "win" if is_win else "loss"
                            current_streak = 1
                        elif (streak_type == "win" and is_win) or (streak_type == "loss" and (not is_win)):
                            current_streak += 1
                        else:
                            break

                daily_pnl = float(daily_pnl or 0.0)
                daily_trades = int(daily_trades or 0)
                daily_wins = int(daily_wins or 0)
                daily_losses = int(daily_losses or 0)

                if daily_trades > 0 or daily_pnl != 0:
                    pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                    pnl_sign = "+" if daily_pnl >= 0 else "-"
                    win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0.0
                    streak_str = ""
                    if current_streak >= 3 and streak_type:
                        streak_str = f" • {'🔥' if streak_type == 'win' else '❄️'}{current_streak}{'W' if streak_type == 'win' else 'L'}"
                    message += "\n\n*24h:*"
                    message += f"\n{pnl_emoji} {pnl_sign}${abs(daily_pnl):,.2f} ({daily_wins}W/{daily_losses}L • {win_rate:.0f}% WR){streak_str}"

                # Rolling 72h
                if perf_trades:
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
                    trades_72h: list[dict] = []
                    for t in perf_trades:
                        try:
                            ts = str(t.get("exit_time", "") or "")
                            if not ts:
                                continue
                            from pearlalgo.utils.paths import parse_utc_timestamp

                            dt = parse_utc_timestamp(ts)
                            if dt >= cutoff:
                                trades_72h.append(t)
                        except Exception:
                            continue
                    # Defensive: de-dupe by signal_id to avoid any double-counting if the
                    # performance log ever accumulates duplicate exits.
                    try:
                        by_id = {}
                        no_id = []
                        for t in trades_72h:
                            sid = str(t.get("signal_id") or "").strip() if isinstance(t, dict) else ""
                            if not sid:
                                no_id.append(t)
                                continue
                            by_id[sid] = t  # keep most recent occurrence (append-only)
                        if by_id:
                            trades_72h = list(by_id.values()) + no_id
                    except Exception:
                        pass
                    if trades_72h:
                        pnl_72h = sum(float(t.get("pnl", 0) or 0) for t in trades_72h)
                        wins_72h = sum(1 for t in trades_72h if t.get("is_win"))
                        losses_72h = int(len(trades_72h) - int(wins_72h or 0))
                        wr_72h = (wins_72h / len(trades_72h) * 100) if trades_72h else 0.0
                        pnl_emoji_72h = "🟢" if pnl_72h >= 0 else "🔴"
                        pnl_sign_72h = "+" if pnl_72h >= 0 else "-"
                        message += "\n\n*72h:*"
                        message += f"\n{pnl_emoji_72h} {pnl_sign_72h}${abs(pnl_72h):,.2f} ({int(wins_72h)}W/{int(losses_72h)}L • {wr_72h:.0f}% WR)"
            except Exception:
                pass

            # Challenge + performance (best-effort; never block dashboard).
            try:
                from pearlalgo.market_agent.challenge_tracker import ChallengeTracker
                ct = ChallengeTracker(state_dir=self.state_dir)
                try:
                    ct.refresh()
                except Exception:
                    pass

                # Get unrealized PNL from status if available
                unrealized_pnl = status.get("active_trades_unrealized_pnl")
                if unrealized_pnl is not None:
                    try:
                        unrealized_pnl = float(unrealized_pnl)
                    except (ValueError, TypeError):
                        unrealized_pnl = None

                # 30d performance (from SQLite if available)
                try:
                    from pearlalgo.learning.trade_database import TradeDatabase
                    db_path = self.state_dir / "trades.db"
                    if db_path.exists():
                        trade_db = TradeDatabase(db_path)
                        strategy_perf = trade_db.get_performance_by_signal_type(days=30)
                        if strategy_perf:
                            total_pnl_all = sum(perf.get("total_pnl", 0.0) for perf in strategy_perf.values())
                            total_wins = sum(perf.get("wins", 0) for perf in strategy_perf.values())
                            total_losses = sum(perf.get("losses", 0) for perf in strategy_perf.values())
                            total_trades = total_wins + total_losses
                            total_wr = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0
                            total_emoji = "🟢" if total_pnl_all >= 0 else "🔴"
                            message += "\n\n*30d Performance:*"
                            message += (
                                f"\n{total_emoji} *Total:* ${total_pnl_all:,.2f} "
                                f"({total_wins}W/{total_losses}L • {total_wr:.0f}% WR)"
                            )
                except Exception:
                    pass

                # Single canonical challenge block (avoid duplicate "current run" sections).
                try:
                    message += "\n\n" + ct.get_status_summary(bot_label="Scanner", unrealized_pnl=unrealized_pnl)
                except Exception:
                    pass

                # Recent exits (compact; match /start dashboard style)
                try:
                    recent_exits = status.get("recent_exits", [])
                    if isinstance(recent_exits, list) and recent_exits:
                        message += "\n\n*Recent exits:*"
                        for t in recent_exits[:2]:
                            try:
                                pnl_val = float(t.get("pnl") or 0.0)
                            except Exception:
                                pnl_val = 0.0
                            pnl_emoji, pnl_str = format_pnl(pnl_val)
                            dir_emoji, dir_label = format_signal_direction(t.get("direction", "long"))
                            sig_type = safe_label(str(t.get("type") or "unknown"))
                            reason = safe_label(str(t.get("exit_reason") or "")).strip()
                            line = f"\n{pnl_emoji} *{pnl_str}* • {dir_emoji} {dir_label} • {sig_type}"
                            if reason:
                                line += f" • {reason}"
                            message += line
                except Exception:
                    pass
            except Exception:
                pass

            # Support footer (🩺 …) for debugging/sharing (best-effort).
            try:
                from importlib.metadata import version as get_version
                from pearlalgo.utils.logging_config import get_run_id

                ver = None
                try:
                    ver = get_version("pearlalgo-dev-ai-agents")
                except Exception:
                    ver = "0.2.2"
                run_id = None
                try:
                    run_id = get_run_id()
                except Exception:
                    run_id = None

                lvl_map = {
                    "level1": "L1",
                    "level2": "L2",
                    "historical": "HIST",
                    "historical_fallback": "HIST",
                    "error": "ERR",
                    "unknown": "?",
                }
                lvl_short = lvl_map.get(str(data_level).strip().lower(), "?")

                def _fmt_dur(sec: float | None) -> str:
                    if sec is None:
                        return "?"
                    try:
                        s = float(sec)
                    except Exception:
                        return "?"
                    if s < 60:
                        return f"{int(s)}s"
                    if s < 3600:
                        return f"{int(s // 60)}m"
                    hours = int(s // 3600)
                    mins = int((s % 3600) // 60)
                    return f"{hours}h{mins}m"

                age_str = _fmt_dur(data_age_seconds)
                thr_str = f"{float(data_stale_threshold_minutes):.0f}m"
                cycle_str = _fmt_dur(last_cycle_seconds)
                gw = "OK" if gateway_running is True else "OFF" if gateway_running is False else "?"
                a = "ON" if agent_running else "OFF"
                v = f" v{ver}" if ver else ""
                rid = str(run_id or "?").strip()
                stale_flag = "!" if is_data_stale else ""
                support = f"`🩺 {market_label}/{symbol}{v} | A:{a} | G:{gw} | D:{lvl_short} {age_str}/{thr_str}{stale_flag} | C:{cycle_str} | run:{rid}`"
                message += "\n" + support
            except Exception:
                pass
            
            # Build main menu buttons (only useful when the command handler is running).
            reply_markup = None
            handler_running = _is_command_handler_running()
            if handler_running:
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                    # Activity label: include active count when meaningful.
                    try:
                        active_cnt = int(status.get("active_trades_count", 0) or 0)
                    except Exception:
                        active_cnt = 0
                    activity_label = f"📊 Activity ({active_cnt})" if active_cnt > 0 else "📊 Activity"

                    # System/Health dots (quick-glance; the card itself remains authoritative).
                    system_dot = "🟢" if not gateway_uncertain else "🟡"
                    system_label = f"🎛️ System {system_dot}"
                    health_label = "🛡️ Health 🔴" if is_data_stale else "🛡️ Health 🟢"
                    settings_label = "⚙️ Settings"

                    keyboard = [
                        [
                            InlineKeyboardButton(activity_label, callback_data=callback_menu("activity")),
                            InlineKeyboardButton(system_label, callback_data=callback_menu(MENU_SYSTEM)),
                        ],
                        [
                            InlineKeyboardButton(health_label, callback_data=callback_menu(MENU_STATUS)),
                            InlineKeyboardButton(settings_label, callback_data=callback_menu(MENU_SETTINGS)),
                        ],
                        [
                            InlineKeyboardButton("🔄 Refresh", callback_data=callback_action(ACTION_REFRESH_DASHBOARD)),
                            InlineKeyboardButton("🔄📈", callback_data="action:refresh_chart"),
                        ],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                except Exception as e:
                    logger.debug(f"Could not build dashboard buttons: {e}")
                    reply_markup = None

            # Dashboard persistence + pinned behavior.
            try:
                prefs_live = self._get_prefs()
            except Exception:
                prefs_live = self.prefs

            bot = getattr(self.telegram, "bot", None)
            if bot is None:
                return False

            edit_in_place = bool(getattr(prefs_live, "dashboard_edit_in_place", False)) if prefs_live else False
            try:
                message_id = prefs_live.get("dashboard_message_id") if prefs_live else None
            except Exception:
                message_id = None

            sent_at = datetime.now(timezone.utc).isoformat()

            # For visual dashboards, Telegram captions are capped at 1024 chars.
            caption_md = _truncate_telegram_text(sanitize_telegram_markdown(message), limit=1024)
            has_chart = bool(chart_path and isinstance(chart_path, Path) and chart_path.exists())

            def _persist(mid: int | None) -> None:
                try:
                    if prefs_live:
                        prefs_live.set("last_dashboard_sent_at", sent_at)
                        if mid is not None:
                            prefs_live.set("dashboard_message_id", int(mid))
                except Exception:
                    pass

            # If pinned mode is enabled, attempt to update the prior dashboard message in place.
            if edit_in_place and message_id:
                try:
                    mid = int(message_id)
                    if has_chart:
                        # Preferred: update photo + caption together.
                        try:
                            from telegram import InputMediaPhoto
                            with open(chart_path, "rb") as photo:
                                media = InputMediaPhoto(media=photo, caption=caption_md, parse_mode="Markdown")
                                await bot.edit_message_media(
                                    chat_id=self.chat_id,
                                    message_id=mid,
                                    media=media,
                                    reply_markup=reply_markup,
                                )
                        except Exception:
                            # Fallback: update caption only (keeps previous chart media).
                            try:
                                await bot.edit_message_caption(
                                    chat_id=self.chat_id,
                                    message_id=mid,
                                    caption=caption_md,
                                    parse_mode="Markdown",
                                    reply_markup=reply_markup,
                                )
                            except Exception:
                                # If we can't update media/caption, fall back to sending a new visual dashboard.
                                raise
                    else:
                        # No chart update: prefer caption edit if the message is a photo; fall back to text.
                        try:
                            await bot.edit_message_caption(
                                chat_id=self.chat_id,
                                message_id=mid,
                                caption=caption_md,
                                parse_mode="Markdown",
                                reply_markup=reply_markup,
                            )
                        except Exception:
                            await bot.edit_message_text(
                                chat_id=self.chat_id,
                                message_id=mid,
                                text=message,
                                parse_mode="Markdown",
                                reply_markup=reply_markup,
                            )

                    _persist(mid)
                    return True
                except Exception:
                    # If edit fails (message deleted/too old), fall back to sending a new dashboard.
                    try:
                        if prefs_live:
                            prefs_live.set("dashboard_message_id", None)
                    except Exception:
                        pass
                    # Keep message_id so we can best-effort delete it below.

            # Not pinned (or pinned edit failed): keep chat clean by deleting the previous dashboard, if any.
            if message_id:
                try:
                    await bot.delete_message(chat_id=self.chat_id, message_id=int(message_id))
                except Exception:
                    pass

            # Send new dashboard message (photo+caption when chart is provided, otherwise text-only).
            msg_obj = None
            if has_chart:
                try:
                    with open(chart_path, "rb") as photo:
                        msg_obj = await bot.send_photo(
                            chat_id=self.chat_id,
                            photo=photo,
                            caption=caption_md,
                            parse_mode="Markdown",
                            reply_markup=reply_markup,
                        )
                except Exception:
                    # Plain-text fallback if Markdown caption fails.
                    caption_plain = caption_md.replace("*", "").replace("_", "").replace("`", "")
                    with open(chart_path, "rb") as photo:
                        msg_obj = await bot.send_photo(
                            chat_id=self.chat_id,
                            photo=photo,
                            caption=caption_plain,
                            parse_mode=None,
                            reply_markup=reply_markup,
                        )
            else:
                try:
                    msg_obj = await bot.send_message(
                        chat_id=self.chat_id,
                        text=message,
                        parse_mode="Markdown",
                        reply_markup=reply_markup,
                    )
                except Exception:
                    msg_obj = await bot.send_message(
                        chat_id=self.chat_id,
                        text=message,
                        parse_mode=None,
                        reply_markup=reply_markup,
                    )

            msg_id = int(getattr(msg_obj, "message_id", 0) or 0) if msg_obj is not None else None
            _persist(msg_id if msg_id else None)
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
        Send a brief startup confirmation.
        
        Kept minimal - user can use /start for full dashboard.
        """
        if not self.enabled or not self.telegram:
            return False

        try:
            from datetime import datetime, timezone

            # Market label
            market = "NQ"
            try:
                import os
                market = str(os.getenv("PEARLALGO_MARKET") or "NQ").strip().upper()
            except Exception:
                market = "NQ"

            # Current time in ET
            current_time = datetime.now(timezone.utc)
            try:
                import pytz
                et_time = current_time.astimezone(pytz.timezone("US/Eastern"))
                time_str = et_time.strftime("%I:%M %p ET")
            except Exception:
                time_str = current_time.strftime("%H:%M UTC")

            futures_market_open = config.get("futures_market_open")
            strategy_session_open = config.get("strategy_session_open")
            fut_dot = "🟢" if futures_market_open is True else "🔴" if futures_market_open is False else "⚪️"
            ses_dot = "🟢" if strategy_session_open is True else "🔴" if strategy_session_open is False else "⚪️"

            # Simple 2-line startup message
            msg = f"🚀 *{market} Agent Started* • {time_str}\n"
            msg += f"{fut_dot} Futures {ses_dot} Session\n\n"
            msg += "Use /start for full dashboard"

            await self.telegram.send_message(msg, parse_mode="Markdown", dedupe=False)
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
            message = "🛑 *Agent Stopped*\n"
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
            message += "\n💡 /start\\_agent"

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
            message = "📅 *Weekly Performance Summary*\n\n"

            total_signals = performance_metrics.get("total_signals", 0)
            exited_signals = performance_metrics.get("exited_signals", 0)
            wins = performance_metrics.get("wins", 0)
            losses = performance_metrics.get("losses", 0)
            win_rate = performance_metrics.get("win_rate", 0) * 100
            total_pnl = performance_metrics.get("total_pnl", 0)
            avg_pnl = performance_metrics.get("avg_pnl", 0)
            avg_hold = performance_metrics.get("avg_hold_minutes", 0)

            # Signal statistics (mobile-friendly)
            message += "*Signals:*\n"
            message += f"• Total: {total_signals}\n"
            message += f"• Exited: {exited_signals}\n"
            if total_signals > 0:
                exit_rate = (exited_signals / total_signals) * 100
                message += f"• Exit Rate: {_format_percentage(exit_rate)}\n"

            if exited_signals > 0:
                message += "\n*Trade Performance:*\n"
                message += f"✅ {wins}W  ❌ {losses}L\n"
                message += f"📈 {_format_percentage(win_rate)} WR\n"
                message += f"💰 {_format_currency(total_pnl)}\n"
                message += f"📊 {_format_currency(avg_pnl)} avg\n"
                message += f"⏱️ {avg_hold:.1f}m avg hold\n"

                # Performance trend
                if total_pnl > 0:
                    message += "\n📈 *Trend:* ↗️ Profitable week\n"
                elif total_pnl < 0:
                    message += "\n📉 *Trend:* ↘️ Loss week\n"
                else:
                    message += "\n➡️ *Trend:* ➡️ Break even\n"
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
            message = "🛑 *Circuit Breaker Activated*\n\n"
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
            message = "✅ *Service Recovered*\n\n"
            message += f"*Issue:* {issue}\n"
            message += f"*Time:* {recovery_info.get('recovery_time_seconds', 0):.0f}s\n"
            message += "*Status:* Normal operation\n"

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
                message += "\n*By Type:*\n"
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
                    message += "\n⚠️ Significant price movement detected\n"

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
