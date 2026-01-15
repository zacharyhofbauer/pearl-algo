"""
Minimal Telegram Command Handler for NQ Agent.

Commands:
  /analyze - performance + strategy selection summary
  /help    - list commands
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir

try:
    from telegram import Update, BotCommand
    from telegram.ext import Application, CommandHandler, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed, command handler disabled")


class TelegramCommandHandler:
    """Minimal command handler for AI insights only."""

    def __init__(self, bot_token: str, chat_id: str, state_dir: Optional[Path] = None):
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot required for command handler")
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.state_dir = ensure_state_dir(state_dir)
        self.exports_dir = self.state_dir / "exports"
        self.application = Application.builder().token(bot_token).build()
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.application.add_handler(CommandHandler("help", self.handle_help))
        self.application.add_handler(CommandHandler("analyze", self.handle_analyze))

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        text = (
            "Available commands:\n"
            "/analyze - performance summary + strategy recommendation\n"
            "/help - this message"
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

    def run(self) -> None:
        logger.info("Starting minimal Telegram Command Handler")
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
