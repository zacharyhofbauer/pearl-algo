"""
Telegram Action Handlers for Market Agent.

This module provides mixin methods for handling callback actions and menu navigation.
These are extracted from TelegramCommandHandler to improve modularity.

Architecture Note:
------------------
This is a mixin class designed to be composed with TelegramCommandHandler.
It provides action handling utilities while keeping the main handler class
focused on high-level orchestration.

The main TelegramCommandHandler class still handles the primary routing
(handle_callback method), but delegates specific action implementations
to methods in this mixin.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Any

from pearlalgo.config.config_file import toggle_strategy_in_config
from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_state_file
from pearlalgo.utils.state_io import load_json_file

if TYPE_CHECKING:
    from telegram import CallbackQuery, InlineKeyboardMarkup


class TelegramHandlersMixin:
    """
    Mixin providing action handler utilities for Telegram bot.

    This mixin is designed to be used with TelegramCommandHandler and provides:
    - Service control actions (start/stop agent/gateway)
    - Trade management actions (close all, emergency stop)
    - Performance actions (reset, export)
    - Settings toggle actions

    Usage:
        class TelegramCommandHandler(TelegramHandlersMixin, ...):
            ...

    Required attributes on the composing class:
        - state_dir: Path to the state directory
        - active_market: Current market identifier
        - service_controller: ServiceController instance
        - _safe_edit_or_send: Method for safe message editing
        - _nav_back_row: Method returning back navigation row
    """

    # Required by composing class
    state_dir: Path
    active_market: str

    async def _execute_service_action(
        self,
        query: Any,
        action: str,
        service: str,
    ) -> dict:
        """
        Execute a service control action.

        Args:
            query: Telegram callback query
            action: Action to perform (start, stop, restart)
            service: Service to control (agent, gateway)

        Returns:
            Dict with keys: success, message, details
        """
        sc = getattr(self, "service_controller", None)
        if sc is None:
            return {
                "success": False,
                "message": "Service controller not available.",
                "details": None,
            }

        try:
            if service == "agent":
                if action == "start":
                    result = await sc.start_agent(background=True, market=self.active_market)
                elif action == "stop":
                    result = await sc.stop_agent(market=self.active_market)
                elif action == "restart":
                    result = await sc.restart_agent(background=True, market=self.active_market)
                else:
                    return {"success": False, "message": f"Unknown action: {action}", "details": None}
            elif service == "gateway":
                if action == "start":
                    result = await sc.start_gateway()
                elif action == "stop":
                    result = await sc.stop_gateway()
                elif action == "restart":
                    result = await sc.restart_gateway()
                else:
                    return {"success": False, "message": f"Unknown action: {action}", "details": None}
            else:
                return {"success": False, "message": f"Unknown service: {service}", "details": None}

            return {
                "success": True,
                "message": result.get("message", f"{action.title()}ed {service}."),
                "details": result.get("details"),
            }
        except Exception as e:
            logger.error(f"Error executing {action} {service}: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Error: {str(e)[:100]}",
                "details": None,
            }

    async def _handle_close_all_trades(self, query: Any, reply_markup: Any) -> None:
        """
        Handle close all trades confirmation action.

        Writes a close_all_requested flag to state.json for the agent to process.
        """
        try:
            state_file = get_state_file(self.state_dir)
            if state_file.exists():
                state = load_json_file(state_file)
                virtual_count = state.get("active_trades_count", 0) or 0
                state["close_all_requested"] = True
                state["close_all_requested_time"] = datetime.now(timezone.utc).isoformat()
                state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    keyboard = [
                        [InlineKeyboardButton("📊 Check Activity", callback_data="menu:activity")],
                        self._nav_back_row(),
                    ]
                    await self._safe_edit_or_send(
                        query,
                        f"✅ Close All Trades Request Sent\n\n"
                        f"Closing {virtual_count} trade(s) at next opportunity (~5 seconds).\n\n"
                        "Tap 'Check Activity' to verify positions are closed.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                except Exception:
                    await self._safe_edit_or_send(
                        query,
                        f"✅ Close all trades requested ({virtual_count})",
                        reply_markup=reply_markup,
                    )

                logger.info(f"Close all virtual trades ({virtual_count}) requested via Telegram")
            else:
                await self._safe_edit_or_send(
                    query,
                    "❌ State file not found.\n\nIs the agent running?",
                    reply_markup=reply_markup,
                )
        except Exception as e:
            logger.error(f"Close all trades error: {e}", exc_info=True)
            await self._safe_edit_or_send(query, f"❌ Error: {e}", reply_markup=reply_markup)

    async def _handle_emergency_stop(self, query: Any, reply_markup: Any) -> None:
        """
        Handle emergency stop confirmation action.

        Writes emergency_stop flag to state and stops the agent.
        """
        try:
            sc = getattr(self, "service_controller", None)
            messages = ["🚨 *EMERGENCY STOP EXECUTED*\n"]

            # First, try to write emergency stop signal to state file
            state_file = get_state_file(self.state_dir)
            state = load_json_file(state_file)
            if state is not None:
                try:
                    state["emergency_stop"] = True
                    state["emergency_stop_time"] = datetime.now(timezone.utc).isoformat()
                    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
                    messages.append("✅ Emergency stop signal written to state")
                except Exception as e:
                    messages.append(f"⚠️ Could not write emergency state: {e}")

            # Stop the agent
            if sc is not None:
                result = await sc.stop_agent(market=self.active_market)
                messages.append(f"✅ Agent stopped: {result.get('message', 'OK')}")
            else:
                messages.append("⚠️ Service controller not available")

            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = [
                    [InlineKeyboardButton("🤖 Check Bots", callback_data="menu:bots")],
                    self._nav_back_row(),
                ]
                await self._safe_edit_or_send(
                    query,
                    "\n".join(messages),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown",
                )
            except Exception:
                await self._safe_edit_or_send(
                    query,
                    "\n".join(messages),
                    reply_markup=reply_markup,
                )

            logger.warning("EMERGENCY STOP executed via Telegram")
        except Exception as e:
            logger.error(f"Emergency stop error: {e}", exc_info=True)
            await self._safe_edit_or_send(
                query,
                f"❌ Emergency stop error: {e}",
                reply_markup=reply_markup,
            )

    async def _handle_clear_cache(self, query: Any, reply_markup: Any) -> None:
        """
        Handle clear cache confirmation action.

        Clears temporary data and cache directories.
        """
        try:
            cleared = []
            cache_paths = [
                self.state_dir / "cache",
                self.state_dir / "temp",
                self.state_dir / ".cache",
            ]
            for cache_path in cache_paths:
                if cache_path.exists() and cache_path.is_dir():
                    shutil.rmtree(cache_path)
                    cache_path.mkdir(exist_ok=True)
                    cleared.append(str(cache_path.name))

            if cleared:
                text = f"✅ Cache Cleared\n\nCleared: {', '.join(cleared)}"
            else:
                text = "✅ Cache Clear Complete\n\nNo cache directories found."

            try:
                from telegram import InlineKeyboardMarkup
                keyboard = [self._nav_back_row()]
                await self._safe_edit_or_send(
                    query,
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            except Exception:
                await self._safe_edit_or_send(query, text, reply_markup=reply_markup)

            logger.info(f"Cache cleared via Telegram: {cleared}")
        except Exception as e:
            logger.error(f"Clear cache error: {e}", exc_info=True)
            await self._safe_edit_or_send(
                query,
                f"❌ Error clearing cache: {e}",
                reply_markup=reply_markup,
            )

    async def _handle_reset_performance(self, query: Any, reply_markup: Any) -> None:
        """
        Handle reset performance stats confirmation action.

        Resets daily P&L counters in state file.
        """
        try:
            state_file = get_state_file(self.state_dir)
            if state_file.exists():
                state = load_json_file(state_file)
                state["daily_pnl"] = 0.0
                state["daily_trades"] = 0
                state["daily_wins"] = 0
                state["daily_losses"] = 0
                state["performance_reset_time"] = datetime.now(timezone.utc).isoformat()
                state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    keyboard = [
                        [InlineKeyboardButton("💎 Performance", callback_data="menu:performance")],
                        self._nav_back_row(),
                    ]
                    await self._safe_edit_or_send(
                        query,
                        "✅ Performance Stats Reset\n\n"
                        "Daily counters have been reset.\n"
                        "Trade history is preserved.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                except Exception:
                    await self._safe_edit_or_send(
                        query,
                        "✅ Performance stats reset.",
                        reply_markup=reply_markup,
                    )

                logger.info("Performance stats reset via Telegram")
            else:
                await self._safe_edit_or_send(
                    query,
                    "❌ State file not found.",
                    reply_markup=reply_markup,
                )
        except Exception as e:
            logger.error(f"Reset performance error: {e}", exc_info=True)
            await self._safe_edit_or_send(query, f"❌ Error: {e}", reply_markup=reply_markup)

    async def _handle_reset_challenge(self, query: Any, reply_markup: Any) -> None:
        """
        Handle reset challenge confirmation action.

        Starts a fresh challenge attempt.
        """
        try:
            from pearlalgo.market_agent.challenge_tracker import ChallengeTracker
            challenge_tracker = ChallengeTracker(state_dir=self.state_dir)
            new_attempt = challenge_tracker.manual_reset(reason="telegram_reset")

            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = [
                    [InlineKeyboardButton("🔄 Refresh Health", callback_data="menu:status")],
                    self._nav_back_row(),
                ]
                await self._safe_edit_or_send(
                    query,
                    f"✅ Challenge Reset Complete\n\n"
                    f"New attempt started: #{new_attempt.attempt_id}\n\n"
                    f"Starting Balance: ${new_attempt.starting_balance:,.2f}\n"
                    f"Profit Target: +$3,000\n"
                    f"Max Drawdown: -$2,000\n\n"
                    f"Previous attempt saved to history.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            except Exception:
                await self._safe_edit_or_send(
                    query,
                    f"✅ Challenge reset. New attempt: #{new_attempt.attempt_id}",
                    reply_markup=reply_markup,
                )

            logger.info(f"Challenge reset via Telegram: new attempt #{new_attempt.attempt_id}")
        except Exception as e:
            logger.error(f"Error resetting challenge: {e}", exc_info=True)
            await self._safe_edit_or_send(
                query,
                f"❌ Error resetting challenge: {e}\n\nPlease check logs.",
                reply_markup=reply_markup,
            )

    def _apply_preference_toggle(self, pref_key: str) -> bool:
        """
        Toggle a preference and return the new value.

        Args:
            pref_key: The preference key to toggle

        Returns:
            The new value after toggling
        """
        from pearlalgo.utils.telegram_alerts import TelegramPrefs

        prefs = TelegramPrefs(state_dir=self.state_dir)

        try:
            # Snooze requires special handling
            if pref_key == "snooze_noncritical_alerts":
                if bool(getattr(prefs, "snooze_noncritical_alerts", False)):
                    prefs.disable_snooze()
                    return False
                else:
                    prefs.enable_snooze(hours=1.0)
                    return True

            # Dashboard buttons always on
            if pref_key == "dashboard_buttons":
                prefs.set("dashboard_buttons", True)
                return True

            # Pinned dashboard needs message ID reset
            if pref_key == "dashboard_edit_in_place":
                cur = bool(prefs.get(pref_key, False))
                prefs.set(pref_key, not cur)
                prefs.set("dashboard_message_id", None)
                return not cur

            # Standard boolean toggle
            current = prefs.get(pref_key)
            if isinstance(current, bool):
                prefs.set(pref_key, not current)
                return not current

            return False
        except Exception as e:
            logger.error(f"Error toggling preference {pref_key}: {e}")
            return False

    def _apply_alert_mode_preset(self, mode: str) -> None:
        """
        Apply an alert mode preset (minimal, standard, verbose).

        Args:
            mode: The preset mode to apply
        """
        from pearlalgo.utils.telegram_alerts import TelegramPrefs

        prefs = TelegramPrefs(state_dir=self.state_dir)

        try:
            if mode == "minimal":
                # Signals only, no charts, no interval updates
                prefs.set("auto_chart_on_signal", False)
                prefs.set("interval_notifications", False)
                prefs.set("signal_detail_expanded", False)
            elif mode == "standard":
                # Signals + charts (recommended)
                prefs.set("auto_chart_on_signal", True)
                prefs.set("interval_notifications", True)
                prefs.set("signal_detail_expanded", False)
            elif mode == "verbose":
                # Everything + detailed info
                prefs.set("auto_chart_on_signal", True)
                prefs.set("interval_notifications", True)
                prefs.set("signal_detail_expanded", True)
        except Exception as e:
            logger.error(f"Error setting alert mode {mode}: {e}")

    async def _handle_toggle_strategy(
        self,
        query: Any,
        strategy_name: str,
        reply_markup: Any,
    ) -> None:
        """
        Toggle a strategy on/off by updating config.yaml.

        Args:
            query: Telegram callback query
            strategy_name: Name of the strategy to toggle
            reply_markup: Fallback keyboard markup
        """
        try:
            action = toggle_strategy_in_config(strategy_name)

            # Show success message
            status_emoji = "🟢" if action == "enabled" else "🔴"
            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = [
                    [InlineKeyboardButton("🔄 Refresh Bots", callback_data="menu:bots")],
                    self._nav_back_row(),
                ]
                message = (
                    f"{status_emoji} *Bot {action.title()}*\n\n"
                    f"Bot: `{strategy_name}`\n\n"
                    f"⚠️ *Restart the agent* for changes to take effect.\n\n"
                    f"Use System menu → Restart Agent"
                )
                await self._safe_edit_or_send(
                    query,
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown",
                )
            except Exception:
                await self._safe_edit_or_send(
                    query,
                    f"Strategy {strategy_name} {action}. Restart agent to apply.",
                    reply_markup=reply_markup,
                )

            logger.info(f"Strategy {strategy_name} {action} via Telegram")

        except FileNotFoundError as e:
            await self._safe_edit_or_send(
                query,
                f"❌ {e}\n\nCannot modify strategies.",
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error(f"Error toggling strategy: {e}", exc_info=True)
            await self._safe_edit_or_send(
                query,
                f"❌ Error updating bot: {e}\n\nPlease check config file manually.",
                reply_markup=reply_markup,
            )
