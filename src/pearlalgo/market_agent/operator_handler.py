"""
Operator Handler - Process operator requests extracted from MarketAgentService.

Handles grade requests from Telegram /grade command and Pearl suggestion
feedback from the web API.  Receives all dependencies via constructor injection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.state_io import (
    atomic_write_jsonl,
    file_lock,
    load_json_file,
    load_jsonl_file,
)
from pearlalgo.market_agent.notification_queue import Priority

if TYPE_CHECKING:
    from pearlalgo.market_agent.notification_queue import NotificationQueue
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager


class OperatorHandler:
    """Processes operator request files written by Telegram or the web API."""

    def __init__(
        self,
        *,
        state_manager: MarketAgentStateManager,
        notification_queue: NotificationQueue,
        get_status_snapshot: Optional[Callable[[], Dict]] = None,
    ):
        self.state_manager = state_manager
        self.notification_queue = notification_queue
        self._get_status_snapshot = get_status_snapshot or (lambda: {})

    # ------------------------------------------------------------------
    # Grade Request
    # ------------------------------------------------------------------

    async def process_grade_request(self, grade_file: Path) -> None:
        """Process a grade request from Telegram /grade command.

        The grade request contains:
        - signal_id: The signal to grade
        - signal_type: The type of signal
        - is_win: Whether it was a win
        - pnl: Optional P&L value
        - force: Whether to log even if signal already exited
        """
        try:
            grade_req = load_json_file(Path(grade_file))

            signal_id = grade_req.get("signal_id", "")
            signal_type = grade_req.get("signal_type", "unknown")
            is_win = grade_req.get("is_win", False)
            pnl = grade_req.get("pnl")
            force = grade_req.get("force", False)

            logger.info(f"Processing grade request: {signal_id} -> {'win' if is_win else 'loss'} (force={force})")

            # Check if signal already has an exit recorded (latest status per signal_id wins)
            already_exited = False
            try:
                recent_signals = self.state_manager.get_recent_signals(limit=500)
                for record in recent_signals:
                    if isinstance(record, dict) and record.get("signal_id") == signal_id:
                        already_exited = record.get("status") == "exited"
                        # Do not break: keep updating so last occurrence (latest status) wins
            except Exception as e:
                logger.warning(f"Failed to check signal exit status: {e}")

            processed = True

            # Update feedback.jsonl to mark the request as processed.
            feedback_file = self.state_manager.state_dir / "feedback.jsonl"
            if feedback_file.exists():
                try:
                    lock_path = Path(str(feedback_file) + ".lock")
                    with file_lock(lock_path):
                        records = load_jsonl_file(feedback_file, max_lines=50000)
                        for rec in records:
                            if rec.get("signal_id") == signal_id and not rec.get("processed"):
                                for key in list(rec.keys()):
                                    if str(key).startswith("applied_"):
                                        rec.pop(key, None)
                                rec["processed"] = processed
                                rec["processed_at"] = datetime.now(timezone.utc).isoformat()
                        atomic_write_jsonl(feedback_file, records)
                except Exception as e:
                    logger.warning(f"Could not update feedback file: {e}")

            # Notify via Telegram
            try:
                await self.notification_queue.enqueue_raw_message(
                    f"\u2139\ufe0f *Grade Logged*\n\n"
                    f"Signal: `{signal_id[:25]}...`\n"
                    f"Type: `{signal_type}`\n"
                    f"Outcome: {'Win' if is_win else 'Loss'}\n"
                    f"Feedback recorded.",
                    parse_mode="Markdown",
                    priority=Priority.NORMAL,
                )
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

        except Exception as e:
            logger.error(f"Error processing grade request: {e}", exc_info=True)
        finally:
            grade_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Close Trade Requests
    # ------------------------------------------------------------------

    async def process_close_trade_requests(self, state_dir: Path) -> None:
        """Process close_trade request files written by the web API.

        Reads ``operator_requests/close_trade_*.json`` files, extracts signal_ids,
        and appends them to ``close_signals_requested`` in state.json so that the
        main agent loop can close the positions (virtual + broker).
        """
        req_dir = Path(state_dir) / "operator_requests"
        if not req_dir.exists():
            return

        try:
            files = sorted([p for p in req_dir.glob("close_trade_*.json") if p.is_file()])
        except Exception as e:
            logger.warning(f"Failed listing close_trade files: {e}")
            return

        if not files:
            return

        new_signal_ids: list[str] = []
        for fp in files[:50]:
            try:
                rec = load_json_file(fp)
                if not isinstance(rec, dict):
                    continue

                signal_id = str(rec.get("signal_id") or "").strip()
                if not signal_id:
                    logger.warning(f"close_trade request missing signal_id: {fp.name}")
                    continue

                new_signal_ids.append(signal_id)
                logger.info(f"Ingested close_trade request: signal_id={signal_id} from {fp.name}")
            except Exception as e:
                logger.warning(f"Failed to process close_trade request {fp.name}: {e}")
            finally:
                try:
                    fp.unlink(missing_ok=True)
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

        if not new_signal_ids:
            return

        # Merge into close_signals_requested in state.json
        try:
            state = self.state_manager.load_state()
            if not isinstance(state, dict):
                state = {}
            existing = list(state.get("close_signals_requested", []))
            # Deduplicate while preserving order
            merged = list(dict.fromkeys(existing + new_signal_ids))
            state["close_signals_requested"] = merged
            state["close_signals_requested_time"] = datetime.now(timezone.utc).isoformat()
            self.state_manager.save_state(state)
            logger.info(f"Updated close_signals_requested: {merged}")
        except Exception as e:
            logger.error(f"Failed to update close_signals_requested in state: {e}")

    # ------------------------------------------------------------------
    # Close All Flag (web API → state.json bridge)
    # ------------------------------------------------------------------

    async def process_close_all_flag(self, state_dir: Path) -> None:
        """Ingest ``close_all_request.flag`` written by the web API.

        The web API writes a flag file instead of editing state.json directly
        (to avoid race conditions with the agent).  This method reads the flag
        and sets ``close_all_requested=True`` in state.json so the main agent
        loop can process it.
        """
        flag_file = Path(state_dir) / "close_all_request.flag"
        if not flag_file.exists():
            return

        try:
            state = self.state_manager.load_state()
            if not isinstance(state, dict):
                state = {}
            state["close_all_requested"] = True
            state["close_all_requested_time"] = datetime.now(timezone.utc).isoformat()
            self.state_manager.save_state(state)
            logger.info("Ingested close_all_request.flag → close_all_requested=True in state")
        except Exception as e:
            logger.error(f"Failed to set close_all_requested in state: {e}")
        finally:
            try:
                flag_file.unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

    # ------------------------------------------------------------------
    # Operator Requests (Pearl suggestion feedback)
    # ------------------------------------------------------------------

    async def process_operator_requests(self, state_dir: Path) -> None:
        """Process operator request files written by the web API server.

        This is intentionally **shadow-only** feedback collection and MUST NOT
        affect live trading decisions.
        """
        req_dir = Path(state_dir) / "operator_requests"
        if not req_dir.exists():
            return

        try:
            files = sorted([p for p in req_dir.glob("pearl_suggestion_feedback_*.json") if p.is_file()])
        except Exception as e:
            logger.warning(f"Failed listing pearl_suggestion_feedback files: {e}")
            return

        if not files:
            return

        snap = {}
        try:
            snap = self._get_status_snapshot() or {}
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            snap = {}

        shadow_context = {
            "daily_pnl": snap.get("daily_pnl", 0),
            "wins_today": snap.get("wins_today", 0),
            "losses_today": snap.get("losses_today", 0),
            "active_positions": snap.get("active_trades_count", 0) or 0,
        }

        for fp in files[:50]:
            try:
                rec = load_json_file(fp)
                if not isinstance(rec, dict):
                    continue

                if str(rec.get("type") or "") != "pearl_suggestion_feedback":
                    continue

                action = str(rec.get("action") or "").strip().lower()
                suggestion_id = str(rec.get("suggestion_id") or "").strip()
                if not action or not suggestion_id:
                    continue

                if action in ("accept", "dismiss"):
                    logger.info(f"[Pearl] Suggestion {action}ed: {suggestion_id}")
                else:
                    logger.warning(f"[Pearl] Unknown suggestion feedback action: {action}")
            except Exception as e:
                logger.warning(f"[Pearl] Failed to process operator request {fp.name}: {e}")
            finally:
                try:
                    fp.unlink(missing_ok=True)
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")
