"""
Telegram Menu Handler for NQ Agent.

Provides button-based remote control interface for the trading system.

Commands:
  /start - Show main menu with control buttons
  /menu - Same as /start
  /help - Show help information

All other functions are available through the interactive button menus.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir

try:
    from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
    from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed, command handler disabled")


class TelegramCommandHandler:
    """Full-featured command handler for PEARLalgo trading system."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        state_dir: Optional[Path] = None,
        startup_ping: bool = True,
    ):
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot required for command handler")
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.state_dir = ensure_state_dir(state_dir)
        self.exports_dir = self.state_dir / "exports"
        self._startup_ping = bool(startup_ping)
        self.application = (
            Application.builder()
            .token(bot_token)
            .post_init(self._post_init)
            .build()
        )
        self._register_handlers()

    async def _post_init(self, application: Application) -> None:
        """Runs once after the Telegram application initializes."""
        # Set minimal command surface for menu-based interface
        try:
            await application.bot.set_my_commands([
                BotCommand('start', 'Show main control menu'),
                BotCommand('menu', 'Show main control menu'),
                BotCommand('help', 'Show help information'),
            ])
        except Exception as e:
            logger.debug(f"Could not set bot commands: {e}")

        # Send a startup ping so users can confirm connectivity immediately.
        if self._startup_ping:
            try:
                logger.info(f"Sending startup ping to chat_id={self.chat_id}")
                # Send the main menu as startup message
                keyboard = [
                    [
                        InlineKeyboardButton("🚀 Start Agent", callback_data="start_agent"),
                        InlineKeyboardButton("🛑 Stop Agent", callback_data="stop_agent"),
                    ],
                    [
                        InlineKeyboardButton("🔌 Gateway Status", callback_data="gateway_status"),
                        InlineKeyboardButton("📊 System Status", callback_data="status"),
                    ],
                    [
                        InlineKeyboardButton("🎯 Signals & Trades", callback_data="signals"),
                        InlineKeyboardButton("📈 Performance", callback_data="performance"),
                    ],
                    [
                        InlineKeyboardButton("🛠️ Tools", callback_data="tools"),
                        InlineKeyboardButton("🤖 AI Features", callback_data="ai_menu"),
                    ],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await application.bot.send_message(
                    chat_id=self.chat_id,
                    text="✅ PEARLalgo command handler is online!\n\nTap the buttons below to control the system:",
                    reply_markup=reply_markup
                )
                logger.info("Startup ping sent")
            except Exception as e:
                # Do not crash the handler; reply_text() still works in any chat that sends commands.
                logger.warning(f"Could not send startup ping to chat_id={self.chat_id}: {e}")

    def _register_handlers(self) -> None:
        # Main menu commands
        self.application.add_handler(CommandHandler("start", self.handle_start))
        self.application.add_handler(CommandHandler("menu", self.handle_start))
        self.application.add_handler(CommandHandler("help", self.handle_help))

        # Callback query handler for button presses
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send the main menu with inline buttons."""
        if not update.message:
            return
        logger.info("Received /start or /menu command - showing main menu")

        text = (
            "🎯 PEARLalgo Trading System\n\n"
            "Tap the buttons below to control the system:"
        )

        keyboard = [
            [
                InlineKeyboardButton("🚀 Start Agent", callback_data="start_agent"),
                InlineKeyboardButton("🛑 Stop Agent", callback_data="stop_agent"),
            ],
            [
                InlineKeyboardButton("🔌 Gateway Status", callback_data="gateway_status"),
                InlineKeyboardButton("📊 System Status", callback_data="status"),
            ],
            [
                InlineKeyboardButton("🎯 Signals & Trades", callback_data="signals"),
                InlineKeyboardButton("📈 Performance", callback_data="performance"),
            ],
            [
                InlineKeyboardButton("🛠️ Tools", callback_data="tools"),
                InlineKeyboardButton("🤖 AI Features", callback_data="ai_menu"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(text, reply_markup=reply_markup)

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show help information."""
        if not update.message:
            return
        logger.info("Received /help command")

        text = (
            "🎯 PEARLalgo Command Handler\n\n"
            "Use /start or /menu to access the main control panel.\n\n"
            "Available commands:\n"
            "/start - Show main menu with buttons\n"
            "/menu - Same as /start\n"
            "/help - Show this help message\n\n"
            "All other functions are available through the button menus."
        )
        await update.message.reply_text(text)

    def _read_latest_metrics(self) -> Optional[dict]:
        if not self.exports_dir.exists():
            return None
        metrics_files = sorted(
            self.exports_dir.glob("performance_*_metrics.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not metrics_files:
            return None
        try:
            return json.loads(metrics_files[0].read_text(encoding="utf-8"))
        except Exception:
            return None

    def _read_strategy_selection(self) -> Optional[dict]:
        if not self.exports_dir.exists():
            return None
        candidates = list(self.exports_dir.glob("strategy_selection_*.json"))
        if not candidates:
            latest = self.exports_dir / "strategy_selection_latest.json"
            candidates = [latest] if latest.exists() else []
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        try:
            return json.loads(candidates[0].read_text(encoding="utf-8"))
        except Exception:
            return None

    async def handle_analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        logger.info("Received /analyze command")
        metrics = self._read_latest_metrics()
        selection = self._read_strategy_selection()

        lines = ["AI Strategy Report", f"Generated: {datetime.now(timezone.utc).isoformat()}"]

        if metrics:
            lines.extend(
                [
                    "",
                    "Performance (latest export):",
                    f"- Trades: {metrics.get('exited_signals', 0)}",
                    f"- Win rate: {metrics.get('win_rate', 0.0):.1%}",
                    f"- Total PnL: {metrics.get('total_pnl', 0.0):.2f}",
                    f"- Avg PnL: {metrics.get('avg_pnl', 0.0):.2f}",
                ]
            )
        else:
            lines.append("")
            lines.append("No performance metrics export found.")

        if selection:
            top = None
            ranked = selection.get("ranked_by_type_direction", [])
            if ranked:
                top = ranked[0]
            lines.append("")
            lines.append("Strategy recommendation:")
            if top:
                lines.append(f"- Top: {top.get('key')} (score {top.get('score', 0.0):.2f})")
                lines.append(f"- Trades: {top.get('count', 0)} | WR {top.get('win_rate', 0.0):.1%}")
                lines.append(f"- Max DD: {top.get('max_drawdown', 0.0):.2f}")
            else:
                lines.append("- No ranked strategy found in selection report.")
        else:
            lines.append("")
            lines.append("No strategy selection report found. Run:")
            lines.append("  python3 scripts/backtesting/strategy_selection.py")

        await update.message.reply_text("\n".join(lines))

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button callback queries."""
        query = update.callback_query
        if not query:
            return

        await query.answer()  # Acknowledge the callback
        callback_data = query.data
        logger.info(f"Received callback: {callback_data}")

        # Main menu actions
        if callback_data == "start_agent":
            await query.edit_message_text("🚀 Starting NQ Agent Service...")
        elif callback_data == "stop_agent":
            await query.edit_message_text("🛑 Stopping NQ Agent Service...")
        elif callback_data == "gateway_status":
            await query.edit_message_text("🔌 Gateway Status: Checking...")
        elif callback_data == "status":
            await query.edit_message_text("📊 System Status: Loading...")
        elif callback_data == "signals":
            await query.edit_message_text("🎯 Signals & Trades: Loading...")
        elif callback_data == "performance":
            await query.edit_message_text("📈 Performance: Loading metrics...")
        elif callback_data == "tools":
            # Show tools submenu
            keyboard = [
                [InlineKeyboardButton("📊 Backtest", callback_data="backtest")],
                [InlineKeyboardButton("📋 Reports", callback_data="reports")],
                [InlineKeyboardButton("🧪 Test Signal", callback_data="test_signal")],
                [InlineKeyboardButton("🔍 Data Quality", callback_data="data_quality")],
                [InlineKeyboardButton("⚙️ Config", callback_data="config")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="main_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("🛠️ Tools Menu:", reply_markup=reply_markup)
        elif callback_data == "ai_menu":
            # Show AI submenu
            keyboard = [
                [InlineKeyboardButton("🤖 AI Patch", callback_data="ai_patch")],
                [InlineKeyboardButton("🔍 Analyze", callback_data="analyze")],
                [InlineKeyboardButton("🧠 Claude Monitor", callback_data="claude_menu")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="main_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("🤖 AI Features:", reply_markup=reply_markup)
        elif callback_data == "claude_menu":
            # Show Claude submenu
            keyboard = [
                [InlineKeyboardButton("📋 Strategy Review", callback_data="review")],
                [InlineKeyboardButton("📈 Signal Analysis", callback_data="analyze_signals")],
                [InlineKeyboardButton("🔧 System Analysis", callback_data="analyze_system")],
                [InlineKeyboardButton("💡 Config Suggestions", callback_data="suggest_config")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="main_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("🧠 Claude Monitor:", reply_markup=reply_markup)
        elif callback_data == "main_menu":
            # Return to main menu
            keyboard = [
                [
                    InlineKeyboardButton("🚀 Start Agent", callback_data="start_agent"),
                    InlineKeyboardButton("🛑 Stop Agent", callback_data="stop_agent"),
                ],
                [
                    InlineKeyboardButton("🔌 Gateway Status", callback_data="gateway_status"),
                    InlineKeyboardButton("📊 System Status", callback_data="status"),
                ],
                [
                    InlineKeyboardButton("🎯 Signals & Trades", callback_data="signals"),
                    InlineKeyboardButton("📈 Performance", callback_data="performance"),
                ],
                [
                    InlineKeyboardButton("🛠️ Tools", callback_data="tools"),
                    InlineKeyboardButton("🤖 AI Features", callback_data="ai_menu"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("🎯 PEARLalgo Trading System\n\nTap the buttons below to control the system:", reply_markup=reply_markup)

        # Tool actions
        elif callback_data == "backtest":
            await query.edit_message_text("📊 Backtest: Starting strategy evaluation...")
        elif callback_data == "reports":
            await query.edit_message_text("📋 Reports: Browsing saved results...")
        elif callback_data == "test_signal":
            await query.edit_message_text("🧪 Test Signal: Generating sample signal...")
        elif callback_data == "data_quality":
            await query.edit_message_text("🔍 Data Quality: Checking freshness...")
        elif callback_data == "config":
            await query.edit_message_text("⚙️ Configuration: Loading settings...")

        # AI actions
        elif callback_data == "ai_patch":
            await query.edit_message_text("🤖 AI Patch: AI code generation not available")
        elif callback_data == "analyze":
            await query.edit_message_text("🔍 Analyze: Performance summary + strategy recommendation\n\n[Feature not fully implemented]")
        elif callback_data == "review":
            await query.edit_message_text("📋 Strategy Review: Analyzing performance...")
        elif callback_data == "analyze_signals":
            await query.edit_message_text("📈 Signal Analysis: AI analyzing signals...")
        elif callback_data == "analyze_system":
            await query.edit_message_text("🔧 System Analysis: Checking health...")
        elif callback_data == "suggest_config":
            await query.edit_message_text("💡 Config Suggestions: AI analyzing settings...")

        else:
            await query.edit_message_text(f"Unknown action: {callback_data}")

    def run(self) -> None:
        logger.info("Starting PEARLalgo Telegram Menu Handler")
        logger.info(f"Bot token: {'***' + self.bot_token[-4:] if len(self.bot_token) > 4 else '***'}")
        logger.info(f"Chat ID: {self.chat_id}")
        logger.info("Menu-based interface: use /start or /menu to access button controls")
        logger.info("Press Ctrl+C to stop")
        logger.info("Connecting to Telegram...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    import os
    
    # Load .env file (same pattern as other modules)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        logger.warning("python-dotenv not installed, using system environment variables only")
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in environment or .env file. "
            f"Current values: BOT_TOKEN={'***' if bot_token else 'NOT SET'}, CHAT_ID={'***' if chat_id else 'NOT SET'}"
        )
    handler = TelegramCommandHandler(bot_token=bot_token, chat_id=chat_id)
    handler.run()


if __name__ == "__main__":
    main()
