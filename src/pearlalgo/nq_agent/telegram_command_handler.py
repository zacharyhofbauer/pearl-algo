"""
Telegram Command Handler for NQ Agent

Handles incoming Telegram commands and provides interactive bot functionality.
This can run as a separate service or be integrated into the main service.
"""

from __future__ import annotations

import asyncio
import json
import os
import math
import random
import hashlib
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Callable, Awaitable, List

import pandas as pd
import numpy as np

from pearlalgo.utils.logger import logger
from pearlalgo.backtesting.pdf_report import write_backtest_pdf_report

# SQLite "forever memory" (optional). Used for /doctor 24h rollups.
try:
    from pearlalgo.learning.trade_database import TradeDatabase
    TRADE_DB_AVAILABLE = True
except Exception:
    TRADE_DB_AVAILABLE = False
    TradeDatabase = None  # type: ignore

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
    from telegram.ext import (
        Application,
        CommandHandler,
        CallbackQueryHandler,
        ContextTypes,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed, command handler disabled")

from pearlalgo.nq_agent.state_manager import NQAgentStateManager
from pearlalgo.nq_agent.performance_tracker import PerformanceTracker
from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
from pearlalgo.utils.paths import get_signals_file, get_state_file, ensure_state_dir, get_utc_timestamp
from pearlalgo.utils.service_controller import ServiceController
from pearlalgo.utils.telegram_alerts import (
    format_signal_status,
    format_signal_direction,
    format_signal_confidence_tier,
    format_pnl,
    format_time_ago,
    format_home_card,
    format_gate_status,
    format_service_status,
    format_session_window,
    safe_label,
    escape_subprocess_output,
    _format_currency,
    TelegramPrefs,
    # Standardized terminology constants
    LABEL_AGENT,
    LABEL_GATEWAY,
    LABEL_ACTIVE_TRADES,
    LABEL_SCANS,
    LABEL_BUFFER,
    LABEL_FUTURES,
    LABEL_SESSION,
    STATE_RUNNING,
    STATE_STOPPED,
    STATE_PAUSED,
    GATE_OPEN,
    GATE_CLOSED,
)

try:
    from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
    CHART_GENERATOR_AVAILABLE = True
except ImportError:
    CHART_GENERATOR_AVAILABLE = False
    ChartGenerator = None
    ChartConfig = None

# Claude client for /ai_patch command and Claude hub (optional [llm] extra)
try:
    from pearlalgo.utils.claude_client import (
        ClaudeClient,
        ClaudeClientError,
        ClaudeNotAvailableError,
        ClaudeAPIKeyMissingError,
        ClaudeAPIError,
        ANTHROPIC_AVAILABLE,
        get_claude_client,
        build_chat_system_prompt,
    )
except ImportError:
    ANTHROPIC_AVAILABLE = False
    ClaudeClient = None  # type: ignore
    ClaudeClientError = Exception  # type: ignore
    ClaudeNotAvailableError = Exception  # type: ignore
    ClaudeAPIKeyMissingError = Exception  # type: ignore
    ClaudeAPIError = Exception  # type: ignore
    get_claude_client = lambda: None  # type: ignore
    build_chat_system_prompt = lambda system_snapshot=None, memory_summary=None: ""  # type: ignore


class TelegramCommandHandler:
    """
    Handles Telegram bot commands and callbacks.
    
    This class processes incoming Telegram commands and provides
    interactive functionality for the NQ Agent bot.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize command handler.
        
        Args:
            bot_token: Telegram bot token
            chat_id: Authorized chat ID
            state_dir: State directory for reading agent data
        """
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot required for command handler")
        
        self.bot_token = bot_token
        self.chat_id = chat_id
        # Track whether caller explicitly provided a state_dir (tests do this via tmp_path).
        # When explicit, any SQLite reads should prefer that directory to avoid coupling tests
        # to the live agent DB path from config.yaml.
        self._explicit_state_dir = state_dir is not None
        self.state_dir = ensure_state_dir(state_dir)
        self.state_manager = NQAgentStateManager(state_dir=state_dir)
        self.performance_tracker = PerformanceTracker(
            state_dir=state_dir,
            state_manager=self.state_manager,
        )
        self.telegram_notifier = NQAgentTelegramNotifier(
            bot_token=bot_token,
            chat_id=chat_id,
        )
        
        # Initialize service controller for remote control
        self.service_controller = ServiceController()
        
        # Initialize Telegram UI preferences
        self.prefs = TelegramPrefs(state_dir=state_dir)
        
        # Initialize chart generator if available
        self.chart_generator = None
        if CHART_GENERATOR_AVAILABLE:
            try:
                self.chart_generator = ChartGenerator()
            except Exception as e:
                logger.warning(f"Could not initialize ChartGenerator: {e}")
        
        # Data provider for fetching historical data (lazy initialization)
        self._data_provider = None
        self._historical_cache_dir = Path(self.state_dir.parent / "historical")
        self._historical_cache_dir.mkdir(parents=True, exist_ok=True)

        # SQLite trade database (lazy initialization)
        self._trade_db = None
        
        # 50k Challenge tracker (lazy initialization)
        self._challenge_tracker = None
        
        # Build application
        self.application = Application.builder().token(bot_token).build()
        
        # Register handlers
        self._register_handlers()

        # Persistent Claude chat history (survives handler restarts)
        self._claude_chat_history_file = self.state_dir / "claude_chat_history.json"
        # Rolling "operator memory" summary (keeps Claude consistent without long history)
        self._claude_memory_summary_file = self.state_dir / "claude_memory_summary.txt"

    def _load_persistent_claude_chat_history(self) -> List[Dict[str, str]]:
        """Load Claude chat history from disk (best-effort)."""
        try:
            if not self._claude_chat_history_file.exists():
                return []
            with open(self._claude_chat_history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return []
            out: List[Dict[str, str]] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                role = item.get("role")
                content = item.get("content")
                if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                    out.append({"role": role, "content": content})
            return out
        except Exception as e:
            logger.debug(f"Could not load Claude chat history: {e}")
            return []

    def _save_persistent_claude_chat_history(self, history: List[Dict[str, str]]) -> None:
        """Save Claude chat history to disk (best-effort)."""
        try:
            self._claude_chat_history_file.parent.mkdir(parents=True, exist_ok=True)
            # Keep bounded on disk as well
            bounded = history[-40:] if len(history) > 40 else history
            with open(self._claude_chat_history_file, "w", encoding="utf-8") as f:
                json.dump(bounded, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"Could not save Claude chat history: {e}")

    def _clear_persistent_claude_chat_history(self) -> None:
        """Remove persisted Claude chat history file (best-effort)."""
        try:
            if self._claude_chat_history_file.exists():
                self._claude_chat_history_file.unlink()
        except Exception as e:
            logger.debug(f"Could not clear Claude chat history: {e}")

    def _load_claude_memory_summary(self) -> str:
        """Load the rolling Claude memory summary (best-effort)."""
        try:
            if not self._claude_memory_summary_file.exists():
                return ""
            text = self._claude_memory_summary_file.read_text(encoding="utf-8", errors="replace").strip()
            # Keep bounded
            if len(text) > 2000:
                text = text[:2000] + "\n...(truncated)"
            return text
        except Exception as e:
            logger.debug(f"Could not load Claude memory summary: {e}")
            return ""

    def _save_claude_memory_summary(self, summary: str) -> None:
        """Save the rolling Claude memory summary (best-effort)."""
        try:
            self._claude_memory_summary_file.parent.mkdir(parents=True, exist_ok=True)
            text = str(summary).strip()
            # Clamp to ~10 lines
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            text = "\n".join(lines[:10])
            self._claude_memory_summary_file.write_text(text, encoding="utf-8")
        except Exception as e:
            logger.debug(f"Could not save Claude memory summary: {e}")

    def _clear_claude_memory_summary(self) -> None:
        """Clear the rolling Claude memory summary (best-effort)."""
        try:
            if self._claude_memory_summary_file.exists():
                self._claude_memory_summary_file.unlink()
        except Exception as e:
            logger.debug(f"Could not clear Claude memory summary: {e}")

    async def _update_claude_memory_summary(
        self,
        overflow_messages: List[Dict[str, str]],
    ) -> None:
        """
        Update the rolling Claude memory summary using Claude (best-effort).

        Called when chat history grows too large; we summarize older messages into a durable memory.
        """
        if not overflow_messages:
            return

        client = get_claude_client()
        if not client:
            return

        prev = self._load_claude_memory_summary()

        # Format transcript compactly
        transcript_lines: List[str] = []
        for m in overflow_messages[:60]:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            content = content.replace("\n", " ").strip()
            if len(content) > 240:
                content = content[:240] + "…"
            transcript_lines.append(f"{role.upper()}: {content}")

        transcript = "\n".join(transcript_lines).strip()
        if not transcript:
            return

        system_prompt = (
            "You are a summarization engine for an operator 'memory' used by an AI assistant.\n"
            "Update the memory summary with any durable facts: user goals, preferences, constraints, current focus, and recent decisions.\n"
            "Rules:\n"
            "- Output at most 10 lines.\n"
            "- Each line should start with '- '.\n"
            "- Do NOT include secrets, keys, tokens, or credentials.\n"
            "- Be concrete and specific; avoid filler.\n"
        )

        user_text = (
            "PREVIOUS MEMORY:\n"
            f"{prev}\n\n"
            "NEW TRANSCRIPT (incorporate into memory):\n"
            f"{transcript}\n\n"
            "Return the UPDATED MEMORY now."
        )

        import asyncio

        try:
            updated = await asyncio.to_thread(
                client.chat,
                [{"role": "user", "content": user_text}],
                system_prompt,
            )
            if isinstance(updated, str) and updated.strip():
                self._save_claude_memory_summary(updated)
        except Exception as e:
            logger.debug(f"Could not update memory summary: {e}")
        
    def _register_handlers(self):
        """Register command and callback handlers."""
        from telegram.ext import MessageHandler, filters
        
        # Add a message handler to log all incoming messages for debugging (low priority)
        async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.message and update.message.text:
                logger.info(f"📨 Incoming message from chat {update.effective_chat.id}: {update.message.text}")
            elif update.callback_query:
                logger.info(f"🔘 Incoming callback from chat {update.effective_chat.id}: {update.callback_query.data}")
        
        # Add logging handler with low priority (so commands are processed first)
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_all_updates), group=99)
        
        # Command handlers
        # Button-first UX: /start is the only supported slash command.
        # All other actions are accessible via inline buttons.
        self.application.add_handler(CommandHandler("start", self._handle_start))
        
        # Commands that require arguments (can't be done via buttons alone)
        self.application.add_handler(CommandHandler("signal", self._handle_signal_detail))
        self.application.add_handler(CommandHandler("grade", self._handle_grade))
        self.application.add_handler(CommandHandler("performance", self._handle_performance))
        self.application.add_handler(CommandHandler("doctor", self._handle_doctor))
        self.application.add_handler(CommandHandler("brain", self._handle_brain))

        # Friendly fallback for any other slash command: point users back to /start.
        async def _unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                if update.message and update.message.text and update.message.text.strip().lower().startswith("/start"):
                    return
            except Exception:
                pass
            try:
                if update.message:
                    await update.message.reply_text("ℹ️ This bot is button-driven. Tap /start and use the buttons.")
            except Exception:
                pass
        self.application.add_handler(MessageHandler(filters.COMMAND, _unknown_command), group=90)

        # Claude message handler (for chat mode and wizard text input)
        # Must be added AFTER command handlers, lower priority group
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_claude_message),
            group=1  # Lower priority than logging handler
        )
        
        # Callback query handler (for inline buttons)
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))
    
    def _is_agent_process_running(self) -> bool:
        """
        Best-effort check to see if the NQ Agent service process is running.
        
        Uses the PID file created by lifecycle scripts, and falls back to a
        lightweight /proc scan if needed.
        """
        try:
            project_root = Path(__file__).parent.parent.parent.parent
            pid_file = project_root / "logs" / "nq_agent.pid"
            
            # Prefer PID file (matches lifecycle scripts + service runner)
            if pid_file.exists():
                try:
                    pid_text = pid_file.read_text().strip()
                    if not pid_text:
                        return False
                    pid = int(pid_text)
                except Exception:
                    return False
                
                try:
                    # os.kill(pid, 0) checks if process exists without sending a signal
                    os.kill(pid, 0)
                    return True
                except OSError:
                    return False
            
            # Fallback: scan /proc for pearlalgo.nq_agent.main
            proc_root = Path("/proc")
            if not proc_root.exists():
                return False
            
            for entry in proc_root.iterdir():
                if not entry.is_dir() or not entry.name.isdigit():
                    continue
                cmdline_path = entry / "cmdline"
                try:
                    cmd = cmdline_path.read_text(errors="ignore")
                    if "pearlalgo.nq_agent.main" in cmd:
                        return True
                except Exception:
                    continue
        except Exception:
            # Fail closed: if we can't verify, treat as not running
            return False
        
        return False

    def _get_signals_file_stats(self, signals_file: Path) -> Dict:
        """
        Get quick diagnostics for signals.jsonl.

        Returns counts of total non-empty lines, valid JSON records, and parse errors.
        """
        stats: Dict = {
            "exists": False,
            "size_bytes": 0,
            "lines": 0,
            "valid": 0,
            "invalid": 0,
        }

        try:
            if not signals_file.exists():
                return stats

            stats["exists"] = True
            stats["size_bytes"] = int(signals_file.stat().st_size)
            if stats["size_bytes"] == 0:
                return stats

            with open(signals_file, "r") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    stats["lines"] += 1
                    try:
                        json.loads(line)
                        stats["valid"] += 1
                    except json.JSONDecodeError:
                        stats["invalid"] += 1

            return stats
        except Exception as e:
            logger.debug(f"Could not compute signals file stats: {e}")
            return stats

    def _get_trades_for_chart(self, chart_data: Optional[pd.DataFrame], *, symbol: str = "MNQ") -> List[Dict]:
        """
        Build a compact list of recent trades (entries/exits) that fall within the chart window.

        This is used to overlay trade markers on `/chart` images so users can visually
        relate recent P&L outcomes to price action.
        """
        try:
            if chart_data is None or not isinstance(chart_data, pd.DataFrame) or chart_data.empty:
                return []

            # Determine chart time window (normalize to naive UTC for stable comparisons)
            tmin = None
            tmax = None
            if "timestamp" in chart_data.columns:
                ts = pd.to_datetime(chart_data["timestamp"], errors="coerce")
                ts = ts.dropna()
                if ts.empty:
                    return []
                tmin = pd.Timestamp(ts.min())
                tmax = pd.Timestamp(ts.max())
            elif isinstance(chart_data.index, pd.DatetimeIndex) and len(chart_data.index) > 0:
                tmin = pd.Timestamp(chart_data.index.min())
                tmax = pd.Timestamp(chart_data.index.max())
            if tmin is None or tmax is None:
                return []

            def _to_utc_naive(x):
                if not x:
                    return None
                try:
                    tsx = pd.Timestamp(x)
                except Exception:
                    return None
                try:
                    if tsx.tzinfo is not None:
                        tsx = tsx.tz_convert("UTC").tz_localize(None)
                except Exception:
                    # If tz_convert fails, fall back to stripping tz
                    try:
                        tsx = tsx.tz_localize(None)
                    except Exception:
                        pass
                return tsx

            tmin_u = _to_utc_naive(tmin)
            tmax_u = _to_utc_naive(tmax)
            if tmin_u is None or tmax_u is None:
                return []

            # Pull recent signals (append-only), filter to entered/exited within the window.
            try:
                recent = self.state_manager.get_recent_signals(limit=500)
            except Exception:
                recent = []

            symbol_norm = str(symbol or "MNQ").upper()
            trades: List[Dict] = []
            for rec in recent:
                if not isinstance(rec, dict):
                    continue
                status = str(rec.get("status") or "").lower()
                if status not in ("entered", "exited"):
                    continue

                sig = rec.get("signal", {}) or {}
                sym = str(sig.get("symbol") or symbol_norm).upper()
                if sym != symbol_norm:
                    continue

                entry_time_raw = rec.get("entry_time") or sig.get("timestamp") or rec.get("timestamp")
                entry_time = _to_utc_naive(entry_time_raw)
                if entry_time is None:
                    continue

                exit_time_raw = rec.get("exit_time") if status == "exited" else None
                exit_time = _to_utc_naive(exit_time_raw) if exit_time_raw else None

                # Include if entry or exit is inside window, or trade spans across it.
                in_window = (tmin_u <= entry_time <= tmax_u)
                if exit_time is not None:
                    in_window = in_window or (tmin_u <= exit_time <= tmax_u) or (entry_time <= tmax_u and exit_time >= tmin_u)
                if not in_window:
                    continue

                trades.append(
                    {
                        "signal_id": str(rec.get("signal_id") or ""),
                        "direction": str(sig.get("direction") or "long"),
                        "entry_time": entry_time_raw,
                        "entry_price": rec.get("entry_price") or sig.get("entry_price"),
                        "exit_time": exit_time_raw,
                        "exit_price": rec.get("exit_price") if status == "exited" else None,
                        "exit_reason": rec.get("exit_reason"),
                        "pnl": rec.get("pnl") if status == "exited" else None,
                        "is_win": rec.get("is_win") if status == "exited" else None,
                        "status": status,
                    }
                )

            # Keep only the most recent N to avoid chart clutter.
            return trades[-20:]
        except Exception:
            return []

    # -------------------------------------------------------------------------
    # State parsing helpers (robust fallback chain for data age / price)
    # -------------------------------------------------------------------------

    def _extract_data_age_minutes(self, state: Dict) -> Optional[float]:
        """
        Extract data age in minutes from state with robust fallback chain.

        Priority:
          1. state["latest_bar_age_minutes"] (pre-computed by service)
          2. Parse state["latest_bar_timestamp"] (ISO string)
          3. Parse state["latest_bar"]["timestamp"] (nested dict)

        Returns None if unavailable.
        """
        # 1. Pre-computed age (most reliable when present)
        try:
            age = state.get("latest_bar_age_minutes")
            if age is not None:
                return float(age)
        except Exception:
            pass

        # 2. Parse top-level latest_bar_timestamp
        ts_str = state.get("latest_bar_timestamp")
        if ts_str:
            age = self._timestamp_to_age_minutes(ts_str)
            if age is not None:
                return age

        # 3. Parse nested latest_bar.timestamp
        latest_bar = state.get("latest_bar")
        if isinstance(latest_bar, dict):
            ts_str = latest_bar.get("timestamp")
            if ts_str:
                age = self._timestamp_to_age_minutes(ts_str)
                if age is not None:
                    return age

        return None

    def _timestamp_to_age_minutes(self, ts_str: str) -> Optional[float]:
        """Convert ISO timestamp string to age in minutes (now - ts)."""
        try:
            from pearlalgo.utils.paths import parse_utc_timestamp

            ts = parse_utc_timestamp(str(ts_str))
            if ts is None:
                return None
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_delta = datetime.now(timezone.utc) - ts
            return age_delta.total_seconds() / 60.0
        except Exception:
            return None

    def _extract_latest_price(self, state: Dict) -> Optional[float]:
        """
        Extract latest price from state with fallback chain.

        Priority:
          1. state["latest_bar"]["close"]
          2. state["latest_price"] (legacy / push dashboard field)
        """
        # 1. Nested latest_bar.close
        latest_bar = state.get("latest_bar")
        if isinstance(latest_bar, dict):
            close = latest_bar.get("close")
            if close is not None:
                try:
                    return float(close)
                except Exception:
                    pass

        # 2. Top-level latest_price (fallback)
        lp = state.get("latest_price")
        if lp is not None:
            try:
                return float(lp)
            except Exception:
                pass

        return None

    def _compute_state_stale_threshold(self, state: Dict) -> float:
        """
        Compute a sensible state staleness threshold based on configured cadence.

        Default: 2 * state_save_interval * scan_interval (in seconds).
        Floor: 120s to avoid over-sensitive warnings.

        The service saves state every state_save_interval cycles, and each cycle
        takes scan_interval seconds. Allow 2x headroom before flagging.
        """
        try:
            from pearlalgo.config.config_loader import load_service_config

            cfg = load_service_config()
            service_cfg = cfg.get("service", {})
            state_save_interval = int(service_cfg.get("state_save_interval", 10))
        except Exception:
            state_save_interval = 10

        # Scan interval from state (persisted by service)
        scan_interval = 60  # default
        try:
            config_block = state.get("config", {})
            if isinstance(config_block, dict):
                scan_interval = int(config_block.get("scan_interval", 60))
        except Exception:
            pass

        threshold = float(2 * state_save_interval * scan_interval)
        # Floor at 120s to avoid false warnings during normal operation
        return max(threshold, 120.0)

    # Control panel persistence removed (per user request to simplify)
    
    async def _check_authorized(self, update: Update) -> bool:
        """Check if update is from authorized chat."""
        if not update.effective_chat:
            logger.warning("Update has no effective_chat")
            return False
        chat_id = update.effective_chat.id
        authorized = str(chat_id) == str(self.chat_id)
        if not authorized:
            logger.warning(
                f"Unauthorized Telegram access attempt from chat_id={chat_id} (expected {self.chat_id})",
                extra={"chat_id": chat_id, "username": getattr(update.effective_user, 'username', None)},
            )
        else:
            logger.debug(f"Authorized access from chat_id={chat_id}")
        return authorized
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - shows status screen directly."""
        logger.info(f"Received /start command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Show status screen directly (no welcome message)
        await self._handle_status(update, context)
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        message = (
            "📚 *Help*\n\n"
            "*Navigation:* Use buttons below each view.\n\n"
            "*Key Commands:*\n"
            "• /status - Agent status + Home Card\n"
            "• /signals - Signal history\n"
            "• /chart - On-demand chart\n"
            "• /settings - UI preferences\n\n"
            "*Actions:*\n"
            "• Service Control: Start/Stop Agent & Gateway\n"
            "• Monitoring: Status, Signals, Performance, Activity\n"
            "• Data: Quality checks, Backtest, Reports\n\n"
            "💡 `/start` keeps the menu minimal — advanced tools are still available via commands."
        )
        
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
    
    async def _handle_glossary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /glossary or /explain command - show definitions for key terms.
        
        Provides concise explanations for:
        - Scans vs Signals
        - Pressure (buy/sell)
        - MTF (multi-timeframe)
        - Gates (Futures/Session)
        - Active Trades
        """
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Check if a specific term was requested
        args = context.args if context.args else []
        
        # Define glossary entries
        glossary = {
            "scans": (
                "🔄 *Scans*\n"
                "Each scan is one iteration of the strategy loop. "
                "The agent scans market data at regular intervals "
                "(e.g., every 60s) looking for trading setups. "
                "High scan count = agent is actively working."
            ),
            "signals": (
                "🔔 *Signals*\n"
                "A signal is a trading opportunity detected by the strategy. "
                "Signals go through stages: generated → sent → entered → exited. "
                "'Generated' means a pattern matched; 'Sent' means it was delivered to Telegram."
            ),
            "pressure": (
                "📊 *Buy/Sell Pressure*\n"
                "Shows order flow imbalance from Level 2 data. "
                "Positive = more buy pressure; Negative = more sell pressure. "
                "Helps gauge short-term market sentiment. "
                "Only available with Level 2 market data subscription."
            ),
            "mtf": (
                "📈 *MTF (Multi-Timeframe)*\n"
                "Shows trend direction across multiple timeframes (5m, 15m, 1h, 4h, 1D). "
                "⬆️ = bullish, ⬇️ = bearish, ➡️ = neutral. "
                "Helps assess if trends align across timeframes for higher-probability trades."
            ),
            "gates": (
                "🚦 *Gates (Futures/Session)*\n"
                f"• *{LABEL_FUTURES}:* CME futures market hours (includes ETH). "
                "When closed, no live data flows.\n"
                f"• *{LABEL_SESSION}:* Strategy's configured trading window. "
                "Signals are suppressed outside this window. "
                "See /config for the exact session times."
            ),
            "active_trades": (
                f"🎯 *{LABEL_ACTIVE_TRADES}*\n"
                "Currently open positions (signals with status='entered'). "
                "These are being monitored for stop-loss and take-profit levels. "
                "Use /active_trades to see details and unrealized P&L."
            ),
            "buffer": (
                f"📊 *Buffer ({LABEL_BUFFER})*\n"
                "Rolling window of recent price bars held in memory. "
                "Required for technical analysis calculations. "
                "Low buffer count means insufficient data for reliable signals."
            ),
        }
        
        if args:
            term = args[0].lower()
            if term in glossary:
                message = glossary[term]
            else:
                message = (
                    f"❓ Unknown term: `{term}`\n\n"
                    "Available terms: " + ", ".join(f"`{k}`" for k in glossary.keys())
                )
        else:
            # Show all terms in compact format
            message = "📚 *Glossary*\n\n"
            message += "Tap a button below for detailed explanation, or use `/glossary <term>`.\n\n"
            message += "*Quick Reference:*\n"
            message += f"• *Scans* – Strategy loop iterations\n"
            message += f"• *Signals* – Detected trading opportunities\n"
            message += f"• *Pressure* – Order flow imbalance\n"
            message += f"• *MTF* – Multi-timeframe trend alignment\n"
            message += f"• *Gates* – Market hours & session windows\n"
            message += f"• *{LABEL_ACTIVE_TRADES}* – Open positions\n"
            message += f"• *Buffer* – Rolling price data\n"
        
        # Build drill-down buttons
        keyboard = [
            [
                InlineKeyboardButton("🔄 Scans", callback_data="glossary_scans"),
                InlineKeyboardButton("🔔 Signals", callback_data="glossary_signals"),
            ],
            [
                InlineKeyboardButton("📊 Pressure", callback_data="glossary_pressure"),
                InlineKeyboardButton("📈 MTF", callback_data="glossary_mtf"),
            ],
            [
                InlineKeyboardButton("🚦 Gates", callback_data="glossary_gates"),
                InlineKeyboardButton("🎯 Trades", callback_data="glossary_active_trades"),
            ],
            [InlineKeyboardButton("🏠 Menu", callback_data="start")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
    
    async def _handle_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /settings command - show and manage Telegram UI preferences.
        
        Provides toggles for:
        - Dashboard buttons on push alerts
        - Expanded signal details
        - Auto-chart on signal push
        - Snooze non-critical alerts
        """
        logger.info(f"Received /settings command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        await self._render_settings_menu(update, context)
    
    async def _render_settings_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Render the settings menu with current preference values."""
        prefs = self.prefs.all()
        
        def toggle_icon(key: str) -> str:
            """Get toggle icon for a boolean setting."""
            return "✅" if prefs.get(key, False) else "⬜"
        
        message = "⚙️ *Telegram Settings*\n\n"
        message += "Customize your Telegram UI experience. Changes take effect immediately.\n\n"
        
        # Dashboard buttons
        message += f"{toggle_icon('dashboard_buttons')} *Dashboard Buttons*\n"
        message += "   Add quick-action navigation buttons to dashboards & alerts\n\n"
        
        # Signal detail verbosity
        message += f"{toggle_icon('signal_detail_expanded')} *Expanded Signal Details*\n"
        message += "   Show full context (regime, MTF, VWAP) by default\n\n"
        
        # Auto-chart on signal
        message += f"{toggle_icon('auto_chart_on_signal')} *Auto-Chart on Signal*\n"
        message += "   Automatically send chart with each signal alert\n\n"
        
        # Interval notifications
        message += f"{toggle_icon('interval_notifications')} *Interval Notifications*\n"
        message += "   Hourly chart + status notifications\n\n"
        
        # Snooze non-critical alerts
        snooze_active = self.prefs.snooze_noncritical_alerts
        snooze_icon = "🔕" if snooze_active else "🔔"
        message += f"{snooze_icon} *Snooze Non-Critical Alerts*\n"
        if snooze_active:
            snooze_until = prefs.get("snooze_until")
            if snooze_until:
                try:
                    from datetime import datetime, timezone
                    expiry = datetime.fromisoformat(str(snooze_until).replace("Z", "+00:00"))
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                    remaining = (expiry - datetime.now(timezone.utc)).total_seconds() / 60
                    message += f"   🔕 Snoozed for {remaining:.0f} more minutes\n\n"
                except Exception:
                    message += "   🔕 Currently snoozed\n\n"
            else:
                message += "   🔕 Currently snoozed\n\n"
        else:
            message += "   Temporarily suppress non-critical data alerts\n\n"
        
        message += "💡 *Tip:* Tap a button to toggle a setting."
        
        # Build settings buttons
        keyboard = [
            # Navigation / secondary tools (kept here to keep /start uncluttered)
            [
                InlineKeyboardButton("❓ Help", callback_data="help"),
                InlineKeyboardButton("⚙️ Config", callback_data="config"),
            ],
        ]

        # Preferences (toggles)
        keyboard += [
            [
                InlineKeyboardButton(
                    f"{toggle_icon('dashboard_buttons')} Dashboard Buttons",
                    callback_data="settings:toggle:dashboard_buttons"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{toggle_icon('signal_detail_expanded')} Expanded Details",
                    callback_data="settings:toggle:signal_detail_expanded"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{toggle_icon('auto_chart_on_signal')} Auto-Chart",
                    callback_data="settings:toggle:auto_chart_on_signal"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{toggle_icon('interval_notifications')} Interval Notifications",
                    callback_data="settings:toggle:interval_notifications"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{snooze_icon} {'Unsnooze Alerts' if snooze_active else 'Snooze 1h'}",
                    callback_data="settings:snooze"
                ),
            ],
            [
                InlineKeyboardButton("🔄 Reset Defaults", callback_data="settings:reset"),
                InlineKeyboardButton("🧹 Purge Test Data", callback_data="settings:purge_test"),
            ],
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="settings"),
            InlineKeyboardButton("🏠 Menu", callback_data="start"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
    
    async def _handle_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /chart command - generate and send on-demand dashboard chart.
        
        Usage: /chart [hours]
        - hours: lookback window (default: 6, max: 24)
        """
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
        
        try:
            if not self.chart_generator:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Chart generator not available.\n\n"
                    "💡 Ensure matplotlib and mplfinance are installed.",
                    reply_markup=self._get_back_to_menu_button()
                )
                return
            
            # Parse optional hours argument
            args = context.args if context.args else []
            lookback_hours = 12.0  # default (matches dashboard chart default)
            if args:
                try:
                    lookback_hours = float(args[0])
                    lookback_hours = max(1.0, min(24.0, lookback_hours))  # clamp 1-24h
                except ValueError:
                    pass
            
            # Get data provider
            data_provider = self._get_data_provider()
            if data_provider is None:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Data provider not available.\n\n"
                    "💡 Check Gateway status and try again.",
                    reply_markup=self._get_back_to_menu_button()
                )
                return
            
            # Fetch historical data
            symbol = "MNQ"
            timeframe = "5m"
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=lookback_hours)
            
            loop = asyncio.get_running_loop()
            bars = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: data_provider.fetch_historical(
                        symbol=symbol,
                        start=start_time,
                        end=end_time,
                        timeframe=timeframe,
                    ),
                ),
                timeout=30.0,
            )
            
            if bars is None or (isinstance(bars, pd.DataFrame) and bars.empty) or (isinstance(bars, list) and len(bars) == 0):
                await self._send_message_or_edit(
                    update, context,
                    "❌ No data available for chart.\n\n"
                    "💡 Check Gateway connection or try again later.",
                    reply_markup=self._get_back_to_menu_button()
                )
                return
            
            # Convert to DataFrame if needed
            if isinstance(bars, list):
                df = pd.DataFrame(bars)
            else:
                df = bars
            
            if df.empty:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Insufficient data for chart.",
                    reply_markup=self._get_back_to_menu_button()
                )
                return
            
            # Generate chart
            # ChartGenerator uses lookback_bars (not hours). Convert hours → bars for the chosen timeframe.
            # /chart currently uses 5m bars (12 bars/hour).
            tf_minutes = 5
            try:
                if isinstance(timeframe, str) and timeframe.endswith("m"):
                    tf_minutes = max(1, int(timeframe[:-1]))
            except Exception:
                tf_minutes = 5

            lookback_bars = int(round((lookback_hours * 60.0) / float(tf_minutes)))
            lookback_bars = max(20, lookback_bars)  # ensure enough context for indicators/overlays

            # Use the exact same window for both chart rendering and trade overlay filtering.
            chart_data = df.tail(min(int(lookback_bars), len(df))).copy()
            range_label = f"{int(round(lookback_hours))}h"
            trades = self._get_trades_for_chart(chart_data, symbol=symbol)

            chart_path = self.chart_generator.generate_dashboard_chart(
                chart_data,
                symbol=symbol,
                timeframe=timeframe,
                lookback_bars=len(chart_data),
                range_label=range_label,
                show_pressure=True,
                trades=trades,
            )
            
            if chart_path and chart_path.exists():
                from pathlib import Path
                caption = f"📊 *{symbol}* {timeframe} Chart ({lookback_hours:.0f}h)\n"
                caption += f"🕐 Generated: {end_time.strftime('%H:%M UTC')}"
                
                # Navigation buttons only (single 12h timeframe, no toggles needed)
                keyboard = [
                    [
                        InlineKeyboardButton("🏠 Menu", callback_data="start"),
                        InlineKeyboardButton("🎯 Signals & Trades", callback_data="signals"),
                    ],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=open(chart_path, "rb"),
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=reply_markup,
                )
                
                # Clean up temp file
                try:
                    chart_path.unlink()
                except Exception:
                    pass
            else:
                await self._send_message_or_edit(
                    update, context,
                    "📊 *Chart Unavailable*\n\n"
                    "Chart generation did not produce an image.\n\n"
                    "*What to try:*\n"
                    "• Wait a few minutes for data to accumulate\n"
                    "• Check /data_quality for data issues\n"
                    "• Try a shorter timeframe (12h)",
                    reply_markup=self._get_back_to_menu_button()
                )
                
        except asyncio.TimeoutError:
            await self._send_message_or_edit(
                update, context,
                "⏱️ *Chart Timed Out*\n\n"
                "Chart generation took too long.\n\n"
                "*What to try:*\n"
                "• Try again in a moment\n"
                "• Check /data_quality for connection issues\n"
                "• Use a shorter timeframe",
                reply_markup=self._get_back_to_menu_button()
            )
        except Exception as e:
            logger.error(f"Error handling chart command: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                "📊 *Chart Unavailable*\n\n"
                "Something went wrong generating the chart.\n\n"
                "*What to try:*\n"
                "• Try again in a moment\n"
                "• Check /data_quality for data issues\n"
                "• If problem persists, check logs",
                reply_markup=self._get_back_to_menu_button()
            )
    
    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - unified Home Card view."""
        logger.info(f"Received /status command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            # Get gateway status first (needed for both message and buttons)
            gateway_status = self.service_controller.get_gateway_status()
            gateway_running = gateway_status.get("process_running", False)
            gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
            
            # Load state
            state_file = get_state_file(self.state_dir)
            if not state_file.exists():
                # No state file - show minimal Home Card with start prompt
                process_running = self._is_agent_process_running()
                message = format_home_card(
                    symbol="MNQ",
                    time_str=self._get_current_time_str(),
                    agent_running=process_running,
                    gateway_running=gateway_running,
                    futures_market_open=None,
                    strategy_session_open=None,
                )
                message += "\n\n⚠️ *No state file found*\n"
                message += "Agent may not have run yet. Start agent to begin."
                
                reply_markup = self._get_main_menu_buttons(
                    agent_running=process_running,
                    gateway_running=gateway_running,
                    gateway_api_ready=gateway_api_ready,
                )
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                return
            
            with open(state_file) as f:
                state = json.load(f)
            
            # Determine if the actual service process is running
            process_running = self._is_agent_process_running()
            
            # Build status from state
            state_running = state.get("running", False)
            running = process_running and state_running
            paused = state.get("paused", False)
            pause_reason = state.get("pause_reason") or None
            
            # Extract metrics from state
            cycles_total = int(state.get("cycle_count", 0) or 0)
            cycles_session = state.get("cycle_count_session")
            try:
                cycles_session = int(cycles_session) if cycles_session is not None else None
            except Exception:
                cycles_session = None
            
            signals_generated = int(state.get("signal_count", 0) or 0)
            try:
                signals_sent = int(state.get("signals_sent", 0) or 0)
            except Exception:
                signals_sent = 0
            
            errors = int(state.get("error_count", 0) or 0)
            buffer_size = int(state.get("buffer_size", 0) or 0)
            buffer_target = state.get("buffer_size_target")
            try:
                buffer_target = int(buffer_target) if buffer_target is not None else None
            except Exception:
                buffer_target = None
            
            # Signal send failures (for error cue in Home Card)
            signal_send_failures = 0
            try:
                signal_send_failures = int(state.get("signals_send_failures", 0) or 0)
            except Exception:
                signal_send_failures = 0
            
            # Compute state file freshness (for liveness cue)
            state_age_seconds = None
            try:
                mtime = state_file.stat().st_mtime
                state_age_seconds = (datetime.now(timezone.utc).timestamp() - mtime)
            except Exception:
                state_age_seconds = None
            
            # Compute activity pulse from last_successful_cycle (more accurate than state file mtime)
            last_cycle_seconds = None
            try:
                last_cycle_ts = state.get("last_successful_cycle")
                if last_cycle_ts:
                    from pearlalgo.utils.paths import parse_utc_timestamp
                    last_cycle_dt = parse_utc_timestamp(str(last_cycle_ts))
                    if last_cycle_dt:
                        if last_cycle_dt.tzinfo is None:
                            last_cycle_dt = last_cycle_dt.replace(tzinfo=timezone.utc)
                        last_cycle_seconds = (datetime.now(timezone.utc) - last_cycle_dt).total_seconds()
            except Exception:
                last_cycle_seconds = None
            
            # Count active trades (signals with status="entered")
            active_trades_count = 0
            try:
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    with open(signals_file) as f:
                        for line in f:
                            try:
                                sig = json.loads(line.strip())
                                if sig.get("status") == "entered":
                                    active_trades_count += 1
                            except Exception:
                                continue
            except Exception:
                active_trades_count = 0
            
            # Gate status
            futures_market_open = state.get("futures_market_open")
            strategy_session_open = state.get("strategy_session_open")
            
            # Get latest price and data age using robust fallback helpers
            latest_price = self._extract_latest_price(state)
            data_age_minutes = self._extract_data_age_minutes(state)
            
            # Get stale threshold from state or use default
            data_stale_threshold_minutes = float(state.get("data_stale_threshold_minutes", 10.0))
            
            # Compute adaptive state staleness threshold based on configured save cadence
            state_stale_threshold = self._compute_state_stale_threshold(state)
            
            # Get performance: both challenge attempt (if enabled) AND 7-day all-time
            perf = None
            challenge_status = None
            perf_7d_alltime = None  # Always fetch 7d for comparison
            try:
                # Always get 7-day all-time performance (for comparison)
                perf_7d_alltime = self.performance_tracker.get_performance_metrics(days=7)
            except Exception:
                pass
            
            try:
                # Try challenge tracker (if enabled)
                challenge_tracker = self._get_challenge_tracker()
                if challenge_tracker is not None:
                    perf = challenge_tracker.get_attempt_performance()
                    challenge_status = challenge_tracker.get_status_summary()
                else:
                    # Fallback: use 7d all-time as main perf
                    perf = perf_7d_alltime
            except Exception as e:
                logger.debug(f"Could not get performance for /status: {e}")
                # Fallback
                perf = perf_7d_alltime
            
            # Get last signal age
            last_signal_age = None
            try:
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    # Read last line efficiently
                    with open(signals_file, 'rb') as f:
                        f.seek(0, 2)  # End of file
                        size = f.tell()
                        if size > 0:
                            # Read last 2KB
                            f.seek(max(0, size - 2048))
                            lines = f.read().decode('utf-8', errors='ignore').strip().split('\n')
                            if lines:
                                last_line = lines[-1]
                                try:
                                    last_sig = json.loads(last_line)
                                    sig_ts = last_sig.get("timestamp") or last_sig.get("signal", {}).get("timestamp")
                                    if sig_ts:
                                        last_signal_age = format_time_ago(str(sig_ts))
                                except Exception:
                                    pass
            except Exception as e:
                logger.debug(f"Could not get last signal age: {e}")
            
            # Get session times from config for config-driven messaging
            config_block = state.get("config", {})
            if isinstance(config_block, dict):
                session_start = config_block.get("start_time") or config_block.get("session_start_time")
                session_end = config_block.get("end_time") or config_block.get("session_end_time")
            else:
                session_start = None
                session_end = None

            # Telegram UI formatting options (optional)
            telegram_ui = state.get("telegram_ui", {})
            if not isinstance(telegram_ui, dict):
                telegram_ui = {}
            compact_metrics_enabled = bool(telegram_ui.get("compact_metrics_enabled", True))
            show_progress_bars = bool(telegram_ui.get("show_progress_bars", False))
            show_volume_metrics = bool(telegram_ui.get("show_volume_metrics", True))
            try:
                compact_metric_width = int(telegram_ui.get("compact_metric_width", 10) or 10)
            except Exception:
                compact_metric_width = 10
            
            # Build Home Card message with enhanced confidence/clarity cues (calm-minimal)
            message = format_home_card(
                symbol=state.get("symbol", "MNQ"),
                time_str=self._get_current_time_str(),
                agent_running=running,
                gateway_running=gateway_running,
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
                performance=perf,
                last_signal_age=last_signal_age,
                # Confidence/clarity cues (adaptive threshold based on save cadence)
                state_age_seconds=state_age_seconds,
                state_stale_threshold=state_stale_threshold,
                signal_send_failures=signal_send_failures,
                buy_sell_pressure=state.get("buy_sell_pressure"),
                buy_sell_pressure_raw=state.get("buy_sell_pressure_raw"),
                # Calm-minimal: activity pulse + active trades
                last_cycle_seconds=last_cycle_seconds,
                active_trades_count=active_trades_count,
                # v6 fields for data staleness
                data_age_minutes=data_age_minutes,
                data_stale_threshold_minutes=data_stale_threshold_minutes,
                # v7 fields for config-driven session messaging
                session_start=session_start,
                session_end=session_end,
                # Config-driven telegram UI formatting
                compact_metrics_enabled=compact_metrics_enabled,
                show_progress_bars=show_progress_bars,
                show_volume_metrics=show_volume_metrics,
                compact_metric_width=compact_metric_width,
            )

            # Trade Monitor: show active trades with unrealized P&L
            if active_trades_count > 0:
                try:
                    active_trades = []
                    signals_file = get_signals_file(self.state_dir)
                    if signals_file.exists():
                        with open(signals_file) as f:
                            for line in f:
                                try:
                                    sig = json.loads(line.strip())
                                    if sig.get("status") == "entered":
                                        active_trades.append(sig)
                                except Exception:
                                    continue
                    
                    if active_trades:
                        # Get current price for unrealized P&L calculation
                        current_price = latest_price  # Already fetched above
                        
                        message += f"\n\n📈 *Trade Monitor*\n"
                        
                        for trade_data in active_trades:
                            signal = trade_data.get("signal", {})
                            direction = (signal.get("direction", "long") or "long").upper()
                            dir_emoji = "🟢" if direction == "LONG" else "🔴"
                            entry_price = float(signal.get("entry_price", 0) or 0)
                            stop_loss = float(signal.get("stop_loss", 0) or 0)
                            take_profit = float(signal.get("take_profit", 0) or 0)
                            tick_value = float(signal.get("tick_value", 2.0) or 2.0)
                            position_size = float(signal.get("position_size", 1.0) or 1.0)
                            
                            message += f"{dir_emoji} {direction} @ ${entry_price:.2f}"
                            
                            # Show unrealized P&L if we have current price
                            if current_price is not None and entry_price > 0:
                                if direction == "LONG":
                                    pnl_pts = current_price - entry_price
                                else:
                                    pnl_pts = entry_price - current_price
                                unrealized_pnl = pnl_pts * tick_value * position_size
                                pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                                if unrealized_pnl >= 0:
                                    pnl_str = f"+${unrealized_pnl:.2f}"
                                else:
                                    pnl_str = f"-${abs(unrealized_pnl):.2f}"
                                message += f" → {pnl_emoji} {pnl_str}\n"
                                
                                # Show distance to stop/TP
                                if stop_loss > 0:
                                    dist_to_stop = abs(current_price - stop_loss)
                                    message += f"   Stop: ${stop_loss:.2f} ({dist_to_stop:.1f} pts)\n"
                                if take_profit > 0:
                                    dist_to_tp = abs(take_profit - current_price)
                                    message += f"   TP: ${take_profit:.2f} ({dist_to_tp:.1f} pts)\n"
                            else:
                                message += "\n"
                except Exception as e:
                    logger.debug(f"Could not build trade monitor: {e}")

            # Optional: 50k Challenge status (shows attempt-specific PnL + progress)
            if challenge_status:
                message += f"\n\n{challenge_status}"

            # Show simplified 7d all-time PnL (below challenge, above recent exits)
            if perf_7d_alltime and perf_7d_alltime.get("exited_signals", 0) > 0:
                pnl_7d = perf_7d_alltime.get("total_pnl", 0.0)
                wins_7d = perf_7d_alltime.get("wins", 0)
                losses_7d = perf_7d_alltime.get("losses", 0)
                pnl_emoji_7d = "🟢" if pnl_7d >= 0 else "🔴"
                pnl_str_7d = f"+${pnl_7d:,.2f}" if pnl_7d >= 0 else f"-${abs(pnl_7d):,.2f}"
                message += f"\n\n*7d All-Time:* {pnl_emoji_7d} {pnl_str_7d} ({wins_7d}W/{losses_7d}L)"

            # Optional: Prop firm guardrails snapshot (kept compact)
            try:
                pf = state.get("prop_firm", {}) or {}
                if isinstance(pf, dict) and pf.get("enabled"):
                    profile = str(pf.get("profile") or "prop_firm")
                    equity = pf.get("equity_est")
                    min_balance = pf.get("min_balance")
                    remaining = pf.get("remaining_drawdown")
                    daily_pnl = pf.get("daily_pnl")
                    daily_cap = pf.get("daily_profit_cap")
                    days_traded = pf.get("days_traded")
                    min_days = pf.get("min_trading_days")

                    lines = [f"🏦 *Prop Firm* (`{profile}`)"]
                    try:
                        if equity is not None and min_balance is not None and remaining is not None:
                            lines.append(
                                f"Equity(est): `${float(equity):,.0f}`  •  Min: `${float(min_balance):,.0f}`  •  Buffer: `${float(remaining):,.0f}`"
                            )
                    except Exception:
                        pass
                    try:
                        if daily_cap is not None and daily_pnl is not None:
                            lines.append(
                                f"Consistency: `${float(daily_pnl):,.0f}` / `${float(daily_cap):,.0f}`"
                            )
                    except Exception:
                        pass
                    try:
                        if days_traded is not None and min_days is not None:
                            lines.append(f"Days: `{int(days_traded)}/{int(min_days)}`")
                    except Exception:
                        pass

                    if len(lines) > 1:
                        message += "\n\n" + "\n".join(lines)
            except Exception:
                pass
            
            # Add recent exits (last 3 closed trades)
            try:
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    recent_exits = []
                    with open(signals_file, "r") as f:
                        for line in f:
                            try:
                                rec = json.loads(line.strip())
                                if rec.get("status") == "exited" and rec.get("pnl") is not None:
                                    sig = rec.get("signal", {}) or {}
                                    recent_exits.append({
                                        "pnl": rec.get("pnl"),
                                        "direction": sig.get("direction", "long"),
                                        "type": sig.get("type", "unknown"),
                                        "exit_reason": rec.get("exit_reason", ""),
                                    })
                            except Exception:
                                continue
                    
                    if recent_exits:
                        # Show last 3 exits
                        recent_exits = recent_exits[-3:]
                        message += "\n\n*Recent exits:*"
                        for t in recent_exits:
                            pnl_val = float(t.get("pnl") or 0.0)
                            pnl_emoji, pnl_str = format_pnl(pnl_val)
                            dir_emoji, dir_label = format_signal_direction(t.get("direction", "long"))
                            sig_type = safe_label(str(t.get("type") or "unknown"))
                            reason = safe_label(str(t.get("exit_reason") or "")).strip()
                            line = f"\n{pnl_emoji} {pnl_str} • {dir_emoji} {dir_label} • {sig_type}"
                            if reason:
                                line += f" • {reason}"
                            message += line
            except Exception as e:
                logger.debug(f"Could not add recent exits to status: {e}")
            
            # Send chart first, then text (like interval notification)
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
            
            # Generate and send chart (12h, 5m candles)
            try:
                if self.chart_generator:
                    data_provider = self._get_data_provider()
                    if data_provider:
                        lookback_hours = 12.0
                        symbol = "MNQ"
                        timeframe = "5m"
                        end_time = datetime.now(timezone.utc)
                        start_time = end_time - timedelta(hours=lookback_hours)
                        
                        loop = asyncio.get_running_loop()
                        bars = await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda: data_provider.fetch_historical(
                                    symbol=symbol,
                                    start=start_time,
                                    end=end_time,
                                    timeframe=timeframe,
                                ),
                            ),
                            timeout=30.0,
                        )
                        
                        if bars is not None and not (isinstance(bars, pd.DataFrame) and bars.empty):
                            if isinstance(bars, list):
                                df = pd.DataFrame(bars)
                            else:
                                df = bars
                            
                            if not df.empty:
                                tf_minutes = 5
                                lookback_bars = int(round((lookback_hours * 60.0) / float(tf_minutes)))
                                chart_data = df.tail(min(int(lookback_bars), len(df))).copy()
                                range_label = f"{int(round(lookback_hours))}h"
                                trades = self._get_trades_for_chart(chart_data, symbol=symbol)
                                
                                chart_path = self.chart_generator.generate_dashboard_chart(
                                    chart_data,
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    lookback_bars=len(chart_data),
                                    range_label=range_label,
                                    show_pressure=True,
                                    trades=trades,
                                )
                                
                                if chart_path and chart_path.exists():
                                    caption = f"📊 *{symbol}* {timeframe} ({lookback_hours:.0f}h) • {end_time.strftime('%H:%M UTC')}"
                                    
                                    await context.bot.send_photo(
                                        chat_id=update.effective_chat.id,
                                        photo=open(chart_path, "rb"),
                                        caption=caption,
                                        parse_mode="Markdown",
                                    )
                                    
                                    try:
                                        chart_path.unlink()
                                    except Exception:
                                        pass
            except Exception as e:
                logger.debug(f"Could not send chart with status: {e}")
            
            # Send text status (always new message, immediately after chart)
            reply_markup = self._get_main_menu_buttons(
                agent_running=running,
                gateway_running=gateway_running,
                gateway_api_ready=gateway_api_ready,
            )
            
            # IMPORTANT UX:
            # When invoked via callback_query (user tapped a button), editing the existing message
            # would keep it *above* the newly sent chart photo (because edits don't change ordering),
            # resulting in chart appearing below the Home Card.
            #
            # Fix: for callbacks, remove buttons on the old view and SEND a NEW Home Card message
            # right after the chart so the chart is always on top of the menu text.
            if update.callback_query:
                # Best-effort: disable buttons on the previous view to avoid stale navigation.
                try:
                    await update.callback_query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
                # Send new message (with Markdown fallback)
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode="Markdown",
                    )
                except Exception:
                    try:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=message.replace("*", "").replace("_", "").replace("`", ""),
                            reply_markup=reply_markup,
                            parse_mode=None,
                        )
                    except Exception:
                        # Final fallback: keep UX alive even if buttons fail
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=message.replace("*", "").replace("_", "").replace("`", ""),
                            parse_mode=None,
                        )
            else:
                # Use the unified sender so tests and runtime behavior stay consistent.
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling status command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting status*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check if agent service is running\n"
                f"• Verify state file exists\n"
                f"• Try restarting the agent"
            )
            gateway_status = self.service_controller.get_gateway_status()
            gateway_running = gateway_status.get("process_running", False)
            gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
            reply_markup = self._get_main_menu_buttons(
                agent_running=self._is_agent_process_running(),
                gateway_running=gateway_running,
                gateway_api_ready=gateway_api_ready,
            )
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
    async def _handle_status_refresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle status refresh - edit text only, no new chart."""
        if not await self._check_authorized(update):
            return
        
        try:
            # Get gateway status
            gateway_status = self.service_controller.get_gateway_status()
            gateway_running = gateway_status.get("process_running", False)
            gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
            
            # Load state
            state_file = get_state_file(self.state_dir)
            if not state_file.exists():
                process_running = self._is_agent_process_running()
                message = format_home_card(
                    symbol="MNQ",
                    time_str=self._get_current_time_str(),
                    agent_running=process_running,
                    gateway_running=gateway_running,
                    futures_market_open=None,
                    strategy_session_open=None,
                )
                message += "\n\n⚠️ *No state file found*"
                reply_markup = self._get_main_menu_buttons(
                    agent_running=process_running,
                    gateway_running=gateway_running,
                    gateway_api_ready=gateway_api_ready,
                )
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                return
            
            with open(state_file) as f:
                state = json.load(f)
            
            # Build status (same as _handle_status but simplified)
            process_running = self._is_agent_process_running()
            running = process_running and state.get("running", False)
            paused = state.get("paused", False)
            pause_reason = state.get("pause_reason") or None
            
            cycles_total = int(state.get("cycle_count", 0) or 0)
            cycles_session = state.get("cycle_count_session")
            try:
                cycles_session = int(cycles_session) if cycles_session is not None else None
            except Exception:
                cycles_session = None
            
            signals_generated = int(state.get("signal_count", 0) or 0)
            signals_sent = int(state.get("signals_sent", 0) or 0)
            errors = int(state.get("error_count", 0) or 0)
            buffer_size = int(state.get("buffer_size", 0) or 0)
            buffer_target = state.get("buffer_size_target")
            signal_send_failures = int(state.get("signals_send_failures", 0) or 0)
            
            # Activity pulse
            last_cycle_seconds = None
            try:
                last_cycle_ts = state.get("last_successful_cycle")
                if last_cycle_ts:
                    from pearlalgo.utils.paths import parse_utc_timestamp
                    last_cycle_dt = parse_utc_timestamp(str(last_cycle_ts))
                    if last_cycle_dt:
                        if last_cycle_dt.tzinfo is None:
                            last_cycle_dt = last_cycle_dt.replace(tzinfo=timezone.utc)
                        last_cycle_seconds = (datetime.now(timezone.utc) - last_cycle_dt).total_seconds()
            except Exception:
                pass
            
            # Gates and price
            futures_market_open = state.get("futures_market_open")
            strategy_session_open = state.get("strategy_session_open")
            latest_price = self._extract_latest_price(state)
            
            # Performance
            perf = None
            try:
                perf = self.performance_tracker.get_performance_metrics(days=7)
            except Exception:
                pass
            
            # Buy/sell pressure
            buy_sell_pressure = state.get("buy_sell_pressure")
            
            # Session times
            config_block = state.get("config", {})
            session_start = config_block.get("start_time") if isinstance(config_block, dict) else None
            session_end = config_block.get("end_time") if isinstance(config_block, dict) else None
            
            # Format home card
            message = format_home_card(
                symbol="MNQ",
                time_str=self._get_current_time_str(),
                agent_running=running,
                gateway_running=gateway_running,
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
                performance=perf,
                signal_send_failures=signal_send_failures,
                buy_sell_pressure=buy_sell_pressure,
                last_cycle_seconds=last_cycle_seconds,
                session_start=session_start,
                session_end=session_end,
            )
            
            # Add recent exits (last 3 closed trades)
            try:
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    recent_exits = []
                    with open(signals_file, "r") as f:
                        for line in f:
                            try:
                                rec = json.loads(line.strip())
                                if rec.get("status") == "exited" and rec.get("pnl") is not None:
                                    sig = rec.get("signal", {}) or {}
                                    recent_exits.append({
                                        "pnl": rec.get("pnl"),
                                        "direction": sig.get("direction", "long"),
                                        "type": sig.get("type", "unknown"),
                                        "exit_reason": rec.get("exit_reason", ""),
                                    })
                            except Exception:
                                continue
                    
                    if recent_exits:
                        recent_exits = recent_exits[-3:]
                        message += "\n\n*Recent exits:*"
                        for t in recent_exits:
                            pnl_val = float(t.get("pnl") or 0.0)
                            pnl_emoji, pnl_str = format_pnl(pnl_val)
                            dir_emoji, dir_label = format_signal_direction(t.get("direction", "long"))
                            sig_type = safe_label(str(t.get("type") or "unknown"))
                            reason = safe_label(str(t.get("exit_reason") or "")).strip()
                            line = f"\n{pnl_emoji} {pnl_str} • {dir_emoji} {dir_label} • {sig_type}"
                            if reason:
                                line += f" • {reason}"
                            message += line
            except Exception:
                pass
            
            reply_markup = self._get_main_menu_buttons(
                agent_running=running,
                gateway_running=gateway_running,
                gateway_api_ready=gateway_api_ready,
            )
            
            # Edit message in place
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling status refresh: {e}", exc_info=True)
            await self._send_message_or_edit(update, context, f"❌ Refresh failed: {str(e)[:100]}")
    
    def _get_current_time_str(self) -> str:
        """Get current time formatted for display (ET timezone)."""
        try:
            import pytz
            now = datetime.now(timezone.utc)
            et_tz = pytz.timezone('US/Eastern')
            et_time = now.astimezone(et_tz)
            return et_time.strftime("%I:%M %p ET")
        except Exception:
            return datetime.now(timezone.utc).strftime("%H:%M UTC")
    
    async def _handle_quick_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /quick_status command - ultra-compact status."""
        logger.info(f"Received /quick_status command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        try:
            state_file = get_state_file(self.state_dir)
            if not state_file.exists():
                reply_markup = self._get_main_menu_buttons(agent_running=False)
                await self._send_message_or_edit(
                    update, context,
                    f"🔴 *{LABEL_AGENT}:* {STATE_STOPPED}\n\n"
                    f"💡 Tap 'Start {LABEL_AGENT}' below to begin",
                    reply_markup=reply_markup
                )
                return
            
            with open(state_file) as f:
                state = json.load(f)
            
            process_running = self._is_agent_process_running()
            running = process_running and state.get("running", False)
            status_emoji = "🟢" if running else "🔴"
            
            scans = state.get('cycle_count', 0)
            signals = state.get('signal_count', 0)
            buffer = state.get('buffer_size', 0)
            
            message = f"{status_emoji} *Quick Status*\n\n"
            message += f"🔄 {scans:,} scans\n"
            message += f"🔔 {signals} signals\n"
            message += f"📊 {buffer} bars\n"
            
            # Add performance if available
            try:
                perf = self.performance_tracker.get_performance_metrics(days=7)
                exited = perf.get("exited_signals", 0)
                if exited > 0:
                    wins = perf.get("wins", 0)
                    losses = perf.get("losses", 0)
                    total_pnl = perf.get("total_pnl", 0.0)
                    message += f"\n📈 {wins}W/{losses}L • ${total_pnl:,.2f}"
            except Exception:
                pass
            
            reply_markup = self._get_main_menu_buttons(agent_running=running)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling quick_status command: {e}", exc_info=True)
            error_msg = f"❌ Error: {str(e)}"
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
    async def _handle_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pause command."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Note: This requires integration with the running service
        # For now, just acknowledge the command
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(
            update, context,
            "⏸️ *Pause command received*\n\n"
            "Note: Direct pause/resume requires service integration.\n"
            "Use Stop Agent and Start Agent buttons for full control.",
            reply_markup=reply_markup
        )
    
    async def _handle_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /resume command."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(
            update, context,
            "▶️ *Resume command received*\n\n"
            "Note: Direct pause/resume requires service integration.\n"
            "Use Stop Agent and Start Agent buttons for full control.",
            reply_markup=reply_markup
        )
    
    async def _handle_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /signals command."""
        logger.info(f"Received /signals command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # For explicit /signals commands (not button callbacks), default to newest page.
        if not update.callback_query and hasattr(context, "user_data"):
            context.user_data["signals_page"] = 0
        
        try:
            signals_file = get_signals_file(self.state_dir)
            # Pull state signal_count for mismatch diagnostics (state can show signals even if file is empty)
            state_signal_count = 0
            try:
                state_file = get_state_file(self.state_dir)
                if state_file.exists():
                    with open(state_file, "r") as sf:
                        st = json.load(sf)
                    state_signal_count = int(st.get("signal_count", 0) or 0)
            except Exception:
                state_signal_count = 0

            if not signals_file.exists():
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "The signals file doesn't exist yet.\n"
                    f"*State reports:* {state_signal_count} signal(s)\n\n"
                    "Signals will appear here once the agent generates trading opportunities.",
                    reply_markup=reply_markup
                )
                return
            
            # Check file size
            file_size = signals_file.stat().st_size
            if file_size == 0:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "The signals file exists but is empty.\n"
                    f"*State reports:* {state_signal_count} signal(s)\n\n"
                    "This could mean:\n"
                    "• Signals haven't been generated yet\n"
                    "• Signals were generated but not saved (check logs)\n"
                    "• The file was cleared\n\n"
                    f"💡 Check: `ls -lh {signals_file}`",
                    reply_markup=reply_markup
                )
                return
            
            # Read all signals (handle both old and new formats)
            signals = []
            line_num = 0
            with open(signals_file) as f:
                for line in f:
                    line_num += 1
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        signal_data = json.loads(line)
                        
                        # Handle both formats:
                        # New format: {"signal_id": "...", "timestamp": "...", "status": "...", "signal": {...}}
                        # Old format: {"signal_id": "...", "type": "...", "direction": "...", ...} (signal dict directly)
                        if "signal" in signal_data:
                            # New format - use as is
                            signals.append(signal_data)
                        elif "signal_id" in signal_data or "type" in signal_data:
                            # Old format - wrap it
                            signals.append({
                                "signal_id": signal_data.get("signal_id", f"unknown_{line_num}"),
                                "timestamp": signal_data.get("timestamp", ""),
                                "status": signal_data.get("status", "generated"),
                                "signal": signal_data,  # The whole thing is the signal
                            })
                        else:
                            logger.warning(f"Unknown signal format at line {line_num}: {signal_data.keys()}")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON at line {line_num} in signals file: {e}")
                        continue
            
            if not signals:
                reply_markup = self._get_back_to_menu_button()
                sig_stats = self._get_signals_file_stats(signals_file)
                lines = int(sig_stats.get("lines", 0) or 0)
                invalid = int(sig_stats.get("invalid", 0) or 0)
                await self._send_message_or_edit(
                    update, context,
                    f"📭 *No valid signals found*\n\n"
                    f"File exists ({file_size} bytes) but has 0 valid signal records.\n"
                    f"*State reports:* {state_signal_count} signal(s)\n"
                    f"*Lines parsed:* {lines} • *Invalid JSON lines:* {invalid}\n\n"
                    f"💡 Try: `python3 scripts/testing/check_signals.py`",
                    reply_markup=reply_markup
                )
                return
            
            # Filters (persist per-chat; single-admin setup makes this straightforward)
            user_data = context.user_data if hasattr(context, "user_data") else {}
            dir_filter = (user_data.get("signals_dir") or "all").lower()
            type_filter = (user_data.get("signals_type") or "all").lower()
            try:
                min_conf = float(user_data.get("signals_min_conf", 0.0) or 0.0)
            except Exception:
                min_conf = 0.0

            if dir_filter not in ("all", "long", "short"):
                dir_filter = "all"
            if type_filter not in ("all", "momentum", "mean_reversion", "breakout", "other"):
                type_filter = "all"
            if min_conf not in (0.0, 0.5, 0.6, 0.7):
                # Keep it predictable (button presets)
                min_conf = 0.0

            def _bucket_type(t: str) -> str:
                t = (t or "").lower()
                if "momentum" in t:
                    return "momentum"
                if "breakout" in t:
                    return "breakout"
                if "mean_reversion" in t or "vwap_reversion" in t or "sr_bounce" in t or "engulfing" in t:
                    return "mean_reversion"
                return "other"

            filtered: List[Dict] = []
            for sig_data in signals:
                signal = sig_data.get("signal", {}) or {}
                sig_dir = (signal.get("direction", "long") or "long").lower()
                sig_type = signal.get("type", "unknown")
                try:
                    conf_val = float(signal.get("confidence", 0.0) or 0.0)
                except Exception:
                    conf_val = 0.0

                if dir_filter != "all" and sig_dir != dir_filter:
                    continue
                if conf_val < min_conf:
                    continue
                if type_filter != "all" and _bucket_type(sig_type) != type_filter:
                    continue
                filtered.append(sig_data)

            total_count = len(signals)
            filtered_count = len(filtered)

            # Paging (newest-first)
            page_size = 10
            try:
                page = int(user_data.get("signals_page", 0) or 0)
            except Exception:
                page = 0
            if page < 0:
                page = 0

            total_pages = max(1, (filtered_count + page_size - 1) // page_size) if filtered_count > 0 else 1
            if page > total_pages - 1:
                page = total_pages - 1

            # Persist clamped page
            if hasattr(context, "user_data"):
                context.user_data["signals_page"] = page

            end = filtered_count - (page * page_size)
            start = max(0, end - page_size)
            page_signals = filtered[start:end]
            page_signals.reverse()

            active_trades_count = sum(1 for s in signals if s.get("status") == "entered")

            message = "🎯 *Signals & Trades*\n\n"
            message += f"*Stored:* {total_count}\n"
            message += f"*Active Trades:* {active_trades_count}\n"
            message += f"*Page:* {page + 1}/{total_pages}  |  *Showing:* {len(page_signals)}\n\n"

            keyboard: List[List[InlineKeyboardButton]] = []

            # Paging row (compact)
            if filtered_count > 0 and total_pages > 1:
                pager_row: List[InlineKeyboardButton] = []
                if page < total_pages - 1:
                    pager_row.append(InlineKeyboardButton("◀ Older", callback_data="signals:page:older"))
                if page > 0:
                    pager_row.append(InlineKeyboardButton("Newer ▶", callback_data="signals:page:newer"))
                pager_row.append(InlineKeyboardButton("🔝 Top", callback_data="signals:page:newest"))
                keyboard.append(pager_row)

            if not page_signals:
                message += "📭 No signals match these filters.\n"
            else:
                # Build compact signal list with freshness indicators
                for i, sig_data in enumerate(page_signals, 1):
                    signal = sig_data.get("signal", {}) or {}
                    signal_type = signal.get("type", "unknown")
                    status = sig_data.get("status", "unknown")
                    signal_id = sig_data.get("signal_id", "")
                    entry_price = float(signal.get("entry_price", 0.0) or 0.0)
                    try:
                        conf_val = float(signal.get("confidence", 0.0) or 0.0)
                    except Exception:
                        conf_val = 0.0

                    # Check if this is a test signal (excluded from P&L)
                    is_test = signal.get("_is_test", False) or sig_data.get("_is_test", False)
                    test_marker = "🧪 " if is_test else ""

                    # Use shared helpers for consistent formatting
                    is_win = sig_data.get("is_win") if status == "exited" else None
                    status_emoji, _ = format_signal_status(status, is_win)
                    _, dir_label = format_signal_direction(signal.get("direction", "long"))
                    
                    # Freshness: time since signal was generated
                    sig_ts = sig_data.get("timestamp") or signal.get("timestamp")
                    age_str = format_time_ago(sig_ts)
                    age_part = f" • {age_str}" if age_str else ""

                    # Compact one-liner: status, type, direction, confidence, age
                    message += f"{i}. {test_marker}{status_emoji} {safe_label(signal_type)} {dir_label} • {conf_val:.0%}{age_part}\n"
                    
                    # Second line: entry price + PnL for exited, or just price for others
                    # (signal ID hidden for cleaner list - tap ℹ️{n} for details)
                    if status == "exited":
                        pnl = float(sig_data.get("pnl", 0.0) or 0.0)
                        pnl_emoji, pnl_str = format_pnl(pnl)
                        exit_reason = safe_label(str(sig_data.get("exit_reason", "") or "")[:16])
                        # Show (TEST - not in P&L) for test signals
                        test_note = " _(test)_" if is_test else ""
                        message += f"   {pnl_emoji} {pnl_str} ({exit_reason}) @ ${entry_price:.2f}{test_note}\n\n"
                    else:
                        message += f"   Entry: ${entry_price:.2f}\n\n"

                # Compact numeric grid for actions (batch multiple signals per row)
                action_buttons: List[InlineKeyboardButton] = []
                for i, sig_data in enumerate(page_signals, 1):
                    signal_id = sig_data.get("signal_id", "")
                    if signal_id:
                        action_buttons.append(
                            InlineKeyboardButton(f"ℹ️{i}", callback_data=f"signal_detail_{signal_id[:16]}")
                        )
                # Group action buttons in rows of 5
                for j in range(0, len(action_buttons), 5):
                    keyboard.append(action_buttons[j : j + 5])

            # Navigation
            keyboard.append([
                InlineKeyboardButton("🎯 Trades", callback_data="active_trades"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="start"),
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling signals command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting signals*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check if signals file exists\n"
                f"• Verify agent is running: `/status`\n"
                f"• Wait for signals to be generated"
            )
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
    async def _handle_last_signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /last_signal command - show most recent signal with chart."""
        logger.info(f"Received /last_signal command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "Signals will appear here when the agent generates trading opportunities.",
                    reply_markup=reply_markup
                )
                return
            
            # Read all signals and get the last one
            signals = []
            with open(signals_file) as f:
                for line in f:
                    try:
                        signal_data = json.loads(line.strip())
                        signals.append(signal_data)
                    except json.JSONDecodeError:
                        continue
            
            if not signals:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "Signals will appear here when the agent generates trading opportunities.\n\n"
                    "💡 *Tip:* Make sure the agent is running and the market is open.",
                    reply_markup=reply_markup
                )
                return
            
            # Get last signal
            last_signal_data = signals[-1]
            signal = last_signal_data.get("signal", {})
            signal_id = last_signal_data.get("signal_id", "")
            status = last_signal_data.get("status", "unknown")
            
            signal_type = signal.get("type", "unknown")
            entry_price = float(signal.get("entry_price", 0) or 0)
            stop_loss = float(signal.get("stop_loss", 0) or 0)
            take_profit = float(signal.get("take_profit", 0) or 0)
            try:
                conf_val = float(signal.get("confidence", 0.0) or 0.0)
            except Exception:
                conf_val = 0.0
            
            # Use shared helpers for consistent formatting
            is_win = last_signal_data.get("is_win") if status == "exited" else None
            status_emoji, status_label = format_signal_status(status, is_win)
            dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))
            conf_emoji, conf_tier = format_signal_confidence_tier(conf_val)
            
            # Freshness indicator
            sig_ts = last_signal_data.get("timestamp") or signal.get("timestamp")
            age_str = format_time_ago(sig_ts)
            
            message = f"{status_emoji} *Last Signal*\n\n"
            message += f"*Type:* {safe_label(signal_type)} {dir_emoji} {dir_label}\n"
            message += f"*Entry:* ${entry_price:.2f}\n"
            if stop_loss:
                message += f"*Stop:* ${stop_loss:.2f}\n"
            if take_profit:
                message += f"*TP:* ${take_profit:.2f}\n"
            message += f"*Confidence:* {conf_emoji} {conf_val:.0%} ({conf_tier})\n"
            message += f"*Status:* {status_label}\n"
            if age_str:
                message += f"*Age:* {age_str}\n"
            message += f"*ID:* `{signal_id[:16]}…`\n"
            
            # Show PnL for exited signals
            if status == "exited":
                pnl = float(last_signal_data.get("pnl", 0.0) or 0.0)
                pnl_emoji, pnl_str = format_pnl(pnl)
                exit_reason = safe_label(str(last_signal_data.get("exit_reason", "") or ""))
                message += f"\n{pnl_emoji} *P&L:* {pnl_str}"
                if exit_reason:
                    message += f" ({exit_reason})"
                message += "\n"
            
            # Add chart button
            keyboard = []
            if signal_id and self.chart_generator:
                keyboard.append([
                    InlineKeyboardButton("📊 View Chart", callback_data=f"signal_chart_{signal_id[:16]}")
                ])
            keyboard.append([
                InlineKeyboardButton("🔔 All Signals", callback_data='signals'),
                InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
            ])
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling last_signal command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting last signal*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 Try `/signals` to see all signals"
            )
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
    async def _handle_active_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /active_trades command - show currently open positions."""
        logger.info(f"Received /active_trades command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "No positions are currently open.",
                    reply_markup=reply_markup
                )
                return
            
            # Read all signals and filter for entered but not exited
            active_trades = []
            with open(signals_file) as f:
                for line in f:
                    try:
                        signal_data = json.loads(line.strip())
                        status = signal_data.get("status", "unknown")
                        if status == "entered":
                            active_trades.append(signal_data)
                    except json.JSONDecodeError:
                        continue
            
            if not active_trades:
                reply_markup = self._get_back_to_menu_button()
                message = "📭 *No Active Trades*\n\n"
                message += "No positions are currently open."
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                return
            
            message = f"📊 *Active Trades ({len(active_trades)})*\n\n"
            
            # Try to get current price for unrealized PnL
            current_price = None
            price_source = None
            try:
                data_provider = self._get_data_provider()
                if data_provider is not None:
                    # get_latest_bar is async - await it directly with timeout
                    latest = await asyncio.wait_for(
                        data_provider.get_latest_bar("MNQ"),
                        timeout=5.0,
                    )
                    if isinstance(latest, dict) and "close" in latest:
                        current_price = float(latest["close"])
                        price_source = latest.get("_data_level", "live")
            except asyncio.TimeoutError:
                logger.debug("Timeout fetching current price for active trades")
            except Exception as e:
                logger.debug(f"Could not fetch current price for active trades: {e}")
            
            # Show price with confidence cue
            if current_price is not None:
                message += f"*Current Price:* ${current_price:.2f}\n\n"
            else:
                message += "⚠️ *Price unavailable* — P&L not shown\n\n"
            
            for i, trade_data in enumerate(active_trades, 1):
                signal = trade_data.get("signal", {})
                signal_type = signal.get("type", "unknown")
                direction = (signal.get("direction", "long") or "long").upper()
                entry_price = float(signal.get("entry_price", 0) or 0)
                stop_loss = float(signal.get("stop_loss", 0) or 0)
                take_profit = float(signal.get("take_profit", 0) or 0)
                signal_id = trade_data.get("signal_id", "")
                tick_value = float(signal.get("tick_value", 2.0) or 2.0)
                position_size = float(signal.get("position_size", 1.0) or 1.0)
                
                message += f"{i}. 🎯 {safe_label(signal_type)} {direction}\n"
                message += f"   Entry: ${entry_price:.2f}"
                
                # Show unrealized PnL if we have current price
                if current_price is not None and entry_price > 0:
                    if direction == "LONG":
                        pnl_pts = current_price - entry_price
                    else:
                        pnl_pts = entry_price - current_price
                    unrealized_pnl = pnl_pts * tick_value * position_size
                    pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                    pnl_str = f"+${unrealized_pnl:.2f}" if unrealized_pnl >= 0 else f"-${abs(unrealized_pnl):.2f}"
                    message += f" | {pnl_emoji} {pnl_str}"
                message += "\n"
                
                if stop_loss:
                    message += f"   Stop: ${stop_loss:.2f}"
                    if current_price is not None:
                        dist_to_stop = abs(current_price - stop_loss)
                        message += f" ({dist_to_stop:.2f} pts away)"
                    message += "\n"
                if take_profit:
                    message += f"   TP: ${take_profit:.2f}"
                    if current_price is not None:
                        dist_to_tp = abs(take_profit - current_price)
                        message += f" ({dist_to_tp:.2f} pts away)"
                    message += "\n"
                message += f"   ID: {signal_id[:16]}...\n\n"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="active_trades")],
                [InlineKeyboardButton("🔔 All Signals", callback_data="signals")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling active_trades command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting active trades*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 Try `/signals` to see all signals"
            )
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
    def _get_data_provider(self):
        """Get or create data provider for fetching historical data."""
        if self._data_provider is None:
            try:
                from pearlalgo.data_providers.factory import create_data_provider
                from pearlalgo.config.settings import get_settings
                
                settings = get_settings()
                # Try to get provider from config, default to 'ibkr'
                provider_name = getattr(settings, 'data_provider', 'ibkr') if hasattr(settings, 'data_provider') else 'ibkr'
                # Use a dedicated client_id for the command handler to avoid colliding with the main service.
                # IMPORTANT: Do NOT reuse IBKR_DATA_CLIENT_ID here; the main agent typically uses it.
                # Allow an explicit override, otherwise pick a safe unused id derived from configured ids.
                client_id = None
                try:
                    override = (
                        os.getenv("IBKR_TELEGRAM_CLIENT_ID")
                        or os.getenv("PEARLALGO_IBKR_TELEGRAM_CLIENT_ID")
                    )
                    if override:
                        client_id = int(override)
                    else:
                        base = int(getattr(settings, "ib_client_id", 1) or 1)
                        data_cid_raw = getattr(settings, "ib_data_client_id", None)
                        reserved = {base}
                        if data_cid_raw is not None:
                            reserved.add(int(data_cid_raw))
                        # Common defaults: base=10, data=11, so we select 12.
                        client_id = max(reserved) + 1
                except Exception:
                    client_id = None

                self._data_provider = create_data_provider(provider_name, settings=settings, client_id=client_id)
                logger.info(f"Initialized data provider: {provider_name} (client_id={client_id})")
            except Exception as e:
                logger.warning(f"Could not initialize data provider: {e}")
                return None
        return self._data_provider

    def _get_trade_db(self) -> Optional["TradeDatabase"]:
        """Get or create the SQLite TradeDatabase (if enabled)."""
        if not TRADE_DB_AVAILABLE or TradeDatabase is None:
            return None

        existing = getattr(self, "_trade_db", None)
        if existing is not None:
            return existing

        try:
            from pearlalgo.config.config_loader import load_service_config

            cfg = load_service_config(validate=False) or {}
            storage_cfg = cfg.get("storage", {}) or {}
            if not bool(storage_cfg.get("sqlite_enabled", False)):
                return None

            # IMPORTANT:
            # - In production (no explicit state_dir), honor config.db_path if provided.
            # - In tests (explicit state_dir), ALWAYS use state_dir/trades.db regardless of config.
            if getattr(self, "_explicit_state_dir", False):
                db_path = self.state_dir / "trades.db"
            else:
                db_path_raw = storage_cfg.get("db_path") or str(self.state_dir / "trades.db")
                db_path = Path(str(db_path_raw))

            self._trade_db = TradeDatabase(db_path)
            return self._trade_db
        except Exception as e:
            logger.debug(f"Could not initialize TradeDatabase: {e}")
            return None

    def _get_challenge_tracker(self) -> Optional["ChallengeTracker"]:
        """Get or create the 50k Challenge Tracker (if enabled)."""
        existing = getattr(self, "_challenge_tracker", None)
        if existing is not None:
            return existing

        try:
            from pearlalgo.nq_agent.challenge_tracker import ChallengeTracker, ChallengeConfig
            from pearlalgo.config.config_loader import load_service_config

            cfg = load_service_config(validate=False) or {}
            challenge_cfg = cfg.get("challenge", {}) or {}
            if not bool(challenge_cfg.get("enabled", False)):
                return None

            config = ChallengeConfig(
                enabled=True,
                start_balance=float(challenge_cfg.get("start_balance", 50_000.0)),
                max_drawdown=float(challenge_cfg.get("max_drawdown", 2_000.0)),
                profit_target=float(challenge_cfg.get("profit_target", 3_000.0)),
                auto_reset_on_pass=bool(challenge_cfg.get("auto_reset_on_pass", True)),
                auto_reset_on_fail=bool(challenge_cfg.get("auto_reset_on_fail", True)),
            )

            # Use consistent state_dir (test-aware)
            self._challenge_tracker = ChallengeTracker(
                config=config,
                state_dir=self.state_dir,
                trade_db=self._get_trade_db(),
            )
            return self._challenge_tracker
        except Exception as e:
            logger.debug(f"Could not initialize ChallengeTracker: {e}")
            return None
    
    async def _fetch_historical_data_for_backtest(
        self, 
        symbol: str = "MNQ", 
        weeks: int = 2,
        timeframe: str = "1m",
    ) -> Optional[pd.DataFrame]:
        """
        Fetch and cache historical data for backtesting.
        
        Args:
            symbol: Symbol to fetch (default: MNQ)
            weeks: Number of weeks to fetch (default: 2)
            timeframe: Data timeframe (default: 1m)
            
        Returns:
            DataFrame with historical OHLCV data, or None if fetch failed
        """
        cache_file = self._historical_cache_dir / f"{symbol}_{timeframe}_{weeks}w.parquet"
        # Backtests should use *completed* historical data only.
        # If today is Monday, "yesterday" is Sunday (no session) which can cause HMDS weirdness/timeouts.
        # Clamp to the most recent weekday (Mon-Fri) at 23:59 UTC.
        end = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
            hour=23, minute=59, second=0, microsecond=0
        )
        while end.weekday() >= 5:  # Sat/Sun
            end = end - timedelta(days=1)
        start = end - timedelta(days=weeks * 7)
        
        logger.info(f"Fetching {weeks} weeks of historical data for {symbol}...")
        
        # Check for cached data first
        if cache_file.exists():
            try:
                cached_data = pd.read_parquet(cache_file)
                if not cached_data.empty:
                    # We REQUIRE a timestamp for backtests. Older caches were saved without it (lost index).
                    if 'timestamp' in cached_data.columns:
                        cached_data['timestamp'] = pd.to_datetime(cached_data['timestamp'], utc=True)
                        cached_data = cached_data.dropna(subset=["timestamp"])
                        # Normalize return shape: keep timestamp column, but ensure DatetimeIndex for resampling.
                        cached_data = cached_data.sort_values('timestamp')
                        cached_data = cached_data.drop_duplicates(subset=['timestamp'], keep='first')
                        cached_data = cached_data.set_index('timestamp', drop=False)
                        
                        # VALIDATION: Check that cached data actually covers the requested date range
                        # Allow some tolerance for weekends/holidays (at least 5 trading days per week)
                        if len(cached_data) > 0:
                            cache_start = cached_data.index.min()
                            cache_end = cached_data.index.max()
                            cache_days = (cache_end - cache_start).days
                            min_required_days = max(1, (weeks * 5) - 3)  # ~5 trading days/week with tolerance
                            
                            if cache_days >= min_required_days:
                                logger.info(f"✅ Using cached data: {len(cached_data):,} bars ({cache_days} days: {cache_start.date()} to {cache_end.date()})")
                                return cached_data
                            else:
                                logger.warning(
                                    f"Cache {cache_file.name} has only {cache_days} days of data "
                                    f"(need ~{min_required_days}+ days for {weeks} weeks). Deleting stale cache."
                                )
                                try:
                                    cache_file.unlink()
                                except Exception:
                                    pass

                    if isinstance(cached_data.index, pd.DatetimeIndex):
                        cached_data = cached_data.reset_index()
                        # The reset index column name can vary; normalize it to 'timestamp'.
                        if 'timestamp' not in cached_data.columns and len(cached_data.columns) > 0:
                            first_col = cached_data.columns[0]
                            cached_data = cached_data.rename(columns={first_col: 'timestamp'})
                        if 'timestamp' in cached_data.columns:
                            cached_data['timestamp'] = pd.to_datetime(cached_data['timestamp'], utc=True)
                            cached_data = cached_data.dropna(subset=["timestamp"])
                            cached_data = cached_data.sort_values('timestamp')
                            cached_data = cached_data.drop_duplicates(subset=['timestamp'], keep='first')
                            cached_data = cached_data.set_index('timestamp', drop=False)
                            
                            # VALIDATION: Check that cached data actually covers the requested date range
                            if len(cached_data) > 0:
                                cache_start = cached_data.index.min()
                                cache_end = cached_data.index.max()
                                cache_days = (cache_end - cache_start).days
                                min_required_days = max(1, (weeks * 5) - 3)
                                
                                if cache_days >= min_required_days:
                                    logger.info(f"✅ Using cached data: {len(cached_data):,} bars ({cache_days} days: {cache_start.date()} to {cache_end.date()})")
                                    return cached_data
                                else:
                                    logger.warning(
                                        f"Cache {cache_file.name} has only {cache_days} days of data "
                                        f"(need ~{min_required_days}+ days for {weeks} weeks). Deleting stale cache."
                                    )
                                    try:
                                        cache_file.unlink()
                                    except Exception:
                                        pass

                    logger.warning("Cached data missing timestamp; deleting invalid cache and re-fetching")
                    try:
                        cache_file.unlink()
                    except Exception as delete_error:
                        logger.warning(f"Could not delete invalid cache file: {delete_error}")
            except Exception as e:
                logger.warning(f"Error reading cache: {e}")

        # If an exact cache file doesn't exist (or was invalid), try deriving it from a *larger* cached file.
        # This supports both new week caches (e.g. *_6w.parquet) and legacy month caches (e.g. *_2m.parquet).
        try:
            superset_files: List[Path] = []
            superset_files.extend(self._historical_cache_dir.glob(f"{symbol}_{timeframe}_*w.parquet"))
            superset_files.extend(self._historical_cache_dir.glob(f"{symbol}_{timeframe}_*m.parquet"))

            candidates: List[tuple[float, Path]] = []
            for f in superset_files:
                if f == cache_file:
                    continue
                tail = f.name.split("_")[-1]  # e.g. "6w.parquet" or "2m.parquet"
                dur_weeks = None
                if tail.endswith("w.parquet"):
                    try:
                        dur_weeks = float(int(tail[:-9]))
                    except Exception:
                        dur_weeks = None
                elif tail.endswith("m.parquet"):
                    try:
                        m = int(tail[:-9])
                        dur_weeks = float(m * 30) / 7.0
                    except Exception:
                        dur_weeks = None
                if dur_weeks is None:
                    dur_weeks = 1e9
                if dur_weeks >= float(weeks):
                    candidates.append((dur_weeks, f))

            if not candidates:
                # If we can't parse durations, try any existing cache file as a last resort.
                candidates = [(1e9, f) for f in superset_files if f != cache_file]

            if candidates:
                # Prefer the smallest superset (closest to requested duration)
                candidates.sort(key=lambda x: x[0])
                for _, superset_file in candidates:
                    superset_df = pd.read_parquet(superset_file)
                    if superset_df is None or superset_df.empty:
                        continue

                    if "timestamp" not in superset_df.columns and isinstance(superset_df.index, pd.DatetimeIndex):
                        superset_df = superset_df.reset_index()
                        if "timestamp" not in superset_df.columns and len(superset_df.columns) > 0:
                            first_col = superset_df.columns[0]
                            superset_df = superset_df.rename(columns={first_col: "timestamp"})

                    if "timestamp" not in superset_df.columns:
                        continue

                    superset_df["timestamp"] = pd.to_datetime(superset_df["timestamp"], errors="coerce", utc=True)
                    superset_df = superset_df.dropna(subset=["timestamp"])

                    derived = superset_df[
                        (superset_df["timestamp"] >= start) & (superset_df["timestamp"] <= end)
                    ].copy()
                    if derived.empty:
                        continue

                    derived = derived.sort_values("timestamp")
                    derived = derived.drop_duplicates(subset=["timestamp"], keep="first")
                    derived = derived.set_index("timestamp", drop=False)
                    try:
                        derived.to_parquet(cache_file, index=False)
                        logger.info(
                            f"💾 Derived cache {cache_file.name} from {superset_file.name} "
                            f"({len(derived):,} bars)"
                        )
                    except Exception as e:
                        logger.warning(f"Could not write derived cache: {e}")
                    return derived
        except Exception as e:
            logger.debug(f"Could not derive cache from superset: {e}")
        
        # Fetch data
        data_provider = self._get_data_provider()
        if data_provider is None:
            logger.error("Data provider not available")
            return None
        
        try:
            # If the most recent window fails (often due to expiry/roll), automatically shift further back in time.
            # This matches your request: "pick past weeks if that's the only thing that works".
            max_window_shifts = 3
            all_chunks = []
            window_end = end
            window_start = start

            # Smaller chunks are far more reliable with IBKR HMDS for 1m bars.
            # We'll use weekly chunks and, if needed, fall back to daily chunks.
            base_chunk_days = 7

            for shift_idx in range(max_window_shifts + 1):
                if shift_idx > 0:
                    window_end = end - timedelta(days=shift_idx * 7)
                    window_end = window_end.replace(hour=23, minute=59, second=0, microsecond=0)
                    while window_end.weekday() >= 5:  # Sat/Sun
                        window_end = window_end - timedelta(days=1)
                    window_start = window_end - timedelta(days=weeks * 7)
                    logger.warning(
                        f"No data fetched for requested window; trying earlier window: "
                        f"{window_start.date()} to {window_end.date()}"
                    )

                all_chunks = []
                # Build weekly chunk ranges
                chunk_ranges = []
                cur = window_start
                while cur < window_end:
                    nxt = min(cur + timedelta(days=base_chunk_days), window_end)
                    chunk_ranges.append((cur, nxt))
                    cur = nxt

                total_chunks = max(1, len(chunk_ranges))
                for chunk_i, (chunk_start, chunk_end) in enumerate(chunk_ranges, start=1):
                    logger.info(
                        f"Fetching chunk {chunk_i}/{total_chunks}: {chunk_start.date()} to {chunk_end.date()}"
                    )

                    loop = asyncio.get_event_loop()

                    async def _fetch_range(cs, ce, timeout_s: float):
                        return await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda s=cs, e=ce: data_provider.fetch_historical(
                                    symbol=symbol,
                                    start=s,
                                    end=e,
                                    timeframe=timeframe,
                                )
                            ),
                            timeout=timeout_s,
                        )

                    try:
                        chunk_df = await _fetch_range(chunk_start, chunk_end, timeout_s=120.0)
                    except asyncio.TimeoutError:
                        chunk_df = None
                        logger.warning(
                            f"Chunk {chunk_i}/{total_chunks} timed out (weekly). Falling back to daily slices..."
                        )
                    except Exception as e:
                        chunk_df = None
                        logger.warning(
                            f"Chunk {chunk_i}/{total_chunks} failed (weekly): {e}. Falling back to daily slices..."
                        )

                    if chunk_df is not None and not chunk_df.empty:
                        all_chunks.append(chunk_df)
                        logger.info(f"Successfully fetched chunk: {len(chunk_df)} bars")
                        continue

                    # Daily fallback for this chunk (more requests, but much more reliable)
                    daily_cur = chunk_start
                    daily_chunks = []
                    while daily_cur < chunk_end:
                        daily_nxt = min(daily_cur + timedelta(days=1), chunk_end)
                        try:
                            day_df = await _fetch_range(daily_cur, daily_nxt, timeout_s=45.0)
                        except Exception:
                            day_df = None

                        if day_df is not None and not day_df.empty:
                            daily_chunks.append(day_df)
                        daily_cur = daily_nxt

                    if daily_chunks:
                        day_df_all = pd.concat(daily_chunks)
                        all_chunks.append(day_df_all)
                        logger.info(
                            f"Recovered chunk via daily slices: {len(day_df_all)} bars"
                        )
                        continue

                    # If we can't fetch anything for the earliest part of this window, shift earlier.
                    if not all_chunks:
                        logger.error(
                            f"⚠️ No data fetched for first chunk of window ({chunk_start.date()} to {chunk_end.date()}); "
                            f"trying earlier weeks..."
                        )
                        break

                    # Otherwise, we already have some data; stop here and use partial dataset.
                    logger.warning(
                        f"Stopping early due to repeated chunk failures; using partial data "
                        f"({len(all_chunks)} chunks fetched so far)."
                    )
                    break

                if all_chunks:
                    # Lock in the window that produced data
                    end = window_end
                    start = window_start
                    break

            if not all_chunks:
                logger.error("❌ No data fetched after trying multiple past windows")
                return None
            
            # Combine chunks
            # IBKRProvider returns a DatetimeIndex; do NOT drop it (older code used ignore_index=True and lost timestamps).
            df = pd.concat(all_chunks)
            if isinstance(df.index, pd.DatetimeIndex):
                df = df[~df.index.duplicated(keep='first')].sort_index()
                # Persist timestamp as a column for caching + downstream usage.
                df = df.reset_index()
                # Normalize index column name to 'timestamp' (index name can be lost during concat/reset).
                if 'timestamp' not in df.columns and len(df.columns) > 0:
                    first_col = df.columns[0]
                    df = df.rename(columns={first_col: 'timestamp'})
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.dropna(subset=["timestamp"])
            
            # Column mapping
            if 'timestamp' not in df.columns and df.index.name == 'timestamp':
                df = df.reset_index()
            
            column_mapping = {
                'Open': 'open', 'High': 'high', 'Low': 'low', 
                'Close': 'close', 'Volume': 'volume'
            }
            for old, new in column_mapping.items():
                if old in df.columns:
                    df = df.rename(columns={old: new})
            
            if 'timestamp' not in df.columns:
                if df.index.name == 'timestamp' or isinstance(df.index, pd.DatetimeIndex):
                    df = df.reset_index()
                    if 'index' in df.columns:
                        df = df.rename(columns={'index': 'timestamp'})
            
            # Normalize return shape: keep timestamp column, but ensure DatetimeIndex for resampling/backtests.
            if 'timestamp' in df.columns:
                df = df.sort_values('timestamp')
                df = df.drop_duplicates(subset=['timestamp'], keep='first')
                df = df.set_index('timestamp', drop=False)

            # Cache
            try:
                df.to_parquet(cache_file, index=False)
                logger.info(f"💾 Cached {len(df):,} bars")
            except Exception as e:
                logger.warning(f"Could not cache: {e}")
            
            logger.info(f"✅ Complete: {len(df):,} bars")
            return df
            
        except Exception as e:
            logger.error(f"Error fetching data: {e}", exc_info=True)
            return None
    
    async def _handle_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE, weeks: Optional[int] = None):
        """Handle /backtest command - run backtest and show results with chart."""
        logger.info(f"Received /backtest command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # If no weeks specified, show duration selection menu
        if weeks is None:
            mode = (context.user_data.get("backtest_mode") or "5m") if hasattr(context, "user_data") else "5m"
            if mode not in ("5m", "1m"):
                mode = "5m"
            mode_label = "5m decision (recommended)" if mode == "5m" else "1m (legacy)"

            # Preset parameters (persist per-chat)
            user_data = context.user_data if hasattr(context, "user_data") else {}
            try:
                pos_size = int(user_data.get("backtest_contracts", 5) or 5)
            except Exception:
                pos_size = 5
            try:
                slippage_ticks = float(user_data.get("backtest_slippage_ticks", 0.5) or 0.5)
            except Exception:
                slippage_ticks = 0.5

            # Execution policy: maximum concurrent positions (trade simulator)
            try:
                max_pos = int(user_data.get("backtest_max_positions", 1) or 1)
            except Exception:
                max_pos = 1
            if max_pos not in (1, 2, 3):
                max_pos = 1
            
            # Symbol selection (MNQ or NQ, default MNQ)
            symbol = user_data.get("backtest_symbol", "MNQ") if hasattr(context, "user_data") else "MNQ"
            if symbol not in ("MNQ", "NQ"):
                symbol = "MNQ"
            tick_value = 2.0 if symbol == "MNQ" else 20.0
            symbol_label = f"{symbol} (${tick_value:.0f}/pt)"

            # Simple, clean UI - smart defaults, no confusing options
            message = (
                "📊 *Backtest Strategy*\n\n"
                f"*Symbol:* {symbol} (${tick_value:.0f}/pt)\n\n"
                "Select how far back to test:\n\n"
                "_2 weeks recommended for quick validation_"
            )
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("1 Week", callback_data='backtest_1w'),
                    InlineKeyboardButton("2 Weeks ⭐", callback_data='backtest_2w'),
                ],
                [
                    InlineKeyboardButton("4 Weeks", callback_data='backtest_4w'),
                    InlineKeyboardButton("6 Weeks", callback_data='backtest_6w'),
                ],
                [
                    InlineKeyboardButton(
                        "✅ MNQ" if symbol == "MNQ" else "MNQ",
                        callback_data="backtest_setsymbol_MNQ",
                    ),
                    InlineKeyboardButton(
                        "✅ NQ" if symbol == "NQ" else "NQ",
                        callback_data="backtest_setsymbol_NQ",
                    ),
                ],
                [
                    InlineKeyboardButton("📂 Past Reports", callback_data='reports'),
                    InlineKeyboardButton("🗑️ Clear Cache", callback_data='backtest_clearcache'),
                ],
                [
                    InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
                ],
            ])
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            from pearlalgo.strategies.nq_intraday.backtest_adapter import (
                export_trade_journal,
                run_full_backtest,
                run_full_backtest_5m_decision,
            )
            from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
            
            mode = (context.user_data.get("backtest_mode") or "5m") if hasattr(context, "user_data") else "5m"
            if mode not in ("5m", "1m"):
                mode = "5m"

            # Simple message like the original that worked (NO PROGRESS BAR)
            await self._send_message_or_edit(
                update, context,
                f"📊 *Fetching Historical Data*\n\n"
                f"Mode: {'5m decision' if mode == '5m' else '1m legacy'}\n"
                f"Fetching {weeks} week{'s' if weeks > 1 else ''} of historical data for backtest...\n"
                f"This may take a moment...",
                reply_markup=None
            )
            
            # Fetch data (no progress callbacks - they interfere)
            historical_data = await self._fetch_historical_data_for_backtest(
                symbol="MNQ",
                weeks=weeks,
                timeframe="1m",
            )
            
            signals_from_backtest = []
            
            if historical_data is not None and not historical_data.empty:
                # Prepare data for backtest
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                
                # Ensure data is in correct format for backtest
                backtest_data = historical_data.copy()
                
                # CRITICAL: Ensure timestamp is properly set as DatetimeIndex
                if 'timestamp' in backtest_data.columns:
                    # Convert timestamp to datetime if it's not already
                    backtest_data['timestamp'] = pd.to_datetime(backtest_data['timestamp'])
                    backtest_data = backtest_data.set_index('timestamp')
                elif not isinstance(backtest_data.index, pd.DatetimeIndex):
                    # If index is not DatetimeIndex, try to convert it
                    logger.warning("Historical data index is not DatetimeIndex, attempting to convert")
                    if backtest_data.index.name == 'timestamp' or 'timestamp' in backtest_data.columns:
                        if 'timestamp' in backtest_data.columns:
                            backtest_data['timestamp'] = pd.to_datetime(backtest_data['timestamp'])
                            backtest_data = backtest_data.set_index('timestamp')
                        else:
                            # Try to convert the index itself
                            backtest_data.index = pd.to_datetime(backtest_data.index)
                    else:
                        # Last resort: reset index and use first datetime-like column
                        backtest_data = backtest_data.reset_index()
                        for col in backtest_data.columns:
                            if 'time' in col.lower() or 'date' in col.lower():
                                backtest_data[col] = pd.to_datetime(backtest_data[col])
                                backtest_data = backtest_data.set_index(col)
                                break
                
                # Ensure we have a DatetimeIndex
                if not isinstance(backtest_data.index, pd.DatetimeIndex):
                    raise ValueError(f"Could not convert data index to DatetimeIndex. Index type: {type(backtest_data.index)}")
                
                # Ensure required OHLCV columns exist (prefer lowercase for strategy/backtest stack)
                column_mapping = {
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                }
                for lower, upper in column_mapping.items():
                    # If provider returned uppercase, mirror to lowercase
                    if upper in backtest_data.columns and lower not in backtest_data.columns:
                        backtest_data[lower] = backtest_data[upper]
                    # If lowercase exists, optionally mirror to uppercase for any charting helpers
                    if lower in backtest_data.columns and upper not in backtest_data.columns:
                        backtest_data[upper] = backtest_data[lower]
                
                # Run backtest (default: full trade simulation)
                user_data = context.user_data if hasattr(context, "user_data") else {}
                try:
                    pos_size = int(user_data.get("backtest_contracts", 5) or 5)
                except Exception:
                    pos_size = 5
                if pos_size not in (1, 5, 10):
                    pos_size = 5
                try:
                    slippage_ticks = float(user_data.get("backtest_slippage_ticks", 0.5) or 0.5)
                except Exception:
                    slippage_ticks = 0.5
                if slippage_ticks not in (0.5, 1.0):
                    slippage_ticks = 0.5

                # Execution policy: maximum concurrent positions (trade simulator)
                try:
                    max_pos = int(user_data.get("backtest_max_positions", 1) or 1)
                except Exception:
                    max_pos = 1
                if max_pos not in (1, 2, 3):
                    max_pos = 1
                
                # Symbol selection (MNQ or NQ, default MNQ)
                symbol = user_data.get("backtest_symbol", "MNQ") if hasattr(context, "user_data") else "MNQ"
                if symbol not in ("MNQ", "NQ"):
                    symbol = "MNQ"
                tick_value = 2.0 if symbol == "MNQ" else 20.0

                config = NQIntradayConfig.from_config_file()

                if mode == "5m":
                    result = run_full_backtest_5m_decision(
                        backtest_data,
                        config=config,
                        position_size=pos_size,
                        tick_value=tick_value,
                        slippage_ticks=slippage_ticks,
                        max_concurrent_trades=max_pos,
                        return_trades=True,
                        decision_rule="5min",
                        context_rule_1="1h",
                        context_rule_2="4h",
                    )
                else:
                    result = run_full_backtest(
                        backtest_data,
                        config=config,
                        position_size=pos_size,
                        tick_value=tick_value,
                        slippage_ticks=slippage_ticks,
                        max_concurrent_trades=max_pos,
                        return_trades=True,
                    )
                        
                # Use actual signals from backtest if available
                if result.signals and len(result.signals) > 0:
                    # Use real signals from backtest
                    for signal in result.signals:
                        # Ensure timestamp is set
                        if 'timestamp' not in signal or not signal.get('timestamp'):
                            # Find closest timestamp in data
                            entry_price = signal.get('entry_price', 0)
                            if entry_price > 0:
                                close_col = 'Close' if 'Close' in backtest_data.columns else 'close'
                                closest_idx = (backtest_data[close_col] - entry_price).abs().idxmin()
                                signal['timestamp'] = closest_idx.isoformat() if hasattr(closest_idx, 'isoformat') else str(closest_idx)
                        signals_from_backtest.append(signal)
                
                # Generate backtest chart
                if self.chart_generator and not backtest_data.empty:
                    # Prefer plotting EXECUTED trade entries (less misleading + clearer than plotting all raw signals).
                    # We include trade pnl so charts can color markers by outcome (win=green, loss=red).
                    plot_signals: List[Dict] = []
                    if getattr(result, "trades", None):
                        for t in (result.trades or []):
                            ts = t.get("entry_time") or t.get("timestamp")
                            if not ts:
                                continue
                            plot_signals.append(
                                {
                                    "timestamp": ts,
                                    "direction": (t.get("direction") or "long"),
                                    "pnl": t.get("pnl"),
                                    "signal_type": t.get("signal_type"),
                                }
                            )
                    plot_label = "trade entries" if plot_signals else "signals"
                    if not plot_signals:
                        plot_signals = signals_from_backtest

                    # Limit for Telegram readability (avoid thousands of markers)
                    MAX_MARKERS = 250
                    signals_shown = min(len(plot_signals), MAX_MARKERS)
                    plot_signals = plot_signals[-signals_shown:] if signals_shown > 0 else []
                    
                    # Compact title (chart generator will add timeframe label)
                    data_start = backtest_data.index[0].strftime('%Y-%m-%d') if len(backtest_data) > 0 else 'N/A'
                    data_end = backtest_data.index[-1].strftime('%Y-%m-%d') if len(backtest_data) > 0 else 'N/A'
                    chart_title = f"{symbol} Backtest {data_start} to {data_end} | sig {result.total_signals} | tr {result.total_trades or 0}"
                    
                    # Prepare performance data
                    performance_data = {
                        "total_signals": result.total_signals,
                        "avg_confidence": result.avg_confidence,
                        "avg_risk_reward": result.avg_risk_reward,
                        "win_rate": result.win_rate if result.win_rate is not None else 0.0,
                        "total_pnl": result.total_pnl if result.total_pnl is not None else 0.0,
                        "total_trades": result.total_trades if result.total_trades is not None else 0,
                        "profit_factor": result.profit_factor if result.profit_factor is not None else 0.0,
                        "max_drawdown": result.max_drawdown if result.max_drawdown is not None else 0.0,
                        "sharpe_ratio": result.sharpe_ratio if result.sharpe_ratio is not None else 0.0,
                    }
                    
                    # Convert back to format expected by chart generator (reset index to get timestamp column)
                    # SMART TIMEFRAME: For long backtests, use higher timeframes for readable charts
                    # - 1-2 weeks: 5m candles (~288-576 candles)
                    # - 3-4 weeks: 1H candles (~120-160 candles)
                    # - 5-6 weeks: 4H candles (~60-90 candles)
                    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
                    if "volume" in backtest_data.columns:
                        agg["volume"] = "sum"
                    
                    if weeks <= 2:
                        # Short backtest: use 5m candles for detail
                        chart_tf = "5min"
                        chart_tf_label = "5m"
                    elif weeks <= 4:
                        # Medium backtest: use 1H candles for readability
                        chart_tf = "1H"
                        chart_tf_label = "1H"
                    else:
                        # Long backtest: use 4H candles for overview
                        chart_tf = "4H"
                        chart_tf_label = "4H"
                    
                    df_resampled = backtest_data.resample(chart_tf).agg(agg).dropna()
                    chart_data = df_resampled.reset_index()
                    
                    if 'timestamp' not in chart_data.columns and chart_data.index.name == 'timestamp':
                        chart_data = chart_data.reset_index()
                    
                    # Keep chart title compact; `generate_backtest_chart()` appends timeframe label.
                    
                    # Use larger figure for longer backtests
                    if weeks >= 4:
                        figsize = (18, 10)
                        dpi = 200
                    else:
                        figsize = (16, 9)
                        dpi = 150
                    
                    # For long backtests (4+ weeks), generate equity curve as primary chart
                    # For shorter backtests, use traditional candlestick/line price chart
                    chart_path = None
                    equity_chart_path = None
                    
                    if result.trades:
                        # Generate equity curve (best backtest overview, even for 2 weeks)
                        equity_chart_path = self.chart_generator.generate_equity_curve_chart(
                            result.trades,
                            symbol,
                            f"{symbol} Equity Curve ({data_start} to {data_end})",
                            performance_data=performance_data,
                            figsize=figsize,
                            dpi=dpi,
                        )
                        # Prefer equity curve as the primary chart when available
                        chart_path = equity_chart_path
                    
                    # Generate price chart (line chart for 6+ weeks, candles for shorter)
                    use_line = weeks >= 6
                    price_chart_path = self.chart_generator.generate_backtest_chart(
                        chart_data,
                        plot_signals,
                        symbol,
                        chart_title,
                        performance_data=performance_data,
                        timeframe=chart_tf_label,
                        figsize=figsize,
                        dpi=dpi,
                        use_line_chart=use_line,
                    )
                    
                    # Use price chart as primary if we don't have equity curve
                    if chart_path is None:
                        chart_path = price_chart_path

                    # Auto-save this Telegram /backtest run into /reports so every run is browseable.
                    saved_report_dir: Optional[Path] = None
                    saved_report_name: Optional[str] = None
                    saved_report_key: Optional[str] = None
                    try:
                        reports_dir = self._get_reports_dir_for_write()
                        run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                        rep_start = backtest_data.index[0].strftime("%Y%m%d") if len(backtest_data) > 0 else "unknown"
                        rep_end = backtest_data.index[-1].strftime("%Y%m%d") if len(backtest_data) > 0 else "unknown"
                        saved_report_name = f"backtest_{symbol}_{mode}_{rep_start}_{rep_end}_{run_ts}"
                        saved_report_dir = reports_dir / saved_report_name
                        saved_report_dir.mkdir(parents=True, exist_ok=True)

                        # Summary JSON (compatible with /reports viewer)
                        metrics_obj = {
                            "total_bars": int(result.total_bars or 0),
                            "total_signals": int(result.total_signals or 0),
                            "avg_confidence": float(result.avg_confidence or 0.0),
                            "avg_risk_reward": float(result.avg_risk_reward or 0.0),
                            "total_trades": int(result.total_trades or 0),
                            "winning_trades": int(result.winning_trades or 0),
                            "losing_trades": int(result.losing_trades or 0),
                            "win_rate": float(result.win_rate or 0.0),
                            "total_pnl": float(result.total_pnl or 0.0),
                            "profit_factor": float(result.profit_factor or 0.0),
                            "max_drawdown": float(result.max_drawdown or 0.0),
                            "max_drawdown_pct": float(getattr(result, "max_drawdown_pct", 0.0) or 0.0),
                            "sharpe_ratio": float(result.sharpe_ratio or 0.0),
                            "avg_win": float(getattr(result, "avg_win", 0.0) or 0.0),
                            "avg_loss": float(getattr(result, "avg_loss", 0.0) or 0.0),
                            "avg_hold_time_minutes": float(getattr(result, "avg_hold_time_minutes", 0.0) or 0.0),
                            "signal_distribution": getattr(result, "signal_distribution", None),
                        }
                        summary = {
                            "symbol": symbol,
                            "decision_timeframe": mode,
                            "run_timestamp": run_ts,
                            "date_range": {
                                "dataset_start": backtest_data.index[0].isoformat() if len(backtest_data) > 0 else None,
                                "dataset_end": backtest_data.index[-1].isoformat() if len(backtest_data) > 0 else None,
                                "requested_start": None,
                                "requested_end": None,
                                "actual_start": backtest_data.index[0].isoformat() if len(backtest_data) > 0 else None,
                                "actual_end": backtest_data.index[-1].isoformat() if len(backtest_data) > 0 else None,
                                "bars_total": int(len(backtest_data)),
                                "bars_sliced": int(len(backtest_data)),
                                "warning": None,
                            },
                            "metrics": metrics_obj,
                            "verification": result.verification.to_dict() if getattr(result, "verification", None) else None,
                        }
                        with open(saved_report_dir / "summary.json", "w") as f:
                            json.dump(summary, f, indent=2)

                        # Signals CSV
                        try:
                            if getattr(result, "signals", None):
                                signals_df = pd.DataFrame(result.signals or [])
                                for col in signals_df.columns:
                                    if signals_df[col].apply(lambda x: isinstance(x, dict)).any():
                                        signals_df[col] = signals_df[col].apply(lambda x: json.dumps(x) if isinstance(x, dict) else x)
                                signals_df.to_csv(saved_report_dir / "signals.csv", index=False)
                        except Exception:
                            pass

                        # Trades CSV
                        try:
                            if getattr(result, "trades", None):
                                pd.DataFrame(result.trades or []).to_csv(saved_report_dir / "trades.csv", index=False)
                        except Exception:
                            pass

                        # Skipped signals CSV
                        try:
                            if getattr(result, "skipped_signals", None):
                                pd.DataFrame(result.skipped_signals or []).to_csv(saved_report_dir / "skipped_signals.csv", index=False)
                        except Exception:
                            pass

                        # Persist charts into the report folder (so /reports can serve them)
                        try:
                            if price_chart_path and price_chart_path.exists():
                                dest_price = saved_report_dir / "chart_overview.png"
                                try:
                                    shutil.move(str(price_chart_path), str(dest_price))
                                except Exception:
                                    shutil.copy2(str(price_chart_path), str(dest_price))
                                if chart_path == price_chart_path:
                                    chart_path = dest_price
                                price_chart_path = dest_price
                        except Exception:
                            pass
                        try:
                            if equity_chart_path and equity_chart_path.exists():
                                dest_eq = saved_report_dir / "equity_curve.png"
                                try:
                                    shutil.move(str(equity_chart_path), str(dest_eq))
                                except Exception:
                                    shutil.copy2(str(equity_chart_path), str(dest_eq))
                                if chart_path == equity_chart_path:
                                    chart_path = dest_eq
                                equity_chart_path = dest_eq
                        except Exception:
                            pass

                        # Detailed PDF report (multi-page)
                        try:
                            write_backtest_pdf_report(saved_report_dir, output_name="report.pdf")
                        except Exception as e:
                            logger.warning(f"Could not write PDF report: {e}")

                        saved_report_key = self._report_key(saved_report_name)
                    except Exception as e:
                        logger.warning(f"Could not save backtest report: {e}")
                        saved_report_dir = None
                        saved_report_name = None
                        saved_report_key = None
                            
                    # Format results message
                    data_start = backtest_data.index[0].strftime('%Y-%m-%d') if len(backtest_data) > 0 else 'N/A'
                    data_end = backtest_data.index[-1].strftime('%Y-%m-%d') if len(backtest_data) > 0 else 'N/A'
                    
                    win_rate_display = f"{result.win_rate:.1%}" if result.win_rate is not None else "N/A"
                    total_pnl_display = f"${result.total_pnl:.2f}" if result.total_pnl is not None else "N/A"
                    profit_factor_display = f"{result.profit_factor:.2f}" if result.profit_factor is not None else "N/A"
                    max_dd_display = f"${result.max_drawdown:.2f}" if result.max_drawdown is not None else "N/A"
                    sharpe_display = f"{result.sharpe_ratio:.2f}" if result.sharpe_ratio is not None else "N/A"
                    trades_display = f"{result.total_trades}" if result.total_trades is not None else "0"
                    
                    # Format verification summary if available
                    verification_block = ""
                    if result.verification:
                        verification_block = f"\n🔍 *Verification*\n{result.verification.format_compact()}\n"

                    # Trade breakdown by signal type (helps refine strategy quickly)
                    trade_type_block = ""
                    try:
                        if getattr(result, "trades", None):
                            by_type: Dict[str, Dict[str, float]] = {}
                            for t in (result.trades or []):
                                st = str(t.get("signal_type") or "unknown")
                                try:
                                    pnl = float(t.get("pnl") or 0.0)
                                except Exception:
                                    pnl = 0.0
                                wins = 1.0 if pnl > 0 else 0.0
                                losses = 1.0 if pnl < 0 else 0.0

                                if st not in by_type:
                                    by_type[st] = {"n": 0.0, "wins": 0.0, "losses": 0.0, "pnl_total": 0.0}
                                by_type[st]["n"] += 1.0
                                by_type[st]["wins"] += wins
                                by_type[st]["losses"] += losses
                                by_type[st]["pnl_total"] += pnl

                            if by_type:
                                ranked = sorted(by_type.items(), key=lambda kv: float(kv[1].get("pnl_total", 0.0)), reverse=True)
                                best_k, best_v = ranked[0]
                                worst_k, worst_v = ranked[-1]

                                def _fmt_type(k: str) -> str:
                                    # Avoid underscores triggering Telegram markdown
                                    return safe_label(k.replace("_", " "))

                                def _fmt_wr(v: Dict[str, float]) -> str:
                                    n = float(v.get("n", 0.0) or 0.0)
                                    w = float(v.get("wins", 0.0) or 0.0)
                                    return f"{(w / n * 100.0):.1f}%" if n > 0 else "N/A"

                                trade_type_block = (
                                    "\n📌 *Trade Types (this run)*\n"
                                    f"✅ Best: {_fmt_type(best_k)}  |  n={int(best_v.get('n', 0))}  |  WR {_fmt_wr(best_v)}  |  P&L {_format_currency(float(best_v.get('pnl_total', 0.0)))}\n"
                                    f"❌ Worst: {_fmt_type(worst_k)}  |  n={int(worst_v.get('n', 0))}  |  WR {_fmt_wr(worst_v)}  |  P&L {_format_currency(float(worst_v.get('pnl_total', 0.0)))}\n"
                                )
                    except Exception:
                        trade_type_block = ""

                    saved_report_block = ""
                    if saved_report_name:
                        saved_report_block = f"\n📂 *Saved to Reports:* `{saved_report_name}`\n"

                    message = (
                        f"📊 *Backtest Results ({weeks} Week{'s' if weeks > 1 else ''})*\n\n"
                        f"*Period:* {data_start} to {data_end}\n"
                        f"*Bars Analyzed:* {result.total_bars:,}\n"
                        f"*Signals Generated:* {result.total_signals}\n"
                        f"*Chart markers:* {signals_shown} {plot_label} (green=win, red=loss)\n\n"
                        f"*Symbol:* {symbol} (${tick_value:.0f}/pt)  |  *Contracts:* {pos_size}\n"
                        f"*Slippage:* {slippage_ticks} ticks  |  *Max pos:* {max_pos}\n"
                        f"*Trades:* {trades_display}  |  *Win Rate:* {win_rate_display}  |  *PF:* {profit_factor_display}\n"
                        f"*Avg Confidence:* {result.avg_confidence:.2f}\n"
                        f"*Avg R:R:* {result.avg_risk_reward:.2f}:1\n"
                        f"*Total P&L:* {total_pnl_display}  |  *Max DD:* {max_dd_display}  |  *Sharpe:* {sharpe_display}\n"
                        f"{trade_type_block}"
                        f"{verification_block}"
                        f"{saved_report_block}"
                    )
                            
                    # Export artifacts (trade journal + metrics + verification)
                    export_paths: Dict[str, str] = {}
                    try:
                        exports_dir = self.state_dir / "exports"
                        exports_dir.mkdir(parents=True, exist_ok=True)
                        ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                        base_name = f"backtest_{mode}_{symbol}_{weeks}w_mp{max_pos}_{ts_tag}"

                        # Metrics JSON (always) - now includes compact verification summary
                        metrics_path = exports_dir / f"{base_name}_metrics.json"
                        metrics_obj = {
                            "mode": mode,
                            "symbol": symbol,
                            "tick_value": tick_value,
                            "weeks": weeks,
                            "contracts": pos_size,
                            "slippage_ticks": slippage_ticks,
                            "max_concurrent_trades": max_pos,
                            "total_bars": result.total_bars,
                            "total_signals": result.total_signals,
                            "avg_confidence": result.avg_confidence,
                            "avg_risk_reward": result.avg_risk_reward,
                            "total_trades": result.total_trades,
                            "win_rate": result.win_rate,
                            "total_pnl": result.total_pnl,
                            "profit_factor": result.profit_factor,
                            "max_drawdown": result.max_drawdown,
                            "max_drawdown_pct": result.max_drawdown_pct,
                            "sharpe_ratio": result.sharpe_ratio,
                            "avg_win": result.avg_win,
                            "avg_loss": result.avg_loss,
                            "avg_hold_time_minutes": result.avg_hold_time_minutes,
                        }
                        # Trade type stats (executed trades only) — helps post-run refinement.
                        try:
                            if getattr(result, "trades", None):
                                tstats: Dict[str, Dict[str, float]] = {}
                                # Also track by regime
                                regime_stats: Dict[str, Dict[str, Dict[str, float]]] = {}
                                for t in (result.trades or []):
                                    st = str(t.get("signal_type") or "unknown")
                                    try:
                                        pnl = float(t.get("pnl") or 0.0)
                                    except Exception:
                                        pnl = 0.0
                                    win = 1.0 if pnl > 0 else 0.0
                                    if st not in tstats:
                                        tstats[st] = {"n": 0.0, "wins": 0.0, "pnl_total": 0.0}
                                    tstats[st]["n"] += 1.0
                                    tstats[st]["wins"] += win
                                    tstats[st]["pnl_total"] += pnl
                                    
                                    # Track by regime (signal_type -> regime -> stats)
                                    regime = str(t.get("regime") or "unknown")
                                    if st not in regime_stats:
                                        regime_stats[st] = {}
                                    if regime not in regime_stats[st]:
                                        regime_stats[st][regime] = {"n": 0.0, "wins": 0.0, "pnl_total": 0.0}
                                    regime_stats[st][regime]["n"] += 1.0
                                    regime_stats[st][regime]["wins"] += win
                                    regime_stats[st][regime]["pnl_total"] += pnl
                                    
                                # Add win_rate per type
                                out: Dict[str, Dict[str, float]] = {}
                                for st, v in tstats.items():
                                    n = float(v.get("n", 0.0) or 0.0)
                                    w = float(v.get("wins", 0.0) or 0.0)
                                    out[st] = {
                                        "n": n,
                                        "wins": w,
                                        "win_rate": (w / n) if n > 0 else 0.0,
                                        "pnl_total": float(v.get("pnl_total", 0.0) or 0.0),
                                    }
                                metrics_obj["trade_type_stats"] = out
                                
                                # Compute regime breakdown with win_rate
                                regime_out: Dict[str, Dict[str, Dict[str, float]]] = {}
                                for st, regimes in regime_stats.items():
                                    regime_out[st] = {}
                                    for regime, v in regimes.items():
                                        n = float(v.get("n", 0.0) or 0.0)
                                        w = float(v.get("wins", 0.0) or 0.0)
                                        regime_out[st][regime] = {
                                            "n": n,
                                            "wins": w,
                                            "win_rate": (w / n) if n > 0 else 0.0,
                                            "pnl_total": float(v.get("pnl_total", 0.0) or 0.0),
                                        }
                                metrics_obj["trade_type_by_regime"] = regime_out
                        except Exception:
                            pass
                        # Embed compact verification in metrics
                        if result.verification:
                            metrics_obj["verification_summary"] = {
                                "signals_per_day": result.verification.signals_per_day,
                                "trading_days": result.verification.trading_days,
                                "top_bottlenecks": list(result.verification.bottleneck_summary.keys())[:3] if result.verification.bottleneck_summary else [],
                            }
                        with open(metrics_path, "w") as f:
                            json.dump(metrics_obj, f, indent=2)
                        export_paths["metrics"] = str(metrics_path)

                        # Verification JSON (full diagnostics)
                        if result.verification:
                            verification_path = exports_dir / f"{base_name}_verification.json"
                            with open(verification_path, "w") as f:
                                json.dump(result.verification.to_dict(), f, indent=2)
                            export_paths["verification"] = str(verification_path)

                        # Trades (if available)
                        if getattr(result, "trades", None):
                            trades_csv = exports_dir / f"{base_name}_trades.csv"
                            trades_json = exports_dir / f"{base_name}_trades.json"
                            export_trade_journal(result.trades, str(trades_csv), format="csv")
                            export_trade_journal(result.trades, str(trades_json), format="json")
                            export_paths["csv"] = str(trades_csv)
                            export_paths["json"] = str(trades_json)

                        if hasattr(context, "user_data"):
                            context.user_data["backtest_export_paths"] = export_paths
                    except Exception as e:
                        logger.warning(f"Could not create export artifacts: {e}")

                    # Buttons
                    keyboard = []
                    export_row = []
                    if export_paths.get("csv"):
                        export_row.append(InlineKeyboardButton("📄 Trades CSV", callback_data="backtest_export:csv"))
                    if export_paths.get("json"):
                        export_row.append(InlineKeyboardButton("🧾 Trades JSON", callback_data="backtest_export:json"))
                    if export_row:
                        keyboard.append(export_row)
                    export_row2 = [InlineKeyboardButton("📊 Metrics", callback_data="backtest_export:metrics")]
                    if export_paths.get("verification"):
                        export_row2.append(InlineKeyboardButton("🔍 Verification", callback_data="backtest_export:verification"))
                    keyboard.append(export_row2)
                    if saved_report_key:
                        keyboard.append(
                            [
                                InlineKeyboardButton("📂 View Report", callback_data=f"report_detail_k:{saved_report_key}"),
                                InlineKeyboardButton("📄 PDF", callback_data=f"report_artifact_k:{saved_report_key}:pdf"),
                            ]
                        )
                    keyboard.append([
                        InlineKeyboardButton("🔄 Run Again", callback_data="backtest"),
                        InlineKeyboardButton("🏠 Main Menu", callback_data="start"),
                    ])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                    
                    # Send charts
                    # For long backtests (4+ weeks), send equity curve first, then price chart
                    # For short backtests, send price chart only
                    if chart_path and chart_path.exists():
                        try:
                            # Send primary chart (equity curve when available, otherwise price chart)
                            chart_type = "Equity Curve" if equity_chart_path and chart_path == equity_chart_path else "Price Chart"
                            with open(chart_path, 'rb') as photo:
                                if update.callback_query:
                                    await context.bot.send_photo(
                                        chat_id=update.effective_chat.id,
                                        photo=photo,
                                        caption=f"📈 {chart_type} ({weeks} Week{'s' if weeks > 1 else ''})"
                                    )
                                else:
                                    await update.message.reply_photo(
                                        photo=photo,
                                        caption=f"📈 {chart_type} ({weeks} Week{'s' if weeks > 1 else ''})"
                                    )
                            # Keep charts if we saved a report; otherwise clean up temp files.
                            try:
                                if not (saved_report_dir and saved_report_dir in chart_path.parents):
                                    chart_path.unlink()
                            except Exception:
                                pass
                            
                            # Also send the price chart if we have a separate file (common when equity curve is primary)
                            if price_chart_path and price_chart_path.exists() and (chart_path is None or price_chart_path != chart_path):
                                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
                                chart_type_label = "Line" if use_line else "Candlestick"
                                with open(price_chart_path, 'rb') as photo:
                                    await context.bot.send_photo(
                                        chat_id=update.effective_chat.id,
                                        photo=photo,
                                        caption=f"📊 {chart_type_label} Chart ({weeks} Week{'s' if weeks > 1 else ''}, {chart_tf_label} bars) • entries: green=win red=loss"
                                    )
                                try:
                                    if not (saved_report_dir and saved_report_dir in price_chart_path.parents):
                                        price_chart_path.unlink()
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.error(f"Error sending backtest chart: {e}")
                else:
                    message = (
                        "📊 *Backtest Results*\n\n"
                        f"*Bars Analyzed:* {result.total_bars:,}\n"
                        f"*Signals Generated:* {result.total_signals}\n"
                        f"*Avg Confidence:* {result.avg_confidence:.2f}\n"
                        f"*Avg R:R:* {result.avg_risk_reward:.2f}:1\n\n"
                        "⚠️ Chart generation not available"
                    )
                    reply_markup = self._get_back_to_menu_button()
                    await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            else:
                # Failed to fetch historical data - check for any cached data
                cache_files = list(self._historical_cache_dir.glob("MNQ_1m_*.parquet"))
                cache_info = ""
                if cache_files:
                    # Find the most recent cache
                    most_recent = max(cache_files, key=lambda f: f.stat().st_mtime)
                    cache_age = datetime.now(timezone.utc) - datetime.fromtimestamp(
                        most_recent.stat().st_mtime, tz=timezone.utc
                    )
                    cache_info = (
                        f"\n💡 *Found cached data:* {most_recent.name} ({cache_age.days} days old)\n"
                        f"   Try using cached data (recommended) or retry fetching."
                    )
                else:
                    cache_info = (
                        "\n⚠️ *No cached data found.*\n"
                        "   IBKR HMDS may be timing out or rate-limiting requests.\n"
                        "   Try again in a few minutes or choose a shorter backtest window."
                    )
                
                message = (
                    "📊 *Backtest Strategy*\n\n"
                    "❌ Could not fetch historical data for backtest.\n\n"
                    "*Likely causes:*\n"
                    "• IBKR HMDS timeout / temporary outage\n"
                    "• Pacing / rate limiting on historical requests\n"
                    "• Contract rollover edge-case\n\n"
                    f"{cache_info}\n\n"
                    "*Solutions:*\n"
                    "1. Try again (sometimes HMDS recovers within minutes)\n"
                    "2. Choose a shorter backtest window (1–2 weeks)\n"
                    "3. Use command line with an existing data file:\n"
                    "```bash\n"
                    "python scripts/backtesting/backtest_cli.py signal --data-path data.parquet\n"
                    "```\n"
                    "4. If it still fails, retry later (IBKR side)"
                )
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Try Again", callback_data='backtest'),
                    InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
                ]])
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                
        except Exception as e:
            logger.error(f"Error handling backtest command: {e}", exc_info=True)
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(
                update, context,
                f"❌ *Error:* {str(e)}",
                reply_markup=reply_markup
            )

    async def _handle_backtest_export(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        kind: str,
    ) -> None:
        """Send the most recent backtest export artifact (CSV/JSON/Metrics/Verification).

        Important UX note:
        - Do NOT edit/replace the backtest results message when exporting, otherwise
          the user loses access to the other export buttons.
        """
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        paths = {}
        if hasattr(context, "user_data"):
            paths = context.user_data.get("backtest_export_paths", {}) or {}

        key = kind.lower().strip()
        if key not in ("csv", "json", "metrics", "verification"):
            key = "metrics"

        target = paths.get(key)
        if not target:
            # Fallback: if the handler was restarted (lost in-memory user_data),
            # try to locate the most recent export artifact from disk.
            try:
                exports_dir = self.state_dir / "exports"
                suffix_by_key = {
                    "csv": "_trades.csv",
                    "json": "_trades.json",
                    "metrics": "_metrics.json",
                    "verification": "_verification.json",
                }
                suffix = suffix_by_key.get(key, "_metrics.json")
                candidates = sorted(
                    exports_dir.glob(f"backtest_*{suffix}"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    target = str(candidates[0])
            except Exception:
                target = None

        if not target:
            # Send a new message (do not replace the backtest results).
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    "❌ *No export available*\n\n"
                    "Run a backtest first, then try export again."
                ),
            )
            return

        try:
            p = Path(target)
            if not p.exists() or not p.is_file():
                raise FileNotFoundError(str(p))

            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")
            with open(p, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=p.name,
                )
        except Exception as e:
            logger.error(f"Error exporting backtest artifact: {e}", exc_info=True)
            # Send a new message (do not replace the backtest results).
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ *Export failed*\n\n`{str(e)}`",
            )

    async def _handle_performance_export(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        kind: str,
    ) -> None:
        """Send the most recent performance export artifact."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        paths = {}
        if hasattr(context, "user_data"):
            paths = context.user_data.get("performance_export_paths", {}) or {}

        key = kind.lower().strip()
        if key == "signals":
            target = paths.get("signals_jsonl")
        elif key == "exited":
            target = paths.get("exited_csv")
        else:
            target = paths.get("metrics")

        if not target:
            await self._send_message_or_edit(
                update,
                context,
                "❌ *No export available*\n\nOpen `/performance` first to generate export files.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                ]),
            )
            return

        try:
            p = Path(target)
            if not p.exists() or not p.is_file():
                raise FileNotFoundError(str(p))

            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")
            with open(p, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=p.name,
                )

            await self._send_message_or_edit(
                update,
                context,
                f"✅ Sent `{p.name}`",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                ]),
            )
        except Exception as e:
            logger.error(f"Error exporting performance artifact: {e}", exc_info=True)
            await self._send_message_or_edit(
                update,
                context,
                f"❌ *Export failed*\n\n`{str(e)}`",
                reply_markup=self._get_back_to_menu_button(),
            )
    
    async def _handle_backtest_reports(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        page: int = 0,
    ) -> None:
        """Handle /reports command - browse saved backtest reports from reports/ directory."""
        logger.info(f"Received backtest_reports request from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        try:
            # Find reports directory (relative to project root)
            reports_dir = Path(self.state_dir.parent / "reports")
            if not reports_dir.exists():
                # Try alternate location
                reports_dir = Path.cwd() / "reports"

            if not reports_dir.exists():
                await self._send_message_or_edit(
                    update, context,
                    "📂 *Backtest Reports*\n\n"
                    "No reports directory found.\n\n"
                    "Run a backtest using the CLI to generate reports:\n"
                    "`python scripts/backtesting/backtest_cli.py full --data-path <file>`",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📉 Run Backtest", callback_data='backtest')],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data='start')],
                    ]),
                )
                return

            # List report directories (sorted by modification time, newest first)
            report_dirs = sorted(
                [d for d in reports_dir.iterdir() if d.is_dir() and d.name.startswith("backtest_")],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )

            if not report_dirs:
                await self._send_message_or_edit(
                    update, context,
                    "📂 *Backtest Reports*\n\n"
                    "No saved reports found.\n\n"
                    "Run a backtest using the CLI to generate reports:\n"
                    "`python scripts/backtesting/backtest_cli.py full --data-path <file>`",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📉 Run Backtest", callback_data='backtest')],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data='start')],
                    ]),
                )
                return

            # Paginate (5 reports per page)
            page_size = 5
            total_reports = len(report_dirs)
            total_pages = (total_reports + page_size - 1) // page_size
            page = max(0, min(page, total_pages - 1))
            start_idx = page * page_size
            end_idx = min(start_idx + page_size, total_reports)
            page_reports = report_dirs[start_idx:end_idx]

            message = f"📂 *Backtest Reports* ({total_reports} total)\n\n"

            keyboard = []
            for rd in page_reports:
                # Parse report name for display
                # Format: backtest_<symbol>_<tf>_<start>_<end>_<timestamp>
                parts = rd.name.split("_")
                if len(parts) >= 5:
                    symbol = parts[1]
                    tf = parts[2]
                    start_date = parts[3] if len(parts) > 3 else "?"
                    end_date = parts[4] if len(parts) > 4 else "?"
                    label = f"{symbol} {tf} ({start_date}→{end_date})"
                else:
                    label = rd.name[-30:] if len(rd.name) > 30 else rd.name

                # Load summary for quick metrics
                summary_file = rd / "summary.json"
                if summary_file.exists():
                    try:
                        with open(summary_file) as f:
                            summary = json.load(f)
                        metrics = summary.get("metrics", {})
                        pnl = metrics.get("total_pnl", 0)
                        wr = metrics.get("win_rate", 0) or 0
                        pnl_str = f"${pnl:+,.0f}" if pnl else "$0"
                        label = f"{label} • {pnl_str} • {wr*100:.0f}%WR"
                    except Exception:
                        pass

                report_key = self._report_key(rd.name)
                keyboard.append([
                    InlineKeyboardButton(label, callback_data=f"report_detail_k:{report_key}")
                ])

            # Pagination buttons
            if total_pages > 1:
                nav_row = []
                if page > 0:
                    nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f'reports_page:{page-1}'))
                nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data='noop'))
                if page < total_pages - 1:
                    nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f'reports_page:{page+1}'))
                keyboard.append(nav_row)

            keyboard.append([
                InlineKeyboardButton("📉 New Backtest", callback_data='backtest'),
                InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
            ])

            await self._send_message_or_edit(
                update, context,
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        except Exception as e:
            logger.error(f"Error listing backtest reports: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                f"❌ Error loading reports: {str(e)}",
                reply_markup=self._get_back_to_menu_button(),
            )

    async def _handle_report_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        report_name: str,
    ) -> None:
        """Show details of a specific backtest report."""
        logger.info(f"Showing report detail: {report_name}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        try:
            # Find report directory
            reports_dir = Path(self.state_dir.parent / "reports")
            if not reports_dir.exists():
                reports_dir = Path.cwd() / "reports"

            report_dir = reports_dir / report_name
            if not report_dir.exists():
                await self._send_message_or_edit(
                    update, context,
                    f"❌ Report not found: `{report_name}`",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📂 Reports", callback_data='reports')],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data='start')],
                    ]),
                )
                return

            summary_file = report_dir / "summary.json"
            if not summary_file.exists():
                await self._send_message_or_edit(
                    update, context,
                    f"❌ Report summary not found for `{report_name}`",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📂 Reports", callback_data='reports')],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data='start')],
                    ]),
                )
                return

            with open(summary_file) as f:
                summary = json.load(f)

            metrics = summary.get("metrics", {})
            date_range = summary.get("date_range", {})
            verification = summary.get("verification", {})

            # Format message
            symbol = summary.get("symbol", "?")
            tf = summary.get("decision_timeframe", "?")
            
            actual_start = date_range.get("actual_start", "?")[:10] if date_range.get("actual_start") else "?"
            actual_end = date_range.get("actual_end", "?")[:10] if date_range.get("actual_end") else "?"

            total_trades = metrics.get("total_trades", 0) or 0
            win_rate = (metrics.get("win_rate", 0) or 0) * 100
            pf = metrics.get("profit_factor", 0) or 0
            total_pnl = metrics.get("total_pnl", 0) or 0
            max_dd = metrics.get("max_drawdown", 0) or 0
            sharpe = metrics.get("sharpe_ratio", 0) or 0
            total_signals = metrics.get("total_signals", 0) or 0
            avg_conf = metrics.get("avg_confidence", 0) or 0
            avg_rr = metrics.get("avg_risk_reward", 0) or 0

            message = (
                f"📊 *Report: {symbol} {tf}*\n"
                f"Period: {actual_start} → {actual_end}\n\n"
                f"*Performance*\n"
                f"Trades: {total_trades} | Win Rate: {win_rate:.1f}%\n"
                f"P&L: ${total_pnl:+,.2f} | PF: {pf:.2f}\n"
                f"Max DD: ${max_dd:,.2f} | Sharpe: {sharpe:.2f}\n\n"
                f"*Signals*\n"
                f"Total: {total_signals} | Avg Conf: {avg_conf:.2f}\n"
                f"Avg R:R: {avg_rr:.2f}:1\n"
            )

            # Verification summary
            if verification:
                exec_summary = verification.get("execution_summary", {})
                opened = exec_summary.get("signals_opened", 0)
                skipped = exec_summary.get("signals_skipped_concurrency", 0)
                if opened or skipped:
                    message += f"\n*Execution*\n{opened} opened, {skipped} skipped\n"

                bottlenecks = verification.get("bottleneck_summary", {})
                if bottlenecks:
                    top_3 = sorted(bottlenecks.items(), key=lambda x: -x[1])[:3]
                    bn_str = ", ".join([f"{k}: {v}" for k, v in top_3])
                    message += f"\n*Bottlenecks*\n{bn_str}\n"

            # Warning if present
            warning = date_range.get("warning")
            if warning:
                message += f"\n⚠️ {warning}\n"

            # Build artifact buttons
            keyboard = []
            report_key = self._report_key(report_name)
            
            # Check available artifacts
            chart_row = []
            if (report_dir / "chart_overview.png").exists():
                chart_row.append(InlineKeyboardButton("📈 View Chart", callback_data=f"report_artifact_k:{report_key}:chart"))
            if (report_dir / "report.pdf").exists():
                chart_row.append(InlineKeyboardButton("📄 PDF Report", callback_data=f"report_artifact_k:{report_key}:pdf"))
            if chart_row:
                keyboard.append(chart_row)
            
            artifact_row = []
            if (report_dir / "trades.csv").exists():
                artifact_row.append(InlineKeyboardButton("📄 Trades", callback_data=f"report_artifact_k:{report_key}:trades"))
            if (report_dir / "signals.csv").exists():
                artifact_row.append(InlineKeyboardButton("📄 Signals", callback_data=f"report_artifact_k:{report_key}:signals"))
            if artifact_row:
                keyboard.append(artifact_row)

            artifact_row2 = []
            if (report_dir / "skipped_signals.csv").exists():
                artifact_row2.append(InlineKeyboardButton("📄 Skipped", callback_data=f"report_artifact_k:{report_key}:skipped"))
            if (report_dir / "summary.json").exists():
                artifact_row2.append(InlineKeyboardButton("📄 Summary", callback_data=f"report_artifact_k:{report_key}:summary"))
            if artifact_row2:
                keyboard.append(artifact_row2)

            keyboard.append([
                InlineKeyboardButton("📂 All Reports", callback_data='reports'),
                InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
            ])

            await self._send_message_or_edit(
                update, context,
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        except Exception as e:
            logger.error(f"Error showing report detail: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                f"❌ Error loading report: {str(e)}",
                reply_markup=self._get_back_to_menu_button(),
            )

    async def _handle_report_artifact(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        report_name: str,
        artifact: str,
    ) -> None:
        """Send a specific artifact from a backtest report."""
        logger.info(f"Sending report artifact: {report_name}/{artifact}")
        if not await self._check_authorized(update):
            return

        try:
            reports_dir = Path(self.state_dir.parent / "reports")
            if not reports_dir.exists():
                reports_dir = Path.cwd() / "reports"

            report_dir = reports_dir / report_name
            
            # Map artifact type to file
            file_map = {
                "chart": "chart_overview.png",
                "pdf": "report.pdf",
                "trades": "trades.csv",
                "signals": "signals.csv",
                "skipped": "skipped_signals.csv",
                "summary": "summary.json",
            }
            
            filename = file_map.get(artifact)
            if not filename:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ Unknown artifact type: {artifact}",
                )
                return

            filepath = report_dir / filename
            if not filepath.exists():
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ Artifact not found: {filename}",
                )
                return

            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action="upload_photo" if artifact == "chart" else "upload_document",
            )

            if artifact == "chart":
                with open(filepath, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=f,
                        caption=f"📊 {report_name}",
                    )
            else:
                with open(filepath, "rb") as f:
                    caption = None
                    if artifact == "pdf":
                        caption = "📄 Detailed PDF report"
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=f,
                        filename=filepath.name,
                        caption=caption,
                    )

        except Exception as e:
            logger.error(f"Error sending report artifact: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Error sending artifact: {str(e)}",
            )

    # -------------------------------------------------------------------------
    # Reports: stable short IDs to satisfy Telegram callback_data length limits
    # -------------------------------------------------------------------------

    def _report_key(self, report_name: str) -> str:
        """Stable short key for a report dir name (safe for callback_data)."""
        try:
            # 64-bit digest => 16 hex chars; collision risk is negligible for this use.
            return hashlib.blake2b(report_name.encode("utf-8"), digest_size=8).hexdigest()
        except Exception:
            return str(report_name).strip()[:16]

    def _resolve_report_name_by_key(self, report_key: str) -> Optional[str]:
        """Resolve a report key back to an on-disk report directory name."""
        try:
            reports_dir = Path(self.state_dir.parent / "reports")
            if not reports_dir.exists():
                reports_dir = Path.cwd() / "reports"
            if not reports_dir.exists():
                return None

            for d in reports_dir.iterdir():
                if not d.is_dir():
                    continue
                name = d.name
                if not name.startswith("backtest_"):
                    continue
                if self._report_key(name) == report_key:
                    return name
        except Exception:
            return None
        return None

    def _get_reports_dir_for_write(self) -> Path:
        """
        Return the reports directory where we should write new reports.

        Important UX detail:
        - If `data/reports` already exists, we use it.
        - Otherwise we write to `<cwd>/reports` to avoid changing precedence of `/reports`.
        """
        primary = Path(self.state_dir.parent / "reports")
        if primary.exists():
            return primary
        fallback = Path.cwd() / "reports"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    async def _handle_test_signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /test_signal command - generate a test signal with chart for testing."""
        logger.info(f"Received /test_signal command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            if not self.chart_generator:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "❌ Chart generation not available.\n\n"
                    "Install matplotlib: `pip install matplotlib`",
                    reply_markup=reply_markup
                )
                return

            symbol = "MNQ"

            # Prefer a real historical slice (cached) so the chart looks identical to production.
            # This avoids synthetic candle edge cases and avoids hammering IBKR.
            def _load_cached_history() -> tuple[Optional[pd.DataFrame], Optional[str], Optional[str]]:
                """Return (df, source_name, inferred_tf) where df has a DateTimeIndex + lowercase OHLCV."""
                try:
                    candidates = []
                    candidates.extend(self._historical_cache_dir.glob(f"{symbol}_1m_*.parquet"))
                    candidates.extend(self._historical_cache_dir.glob(f"{symbol}_5m_*.parquet"))
                    files = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
                except Exception:
                    files = []

                for f in files:
                    try:
                        tmp = pd.read_parquet(f)
                        if tmp is None or tmp.empty:
                            continue

                        inferred_tf = "1m" if "_1m_" in f.name else "5m" if "_5m_" in f.name else None

                        # Normalize timestamp/index
                        if "timestamp" in tmp.columns:
                            tmp["timestamp"] = pd.to_datetime(tmp["timestamp"], errors="coerce", utc=True)
                            tmp = tmp.dropna(subset=["timestamp"])
                            tmp = tmp.sort_values("timestamp")
                            tmp = tmp.drop_duplicates(subset=["timestamp"], keep="first")
                            tmp = tmp.set_index("timestamp")
                        elif isinstance(tmp.index, pd.DatetimeIndex):
                            if tmp.index.tz is None:
                                tmp.index = tmp.index.tz_localize(timezone.utc)
                            tmp = tmp.sort_index()
                        else:
                            continue

                        # Normalize column names to lowercase
                        col_map = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
                        for old, new in col_map.items():
                            if old in tmp.columns and new not in tmp.columns:
                                tmp = tmp.rename(columns={old: new})

                        if not all(c in tmp.columns for c in ("open", "high", "low", "close")):
                            continue

                        return tmp, f.name, inferred_tf
                    except Exception:
                        continue

                return None, None, None

            hist_df, hist_src, hist_tf = _load_cached_history()

            # Fallback: synthetic data (should be rare)
            def _create_synthetic_5m(num_bars: int = 160) -> pd.DataFrame:
                np.random.seed(42)
                base_price = 25000.0
                dates = pd.date_range(end=datetime.now(timezone.utc), periods=num_bars, freq="5min")
                price_changes = np.random.randn(num_bars) * 8
                prices = base_price + np.cumsum(price_changes)
                rows = []
                for date, price in zip(dates, prices):
                    candle_range = abs(np.random.randn() * 8) + 5
                    if np.random.random() > 0.5:
                        open_price = price - candle_range * 0.3
                        close_price = price + candle_range * 0.3
                    else:
                        open_price = price + candle_range * 0.3
                        close_price = price - candle_range * 0.3
                    high = max(open_price, close_price) + abs(np.random.randn() * 3) + 2
                    low = min(open_price, close_price) - abs(np.random.randn() * 3) - 2
                    rows.append(
                        {
                            "timestamp": date,
                            "open": open_price,
                            "high": high,
                            "low": low,
                            "close": close_price,
                            "volume": int(np.random.uniform(1000, 5000)),
                        }
                    )
                df = pd.DataFrame(rows)
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                return df.set_index("timestamp")

            # Convert to 5m bars for charting
            df_5m: pd.DataFrame
            src_label = hist_src or "synthetic"
            if hist_df is None or hist_df.empty:
                df_5m = _create_synthetic_5m(220)
                src_label = "synthetic"
            else:
                if hist_tf == "5m":
                    df_5m = hist_df.copy()
                else:
                    # Resample 1m → 5m
                    df_5m = (
                        hist_df.resample("5min")
                        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                        .dropna()
                    )

            # Choose a recent random window so it feels like a real trade snapshot
            window_bars = 160
            if len(df_5m) < window_bars + 10:
                df_5m = df_5m.tail(window_bars + 10)

            max_end = len(df_5m) - 1
            min_end = max(window_bars, max_end - 3000)  # ~last 10 days of 5m bars
            end_i = random.randint(min_end, max_end) if max_end > min_end else max_end
            window = df_5m.iloc[end_i - window_bars : end_i + 1].copy()

            # Simple ATR-based risk sizing for realistic SL/TP distances
            def _atr(d: pd.DataFrame, period: int = 14) -> float:
                try:
                    h = d["high"].astype(float)
                    l = d["low"].astype(float)
                    c = d["close"].astype(float)
                    pc = c.shift(1)
                    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
                    v = tr.rolling(period).mean().iloc[-1]
                    return float(v) if v is not None and np.isfinite(v) else 0.0
                except Exception:
                    return 0.0

            entry_price = float(window["close"].iloc[-1])
            atr_val = _atr(window)
            stop_dist = max(10.0, atr_val * 1.5 if atr_val > 0 else 15.0)
            direction = random.choice(["long", "short"])

            if direction == "long":
                stop_loss = entry_price - stop_dist
                take_profit = entry_price + (stop_dist * 1.5)
            else:
                stop_loss = entry_price + stop_dist
                take_profit = entry_price - (stop_dist * 1.5)

            sig_type = random.choice(["momentum_breakout", "trend_continuation", "mean_reversion"])
            confidence = float(round(random.uniform(0.58, 0.86), 2))

            test_signal: Dict[str, Any] = {
                "entry_price": round(entry_price, 2),
                "stop_loss": round(stop_loss, 2),
                "take_profit": round(take_profit, 2),
                "direction": direction,
                "type": sig_type,
                "symbol": symbol,
                "confidence": confidence,
                "reason": f"Test signal (replica) from {src_label}",
                # Used by chart HUD RR box
                "tick_value": 2.0,  # MNQ ~$2/point
                "position_size": 1,
                # CRITICAL: Mark as test so it's excluded from P&L and performance metrics
                "_is_test": True,
            }

            # Optional: enrich with HUD context (sessions/key levels/etc.)
            try:
                from pearlalgo.strategies.nq_intraday.hud_context import build_hud_context

                test_signal["hud_context"] = build_hud_context(window, symbol=symbol, tick_size=0.25)
            except Exception:
                pass

            # Generate entry chart (production generator)
            chart_path = self.chart_generator.generate_entry_chart(test_signal, window, symbol)
            
            if chart_path and chart_path.exists():
                # Calculate R:R ratio
                risk = abs(entry_price - stop_loss)
                reward = abs(take_profit - entry_price)
                rr_ratio = reward / risk if risk > 0 else 0
                
                # Send test signal message
                side = "LONG" if direction == "long" else "SHORT"
                type_label = sig_type.replace("_", " ").title()
                message = (
                    "🧪 *Test Signal Generated*\n\n"
                    f"*Type:* {type_label} ({side})\n"
                    f"*Entry:* ${entry_price:,.2f}\n"
                    f"*Stop:* ${stop_loss:,.2f}\n"
                    f"*TP:* ${take_profit:,.2f}\n"
                    f"*R:R:* {rr_ratio:.2f}:1\n\n"
                    "📊 Entry chart generated below!"
                )
                
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Generate Another", callback_data='test_signal'),
                    InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
                ]])
                
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                
                # Send chart
                try:
                    with open(chart_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo,
                            caption="📊 Test Signal Entry Chart",
                        )
                    
                    # Clean up
                    chart_path.unlink()
                    logger.info("Test signal chart sent successfully")

                    # Auto-send a simulated exit after 10 seconds (replica lifecycle)
                    chat_id = update.effective_chat.id
                    bot = context.bot

                    exit_win = random.random() < 0.55
                    exit_reason = "take_profit" if exit_win else "stop_loss"
                    exit_price = float(take_profit if exit_win else stop_loss)

                    # PnL in USD (approx, MNQ: $2/point)
                    pnl_points = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
                    pnl_usd = float(pnl_points) * float(test_signal.get("tick_value") or 2.0) * float(test_signal.get("position_size") or 1.0)

                    async def _send_test_exit():
                        await asyncio.sleep(10)
                        try:
                            result = "WIN" if exit_reason == "take_profit" else "LOSS"
                            exit_label = safe_label(exit_reason).title()
                            msg = (
                                f"🧪 *Test Exit ({result})*\n\n"
                                f"*Exit:* ${exit_price:,.2f} ({exit_label})\n"
                                f"*P&L:* ${pnl_usd:,.2f}\n\n"
                                "📉 Exit chart below!"
                            )
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

                            exit_chart = self.chart_generator.generate_exit_chart(
                                test_signal,
                                exit_price=exit_price,
                                exit_reason=exit_reason,
                                pnl=pnl_usd,
                                buffer_data=window,
                                symbol=symbol,
                                timeframe="5m",
                            )
                            if exit_chart and exit_chart.exists():
                                with open(exit_chart, "rb") as photo2:
                                    await bot.send_photo(
                                        chat_id=chat_id,
                                        photo=photo2,
                                        caption="📉 Test Signal Exit Chart",
                                    )
                                try:
                                    exit_chart.unlink()
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.error(f"Error sending test exit: {e}", exc_info=True)

                    asyncio.create_task(_send_test_exit())
                    
                except Exception as e:
                    logger.error(f"Error sending test chart: {e}", exc_info=True)
                    await self._send_message_or_edit(
                        update, context,
                        "📊 *Test Chart Delivery Failed*\n\n"
                        "Chart was generated but couldn't be sent.\n\n"
                        "💡 Try again"
                    )
            else:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📊 *Test Chart Unavailable*\n\n"
                    "Could not generate test chart.\n\n"
                    "💡 Check /data_quality for data issues",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error handling test_signal command: {e}", exc_info=True)
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(
                update, context,
                "📊 *Test Signal Failed*\n\n"
                "Something went wrong generating the test signal.\n\n"
                "💡 Try again or check /data_quality",
                reply_markup=reply_markup
            )
    
    async def _handle_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /performance command with optional lookback argument.
        
        Usage:
        - /performance        -> 7 days (default)
        - /performance 24h    -> 24 hours
        - /performance 7d     -> 7 days
        - /performance 30d    -> 30 days
        """
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Parse lookback argument from command text
        lookback_days = 7  # default
        lookback_label = "7-day"
        
        # Get the raw message text (could be from /performance or callback)
        raw_text = ""
        if update.message and update.message.text:
            raw_text = update.message.text.strip()
        elif update.callback_query and update.callback_query.data:
            # Check for callback data like "performance:7d"
            cb_data = update.callback_query.data
            if cb_data.startswith("performance:"):
                raw_text = f"/performance {cb_data.split(':', 1)[1]}"
        
        # Parse lookback from text
        if raw_text:
            parts = raw_text.split()
            if len(parts) > 1:
                lookback_arg = parts[1].lower().strip()
                if lookback_arg in ("24h", "1d"):
                    lookback_days = 1
                    lookback_label = "24-hour"
                elif lookback_arg in ("7d", "week"):
                    lookback_days = 7
                    lookback_label = "7-day"
                elif lookback_arg in ("30d", "month"):
                    lookback_days = 30
                    lookback_label = "30-day"
                elif lookback_arg in ("14d", "2w"):
                    lookback_days = 14
                    lookback_label = "14-day"
        
        try:
            performance = self.performance_tracker.get_performance_metrics(days=lookback_days)
            
            message = f"📈 *Performance ({lookback_label})*\n\n"
            
            total_signals = performance.get("total_signals", 0)
            exited_signals = performance.get("exited_signals", 0)
            wins = performance.get("wins", 0)
            losses = performance.get("losses", 0)
            win_rate = performance.get("win_rate", 0) * 100
            total_pnl = performance.get("total_pnl", 0)
            avg_pnl = performance.get("avg_pnl", 0)
            
            message += f"*Signals:* {total_signals} total, {exited_signals} exited\n"
            
            if exited_signals > 0:
                message += f"✅ {wins}W  ❌ {losses}L\n"
                message += f"📊 Win Rate: {win_rate:.1f}%\n"
                message += f"💰 Total P&L: ${total_pnl:,.2f}\n"
                message += f"📊 Avg P&L: ${avg_pnl:,.2f}\n"
                message += f"⏱️ Avg Hold: {performance.get('avg_hold_minutes', 0.0):.1f} min\n"
            else:
                message += "⏳ No completed trades yet\n"

            # Breakdown by signal type (top 6 by count)
            by_type = performance.get("by_signal_type", {}) or {}
            if by_type:
                message += "\n🧾 *By Signal Type*\n"
                items = []
                for sig_type, m in by_type.items():
                    items.append(
                        (
                            int(m.get("count", 0) or 0),
                            str(sig_type),
                            float(m.get("win_rate", 0.0) or 0.0),
                            float(m.get("total_pnl", 0.0) or 0.0),
                        )
                    )
                items.sort(key=lambda x: x[0], reverse=True)
                for count, sig_type, wr, pnl in items[:6]:
                    message += f"- `{sig_type}`: {count} • {wr*100:.0f}% • ${pnl:,.2f}\n"

            # Recent exits preview (show last 3)
            recent_exits = performance.get("recent_exits", []) or []
            if recent_exits:
                message += "\n📋 *Recent Exits*\n"
                for exit_info in recent_exits[:3]:
                    sig_type = exit_info.get("type", "?")[:12]
                    pnl = exit_info.get("pnl", 0)
                    is_win = exit_info.get("is_win", pnl > 0)
                    icon = "✅" if is_win else "❌"
                    message += f"{icon} `{sig_type}`: ${pnl:+.2f}\n"
                if len(recent_exits) > 3:
                    message += f"_...and {len(recent_exits) - 3} more_\n"

            # Prepare export artifacts (signals + metrics)
            export_paths: Dict[str, str] = {}
            try:
                exports_dir = self.state_dir / "exports"
                exports_dir.mkdir(parents=True, exist_ok=True)
                ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                base_name = f"performance_{lookback_days}d_{ts_tag}"

                # Metrics JSON
                metrics_path = exports_dir / f"{base_name}_metrics.json"
                with open(metrics_path, "w") as f:
                    json.dump(performance, f, indent=2)
                export_paths["metrics"] = str(metrics_path)

                # Export signals within lookback period (JSONL) + exited signals CSV
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    cutoff = datetime.now(timezone.utc).timestamp() - (lookback_days * 24 * 60 * 60)
                    kept = []
                    with open(signals_file, "r") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                rec = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            ts_str = rec.get("timestamp") or rec.get("signal", {}).get("timestamp") or ""
                            try:
                                ts = pd.to_datetime(ts_str).timestamp() if ts_str else None
                            except Exception:
                                ts = None
                            if ts is None or ts < cutoff:
                                continue
                            kept.append(rec)

                    if kept:
                        signals_jsonl = exports_dir / f"{base_name}_signals.jsonl"
                        with open(signals_jsonl, "w") as f:
                            for rec in kept:
                                f.write(json.dumps(rec) + "\n")
                        export_paths["signals_jsonl"] = str(signals_jsonl)

                        # Exited-only CSV (best-effort)
                        exited = [r for r in kept if r.get("status") == "exited"]
                        if exited:
                            rows = []
                            for r in exited:
                                s = r.get("signal", {}) or {}
                                rows.append(
                                    {
                                        "timestamp": r.get("timestamp"),
                                        "signal_id": r.get("signal_id"),
                                        "type": s.get("type"),
                                        "direction": s.get("direction"),
                                        "confidence": s.get("confidence"),
                                        "entry_price": s.get("entry_price"),
                                        "stop_loss": s.get("stop_loss"),
                                        "take_profit": s.get("take_profit"),
                                        "exit_price": r.get("exit_price"),
                                        "exit_reason": r.get("exit_reason"),
                                        "pnl": r.get("pnl"),
                                        "is_win": r.get("is_win"),
                                        "hold_minutes": r.get("hold_duration_minutes"),
                                    }
                                )
                            df_out = pd.DataFrame(rows)
                            csv_path = exports_dir / f"{base_name}_exited.csv"
                            df_out.to_csv(csv_path, index=False)
                            export_paths["exited_csv"] = str(csv_path)

                if hasattr(context, "user_data"):
                    context.user_data["performance_export_paths"] = export_paths
            except Exception as e:
                logger.warning(f"Could not create performance export artifacts: {e}")

            # Buttons (exports)
            keyboard = []
            export_row = []
            if export_paths.get("signals_jsonl"):
                export_row.append(
                    InlineKeyboardButton(
                        "📄 Signals JSONL",
                        callback_data="performance_export:signals",
                    )
                )
            if export_paths.get("exited_csv"):
                export_row.append(
                    InlineKeyboardButton(
                        "📄 Exited CSV",
                        callback_data="performance_export:exited",
                    )
                )
            if export_row:
                keyboard.append(export_row)

            keyboard.append(
                [
                    InlineKeyboardButton(
                        "📊 Metrics JSON",
                        callback_data="performance_export:metrics",
                    ),
                    InlineKeyboardButton("🔄 Refresh", callback_data="performance"),
                ]
            )
            
            # Lookback toggle buttons
            lookback_row = []
            for days, label in [(1, "24h"), (7, "7d"), (14, "14d"), (30, "30d")]:
                marker = "•" if lookback_days == days else ""
                lookback_row.append(
                    InlineKeyboardButton(
                        f"{marker}{label}",
                        callback_data=f"performance:{label}",
                    )
                )
            keyboard.append(lookback_row)
            
            keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="start")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling performance command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting performance*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check if performance tracker is working\n"
                f"• Verify signals have been exited\n"
                f"• Try `/status` to check agent state"
            )
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)

    async def _handle_signal_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /signal <id_prefix> command - show detailed view of a specific signal.
        
        Usage:
        - /signal sr_bounce_1767     -> Shows signal matching this prefix
        - /signal mean_rev           -> Partial match works
        """
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Parse signal ID prefix from command
        raw_text = ""
        if update.message and update.message.text:
            raw_text = update.message.text.strip()
        
        parts = raw_text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send_message_or_edit(
                update, context,
                "❌ *Usage:* `/signal <signal_id_prefix>`\n\n"
                "Example: `/signal sr_bounce_1767`\n\n"
                "Use `/signals` to see available signal IDs.",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        signal_prefix = parts[1].strip()
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            # Search for signal by prefix
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals file found*\n\nNo signals have been generated yet.",
                    reply_markup=self._get_back_to_menu_button(),
                )
                return
            
            matched_signal = None
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        sig_id = record.get("signal_id", "")
                        if sig_id.startswith(signal_prefix) or signal_prefix in sig_id:
                            matched_signal = record
                            # Don't break - keep last match (most recent)
                    except json.JSONDecodeError:
                        continue
            
            if not matched_signal:
                await self._send_message_or_edit(
                    update, context,
                    f"❌ No signal found matching `{signal_prefix}`\n\n"
                    "Use `/signals` to see available signal IDs.",
                    reply_markup=self._get_back_to_menu_button(),
                )
                return
            
            # Format detailed signal view
            sig = matched_signal.get("signal", {}) or {}
            sig_id = matched_signal.get("signal_id", "unknown")
            status = matched_signal.get("status", "unknown")
            timestamp = matched_signal.get("timestamp", "")
            
            # Basic info
            sig_type = sig.get("type", "unknown")
            direction = sig.get("direction", "unknown")
            confidence = sig.get("confidence", 0)
            
            # Prices
            entry_price = sig.get("entry_price", 0)
            stop_loss = sig.get("stop_loss", 0)
            take_profit = sig.get("take_profit", 0)
            
            # Regime/context
            regime = sig.get("regime", {}) or {}
            regime_type = regime.get("regime", "unknown")
            volatility = regime.get("volatility", "unknown")
            session = regime.get("session", "unknown")
            
            # Exit info (if exited)
            exit_price = matched_signal.get("exit_price")
            exit_reason = matched_signal.get("exit_reason")
            pnl = matched_signal.get("pnl")
            is_win = matched_signal.get("is_win")
            
            # Build message
            status_emoji = {"generated": "📋", "entered": "📈", "exited": "✅" if is_win else "❌", "expired": "⏰"}.get(status, "❓")
            dir_emoji = "🟢" if direction == "long" else "🔴"
            
            message = f"🔍 *Signal Detail*\n\n"
            message += f"*ID:* `{sig_id[:30]}...`\n"
            message += f"*Status:* {status_emoji} {status}\n"
            message += f"*Type:* `{sig_type}`\n"
            message += f"*Direction:* {dir_emoji} {direction}\n"
            message += f"*Confidence:* {confidence:.0%}\n"
            message += f"*Time:* {timestamp[:19] if timestamp else 'N/A'}\n\n"
            
            message += f"*Entry:* ${entry_price:,.2f}\n"
            message += f"*Stop Loss:* ${stop_loss:,.2f}\n"
            message += f"*Take Profit:* ${take_profit:,.2f}\n\n"
            
            message += f"*Regime:* {regime_type}\n"
            message += f"*Volatility:* {volatility}\n"
            message += f"*Session:* {session}\n"
            
            if status == "exited" and exit_price is not None:
                message += f"\n*Exit Price:* ${exit_price:,.2f}\n"
                message += f"*Exit Reason:* {exit_reason}\n"
                message += f"*P&L:* ${pnl:+,.2f}\n"
                message += f"*Result:* {'✅ Win' if is_win else '❌ Loss'}\n"
            
            # Reason
            reason = sig.get("reason", "")
            if reason:
                message += f"\n*Reason:* {reason[:100]}{'...' if len(reason) > 100 else ''}\n"
            
            # Buttons
            keyboard = [
                [
                    InlineKeyboardButton("📄 Export JSON", callback_data=f"signal_export:{sig_id[:40]}"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"signal_detail:{sig_id[:40]}"),
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling signal detail: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                f"❌ *Error getting signal detail*\n\n`{str(e)[:100]}`",
                reply_markup=self._get_back_to_menu_button(),
            )

    async def _handle_signal_export(self, update: Update, context: ContextTypes.DEFAULT_TYPE, sig_id_prefix: str):
        """Export a signal as a JSON file attachment."""
        if not await self._check_authorized(update):
            return
        
        try:
            # Find the signal
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="📭 No signals file found.",
                )
                return
            
            matched_signal = None
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        sig_id = record.get("signal_id", "")
                        if sig_id.startswith(sig_id_prefix) or sig_id_prefix in sig_id:
                            matched_signal = record
                    except json.JSONDecodeError:
                        continue
            
            if not matched_signal:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ No signal found matching `{sig_id_prefix}`",
                    parse_mode="Markdown",
                )
                return
            
            # Write to temp file and send
            sig_id = matched_signal.get("signal_id", "signal")
            export_path = self.state_dir / "exports" / f"{sig_id[:40]}.json"
            export_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(export_path, "w") as f:
                json.dump(matched_signal, f, indent=2)
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=open(export_path, "rb"),
                filename=f"{sig_id[:40]}.json",
                caption=f"📄 Signal export: `{sig_id[:30]}...`",
                parse_mode="Markdown",
            )
            
        except Exception as e:
            logger.error(f"Error exporting signal: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Export failed: {str(e)[:100]}",
            )

    async def _handle_grade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /grade command - record manual outcome feedback for learning.
        
        Usage:
        - /grade <signal_id_prefix> win|loss [pnl] [note...]
        
        Examples:
        - /grade sr_bounce_1767 win 150 Great entry
        - /grade mean_rev_456 loss -75 Stopped out on news
        - /grade momentum_short win
        - /grade sr_bounce_1767 win force  # Force apply even if already exited
        """
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Parse command arguments
        raw_text = ""
        if update.message and update.message.text:
            raw_text = update.message.text.strip()
        
        parts = raw_text.split()
        if len(parts) < 3:
            await self._send_message_or_edit(
                update, context,
                "❌ *Usage:* `/grade <signal_id> win|loss [pnl] [note...]`\n\n"
                "*Examples:*\n"
                "`/grade sr_bounce_1767 win 150 Great entry`\n"
                "`/grade mean_rev_456 loss -75 Stopped out`\n"
                "`/grade momentum_short win`\n\n"
                "Use `/signals` to see signal IDs.",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        signal_prefix = parts[1].strip()
        outcome = parts[2].lower().strip()
        
        if outcome not in ("win", "loss"):
            await self._send_message_or_edit(
                update, context,
                f"❌ Invalid outcome: `{outcome}`\n\nMust be `win` or `loss`.",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        is_win = outcome == "win"
        
        # Parse optional pnl and note
        pnl = None
        note = ""
        force = False
        remaining = parts[3:] if len(parts) > 3 else []
        
        for i, part in enumerate(remaining):
            if part.lower() == "force":
                force = True
            elif pnl is None:
                try:
                    pnl = float(part)
                except ValueError:
                    # Not a number, treat as start of note
                    note = " ".join(remaining[i:])
                    break
            else:
                note = " ".join(remaining[i:])
                break
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            # Find the signal
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals file found*",
                    reply_markup=self._get_back_to_menu_button(),
                )
                return
            
            matched_signal = None
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        sig_id = record.get("signal_id", "")
                        if sig_id.startswith(signal_prefix) or signal_prefix in sig_id:
                            matched_signal = record
                    except json.JSONDecodeError:
                        continue
            
            if not matched_signal:
                await self._send_message_or_edit(
                    update, context,
                    f"❌ No signal found matching `{signal_prefix}`",
                    reply_markup=self._get_back_to_menu_button(),
                )
                return
            
            sig_id = matched_signal.get("signal_id", "unknown")
            sig = matched_signal.get("signal", {}) or {}
            sig_type = sig.get("type", "unknown")
            status = matched_signal.get("status", "unknown")
            
            # Check if already exited
            already_exited = status == "exited"
            
            # Write feedback to feedback.jsonl
            feedback_file = self.state_dir / "feedback.jsonl"
            feedback_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "signal_id": sig_id,
                "signal_type": sig_type,
                "outcome": outcome,
                "is_win": is_win,
                "pnl": pnl,
                "note": note,
                "force": force,
                "already_exited": already_exited,
                "applied_to_learning": False,  # Will be updated by service
            }
            
            with open(feedback_file, "a") as f:
                f.write(json.dumps(feedback_record) + "\n")
            
            # Write grade request flag for service to pick up
            grade_request_file = self.state_dir / "grade_request.json"
            grade_request = {
                "signal_id": sig_id,
                "signal_type": sig_type,
                "is_win": is_win,
                "pnl": pnl,
                "force": force,
                "requested_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(grade_request_file, "w") as f:
                json.dump(grade_request, f)
            
            # Build response message
            outcome_emoji = "✅" if is_win else "❌"
            message = f"{outcome_emoji} *Feedback Recorded*\n\n"
            message += f"*Signal:* `{sig_id[:25]}...`\n"
            message += f"*Type:* `{sig_type}`\n"
            message += f"*Outcome:* {outcome}\n"
            if pnl is not None:
                message += f"*P&L:* ${pnl:+,.2f}\n"
            if note:
                message += f"*Note:* {note[:80]}\n"
            
            if already_exited and not force:
                message += "\n⚠️ *Note:* Signal already has virtual exit.\n"
                message += "Feedback logged but not double-counted for learning.\n"
                message += "_Use `/grade ... force` to override._"
            else:
                message += "\n✅ Will be applied to learning on next cycle."
            
            await self._send_message_or_edit(
                update, context,
                message,
                reply_markup=self._get_back_to_menu_button(),
            )
            
        except Exception as e:
            logger.error(f"Error handling grade command: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                f"❌ *Error recording feedback*\n\n`{str(e)[:100]}`",
                reply_markup=self._get_back_to_menu_button(),
            )

    async def _handle_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /config command (read-only view of key config)."""
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        from pathlib import Path
        import yaml

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            project_root = Path(__file__).parent.parent.parent.parent
            config_path = project_root / "config" / "config.yaml"
            if not config_path.exists():
                await update.message.reply_text(
                    "⚙️ *Config:* `config/config.yaml` not found.",
                    parse_mode="Markdown",
                )
                return

            data = yaml.safe_load(config_path.read_text()) or {}
            symbol = data.get("symbol", "MNQ")
            timeframe = data.get("timeframe", "1m")
            scan_interval = data.get("scan_interval", 30)
            risk = data.get("risk", {})

            max_risk_per_trade = risk.get("max_risk_per_trade", 0.01)
            max_drawdown = risk.get("max_drawdown", 0.10)
            min_pos = risk.get("min_position_size", 5)
            max_pos = risk.get("max_position_size", 15)

            message = "⚙️ *Agent Configuration (read-only)*\n\n"
            message += f"*Symbol:* {symbol}\n"
            message += f"*Timeframe:* {timeframe}\n"
            message += f"*Scan Interval:* {scan_interval}s\n\n"
            message += "*Risk (prop firm style):*\n"
            message += f"- Max risk/trade: {max_risk_per_trade:.2%}\n"
            message += f"- Max drawdown: {max_drawdown:.2%}\n"
            message += f"- Position size: {min_pos}-{max_pos} MNQ\n"

            reply_markup = self._get_back_to_menu_button(include_refresh=True)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error handling config command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting config*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check if config file exists: `config/config.yaml`\n"
                f"• Verify file permissions\n"
                f"• Ensure YAML format is valid"
            )
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)

    async def _handle_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /health command (lightweight health summary)."""
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            # Service process + state freshness
            project_root = Path(__file__).parent.parent.parent.parent
            state_file = get_state_file(self.state_dir)

            process_running = self._is_agent_process_running()
            state_exists = state_file.exists()

            last_updated = "unknown"
            if state_exists:
                mtime = state_file.stat().st_mtime
                dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
                last_updated = dt.isoformat(timespec="seconds")

            health_emoji = "🟢" if process_running and state_exists else "🟡" if state_exists else "🔴"
            message = f"{health_emoji} *{LABEL_AGENT} Health*\n\n"
            message += f"- {LABEL_AGENT}: {STATE_RUNNING if process_running else STATE_STOPPED}\n"
            message += f"- State file: {'present' if state_exists else 'missing'}\n"
            message += f"- State last updated (UTC): {last_updated}\n"

            reply_markup = self._get_back_to_menu_button(include_refresh=True)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error handling health command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error checking health*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check system permissions\n"
                f"• Verify process detection is working\n"
                f"• Try `/status` for basic status"
            )
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)

    async def _handle_health_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show a Health submenu with Gateway / Activity / Data / Performance."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        # Gateway badge (tri-state): ✅ running+API ready, 🟡 running but API not ready, ❌ stopped
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = bool(gateway_status.get("process_running", False))
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False

        gw_badge = "🔌 ❌"
        if gateway_running:
            if gateway_api_ready is True:
                gw_badge = "🔌 ✅"
            elif gateway_api_ready is False:
                gw_badge = "🔌 🟡"
            else:
                gw_badge = "🔌 ✅"

        message = """📡 *Health*

Choose what you want to inspect:
- *Gateway*: IBKR gateway status / API readiness
- *Activity*: is the bot scanning?
- *Data*: live vs historical, staleness, gaps
- *Performance*: last 7d WR / P&L
"""

        keyboard = [
            [
                InlineKeyboardButton(f"{gw_badge} Gateway", callback_data="gateway_status"),
                InlineKeyboardButton("🛡 Data", callback_data="data_quality"),
            ],
            [
                InlineKeyboardButton("📈 Activity", callback_data="activity"),
                InlineKeyboardButton("🔬 Diagnostics", callback_data="diagnostics"),
            ],
            [
                InlineKeyboardButton("📈 Performance", callback_data="performance"),
                InlineKeyboardButton("🩺 Doctor", callback_data="doctor"),
            ],
            [
                InlineKeyboardButton("🧠 Brain", callback_data="brain"),
                InlineKeyboardButton("🏠 Menu", callback_data="start"),
            ],
        ]
        await self._send_message_or_edit(
            update,
            context,
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _handle_activity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /activity command - answers "is the bot doing anything?"
        
        Shows:
        - Last cycle time and status
        - Current buffer status
        - Active positions (if any)
        - Next expected action
        """
        logger.info(f"Received /activity command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            state_file = get_state_file(self.state_dir)
            process_running = self._is_agent_process_running()
            
            if not state_file.exists():
                message = "📈 *Activity Status*\n\n"
                message += f"🔴 *{LABEL_AGENT}:* {STATE_STOPPED}\n\n"
                message += "ℹ️ No activity data available.\n"
                message += f"💡 Start the {LABEL_AGENT.lower()} to begin monitoring.\n"
                reply_markup = self._get_main_menu_buttons(agent_running=False)
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                return
            
            with open(state_file) as f:
                state = json.load(f)
            
            # Get activity pulse from last_successful_cycle (more accurate than state file mtime)
            from pearlalgo.utils.telegram_alerts import format_activity_pulse, format_next_session_time, format_session_window
            from pearlalgo.utils.paths import parse_utc_timestamp
            
            last_cycle_seconds = None
            try:
                last_cycle_ts = state.get("last_successful_cycle")
                if last_cycle_ts:
                    last_cycle_dt = parse_utc_timestamp(str(last_cycle_ts))
                    if last_cycle_dt:
                        if last_cycle_dt.tzinfo is None:
                            last_cycle_dt = last_cycle_dt.replace(tzinfo=timezone.utc)
                        last_cycle_seconds = (datetime.now(timezone.utc) - last_cycle_dt).total_seconds()
            except Exception:
                last_cycle_seconds = None
            
            # Fallback: if no last_successful_cycle, use nq_agent.log mtime as liveness proxy
            if last_cycle_seconds is None and process_running:
                try:
                    project_root = Path(__file__).parent.parent.parent.parent
                    log_file = project_root / "logs" / "nq_agent.log"
                    if log_file.exists():
                        log_mtime = log_file.stat().st_mtime
                        last_cycle_seconds = datetime.now(timezone.utc).timestamp() - log_mtime
                except Exception:
                    pass
            
            running = process_running and state.get("running", False)
            paused = state.get("paused", False)
            
            # Compute data freshness using robust helper
            data_age_minutes = self._extract_data_age_minutes(state)
            data_stale_threshold = float(state.get("data_stale_threshold_minutes", 10.0))
            is_data_stale = data_age_minutes is not None and data_age_minutes > data_stale_threshold
            
            # Build activity message
            message = "📈 *Activity Status*\n\n"
            
            # Service status (using standardized terminology)
            if not running:
                message += f"🔴 *{LABEL_AGENT}:* {STATE_STOPPED}\n"
            elif paused:
                message += f"⏸️ *{LABEL_AGENT}:* {STATE_PAUSED}\n"
                pause_reason = state.get("pause_reason")
                if pause_reason:
                    message += f"   Reason: {safe_label(str(pause_reason))}\n"
            else:
                message += f"🟢 *{LABEL_AGENT}:* {STATE_RUNNING}\n"
            
            # Activity pulse (using last_successful_cycle for accuracy)
            if last_cycle_seconds is not None:
                pulse_emoji, pulse_text = format_activity_pulse(last_cycle_seconds, is_paused=paused)
                message += f"\n{pulse_emoji} *Last Scan:* {pulse_text}\n"
            
            # Scan information (standardized: "scans" not "cycles")
            scans_total = int(state.get("cycle_count", 0) or 0)
            scans_session = state.get("cycle_count_session")
            if scans_session is not None:
                message += f"🔄 *Scans:* {scans_session:,} (session) / {scans_total:,} (total)\n"
            else:
                message += f"🔄 *Scans:* {scans_total:,}\n"
            
            # Buffer status
            buffer_size = int(state.get("buffer_size", 0) or 0)
            buffer_target = state.get("buffer_size_target")
            if buffer_target:
                buffer_pct = (buffer_size / int(buffer_target)) * 100 if int(buffer_target) > 0 else 0
                message += f"📊 *Buffer:* {buffer_size}/{buffer_target} {LABEL_BUFFER} ({buffer_pct:.0f}%)\n"
            else:
                message += f"📊 *Buffer:* {buffer_size} {LABEL_BUFFER}\n"
            
            # Latest bar info + data freshness
            latest_price = self._extract_latest_price(state)
            if latest_price is not None:
                message += f"💰 *Latest Price:* ${latest_price:,.2f}\n"
            
            # Data freshness cue (concise + actionable when stale)
            if data_age_minutes is not None:
                if is_data_stale:
                    age_str = f"{data_age_minutes:.0f}m" if data_age_minutes < 60 else f"{data_age_minutes / 60:.1f}h"
                    message += f"⏰ *Data:* stale ({age_str}) • /data_quality\n"
                else:
                    message += f"🟢 *Data:* fresh ({data_age_minutes:.0f}m old)\n"
            
            # Active trades count (standardized terminology)
            try:
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    active_count = 0
                    with open(signals_file) as f:
                        for line in f:
                            try:
                                sig = json.loads(line.strip())
                                if sig.get("status") == "entered":
                                    active_count += 1
                            except Exception:
                                continue
                    if active_count > 0:
                        message += f"\n🎯 *{LABEL_ACTIVE_TRADES}:* {active_count}\n"
            except Exception:
                pass
            
            # Next expected action (consistent with pulse status)
            message += "\n*What's Next:*\n"
            futures_open = state.get("futures_market_open")
            session_open = state.get("strategy_session_open")
            
            if not running:
                message += f"💡 Start {LABEL_AGENT.lower()} to begin monitoring\n"
            elif paused:
                message += f"💡 Resume {LABEL_AGENT.lower()} or address pause reason\n"
            elif is_data_stale:
                # Data stale - prioritize this issue
                message += "⏰ Data stale—signals paused • /data_quality\n"
            elif last_cycle_seconds is not None and last_cycle_seconds > 300:
                # Stale pulse - highlight potential issue
                message += "⚠️ Scans appear stalled—check /health or logs\n"
            elif session_open is False:
                # Get session times from config for config-driven messaging
                config_block = state.get("config", {})
                session_start = config_block.get("start_time") if isinstance(config_block, dict) else None
                session_end = config_block.get("end_time") if isinstance(config_block, dict) else None
                next_session = format_next_session_time(session_start, session_end)
                if session_start and session_end:
                    session_window = format_session_window(session_start, session_end)
                    message += f"⏳ Waiting for session ({session_window}) • {next_session}\n"
                else:
                    message += f"⏳ Waiting for session • {next_session}\n"
            elif futures_open is False:
                message += "⏳ Waiting for market to open\n"
            else:
                # Get scan_interval from nested config block
                config_block = state.get("config", {})
                scan_interval = config_block.get("scan_interval", 60) if isinstance(config_block, dict) else 60
                message += f"🔄 Next scan in ~{scan_interval}s\n"
            
            # Buttons
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="activity"),
                    InlineKeyboardButton("📊 Active Trades", callback_data="active_trades"),
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling activity command: {e}", exc_info=True)
            error_msg = f"❌ *Error:* {str(e)}"
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)

    async def _handle_data_quality(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        diagnose: bool = False,
    ):
        """Handle /data_quality command (data freshness + buffer + gateway triage)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # Load state file (written by agent service)
        state_file = get_state_file(self.state_dir)
        state: Dict = {}
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
            except Exception:
                state = {}

        agent_running = self._is_agent_process_running()
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False)

        # Compute state file freshness (operator signal)
        state_last_updated_utc = None
        state_age_seconds = None
        if state_file.exists():
            try:
                mtime = state_file.stat().st_mtime
                state_last_updated_utc = datetime.fromtimestamp(mtime, tz=timezone.utc)
                state_age_seconds = (datetime.now(timezone.utc) - state_last_updated_utc).total_seconds()
            except Exception:
                state_last_updated_utc = None
                state_age_seconds = None

        # Market/session status is relevant for stale-data interpretation and signal expectations.
        # Prefer persisted state values when available (so the UI reflects what the agent believed),
        # but fall back to live evaluation if missing.
        futures_market_open = state.get("futures_market_open")
        strategy_session_open = state.get("strategy_session_open")
        if futures_market_open is None:
            try:
                from pearlalgo.utils.market_hours import get_market_hours

                futures_market_open = bool(get_market_hours().is_market_open())
            except Exception:
                futures_market_open = None

        # Data freshness metadata (populated by service._save_state)
        data_fresh = state.get("data_fresh")
        latest_bar_timestamp = state.get("latest_bar_timestamp")
        latest_bar_age_minutes = state.get("latest_bar_age_minutes")
        latest_bar = state.get("latest_bar") if isinstance(state, dict) else None
        if not isinstance(latest_bar, dict):
            latest_bar = {}
        data_level = str(latest_bar.get("_data_level") or latest_bar.get("_data_source") or "").strip().lower()
        has_bid_ask = bool(latest_bar.get("bid") is not None or latest_bar.get("ask") is not None)

        # Backward-compatible: if age isn't persisted but timestamp is, compute age.
        if latest_bar_age_minutes is None and latest_bar_timestamp:
            try:
                ts = datetime.fromisoformat(str(latest_bar_timestamp).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                latest_bar_age_minutes = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
            except Exception:
                latest_bar_age_minutes = None

        buffer_size = int(state.get("buffer_size", 0) or 0)
        buffer_target = state.get("buffer_size_target")
        try:
            buffer_target = int(buffer_target) if buffer_target is not None else None
        except Exception:
            buffer_target = None

        # Identify issues (keep short; top 3 shown)
        issues: list[str] = []
        if not agent_running:
            issues.append(f"{LABEL_AGENT} process not running")
        if not gateway_running:
            issues.append(f"IBKR {LABEL_GATEWAY} not running")
        elif not gateway_api_ready:
            issues.append(f"{LABEL_GATEWAY} running but API not ready (port 4002 not listening)")

        # State file should update frequently when agent is healthy
        if state_age_seconds is not None and state_age_seconds > 60:
            issues.append(f"State file update lag ({int(state_age_seconds)}s)")

        if data_fresh is False:
            issues.append("Market data appears stale while market is open")
        if buffer_size < 10:
            issues.append(f"Buffer low ({buffer_size} bars; min 10)")

        # Heuristics: likely causes (prioritized)
        likely_causes: list[str] = []
        if not agent_running:
            likely_causes.append("Agent stopped/crashed (restart agent)")
        if not gateway_running:
            likely_causes.append("Gateway down (start/restart gateway)")
        if gateway_running and not gateway_api_ready:
            likely_causes.append("Gateway still authenticating / 2FA / API not ready")
        if data_fresh is False and (futures_market_open is True or futures_market_open is None):
            likely_causes.append("IBKR market data entitlement / delayed feed / connectivity issue")
        if buffer_size < 10:
            likely_causes.append("Historical fetch failing (HMDS pacing/outage) or connection issue")

        # Render message using standardized terminology
        title = "🛡 *Data Quality*" + (" (diagnose)" if diagnose else "")
        message = f"{title}\n\n"

        message += f"🤖 *{LABEL_AGENT}:* {'🟢 ' + STATE_RUNNING if agent_running else '🔴 ' + STATE_STOPPED}\n"
        message += (
            f"🔌 *{LABEL_GATEWAY}:* {'🟢 ' + STATE_RUNNING if gateway_running else '🔴 ' + STATE_STOPPED}"
            + (f" • API {'🟢 READY' if gateway_api_ready else '🔴 NOT READY'}" if gateway_running else "")
            + "\n"
        )
        
        # Buffer with target/percent
        if buffer_target is not None and buffer_target > 0:
            buffer_pct = (buffer_size / buffer_target) * 100
            message += f"📊 *Buffer:* {buffer_size}/{buffer_target} {LABEL_BUFFER} ({buffer_pct:.0f}%)\n"
        else:
            message += f"📊 *Buffer:* {buffer_size} {LABEL_BUFFER}\n"

        if latest_bar_age_minutes is not None:
            freshness_emoji = "🟢" if data_fresh is True else "🔴" if data_fresh is False else "⚪"
            message += f"{freshness_emoji} *Latest Bar Age:* {float(latest_bar_age_minutes):.1f} min\n"
        else:
            message += "⚪ *Latest Bar Age:* unknown\n"

        # Feed type (clarify bars vs quotes without calling it an error)
        if data_level:
            if data_level == "level1":
                message += "📡 *Feed:* live quotes (L1)\n"
            elif data_level == "historical":
                # Bars can still be fresh; avoid the word "fallback" here.
                message += "📡 *Feed:* 1m bars (updating)\n"
                if not has_bid_ask:
                    message += "   • bid/ask: unavailable (OK for signal scanning)\n"
            else:
                message += f"📡 *Feed:* {data_level}\n"

        # Use standardized gate terminology
        message += format_gate_status(futures_market_open, strategy_session_open) + "\n"

        if state_last_updated_utc:
            message += f"\n🗂️ *State Updated:* {state_last_updated_utc.isoformat(timespec='seconds')}\n"

        # Impact section: explain what issues mean for trading
        if issues:
            message += "\n⚠️ *Issues:*\n"
            for i, issue in enumerate(issues[:3], start=1):
                message += f"{i}. {issue}\n"
            
            # Add short impact summary
            message += "\n📉 *Impact:*\n"
            if not agent_running or not gateway_running:
                message += "• Signal generation halted\n"
            elif data_fresh is False:
                message += "• Signals paused until data refreshes\n"
            elif buffer_size < 10:
                message += "• Insufficient data for reliable signals\n"
            else:
                message += "• May affect signal accuracy\n"

        if likely_causes:
            message += "\n💡 *Likely causes:*\n"
            for i, cause in enumerate(likely_causes[:2], start=1):
                message += f"• {cause}\n"

        if diagnose:
            try:
                from pearlalgo.config.config_loader import load_service_config

                cfg = load_service_config()
                data_cfg = cfg.get("data", {})
                svc_cfg = cfg.get("service", {})
                stale_thr = data_cfg.get("stale_data_threshold_minutes", 10)
                alert_int = svc_cfg.get("data_quality_alert_interval", 300)
                buf_target = data_cfg.get("buffer_size", 100)
                message += "\n🔎 *Diagnostics:*\n"
                message += f"- stale_threshold_minutes: {stale_thr}\n"
                message += f"- data_quality_alert_interval_sec: {alert_int}\n"
                message += f"- configured_buffer_size: {buf_target}\n"
            except Exception:
                pass

        # Buttons
        keyboard = [
            [
                InlineKeyboardButton("🔎 Diagnose", callback_data="data_quality:diagnose"),
                InlineKeyboardButton("🔄 Refresh", callback_data="data_quality"),
            ],
            [
                InlineKeyboardButton("🔁 Restart Agent", callback_data="confirm:restart_agent"),
                InlineKeyboardButton("🔁 Restart Gateway", callback_data="confirm:restart_gateway"),
            ],
            [
                InlineKeyboardButton("🔌 Gateway Status", callback_data="gateway_status"),
                InlineKeyboardButton("🏠 Menu", callback_data="start"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
    
    async def _handle_start_gateway(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_gateway command."""
        logger.info(f"Received /start_gateway command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(
            update,
            context,
            "🔄 Starting *IBKR Gateway*...\n\nThis may take up to 60–120 seconds.",
            reply_markup=None,
        )

        result = await self.service_controller.start_gateway()

        message = f"{result['message']}\n"
        if result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(result['details'])
            message += f"\n{escaped_details}"

        gateway_status = self.service_controller.get_gateway_status()
        reply_markup = self._get_gateway_buttons(gateway_running=gateway_status.get("process_running", False))
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_stop_gateway(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_gateway command."""
        logger.info(f"Received /stop_gateway command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(update, context, "🔄 Stopping *IBKR Gateway*...", reply_markup=None)

        result = await self.service_controller.stop_gateway()

        message = f"{result['message']}\n"
        if result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(result['details'])
            message += f"\n{escaped_details}"
        
        # Get updated gateway status
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)

        reply_markup = self._get_gateway_buttons(gateway_running=gateway_running)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_gateway_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /gateway_status command."""
        logger.info(f"Received /gateway_status command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        status = self.service_controller.get_gateway_status()

        message = "🔌 *IBKR Gateway Status*\n\n"
        message += f"*Process:* {'🟢 RUNNING' if status['process_running'] else '🔴 STOPPED'}\n"
        message += f"*API Port:* {'🟢 LISTENING' if status['port_listening'] else '🔴 NOT LISTENING'}\n"
        message += f"\n*Status:* {status['message']}"
        
        if not status['process_running']:
            message += "\n\n💡 *Tip:* Start Gateway before starting the Agent."

        reply_markup = self._get_gateway_buttons(gateway_running=status['process_running'])
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_start_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_agent command."""
        logger.info(f"Received /start_agent command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(update, context, "🔄 Starting *NQ Agent Service*...", reply_markup=None)

        result = await self.service_controller.start_agent(background=True)

        message = f"{result['message']}\n"
        if result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(result['details'])
            message += f"\n{escaped_details}"

        # Optional: ensure Claude Monitor is running (daily reports + proactive suggestions)
        if result.get("success"):
            try:
                monitor_result = await self.service_controller.start_claude_monitor(background=True)
                message += f"\n\n{monitor_result.get('message', '').strip()}"
                if monitor_result.get("details"):
                    message += f"\n{escape_subprocess_output(monitor_result['details'])}"
            except Exception as e:
                message += f"\n\n⚠️ Claude Monitor start failed: {str(e)[:120]}"

        # Add gateway status warning if needed
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        if not gateway_running:
            message += "\n\n⚠️ *Warning:* IBKR Gateway is not running. Agent may not receive data."

        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_stop_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_agent command."""
        logger.info(f"Received /stop_agent command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(update, context, "🔄 Stopping *NQ Agent Service*...", reply_markup=None)

        result = await self.service_controller.stop_agent()

        message = f"{result['message']}\n"
        if result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(result['details'])
            message += f"\n{escaped_details}"

        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=False,
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_restart_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /restart_agent command."""
        logger.info(f"Received /restart_agent command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(update, context, "🔄 Restarting *NQ Agent Service*...", reply_markup=None)

        # Stop first
        stop_result = await self.service_controller.stop_agent()
        if not stop_result["success"] and "not running" not in stop_result["message"].lower():
            reply_markup = self._get_main_menu_buttons(agent_running=True)
            await self._send_message_or_edit(
                update, context,
                f"⚠️ Stop failed: {escape_subprocess_output(stop_result['message'])}\nAborting restart.",
                reply_markup=reply_markup
            )
            return

        # Wait a moment
        await asyncio.sleep(2)

        # Start
        start_result = await self.service_controller.start_agent(background=True)

        message = "🔄 *Restart Complete*\n\n"
        message += f"*Stop:* {escape_subprocess_output(stop_result['message'])}\n"
        message += f"*Start:* {escape_subprocess_output(start_result['message'])}"

        if start_result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(start_result['details'])
            message += f"\n\n{escaped_details}"

        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=True,
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    # -------------------------------------------------------------------------
    # AI/LLM Commands (optional, requires [llm] extra)
    # -------------------------------------------------------------------------
    
    # Paths that are blocked from /ai_patch for security
    _AI_PATCH_BLOCKED_PATHS = {
        "data/",
        "logs/",
        ".env",
        "ibkr/",
        ".venv/",
        ".git/",
        "__pycache__/",
        "*.pyc",
        "*.pyo",
        "*.parquet",
        "*.json",  # block state/config JSON by default
    }
    
    # File size limit for reading (prevent massive files in prompt)
    _AI_PATCH_MAX_FILE_SIZE = 100_000  # 100KB
    
    def _is_path_blocked(self, file_path: str) -> bool:
        """Check if a path is blocked from AI patch operations."""
        normalized = file_path.replace("\\", "/").lower()
        
        for blocked in self._AI_PATCH_BLOCKED_PATHS:
            if blocked.startswith("*"):
                # Wildcard suffix match
                if normalized.endswith(blocked[1:]):
                    return True
            elif blocked.endswith("/"):
                # Directory prefix match
                if normalized.startswith(blocked) or f"/{blocked}" in normalized:
                    return True
            else:
                # Exact match or filename match
                if normalized == blocked or normalized.endswith(f"/{blocked}"):
                    return True
        
        return False
    
    async def _handle_ai_patch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /ai_patch command - generate a unified diff patch using Claude.
        
        Usage: /ai_patch <file1>[,file2,...] <task description>
        
        Example: /ai_patch src/pearlalgo/utils/retry.py add exponential backoff with jitter
        """
        logger.info(f"Received /ai_patch command from chat {update.effective_chat.id}")
        
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Check if anthropic is available
        if not ANTHROPIC_AVAILABLE:
            await self._send_message_or_edit(
                update, context,
                "❌ *AI Patch Not Available*\n\n"
                "The `anthropic` package is not installed.\n"
                "Install with: `pip install -e .[llm]`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        # Parse arguments: first token is file(s), rest is the task
        args = context.args if context.args else []
        
        if len(args) < 2:
            await self._send_message_or_edit(
                update, context,
                "📝 *AI Patch - Usage*\n\n"
                "`/ai_patch <file(s)> <task>`\n\n"
                "*Examples:*\n"
                "• `/ai_patch src/pearlalgo/utils/retry.py add jitter to backoff`\n"
                "• `/ai_patch src/foo.py,src/bar.py refactor X into Y`\n\n"
                "*Notes:*\n"
                "• First argument is file path(s), comma-separated for multiple\n"
                "• Remaining arguments are the task description\n"
                "• Blocked paths: `data/`, `logs/`, `.env`, `ibkr/`, `.venv/`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        # Parse file paths (comma-separated first argument)
        file_arg = args[0]
        file_paths = [p.strip() for p in file_arg.split(",") if p.strip()]
        task = " ".join(args[1:])
        
        if not file_paths:
            await self._send_message_or_edit(
                update, context,
                "❌ No file paths provided.\n\nUsage: `/ai_patch <file(s)> <task>`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        if not task:
            await self._send_message_or_edit(
                update, context,
                "❌ No task provided.\n\nUsage: `/ai_patch <file(s)> <task>`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        # Check for blocked paths
        blocked_files = [f for f in file_paths if self._is_path_blocked(f)]
        if blocked_files:
            await self._send_message_or_edit(
                update, context,
                f"❌ *Blocked Path(s)*\n\n"
                f"The following paths are not allowed:\n"
                f"`{', '.join(blocked_files)}`\n\n"
                f"Blocked: `data/`, `logs/`, `.env`, `ibkr/`, `.venv/`, `.git/`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        # Show typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Send "working" message
        await self._send_message_or_edit(
            update, context,
            f"🤖 *Generating patch...*\n\n"
            f"*Files:* `{', '.join(file_paths)}`\n"
            f"*Task:* {task[:100]}{'...' if len(task) > 100 else ''}\n\n"
            f"This may take 30-60 seconds.",
            reply_markup=None,
        )
        
        # Get project root
        project_root = Path(__file__).parent.parent.parent.parent
        
        # Read file contents
        files_content: Dict[str, str] = {}
        missing_files: List[str] = []
        too_large_files: List[str] = []
        
        for file_path in file_paths:
            full_path = project_root / file_path
            
            # Security: ensure path is within project
            try:
                resolved = full_path.resolve()
                if not str(resolved).startswith(str(project_root.resolve())):
                    logger.warning(f"Path traversal attempt blocked: {file_path}")
                    missing_files.append(f"{file_path} (outside project)")
                    continue
            except Exception:
                missing_files.append(file_path)
                continue
            
            if not full_path.exists():
                missing_files.append(file_path)
                continue
            
            if not full_path.is_file():
                missing_files.append(f"{file_path} (not a file)")
                continue
            
            # Check file size
            try:
                file_size = full_path.stat().st_size
                if file_size > self._AI_PATCH_MAX_FILE_SIZE:
                    too_large_files.append(f"{file_path} ({file_size // 1024}KB)")
                    continue
            except Exception:
                missing_files.append(f"{file_path} (unreadable)")
                continue
            
            # Read file content
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                files_content[file_path] = content
            except Exception as e:
                logger.warning(f"Could not read {file_path}: {e}")
                missing_files.append(f"{file_path} (read error)")
        
        # Report errors
        if missing_files or too_large_files:
            error_parts = []
            if missing_files:
                error_parts.append(f"*Missing/invalid:* `{', '.join(missing_files)}`")
            if too_large_files:
                error_parts.append(f"*Too large (>100KB):* `{', '.join(too_large_files)}`")
            
            if not files_content:
                await self._send_message_or_edit(
                    update, context,
                    f"❌ *No valid files to process*\n\n" + "\n".join(error_parts),
                    reply_markup=self._get_back_to_menu_button(),
                )
                return
            else:
                # Some files valid, some not - warn but continue
                logger.warning(f"Some files could not be read: {missing_files + too_large_files}")
        
        # Try to create Claude client and generate patch
        try:
            client = ClaudeClient()
            diff_output = client.generate_patch(files=files_content, task=task)
            
        except ClaudeAPIKeyMissingError:
            await self._send_message_or_edit(
                update, context,
                "❌ *API Key Not Configured*\n\n"
                "`ANTHROPIC_API_KEY` not set in `.env`.\n\n"
                "Get your API key from https://console.anthropic.com/",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        except ClaudeAPIError as e:
            await self._send_message_or_edit(
                update, context,
                f"❌ *Claude API Error*\n\n`{str(e)[:200]}`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        except ClaudeClientError as e:
            await self._send_message_or_edit(
                update, context,
                f"❌ *Claude Error*\n\n`{str(e)[:200]}`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        except Exception as e:
            logger.error(f"Unexpected error in ai_patch: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                f"❌ *Unexpected Error*\n\n`{str(e)[:200]}`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        # Check if we got a valid diff
        if not diff_output or not diff_output.strip():
            await self._send_message_or_edit(
                update, context,
                "⚠️ *Empty Response*\n\n"
                "Claude returned an empty response. The task may be unclear or the files may already satisfy the requirement.",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        # Decide delivery method based on size
        # Telegram message limit is ~4096 chars, but we want some margin
        INLINE_LIMIT = 3500
        
        if len(diff_output) <= INLINE_LIMIT:
            # Send inline (use code block for formatting)
            # Escape any backticks in the diff to prevent markdown issues
            safe_diff = diff_output.replace("`", "'")
            message = (
                f"✅ *Patch Generated*\n\n"
                f"*Files:* `{', '.join(file_paths)}`\n"
                f"*Task:* {task[:80]}{'...' if len(task) > 80 else ''}\n\n"
                f"```diff\n{safe_diff}\n```\n\n"
                f"💡 Apply with: `git apply patch.diff`"
            )
            await self._send_message_or_edit(
                update, context,
                message,
                reply_markup=self._get_back_to_menu_button(),
            )
        else:
            # Send as document
            import io
            diff_bytes = diff_output.encode("utf-8")
            diff_file = io.BytesIO(diff_bytes)
            diff_file.name = "patch.diff"
            
            # Send the file
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action="upload_document"
            )
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=diff_file,
                filename="patch.diff",
                caption=(
                    f"✅ *Patch Generated*\n\n"
                    f"*Files:* `{', '.join(file_paths)}`\n"
                    f"*Task:* {task[:80]}{'...' if len(task) > 80 else ''}\n\n"
                    f"💡 Apply with: `git apply patch.diff`"
                ),
                parse_mode="Markdown",
            )
            
            # Send follow-up message with buttons
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="📄 Patch file sent above.",
                reply_markup=self._get_back_to_menu_button(),
            )

    # -------------------------------------------------------------------------
    # Claude Hub (mobile Cursor-like AI assistant)
    # -------------------------------------------------------------------------
    
    def _get_claude_hub_buttons(self, chat_mode_enabled: bool = False, show_monitor: bool = False) -> InlineKeyboardMarkup:
        """Generate Claude hub inline keyboard buttons."""
        chat_toggle_text = "💬 Chat: ON ✓" if chat_mode_enabled else "💬 Chat: OFF"
        
        if show_monitor:
            # Claude Monitor view
            try:
                monitor_running = bool(self.service_controller.get_claude_monitor_status().get("running"))
            except Exception:
                monitor_running = False

            monitor_btn_text = "⏹️ Stop Monitor" if monitor_running else "▶️ Start Monitor"
            monitor_btn_action = "claude_monitor_stop" if monitor_running else "claude_monitor_start"
            keyboard = [
                [
                    InlineKeyboardButton(monitor_btn_text, callback_data=monitor_btn_action),
                    InlineKeyboardButton("🔄 Refresh", callback_data="claude_monitor_hub"),
                ],
                [InlineKeyboardButton("📊 Analyze Now", callback_data='claude_analyze_now')],
                [
                    InlineKeyboardButton("📈 Signals", callback_data='claude_analyze_signals'),
                    InlineKeyboardButton("🔧 System", callback_data='claude_analyze_system'),
                ],
                [
                    InlineKeyboardButton("📉 Market", callback_data='claude_analyze_market'),
                    InlineKeyboardButton("💡 Suggest", callback_data='claude_suggest_config'),
                ],
                [InlineKeyboardButton("📋 Suggestions", callback_data='claude_suggestions')],
                [InlineKeyboardButton("⬅️ Back to Hub", callback_data='claude_hub')],
            ]
        else:
            # Main Claude hub view
            keyboard = [
                [InlineKeyboardButton(chat_toggle_text, callback_data='claude_chat_toggle')],
                [InlineKeyboardButton("🧩 Patch Wizard", callback_data='claude_patch_wizard')],
                [InlineKeyboardButton("🧠 Memory", callback_data='claude_memory')],
                [InlineKeyboardButton("🔍 AI Monitor", callback_data='claude_monitor_hub')],
                [InlineKeyboardButton("🧼 Reset Chat", callback_data='claude_reset')],
                [InlineKeyboardButton("🏠 Menu", callback_data='start')],
            ]
        return InlineKeyboardMarkup(keyboard)
    
    def _get_claude_wizard_files_buttons(
        self,
        suggested_files: list[str],
        selected_files: set[str],
    ) -> InlineKeyboardMarkup:
        """Generate file selection buttons for patch wizard."""
        keyboard = []
        
        # File toggle buttons (max 6 visible at once)
        for filepath in suggested_files[:6]:
            # Shorten path for display
            display_path = filepath
            if len(display_path) > 35:
                display_path = "..." + filepath[-32:]
            
            is_selected = filepath in selected_files
            prefix = "✓ " if is_selected else "○ "
            keyboard.append([
                InlineKeyboardButton(
                    f"{prefix}{display_path}",
                    callback_data=f'claude_file_toggle:{filepath}'
                ),
                InlineKeyboardButton("👁", callback_data=f'claude_file_preview:{filepath}'),
            ])
        
        # Action buttons
        action_row = []
        if selected_files:
            action_row.append(InlineKeyboardButton("✅ Generate Patch", callback_data='claude_generate_patch'))
        action_row.append(InlineKeyboardButton("🔍 Refine", callback_data='claude_refine_search'))
        keyboard.append(action_row)
        
        # Cancel button
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='claude_cancel')])
        
        return InlineKeyboardMarkup(keyboard)
    
    def _discover_project_files(self) -> list[str]:
        """
        Discover all editable files in the project (for search/suggestion).
        
        Returns paths relative to project root.
        Excludes blocked directories and file types.
        """
        project_root = Path(__file__).parent.parent.parent.parent
        
        allowed_roots = ["src", "tests", "scripts", "docs", "config"]
        blocked_dirs = {".git", ".venv", "__pycache__", "node_modules", "ibkr", "data", "logs", "telemetry"}
        blocked_suffixes = {".pyc", ".pyo", ".parquet", ".pkl", ".db", ".sqlite"}
        
        files = []
        
        for root_dir in allowed_roots:
            root_path = project_root / root_dir
            if not root_path.exists():
                continue
            
            for filepath in root_path.rglob("*"):
                if not filepath.is_file():
                    continue
                
                # Check for blocked directories in path
                path_parts = set(filepath.relative_to(project_root).parts)
                if path_parts & blocked_dirs:
                    continue
                
                # Check for blocked suffixes
                if filepath.suffix.lower() in blocked_suffixes:
                    continue
                
                # Check file size (skip very large files)
                try:
                    if filepath.stat().st_size > 100 * 1024:  # 100KB
                        continue
                except Exception:
                    continue
                
                rel_path = str(filepath.relative_to(project_root))
                files.append(rel_path)
        
        return sorted(files)
    
    def _search_files(self, query: str, all_files: list[str], limit: int = 8) -> list[str]:
        """
        Search files by query (filename and path matching).
        
        Returns most relevant files first.
        """
        if not query:
            return all_files[:limit]
        
        query_lower = query.lower()
        query_words = query_lower.split()
        
        scored_files = []
        for filepath in all_files:
            path_lower = filepath.lower()
            filename_lower = Path(filepath).name.lower()
            
            # Score based on matches
            score = 0
            
            # Exact filename match (highest)
            if filename_lower == query_lower:
                score += 100
            
            # Filename contains query
            if query_lower in filename_lower:
                score += 50
            
            # Path contains query
            if query_lower in path_lower:
                score += 20
            
            # Word matches
            for word in query_words:
                if word in filename_lower:
                    score += 10
                if word in path_lower:
                    score += 5
            
            if score > 0:
                scored_files.append((score, filepath))
        
        # Sort by score descending, then alphabetically
        scored_files.sort(key=lambda x: (-x[0], x[1]))
        
        return [f for _, f in scored_files[:limit]]
    
    async def _handle_ai_hub(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ai command and Claude hub screen."""
        logger.info(f"Received Claude hub request from chat {update.effective_chat.id}")
        
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        if not ANTHROPIC_AVAILABLE:
            await self._send_message_or_edit(
                update, context,
                "❌ *Claude Not Available*\n\n"
                "Install with: `pip install -e .[llm]`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        # Check if chat mode is enabled (from persistent prefs)
        chat_mode = self.prefs.get("ai_chat_mode", False) if self.prefs else False
        
        # Get chat history length for display
        chat_history = context.user_data.get("claude_chat_history", []) if hasattr(context, "user_data") else []
        history_info = f"\n📝 Chat history: {len(chat_history)} messages" if chat_history else ""
        
        status = "🟢 Chat mode ON - send any message" if chat_mode else "⚪ Chat mode OFF"
        
        message = (
            "🤖 *Claude AI Hub*\n\n"
            f"{status}\n"
            f"{history_info}\n\n"
            "*Features:*\n"
            "• *Chat mode* - Talk to Claude like Cursor\n"
            "• *Patch wizard* - Describe a change, get a diff\n\n"
            "💡 When chat is ON, just send a message to talk to Claude."
        )
        
        await self._send_message_or_edit(
            update, context,
            message,
            reply_markup=self._get_claude_hub_buttons(chat_mode_enabled=chat_mode),
        )
    
    async def _handle_ai_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ai_on command - enable chat mode."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Set in persistent prefs
        if self.prefs:
            self.prefs.set("ai_chat_mode", True)
        
        await self._send_message_or_edit(
            update, context,
            "🟢 *Claude Chat Mode: ON*\n\n"
            "Send any message to chat with Claude.\n"
            "Use `/ai_off` to disable.",
            reply_markup=self._get_claude_hub_buttons(chat_mode_enabled=True),
        )
    
    async def _handle_ai_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ai_off command - disable chat mode."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Set in persistent prefs
        if self.prefs:
            self.prefs.set("ai_chat_mode", False)
        
        await self._send_message_or_edit(
            update, context,
            "⚪ *Claude Chat Mode: OFF*\n\n"
            "Regular messages will no longer go to Claude.\n"
            "Use `/ai_on` or tap Claude in the menu to enable.",
            reply_markup=self._get_claude_hub_buttons(chat_mode_enabled=False),
        )
    
    async def _handle_ai_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ai_reset command - reset chat history."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        if hasattr(context, "user_data"):
            context.user_data["claude_chat_history"] = []
            context.user_data.pop("claude_wizard_state", None)
            context.user_data.pop("claude_wizard_task", None)
            context.user_data.pop("claude_wizard_files", None)
        # Also clear persisted chat history
        self._clear_persistent_claude_chat_history()
        self._clear_claude_memory_summary()
        
        chat_mode = self.prefs.get("ai_chat_mode", False) if self.prefs else False
        
        await self._send_message_or_edit(
            update, context,
            "🧼 *Chat Reset*\n\n"
            "Chat history cleared. Starting fresh.",
            reply_markup=self._get_claude_hub_buttons(chat_mode_enabled=chat_mode),
        )

    async def _handle_claude_memory_view(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show the durable Claude memory summary (operator preferences/goals)."""
        if not await self._check_authorized(update):
            return

        summary = self._load_claude_memory_summary()
        text = summary if summary else "_No memory saved yet._\n\nChat a bit, then refresh to build memory."

        message = "🧠 *Claude Memory*\n\n" + text
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔄 Refresh Memory", callback_data="claude_memory_refresh"),
                    InlineKeyboardButton("🧼 Clear", callback_data="claude_memory_clear"),
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="claude_hub")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
        )
        await self._send_message_or_edit(update, context, message, reply_markup=keyboard)

    async def _handle_claude_memory_refresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Force-refresh the durable memory summary using recent chat history."""
        if not await self._check_authorized(update):
            return

        await self._send_message_or_edit(
            update,
            context,
            "🧠 *Claude Memory*\n\n🔄 Refreshing memory…",
            reply_markup=None,
        )

        # Use current chat history if available, else load from disk
        history: List[Dict[str, str]] = []
        if hasattr(context, "user_data") and isinstance(context.user_data.get("claude_chat_history"), list):
            history = context.user_data.get("claude_chat_history") or []
        else:
            history = self._load_persistent_claude_chat_history()

        # Best-effort summarization (uses Claude)
        try:
            await self._update_claude_memory_summary(history)
        except Exception:
            pass

        await self._handle_claude_memory_view(update, context)

    async def _handle_claude_memory_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clear the durable memory summary."""
        if not await self._check_authorized(update):
            return
        self._clear_claude_memory_summary()
        await self._handle_claude_memory_view(update, context)
    
    async def _handle_claude_chat_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle Claude chat mode on/off (persistent setting)."""
        if self.prefs:
            self.prefs.toggle("ai_chat_mode")
        
        # Re-render the hub
        await self._handle_ai_hub(update, context)
    
    async def _handle_claude_monitor_hub(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show Claude Monitor hub with analysis options."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        logger.info(f"📡 Claude Monitor hub requested from {update.effective_chat.id}")
        
        # Monitor service status (daily reports + proactive alerts require the service)
        svc_status = {}
        try:
            svc_status = self.service_controller.get_claude_monitor_status()
        except Exception:
            svc_status = {}
        svc_running = bool(svc_status.get("running"))
        svc_pid = svc_status.get("pid")

        # Analyzer availability (on-demand analysis works even if service is stopped)
        monitor = self._get_claude_monitor()
        
        if not monitor:
            message = (
                "🔍 *AI Monitor*\n\n"
                f"{'🟢' if svc_running else '⚪'} Service: `{'running' if svc_running else 'stopped'}`"
                f"{f' (PID {svc_pid})' if svc_pid else ''}\n\n"
                "⚠️ Claude Monitor not fully available.\n"
                "Check that `anthropic` package is installed.\n\n"
                "_The analysis commands below will work with limited features._"
            )
        else:
            stats = monitor.monitor_state.get_stats()
            claude_ok = "✅" if monitor._claude else "⚠️"
            
            message = (
                "🔍 *AI Monitor*\n\n"
                f"{'🟢' if svc_running else '⚪'} Service: `{'running' if svc_running else 'stopped'}`"
                f"{f' (PID {svc_pid})' if svc_pid else ''}\n"
                f"{claude_ok} Claude API: `{'available' if monitor._claude else 'limited'}`\n"
                f"🕒 Timezone: `{getattr(monitor, 'timezone_name', 'n/a')}`\n"
                f"📊 Analyses: `{stats.get('analysis_count', 0)}`\n"
                f"💡 Suggestions: `{stats.get('active_suggestions', 0)}` active\n\n"
                "*Analyze your trading agent:*\n"
                "_Tip: Start the service to get daily reports + proactive alerts._"
            )
        
        await self._send_message_or_edit(
            update, context,
            message,
            reply_markup=self._get_claude_hub_buttons(show_monitor=True),
        )

    async def _handle_claude_monitor_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Start the Claude Monitor service (background)."""
        if not await self._check_authorized(update):
            return

        await self._send_message_or_edit(
            update,
            context,
            "▶️ Starting *Claude Monitor*...\n\nThis runs in the background and sends daily reports + proactive alerts.",
            reply_markup=None,
        )

        result = await self.service_controller.start_claude_monitor(background=True)
        message = f"{result.get('message', 'Done')}\n"
        if result.get("details"):
            message += f"\n{escape_subprocess_output(result['details'])}"

        await self._send_message_or_edit(
            update,
            context,
            message,
            reply_markup=self._get_claude_hub_buttons(show_monitor=True),
        )

    async def _handle_claude_monitor_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Stop the Claude Monitor service."""
        if not await self._check_authorized(update):
            return

        await self._send_message_or_edit(
            update,
            context,
            "⏹️ Stopping *Claude Monitor*...",
            reply_markup=None,
        )

        result = await self.service_controller.stop_claude_monitor()
        message = f"{result.get('message', 'Done')}\n"
        if result.get("details"):
            message += f"\n{escape_subprocess_output(result['details'])}"

        await self._send_message_or_edit(
            update,
            context,
            message,
            reply_markup=self._get_claude_hub_buttons(show_monitor=True),
        )
    
    async def _handle_claude_patch_wizard_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the patch wizard - offer Auto or Manual mode."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Set wizard state
        if hasattr(context, "user_data"):
            context.user_data["claude_wizard_state"] = "choose_mode"
            context.user_data["claude_wizard_task"] = None
            context.user_data["claude_wizard_files"] = set()
            context.user_data["claude_wizard_suggested"] = []
        
        await self._send_message_or_edit(
            update, context,
            "🧩 *Patch Wizard*\n\n"
            "Choose your mode:\n\n"
            "🚀 *Auto* — Just describe what you want.\n"
            "_Claude finds files & generates patch automatically._\n\n"
            "🔧 *Manual* — Select files yourself.\n"
            "_More control, but requires file navigation._",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Auto (Recommended)", callback_data='claude_wizard_auto')],
                [InlineKeyboardButton("🔧 Manual", callback_data='claude_wizard_manual')],
                [InlineKeyboardButton("❌ Cancel", callback_data='claude_cancel')],
            ]),
        )
    
    async def _handle_claude_wizard_auto_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start auto patch mode - Claude does everything."""
        if not await self._check_authorized(update):
            return
        
        if hasattr(context, "user_data"):
            context.user_data["claude_wizard_state"] = "auto_awaiting_task"
            context.user_data["claude_wizard_task"] = None
        
        await self._send_message_or_edit(
            update, context,
            "🚀 *Auto Patch*\n\n"
            "Just describe what you want to change:\n\n"
            "_Examples:_\n"
            "• `add rate limiting to the API client`\n"
            "• `fix the bug where signals aren't sent`\n"
            "• `add logging to the order executor`\n\n"
            "I'll find the right files and generate a patch automatically.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data='claude_cancel')],
            ]),
        )
    
    async def _handle_claude_wizard_manual_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start manual patch mode - user selects files."""
        if not await self._check_authorized(update):
            return
        
        if hasattr(context, "user_data"):
            context.user_data["claude_wizard_state"] = "awaiting_task"
            context.user_data["claude_wizard_task"] = None
            context.user_data["claude_wizard_files"] = set()
            context.user_data["claude_wizard_suggested"] = []
        
        await self._send_message_or_edit(
            update, context,
            "🔧 *Manual Patch*\n\n"
            "*Step 1:* Describe what you want to change.\n\n"
            "I'll suggest files and you can pick which ones to include.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data='claude_cancel')],
            ]),
        )
    
    async def _process_auto_patch(self, update: Update, context: ContextTypes.DEFAULT_TYPE, task: str):
        """
        Fully agentic patch generation - Claude finds files and generates patch automatically.
        """
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Send progress message (supports both message and button-trigger flows)
        progress_text = (
            "🔍 *Analyzing your request...*\n\n"
            "Claude is:\n"
            "1️⃣ Understanding your task\n"
            "2️⃣ Searching for relevant files\n"
            "3️⃣ Reading file contents\n"
            "4️⃣ Generating patch\n\n"
            "_This may take 15-60 seconds..._"
        )
        if update.message:
            progress_msg = await update.message.reply_text(progress_text, parse_mode="Markdown")
        else:
            progress_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=progress_text,
                parse_mode="Markdown",
            )
        
        try:
            # Discover all project files
            all_files = self._discover_project_files()
            
            # Get Claude to suggest the most relevant files
            client = get_claude_client()
            if not client:
                await progress_msg.edit_text(
                    "❌ Claude not available.\n\n"
                    "Make sure `ANTHROPIC_API_KEY` is set in `.env`",
                    parse_mode="Markdown",
                )
                return
            
            import asyncio
            
            # Step 1: Let Claude identify relevant files
            suggested_files = await asyncio.to_thread(client.suggest_files, task, all_files)
            suggested_files = (suggested_files or [])[:8]
            
            if not suggested_files:
                # Fallback to local search
                suggested_files = self._search_files(task, all_files)[:5]
            
            if not suggested_files:
                await progress_msg.edit_text(
                    "⚠️ *Couldn't find relevant files*\n\n"
                    "Try being more specific about which component "
                    "or file you want to modify.",
                    parse_mode="Markdown",
                    reply_markup=self._get_claude_hub_buttons(),
                )
                return
            
            # Update progress
            file_list = "\n".join(f"• `{f.split('/')[-1]}`" for f in suggested_files[:5])
            await progress_msg.edit_text(
                f"🔍 *Found relevant files:*\n{file_list}\n\n"
                "📝 Generating patch...",
                parse_mode="Markdown",
            )
            
            # Step 2: Read file contents
            file_contents = {}
            errors = []
            for filepath in suggested_files:
                try:
                    full_path = self._resolve_project_path(filepath)
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    # Limit content to avoid token issues
                    if len(content) > 15000:
                        content = content[:15000] + "\n\n... [truncated for length] ..."
                    file_contents[filepath] = content
                except Exception as e:
                    errors.append(filepath)
            
            if not file_contents:
                await progress_msg.edit_text(
                    f"❌ Could not read files:\n`{', '.join(errors)}`",
                    parse_mode="Markdown",
                    reply_markup=self._get_claude_hub_buttons(),
                )
                return
            
            # Step 3: Generate patch
            try:
                diff_output = await asyncio.to_thread(
                    client.generate_patch, file_contents, task
                )
            except ClaudeAPIKeyMissingError:
                await progress_msg.edit_text(
                    "❌ *API Key Not Configured*\n\n"
                    "`ANTHROPIC_API_KEY` not set in `.env`.",
                    parse_mode="Markdown",
                    reply_markup=self._get_claude_hub_buttons(),
                )
                return
            except Exception as e:
                logger.error(f"Error generating patch: {e}", exc_info=True)
                await progress_msg.edit_text(
                    f"❌ *Error*\n\n`{str(e)[:200]}`",
                    parse_mode="Markdown",
                    reply_markup=self._get_claude_hub_buttons(),
                )
                return
            
            # Check if we got a valid diff
            if not diff_output or not diff_output.strip():
                await progress_msg.edit_text(
                    "⚠️ *No changes needed*\n\n"
                    "Claude analyzed the files but didn't generate any changes.\n"
                    "Try rephrasing your request.",
                    parse_mode="Markdown",
                    reply_markup=self._get_claude_hub_buttons(),
                )
                return
            
            # Deliver patch
            INLINE_LIMIT = 3500
            if len(diff_output) <= INLINE_LIMIT:
                message = (
                    f"✅ *Auto Patch Generated*\n\n"
                    f"📋 Task: _{task[:100]}_\n"
                    f"📁 Files: `{len(file_contents)}`\n\n"
                    f"```diff\n{diff_output}\n```\n\n"
                    "💡 Copy and apply with `git apply` or review in Cursor."
                )
                await progress_msg.edit_text(
                    message,
                    parse_mode="Markdown",
                    reply_markup=self._get_claude_hub_buttons(),
                )
            else:
                # Send as file
                import io
                diff_bytes = diff_output.encode("utf-8")
                diff_file = io.BytesIO(diff_bytes)
                diff_file.name = "auto_patch.diff"
                
                await progress_msg.edit_text(
                    f"✅ *Auto Patch Generated*\n\n"
                    f"📋 Task: _{task[:100]}_\n"
                    f"📁 Files: `{len(file_contents)}`\n\n"
                    "Patch is large - sending as file...",
                    parse_mode="Markdown",
                )
                
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=diff_file,
                    filename="auto_patch.diff",
                    caption=f"🚀 Auto Patch: {task[:50]}...\n\nApply with: `git apply auto_patch.diff`",
                    parse_mode="Markdown",
                )
                
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="📄 Patch file sent above.",
                    reply_markup=self._get_claude_hub_buttons(),
                )
            
        except Exception as e:
            logger.error(f"Auto patch error: {e}", exc_info=True)
            await progress_msg.edit_text(
                f"❌ *Error*\n\n`{str(e)[:300]}`",
                parse_mode="Markdown",
                reply_markup=self._get_claude_hub_buttons(),
            )
        finally:
            # Clear wizard state
            if hasattr(context, "user_data"):
                context.user_data.pop("claude_wizard_state", None)
                context.user_data.pop("claude_wizard_task", None)
    
    async def _handle_claude_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle plain text messages for Claude chat mode and wizard.
        
        Routes messages based on current state:
        - If in wizard "awaiting_task" state -> process as wizard task
        - If in wizard "refine_search" state -> search for files
        - If chat mode enabled -> send to Claude
        - Otherwise -> ignore (let other handlers process)
        """
        if not update.message or not update.message.text:
            return
        
        if not await self._check_authorized(update):
            return
        
        text = update.message.text.strip()
        if not text:
            return
        
        # Check wizard state first (session-based)
        wizard_state = context.user_data.get("claude_wizard_state") if hasattr(context, "user_data") else None
        
        if wizard_state == "auto_awaiting_task":
            await self._process_auto_patch(update, context, text)
            return
        
        if wizard_state == "awaiting_task":
            await self._process_wizard_task(update, context, text)
            return
        
        if wizard_state == "refine_search":
            await self._process_wizard_search(update, context, text)
            return
        
        # Check for AI Terminal commands (starts with !)
        # Terminal commands work even when chat mode is off
        if text.startswith("!"):
            await self._process_terminal_command(update, context, text[1:].strip())
            return
        
        # Check chat mode (persistent preference)
        chat_mode = self.prefs.get("ai_chat_mode", False) if self.prefs else False
        
        if chat_mode:
            await self._process_claude_chat(update, context, text)
            return
        
        # Not in chat mode and not in wizard - ignore message
        # (Let other handlers or default behavior handle it)
    
    async def _process_wizard_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE, task: str):
        """Process wizard task description and suggest files."""
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Store task
        if hasattr(context, "user_data"):
            context.user_data["claude_wizard_task"] = task
            context.user_data["claude_wizard_state"] = "selecting_files"
            context.user_data["claude_wizard_files"] = set()
        
        # Discover project files
        all_files = self._discover_project_files()
        
        # Try to get suggestions from Claude
        suggested_files = []
        try:
            client = get_claude_client()
            if client:
                import asyncio
                # Run in thread to avoid blocking
                suggested_files = await asyncio.to_thread(
                    client.suggest_files, task, all_files
                )
        except Exception as e:
            logger.warning(f"Could not get Claude file suggestions: {e}")
        
        # Fallback to local search if Claude didn't suggest
        if not suggested_files:
            suggested_files = self._search_files(task, all_files)
        
        # Store suggestions
        if hasattr(context, "user_data"):
            context.user_data["claude_wizard_suggested"] = suggested_files
        
        if not suggested_files:
            await self._send_message_or_edit(
                update, context,
                "🧩 *Patch Wizard*\n\n"
                f"*Task:* {task[:100]}{'...' if len(task) > 100 else ''}\n\n"
                "⚠️ No matching files found.\n\n"
                "Try using 🔍 Refine to search for specific files.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Search Files", callback_data='claude_refine_search')],
                    [InlineKeyboardButton("❌ Cancel", callback_data='claude_cancel')],
                ]),
            )
            return
        
        await self._send_message_or_edit(
            update, context,
            "🧩 *Patch Wizard*\n\n"
            f"*Task:* {task[:100]}{'...' if len(task) > 100 else ''}\n\n"
            "*Step 2:* Select files to modify\n"
            "Tap to toggle selection, 👁 to preview.\n"
            "Then tap ✅ Generate Patch.",
            reply_markup=self._get_claude_wizard_files_buttons(suggested_files, set()),
        )
    
    async def _process_wizard_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
        """Process file search query in wizard."""
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Search files
        all_files = self._discover_project_files()
        matching_files = self._search_files(query, all_files)
        
        # Merge with existing suggestions (keep selected ones)
        existing_suggested = context.user_data.get("claude_wizard_suggested", []) if hasattr(context, "user_data") else []
        selected_files = context.user_data.get("claude_wizard_files", set()) if hasattr(context, "user_data") else set()
        
        # Combine: matching files first, then previously suggested (deduplicated)
        combined = []
        seen = set()
        for f in matching_files + existing_suggested:
            if f not in seen:
                combined.append(f)
                seen.add(f)
        
        # Update suggestions
        if hasattr(context, "user_data"):
            context.user_data["claude_wizard_suggested"] = combined[:8]
            context.user_data["claude_wizard_state"] = "selecting_files"
        
        task = context.user_data.get("claude_wizard_task", "") if hasattr(context, "user_data") else ""
        
        await self._send_message_or_edit(
            update, context,
            "🧩 *Patch Wizard*\n\n"
            f"*Task:* {task[:80]}{'...' if len(task) > 80 else ''}\n"
            f"*Search:* `{query}`\n\n"
            f"Found {len(matching_files)} matching files.\n"
            "Tap to select, 👁 to preview.",
            reply_markup=self._get_claude_wizard_files_buttons(combined[:8], selected_files),
        )

    def _build_ai_chat_snapshot(self) -> str:
        """
        Build a compact, read-only snapshot of the current agent state for Claude chat.

        This helps Claude answer questions like "how are trades doing?" with concrete context.
        Keep this short to control token usage.
        """
        lines: List[str] = []
        try:
            lines.append(f"utc_now: {datetime.now(timezone.utc).isoformat()}")
        except Exception:
            pass

        # Processes (source of truth for "is it running?")
        try:
            lines.append(f"agent_process_running: {self._is_agent_process_running()}")
        except Exception:
            pass
        try:
            gw = self.service_controller.get_gateway_status()
            lines.append(f"gateway_process_running: {bool(gw.get('process_running'))}")
            lines.append(f"gateway_api_ready: {bool(gw.get('port_listening'))}")
        except Exception:
            pass

        # state.json (trading/runtime state)
        try:
            state_file = get_state_file(self.state_dir)
            if state_file.exists():
                with open(state_file, "r") as f:
                    state = json.load(f)
                if isinstance(state, dict):
                    for key in ("running", "paused", "data_fresh", "latest_price", "latest_bar_timestamp"):
                        if key in state and state.get(key) is not None:
                            lines.append(f"state.{key}: {state.get(key)}")

                    active_trades = state.get("active_trades")
                    if isinstance(active_trades, list):
                        lines.append(f"active_trades_count: {len(active_trades)}")
                    elif state.get("active_trades_count") is not None:
                        lines.append(f"active_trades_count: {state.get('active_trades_count')}")
        except Exception:
            pass

        # performance.json (aggregates)
        try:
            perf_file = self.state_dir / "performance.json"
            if perf_file.exists():
                with open(perf_file, "r") as f:
                    perf = json.load(f)
                if isinstance(perf, dict):
                    wins = perf.get("wins")
                    losses = perf.get("losses")
                    if wins is not None or losses is not None:
                        lines.append(f"performance_7d.wins_losses: {wins}/{losses}")
                    if perf.get("win_rate") is not None:
                        lines.append(f"performance_7d.win_rate: {perf.get('win_rate')}")
                    if perf.get("total_pnl") is not None:
                        lines.append(f"performance_7d.total_pnl: {perf.get('total_pnl')}")
        except Exception:
            pass

        # ML/Bandit Policy status (for Claude to monitor learning)
        try:
            state_file = get_state_file(self.state_dir)
            if state_file.exists():
                with open(state_file, "r") as f:
                    state = json.load(f)
                if isinstance(state, dict):
                    learning = state.get("learning", {})
                    if learning.get("enabled"):
                        lines.append("ml.learning_enabled: true")
                        lines.append(f"ml.mode: {learning.get('mode', 'shadow')}")
                        
                        # Bandit policy stats
                        bandit = state.get("bandit_policy", {})
                        if isinstance(bandit, dict):
                            signal_types = bandit.get("signal_types", {})
                            if signal_types:
                                lines.append("ml.bandit_policy:")
                                for sig_type, stats in signal_types.items():
                                    wins = stats.get("wins", 0)
                                    losses = stats.get("losses", 0)
                                    total = wins + losses
                                    wr = (wins / total * 100) if total > 0 else 0
                                    lines.append(f"  {sig_type}: {wins}W/{losses}L ({wr:.0f}% WR, n={total})")
        except Exception:
            pass

        # recent signals (last few)
        try:
            from collections import deque

            signals_file = get_signals_file(self.state_dir)
            if signals_file.exists():
                tail: "deque[str]" = deque(maxlen=5)
                with open(signals_file, "r") as f:
                    for line in f:
                        if line.strip():
                            tail.append(line)
                if tail:
                    lines.append("recent_signals:")
                    for raw in list(tail)[-3:]:
                        try:
                            sig = json.loads(raw)
                        except Exception:
                            continue
                        sig_type = sig.get("signal_type") or sig.get("type") or "unknown"
                        direction = str(sig.get("direction") or "").upper()
                        status = sig.get("status") or sig.get("state") or "unknown"
                        ts = sig.get("timestamp") or sig.get("generated_at") or sig.get("created_at") or "n/a"
                        lines.append(f"- {sig_type} {direction} ({status}) @ {ts}")
        except Exception:
            pass

        # Durable operator memory (helps keep Claude consistent without long chat history)
        try:
            mem = self._load_claude_memory_summary()
            if mem:
                lines.append("")
                lines.append("operator_memory:")
                # Keep it compact; the summary is already line-bounded.
                for ln in mem.splitlines():
                    ln = ln.strip()
                    if ln:
                        lines.append(ln)
        except Exception:
            pass

        snapshot = "\n".join(lines).strip()
        if len(snapshot) > 1800:
            snapshot = snapshot[:1800] + "\n...(truncated)"
        return snapshot

    def _format_telegram_plaintext(
        self,
        text: str,
        *,
        max_lines: int | None = None,
        max_chars: int = 1600,
    ) -> str:
        """
        Sanitize model output for Telegram.

        Telegram doesn't support GitHub-style markdown headings/bold (e.g. ##, **).
        This helper removes common markdown artifacts and optionally truncates for mobile.
        """
        try:
            raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        except Exception:
            raw = str(text)

        cleaned_lines: List[str] = []
        prev_blank = False
        in_code_block = False

        for line in raw.split("\n"):
            ln = line.strip()

            # Drop fenced code blocks entirely for readability
            if ln.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            # Strip Markdown headings like "## Title"
            if ln.startswith("#"):
                ln = ln.lstrip("#").strip()

            # Strip common Markdown emphasis markers
            ln = ln.replace("**", "")

            if not ln:
                if not prev_blank:
                    cleaned_lines.append("")
                prev_blank = True
                continue

            prev_blank = False
            cleaned_lines.append(ln)

        out = "\n".join(cleaned_lines).strip()

        if max_lines is not None and max_lines > 0:
            lines_out = out.split("\n")
            if len(lines_out) > max_lines:
                out = "\n".join(lines_out[:max_lines]).rstrip() + "\n… (tap Export for full)"

        if max_chars and len(out) > max_chars:
            out = out[: max_chars - 1].rstrip() + "…"

        return out
    
    async def _process_claude_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Process a chat message and get Claude's response."""
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Get chat history (persisted across restarts)
        chat_history: List[Dict[str, str]] = []
        if hasattr(context, "user_data") and "claude_chat_history" in context.user_data:
            raw = context.user_data.get("claude_chat_history")
            if isinstance(raw, list):
                chat_history = raw
        else:
            chat_history = self._load_persistent_claude_chat_history()
            if hasattr(context, "user_data"):
                context.user_data["claude_chat_history"] = chat_history
        
        # Add user message to history
        chat_history.append({"role": "user", "content": text})

        # Rolling memory: when history grows large, summarize older messages into durable memory
        HISTORY_MAX = 40
        MODEL_CONTEXT = 12
        if len(chat_history) > HISTORY_MAX:
            overflow = chat_history[:-MODEL_CONTEXT]
            chat_history = chat_history[-MODEL_CONTEXT:]
            # Best-effort: update durable memory; do not fail the chat if this errors
            try:
                await self._update_claude_memory_summary(overflow)
            except Exception:
                pass
        
        try:
            client = get_claude_client()
            if not client:
                hint = (
                    "❌ Claude not available.\n\n"
                    "What to check:\n"
                    "• Install extras: `pip install -e .[llm]`\n"
                    "• Set `ANTHROPIC_API_KEY` in `.env` and restart the handler"
                )
                await update.message.reply_text(hint, reply_markup=self._get_claude_hub_buttons(chat_mode_enabled=True))
                return

            chat_controls = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("🤖 Hub", callback_data="claude_hub"),
                        InlineKeyboardButton("💬 Chat: OFF", callback_data="claude_chat_toggle"),
                    ],
                    [InlineKeyboardButton("🏠 Menu", callback_data="start")],
                ]
            )
            
            import asyncio
            # Run in thread to avoid blocking. Include a compact runtime snapshot for better answers.
            system_prompt = build_chat_system_prompt(
                system_snapshot=self._build_ai_chat_snapshot(),
                memory_summary=self._load_claude_memory_summary(),
            )
            # Keep the model context small; durable memory carries long-term context.
            response = await asyncio.to_thread(client.chat, chat_history[-MODEL_CONTEXT:], system_prompt)
            
            # Add assistant response to history
            chat_history.append({"role": "assistant", "content": response})
            
            # Save history
            if hasattr(context, "user_data"):
                context.user_data["claude_chat_history"] = chat_history
            self._save_persistent_claude_chat_history(chat_history)
            
            # Send response (handle long responses)
            if len(response) > 4000:
                # Send as file
                import io
                response_file = io.BytesIO(response.encode("utf-8"))
                response_file.name = "response.txt"
                
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=response_file,
                    filename="claude_response.txt",
                    caption="📝 Response was too long, sent as file.",
                )
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⬅️ Use the buttons below to return to the hub or disable chat mode.",
                    reply_markup=chat_controls,
                )
            else:
                # Send as plain text (avoid Telegram Markdown parsing errors + GitHub-markdown artifacts).
                response_clean = self._format_telegram_plaintext(response, max_lines=None, max_chars=3500)
                await update.message.reply_text(response_clean, reply_markup=chat_controls)
                
        except ClaudeAPIKeyMissingError:
            await update.message.reply_text(
                "❌ `ANTHROPIC_API_KEY` not set in `.env`.",
                parse_mode="Markdown",
                reply_markup=self._get_claude_hub_buttons(chat_mode_enabled=True),
            )
        except ClaudeAPIError as e:
            await update.message.reply_text(
                f"❌ Claude error: {str(e)[:200]}",
                reply_markup=self._get_claude_hub_buttons(chat_mode_enabled=True),
            )
        except Exception as e:
            logger.error(f"Error in Claude chat: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ Error: {str(e)[:200]}",
                reply_markup=self._get_claude_hub_buttons(chat_mode_enabled=True),
            )
    
    # =========================================================================
    # AI Terminal Mode - Deterministic command interface (!command syntax)
    # =========================================================================
    
    async def _process_terminal_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        command_text: str,
    ) -> None:
        """
        Process AI Terminal commands (prefixed with !).
        
        Supported commands:
        - !status - Show agent status
        - !config <path> [value] - Get/set config values
        - !apply <suggestion_id> - Apply a suggestion
        - !rollback <request_id> - Rollback an action
        - !suggestions - List active suggestions
        - !audit [n] - Show recent audit log entries
        - !policy - Show policy status
        - !help - Show terminal help
        """
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        parts = command_text.split(maxsplit=2)
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []
        
        try:
            if cmd == "help" or not cmd:
                await self._terminal_help(update)
            elif cmd == "status":
                await self._terminal_status(update)
            elif cmd == "config":
                await self._terminal_config(update, args)
            elif cmd == "apply":
                await self._terminal_apply(update, args)
            elif cmd == "rollback":
                await self._terminal_rollback(update, args)
            elif cmd == "suggestions" or cmd == "sug":
                await self._terminal_suggestions(update)
            elif cmd == "audit":
                await self._terminal_audit(update, args)
            elif cmd == "policy":
                await self._terminal_policy(update)
            else:
                await update.message.reply_text(
                    f"❓ Unknown command: `{cmd}`\n\n"
                    "Type `!help` for available commands.",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"Terminal command error: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:200]}")
    
    async def _terminal_help(self, update: Update) -> None:
        """Show terminal help."""
        help_text = """
🖥️ *AI Terminal Commands*

*Status & Info*
`!status` - Agent status snapshot
`!config <path>` - Show config value
`!policy` - Auto-tune policy status
`!suggestions` - List active suggestions
`!audit [n]` - Recent audit entries (default 10)

*Actions*
`!config <path> <value>` - Update config
`!apply <suggestion_id>` - Apply suggestion
`!rollback <request_id>` - Rollback action

*Examples*
`!config signals.min_confidence`
`!config signals.min_confidence 0.65`
`!apply sug_001`
`!rollback act_20260102_0001`

_Commands are policy-gated for safety._
"""
        await update.message.reply_text(help_text.strip(), parse_mode="Markdown")
    
    async def _terminal_status(self, update: Update) -> None:
        """Show agent status via terminal."""
        state = self._load_state_snapshot()
        if not state:
            await update.message.reply_text("⚠️ Agent state unavailable")
            return
        
        execution = state.get("execution", {})
        mode = execution.get("mode", "paper")
        armed = "🔴 ARMED" if execution.get("armed") else "⚪ Disarmed"
        
        lines = [
            "📊 *Agent Status*",
            "",
            f"*Mode:* `{mode}` {armed}",
            f"*Running:* {'✅' if state.get('running') else '❌'}",
            f"*Uptime:* `{state.get('uptime', 'N/A')}`",
            f"*Connection:* {'🟢' if state.get('connected') else '🔴'}",
            f"*Errors:* `{state.get('consecutive_errors', 0)}`",
            "",
            f"*Last Signal:* `{state.get('last_signal_time', 'N/A')}`",
            f"*Open Positions:* `{len(state.get('positions', []))}`",
        ]
        
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    
    async def _terminal_config(self, update: Update, args: List[str]) -> None:
        """Get or set config values via terminal."""
        if not args:
            await update.message.reply_text(
                "Usage: `!config <path>` or `!config <path> <value>`",
                parse_mode="Markdown",
            )
            return
        
        config_path = args[0]
        
        # Load current config
        config = self._load_config_yaml()
        if not config:
            await update.message.reply_text("❌ Could not load config")
            return
        
        # Navigate to config path
        path_parts = config_path.split(".")
        current = config
        for part in path_parts[:-1]:
            current = current.get(part, {})
        
        current_value = current.get(path_parts[-1]) if path_parts else None
        
        if len(args) < 2:
            # GET mode
            await update.message.reply_text(
                f"📝 *Config Value*\n\n"
                f"*Path:* `{config_path}`\n"
                f"*Value:* `{current_value}`",
                parse_mode="Markdown",
            )
            return
        
        # SET mode
        new_value_str = " ".join(args[1:])
        
        # Parse value type
        try:
            if new_value_str.lower() == "true":
                new_value = True
            elif new_value_str.lower() == "false":
                new_value = False
            elif "." in new_value_str:
                new_value = float(new_value_str)
            else:
                try:
                    new_value = int(new_value_str)
                except ValueError:
                    new_value = new_value_str
        except ValueError:
            new_value = new_value_str
        
        # Use monitor's apply_suggestion mechanism with policy checks
        monitor = self._get_claude_monitor()
        if not monitor:
            await update.message.reply_text("❌ Claude monitor not available")
            return
        
        # Check policy first
        if monitor.action_executor._policy:
            agent_state = self._load_state_snapshot() or {}
            decision = monitor.action_executor._policy.check_change(
                config_path=config_path,
                old_value=current_value,
                new_value=new_value,
                agent_state=agent_state,
            )
            
            if not decision.allowed:
                await update.message.reply_text(
                    f"🚫 *Policy Rejected*\n\n"
                    f"*Path:* `{config_path}`\n"
                    f"*Reason:* {decision.reason}\n\n"
                    "_This config path is not allowed for terminal updates._",
                    parse_mode="Markdown",
                )
                return
            
            # Use bounded value if policy adjusted it
            if decision.bounded_value is not None:
                new_value = decision.bounded_value
        
        # Create and execute action request
        from pearlalgo.claude_monitor.action_executor import ActionRequest, ActionType
        
        request = ActionRequest(
            action_type=ActionType.CONFIG_UPDATE,
            description=f"Terminal config update: {config_path}",
            changes={"source": "terminal"},
            config_path=config_path,
            old_value=current_value,
            new_value=new_value,
        )
        
        result = await monitor.action_executor.execute(request)
        
        if result.success:
            await update.message.reply_text(
                f"✅ *Config Updated*\n\n"
                f"*Path:* `{config_path}`\n"
                f"*Old:* `{current_value}`\n"
                f"*New:* `{new_value}`\n\n"
                f"*Request ID:* `{result.request_id}`\n"
                f"*Rollback:* `!rollback {result.request_id}`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"❌ *Update Failed*\n\n"
                f"*Path:* `{config_path}`\n"
                f"*Error:* {result.error or result.message}",
                parse_mode="Markdown",
            )
    
    async def _terminal_apply(self, update: Update, args: List[str]) -> None:
        """Apply a suggestion via terminal."""
        if not args:
            await update.message.reply_text(
                "Usage: `!apply <suggestion_id>`\n\n"
                "Use `!suggestions` to list available suggestions.",
                parse_mode="Markdown",
            )
            return
        
        suggestion_id = args[0]
        monitor = self._get_claude_monitor()
        
        if not monitor:
            await update.message.reply_text("❌ Claude monitor not available")
            return
        
        await update.message.reply_text(f"⏳ Applying `{suggestion_id}`...")
        
        result = await monitor.apply_suggestion(suggestion_id)
        
        if result.get("success"):
            suggestion = result.get("suggestion", {})
            await update.message.reply_text(
                f"✅ *Applied*\n\n"
                f"*ID:* `{suggestion_id}`\n"
                f"*Config:* `{suggestion.get('config_path', 'N/A')}`\n"
                f"*Value:* `{suggestion.get('new_value')}`\n\n"
                f"*Request ID:* `{result.get('request_id')}`\n"
                f"*Rollback:* `!rollback {result.get('request_id')}`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"❌ *Failed*\n\n"
                f"*ID:* `{suggestion_id}`\n"
                f"*Error:* {result.get('error', 'Unknown')}",
                parse_mode="Markdown",
            )
    
    async def _terminal_rollback(self, update: Update, args: List[str]) -> None:
        """Rollback an action via terminal."""
        if not args:
            await update.message.reply_text(
                "Usage: `!rollback <request_id>`\n\n"
                "Request IDs are shown when applying suggestions/configs.",
                parse_mode="Markdown",
            )
            return
        
        request_id = args[0]
        monitor = self._get_claude_monitor()
        
        if not monitor:
            await update.message.reply_text("❌ Claude monitor not available")
            return
        
        await update.message.reply_text(f"⏳ Rolling back `{request_id}`...")
        
        result = await monitor.rollback_suggestion(request_id)
        
        if result.get("success"):
            await update.message.reply_text(
                f"✅ *Rolled Back*\n\n"
                f"*Request ID:* `{request_id}`\n"
                f"*Status:* `{result.get('status')}`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"❌ *Rollback Failed*\n\n"
                f"*Request ID:* `{request_id}`\n"
                f"*Error:* {result.get('error', 'Unknown')}",
                parse_mode="Markdown",
            )
    
    async def _terminal_suggestions(self, update: Update) -> None:
        """List active suggestions via terminal."""
        monitor = self._get_claude_monitor()
        
        if not monitor:
            await update.message.reply_text("❌ Claude monitor not available")
            return
        
        suggestions = monitor.get_active_suggestions()
        
        if not suggestions:
            await update.message.reply_text("📋 No active suggestions")
            return
        
        lines = ["📋 *Active Suggestions*", ""]
        for sug in suggestions[:10]:  # Limit to 10
            sug_id = sug.get("id", "???")
            title = sug.get("title", "Untitled")[:40]
            risk = sug.get("risk_level", "?")
            config_path = sug.get("config_path", "")
            
            emoji = "🟢" if risk == "low" else ("🟡" if risk == "medium" else "🔴")
            
            lines.append(f"{emoji} `{sug_id}`")
            lines.append(f"   {title}")
            if config_path:
                lines.append(f"   📝 `{config_path}`")
            lines.append("")
        
        if len(suggestions) > 10:
            lines.append(f"_...and {len(suggestions) - 10} more_")
        
        lines.append("\n`!apply <id>` to apply")
        
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    
    async def _terminal_audit(self, update: Update, args: List[str]) -> None:
        """Show recent audit log entries via terminal."""
        n = 10
        if args:
            try:
                n = min(int(args[0]), 25)
            except ValueError:
                pass
        
        audit_file = self.state_dir / "claude_action_audit.jsonl"
        
        if not audit_file.exists():
            await update.message.reply_text("📜 No audit entries yet")
            return
        
        try:
            with open(audit_file) as f:
                entries = [json.loads(line) for line in f if line.strip()]
        except Exception as e:
            await update.message.reply_text(f"❌ Could not read audit log: {e}")
            return
        
        if not entries:
            await update.message.reply_text("📜 Audit log is empty")
            return
        
        # Get last N entries
        recent = entries[-n:]
        recent.reverse()  # Most recent first
        
        lines = [f"📜 *Recent Audit* (last {len(recent)})", ""]
        
        for entry in recent:
            action = entry.get("action", "?")
            ts = entry.get("timestamp", "")[:16]  # Truncate to min:sec
            req_id = entry.get("request_id", "")[:20]
            
            emoji = {"request": "📤", "result": "📥", "policy_rejected": "🚫", "error": "❌"}.get(action, "•")
            
            lines.append(f"{emoji} `{ts}` {action}")
            if req_id:
                lines.append(f"   `{req_id}`")
        
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    
    async def _terminal_policy(self, update: Update) -> None:
        """Show policy status via terminal."""
        monitor = self._get_claude_monitor()
        
        if not monitor or not monitor.action_executor._policy:
            await update.message.reply_text("⚠️ Policy not available")
            return
        
        status = monitor.action_executor._policy.get_status()
        
        lines = [
            "🔒 *Auto-Tune Policy Status*",
            "",
            f"*Changes Today:* `{status['changes_today']}/{status['max_per_day']}`",
            f"*Remaining:* `{status['remaining_today']}`",
            f"*Block When Armed:* `{status['block_when_armed']}`",
            f"*Auto-Rollback:* `{status['auto_rollback_enabled']}`",
            "",
            "*Allowlist:*",
        ]
        
        for key in status.get("allowlist_keys", [])[:10]:
            lines.append(f"  • `{key}`")
        
        if len(status.get("allowlist_keys", [])) > 10:
            lines.append(f"  _...and {len(status['allowlist_keys']) - 10} more_")
        
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    
    def _load_state_snapshot(self) -> Dict:
        """
        Load a best-effort state snapshot for terminal/monitor tooling.

        Returns the raw `state.json` dict, plus a few convenience fields expected by
        some UI helpers (uptime/connected/positions/last_signal_time).
        """
        try:
            state = self.state_manager.load_state()
            if not isinstance(state, dict) or not state:
                return {}

            snapshot = dict(state)

            # Uptime (human-ish)
            try:
                st = snapshot.get("start_time")
                if st:
                    dt = datetime.fromisoformat(str(st).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    uptime_s = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
                    h = int(uptime_s // 3600)
                    m = int((uptime_s % 3600) // 60)
                    snapshot["uptime"] = f"{h}h {m}m"
            except Exception:
                pass

            # Simple connectivity heuristic
            try:
                snapshot["connected"] = bool(int(snapshot.get("connection_failures", 0) or 0) == 0)
            except Exception:
                snapshot["connected"] = None

            # Last signal time convenience
            snapshot["last_signal_time"] = snapshot.get("last_signal_generated_at") or snapshot.get("last_signal_sent_at")

            # Positions convenience (optional)
            execution = snapshot.get("execution", {})
            if isinstance(execution, dict) and isinstance(execution.get("positions"), list):
                snapshot["positions"] = execution.get("positions")
            else:
                snapshot["positions"] = []

            return snapshot
        except Exception as e:
            logger.debug(f"Could not load state snapshot: {e}")
            return {}

    def _load_config_yaml(self) -> Optional[Dict[str, Any]]:
        """Load config.yaml for terminal config commands."""
        try:
            config_path = self.project_root / "config" / "config.yaml"
            if config_path.exists():
                import yaml
                with open(config_path) as f:
                    return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Could not load config.yaml: {e}")
        return None
    
    async def _handle_claude_file_toggle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        filepath: str,
    ):
        """Toggle file selection in patch wizard."""
        selected_files = context.user_data.get("claude_wizard_files", set()) if hasattr(context, "user_data") else set()
        
        if filepath in selected_files:
            selected_files.discard(filepath)
        else:
            selected_files.add(filepath)
        
        if hasattr(context, "user_data"):
            context.user_data["claude_wizard_files"] = selected_files
        
        # Re-render file selection
        suggested = context.user_data.get("claude_wizard_suggested", []) if hasattr(context, "user_data") else []
        task = context.user_data.get("claude_wizard_task", "") if hasattr(context, "user_data") else ""
        
        selected_display = ", ".join(Path(f).name for f in selected_files) if selected_files else "none"
        
        await self._send_message_or_edit(
            update, context,
            "🧩 *Patch Wizard*\n\n"
            f"*Task:* {task[:80]}{'...' if len(task) > 80 else ''}\n"
            f"*Selected:* {selected_display}\n\n"
            "Tap to toggle, 👁 to preview.",
            reply_markup=self._get_claude_wizard_files_buttons(suggested, selected_files),
        )
    
    async def _handle_claude_file_preview(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        filepath: str,
    ):
        """Preview a file's content (first ~50 lines)."""
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        project_root = Path(__file__).parent.parent.parent.parent
        full_path = project_root / filepath
        
        # Security check
        try:
            resolved = full_path.resolve()
            if not str(resolved).startswith(str(project_root.resolve())):
                await self._send_message_or_edit(
                    update, context,
                    f"❌ Invalid path: `{filepath}`",
                    reply_markup=self._get_back_to_menu_button(),
                )
                return
        except Exception:
            pass
        
        if not full_path.exists() or not full_path.is_file():
            await self._send_message_or_edit(
                update, context,
                f"❌ File not found: `{filepath}`",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            
            # Show first 50 lines max
            preview_lines = lines[:50]
            preview = "\n".join(preview_lines)
            
            # Truncate if too long for message
            if len(preview) > 3000:
                preview = preview[:3000] + "\n... (truncated)"
            
            truncated = len(lines) > 50
            
            await self._send_message_or_edit(
                update, context,
                f"👁 *Preview:* `{filepath}`\n"
                f"({len(lines)} lines{', showing first 50' if truncated else ''})\n\n"
                f"```\n{preview}\n```",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Files", callback_data='claude_patch_wizard')],
                    [InlineKeyboardButton("❌ Cancel Wizard", callback_data='claude_cancel')],
                ]),
            )
        except Exception as e:
            await self._send_message_or_edit(
                update, context,
                f"❌ Could not read file: `{str(e)[:100]}`",
                reply_markup=self._get_back_to_menu_button(),
            )
    
    async def _handle_claude_generate_patch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate patch from wizard selections."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        task = context.user_data.get("claude_wizard_task", "") if hasattr(context, "user_data") else ""
        selected_files = context.user_data.get("claude_wizard_files", set()) if hasattr(context, "user_data") else set()
        
        if not task:
            await self._send_message_or_edit(
                update, context,
                "❌ No task specified. Start the wizard again.",
                reply_markup=self._get_claude_hub_buttons(),
            )
            return
        
        if not selected_files:
            await self._send_message_or_edit(
                update, context,
                "❌ No files selected. Please select at least one file.",
                reply_markup=self._get_back_to_menu_button(),
            )
            return
        
        # Clear wizard state
        if hasattr(context, "user_data"):
            context.user_data.pop("claude_wizard_state", None)
        
        # Show working message
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(
            update, context,
            "🤖 *Generating patch...*\n\n"
            f"*Files:* `{', '.join(Path(f).name for f in selected_files)}`\n"
            f"*Task:* {task[:100]}{'...' if len(task) > 100 else ''}\n\n"
            "This may take 30-60 seconds.",
            reply_markup=None,
        )
        
        # Read file contents
        project_root = Path(__file__).parent.parent.parent.parent
        files_content: Dict[str, str] = {}
        errors = []
        
        for filepath in selected_files:
            full_path = project_root / filepath
            try:
                resolved = full_path.resolve()
                if not str(resolved).startswith(str(project_root.resolve())):
                    errors.append(f"{filepath} (outside project)")
                    continue
                    
                if not full_path.exists():
                    errors.append(f"{filepath} (not found)")
                    continue
                
                content = full_path.read_text(encoding="utf-8", errors="replace")
                files_content[filepath] = content
            except Exception as e:
                errors.append(f"{filepath} ({str(e)[:30]})")
        
        if not files_content:
            await self._send_message_or_edit(
                update, context,
                f"❌ Could not read any files:\n`{', '.join(errors)}`",
                reply_markup=self._get_claude_hub_buttons(),
            )
            return
        
        # Generate patch
        try:
            import asyncio
            client = ClaudeClient()
            diff_output = await asyncio.to_thread(
                client.generate_patch,
                files=files_content,
                task=task,
            )
            
        except ClaudeAPIKeyMissingError:
            await self._send_message_or_edit(
                update, context,
                "❌ *API Key Not Configured*\n\n"
                "`ANTHROPIC_API_KEY` not set in `.env`.",
                reply_markup=self._get_claude_hub_buttons(),
            )
            return
        except ClaudeAPIError as e:
            await self._send_message_or_edit(
                update, context,
                f"❌ *Claude API Error*\n\n`{str(e)[:200]}`",
                reply_markup=self._get_claude_hub_buttons(),
            )
            return
        except Exception as e:
            logger.error(f"Error generating patch: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                f"❌ *Error*\n\n`{str(e)[:200]}`",
                reply_markup=self._get_claude_hub_buttons(),
            )
            return
        
        # Check if we got a valid diff
        if not diff_output or not diff_output.strip():
            await self._send_message_or_edit(
                update, context,
                "⚠️ *Empty Response*\n\n"
                "Claude returned an empty response. Try rephrasing the task.",
                reply_markup=self._get_claude_hub_buttons(),
            )
            return
        
        # Deliver patch
        INLINE_LIMIT = 3500
        file_names = ", ".join(Path(f).name for f in selected_files)
        
        if len(diff_output) <= INLINE_LIMIT:
            safe_diff = diff_output.replace("`", "'")
            message = (
                f"✅ *Patch Generated*\n\n"
                f"*Files:* `{file_names}`\n"
                f"*Task:* {task[:80]}{'...' if len(task) > 80 else ''}\n\n"
                f"```diff\n{safe_diff}\n```\n\n"
                f"💡 Apply with: `git apply patch.diff`"
            )
            await self._send_message_or_edit(
                update, context,
                message,
                reply_markup=self._get_claude_hub_buttons(),
            )
        else:
            import io
            diff_bytes = diff_output.encode("utf-8")
            diff_file = io.BytesIO(diff_bytes)
            diff_file.name = "patch.diff"
            
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action="upload_document"
            )
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=diff_file,
                filename="patch.diff",
                caption=(
                    f"✅ *Patch Generated*\n\n"
                    f"*Files:* `{file_names}`\n"
                    f"*Task:* {task[:80]}{'...' if len(task) > 80 else ''}\n\n"
                    f"💡 Apply with: `git apply patch.diff`"
                ),
                parse_mode="Markdown",
            )
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="📄 Patch file sent above.",
                reply_markup=self._get_claude_hub_buttons(),
            )
    
    async def _handle_claude_refine_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Prompt user to refine file search."""
        if hasattr(context, "user_data"):
            context.user_data["claude_wizard_state"] = "refine_search"
        
        task = context.user_data.get("claude_wizard_task", "") if hasattr(context, "user_data") else ""
        
        await self._send_message_or_edit(
            update, context,
            "🔍 *Search Files*\n\n"
            f"*Task:* {task[:80]}{'...' if len(task) > 80 else ''}\n\n"
            "Type a search term (filename or keyword):\n"
            "• `retry` - find files with 'retry' in name\n"
            "• `telegram` - find telegram-related files\n"
            "• `handler` - find handler files",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data='claude_cancel')],
            ]),
        )

    async def _handle_signal_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        signal_id_prefix: str,
    ) -> None:
        """Show a rich, text-only signal detail view (fast; chart optional)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await self._send_message_or_edit(
                    update,
                    context,
                    "📭 *No signals found*\n\nSignals will appear here once the agent generates opportunities.",
                    reply_markup=self._get_back_to_menu_button(),
                )
                return

            # Search recent signals (tail) for matching prefix
            found: Optional[Dict] = None
            with open(signals_file, "r") as f:
                lines = f.readlines()[-500:]
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "signal" in raw:
                    record = raw
                else:
                    record = {
                        "signal_id": raw.get("signal_id", ""),
                        "timestamp": raw.get("timestamp", ""),
                        "status": raw.get("status", "generated"),
                        "signal": raw,
                    }

                sig_id = record.get("signal_id", "") or ""
                if sig_id.startswith(signal_id_prefix):
                    found = record
                    break

            if not found:
                await self._send_message_or_edit(
                    update,
                    context,
                    f"❌ *Signal not found*\n\nNo signal matching `{signal_id_prefix}` in recent history.",
                    reply_markup=self._get_back_to_menu_button(),
                )
                return

            signal = found.get("signal", {}) or {}
            sig_type = str(signal.get("type", "unknown"))
            status = str(found.get("status", "unknown"))
            sig_id = str(found.get("signal_id", "")) or ""

            entry = float(signal.get("entry_price", 0.0) or 0.0)
            stop = float(signal.get("stop_loss", 0.0) or 0.0)
            tp = float(signal.get("take_profit", 0.0) or 0.0)
            conf = float(signal.get("confidence", 0.0) or 0.0)

            # Use shared helpers for consistent formatting
            is_win = found.get("is_win") if status == "exited" else None
            status_emoji, status_label = format_signal_status(status, is_win)
            dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))
            conf_emoji, conf_tier = format_signal_confidence_tier(conf)

            # Calculate R:R
            rr = None
            if entry > 0 and stop > 0 and tp > 0:
                if dir_label == "LONG":
                    risk = entry - stop
                    reward = tp - entry
                else:
                    risk = stop - entry
                    reward = entry - tp
                if risk > 0:
                    rr = reward / risk

            # Freshness indicator
            sig_ts = found.get("timestamp") or signal.get("timestamp")
            age_str = format_time_ago(sig_ts)

            # DECISION-FIRST LAYOUT: Trade plan at the top for fast action
            message = f"{status_emoji} *Signal Detail*\n"
            message += f"{dir_emoji} *{sig_type.replace('_', ' ').title()}* {dir_label}\n\n"

            # Trade Plan (always visible first)
            message += "📋 *Trade Plan*\n"
            if entry:
                message += f"   Entry: ${entry:.2f}\n"
            if stop:
                stop_dist = abs(entry - stop) if entry else 0
                message += f"   Stop:  ${stop:.2f} ({stop_dist:.2f} pts)\n"
            if tp:
                tp_dist = abs(tp - entry) if entry else 0
                message += f"   TP:    ${tp:.2f} ({tp_dist:.2f} pts)\n"
            if rr is not None:
                message += f"   R:R:   {rr:.2f}:1\n"
            message += "\n"

            # Confidence + Status
            message += f"{conf_emoji} *Confidence:* {conf:.0%} ({conf_tier})\n"

            # Opportunity tier (A-tier actionable vs B-tier explore)
            opp_tier = str(signal.get("_opportunity_tier") or "").strip().upper()
            if opp_tier in ("A", "B"):
                try:
                    label = "Actionable" if opp_tier == "A" else "Explore"
                    tier_emoji = "✅" if opp_tier == "A" else "⚗️"
                    extra = ""
                    reason = str(signal.get("_opportunity_reason") or "").strip()
                    if opp_tier == "B" and reason:
                        extra = f" — {reason[:80]}{'…' if len(reason) > 80 else ''}"
                    message += f"{tier_emoji} *Tier:* `{opp_tier}` ({label}){extra}\n"
                except Exception:
                    pass

            # Learning / policy (show even in non-expanded view for transparency)
            policy = signal.get("_policy")
            if isinstance(policy, dict) and policy.get("signal_type"):
                try:
                    mode = str(policy.get("mode") or "shadow").lower()
                    mode_emoji = "👁️" if mode == "shadow" else "🔥"
                    exec_emoji = "✅" if bool(policy.get("execute")) else "⏭️"
                    sample_count = int(policy.get("sample_count") or 0)
                    obs_wr = policy.get("observed_win_rate")
                    score = policy.get("sampled_score")
                    reason = str(policy.get("reason") or "")

                    parts = [f"{mode_emoji} `{mode}`", exec_emoji]
                    if obs_wr is not None and sample_count > 0:
                        parts.append(f"obs `{float(obs_wr) * 100:.0f}%` (n={sample_count})")
                    elif sample_count > 0:
                        parts.append(f"n={sample_count}")
                    if score is not None:
                        parts.append(f"score `{float(score):.2f}`")
                    if reason:
                        parts.append(f"`{reason[:32]}{'…' if len(reason) > 32 else ''}`")

                    message += "🧠 *Policy:* " + " • ".join(parts) + "\n"
                except Exception:
                    pass

            # Contextual policy (optional): shows the learned context bucket for this setup
            ctx_policy = signal.get("_policy_ctx")
            if isinstance(ctx_policy, dict) and ctx_policy.get("context_key"):
                try:
                    ctx_key = str(ctx_policy.get("context_key") or "")
                    ctx_exec_emoji = "✅" if bool(ctx_policy.get("execute")) else "⏭️"
                    exp_wr = ctx_policy.get("expected_win_rate")
                    ctx_n = int(ctx_policy.get("context_sample_count") or 0)
                    ctx_score = ctx_policy.get("sampled_score")
                    used_global = bool(ctx_policy.get("used_global_fallback"))
                    suffix = " (global)" if used_global else ""

                    parts = [ctx_exec_emoji, f"`{ctx_key}`{suffix}"]
                    if exp_wr is not None:
                        parts.append(f"exp `{float(exp_wr) * 100:.0f}%`")
                    if ctx_n > 0:
                        parts.append(f"n={ctx_n}")
                    if ctx_score is not None:
                        parts.append(f"score `{float(ctx_score):.2f}`")

                    message += "🧠 *Ctx Policy:* " + " • ".join(parts) + "\n"
                except Exception:
                    pass

            message += f"📌 *Status:* {status_label}"
            if age_str:
                message += f" • {age_str}"
            message += "\n"

            # P&L for exited signals
            if status == "exited":
                pnl = float(found.get("pnl", 0.0) or 0.0)
                pnl_emoji, pnl_str = format_pnl(pnl)
                exit_reason = safe_label(str(found.get("exit_reason", "") or ""))
                message += f"{pnl_emoji} *P&L:* {pnl_str}"
                if exit_reason:
                    message += f" ({exit_reason})"
                message += "\n"

            message += f"🆔 `{sig_id[:16]}…`\n"

            # Check if context should be shown (based on prefs or explicit expand request)
            show_context = self.prefs.signal_detail_expanded if self.prefs else False
            
            # Check if this is an explicit context expand request (via callback)
            user_data = context.user_data if hasattr(context, "user_data") else {}
            force_expand = user_data.get("signal_context_expanded", False)
            if force_expand:
                show_context = True
                # Reset the flag
                if hasattr(context, "user_data"):
                    context.user_data["signal_context_expanded"] = False

            # Optional enhanced context (shown based on signal_detail_expanded pref or explicit request)
            regime = signal.get("regime", {}) or {}
            mtf = signal.get("mtf_analysis", {}) or {}
            vwap = signal.get("vwap_data", {}) or {}
            flow = signal.get("order_flow", {}) or {}
            quality = signal.get("quality_score", {}) or {}
            sr_levels = signal.get("sr_levels", {}) or {}

            # Check if there's any context to show
            has_context = bool(
                quality or 
                (regime and regime.get("regime")) or 
                mtf.get("alignment") or 
                (vwap and vwap.get("vwap")) or 
                (flow and flow.get("recent_trend")) or 
                sr_levels
            )

            if show_context and has_context:
                context_lines = []

                # Quality metrics (trader-facing labels)
                if quality:
                    q_parts = []
                    if "quality_score" in quality:
                        q_parts.append(f"Score: {float(quality.get('quality_score', 0.0)):.2f}")
                    if "confluence_score" in quality:
                        q_parts.append(f"Confluence: {float(quality.get('confluence_score', 0.0)):.2f}")
                    if "historical_wr" in quality:
                        q_parts.append(f"Historical WR: {float(quality.get('historical_wr', 0.0)):.0%}")
                    if q_parts:
                        context_lines.append("🧠 *Quality:* " + " • ".join(q_parts))

                # Regime context
                if regime and regime.get("regime"):
                    r_regime = str(regime.get("regime", "")).replace("_", " ").title()
                    r_vol = str(regime.get("volatility", "")).title()
                    r_session = str(regime.get("session", "")).replace("_", " ").title()
                    context_lines.append(f"🧭 *Regime:* {r_regime} | {r_vol} Vol | {r_session}")

                # MTF alignment
                alignment = mtf.get("alignment")
                if alignment:
                    mtf_score = mtf.get("alignment_score")
                    mtf_str = f"🧩 *MTF:* {alignment.title()}"
                    if mtf_score is not None:
                        mtf_str += f" ({float(mtf_score):.2f})"
                    context_lines.append(mtf_str)

                # VWAP position
                if vwap and vwap.get("vwap"):
                    vwap_val = float(vwap.get("vwap", 0.0))
                    dist_pct = vwap.get("distance_pct")
                    vwap_str = f"📍 *VWAP:* ${vwap_val:.2f}"
                    if dist_pct is not None:
                        vwap_str += f" ({float(dist_pct):+.2f}%)"
                    context_lines.append(vwap_str)

                # Order flow
                if flow and flow.get("recent_trend"):
                    flow_trend = str(flow.get("recent_trend", "")).title()
                    net = flow.get("net_pressure")
                    flow_str = f"🌊 *Flow:* {flow_trend}"
                    if net is not None:
                        flow_str += f" ({float(net):+.2f})"
                    context_lines.append(flow_str)

                # S/R levels
                if sr_levels:
                    sup = sr_levels.get("strongest_support")
                    res = sr_levels.get("strongest_resistance")
                    if sup or res:
                        lvl_parts = []
                        if sup:
                            lvl_parts.append(f"Sup: ${float(sup):.2f}")
                        if res:
                            lvl_parts.append(f"Res: ${float(res):.2f}")
                        context_lines.append("🧱 *Levels:* " + " | ".join(lvl_parts))

                if context_lines:
                    message += "\n" + "\n".join(context_lines) + "\n"

            # Keyboard with chart, context, and navigation
            keyboard = []
            
            # Row 1: Chart + Context (if context is available and hidden)
            row1 = []
            if sig_id and self.chart_generator:
                row1.append(InlineKeyboardButton("📊 Chart", callback_data=f"signal_chart_{sig_id[:16]}"))
            if has_context and not show_context:
                row1.append(InlineKeyboardButton("🧠 Context", callback_data=f"signal_context_{sig_id[:16]}"))
            if row1:
                keyboard.append(row1)
            
            # Row 2: Signals navigation
            keyboard.append([
                InlineKeyboardButton("🔔 Signals", callback_data="signals"),
                InlineKeyboardButton("📊 Active", callback_data="active_trades"),
            ])
            keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="start")])
            await self._send_message_or_edit(update, context, message, reply_markup=InlineKeyboardMarkup(keyboard))

        except Exception as e:
            logger.error(f"Error handling signal detail: {e}", exc_info=True)
            await self._send_message_or_edit(
                update,
                context,
                f"❌ *Error*\n\n`{str(e)}`",
                reply_markup=self._get_back_to_menu_button(),
            )

    async def _handle_signal_chart(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        signal_id_prefix: str,
    ):
        """Handle signal chart viewing with historical data fetch and exit chart support."""
        if not await self._check_authorized(update):
            if update.callback_query:
                await update.callback_query.edit_message_text("❌ Unauthorized access")
            else:
                await update.message.reply_text("❌ Unauthorized access")
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            if not self.chart_generator:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "❌ Chart generation not available. matplotlib may not be installed.",
                    reply_markup=reply_markup
                )
                return
            
            # Find signal by ID
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *Signal not found*\n\n"
                    "The signals file doesn't exist.",
                    reply_markup=reply_markup
                )
                return
            
            signal_data = None
            with open(signals_file) as f:
                for line in f:
                    try:
                        sig_data = json.loads(line.strip())
                        sig_id = sig_data.get("signal_id", "")
                        if sig_id.startswith(signal_id_prefix):
                            signal_data = sig_data
                            break
                    except json.JSONDecodeError:
                        continue
            
            if not signal_data:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *Signal not found*\n\n"
                    "The requested signal could not be found in the signals file.",
                    reply_markup=reply_markup
                )
                return
            
            signal = signal_data.get("signal", {})
            status = signal_data.get("status", "generated")
            symbol = signal.get("symbol", "MNQ")
            
            # Fetch historical data around signal time for chart rendering
            buffer_data = pd.DataFrame()
            try:
                signal_ts = signal_data.get("timestamp") or signal.get("timestamp")
                if signal_ts:
                    from pearlalgo.utils.paths import parse_utc_timestamp
                    signal_time = parse_utc_timestamp(str(signal_ts))
                    
                    # Fetch enough history for meaningful context (>= 6h requested).
                    # We include a small forward window so the chart also shows immediate post-signal behavior.
                    start_time = signal_time - timedelta(hours=6)
                    end_time = min(signal_time + timedelta(hours=1), datetime.now(timezone.utc))
                    
                    data_provider = self._get_data_provider()
                    if data_provider is not None:
                        try:
                            loop = asyncio.get_running_loop()
                            buffer_data = await asyncio.wait_for(
                                loop.run_in_executor(
                                    None,
                                    lambda: data_provider.fetch_historical(
                                        symbol=symbol,
                                        start=start_time,
                                        end=end_time,
                                        timeframe="5m",
                                    ),
                                ),
                                timeout=30.0,
                            )
                            if buffer_data is not None and not buffer_data.empty:
                                logger.info(f"Fetched {len(buffer_data)} bars for signal chart")
                        except asyncio.TimeoutError:
                            logger.warning("Timeout fetching historical data for signal chart")
                        except Exception as e:
                            logger.warning(f"Could not fetch historical data for signal chart: {e}")
            except Exception as e:
                logger.warning(f"Error preparing historical fetch for signal chart: {e}")
            
            # Generate chart based on signal status
            chart_path = None
            caption = ""
            
            if status == "exited":
                # Exited signal: show exit chart with PnL
                exit_price = float(signal_data.get("exit_price", 0.0) or 0.0)
                exit_reason = safe_label(str(signal_data.get("exit_reason", "unknown") or "unknown"))
                pnl = float(signal_data.get("pnl", 0.0) or 0.0)
                is_win = signal_data.get("is_win", pnl > 0)
                
                sig_type = safe_label(str(signal.get('type', 'signal')))
                sig_dir = str(signal.get('direction', '')).upper()
                
                if exit_price > 0:
                    chart_path = self.chart_generator.generate_exit_chart(
                        signal=signal,
                        exit_price=exit_price,
                        exit_reason=exit_reason,
                        pnl=pnl,
                        buffer_data=buffer_data if buffer_data is not None else pd.DataFrame(),
                        symbol=symbol,
                    )
                    result_emoji = "✅" if is_win else "❌"
                    caption = (
                        f"{result_emoji} {sig_type} {sig_dir} | "
                        f"Exit: {exit_reason} | PnL: ${pnl:+.2f}"
                    )
                else:
                    # Fallback to entry chart if exit_price missing
                    chart_path = self.chart_generator.generate_entry_chart(
                        signal, buffer_data if buffer_data is not None else pd.DataFrame(), symbol
                    )
                    caption = f"📊 {sig_type} {sig_dir} (exited)"
            else:
                # Entry or active signal: show entry chart
                chart_path = self.chart_generator.generate_entry_chart(
                    signal, buffer_data if buffer_data is not None else pd.DataFrame(), symbol
                )
                sig_type = safe_label(str(signal.get('type', 'signal')))
                sig_dir = str(signal.get('direction', '')).upper()
                status_emoji = "🎯" if status == "entered" else "📊"
                caption = f"{status_emoji} {sig_type} {sig_dir}"
            
            if chart_path and chart_path.exists():
                try:
                    # Send chart
                    with open(chart_path, 'rb') as photo:
                        if update.callback_query:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=photo,
                                caption=caption
                            )
                        else:
                            await update.message.reply_photo(
                                photo=photo,
                                caption=caption
                            )
                    # Clean up
                    try:
                        chart_path.unlink()
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"Error sending chart: {e}", exc_info=True)
                    await self._send_message_or_edit(
                        update, context,
                        "📊 *Chart Delivery Failed*\n\n"
                        "Chart was generated but couldn't be sent.\n\n"
                        "💡 Try again or check /data_quality"
                    )
            else:
                await self._send_message_or_edit(
                    update, context,
                    "📊 *Chart Unavailable*\n\n"
                    "Could not generate chart for this signal.\n\n"
                    "*Possible reasons:*\n"
                    "• Historical data not available\n"
                    "• Data still loading\n\n"
                    "💡 Try /data_quality to check data status"
                )
                
        except Exception as e:
            logger.error(f"Error handling signal chart: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                "📊 *Chart Unavailable*\n\n"
                "Something went wrong loading the chart.\n\n"
                "💡 Try again or check /data_quality"
            )
    
    def _get_main_menu_buttons(
        self,
        agent_running: bool = False,
        gateway_running: bool = False,
        gateway_api_ready: Optional[bool] = None,
    ) -> InlineKeyboardMarkup:
        """
        Generate main menu inline keyboard buttons (clean, button-first UX).

        Layout (calm-minimal, but with core tools exposed):
        - Row 1: Agent control + Gateway status
        - Row 2: Last signal + Active trades
        - Row 3: Activity + Data quality
        - Row 4: Signals + Performance + Review
        - Row 5: Backtest + Reports
        - Row 6: Settings (advanced tools: Help/Config/Claude live here)

        Gateway indicator tri-state:
        - ✅ running and API ready
        - 🟡 running but API not ready (authenticating/2FA)
        - ❌ stopped
        """
        keyboard: List[List[InlineKeyboardButton]] = []
        
        # Row 1: Agent control (Gateway status lives in 📡 Health)
        if agent_running:
            keyboard.append([
                InlineKeyboardButton("⏹️ Stop", callback_data='stop_agent'),
                InlineKeyboardButton("🔄 Restart", callback_data='restart_agent'),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("▶️ Start", callback_data='start_agent'),
            ])

        # Row 2: Primary drill-down (fastest operator actions)
        keyboard.append([
            InlineKeyboardButton("📟 Status", callback_data="status"),
            InlineKeyboardButton("🔄", callback_data="status_refresh"),  # Quick refresh (text only)
            InlineKeyboardButton("📡 Health", callback_data="health_menu"),
            InlineKeyboardButton("🧠 Review", callback_data="strategy_review"),
        ])


        # Row 3: Signals & Trades (primary workflow)
        keyboard.append([
            InlineKeyboardButton("🎯 Signals & Trades", callback_data="signals"),
            InlineKeyboardButton("📊 Performance", callback_data="performance"),
        ])


        # Row 4: Tools
        keyboard.append([
            InlineKeyboardButton("📉 Backtest", callback_data="backtest"),
            InlineKeyboardButton("📂 Reports", callback_data="reports"),
        ])

        # Row 5: AI + Settings (keep top-level, avoid menu-in-menu)
        if ANTHROPIC_AVAILABLE:
            keyboard.append([
                InlineKeyboardButton("🤖 AI Hub", callback_data="claude_hub"),
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            ])
        else:
            keyboard.append([InlineKeyboardButton("⚙️ Settings", callback_data="settings")])
        
        return InlineKeyboardMarkup(keyboard)
    
    def _get_gateway_buttons(self, gateway_running: bool = False) -> InlineKeyboardMarkup:
        """Generate gateway control buttons."""
        keyboard = []
        
        # Primary gateway actions
        if gateway_running:
            keyboard.append([
                InlineKeyboardButton("⏹️ Stop Gateway", callback_data='stop_gateway'),
                InlineKeyboardButton("🔄 Refresh", callback_data='gateway_status'),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("▶️ Start Gateway", callback_data='start_gateway'),
                InlineKeyboardButton("🔄 Refresh", callback_data='gateway_status'),
            ])
        
        # Navigation
        keyboard.append([
            InlineKeyboardButton("🏠 Menu", callback_data='start'),
            InlineKeyboardButton("📊 Status", callback_data='status'),
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    def _get_back_to_menu_button(self, include_refresh: bool = False) -> InlineKeyboardMarkup:
        """Generate navigation buttons - always returns to main menu (/start)."""
        keyboard = []
        if include_refresh:
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh", callback_data='status'),
                InlineKeyboardButton("🏠 Menu", callback_data='start'),
            ])
        else:
            keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data='start')])
        return InlineKeyboardMarkup(keyboard)
    
    def _get_signals_buttons(self, has_signals: bool = True) -> InlineKeyboardMarkup:
        """Generate buttons for signals view."""
        keyboard = []
        if has_signals:
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh", callback_data='signals'),
            ])
        keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data='start')])
        return InlineKeyboardMarkup(keyboard)

    def _get_confirm_buttons(
        self,
        action: str,
        cancel_callback: str = "data_quality",
    ) -> InlineKeyboardMarkup:
        """Generic confirm buttons for dangerous operations."""
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"do:{action}"),
                InlineKeyboardButton("❌ Cancel", callback_data=cancel_callback),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _format_confirm_message(self, action: str) -> str:
        """Format confirm message for a dangerous operation."""
        if action == "restart_agent":
            return (
                "⚠️ *Confirm: Restart Agent*\n\n"
                "This will *stop* and then *start* the NQ Agent service.\n"
                "You may miss signals during the restart.\n\n"
                "Proceed?"
            )
        if action == "restart_gateway":
            return (
                "⚠️ *Confirm: Restart Gateway*\n\n"
                "This will *stop* and then *start* the IBKR Gateway.\n"
                "The gateway may take 60–120s to become API-ready.\n\n"
                "Proceed?"
            )
        return (
            "⚠️ *Confirm Action*\n\n"
            f"Proceed with: `{action}`?"
        )

    async def _run_confirmed_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
    ) -> None:
        """Execute a confirmed operation and report results."""
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        if action == "restart_agent":
            await self._send_message_or_edit(
                update,
                context,
                "🔄 Restarting *Agent*...\n\n"
                "Stopping service, then starting again. This should take ~10–20s.",
                reply_markup=None,
            )
            stop_result = await self.service_controller.stop_agent()
            await asyncio.sleep(2)
            start_result = await self.service_controller.start_agent(background=True)

            message = "🔄 *Restart Agent Complete*\n\n"
            message += f"*Stop:* {stop_result.get('message', 'N/A')}\n"
            message += f"*Start:* {start_result.get('message', 'N/A')}\n"
            if start_result.get("details"):
                message += f"\n{start_result['details']}"

            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ])
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            return

        if action == "restart_gateway":
            await self._send_message_or_edit(
                update,
                context,
                "🔄 Restarting *Gateway*...\n\n"
                "Stopping gateway, then starting again. This can take up to ~2 minutes.",
                reply_markup=None,
            )
            stop_result = await self.service_controller.stop_gateway()
            await asyncio.sleep(2)
            start_result = await self.service_controller.start_gateway()

            message = "🔄 *Restart Gateway Complete*\n\n"
            message += f"*Stop:* {stop_result.get('message', 'N/A')}\n"
            message += f"*Start:* {start_result.get('message', 'N/A')}\n"
            if start_result.get("details"):
                message += f"\n{start_result['details']}"

            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔌 Gateway Status", callback_data="gateway_status"),
                    InlineKeyboardButton("🏠 Main Menu", callback_data="start"),
                ],
            ])
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            return

        await self._send_message_or_edit(
            update,
            context,
            f"❌ Unknown confirmed action: `{action}`",
            reply_markup=self._get_back_to_menu_button(),
        )
    
    async def _send_message_or_edit(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        parse_mode: str = "Markdown",
    ):
        """
        Helper to send message for commands or edit for callbacks.
        
        Includes Markdown parse fallback: if Markdown parsing fails, retries
        as plain text to ensure the UI never fails silently due to formatting.
        """
        async def _try_send(text: str, mode: str | None) -> bool:
            """Try to send/edit with given parse mode. Returns True on success."""
            try:
                if update.callback_query:
                    try:
                        await update.callback_query.edit_message_text(
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode=mode,
                        )
                        logger.debug(f"Edited message with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows")
                        return True
                    except Exception as e:
                        error_str = str(e).lower()
                        # Check for Markdown parsing errors
                        if "parse entities" in error_str or "can't parse" in error_str:
                            raise  # Propagate to trigger fallback
                        # If edit fails for other reasons (e.g., message unchanged), send new message
                        logger.debug(f"Could not edit message, sending new: {e}")
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode=mode,
                        )
                        logger.debug(f"Sent new message with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows")
                        return True
                else:
                    if update.message:
                        await update.message.reply_text(
                            text,
                            reply_markup=reply_markup,
                            parse_mode=mode,
                        )
                        logger.info(f"Sent message with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows to chat {update.effective_chat.id}")
                        return True
                    else:
                        # Fallback: send directly via bot
                        logger.warning("No update.message, sending directly via bot")
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode=mode,
                        )
                        logger.info(f"Sent message directly with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows")
                        return True
            except Exception as e:
                error_str = str(e).lower()
                if "parse entities" in error_str or "can't parse" in error_str:
                    raise  # Propagate Markdown errors for fallback handling
                # Safety: if reply_markup is invalid (e.g., callback_data too long), retry without buttons.
                if reply_markup is not None and ("button_data_invalid" in error_str or "reply_markup" in error_str):
                    logger.warning(f"Reply markup rejected by Telegram, retrying without buttons: {e}")
                    try:
                        if update.callback_query:
                            try:
                                await update.callback_query.edit_message_text(text=text, parse_mode=mode)
                                return True
                            except Exception:
                                await context.bot.send_message(
                                    chat_id=update.effective_chat.id,
                                    text=text,
                                    parse_mode=mode,
                                )
                                return True
                        else:
                            if update.message:
                                await update.message.reply_text(text, parse_mode=mode)
                                return True
                            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode=mode)
                            return True
                    except Exception as e2:
                        logger.error(f"Retry without buttons also failed: {e2}", exc_info=True)
                logger.error(f"Error sending message: {e}", exc_info=True)
                return False
            return False

        try:
            # First attempt with requested parse mode
            if await _try_send(message, parse_mode):
                return
        except Exception as e:
            error_str = str(e).lower()
            if "parse entities" in error_str or "can't parse" in error_str:
                # Markdown parsing error - fallback to plain text
                logger.warning(f"Markdown parsing error, retrying as plain text: {e}")
                try:
                    # Strip Markdown formatting and retry
                    plain_message = message.replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')
                    if await _try_send(plain_message, None):
                        return
                except Exception as e2:
                    logger.error(f"Plain text fallback also failed: {e2}")
        
        # Final fallback: try to send error message without markup
        try:
            error_msg = f"❌ Error sending message (see logs for details)"
            if update.message:
                await update.message.reply_text(error_msg)
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=error_msg)
        except Exception as e2:
            logger.error(f"Could not send error message: {e2}")
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks."""
        query = update.callback_query
        await query.answer()
        
        if not await self._check_authorized(update):
            await query.edit_message_text("❌ Unauthorized access")
            return
        
        callback_data = query.data
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        if callback_data == 'status':
            await self._handle_status(update, context)
        elif callback_data == 'status_refresh':
            await self._handle_status_refresh(update, context)
        elif callback_data == 'performance':
            await self._handle_performance(update, context)
        elif callback_data.startswith("performance:"):
            # Lookback selection like "performance:7d"
            await self._handle_performance(update, context)
        elif callback_data.startswith("performance_export:"):
            kind = callback_data.split("performance_export:", 1)[1].strip()
            await self._handle_performance_export(update, context, kind)
        elif callback_data == 'signals':
            await self._handle_signals(update, context)
        elif callback_data.startswith("signal_detail:"):
            # Signal detail view by ID prefix
            sig_id_prefix = callback_data.split("signal_detail:", 1)[1].strip()
            # Fake the message text for the handler
            if update.callback_query:
                update.callback_query.message.text = f"/signal {sig_id_prefix}"
            await self._handle_signal_detail(update, context)
        elif callback_data.startswith("signal_export:"):
            # Export signal as JSON file
            sig_id_prefix = callback_data.split("signal_export:", 1)[1].strip()
            await self._handle_signal_export(update, context, sig_id_prefix)
        elif callback_data.startswith("signals:page:"):
            action = callback_data.split("signals:page:", 1)[1].strip()
            if hasattr(context, "user_data"):
                try:
                    cur = int(context.user_data.get("signals_page", 0) or 0)
                except Exception:
                    cur = 0
                if action == "older":
                    cur += 1
                elif action == "newer":
                    cur = max(0, cur - 1)
                elif action == "newest":
                    cur = 0
                context.user_data["signals_page"] = cur
            await self._handle_signals(update, context)
        elif callback_data.startswith("signals:setdir:"):
            if hasattr(context, "user_data"):
                context.user_data["signals_dir"] = callback_data.split("signals:setdir:", 1)[1]
                context.user_data["signals_page"] = 0
            await self._handle_signals(update, context)
        elif callback_data.startswith("signals:setconf:"):
            if hasattr(context, "user_data"):
                raw = callback_data.split("signals:setconf:", 1)[1]
                try:
                    context.user_data["signals_min_conf"] = float(raw)
                except Exception:
                    context.user_data["signals_min_conf"] = 0.0
                context.user_data["signals_page"] = 0
            await self._handle_signals(update, context)
        elif callback_data.startswith("signals:settype:"):
            if hasattr(context, "user_data"):
                context.user_data["signals_type"] = callback_data.split("signals:settype:", 1)[1]
                context.user_data["signals_page"] = 0
            await self._handle_signals(update, context)
        elif callback_data == "signals:noop":
            # Noop callback for UI separator buttons - just acknowledge
            pass
        elif callback_data == 'config':
            await self._handle_config(update, context)
        elif callback_data == 'health_menu':
            await self._handle_health_menu(update, context)
        elif callback_data == 'health':
            await self._handle_health(update, context)
        elif callback_data == 'activity':
            await self._handle_activity(update, context)
        elif callback_data == 'data_quality':
            await self._handle_data_quality(update, context)
        elif callback_data == 'data_quality:diagnose':
            await self._handle_data_quality(update, context, diagnose=True)
        elif callback_data == 'diagnostics':
            await self._handle_diagnostics(update, context)
        elif callback_data == 'doctor':
            await self._handle_doctor(update, context)
        elif callback_data == 'brain':
            await self._handle_brain(update, context)
        elif callback_data == 'start_agent':
            await self._handle_start_agent(update, context)
        elif callback_data == 'stop_agent':
            await self._handle_stop_agent(update, context)
        elif callback_data == 'gateway_status':
            await self._handle_gateway_status(update, context)
        elif callback_data == 'start_gateway':
            await self._handle_start_gateway(update, context)
        elif callback_data == 'stop_gateway':
            await self._handle_stop_gateway(update, context)
        elif callback_data == 'restart_agent':
            # Route menu restart button through confirm flow
            message = self._format_confirm_message("restart_agent")
            reply_markup = self._get_confirm_buttons("restart_agent", cancel_callback="data_quality")
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
        elif callback_data == 'start' or callback_data == 'main_menu':
            # Main menu - always return to start
            await self._handle_start(update, context)
        elif callback_data == 'help':
            await self._handle_help(update, context)
        elif callback_data == 'glossary':
            await self._handle_glossary(update, context)
        elif callback_data.startswith('glossary_'):
            # Handle glossary drill-down buttons
            term = callback_data.replace('glossary_', '')
            # Simulate args for the glossary handler
            context.args = [term]
            await self._handle_glossary(update, context)
            context.args = []  # Reset
        elif callback_data == 'settings':
            await self._handle_settings(update, context)
        elif callback_data.startswith('settings:toggle:'):
            # Toggle a boolean setting
            key = callback_data.replace('settings:toggle:', '')
            if key in TelegramPrefs.DEFAULTS:
                self.prefs.toggle(key)
                await self._render_settings_menu(update, context)
        elif callback_data == 'settings:snooze':
            # Toggle snooze for non-critical alerts
            if self.prefs.snooze_noncritical_alerts:
                self.prefs.disable_snooze()
            else:
                self.prefs.enable_snooze(hours=1.0)
            await self._render_settings_menu(update, context)
        elif callback_data == 'settings:reset':
            # Reset all settings to defaults
            self.prefs.reset()
            await self._render_settings_menu(update, context)
        elif callback_data == 'settings:purge_test':
            # Purge test signals (inline version)
            await self._handle_purge_test_callback(update, context)
        elif callback_data == 'chart':
            await self._handle_chart(update, context)
        elif callback_data == 'chart_12h':
            context.args = ['12']
            await self._handle_chart(update, context)
            context.args = []
        elif callback_data == 'last_signal':
            # Backwards-compat: older menus had a Last Signal button; route to Signals & Trades.
            await self._handle_signals(update, context)
        elif callback_data == 'active_trades':
            await self._handle_active_trades(update, context)
        elif callback_data == 'test_signal':
            await self._handle_test_signal(update, context)
        elif callback_data == 'backtest':
            await self._handle_backtest(update, context)
        elif callback_data == 'reports':
            await self._handle_backtest_reports(update, context)
        elif callback_data == "strategy_review:show":
            await self._render_strategy_review_cached(update, context)
        elif callback_data == "strategy_review" or callback_data == "strategy_review:refresh":
            await self._handle_strategy_review(update, context)
        elif callback_data == "strategy_review:more":
            await self._render_strategy_review_more_menu(update, context)
        elif callback_data == "strategy_review:export":
            await self._handle_strategy_review_export(update, context)
        elif callback_data == "strategy_review:config_patch":
            await self._handle_strategy_review_config_patch(update, context)
        elif callback_data == "strategy_review:config_patch:do":
            await self._handle_strategy_review_config_patch_do(update, context)
        elif callback_data == "strategy_review:variant_backtest":
            await self._handle_strategy_review_variant_backtest(update, context)
        elif callback_data == "strategy_review:apply_candidate":
            await self._handle_strategy_review_apply_candidate(update, context)
        elif callback_data == "strategy_review:apply_candidate:do":
            await self._handle_strategy_review_apply_candidate_do(update, context, dry_run=False)
        elif callback_data == "strategy_review:apply_candidate:dry":
            await self._handle_strategy_review_apply_candidate_do(update, context, dry_run=True)
        elif callback_data == "strategy_review:discuss":
            await self._handle_strategy_review_discuss(update, context)
        elif callback_data == "strategy_review:autofix":
            await self._handle_strategy_review_autofix(update, context)
        elif callback_data.startswith("strategy_review:variant_weeks:"):
            try:
                w = int(callback_data.split("strategy_review:variant_weeks:", 1)[1])
            except Exception:
                w = 2
            if w not in (1, 2, 4):
                w = 2
            if hasattr(context, "user_data"):
                context.user_data["strategy_review_variant_weeks"] = w
            await self._render_strategy_review_cached(update, context)
        elif callback_data.startswith("strategy_review:lookback:"):
            try:
                lb = int(callback_data.split("strategy_review:lookback:", 1)[1])
            except Exception:
                lb = 24
            lb = 24 if lb <= 24 else 168
            if hasattr(context, "user_data"):
                context.user_data["strategy_review_lookback_hours"] = lb
            await self._handle_strategy_review(update, context)
        elif callback_data.startswith('reports_page:'):
            try:
                page = int(callback_data.split(':')[1])
            except Exception:
                page = 0
            await self._handle_backtest_reports(update, context, page=page)
        elif callback_data.startswith("report_detail_k:"):
            report_key = callback_data.split("report_detail_k:", 1)[1].strip()
            report_name = self._resolve_report_name_by_key(report_key)
            if not report_name:
                await self._send_message_or_edit(
                    update,
                    context,
                    "❌ Report not found (stale button). Tap *Reports* to refresh.",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton("📂 Reports", callback_data="reports")],
                            [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                        ]
                    ),
                )
                return
            await self._handle_report_detail(update, context, report_name)
        elif callback_data.startswith('report_detail:'):
            report_name = callback_data.split(':', 1)[1]
            await self._handle_report_detail(update, context, report_name)
        elif callback_data.startswith("report_artifact_k:"):
            parts = callback_data.split(":")
            if len(parts) >= 3:
                report_key = parts[1]
                artifact = parts[2]
                report_name = self._resolve_report_name_by_key(report_key)
                if not report_name:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="❌ Report not found (stale button). Tap Reports to refresh.",
                    )
                    return
                await self._handle_report_artifact(update, context, report_name, artifact)
        elif callback_data.startswith('report_artifact:'):
            parts = callback_data.split(':')
            if len(parts) >= 3:
                report_name = parts[1]
                artifact = parts[2]
                await self._handle_report_artifact(update, context, report_name, artifact)
        elif callback_data == 'noop':
            # No-op callback for UI elements (page counter, etc.)
            pass
        elif callback_data.startswith("backtest_export:"):
            kind = callback_data.split("backtest_export:", 1)[1].strip()
            await self._handle_backtest_export(update, context, kind)
        elif callback_data.startswith('backtest_setmode_'):
            # Toggle backtest mode (5m recommended vs 1m legacy)
            mode = callback_data.replace('backtest_setmode_', '')
            if mode not in ("5m", "1m"):
                mode = "5m"
            if hasattr(context, "user_data"):
                context.user_data["backtest_mode"] = mode
            await self._handle_backtest(update, context, weeks=None)
        elif callback_data.startswith("backtest_setpos_"):
            # Set position size (contracts) for backtest simulation
            try:
                pos = int(callback_data.replace("backtest_setpos_", ""))
            except Exception:
                pos = 5
            if pos not in (1, 5, 10):
                pos = 5
            if hasattr(context, "user_data"):
                context.user_data["backtest_contracts"] = pos
            await self._handle_backtest(update, context, weeks=None)
        elif callback_data.startswith("backtest_setslip_"):
            # Set slippage ticks for backtest simulation
            raw = callback_data.replace("backtest_setslip_", "")
            try:
                slip = float(raw)
            except Exception:
                slip = 0.5
            if slip not in (0.5, 1.0):
                slip = 0.5
            if hasattr(context, "user_data"):
                context.user_data["backtest_slippage_ticks"] = slip
            await self._handle_backtest(update, context, weeks=None)
        elif callback_data.startswith("backtest_setsymbol_"):
            # Set symbol (MNQ or NQ) for backtest simulation
            symbol = callback_data.replace("backtest_setsymbol_", "")
            if symbol not in ("MNQ", "NQ"):
                symbol = "MNQ"
            if hasattr(context, "user_data"):
                context.user_data["backtest_symbol"] = symbol
            await self._handle_backtest(update, context, weeks=None)
        elif callback_data.startswith("backtest_setmaxpos_"):
            # Set max concurrent positions for backtest trade simulation
            raw = callback_data.replace("backtest_setmaxpos_", "")
            try:
                max_pos = int(raw)
            except Exception:
                max_pos = 1
            if max_pos not in (1, 2, 3):
                max_pos = 1
            if hasattr(context, "user_data"):
                context.user_data["backtest_max_positions"] = max_pos
            await self._handle_backtest(update, context, weeks=None)
        elif callback_data == 'backtest_clearcache':
            # Clear historical data cache to force re-fetch
            try:
                cache_dir = self._historical_cache_dir
                deleted_count = 0
                if cache_dir.exists():
                    for cache_file in cache_dir.glob("*.parquet"):
                        try:
                            cache_file.unlink()
                            deleted_count += 1
                        except Exception:
                            pass
                await self._send_message_or_edit(
                    update, context,
                    f"🗑️ *Cache Cleared*\n\n"
                    f"Deleted {deleted_count} cached data file(s).\n"
                    f"Next backtest will fetch fresh data from IBKR.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📊 Run Backtest", callback_data='backtest')],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data='start')],
                    ])
                )
            except Exception as e:
                await self._send_message_or_edit(
                    update, context,
                    f"❌ Error clearing cache: {e}",
                    reply_markup=self._get_back_to_menu_button()
                )
        elif callback_data.startswith('backtest_'):
            # Handle backtest duration selection (backtest_1w, backtest_2w, etc.)
            try:
                weeks_str = callback_data.replace('backtest_', '').replace('w', '')
                weeks = int(weeks_str)
                if 1 <= weeks <= 6:
                    await self._handle_backtest(update, context, weeks=weeks)
                else:
                    await self._send_message_or_edit(
                        update, context,
                        f"❌ Invalid duration: {weeks} weeks. Please select 1-6 weeks.",
                        reply_markup=self._get_back_to_menu_button()
                    )
            except ValueError:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Invalid backtest duration format.",
                    reply_markup=self._get_back_to_menu_button()
                )
        elif callback_data.startswith('signal_chart_'):
            # Handle signal chart viewing
            signal_id_prefix = callback_data.replace('signal_chart_', '')
            await self._handle_signal_chart(update, context, signal_id_prefix)
        elif callback_data.startswith('signal_detail_'):
            signal_id_prefix = callback_data.replace('signal_detail_', '')
            await self._handle_signal_detail(update, context, signal_id_prefix)
        elif callback_data.startswith('signal_context_'):
            # Show signal detail with expanded context
            signal_id_prefix = callback_data.replace('signal_context_', '')
            if hasattr(context, "user_data"):
                context.user_data["signal_context_expanded"] = True
            await self._handle_signal_detail(update, context, signal_id_prefix)
        elif callback_data.startswith('confirm:'):
            action = callback_data.replace('confirm:', '', 1).strip()
            message = self._format_confirm_message(action)
            reply_markup = self._get_confirm_buttons(action, cancel_callback="data_quality")
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
        elif callback_data.startswith('do:'):
            action = callback_data.replace('do:', '', 1).strip()
            await self._run_confirmed_action(update, context, action)
        elif callback_data in ('pause', 'resume'):
            await query.edit_message_text(
                f"⚠️ {callback_data.title()} requires service integration.\n"
                "Use /stop_agent and /start_agent for full control."
            )
        # Claude hub callbacks
        elif callback_data == 'claude_hub':
            await self._handle_ai_hub(update, context)
        elif callback_data == 'claude_memory':
            await self._handle_claude_memory_view(update, context)
        elif callback_data == 'claude_memory_refresh':
            await self._handle_claude_memory_refresh(update, context)
        elif callback_data == 'claude_memory_clear':
            await self._handle_claude_memory_clear(update, context)
        elif callback_data == 'claude_chat_toggle':
            await self._handle_claude_chat_toggle(update, context)
        elif callback_data == 'claude_patch_wizard':
            await self._handle_claude_patch_wizard_start(update, context)
        elif callback_data == 'claude_wizard_auto':
            await self._handle_claude_wizard_auto_start(update, context)
        elif callback_data == 'claude_wizard_manual':
            await self._handle_claude_wizard_manual_start(update, context)
        elif callback_data == 'claude_reset':
            await self._handle_ai_reset(update, context)
        elif callback_data == 'claude_cancel':
            # Cancel any wizard state and return to hub
            if hasattr(context, "user_data"):
                context.user_data.pop("claude_wizard_state", None)
                context.user_data.pop("claude_wizard_task", None)
                context.user_data.pop("claude_wizard_files", None)
            await self._handle_ai_hub(update, context)
        elif callback_data.startswith('claude_file_toggle:'):
            # Toggle file selection in patch wizard
            filepath = callback_data.replace('claude_file_toggle:', '')
            await self._handle_claude_file_toggle(update, context, filepath)
        elif callback_data.startswith('claude_file_preview:'):
            # Preview a file in patch wizard
            filepath = callback_data.replace('claude_file_preview:', '')
            await self._handle_claude_file_preview(update, context, filepath)
        elif callback_data == 'claude_generate_patch':
            await self._handle_claude_generate_patch(update, context)
        elif callback_data == 'claude_refine_search':
            await self._handle_claude_refine_search(update, context)
        # Claude Monitor callbacks
        elif callback_data == 'claude_monitor_hub':
            await self._handle_claude_monitor_hub(update, context)
        elif callback_data == 'claude_monitor_start':
            await self._handle_claude_monitor_start(update, context)
        elif callback_data == 'claude_monitor_stop':
            await self._handle_claude_monitor_stop(update, context)
        elif callback_data == 'claude_analyze_now':
            await self._handle_analyze_now(update, context)
        elif callback_data == 'claude_analyze_signals':
            await self._handle_analyze_signals(update, context)
        elif callback_data == 'claude_analyze_system':
            await self._handle_analyze_system(update, context)
        elif callback_data == 'claude_analyze_market':
            await self._handle_analyze_market(update, context)
        elif callback_data == 'claude_suggest_config':
            await self._handle_suggest_config(update, context)
        elif callback_data == 'claude_suggestions':
            await self._handle_suggestions(update, context)
        elif callback_data.startswith("sug:"):
            await self._handle_suggestion_callback(update, context, callback_data)
        else:
            await query.edit_message_text(f"❌ Unknown action: {callback_data}")
    
    # ==========================================================================
    # EXECUTION CONTROL COMMANDS (ATS - Automated Trading System)
    # ==========================================================================
    
    async def _handle_arm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /arm command - Arm execution adapter for order placement.
        
        SAFETY: Requires authorized chat ID. Changes are persistent.
        """
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /arm command from {update.effective_user.id}")
        
        try:
            # Get execution status from state
            state = self.state_manager.load_state()
            execution_status = state.get("execution", {})
            
            if not execution_status.get("enabled", False):
                await update.message.reply_text(
                    "⚠️ *Execution Disabled*\n\n"
                    "Execution adapter is not enabled in config.\n"
                    "Set `execution.enabled: true` in `config/config.yaml` and restart.",
                    parse_mode="Markdown",
                )
                return
            
            if execution_status.get("armed", False):
                await update.message.reply_text(
                    "🔫 *Already Armed*\n\n"
                    "Execution adapter is already armed.\n"
                    "Use `/disarm` to disarm.",
                    parse_mode="Markdown",
                )
                return
            
            # Write arm command to a file that the service will pick up
            arm_file = self.state_dir / "arm_request.flag"
            arm_file.write_text(f"arm_requested_at={datetime.now(timezone.utc).isoformat()}")
            
            await update.message.reply_text(
                "🔫 *ARM REQUESTED*\n\n"
                "⚠️ The execution adapter will be armed on the next service cycle.\n\n"
                "This means:\n"
                "• Signals will trigger REAL orders\n"
                "• Bracket orders (entry + SL + TP) will be placed\n"
                "• Use `/disarm` to stop order placement\n"
                "• Use `/kill` to cancel all orders AND disarm\n\n"
                f"Mode: `{execution_status.get('mode', 'unknown')}`\n"
                f"Max positions: `{execution_status.get('max_positions', 'unknown')}`",
                parse_mode="Markdown",
            )
            
        except Exception as e:
            logger.error(f"Error handling /arm: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _handle_disarm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /disarm command - Disarm execution adapter.
        
        SAFETY: Immediately prevents new orders. Does NOT cancel existing orders.
        """
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /disarm command from {update.effective_user.id}")
        
        try:
            # Write disarm command to a file that the service will pick up
            disarm_file = self.state_dir / "disarm_request.flag"
            disarm_file.write_text(f"disarm_requested_at={datetime.now(timezone.utc).isoformat()}")
            
            # Remove arm file if present
            arm_file = self.state_dir / "arm_request.flag"
            if arm_file.exists():
                arm_file.unlink()
            
            await update.message.reply_text(
                "🔒 *DISARM REQUESTED*\n\n"
                "The execution adapter will be disarmed on the next service cycle.\n\n"
                "• No NEW orders will be placed\n"
                "• Existing orders will NOT be cancelled\n"
                "• Use `/kill` to cancel all orders",
                parse_mode="Markdown",
            )
            
        except Exception as e:
            logger.error(f"Error handling /disarm: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _handle_kill(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /kill command - Cancel all orders AND disarm execution.
        
        SAFETY: Emergency kill switch. Immediately disarms and cancels all orders.
        """
        if not await self._check_authorized(update):
            return
        
        logger.info(f"🚨 Received /kill command from {update.effective_user.id}")
        
        try:
            # Write kill command to a file that the service will pick up
            kill_file = self.state_dir / "kill_request.flag"
            kill_file.write_text(f"kill_requested_at={datetime.now(timezone.utc).isoformat()}")
            
            # Also write disarm
            disarm_file = self.state_dir / "disarm_request.flag"
            disarm_file.write_text(f"disarm_requested_at={datetime.now(timezone.utc).isoformat()}")
            
            # Remove arm file if present
            arm_file = self.state_dir / "arm_request.flag"
            if arm_file.exists():
                arm_file.unlink()
            
            await update.message.reply_text(
                "🚨 *KILL SWITCH ACTIVATED*\n\n"
                "Emergency shutdown requested:\n"
                "• Execution adapter will be disarmed\n"
                "• All open orders will be cancelled\n\n"
                "This will take effect on the next service cycle.",
                parse_mode="Markdown",
            )
            
        except Exception as e:
            logger.error(f"Error handling /kill: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _handle_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /positions command - Show current positions.
        
        Read-only command.
        """
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /positions command from {update.effective_user.id}")
        
        try:
            state = self.state_manager.load_state()
            execution_status = state.get("execution", {})
            
            if not execution_status.get("enabled", False):
                await update.message.reply_text(
                    "📊 *Positions*\n\n"
                    "Execution adapter is not enabled.\n"
                    "No positions tracked.",
                    parse_mode="Markdown",
                )
                return
            
            positions_count = execution_status.get("positions", 0)
            max_positions = execution_status.get("max_positions", 1)
            orders_today = execution_status.get("orders_today", 0)
            daily_pnl = execution_status.get("daily_pnl", 0.0)
            armed = execution_status.get("armed", False)
            mode = execution_status.get("mode", "unknown")
            connected = execution_status.get("connected", False)
            
            status_emoji = "🟢" if armed else "🔴"
            conn_emoji = "✅" if connected else "❌"
            
            message = (
                f"📊 *Positions & Execution Status*\n\n"
                f"{status_emoji} Armed: `{armed}`\n"
                f"{conn_emoji} Connected: `{connected}`\n"
                f"Mode: `{mode}`\n\n"
                f"*Positions:* `{positions_count}/{max_positions}`\n"
                f"*Orders Today:* `{orders_today}`\n"
                f"*Daily P&L:* `${daily_pnl:.2f}`\n"
            )
            
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error handling /positions: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _handle_policy(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /policy command - Show bandit policy status.
        
        Read-only command showing learning/policy state.
        """
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /policy command from {update.effective_user.id}")
        
        try:
            state = self.state_manager.load_state()
            learning_status = state.get("learning", {})
            
            if not learning_status.get("enabled", False):
                await update.message.reply_text(
                    "📊 *AI Policy*\n\n"
                    "Adaptive policy is not enabled.\n"
                    "Set `learning.enabled: true` in `config/config.yaml`.",
                    parse_mode="Markdown",
                )
                return
            
            mode = learning_status.get("mode", "shadow")
            threshold = learning_status.get("decision_threshold", 0.3)
            explore_rate = learning_status.get("explore_rate", 0.1)
            total_decisions = learning_status.get("total_decisions", 0)
            total_executes = learning_status.get("total_executes", 0)
            total_skips = learning_status.get("total_skips", 0)
            execute_rate = learning_status.get("execute_rate", 0.0)
            signal_types_tracked = learning_status.get("signal_types_tracked", 0)
            
            last_decision = learning_status.get("last_decision", {})
            
            mode_emoji = "👁️" if mode == "shadow" else "🔥"
            
            message = (
                f"📊 *AI Policy Status*\n\n"
                f"{mode_emoji} Mode: `{mode}`\n"
                f"Threshold: `{threshold}`\n"
                f"Explore Rate: `{explore_rate*100:.0f}%`\n\n"
                f"*Decisions:* `{total_decisions}`\n"
                f"• Execute: `{total_executes}` ({execute_rate*100:.0f}%)\n"
                f"• Skip: `{total_skips}`\n\n"
                f"*Signal Types Tracked:* `{signal_types_tracked}`\n"
            )
            
            if last_decision and last_decision.get("signal_type"):
                exec_emoji = "✅" if last_decision.get("execute") else "⏭️"
                message += (
                    f"\n*Last Decision:*\n"
                    f"Type: `{last_decision.get('signal_type')}`\n"
                    f"{exec_emoji} Execute: `{last_decision.get('execute')}`\n"
                    f"Score: `{last_decision.get('score', 0):.2f}`\n"
                    f"Reason: `{last_decision.get('reason', 'unknown')[:30]}`"
                )

            # Optional contextual learning status (learns by session/regime/time bucket)
            ctx_status = state.get("learning_contextual", {}) or {}
            if isinstance(ctx_status, dict) and ctx_status.get("enabled"):
                try:
                    ctx_mode = str(ctx_status.get("mode", "shadow"))
                    ctx_decisions = int(ctx_status.get("total_decisions", 0))
                    ctx_exec_rate = float(ctx_status.get("execute_rate", 0.0)) * 100.0
                    ctx_contexts = int(ctx_status.get("unique_contexts", 0))
                    ctx_types = int(ctx_status.get("signal_types_tracked", 0))
                    ctx_emoji = "👁️" if ctx_mode == "shadow" else "🔥"
                    message += (
                        f"\n\n🧠 *Contextual Policy*\n"
                        f"{ctx_emoji} Mode: `{ctx_mode}`\n"
                        f"Contexts: `{ctx_contexts}` • Types: `{ctx_types}`\n"
                        f"Decisions: `{ctx_decisions}` • Execute rate: `{ctx_exec_rate:.0f}%`"
                    )
                except Exception:
                    # Never let optional display break /policy
                    pass
            
            # Try to load policy state file for detailed signal type stats
            try:
                policy_state_file = self.state_dir / "policy_state.json"
                if policy_state_file.exists():
                    import json
                    with open(policy_state_file, 'r') as f:
                        policy_state = json.load(f)
                    
                    signal_types = policy_state.get("signal_types", {})
                    if signal_types:
                        message += "\n\n*Signal Type Performance:*\n"
                        
                        # Sort by sample count
                        sorted_types = sorted(
                            signal_types.items(),
                            key=lambda x: x[1].get("sample_count", 0),
                            reverse=True,
                        )
                        
                        for signal_type, stats in sorted_types[:5]:
                            wins = stats.get("wins", 0)
                            losses = stats.get("losses", 0)
                            win_rate = stats.get("win_rate", 0.5)
                            samples = stats.get("sample_count", 0)
                            
                            if samples > 0:
                                emoji = "🟢" if win_rate >= 0.5 else "🔴"
                                message += f"{emoji} `{signal_type}`: {wins}W/{losses}L ({win_rate:.0%})\n"
            except Exception as pe:
                logger.debug(f"Could not load policy state details: {pe}")
            
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error handling /policy: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

    async def _handle_diagnostics(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /diagnostics (alias /missed) - Show why signals were filtered/missed.
        
        Surfaces near-miss candidates, filter stats, and gate reasons from the most
        recent scan cycle so operators can see what's happening under the hood.
        """
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /diagnostics command from {update.effective_user.id}")
        
        try:
            state = self.state_manager.load_state()
            
            # Basic header
            message = "🔬 *Diagnostics / Near-Misses*\n\n"
            
            # Quiet reason (why agent is quiet)
            quiet_reason = state.get("quiet_reason")
            if quiet_reason:
                reason_display = {
                    "StrategySessionClosed": "📴 Session closed",
                    "FuturesMarketClosed": "🌙 Market closed",
                    "StaleData": "⏰ Data stale",
                    "DataGap": "📉 Data gap detected",
                    "NoData": "📭 Waiting for data",
                    "NoOpportunity": "👀 Scanning (no setups)",
                    "Active": "🟢 Active (signals generated)",
                }.get(quiet_reason, f"ℹ️ {quiet_reason}")
                message += f"*Status:* {reason_display}\n\n"
            
            # Signal diagnostics raw dict (if available)
            diag_raw = state.get("signal_diagnostics_raw", {})
            diag_str = state.get("signal_diagnostics")
            
            if diag_raw:
                raw = diag_raw.get("raw_signals", 0)
                valid = diag_raw.get("validated_signals", 0)
                message += f"*Signals:* {raw} raw → {valid} validated\n\n"
                
                # Filter breakdown
                filters = []
                if diag_raw.get("rejected_confidence", 0) > 0:
                    filters.append(f"❌ Confidence: {diag_raw['rejected_confidence']}")
                if diag_raw.get("rejected_risk_reward", 0) > 0:
                    filters.append(f"❌ R:R: {diag_raw['rejected_risk_reward']}")
                if diag_raw.get("rejected_order_book", 0) > 0:
                    filters.append(f"❌ Order Book: {diag_raw['rejected_order_book']}")
                if diag_raw.get("rejected_regime_filter", 0) > 0:
                    filters.append(f"❌ Regime: {diag_raw['rejected_regime_filter']}")
                if diag_raw.get("duplicates_filtered", 0) > 0:
                    filters.append(f"🔁 Duplicates: {diag_raw['duplicates_filtered']}")
                if diag_raw.get("rejected_quality_scorer", 0) > 0:
                    filters.append(f"📉 Quality: {diag_raw['rejected_quality_scorer']}")
                
                if filters:
                    message += "*Filters Applied:*\n"
                    for f in filters:
                        message += f"  {f}\n"
                    message += "\n"
                
                # Gate reasons (why scanner didn't even produce raw signals)
                gate_reasons = diag_raw.get("scanner_gate_reasons", [])
                if gate_reasons:
                    message += "*Gate Reasons (scanner):*\n"
                    for gr in gate_reasons[:5]:
                        message += f"  • `{str(gr)[:80]}`\n"
                    message += "\n"
            elif diag_str:
                message += f"*Last Diagnostics:*\n`{diag_str}`\n\n"
            else:
                message += "_No diagnostics available from last cycle._\n\n"
            
            # Near-misses (from recent session state if tracked)
            near_misses = state.get("near_misses", [])
            if near_misses:
                message += f"*Near-Misses ({len(near_misses)}):*\n"
                for nm in near_misses[:5]:
                    sig_type = nm.get("type", "unknown")
                    reason = nm.get("reason", "unknown")
                    gap = nm.get("gap", 0)
                    message += f"  • `{sig_type}` — {reason} (gap: {gap:.2f})\n"
                message += "\n"
            
            # Opportunity tier breakdown (if available)
            opp_tier_counts = state.get("opportunity_tier_counts", {})
            if opp_tier_counts:
                a_count = opp_tier_counts.get("A", 0)
                b_count = opp_tier_counts.get("B", 0)
                message += f"*Opportunity Tiers:*\n"
                message += f"  ✅ A-tier: {a_count}\n"
                message += f"  ⚗️ B-tier: {b_count}\n"
            
            # Footer tip (button-first UX; only /start is supported)
            message += "\n💡 *Tip:* Use 🎯 *Signals & Trades* for recent signals, and AI Hub → *Policy* for win-rates."

            await self._send_message_or_edit(
                update,
                context,
                message,
                reply_markup=self._get_back_to_menu_button(),
            )
            
        except Exception as e:
            logger.error(f"Error handling /diagnostics: {e}", exc_info=True)
            await self._send_message_or_edit(update, context, f"❌ Error: {str(e)[:100]}", reply_markup=self._get_back_to_menu_button())

    async def _handle_brain(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Brain: learning/policy rollup (mobile-first).

        This is the operator-facing "is the agent getting smarter?" view.
        - Bandit policy (global): per-signal-type Thompson sampling stats
        - Contextual policy: learns by session/regime bucket (if enabled)
        - ML filter: prediction logging + readiness signals (from SQLite, when available)
        """
        if not await self._check_authorized(update):
            return

        try:
            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(hours=24)).isoformat()

            # Load config (best-effort)
            try:
                from pearlalgo.config.config_loader import load_service_config

                cfg = load_service_config(validate=False) or {}
            except Exception:
                cfg = {}

            learning_cfg = cfg.get("learning", {}) or {}
            ml_cfg = cfg.get("ml_filter", {}) or {}

            # SQLite evidence (optional)
            db = self._get_trade_db()
            event_counts: Dict[str, int] = {}
            trade_summary: Dict[str, Any] = {"total": 0, "win_rate": 0.0, "total_pnl": 0.0}
            if db is not None:
                try:
                    event_counts = db.get_signal_event_counts(from_time=cutoff) or {}
                except Exception:
                    event_counts = {}
                try:
                    trade_summary = db.get_trade_summary(from_exit_time=cutoff) or trade_summary
                except Exception:
                    pass

            # -------------------------
            # Bandit policy (global)
            # -------------------------
            bandit_lines: List[str] = []
            try:
                from pearlalgo.learning.bandit_policy import BanditPolicy, BanditConfig

                bandit_config = BanditConfig.from_dict(learning_cfg if isinstance(learning_cfg, dict) else {})
                bandit = BanditPolicy(config=bandit_config, state_dir=self.state_dir)
                status = bandit.get_status() or {}

                stats_list = list(getattr(bandit.state, "signal_types", {}).values())
                stats_sorted = sorted(stats_list, key=lambda s: int(getattr(s, "sample_count", 0) or 0), reverse=True)

                # "Brain metrics" (simple, hard to game): knowledge + uncertainty + expected WR
                total_outcomes = 0
                weighted_expected_sum = 0.0
                weighted_denom = 0
                stdevs: List[float] = []
                for s in stats_list:
                    n = int(getattr(s, "sample_count", 0) or 0)
                    total_outcomes += n
                    w = max(1, n)
                    weighted_denom += w
                    try:
                        weighted_expected_sum += float(getattr(s, "expected_win_rate", 0.5) or 0.5) * w
                    except Exception:
                        weighted_expected_sum += 0.5 * w

                    # Posterior stdev for Beta(alpha, beta)
                    try:
                        a = float(getattr(s, "alpha", 0.0) or 0.0)
                        b = float(getattr(s, "beta", 0.0) or 0.0)
                        if a > 0 and b > 0:
                            var = (a * b) / (((a + b) ** 2) * (a + b + 1))
                            if var >= 0:
                                stdevs.append(math.sqrt(var))
                    except Exception:
                        pass

                avg_expected = (weighted_expected_sum / max(1, weighted_denom)) if weighted_denom else 0.5
                avg_unc = (sum(stdevs) / len(stdevs)) if stdevs else None

                bandit_lines.append(
                    f"- mode: `{bandit_config.mode}` | thr: `{bandit_config.decision_threshold}` | explore: `{bandit_config.explore_rate}`"
                )
                bandit_lines.append(
                    f"- decisions: {int(status.get('total_decisions', 0) or 0)} | execute_rate: {float(status.get('execute_rate', 0) or 0):.2f}"
                )
                if avg_unc is not None:
                    bandit_lines.append(
                        f"- knowledge: {total_outcomes} outcomes | avg exp WR: {avg_expected:.0%} | uncertainty: ±{avg_unc:.0%}"
                    )
                else:
                    bandit_lines.append(
                        f"- knowledge: {total_outcomes} outcomes | avg exp WR: {avg_expected:.0%}"
                    )

                top = [s for s in stats_sorted if int(getattr(s, "sample_count", 0) or 0) > 0][:5]
                if top:
                    bandit_lines.append("\n*Top signal types (by samples):*")
                    for s in top:
                        stype = str(getattr(s, "signal_type", "unknown") or "unknown")
                        wins = int(getattr(s, "wins", 0) or 0)
                        losses = int(getattr(s, "losses", 0) or 0)
                        n = int(getattr(s, "sample_count", 0) or 0)
                        wr = float(getattr(s, "win_rate", 0.0) or 0.0)
                        exp = float(getattr(s, "expected_win_rate", 0.5) or 0.5)
                        bandit_lines.append(f"- `{stype}`: {wins}W/{losses}L (WR {wr:.0%}, exp {exp:.0%}, n={n})")
            except Exception as e:
                bandit_lines = [f"- (bandit unavailable: `{str(e)[:120]}`)"]

            # -------------------------
            # Contextual policy (optional)
            # -------------------------
            contextual_lines: List[str] = []
            try:
                contextual_cfg = learning_cfg.get("contextual", {}) if isinstance(learning_cfg, dict) else {}
                if isinstance(contextual_cfg, dict) and bool(contextual_cfg.get("enabled", False)):
                    from pearlalgo.learning.contextual_bandit import (
                        ContextualBanditPolicy,
                        ContextualBanditConfig,
                    )

                    ctx_config = ContextualBanditConfig.from_dict(contextual_cfg)
                    ctx_policy = ContextualBanditPolicy(config=ctx_config, state_dir=self.state_dir)
                    ctx_status = ctx_policy.get_status() or {}
                    contextual_lines.append(
                        f"- mode: `{ctx_config.mode}` | thr: `{ctx_config.decision_threshold}` | explore: `{ctx_config.explore_rate}`"
                    )
                    contextual_lines.append(
                        f"- decisions: {int(ctx_status.get('total_decisions', 0) or 0)} | execute_rate: {float(ctx_status.get('execute_rate', 0) or 0):.2f}"
                    )
                    contextual_lines.append(f"- contexts tracked: {int(ctx_status.get('unique_contexts', 0) or 0)}")
            except Exception:
                pass

            # -------------------------
            # ML filter metrics (from SQLite signals, when available)
            # -------------------------
            ml_lines: List[str] = []
            ml_enabled = bool(ml_cfg.get("enabled", False)) if isinstance(ml_cfg, dict) else False
            if not ml_enabled:
                ml_lines.append("- disabled in config")
            else:
                try:
                    min_prob = float(ml_cfg.get("min_probability", 0.55))
                except Exception:
                    min_prob = 0.55
                model_path = str(ml_cfg.get("model_path") or "")
                if model_path:
                    try:
                        exists = Path(model_path).exists()
                    except Exception:
                        exists = False
                    ml_lines.append(f"- model: `{model_path}` ({'present' if exists else 'missing'})")
                ml_lines.append(f"- threshold: `{min_prob:.2f}`")

                if db is None:
                    ml_lines.append("- SQLite disabled → no prediction metrics")
                else:
                    try:
                        gen_events = db.get_signal_events(status="generated", from_time=cutoff, limit=2000)
                    except Exception:
                        gen_events = []

                    probs: List[float] = []
                    fallbacks = 0
                    for ev in gen_events:
                        payload = ev.get("payload", {}) or {}
                        sig = payload.get("signal", {}) if isinstance(payload, dict) else {}
                        if not isinstance(sig, dict):
                            continue
                        ml_pred = sig.get("_ml_prediction")
                        if not isinstance(ml_pred, dict):
                            continue
                        try:
                            p = float(ml_pred.get("win_probability", 0.0))
                            probs.append(p)
                        except Exception:
                            continue
                        if bool(ml_pred.get("fallback_used", False)):
                            fallbacks += 1

                    if probs:
                        passed = sum(1 for p in probs if p >= min_prob)
                        ml_lines.append(f"- predictions: {len(probs)} | pass@thr: {passed} ({passed / max(1, len(probs)):.0%})")
                        try:
                            avg_p = float(np.mean(probs))
                            ml_lines.append(f"- avg P(win): {avg_p:.2f} | fallback: {fallbacks} ({fallbacks / max(1, len(probs)):.0%})")
                        except Exception:
                            pass
                    else:
                        ml_lines.append("- predictions: 0 (no signals logged yet)")

            # -------------------------
            # ML lift (shadow A/B) from graded exits (trades table)
            # -------------------------
            ml_lift_lines: List[str] = []
            if ml_enabled and db is not None:
                try:
                    lookback = int(ml_cfg.get("lift_lookback_trades", 200) or 200) if isinstance(ml_cfg, dict) else 200
                except Exception:
                    lookback = 200
                try:
                    min_trades = int(ml_cfg.get("lift_min_trades", 50) or 50) if isinstance(ml_cfg, dict) else 50
                except Exception:
                    min_trades = 50
                try:
                    min_lift = float(ml_cfg.get("lift_min_winrate_delta", 0.05) or 0.05) if isinstance(ml_cfg, dict) else 0.05
                except Exception:
                    min_lift = 0.05
                try:
                    mode = str(ml_cfg.get("mode", "shadow") or "shadow").lower() if isinstance(ml_cfg, dict) else "shadow"
                except Exception:
                    mode = "shadow"
                require_lift = bool(ml_cfg.get("require_lift_to_block", True)) if isinstance(ml_cfg, dict) else True

                try:
                    trades = db.get_recent_trades_by_exit(limit=lookback, from_exit_time=cutoff)
                except Exception:
                    trades = []

                # Filter to trades with real ML predictions (exclude fallback-only)
                scored = []
                for t in trades:
                    feats = t.get("features", {}) if isinstance(t, dict) else {}
                    if not isinstance(feats, dict):
                        continue
                    if "ml_pass_filter" not in feats:
                        continue
                    try:
                        if float(feats.get("ml_fallback_used", 0.0) or 0.0) >= 0.5:
                            continue
                    except Exception:
                        pass
                    scored.append(t)

                if len(scored) < min_trades:
                    ml_lift_lines.append(f"- lift: insufficient data ({len(scored)}/{min_trades} exits)")
                else:
                    p_group = []
                    f_group = []
                    for t in scored:
                        feats = t.get("features", {}) or {}
                        try:
                            pass_flag = float(feats.get("ml_pass_filter", 1.0) or 0.0) >= 0.5
                        except Exception:
                            pass_flag = True
                        (p_group if pass_flag else f_group).append(t)

                    if not p_group or not f_group:
                        ml_lift_lines.append(f"- lift: need both pass+fail groups (pass={len(p_group)}, fail={len(f_group)})")
                    else:
                        def _wr(xs: List[Dict[str, Any]]) -> float:
                            wins = 0
                            for t in xs:
                                try:
                                    if bool(t.get("is_win", False)):
                                        wins += 1
                                except Exception:
                                    continue
                            return wins / max(1, len(xs))

                        wr_pass = _wr(p_group)
                        wr_fail = _wr(f_group)
                        lift_wr = wr_pass - wr_fail
                        lift_ok = bool(lift_wr >= min_lift)
                        blocking_allowed = (mode == "live") and (lift_ok if require_lift else True)

                        ml_lift_lines.append(
                            f"- lift (WR): pass {wr_pass:.0%} vs block {wr_fail:.0%} = {lift_wr:+.0%} "
                            f"(need ≥{min_lift:.0%})"
                        )
                        ml_lift_lines.append(
                            f"- gating: mode `{mode}` | lift_ok `{lift_ok}` | blocking_allowed `{blocking_allowed}`"
                        )

            # -------------------------
            # Drift guard (risk-off cooldown)
            # -------------------------
            drift_lines: List[str] = []
            try:
                dg_path = self.state_dir / "drift_guard_state.json"
                if dg_path.exists():
                    raw = json.loads(dg_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        active = bool(raw.get("active", False))
                        if active:
                            drift_lines.append(f"- status: ON (until {raw.get('until')})")
                            if raw.get("reason"):
                                drift_lines.append(f"- reason: {str(raw.get('reason'))[:120]}")
                            adj = raw.get("adjustments", {}) if isinstance(raw.get("adjustments", {}), dict) else {}
                            if adj:
                                try:
                                    drift_lines.append(
                                        f"- tighten: +{float(adj.get('min_confidence_delta', 0.0) or 0.0):.2f} conf, "
                                        f"+{float(adj.get('min_risk_reward_delta', 0.0) or 0.0):.2f} R:R | "
                                        f"size ×{float(adj.get('size_multiplier', 1.0) or 1.0):.2f}"
                                    )
                                except Exception:
                                    pass
                        else:
                            drift_lines.append("- status: OFF")
                else:
                    drift_lines.append("- status: (no state file yet)")
            except Exception:
                drift_lines = []

            # -------------------------
            # Build message
            # -------------------------
            msg = "🧠 *Brain (last 24h)*\n\n"

            # Evidence: keep ultra-compact
            if db is not None:
                gen = int(event_counts.get("generated", 0) or 0)
                exited = int(event_counts.get("exited", 0) or 0)
                total_trades = int(trade_summary.get("total", 0) or 0)
                try:
                    wr = float(trade_summary.get("win_rate", 0.0) or 0.0)
                except Exception:
                    wr = 0.0
                msg += "*Evidence:*\n"
                msg += f"- signals: {gen} | exits graded: {exited} | trades: {total_trades} | WR: {wr:.0%}\n\n"

            msg += "*Bandit (global):*\n"
            msg += ("\n".join(bandit_lines) if bandit_lines else "- (no data)\n")

            if contextual_lines:
                msg += "\n\n*Contextual (session/regime):*\n"
                msg += "\n".join(contextual_lines)

            if drift_lines:
                msg += "\n\n*Drift guard:*\n"
                msg += "\n".join(drift_lines)

            msg += "\n\n*ML filter:*\n"
            msg += "\n".join(ml_lines) if ml_lines else "- (no data)"

            if ml_lift_lines:
                msg += "\n\n*ML lift (shadow A/B):*\n"
                msg += "\n".join(ml_lift_lines)

            msg += "\n\n💡 Tip: Use 🩺 *Doctor* for ops rollups; this view is about learning/policy."

            await self._send_message_or_edit(
                update,
                context,
                msg,
                reply_markup=self._get_back_to_menu_button(),
            )
        except Exception as e:
            logger.error(f"Error handling /brain: {e}", exc_info=True)
            await self._send_message_or_edit(
                update,
                context,
                f"❌ Error: {str(e)[:120]}",
                reply_markup=self._get_back_to_menu_button(),
            )

    async def _handle_doctor(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Doctor: 24h rollup (mobile-first validation).

        Pulls from SQLite (signals/trades/diagnostics) when enabled, with graceful fallback.
        """
        if not await self._check_authorized(update):
            return

        try:
            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(hours=24)).isoformat()

            db = self._get_trade_db()
            if db is None:
                msg = (
                    "🩺 *Doctor (last 24h)*\n\n"
                    "SQLite storage is *disabled* or unavailable.\n\n"
                    "*Enable it in* `config/config.yaml`:\n"
                    "`storage.sqlite_enabled: true`\n"
                )
                await self._send_message_or_edit(update, context, msg, reply_markup=self._get_back_to_menu_button())
                return

            # 1) Signal events (generated/entered/exited/expired)
            event_counts = db.get_signal_event_counts(from_time=cutoff)

            # 2) Cycle diagnostics (why rejected / why quiet)
            diag = db.get_cycle_diagnostics_aggregate(from_time=cutoff)
            quiet_top = db.get_quiet_reason_counts(from_time=cutoff, limit=3)

            # 3) Trades summary (by exit time)
            trade_summary = db.get_trade_summary(from_exit_time=cutoff)

            # 4) Stop distance + sizing distributions (from generated signals)
            gen_events = db.get_signal_events(status="generated", from_time=cutoff, limit=1000)

            stop_bins = [
                ("<5", 0.0, 5.0),
                ("5-10", 5.0, 10.0),
                ("10-15", 10.0, 15.0),
                ("15-20", 15.0, 20.0),
                ("20-25", 20.0, 25.0),
                (">25", 25.0, 10_000.0),
            ]
            size_bins = [
                ("1", 1.0, 1.0),
                ("2-3", 2.0, 3.0),
                ("4-5", 4.0, 5.0),
                ("6-8", 6.0, 8.0),
                ("9-12", 9.0, 12.0),
                ("13-15", 13.0, 15.0),
                (">15", 15.0, 10_000.0),
            ]

            stop_counts = {k: 0 for (k, _, _) in stop_bins}
            size_counts = {k: 0 for (k, _, _) in size_bins}
            stop_samples: List[float] = []
            size_samples: List[float] = []

            for ev in gen_events:
                payload = ev.get("payload", {}) or {}
                sig = payload.get("signal", {}) if isinstance(payload, dict) else {}
                if not isinstance(sig, dict):
                    continue
                try:
                    entry = float(sig.get("entry_price", 0.0) or 0.0)
                    stop = float(sig.get("stop_loss", 0.0) or 0.0)
                except Exception:
                    entry, stop = 0.0, 0.0

                if entry > 0 and stop > 0:
                    dist = abs(entry - stop)
                    stop_samples.append(dist)
                    for label, lo, hi in stop_bins:
                        if lo <= dist < hi:
                            stop_counts[label] += 1
                            break

                try:
                    size = float(sig.get("position_size", 0.0) or 0.0)
                except Exception:
                    size = 0.0
                if size > 0:
                    size_samples.append(size)
                    for label, lo, hi in size_bins:
                        if label == "1":
                            if abs(size - 1.0) < 1e-9:
                                size_counts[label] += 1
                                break
                        else:
                            if lo <= size <= hi:
                                size_counts[label] += 1
                                break

            def _fmt_pct(x: float) -> str:
                try:
                    return f"{(float(x) * 100):.0f}%"
                except Exception:
                    return "0%"

            # Build message (keep it mobile-safe)
            msg = "🩺 *Doctor (last 24h)*\n\n"

            msg += "*Signals (events):*\n"
            for k in ("generated", "entered", "exited", "expired"):
                if k in event_counts:
                    msg += f"- {k}: {int(event_counts.get(k, 0))}\n"
            if not event_counts:
                msg += "- (no events)\n"

            msg += "\n*Trades (exited):*\n"
            total_trades = int(trade_summary.get("total", 0) or 0)
            msg += f"- total: {total_trades}\n"
            if total_trades > 0:
                msg += f"- WR: {_fmt_pct(trade_summary.get('win_rate', 0.0))}\n"
                try:
                    pnl = float(trade_summary.get("total_pnl", 0.0) or 0.0)
                    pnl_str = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
                except Exception:
                    pnl_str = "$0"
                msg += f"- P&L: {pnl_str}\n"
                try:
                    avg_hold = trade_summary.get("avg_hold_minutes")
                    if avg_hold is not None:
                        msg += f"- avg hold: {float(avg_hold):.1f}m\n"
                except Exception:
                    pass

            msg += "\n*Rejections (cycle totals):*\n"
            rej_lines = []
            for key, label in [
                ("rejected_market_hours", "market hours"),
                ("rejected_confidence", "confidence"),
                ("rejected_risk_reward", "R:R"),
                ("rejected_regime_filter", "regime/session"),
                ("rejected_quality_scorer", "quality"),
                ("rejected_order_book", "order book"),
                ("rejected_invalid_prices", "invalid prices"),
                ("rejected_ml_filter", "ML"),
            ]:
                try:
                    v = int(diag.get(key, 0) or 0)
                except Exception:
                    v = 0
                if v > 0:
                    rej_lines.append(f"- {label}: {v}")
            msg += "\n".join(rej_lines) + ("\n" if rej_lines else "- (no rejection data)\n")

            if stop_samples:
                try:
                    import numpy as np
                    stop_med = float(np.median(stop_samples))
                    stop_avg = float(np.mean(stop_samples))
                    msg += f"\n*Stops (pts):* avg {stop_avg:.1f} • med {stop_med:.1f}\n"
                except Exception:
                    msg += "\n*Stops (pts):*\n"
                msg += "  " + " | ".join([f"{k}:{stop_counts[k]}" for (k, _, _) in stop_bins]) + "\n"
            else:
                msg += "\n*Stops (pts):* (no samples)\n"

            if size_samples:
                try:
                    import numpy as np
                    size_med = float(np.median(size_samples))
                    size_avg = float(np.mean(size_samples))
                    msg += f"*Size (cts):* avg {size_avg:.1f} • med {size_med:.1f}\n"
                except Exception:
                    msg += "*Size (cts):*\n"
                msg += "  " + " | ".join([f"{k}:{size_counts[k]}" for (k, _, _) in size_bins]) + "\n"
            else:
                msg += "*Size (cts):* (no samples)\n"

            if quiet_top:
                msg += "\n*Quiet reasons (top):*\n"
                for qr, c in quiet_top.items():
                    msg += f"- {qr}: {c}\n"

            # Keep within Telegram limit (be conservative)
            if len(msg) > 3800:
                msg = msg[:3800] + "\n...(truncated)"

            await self._send_message_or_edit(update, context, msg, reply_markup=self._get_back_to_menu_button())
        except Exception as e:
            logger.error(f"Error handling /doctor: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context, f"❌ Error: {str(e)[:120]}", reply_markup=self._get_back_to_menu_button()
            )

    async def _handle_purge_test_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /purge_test - Remove all test signals from signals.jsonl.
        
        This removes signals marked with _is_test=true AND signals with
        unrealistic prices (far from recent market prices).
        """
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /purge_test command from {update.effective_user.id}")
        
        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await update.message.reply_text("📭 No signals file found.")
                return
            
            # Read all signals
            signals = []
            purged_count = 0
            kept_count = 0
            
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        signal = record.get("signal", {}) or record
                        
                        # Check if test signal
                        is_test = signal.get("_is_test", False) or record.get("_is_test", False)
                        
                        # Also check for unrealistic prices (likely test data)
                        # MNQ should be roughly $22k-28k range in 2024-2026
                        # Test signals often have prices like $17k-$19k which are way off
                        entry_price = float(signal.get("entry_price", 0) or 0)
                        price_unrealistic = entry_price > 0 and (entry_price < 20000 or entry_price > 32000)
                        
                        if is_test or price_unrealistic:
                            purged_count += 1
                            logger.info(f"Purging signal: is_test={is_test}, price={entry_price}")
                        else:
                            signals.append(record)
                            kept_count += 1
                    except (json.JSONDecodeError, ValueError):
                        continue
            
            if purged_count == 0:
                await update.message.reply_text(
                    "✅ *No test signals found*\n\n"
                    f"All {kept_count} signals appear to be real trades.",
                    parse_mode="Markdown"
                )
                return
            
            # Write back without test signals
            with open(signals_file, "w") as f:
                for record in signals:
                    f.write(json.dumps(record) + "\n")
            
            await update.message.reply_text(
                f"🧹 *Purged {purged_count} test signal(s)*\n\n"
                f"• Removed: {purged_count}\n"
                f"• Kept: {kept_count}\n\n"
                "P&L calculations will now exclude these signals.",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Error handling /purge_test: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

    async def _handle_purge_test_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle settings:purge_test callback button - Remove test signals via inline button.
        
        This is a streamlined version that works with callback queries (button presses).
        """
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Purge test signals button pressed by {update.effective_user.id}")
        
        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals file found*\n\nNothing to purge.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Settings", callback_data="settings"),
                    ]])
                )
                return
            
            # Read all signals and filter
            signals = []
            purged_count = 0
            kept_count = 0
            
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        signal = record.get("signal", {}) or record
                        
                        # Check if test signal
                        is_test = signal.get("_is_test", False) or record.get("_is_test", False)
                        
                        # Also check for unrealistic prices (likely test data)
                        # MNQ should be roughly $22k-28k range in 2024-2026
                        entry_price = float(signal.get("entry_price", 0) or 0)
                        price_unrealistic = entry_price > 0 and (entry_price < 20000 or entry_price > 32000)
                        
                        if is_test or price_unrealistic:
                            purged_count += 1
                            logger.info(f"Purging signal: is_test={is_test}, price={entry_price}")
                        else:
                            signals.append(record)
                            kept_count += 1
                    except (json.JSONDecodeError, ValueError):
                        continue
            
            if purged_count == 0:
                await self._send_message_or_edit(
                    update, context,
                    f"✅ *No test signals found*\n\n"
                    f"All {kept_count} signals appear to be real trades.\n\n"
                    "Nothing was removed.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Settings", callback_data="settings"),
                    ]])
                )
                return
            
            # Write back without test signals
            with open(signals_file, "w") as f:
                for record in signals:
                    f.write(json.dumps(record) + "\n")
            
            await self._send_message_or_edit(
                update, context,
                f"🧹 *Purged {purged_count} test signal(s)*\n\n"
                f"• Removed: {purged_count}\n"
                f"• Kept: {kept_count}\n\n"
                "✅ P&L calculations now exclude test data.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔔 View Signals", callback_data="signals"),
                    InlineKeyboardButton("⬅️ Settings", callback_data="settings"),
                ]])
            )
            
        except Exception as e:
            logger.error(f"Error handling purge_test callback: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                f"❌ Error: {str(e)[:100]}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back to Settings", callback_data="settings"),
                ]])
            )

    async def _handle_mark_signal_as_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /mark_test <signal_id_prefix> - Mark a specific signal as test.
        
        Usage: /mark_test sr_bounce_12345
        """
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /mark_test command from {update.effective_user.id}")
        
        try:
            # Get signal ID from command args
            args = context.args if hasattr(context, "args") else []
            if not args:
                await update.message.reply_text(
                    "❌ *Usage:* `/mark_test <signal_id_prefix>`\n\n"
                    "Example: `/mark_test sr_bounce_1234`\n\n"
                    "Use `/signals` to see signal IDs.",
                    parse_mode="Markdown"
                )
                return
            
            signal_prefix = args[0].strip()
            signals_file = get_signals_file(self.state_dir)
            
            if not signals_file.exists():
                await update.message.reply_text("📭 No signals file found.")
                return
            
            # Read, modify, and write back
            signals = []
            marked_count = 0
            
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        sig_id = record.get("signal_id", "")
                        
                        if sig_id.startswith(signal_prefix):
                            # Mark as test
                            record["_is_test"] = True
                            if "signal" in record and isinstance(record["signal"], dict):
                                record["signal"]["_is_test"] = True
                            marked_count += 1
                            logger.info(f"Marked signal as test: {sig_id}")
                        
                        signals.append(record)
                    except (json.JSONDecodeError, ValueError):
                        continue
            
            if marked_count == 0:
                await update.message.reply_text(
                    f"❌ No signal found matching `{signal_prefix}`\n\n"
                    "Use `/signals` to see available signal IDs.",
                    parse_mode="Markdown"
                )
                return
            
            # Write back
            with open(signals_file, "w") as f:
                for record in signals:
                    f.write(json.dumps(record) + "\n")
            
            await update.message.reply_text(
                f"✅ *Marked {marked_count} signal(s) as test*\n\n"
                f"Signal(s) matching `{signal_prefix}` will be excluded from P&L.\n\n"
                "💡 Use `/purge_test` to permanently remove test signals.",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Error handling /mark_test: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    # =========================================================================
    # Claude Monitor Commands
    # =========================================================================
    
    def _get_claude_monitor(self):
        """Get or create Claude monitor service instance."""
        if not hasattr(self, '_claude_monitor'):
            try:
                from pearlalgo.claude_monitor import ClaudeMonitorService
                self._claude_monitor = ClaudeMonitorService(
                    state_dir=self.state_dir,
                    telegram_bot_token=self.bot_token,
                    telegram_chat_id=self.chat_id,
                )
            except ImportError:
                self._claude_monitor = None
            except Exception as e:
                logger.warning(f"Could not initialize Claude monitor: {e}")
                self._claude_monitor = None
        return self._claude_monitor
    
    async def _handle_claude_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude_status - Show Claude monitor health & recent insights."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /claude_status command from {update.effective_user.id}")
        
        try:
            svc = self.service_controller.get_claude_monitor_status()
            svc_running = bool(svc.get("running"))
            pid = svc.get("pid")

            # Claude API availability (key + anthropic package)
            claude_client_ok = bool(get_claude_client()) if ANTHROPIC_AVAILABLE else False

            # Stats from persistent monitor state (shared with the background service)
            stats = {}
            try:
                from pearlalgo.claude_monitor.monitor_state import MonitorState

                stats = MonitorState(state_dir=self.state_dir).get_stats()
            except Exception:
                stats = {}

            running_emoji = "🟢" if svc_running else "⚪"
            claude_emoji = "✅" if claude_client_ok else "❌"
            telegram_emoji = "✅" if (self.bot_token and self.chat_id) else "❌"

            message = (
                "🤖 *Claude Monitor Status*\n\n"
                f"{running_emoji} Service: `{'running' if svc_running else 'stopped'}`\n"
                f"{'🧾' if pid else '🧾'} PID: `{pid if pid else 'n/a'}`\n"
                f"{claude_emoji} Claude API: `{'available' if claude_client_ok else 'unavailable'}`\n"
                f"{telegram_emoji} Telegram: `{'configured' if (self.bot_token and self.chat_id) else 'not configured'}`\n\n"
                f"*Stats:*\n"
                f"• Analyses: `{stats.get('analysis_count', 0)}`\n"
                f"• Alerts sent: `{stats.get('alert_count', 0)}`\n"
                f"• Active suggestions: `{stats.get('active_suggestions', 0)}`\n"
                f"• Applied changes: `{stats.get('applied_count', 0)}`\n\n"
                "Open the Monitor hub for controls and analysis buttons."
            )

            await self._send_message_or_edit(
                update,
                context,
                message,
                reply_markup=self._get_claude_hub_buttons(show_monitor=True),
            )

        except Exception as e:
            logger.error(f"Error handling /claude_status: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _handle_analyze_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /analyze_now - Force immediate comprehensive analysis."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /analyze_now command from {update.effective_user.id}")
        
        try:
            monitor = self._get_claude_monitor()
            
            if not monitor:
                await update.message.reply_text("❌ Claude monitor not available")
                return
            
            await update.message.reply_text("🔄 Running comprehensive analysis...")
            
            # Run analysis
            analysis = await monitor.force_analysis()
            
            # Format results
            message = "🤖 *Analysis Complete*\n\n"
            
            for dimension, result in analysis.items():
                if dimension in ("timestamp", "status"):
                    continue
                if not isinstance(result, dict):
                    continue
                
                status = result.get("status", "unknown")
                status_emoji = {
                    "healthy": "🟢",
                    "degraded": "🟡",
                    "critical": "🔴",
                    "warning": "🟡",
                    "favorable": "🟢",
                    "neutral": "⚪",
                }.get(status, "⚪")
                
                findings_count = len(result.get("findings", []))
                recs_count = len(result.get("recommendations", []))
                
                message += f"{status_emoji} *{dimension.title()}*: {status}\n"
                if findings_count > 0:
                    message += f"   • {findings_count} finding(s)\n"
                if recs_count > 0:
                    message += f"   • {recs_count} recommendation(s)\n"
            
            # Key insights
            for dimension, result in analysis.items():
                if isinstance(result, dict) and "summary" in result:
                    insight = result["summary"].get("key_insight")
                    if insight:
                        message += f"\n💡 _{insight}_"
                        break
            
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error handling /analyze_now: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _handle_analyze_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /analyze_signals - Deep dive on signal quality."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /analyze_signals command from {update.effective_user.id}")
        
        try:
            monitor = self._get_claude_monitor()
            
            if not monitor:
                await update.message.reply_text("❌ Claude monitor not available")
                return
            
            await update.message.reply_text("🔄 Analyzing signal quality...")
            
            result = await monitor.analyze_signals()
            
            # Format results
            status_emoji = {"healthy": "🟢", "degraded": "🟡", "critical": "🔴"}.get(
                result.get("status", ""), "⚪"
            )
            
            message = f"{status_emoji} *Signal Analysis*\n\n"
            
            summary = result.get("summary", {})
            message += f"*Signals Analyzed:* `{summary.get('total_signals', 0)}`\n"
            
            win_rate = summary.get("overall_win_rate")
            if win_rate is not None:
                wr_emoji = "🟢" if win_rate >= 0.5 else "🔴"
                message += f"*Win Rate:* {wr_emoji} `{win_rate:.1%}`\n"
            
            if summary.get("best_signal_type"):
                message += f"*Best Type:* `{summary['best_signal_type']}`\n"
            if summary.get("worst_signal_type"):
                message += f"*Worst Type:* `{summary['worst_signal_type']}`\n"
            
            # Show findings
            findings = result.get("findings", [])
            if findings:
                message += f"\n*Findings ({len(findings)}):*\n"
                for f in findings[:5]:
                    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(
                        f.get("severity", ""), "🔵"
                    )
                    message += f"{severity_emoji} {f.get('title', 'Finding')}\n"
            
            # Key insight
            if summary.get("key_insight"):
                message += f"\n💡 _{summary['key_insight']}_"
            
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error handling /analyze_signals: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _handle_analyze_system(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /analyze_system - System health report."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /analyze_system command from {update.effective_user.id}")
        
        try:
            monitor = self._get_claude_monitor()
            
            if not monitor:
                await update.message.reply_text("❌ Claude monitor not available")
                return
            
            await update.message.reply_text("🔄 Analyzing system health...")
            
            result = await monitor.analyze_system()
            
            # Format results
            status_emoji = {
                "healthy": "🟢",
                "degraded": "🟡",
                "critical": "🔴",
                "warning": "🟡",
            }.get(result.get("status", ""), "⚪")
            
            message = f"{status_emoji} *System Health Analysis*\n\n"
            
            metrics = result.get("metrics", {})
            
            # Running status
            running_emoji = "🟢" if metrics.get("running") else "🔴"
            message += f"{running_emoji} Agent Running: `{metrics.get('running', False)}`\n"
            
            if metrics.get("paused"):
                message += f"⏸️ Agent Paused: `True`\n"
            
            # Error counts
            cons_errors = metrics.get("consecutive_errors", 0)
            if cons_errors > 0:
                message += f"⚠️ Consecutive Errors: `{cons_errors}`\n"
            
            conn_failures = metrics.get("connection_failures", 0)
            if conn_failures > 0:
                message += f"🔌 Connection Failures: `{conn_failures}`\n"
            
            # Data freshness
            data_fresh = metrics.get("data_fresh")
            if data_fresh is not None:
                fresh_emoji = "✅" if data_fresh else "❌"
                message += f"{fresh_emoji} Data Fresh: `{data_fresh}`\n"
            
            # Show findings
            findings = result.get("findings", [])
            if findings:
                message += f"\n*Issues ({len(findings)}):*\n"
                for f in findings[:5]:
                    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(
                        f.get("severity", ""), "🔵"
                    )
                    message += f"{severity_emoji} {f.get('title', 'Issue')}\n"
            else:
                message += "\n✅ No issues detected"
            
            # Key insight
            summary = result.get("summary", {})
            if summary.get("key_insight"):
                message += f"\n\n💡 _{summary['key_insight']}_"
            
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error handling /analyze_system: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _handle_analyze_market(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /analyze_market - Market conditions & regime analysis."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /analyze_market command from {update.effective_user.id}")
        
        try:
            monitor = self._get_claude_monitor()
            
            if not monitor:
                await update.message.reply_text("❌ Claude monitor not available")
                return
            
            await update.message.reply_text("🔄 Analyzing market conditions...")
            
            result = await monitor.analyze_market()
            
            # Format results
            message = "📊 *Market Analysis*\n\n"
            
            # Regime
            regime = result.get("regime", {})
            regime_type = regime.get("type", "unknown")
            confidence = regime.get("confidence", 0)
            
            regime_emoji = {
                "trending_bullish": "📈",
                "trending_bearish": "📉",
                "ranging": "↔️",
                "choppy": "🌊",
                "closed": "🔒",
            }.get(regime_type, "❓")
            
            message += f"{regime_emoji} *Regime:* `{regime_type.replace('_', ' ').title()}`\n"
            message += f"   Confidence: `{confidence:.0%}`\n"
            
            # Volatility
            vol = result.get("volatility", {})
            vol_level = vol.get("level", "unknown")
            vol_emoji = {"high": "🔥", "normal": "➖", "low": "❄️"}.get(vol_level, "❓")
            message += f"{vol_emoji} *Volatility:* `{vol_level.title()}`\n"
            
            # Session
            session = result.get("session", {})
            session_name = session.get("active", "unknown")
            message += f"🕐 *Session:* `{session_name.title()}`\n"
            
            # Trading bias
            summary = result.get("summary", {})
            bias = summary.get("trading_bias", "neutral")
            bias_emoji = {"long": "📈", "short": "📉", "neutral": "➖"}.get(bias, "➖")
            message += f"{bias_emoji} *Bias:* `{bias.title()}`\n"
            
            # Key insight
            if summary.get("key_insight"):
                message += f"\n💡 _{summary['key_insight']}_"
            
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error handling /analyze_market: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _handle_suggest_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /suggest_config - Get configuration tuning suggestions."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /suggest_config command from {update.effective_user.id}")
        
        try:
            monitor = self._get_claude_monitor()
            
            if not monitor:
                await self._send_message_or_edit(
                    update,
                    context,
                    "❌ Claude monitor not available",
                    reply_markup=self._get_claude_hub_buttons(show_monitor=True),
                )
                return
            
            await self._send_message_or_edit(update, context, "🔄 Generating configuration suggestions...", reply_markup=None)
            
            # Run analysis to generate suggestions
            analysis = await monitor.force_analysis()
            suggestions = monitor.get_active_suggestions()
            
            # Filter to config suggestions
            config_suggestions = [
                s for s in suggestions
                if s.get("type") in ("config_change", "parameter_tune")
            ]
            
            if not config_suggestions:
                # Check recommendations from analysis
                all_recs = []
                for dim, result in analysis.items():
                    if isinstance(result, dict):
                        all_recs.extend(result.get("recommendations", []))
                
                config_recs = [r for r in all_recs if r.get("config_path")]
                
                if config_recs:
                    message = "💡 *Config Recommendations*\n\n"
                    for rec in config_recs[:5]:
                        message += f"*{rec.get('title', 'Recommendation')}*\n"
                        if rec.get("config_path"):
                            message += f"Path: `{rec['config_path']}`\n"
                        if rec.get("new_value") is not None:
                            message += f"Suggested: `{rec['new_value']}`\n"
                        if rec.get("rationale"):
                            message += f"_{rec['rationale']}_\n"
                        message += "\n"
                else:
                    message = "✅ No configuration changes recommended at this time."
            else:
                message = "💡 *Config Suggestions*\n\n"
                for sug in config_suggestions[:5]:
                    message += f"*{sug.get('title', 'Suggestion')}* (`{sug.get('id')}`)\n"
                    if sug.get("config_path"):
                        message += f"Path: `{sug['config_path']}`\n"
                        message += f"Current: `{sug.get('old_value')}`\n"
                        message += f"Suggested: `{sug.get('new_value')}`\n"
                    message += f"_{sug.get('rationale', '')[:100]}_\n\n"
                
                message += "\nUse `/apply_suggestion <id>` to apply."
            
            await self._send_message_or_edit(
                update,
                context,
                message,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("📋 Suggestions", callback_data="claude_suggestions")],
                        [InlineKeyboardButton("⬅️ Claude Hub", callback_data="claude_hub")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                    ]
                ),
            )
            
        except Exception as e:
            logger.error(f"Error handling /suggest_config: {e}", exc_info=True)
            await self._send_message_or_edit(update, context, f"❌ Error: {str(e)[:100]}", reply_markup=self._get_claude_hub_buttons(show_monitor=True))

    # =========================================================================
    # Suggestions UI (tap-to-approve)
    # =========================================================================

    async def _render_suggestions_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        banner: Optional[str] = None,
        reset_page: bool = False,
    ) -> None:
        """Render an interactive suggestions list with Apply/Dry-run/Dismiss buttons."""
        monitor = self._get_claude_monitor()
        if not monitor:
            await self._send_message_or_edit(
                update,
                context,
                "❌ Claude monitor not available",
                reply_markup=self._get_claude_hub_buttons(show_monitor=True),
            )
            return

        # Pagination state
        page = 0
        if hasattr(context, "user_data"):
            try:
                page = int(context.user_data.get("claude_suggestions_page", 0) or 0)
            except Exception:
                page = 0
            if reset_page:
                page = 0
            context.user_data["claude_suggestions_page"] = page

        suggestions = monitor.get_active_suggestions() or []
        if not suggestions:
            msg = "✅ *No active suggestions.*\n\nEverything looks stable right now."
            await self._send_message_or_edit(
                update,
                context,
                msg,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("⬅️ Claude Hub", callback_data="claude_hub")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                    ]
                ),
            )
            return

        # Sort: high -> medium -> low, then newest-ish
        pr_rank = {"high": 0, "medium": 1, "low": 2}
        suggestions = sorted(
            suggestions,
            key=lambda s: (
                pr_rank.get(str(s.get("priority", "medium")), 1),
                str(s.get("created_at", "")),
            ),
        )

        page_size = 5
        total = len(suggestions)
        total_pages = max(1, int(math.ceil(total / page_size)))
        page = max(0, min(page, total_pages - 1))
        if hasattr(context, "user_data"):
            context.user_data["claude_suggestions_page"] = page

        start = page * page_size
        shown = suggestions[start : start + page_size]

        # Message
        lines: List[str] = [f"💡 *Active Suggestions ({total})*"]
        if banner:
            lines += ["", banner.strip()]
        lines.append("")
        if total_pages > 1:
            lines.append(f"*Page:* `{page + 1}/{total_pages}`")
            lines.append("")

        for idx, sug in enumerate(shown, start=1):
            priority = str(sug.get("priority", "medium"))
            pemoji = {"high": "🔺", "medium": "🔸", "low": "🔹"}.get(priority, "•")
            title = safe_label(str(sug.get("title", "Suggestion") or "Suggestion"))
            sid = str(sug.get("id") or "")
            stype = str(sug.get("type", "unknown") or "unknown")
            lines.append(f"{idx}) {pemoji} *{title}*")
            if sid:
                lines.append(f"   ID: `{sid}`  •  Type: `{stype}`")
            else:
                lines.append(f"   Type: `{stype}`")

            cfg_path = sug.get("config_path")
            old_val = sug.get("old_value")
            new_val = sug.get("new_value")
            if cfg_path and new_val is not None:
                ov = str(old_val).replace("`", "'")
                nv = str(new_val).replace("`", "'")
                lines.append(f"   `{cfg_path}`: `{ov}` → `{nv}`")

            desc = str(sug.get("description", "") or "").strip()
            if desc:
                desc = safe_label(desc)
                if len(desc) > 140:
                    desc = desc[:140] + "…"
                lines.append(f"   _{desc}_")

            lines.append("")

        msg = "\n".join(lines).strip()
        if len(msg) > 3800:
            msg = msg[:3800] + "\n…(truncated)  Tap Refresh for more."

        # Buttons
        keyboard: List[List[InlineKeyboardButton]] = []
        for idx, sug in enumerate(shown, start=1):
            sid = str(sug.get("id") or "").strip()
            if not sid:
                continue
            keyboard.append(
                [
                    InlineKeyboardButton(f"✅ Apply {idx}", callback_data=f"sug:apply:{sid}"),
                    InlineKeyboardButton(f"🧪 Dry {idx}", callback_data=f"sug:dry:{sid}"),
                    InlineKeyboardButton(f"🗑 Dismiss {idx}", callback_data=f"sug:dismiss:{sid}"),
                ]
            )

        if total_pages > 1:
            keyboard.append(
                [
                    InlineKeyboardButton("◀ Prev", callback_data="sug:page:prev"),
                    InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="sug:noop"),
                    InlineKeyboardButton("Next ▶", callback_data="sug:page:next"),
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="sug:page:refresh"),
                InlineKeyboardButton("⬅️ Claude Hub", callback_data="claude_hub"),
            ]
        )
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="start")])

        await self._send_message_or_edit(update, context, msg, reply_markup=InlineKeyboardMarkup(keyboard))

    async def _render_suggestion_confirm(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        suggestion_id: str,
        action: str,
    ) -> None:
        """Render a two-step confirmation screen for a suggestion action."""
        monitor = self._get_claude_monitor()
        if not monitor:
            await self._send_message_or_edit(
                update,
                context,
                "❌ Claude monitor not available",
                reply_markup=self._get_claude_hub_buttons(show_monitor=True),
            )
            return

        sug = monitor.monitor_state.get_suggestion(suggestion_id)
        if not sug:
            await self._render_suggestions_menu(update, context, banner="⚠️ Suggestion not found (stale button).", reset_page=False)
            return

        action = str(action or "").lower().strip()
        action_title = {
            "apply": "✅ *Confirm Apply*",
            "dry": "🧪 *Confirm Dry-run*",
            "dismiss": "🗑 *Confirm Dismiss*",
        }.get(action, "⚠️ *Confirm*")

        title = safe_label(str(sug.get("title", "Suggestion") or "Suggestion"))
        stype = str(sug.get("type", "unknown") or "unknown")
        priority = str(sug.get("priority", "medium") or "medium")
        cfg_path = sug.get("config_path")
        old_val = sug.get("old_value")
        new_val = sug.get("new_value")

        lines: List[str] = [
            action_title,
            "",
            f"*ID:* `{suggestion_id}`",
            f"*Type:* `{stype}`  •  *Priority:* `{priority}`",
            "",
            f"*Suggestion:* {title}",
        ]

        if cfg_path and new_val is not None:
            ov = str(old_val).replace("`", "'")
            nv = str(new_val).replace("`", "'")
            lines += ["", "*Change:*", f"`{cfg_path}`: `{ov}` → `{nv}`"]

        if action == "apply":
            lines += ["", "_This will apply the suggestion via the policy-gated executor. You can rollback using the request id._"]
        elif action == "dry":
            lines += ["", "_This will simulate the change (no files modified). The suggestion stays pending._"]
        elif action == "dismiss":
            lines += ["", "_This will hide the suggestion from the active list._"]

        do_cb = f"sug:do:{action}:{suggestion_id}"
        keyboard: List[List[InlineKeyboardButton]] = [[InlineKeyboardButton("✅ Confirm", callback_data=do_cb)]]

        # Switch actions (still requires confirmation)
        if action != "apply":
            keyboard.append([InlineKeyboardButton("✅ Apply Instead", callback_data=f"sug:apply:{suggestion_id}")])
        if action != "dry":
            keyboard.append([InlineKeyboardButton("🧪 Dry-run Instead", callback_data=f"sug:dry:{suggestion_id}")])
        if action != "dismiss":
            keyboard.append([InlineKeyboardButton("🗑 Dismiss Instead", callback_data=f"sug:dismiss:{suggestion_id}")])

        keyboard.append(
            [
                InlineKeyboardButton("⬅️ Back to Suggestions", callback_data="sug:list"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="start"),
            ]
        )

        await self._send_message_or_edit(update, context, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    async def _execute_suggestion_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        suggestion_id: str,
        action: str,
    ) -> None:
        """Execute a confirmed suggestion action."""
        monitor = self._get_claude_monitor()
        if not monitor:
            await self._send_message_or_edit(
                update,
                context,
                "❌ Claude monitor not available",
                reply_markup=self._get_claude_hub_buttons(show_monitor=True),
            )
            return

        action = str(action or "").lower().strip()

        if action == "dismiss":
            ok = bool(monitor.dismiss_suggestion(suggestion_id))
            banner = "✅ Dismissed." if ok else "⚠️ Could not dismiss (stale?)."
            await self._render_suggestions_menu(update, context, banner=banner, reset_page=False)
            return

        dry_run = action == "dry"
        await self._send_message_or_edit(
            update,
            context,
            f"⏳ {'Dry-running' if dry_run else 'Applying'} `{suggestion_id}`…",
            reply_markup=None,
        )

        result = await monitor.apply_suggestion(suggestion_id, dry_run=dry_run)

        if result.get("success"):
            request_id = str(result.get("request_id") or "")
            msg_lines = [
                ("🧪 *Dry-run Complete*" if dry_run else "✅ *Suggestion Applied*"),
                "",
                f"*ID:* `{suggestion_id}`",
                f"*Action:* `{result.get('action_type', 'unknown')}`",
            ]
            if request_id:
                msg_lines.append(f"*Request ID:* `{request_id}`")

            if result.get("message"):
                msg_lines.append("")
                msg_lines.append(f"_{safe_label(str(result.get('message'))[:240])}_")

            if not dry_run and request_id and result.get("can_rollback"):
                msg_lines += ["", f"🔄 Rollback: `/rollback_suggestion {request_id}`"]

            if dry_run:
                msg_lines += ["", "_Suggestion remains pending._"]

            kb: List[List[InlineKeyboardButton]] = []
            if not dry_run and request_id and result.get("can_rollback"):
                kb.append([InlineKeyboardButton("🔄 Rollback", callback_data=f"sug:rollback:{request_id}")])
            kb.append([InlineKeyboardButton("⬅️ Back to Suggestions", callback_data="sug:list")])
            if dry_run:
                kb.append([InlineKeyboardButton("✅ Apply Now", callback_data=f"sug:apply:{suggestion_id}")])
            kb.append([InlineKeyboardButton("🏠 Main Menu", callback_data="start")])

            await self._send_message_or_edit(update, context, "\n".join(msg_lines), reply_markup=InlineKeyboardMarkup(kb))
            return

        if result.get("requires_manual"):
            sug = result.get("suggestion", {}) or {}
            title = safe_label(str(sug.get("title", "Suggestion") or "Suggestion"))
            msg = (
                "⚠️ *Manual Action Required*\n\n"
                f"*ID:* `{suggestion_id}`\n"
                f"*Suggestion:* {title}\n\n"
                f"This suggestion type (`{sug.get('type', 'unknown')}`) cannot be auto-applied.\n\n"
                "*What to do:*\n"
                f"_{safe_label(str(sug.get('description', 'Review and apply manually') or '')[:300])}_"
            )
            await self._send_message_or_edit(
                update,
                context,
                msg,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🧩 Patch Wizard", callback_data="claude_patch_wizard")],
                        [InlineKeyboardButton("⬅️ Back to Suggestions", callback_data="sug:list")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                    ]
                ),
            )
            return

        err = safe_label(str(result.get("error") or "Unknown error")[:240])
        await self._send_message_or_edit(
            update,
            context,
            f"❌ *Action Failed*\n\n*ID:* `{suggestion_id}`\n*Error:* _{err}_",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⬅️ Back to Suggestions", callback_data="sug:list")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                ]
            ),
        )

    async def _render_rollback_confirm(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        request_id: str,
    ) -> None:
        """Render a two-step confirmation screen for rolling back a prior action."""
        if not request_id:
            await self._send_message_or_edit(
                update,
                context,
                "🔄 *Rollback*\n\n⚠️ Missing request id (stale button).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Suggestions", callback_data="sug:list")]]),
            )
            return

        msg = (
            "🔄 *Confirm Rollback*\n\n"
            f"*Request ID:* `{safe_label(request_id)}`\n\n"
            "This will attempt to restore the previous configuration (or reverse a patch) using the saved backup.\n\n"
            "Proceed?"
        )
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Confirm Rollback", callback_data=f"sug:do:rollback:{request_id}")],
                [
                    InlineKeyboardButton("⬅️ Back to Suggestions", callback_data="sug:list"),
                    InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show"),
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
        )
        await self._send_message_or_edit(update, context, msg, reply_markup=kb)

    async def _execute_rollback_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        request_id: str,
    ) -> None:
        """Execute a confirmed rollback."""
        monitor = self._get_claude_monitor()
        if not monitor:
            await self._send_message_or_edit(
                update,
                context,
                "❌ Claude monitor not available",
                reply_markup=self._get_claude_hub_buttons(show_monitor=True),
            )
            return

        request_id = str(request_id or "").strip()
        if not request_id:
            await self._send_message_or_edit(
                update,
                context,
                "🔄 *Rollback*\n\n⚠️ Missing request id (stale button).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Suggestions", callback_data="sug:list")]]),
            )
            return

        await self._send_message_or_edit(
            update,
            context,
            f"⏳ Rolling back `{request_id}`…",
            reply_markup=None,
        )

        result = await monitor.rollback_suggestion(request_id)
        if result.get("success"):
            msg = (
                "✅ *Rollback Successful*\n\n"
                f"*Request ID:* `{request_id}`\n"
                f"*Status:* `{result.get('status', 'rolled_back')}`\n\n"
                f"_{safe_label(str(result.get('message', 'Rolled back'))[:240])}_"
            )
        else:
            err = safe_label(str(result.get("error") or "Unknown error")[:240])
            msg = (
                "❌ *Rollback Failed*\n\n"
                f"*Request ID:* `{request_id}`\n"
                f"*Error:* _{err}_"
            )

        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬅️ Back to Suggestions", callback_data="sug:list")],
                [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
        )
        await self._send_message_or_edit(update, context, msg, reply_markup=kb)

    async def _handle_suggestion_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """Route sug:* callbacks for the Suggestions tap-to-approve UI."""
        if callback_data == "sug:noop":
            return

        if callback_data == "sug:list" or callback_data == "sug:page:refresh":
            await self._render_suggestions_menu(update, context, reset_page=False)
            return

        if callback_data.startswith("sug:page:"):
            action = callback_data.split("sug:page:", 1)[1].strip()
            if hasattr(context, "user_data"):
                try:
                    page = int(context.user_data.get("claude_suggestions_page", 0) or 0)
                except Exception:
                    page = 0
                if action == "next":
                    page += 1
                elif action == "prev":
                    page = max(0, page - 1)
                context.user_data["claude_suggestions_page"] = page
            await self._render_suggestions_menu(update, context, reset_page=False)
            return

        for prefix, act in (("sug:apply:", "apply"), ("sug:dry:", "dry"), ("sug:dismiss:", "dismiss")):
            if callback_data.startswith(prefix):
                sid = callback_data.split(prefix, 1)[1].strip()
                await self._render_suggestion_confirm(update, context, sid, act)
                return

        if callback_data.startswith("sug:rollback:"):
            rid = callback_data.split("sug:rollback:", 1)[1].strip()
            await self._render_rollback_confirm(update, context, rid)
            return

        if callback_data.startswith("sug:do:"):
            parts = callback_data.split(":")
            if len(parts) >= 4:
                act = parts[2].strip()
                sid = ":".join(parts[3:]).strip()
                if act == "rollback":
                    await self._execute_rollback_action(update, context, sid)
                else:
                    await self._execute_suggestion_action(update, context, sid, act)
                return

        await self._send_message_or_edit(
            update,
            context,
            f"❌ Unknown suggestion action: `{safe_label(callback_data)[:120]}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Suggestions", callback_data="sug:list")]]),
        )
    
    async def _handle_suggestions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /suggestions - List all active suggestions."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /suggestions command from {update.effective_user.id}")
        
        try:
            await self._render_suggestions_menu(update, context, reset_page=not bool(update.callback_query))
        except Exception as e:
            logger.error(f"Error handling /suggestions: {e}", exc_info=True)
            await self._send_message_or_edit(update, context, f"❌ Error: {str(e)[:100]}", reply_markup=self._get_claude_hub_buttons(show_monitor=True))
    
    async def _handle_apply_suggestion(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /apply_suggestion <id> [--dry-run] - Apply a suggestion."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /apply_suggestion command from {update.effective_user.id}")
        
        try:
            monitor = self._get_claude_monitor()
            
            if not monitor:
                await update.message.reply_text("❌ Claude monitor not available")
                return
            
            # Get suggestion ID from args
            args = context.args or []
            if not args:
                await update.message.reply_text(
                    "Usage: `/apply_suggestion <suggestion_id>` [--dry-run]\n\n"
                    "Options:\n"
                    "• `--dry-run` - Simulate without applying\n\n"
                    "Use `/suggestions` to see available suggestions.",
                    parse_mode="Markdown",
                )
                return
            
            suggestion_id = args[0]
            dry_run = "--dry-run" in args or "-n" in args
            
            # Get suggestion details first
            suggestion = monitor.monitor_state.get_suggestion(suggestion_id)
            
            if not suggestion:
                await update.message.reply_text(f"❌ Suggestion `{suggestion_id}` not found.")
                return
            
            # Show "working" message
            mode_text = " (DRY RUN)" if dry_run else ""
            await update.message.reply_text(
                f"⏳ Applying suggestion `{suggestion_id}`{mode_text}...",
                parse_mode="Markdown",
            )
            
            # Apply the suggestion via ActionExecutor
            result = await monitor.apply_suggestion(suggestion_id, dry_run=dry_run)
            
            if result.get("success"):
                # Build success message with details
                lines = [
                    f"✅ *Suggestion Applied*{mode_text}",
                    "",
                    f"*ID:* `{suggestion_id}`",
                    f"*Title:* {suggestion.get('title', 'Suggestion')}",
                ]
                
                # Show config change details
                config_path = suggestion.get("config_path")
                if config_path:
                    lines.append(f"*Config:* `{config_path}`")
                    old_val = suggestion.get("old_value")
                    new_val = suggestion.get("new_value")
                    if old_val is not None:
                        lines.append(f"*Old Value:* `{old_val}`")
                    if new_val is not None:
                        lines.append(f"*New Value:* `{new_val}`")
                
                # Action details
                action_type = result.get("action_type", "unknown")
                request_id = result.get("request_id", "unknown")
                lines.extend([
                    "",
                    f"*Action:* `{action_type}`",
                    f"*Request ID:* `{request_id}`",
                ])
                
                # Rollback instructions
                if result.get("can_rollback") and not dry_run:
                    lines.extend([
                        "",
                        "🔄 *Rollback:* `/rollback_suggestion " + request_id + "`",
                    ])
                
                # Description
                desc = suggestion.get("description", "")
                if desc:
                    lines.extend(["", f"_{desc[:180]}{'...' if len(desc) > 180 else ''}_"])
                
                reply_rows: List[List[InlineKeyboardButton]] = []
                if result.get("can_rollback") and not dry_run and request_id and request_id != "unknown":
                    reply_rows.append([InlineKeyboardButton("🔄 Rollback", callback_data=f"sug:rollback:{request_id}")])
                reply_rows += [
                    [InlineKeyboardButton("📋 Suggestions", callback_data="claude_suggestions")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                ]
                await self._send_message_or_edit(
                    update,
                    context,
                    "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup(reply_rows),
                )
            
            elif result.get("requires_manual"):
                # Non-executable suggestion
                await update.message.reply_text(
                    f"⚠️ *Manual Action Required*\n\n"
                    f"*{suggestion.get('title', 'Suggestion')}*\n\n"
                    f"This suggestion type (`{suggestion.get('type')}`) cannot be auto-applied.\n\n"
                    f"*What to do:*\n"
                    f"_{suggestion.get('description', 'Review and apply manually')[:300]}_",
                    parse_mode="Markdown",
                )
            else:
                # Failed
                error = result.get("error", "Unknown error")
                await update.message.reply_text(
                    f"❌ *Apply Failed*\n\n"
                    f"*Suggestion:* `{suggestion_id}`\n"
                    f"*Error:* {error[:200]}",
                    parse_mode="Markdown",
                )
            
        except Exception as e:
            logger.error(f"Error handling /apply_suggestion: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

    async def _handle_rollback_suggestion(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /rollback_suggestion <request_id> - Rollback a previously applied suggestion."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /rollback_suggestion command from {update.effective_user.id}")
        
        try:
            monitor = self._get_claude_monitor()
            
            if not monitor:
                await update.message.reply_text("❌ Claude monitor not available")
                return
            
            # Get request ID from args
            args = context.args or []
            if not args:
                await update.message.reply_text(
                    "Usage: `/rollback_suggestion <request_id>`\n\n"
                    "The `request_id` is shown when you apply a suggestion.\n"
                    "Check the audit log for recent actions.",
                    parse_mode="Markdown",
                )
                return
            
            request_id = args[0]
            
            await update.message.reply_text(
                f"⏳ Rolling back `{request_id}`...",
                parse_mode="Markdown",
            )
            
            # Perform rollback
            result = await monitor.rollback_suggestion(request_id)
            
            if result.get("success"):
                await update.message.reply_text(
                    f"✅ *Rollback Successful*\n\n"
                    f"*Request ID:* `{request_id}`\n"
                    f"*Status:* `{result.get('status', 'rolled_back')}`\n\n"
                    f"_{result.get('message', 'Config restored from backup')}_",
                    parse_mode="Markdown",
                )
            else:
                error = result.get("error", "Unknown error")
                await update.message.reply_text(
                    f"❌ *Rollback Failed*\n\n"
                    f"*Request ID:* `{request_id}`\n"
                    f"*Error:* {error[:200]}",
                    parse_mode="Markdown",
                )
            
        except Exception as e:
            logger.error(f"Error handling /rollback_suggestion: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

    # =========================================================================
    # Strategy Review (one-tap analysis + recommendations + Claude integration)
    # =========================================================================

    def _format_strategy_review_message(self, analysis: Dict[str, Any], suggestions: List[Dict[str, Any]], lookback_hours: int = 24) -> str:
        """Format a compact Strategy Review message for Telegram."""
        now = get_utc_timestamp()
        lines: List[str] = [
            "🧠 *Strategy Review*",
            f"_{now}_",
            f"*Lookback:* `{lookback_hours}h`",
            "",
        ]

        # Status snapshot (signals/system/market/code)
        dim_order = ["signals", "system", "market", "code"]
        status_emoji = {
            "healthy": "🟢",
            "favorable": "🟢",
            "neutral": "⚪",
            "warning": "🟡",
            "degraded": "🟡",
            "critical": "🔴",
            "error": "🔴",
            "insufficient_data": "⚪",
        }

        lines.append("*Status:*")
        for dim in dim_order:
            res = analysis.get(dim)
            if not isinstance(res, dict):
                continue
            st = str(res.get("status") or "unknown")
            emoji = status_emoji.get(st, "⚪")
            findings = res.get("findings") if isinstance(res.get("findings"), list) else []
            recs = res.get("recommendations") if isinstance(res.get("recommendations"), list) else []
            suffix = ""
            try:
                if findings:
                    suffix += f" • {len(findings)} finding(s)"
                if recs:
                    suffix += f" • {len(recs)} rec(s)"
            except Exception:
                pass
            lines.append(f"- {emoji} *{dim.title()}*: `{st}`{suffix}")

        # Pull first key insight we can find
        key_insight = None
        try:
            for dim in dim_order:
                res = analysis.get(dim)
                if isinstance(res, dict):
                    summary = res.get("summary", {})
                    if isinstance(summary, dict) and summary.get("key_insight"):
                        key_insight = str(summary["key_insight"]).strip()
                        break
        except Exception:
            key_insight = None

        if key_insight:
            lines += ["", f"💡 _{key_insight}_"]

        # Top recommendations (prefer SuggestionEngine output)
        lines.append("")
        lines.append("*Top Recommendations:*")

        if suggestions:
            top = suggestions[:3]
            for i, s in enumerate(top, start=1):
                title = str(s.get("title") or "Suggestion").strip()
                desc = str(s.get("description") or "").strip()
                stype = str(s.get("type") or "").strip()
                priority = str(s.get("priority") or "medium").strip()
                pemoji = {"high": "🔺", "medium": "🔸", "low": "🔹"}.get(priority, "•")
                line = f"{i}) {pemoji} *{title}*"
                if stype:
                    line += f"  (`{stype}`)"
                lines.append(line)
                if desc:
                    lines.append(f"   - {desc[:160]}{'…' if len(desc) > 160 else ''}")
                if s.get("config_path") and s.get("new_value") is not None:
                    lines.append(f"   - `{s['config_path']}` → `{s.get('new_value')}`")
        else:
            # Fallback: show recommendations from analysis
            rec_lines = 0
            for dim in dim_order:
                res = analysis.get(dim)
                if not isinstance(res, dict):
                    continue
                recs = res.get("recommendations", [])
                if not isinstance(recs, list):
                    continue
                for rec in recs[:2]:
                    if not isinstance(rec, dict):
                        continue
                    title = str(rec.get("title") or "Recommendation").strip()
                    rationale = str(rec.get("rationale") or "").strip()
                    lines.append(f"- *{title}*")
                    if rationale:
                        lines.append(f"  _{rationale[:160]}{'…' if len(rationale) > 160 else ''}_")
                    rec_lines += 1
                    if rec_lines >= 5:
                        break
                if rec_lines >= 5:
                    break
            if rec_lines == 0:
                lines.append("- ✅ No changes recommended right now.")

        lines += [
            "",
            "Use *More* for actions (export, discuss, patch, suggestions, backtests).",
        ]

        msg = "\n".join(lines)
        # Keep within Telegram comfort zone; detailed export is available via button.
        if len(msg) > 3800:
            msg = msg[:3800] + "\n…(truncated)  Tap Export for full details."
        return msg

    async def _handle_strategy_review(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Run a comprehensive strategy review and show top recommendations with action buttons."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(
            update,
            context,
            "🧠 *Strategy Review*\n\n🔄 Running analysis now…\n_This can take ~15–60s._",
            reply_markup=None,
        )

        monitor = self._get_claude_monitor()
        if not monitor:
            await self._send_message_or_edit(
                update,
                context,
                "🧠 *Strategy Review*\n\n❌ Claude Monitor not available.\n\n"
                "What to check:\n"
                "• Install extras: `pip install -e .[llm]`\n"
                "• Set `ANTHROPIC_API_KEY` in `.env` and restart the handler",
                reply_markup=self._get_back_to_menu_button(),
            )
            return

        try:
            lookback = 24
            if hasattr(context, "user_data"):
                try:
                    lookback = int(context.user_data.get("strategy_review_lookback_hours", 24) or 24)
                except Exception:
                    lookback = 24
            lookback = 24 if lookback <= 24 else 168

            # Force a fresh analysis (with lookback override)
            analysis = await monitor.force_analysis(lookback_hours=lookback)

            # Generate suggestions from the analysis and persist them (so /suggestions stays in sync)
            suggestions = monitor.suggestion_engine.generate(analysis)
            suggestions_dicts = [s.to_dict() for s in suggestions]
            monitor.monitor_state.record_analysis(analysis=analysis, suggestions=suggestions_dicts)

            # Store for export/autofix
            if hasattr(context, "user_data"):
                context.user_data["strategy_review_last_analysis"] = analysis
                context.user_data["strategy_review_last_suggestions"] = suggestions_dicts

                # Pre-compute an Auto Fix task from the top suggestion (if any)
                if suggestions_dicts:
                    top = suggestions_dicts[0]
                    title = str(top.get("title", "Improve the trading agent")).strip()
                    desc = str(top.get("description", "")).strip()
                    rationale = str(top.get("rationale", "")).strip()
                    cfg_path = top.get("config_path")
                    new_val = top.get("new_value")

                    extra = ""
                    if cfg_path and new_val is not None:
                        # Make config changes explicit and easy for Claude to patch.
                        extra = f"\n\nTarget change:\n- Update `config/config.yaml`: set `{cfg_path}` to `{new_val}`"

                    task = (
                        f"{title}\n\n"
                        f"{desc}\n\n"
                        f"Rationale: {rationale}"
                        f"{extra}\n\n"
                        "Please implement a minimal, safe change as a unified diff patch. "
                        "Prefer config-only changes when possible."
                    ).strip()
                    context.user_data["strategy_review_autofix_task"] = task
                else:
                    context.user_data.pop("strategy_review_autofix_task", None)

                # Identify a safe config-only suggestion (for one-tap config patch)
                config_candidate = None
                for s in suggestions_dicts:
                    try:
                        stype = str(s.get("type") or "")
                        cfg_path = s.get("config_path")
                        new_val = s.get("new_value")
                        if stype in ("config_change", "parameter_tune") and cfg_path and new_val is not None:
                            config_candidate = {
                                "title": s.get("title"),
                                "description": s.get("description"),
                                "rationale": s.get("rationale"),
                                "type": stype,
                                "priority": s.get("priority"),
                                "config_path": cfg_path,
                                "old_value": s.get("old_value"),
                                "new_value": new_val,
                            }
                            break
                    except Exception:
                        continue
                if config_candidate:
                    context.user_data["strategy_review_config_candidate"] = config_candidate
                else:
                    context.user_data.pop("strategy_review_config_candidate", None)

            message = self._format_strategy_review_message(analysis, suggestions_dicts, lookback_hours=lookback)

            # Buttons (keep Review screen compact; advanced actions live under "More")
            lb_24 = "⏱ 24h ✓" if lookback == 24 else "⏱ 24h"
            lb_7d = "🗓 7d ✓" if lookback != 24 else "🗓 7d"
            keyboard: List[List[InlineKeyboardButton]] = [
                [
                    InlineKeyboardButton(lb_24, callback_data="strategy_review:lookback:24"),
                    InlineKeyboardButton(lb_7d, callback_data="strategy_review:lookback:168"),
                ],
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="strategy_review:refresh"),
                    InlineKeyboardButton("➕ More", callback_data="strategy_review:more"),
                ],
                [InlineKeyboardButton("🏠 Menu", callback_data="start")],
            ]

            await self._send_message_or_edit(update, context, message, reply_markup=InlineKeyboardMarkup(keyboard))

        except Exception as e:
            logger.error(f"Error running strategy review: {e}", exc_info=True)
            await self._send_message_or_edit(
                update,
                context,
                f"🧠 *Strategy Review*\n\n❌ Error: `{str(e)[:200]}`",
                reply_markup=self._get_back_to_menu_button(),
            )

    async def _render_strategy_review_cached(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Re-render the Strategy Review using cached analysis (no recompute)."""
        if not await self._check_authorized(update):
            return

        analysis = context.user_data.get("strategy_review_last_analysis") if hasattr(context, "user_data") else None
        suggestions_dicts = context.user_data.get("strategy_review_last_suggestions") if hasattr(context, "user_data") else []

        if not isinstance(analysis, dict):
            await self._send_message_or_edit(
                update,
                context,
                "🧠 *Strategy Review*\n\nNo cached review found.\nTap *Refresh* to run it now.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="strategy_review:refresh")]]),
            )
            return

        lookback = 24
        if hasattr(context, "user_data"):
            try:
                lookback = int(context.user_data.get("strategy_review_lookback_hours", 24) or 24)
            except Exception:
                lookback = 24
        lookback = 24 if lookback <= 24 else 168

        message = self._format_strategy_review_message(analysis, suggestions_dicts or [], lookback_hours=lookback)

        # Buttons (keep Review screen compact; advanced actions live under "More")
        lb_24 = "⏱ 24h ✓" if lookback == 24 else "⏱ 24h"
        lb_7d = "🗓 7d ✓" if lookback != 24 else "🗓 7d"
        keyboard: List[List[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(lb_24, callback_data="strategy_review:lookback:24"),
                InlineKeyboardButton(lb_7d, callback_data="strategy_review:lookback:168"),
            ],
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="strategy_review:refresh"),
                InlineKeyboardButton("➕ More", callback_data="strategy_review:more"),
            ],
            [InlineKeyboardButton("🏠 Menu", callback_data="start")],
        ]

        await self._send_message_or_edit(update, context, message, reply_markup=InlineKeyboardMarkup(keyboard))

    async def _render_strategy_review_more_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show a minimal, action-oriented Strategy Review menu (button-first UX)."""
        if not await self._check_authorized(update):
            return

        claude_ok = bool(get_claude_client()) if ANTHROPIC_AVAILABLE else False

        message = """🧠 *Strategy Review — Next Steps*

Recommended flow:
1) 📉 *Backtest* (validate a change)
2) 📂 *Reports* (see results / breakdown)
3) 📄 *Export* (save/share)
"""
        if claude_ok:
            message += "\n💬 Claude can take ~1–2 minutes. If it times out, try later."
        else:
            message += "\n💬 Claude is currently unavailable (or disabled)."

        keyboard: List[List[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton("📉 Backtest", callback_data="backtest"),
                InlineKeyboardButton("📂 Reports", callback_data="reports"),
            ],
            [InlineKeyboardButton("📄 Export", callback_data="strategy_review:export")],
        ]
        if claude_ok:
            keyboard.append([InlineKeyboardButton("💬 Discuss with Claude", callback_data="strategy_review:discuss")])

        keyboard.append([InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")])
        keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data="start")])

        await self._send_message_or_edit(update, context, message, reply_markup=InlineKeyboardMarkup(keyboard))

    async def _handle_strategy_review_config_patch(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Confirm and explain a safe, config-only patch for the best config candidate."""
        if not await self._check_authorized(update):
            return

        cand = context.user_data.get("strategy_review_config_candidate") if hasattr(context, "user_data") else None
        if not isinstance(cand, dict):
            await self._send_message_or_edit(
                update,
                context,
                "⚙️ *Config Patch (Safe)*\n\nNo config recommendation found.\nRun *Refresh* first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="strategy_review:refresh")]]),
            )
            return

        cfg_path = cand.get("config_path")
        new_val = cand.get("new_value")
        old_val = cand.get("old_value")
        title = cand.get("title") or "Config change"

        message = (
            "⚙️ *Config Patch (Safe)*\n\n"
            "This generates a patch for `config/config.yaml` only.\n\n"
            f"*Suggestion:* {safe_label(str(title))}\n"
            f"*Path:* `{cfg_path}`\n"
            f"*Current:* `{old_val}`\n"
            f"*New:* `{new_val}`\n\n"
            "Proceed to generate the patch?"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Generate Patch", callback_data="strategy_review:config_patch:do")],
                [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
        )

        await self._send_message_or_edit(update, context, message, reply_markup=keyboard)

    async def _handle_strategy_review_config_patch_do(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Generate a config-only patch for the stored config candidate using Claude."""
        if not await self._check_authorized(update):
            return

        cand = context.user_data.get("strategy_review_config_candidate") if hasattr(context, "user_data") else None
        if not isinstance(cand, dict):
            await self._send_message_or_edit(
                update,
                context,
                "⚙️ *Config Patch (Safe)*\n\nNo config recommendation found.\nRun *Refresh* first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="strategy_review:refresh")]]),
            )
            return

        client = get_claude_client()
        if not client:
            await self._send_message_or_edit(
                update,
                context,
                "⚙️ *Config Patch (Safe)*\n\n❌ Claude not available.\n\n"
                "What to check:\n"
                "• Install extras: `pip install -e .[llm]`\n"
                "• Set `ANTHROPIC_API_KEY` in `.env` and restart the handler",
                reply_markup=self._get_claude_hub_buttons(),
            )
            return

        cfg_path = cand.get("config_path")
        new_val = cand.get("new_value")
        if not cfg_path or new_val is None:
            await self._send_message_or_edit(
                update,
                context,
                "⚙️ *Config Patch (Safe)*\n\nInvalid config recommendation (missing path/value).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")]]),
            )
            return

        await self._send_message_or_edit(
            update,
            context,
            "⚙️ *Config Patch (Safe)*\n\n🔄 Generating patch for `config/config.yaml`…",
            reply_markup=None,
        )

        # Read config file content
        project_root = Path(__file__).parent.parent.parent.parent
        config_path = project_root / "config" / "config.yaml"
        try:
            config_text = config_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            await self._send_message_or_edit(
                update,
                context,
                f"⚙️ *Config Patch (Safe)*\n\n❌ Could not read `config/config.yaml`: `{str(e)[:200]}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")]]),
            )
            return

        task = (
            "Update `config/config.yaml` only.\n"
            f"Set `{cfg_path}` to `{new_val}`.\n"
            "Preserve existing formatting/comments as much as possible.\n"
            "Output ONLY a unified diff patch."
        )

        import asyncio
        diff_output = await asyncio.to_thread(client.generate_patch, {"config/config.yaml": config_text}, str(task))
        if not diff_output or not diff_output.strip():
            await self._send_message_or_edit(
                update,
                context,
                "⚙️ *Config Patch (Safe)*\n\n⚠️ Claude returned an empty patch.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")]]),
            )
            return

        # Safety check: ensure patch touches only config/config.yaml
        touched = set()
        for line in diff_output.splitlines():
            if line.startswith("--- a/"):
                touched.add(line.replace("--- a/", "", 1).strip())
            if line.startswith("+++ b/"):
                touched.add(line.replace("+++ b/", "", 1).strip())
        touched.discard("/dev/null")
        if touched and any(p != "config/config.yaml" for p in touched):
            await self._send_message_or_edit(
                update,
                context,
                "⚙️ *Config Patch (Safe)*\n\n❌ Patch touched unexpected files.\n\n"
                "For safety, please use *Patch Wizard* instead.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🧩 Patch Wizard", callback_data="claude_patch_wizard")],
                        [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                    ]
                ),
            )
            return

        # Deliver patch
        INLINE_LIMIT = 3500
        back = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
        )

        if len(diff_output) <= INLINE_LIMIT:
            safe_diff = diff_output.replace("`", "'")
            msg = (
                "✅ *Config Patch Generated*\n\n"
                f"*Path:* `{cfg_path}`\n"
                f"*New:* `{new_val}`\n\n"
                f"```diff\n{safe_diff}\n```\n\n"
                "Apply on your computer with: `git apply config_patch.diff`"
            )
            await self._send_message_or_edit(update, context, msg, reply_markup=back)
        else:
            import io
            buf = io.BytesIO(diff_output.encode("utf-8"))
            buf.name = "config_patch.diff"
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=buf,
                filename="config_patch.diff",
                caption="✅ Config patch generated. Apply with: `git apply config_patch.diff`",
                parse_mode="Markdown",
            )
            await self._send_message_or_edit(update, context, "✅ *Config patch file sent above.*", reply_markup=back)

    def _coerce_backtest_df(self, historical_data: "pd.DataFrame") -> "pd.DataFrame":
        """Normalize historical data to a DatetimeIndex OHLCV frame for backtesting."""
        backtest_data = historical_data.copy()

        # Ensure timestamp is a DateTimeIndex
        if "timestamp" in backtest_data.columns:
            backtest_data["timestamp"] = pd.to_datetime(backtest_data["timestamp"])
            backtest_data = backtest_data.dropna(subset=["timestamp"]).set_index("timestamp")
        elif not isinstance(backtest_data.index, pd.DatetimeIndex):
            # Try converting index
            try:
                backtest_data.index = pd.to_datetime(backtest_data.index)
            except Exception:
                pass

        if not isinstance(backtest_data.index, pd.DatetimeIndex):
            raise ValueError(f"Could not convert data index to DatetimeIndex. Index type: {type(backtest_data.index)}")

        # Ensure required OHLCV columns exist (prefer lowercase for strategy/backtest stack)
        column_mapping = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
        for lower, upper in column_mapping.items():
            if upper in backtest_data.columns and lower not in backtest_data.columns:
                backtest_data[lower] = backtest_data[upper]
            if lower in backtest_data.columns and upper not in backtest_data.columns:
                backtest_data[upper] = backtest_data[lower]

        return backtest_data.sort_index()

    def _apply_variant_override_to_strategy_config(
        self,
        config: Any,
        config_path: str,
        new_value: Any,
    ) -> Any:
        """
        Apply a Strategy Review config_path override to an NQIntradayConfig instance (best-effort).

        Returns the mutated config (or a replaced config if needed).
        """
        try:
            path = str(config_path or "").strip()
        except Exception:
            path = ""
        if not path:
            return config

        # Map YAML-ish paths to NQIntradayConfig fields
        mapping = {
            # session.*
            "session.start_time": "start_time",
            "session.end_time": "end_time",
            # risk.*
            "risk.stop_loss_atr_multiplier": "stop_loss_atr_multiplier",
            "risk.take_profit_risk_reward": "take_profit_risk_reward",
            "risk.max_risk_per_trade": "max_risk_per_trade",
            "risk.max_position_size": "max_position_size",
            "risk.min_position_size": "min_position_size",
            "risk.stop_loss_ticks": "stop_loss_ticks",
            "risk.take_profit_ticks": "take_profit_ticks",
            # strategy.*
            "strategy.enable_dynamic_sizing": "enable_dynamic_sizing",
            "strategy.base_contracts": "base_contracts",
            "strategy.high_conf_contracts": "high_conf_contracts",
            "strategy.max_conf_contracts": "max_conf_contracts",
            "strategy.enabled_signals": "enabled_signals",
            "strategy.disabled_signals": "disabled_signals",
        }

        attr = mapping.get(path)
        if not attr and "." not in path:
            # allow direct field names like stop_loss_ticks
            attr = path

        if attr and hasattr(config, attr):
            try:
                current = getattr(config, attr)
                # Coerce type based on current value
                if isinstance(current, bool):
                    val = bool(new_value)
                elif isinstance(current, int):
                    val = int(new_value)
                elif isinstance(current, float):
                    val = float(new_value)
                elif isinstance(current, list):
                    val = list(new_value) if isinstance(new_value, (list, tuple)) else [str(new_value)]
                else:
                    val = new_value
                setattr(config, attr, val)
            except Exception:
                # Best-effort: ignore if coercion fails
                pass
        return config

    async def _handle_strategy_review_variant_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Run baseline vs variant backtest for the current Strategy Review config candidate."""
        if not await self._check_authorized(update):
            return

        cand = context.user_data.get("strategy_review_config_candidate") if hasattr(context, "user_data") else None
        if not isinstance(cand, dict):
            await self._send_message_or_edit(
                update,
                context,
                "🧪 *Backtest Variant*\n\nNo config recommendation found.\nRun *Refresh* first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="strategy_review:refresh")]]),
            )
            return

        cfg_path = str(cand.get("config_path") or "")
        new_val = cand.get("new_value")
        if not cfg_path or new_val is None:
            await self._send_message_or_edit(
                update,
                context,
                "🧪 *Backtest Variant*\n\nInvalid config recommendation (missing path/value).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")]]),
            )
            return

        # Backtest settings (reuse /backtest defaults)
        user_data = context.user_data if hasattr(context, "user_data") else {}
        try:
            weeks = int(user_data.get("strategy_review_variant_weeks", 2) or 2)
        except Exception:
            weeks = 2
        if weeks not in (1, 2, 4, 6):
            weeks = 2

        mode = (user_data.get("backtest_mode") or "5m") if hasattr(context, "user_data") else "5m"
        if mode not in ("5m", "1m"):
            mode = "5m"

        try:
            pos_size = int(user_data.get("backtest_contracts", 5) or 5)
        except Exception:
            pos_size = 5
        if pos_size not in (1, 5, 10):
            pos_size = 5

        try:
            slippage_ticks = float(user_data.get("backtest_slippage_ticks", 0.5) or 0.5)
        except Exception:
            slippage_ticks = 0.5
        if slippage_ticks not in (0.5, 1.0):
            slippage_ticks = 0.5

        try:
            max_pos = int(user_data.get("backtest_max_positions", 1) or 1)
        except Exception:
            max_pos = 1
        if max_pos not in (1, 2, 3):
            max_pos = 1

        symbol = user_data.get("backtest_symbol", "MNQ") if hasattr(context, "user_data") else "MNQ"
        if symbol not in ("MNQ", "NQ"):
            symbol = "MNQ"
        tick_value = 2.0 if symbol == "MNQ" else 20.0

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(
            update,
            context,
            "🧪 *Backtest Variant*\n\n"
            f"Change: `{cfg_path}` → `{new_val}`\n"
            f"Window: `{weeks}w` • Mode: `{mode}` • Contracts: `{pos_size}`\n\n"
            "🔄 Fetching historical data…",
            reply_markup=None,
        )

        # Fetch data (reuse existing fetcher)
        historical_data = await self._fetch_historical_data_for_backtest(
            symbol="MNQ" if symbol == "MNQ" else "NQ",
            weeks=weeks,
            timeframe="1m",
        )
        if historical_data is None or historical_data.empty:
            await self._send_message_or_edit(
                update,
                context,
                "🧪 *Backtest Variant*\n\n❌ Could not fetch historical data.\n\nTry a shorter window or retry later.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔄 Retry", callback_data="strategy_review:variant_backtest")],
                        [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                    ]
                ),
            )
            return

        backtest_data = self._coerce_backtest_df(historical_data)

        from pearlalgo.strategies.nq_intraday.backtest_adapter import run_full_backtest, run_full_backtest_5m_decision
        from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
        from pearlalgo.config.config_loader import service_config_override

        # Baseline config (from file)
        base_cfg = NQIntradayConfig.from_config_file()
        var_cfg = NQIntradayConfig.from_config_file()

        # Apply override to strategy config when relevant
        var_cfg = self._apply_variant_override_to_strategy_config(var_cfg, cfg_path, new_val)

        # Apply override to service config when relevant (signals.*)
        service_override: Dict[str, Any] = {}
        if cfg_path.startswith("signals."):
            key = cfg_path.split("signals.", 1)[1]
            service_override = {"signals": {key: new_val}}

        # Run baseline
        await self._send_message_or_edit(
            update,
            context,
            "🧪 *Backtest Variant*\n\n"
            f"Change: `{cfg_path}` → `{new_val}`\n"
            f"Window: `{weeks}w` • Mode: `{mode}`\n\n"
            "1/2 Running *baseline* backtest…",
            reply_markup=None,
        )

        if mode == "5m":
            base_res = run_full_backtest_5m_decision(
                backtest_data,
                config=base_cfg,
                position_size=pos_size,
                tick_value=tick_value,
                slippage_ticks=slippage_ticks,
                max_concurrent_trades=max_pos,
                return_trades=False,
                decision_rule="5min",
                context_rule_1="1h",
                context_rule_2="4h",
            )
        else:
            base_res = run_full_backtest(
                backtest_data,
                config=base_cfg,
                position_size=pos_size,
                tick_value=tick_value,
                slippage_ticks=slippage_ticks,
                max_concurrent_trades=max_pos,
                return_trades=False,
            )

        # Run variant (with override)
        await self._send_message_or_edit(
            update,
            context,
            "🧪 *Backtest Variant*\n\n"
            f"Change: `{cfg_path}` → `{new_val}`\n"
            f"Window: `{weeks}w` • Mode: `{mode}`\n\n"
            "2/2 Running *variant* backtest…",
            reply_markup=None,
        )

        if service_override:
            with service_config_override(service_override):
                if mode == "5m":
                    var_res = run_full_backtest_5m_decision(
                        backtest_data,
                        config=var_cfg,
                        position_size=pos_size,
                        tick_value=tick_value,
                        slippage_ticks=slippage_ticks,
                        max_concurrent_trades=max_pos,
                        return_trades=False,
                        decision_rule="5min",
                        context_rule_1="1h",
                        context_rule_2="4h",
                    )
                else:
                    var_res = run_full_backtest(
                        backtest_data,
                        config=var_cfg,
                        position_size=pos_size,
                        tick_value=tick_value,
                        slippage_ticks=slippage_ticks,
                        max_concurrent_trades=max_pos,
                        return_trades=False,
                    )
        else:
            if mode == "5m":
                var_res = run_full_backtest_5m_decision(
                    backtest_data,
                    config=var_cfg,
                    position_size=pos_size,
                    tick_value=tick_value,
                    slippage_ticks=slippage_ticks,
                    max_concurrent_trades=max_pos,
                    return_trades=False,
                    decision_rule="5min",
                    context_rule_1="1h",
                    context_rule_2="4h",
                )
            else:
                var_res = run_full_backtest(
                    backtest_data,
                    config=var_cfg,
                    position_size=pos_size,
                    tick_value=tick_value,
                    slippage_ticks=slippage_ticks,
                    max_concurrent_trades=max_pos,
                    return_trades=False,
                )

        def _f(x: Any, fmt: str) -> str:
            try:
                if x is None:
                    return "n/a"
                return format(float(x), fmt)
            except Exception:
                return "n/a"

        def _d(a: Any, b: Any) -> str:
            try:
                if a is None or b is None:
                    return ""
                diff = float(b) - float(a)
                sign = "+" if diff >= 0 else ""
                return f" ({sign}{diff:.2f})"
            except Exception:
                return ""

        # Compare key metrics
        msg = (
            "🧪 *Backtest Variant Results*\n\n"
            f"Change: `{cfg_path}` → `{new_val}`\n"
            f"Window: `{weeks}w` • Mode: `{mode}` • Contracts: `{pos_size}` • Max pos: `{max_pos}`\n\n"
            "*Baseline vs Variant:*\n"
            f"• Trades: `{base_res.total_trades or 0}` → `{var_res.total_trades or 0}`\n"
            f"• Win rate: `{_f(base_res.win_rate, '.1%')}` → `{_f(var_res.win_rate, '.1%')}`\n"
            f"• Total P&L: `{_format_currency(float(base_res.total_pnl or 0.0))}` → `{_format_currency(float(var_res.total_pnl or 0.0))}`{_d(base_res.total_pnl, var_res.total_pnl)}\n"
            f"• Profit factor: `{_f(base_res.profit_factor, '.2f')}` → `{_f(var_res.profit_factor, '.2f')}`\n"
            f"• Max DD: `{_format_currency(float(base_res.max_drawdown or 0.0))}` → `{_format_currency(float(var_res.max_drawdown or 0.0))}`\n"
        )

        # Verdict (simple)
        verdict = ""
        try:
            pnl_diff = float(var_res.total_pnl or 0.0) - float(base_res.total_pnl or 0.0)
            if pnl_diff > 0:
                verdict = f"\n🟢 *Verdict:* Variant improved P&L by {_format_currency(pnl_diff)}"
            elif pnl_diff < 0:
                verdict = f"\n🔴 *Verdict:* Variant reduced P&L by {_format_currency(pnl_diff)}"
            else:
                verdict = "\n⚪ *Verdict:* No P&L change"
        except Exception:
            verdict = ""

        msg += verdict

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                [
                    InlineKeyboardButton("✅ Apply Change", callback_data="strategy_review:apply_candidate"),
                    InlineKeyboardButton("⚙️ Config Patch (Safe)", callback_data="strategy_review:config_patch"),
                ],
                [InlineKeyboardButton("📉 Backtest", callback_data="backtest")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
        )

        await self._send_message_or_edit(update, context, msg, reply_markup=keyboard)

    async def _handle_strategy_review_apply_candidate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Confirm applying the current Strategy Review config candidate (tap-to-approve)."""
        if not await self._check_authorized(update):
            return

        cand = context.user_data.get("strategy_review_config_candidate") if hasattr(context, "user_data") else None
        if not isinstance(cand, dict):
            await self._send_message_or_edit(
                update,
                context,
                "✅ *Apply Change*\n\nNo config recommendation found.\nRun *Refresh* first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Run Review", callback_data="strategy_review")]]),
            )
            return

        cfg_path = cand.get("config_path")
        new_val = cand.get("new_value")
        old_val = cand.get("old_value")
        title = safe_label(str(cand.get("title") or "Config change"))

        if not cfg_path or new_val is None:
            await self._send_message_or_edit(
                update,
                context,
                "✅ *Apply Change*\n\nInvalid config recommendation (missing path/value).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")]]),
            )
            return

        msg = (
            "✅ *Apply Change*\n\n"
            "This will update `config/config.yaml` via the policy-gated executor.\n\n"
            f"*Suggestion:* {title}\n"
            f"*Path:* `{cfg_path}`\n"
            f"*Current:* `{old_val}`\n"
            f"*New:* `{new_val}`\n\n"
            "Proceed?"
        )

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Apply", callback_data="strategy_review:apply_candidate:do"),
                    InlineKeyboardButton("🧪 Dry-run", callback_data="strategy_review:apply_candidate:dry"),
                ],
                [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
        )
        await self._send_message_or_edit(update, context, msg, reply_markup=kb)

    async def _handle_strategy_review_apply_candidate_do(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        dry_run: bool = False,
    ) -> None:
        """Apply (or dry-run) the Strategy Review config candidate."""
        if not await self._check_authorized(update):
            return

        cand = context.user_data.get("strategy_review_config_candidate") if hasattr(context, "user_data") else None
        if not isinstance(cand, dict):
            await self._send_message_or_edit(
                update,
                context,
                "✅ *Apply Change*\n\nNo config recommendation found.\nRun *Refresh* first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Run Review", callback_data="strategy_review")]]),
            )
            return

        cfg_path = str(cand.get("config_path") or "").strip()
        new_val = cand.get("new_value")
        old_val = cand.get("old_value")

        if not cfg_path or new_val is None:
            await self._send_message_or_edit(
                update,
                context,
                "✅ *Apply Change*\n\nInvalid config recommendation (missing path/value).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")]]),
            )
            return

        monitor = self._get_claude_monitor()
        if not monitor:
            await self._send_message_or_edit(
                update,
                context,
                "✅ *Apply Change*\n\n❌ Claude monitor not available.",
                reply_markup=self._get_claude_hub_buttons(show_monitor=True),
            )
            return

        await self._send_message_or_edit(
            update,
            context,
            f"⏳ {'Dry-running' if dry_run else 'Applying'} `{cfg_path}`…",
            reply_markup=None,
        )

        # Optional policy pre-check (even for dry-run) so the preview matches reality.
        if monitor.action_executor._policy:
            try:
                agent_state = self.state_manager.load_state() or {}
                decision = monitor.action_executor._policy.check_change(
                    config_path=cfg_path,
                    old_value=old_val,
                    new_value=new_val,
                    agent_state=agent_state,
                )
                if not decision.allowed:
                    await self._send_message_or_edit(
                        update,
                        context,
                        "🚫 *Policy Rejected*\n\n"
                        f"*Path:* `{cfg_path}`\n"
                        f"*Reason:* {safe_label(decision.reason)}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")]]),
                    )
                    return
                if decision.bounded_value is not None:
                    new_val = decision.bounded_value
            except Exception as e:
                logger.debug(f"Policy pre-check failed (best-effort): {e}")

        from pearlalgo.claude_monitor.action_executor import ActionRequest, ActionType

        request = ActionRequest(
            action_type=ActionType.CONFIG_UPDATE,
            description=f"Strategy Review apply: {cfg_path}",
            changes={"source": "strategy_review"},
            config_path=cfg_path,
            old_value=old_val,
            new_value=new_val,
            dry_run=dry_run,
        )

        result = await monitor.action_executor.execute(request)

        if result.success:
            header = "🧪 *Dry-run Complete*" if dry_run else "✅ *Config Updated*"
            lines = [
                header,
                "",
                f"*Path:* `{cfg_path}`",
                f"*New:* `{new_val}`",
            ]
            if not dry_run:
                lines += [
                    "",
                    f"*Request ID:* `{result.request_id}`",
                    f"🔄 Rollback: `/rollback_suggestion {result.request_id}`",
                ]
            else:
                lines.append("")
                lines.append(f"_{safe_label(str(result.message)[:240])}_")

            rows: List[List[InlineKeyboardButton]] = [
                [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
            ]
            if not dry_run:
                rows.append([InlineKeyboardButton("🔄 Rollback", callback_data=f"sug:rollback:{result.request_id}")])
            rows += [
                [InlineKeyboardButton("📋 Suggestions", callback_data="claude_suggestions")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
            kb = InlineKeyboardMarkup(rows)
            await self._send_message_or_edit(update, context, "\n".join(lines), reply_markup=kb)
            return

        await self._send_message_or_edit(
            update,
            context,
            "❌ *Apply Failed*\n\n"
            f"*Path:* `{cfg_path}`\n"
            f"*Error:* {safe_label(str(result.error or result.message)[:240])}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")]]),
        )

    async def _handle_strategy_review_export(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Export the last strategy review (analysis + suggestions) as a file for sharing/offline use."""
        if not await self._check_authorized(update):
            return

        analysis = context.user_data.get("strategy_review_last_analysis") if hasattr(context, "user_data") else None
        suggestions = context.user_data.get("strategy_review_last_suggestions") if hasattr(context, "user_data") else None

        if not isinstance(analysis, dict):
            await self._send_message_or_edit(
                update,
                context,
                "📄 *Export*\n\nNo recent Strategy Review found.\nTap *Refresh* first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Run Review", callback_data="strategy_review")]]),
            )
            return

        payload = {
            "exported_at": get_utc_timestamp(),
            "analysis": analysis,
            "suggestions": suggestions or [],
        }

        import io
        content = json.dumps(payload, indent=2, default=str)
        buf = io.BytesIO(content.encode("utf-8"))
        buf.name = "strategy_review.json"

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=buf,
            filename="strategy_review.json",
            caption="📄 Strategy Review export (share this with ChatGPT/Claude on desktop).",
        )

    async def _handle_strategy_review_autofix(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Generate an automatic code patch for the top recommendation."""
        if not await self._check_authorized(update):
            return

        task = context.user_data.get("strategy_review_autofix_task") if hasattr(context, "user_data") else None
        if not task:
            await self._send_message_or_edit(
                update,
                context,
                "🧩 *Auto Fix*\n\nNo Auto Fix task available.\nRun *Strategy Review* first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Run Review", callback_data="strategy_review")]]),
            )
            return

        if not ANTHROPIC_AVAILABLE:
            await self._send_message_or_edit(
                update,
                context,
                "🧩 *Auto Fix*\n\n❌ Claude not available.\nInstall with: `pip install -e .[llm]`",
                reply_markup=self._get_claude_hub_buttons(),
            )
            return

        # Reuse the existing auto-patch flow (now supports callback triggers)
        await self._process_auto_patch(update, context, str(task))

    async def _handle_strategy_review_discuss(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Ask Claude for a clear plan based on the last Strategy Review output."""
        if not await self._check_authorized(update):
            return

        analysis = context.user_data.get("strategy_review_last_analysis") if hasattr(context, "user_data") else None
        suggestions = context.user_data.get("strategy_review_last_suggestions") if hasattr(context, "user_data") else None

        if not isinstance(analysis, dict):
            await self._send_message_or_edit(
                update,
                context,
                "💬 *Discuss with Claude*\n\nNo recent Strategy Review found.\nTap *Refresh* first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Run Review", callback_data="strategy_review")]]),
            )
            return

        client = get_claude_client()
        if not client:
            await self._send_message_or_edit(
                update,
                context,
                "💬 *Discuss with Claude*\n\n❌ Claude not available.\n\n"
                "What to check:\n"
                "• Install extras: `pip install -e .[llm]`\n"
                "• Set `ANTHROPIC_API_KEY` in `.env` and restart the handler",
                reply_markup=self._get_claude_hub_buttons(),
            )
            return

        # Build a concise prompt
        lookback = 24
        if hasattr(context, "user_data"):
            try:
                lookback = int(context.user_data.get("strategy_review_lookback_hours", 24) or 24)
            except Exception:
                lookback = 24
        lookback = 24 if lookback <= 24 else 168

        # Include only compact pieces to keep token usage reasonable
        payload = {
            "lookback_hours": lookback,
            "analysis": analysis,
            "suggestions": suggestions or [],
        }

        user_text = (
            "You are my trading strategy assistant.\n"
            "Using the Strategy Review JSON below, write a SHORT, Telegram-friendly update.\n"
            "Output MUST be plain text (no markdown like ## or **).\n"
            "Max 10 lines.\n\n"
            "Format:\n"
            "Summary: <1-2 sentences>\n"
            "Next 24h:\n"
            "- <3 bullets>\n"
            "Experiments:\n"
            "- <2 bullets (change + success metric)>\n\n"
            "Strategy Review JSON:\n"
            f"{json.dumps(payload, default=str)[:4000]}"
        )

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # Use the same persistent history as normal chat so follow-ups continue naturally
        chat_history: List[Dict[str, str]] = []
        if hasattr(context, "user_data") and "claude_chat_history" in context.user_data:
            raw = context.user_data.get("claude_chat_history")
            if isinstance(raw, list):
                chat_history = raw
        else:
            chat_history = self._load_persistent_claude_chat_history()
            if hasattr(context, "user_data"):
                context.user_data["claude_chat_history"] = chat_history

        chat_history.append({"role": "user", "content": user_text})
        if len(chat_history) > 24:
            chat_history = chat_history[-24:]

        system_prompt = build_chat_system_prompt(
            system_snapshot=self._build_ai_chat_snapshot(),
            memory_summary=self._load_claude_memory_summary(),
        )

        import asyncio

        # UX: show an immediate progress message so it never feels like the button "did nothing".
        try:
            await self._send_message_or_edit(
                update,
                context,
                """💬 *Discuss with Claude*

⏳ Asking Claude… (can take up to ~2 minutes)

_Wait for the response — or tap below if you'd rather not wait._""",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("📄 Export", callback_data="strategy_review:export"),
                            InlineKeyboardButton("📉 Backtest", callback_data="backtest"),
                        ],
                        [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                        [InlineKeyboardButton("🏠 Menu", callback_data="start")],
                    ]
                ),
            )
        except Exception:
            # Best-effort only; do not block Claude call
            pass

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(client.chat, chat_history, system_prompt),
                timeout=140.0,
            )
        except asyncio.TimeoutError:
            await self._send_message_or_edit(
                update,
                context,
                """💬 *Discuss with Claude*

⏱️ Claude timed out (~2 min limit).

*What to do instead:*
• Use 📄 *Export* to save/share this review
• Try 📉 *Backtest* or 📂 *Reports* for quick insights
• Or try again later when load is lower""",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("📄 Export", callback_data="strategy_review:export"),
                            InlineKeyboardButton("📉 Backtest", callback_data="backtest"),
                        ],
                        [InlineKeyboardButton("🔄 Try Again", callback_data="strategy_review:discuss")],
                        [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                        [InlineKeyboardButton("🏠 Menu", callback_data="start")],
                    ]
                ),
            )
            return
        except ClaudeAPIError as e:
            await self._send_message_or_edit(
                update,
                context,
                f"💬 *Discuss with Claude*\n\n❌ Claude error: `{str(e)[:120]}`\n\n"
                "*Alternatives:* use 📄 *Export* or try again later.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("📄 Export", callback_data="strategy_review:export"),
                            InlineKeyboardButton("🔄 Try Again", callback_data="strategy_review:discuss"),
                        ],
                        [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                        [InlineKeyboardButton("🏠 Menu", callback_data="start")],
                    ]
                ),
            )
            return
        except Exception as e:
            await self._send_message_or_edit(
                update,
                context,
                f"💬 *Discuss with Claude*\n\n❌ Unexpected error: `{str(e)[:120]}`\n\n"
                "Use 📄 *Export* instead or try again later.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("📄 Export", callback_data="strategy_review:export"),
                            InlineKeyboardButton("🔄 Try Again", callback_data="strategy_review:discuss"),
                        ],
                        [InlineKeyboardButton("⬅️ Back to Review", callback_data="strategy_review:show")],
                        [InlineKeyboardButton("🏠 Menu", callback_data="start")],
                    ]
                ),
            )
            return

        chat_history.append({"role": "assistant", "content": response})

        if hasattr(context, "user_data"):
            context.user_data["claude_chat_history"] = chat_history
        self._save_persistent_claude_chat_history(chat_history)

        # Send response as a new message (keep Strategy Review message intact)
        chat_controls = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("💬 Chat with Claude", callback_data="claude_hub"),
                    InlineKeyboardButton("🧠 Review", callback_data="strategy_review"),
                ],
                [
                    InlineKeyboardButton("📉 Backtest", callback_data="backtest"),
                    InlineKeyboardButton("📂 Reports", callback_data="reports"),
                ],
                [InlineKeyboardButton("🏠 Menu", callback_data="start")],
            ]
        )

        if len(response) > 4000:
            import io
            buf = io.BytesIO(response.encode("utf-8"))
            buf.name = "claude_strategy_review.txt"
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=buf,
                filename="claude_strategy_review.txt",
                caption="📝 Claude response was long; sent as file.",
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⬅️ Use buttons below to navigate.",
                reply_markup=chat_controls,
            )
        else:
            # Keep the response mobile-friendly and free of Markdown artifacts
            # (Telegram doesn't support GitHub-style markdown like ## / **).
            response_short = self._format_telegram_plaintext(response, max_lines=10, max_chars=1600)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=response_short,
                reply_markup=chat_controls,
            )
    
    async def _handle_claude_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude_reports - Configure daily/weekly reports."""
        if not await self._check_authorized(update):
            return
        
        logger.info(f"📡 Received /claude_reports command from {update.effective_user.id}")
        
        try:
            monitor = self._get_claude_monitor()
            
            if not monitor:
                await update.message.reply_text("❌ Claude monitor not available")
                return
            
            # Show current report settings
            daily_emoji = "✅" if monitor.daily_report_enabled else "❌"
            weekly_emoji = "✅" if monitor.weekly_report_enabled else "❌"
            
            message = (
                "📊 *Claude Report Settings*\n\n"
                f"{daily_emoji} Daily Report: `{'Enabled' if monitor.daily_report_enabled else 'Disabled'}`\n"
                f"   Time: `{monitor.daily_report_time} ET`\n\n"
                f"{weekly_emoji} Weekly Report: `{'Enabled' if monitor.weekly_report_enabled else 'Disabled'}`\n"
                f"   Day: `{monitor.weekly_report_day.title()}`\n"
                f"   Time: `{monitor.weekly_report_time} ET`\n\n"
                "_Configure in `config/config.yaml` under `claude_monitor:`_"
            )
            
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error handling /claude_reports: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def start(self):
        """Start the command handler (polling for updates)."""
        logger.info("Starting Telegram command handler...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Telegram command handler started (polling)")
    
    async def stop(self):
        """Stop the command handler."""
        logger.info("Stopping Telegram command handler...")
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
        logger.info("Telegram command handler stopped")
    
    def run(self):
        """Run the command handler (blocking)."""
        logger.info("Starting Telegram command handler...")
        logger.info(f"Listening for commands from chat ID: {self.chat_id}")
        logger.info("Press Ctrl+C to stop")
        try:
            self.application.run_polling(
                drop_pending_updates=True,  # Ignore old messages when starting
                allowed_updates=["message", "callback_query"]  # Only listen to these update types
            )
        except KeyboardInterrupt:
            logger.info("Command handler stopped by user")
        except Exception as e:
            logger.error(f"Command handler error: {e}", exc_info=True)
            raise


def main():
    """Main entry point for running command handler as standalone service."""
    import os
    import sys
    from pathlib import Path
    
    # Try loading from .env
    try:
        from dotenv import load_dotenv
        project_root = Path(__file__).parent.parent.parent.parent
        load_dotenv(project_root / ".env")
    except ImportError:
        pass

    # Optional: configure market-hours overrides from config/config.yaml (disabled by default).
    # This preserves the module boundary: utils never imports config.
    try:
        from pearlalgo.config.config_loader import load_market_hours_overrides
        from pearlalgo.utils.market_hours import configure_market_hours

        holidays, early_closes = load_market_hours_overrides(validate=False)
        configure_market_hours(holiday_overrides=holidays, early_closes=early_closes)
    except Exception as e:
        logger.warning(f"Could not configure market hours overrides: {e}")
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required")
        print("Set them in .env file or environment variables")
        sys.exit(1)
    
    handler = TelegramCommandHandler(
        bot_token=bot_token,
        chat_id=chat_id,
    )
    
    try:
        handler.run()
    except KeyboardInterrupt:
        print("\nShutting down command handler...")
    except Exception as e:
        logger.error(f"Command handler error: {e}", exc_info=True)


if __name__ == "__main__":
    main()



