"""
Scheduled Tasks - Time-based tasks extracted from MarketAgentService.

Handles morning briefings, market close summaries, and follower heartbeat
checks.  Receives all dependencies via constructor injection.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.market_hours import get_market_hours
from pearlalgo.utils.paths import get_utc_timestamp, parse_utc_timestamp
from pearlalgo.market_agent.notification_queue import Priority
from pearlalgo.market_agent.state_reader import StateReader

if TYPE_CHECKING:
    from pearlalgo.market_agent.audit_logger import AuditLogger
    from pearlalgo.market_agent.notification_queue import NotificationQueue
    from pearlalgo.market_agent.performance_tracker import PerformanceTracker
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager
    from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier


class ScheduledTasks:
    """Time-triggered tasks that run on each service cycle."""

    def __init__(
        self,
        *,
        telegram_notifier: MarketAgentTelegramNotifier,
        notification_queue: NotificationQueue,
        state_manager: MarketAgentStateManager,
        performance_tracker: PerformanceTracker,
        service_config: Dict[str, Any],
        # Follower-mode fields
        signal_follower_mode: bool = False,
        follower_heartbeat_timeout_minutes: int = 30,
    ):
        self.telegram_notifier = telegram_notifier
        self.notification_queue = notification_queue
        self.state_manager = state_manager
        self.performance_tracker = performance_tracker
        self._service_config = service_config

        # Audit logger (optional)
        self._audit_logger: Optional["AuditLogger"] = None

        # Follower heartbeat state
        self._signal_follower_mode = signal_follower_mode
        self._follower_heartbeat_timeout_minutes = follower_heartbeat_timeout_minutes
        self._follower_last_signal_at: Optional[datetime] = None
        self._follower_heartbeat_warned: bool = False

        # De-duplication dates (one-shot per calendar day)
        self._morning_briefing_sent_date: Optional[str] = None
        self._daily_summary_sent_date: Optional[str] = None

        # Reconciliation interval (every 6 hours)
        self._last_reconciliation_time: Optional[datetime] = None
        self._reconciliation_interval_hours: int = 6

        # Signal pruning (once per day)
        self._last_pruning_date: Optional[str] = None
        self._signal_retention_days: int = int(
            service_config.get("signals", {}).get("retention_days", 90)
        )

        # Audit retention (once per day)
        self._last_audit_retention_date: Optional[str] = None

        # Equity snapshot (once per day at market close)
        self._last_equity_snapshot_date: Optional[str] = None

    # ------------------------------------------------------------------
    # Public: called by service each cycle
    # ------------------------------------------------------------------

    def set_audit_logger(self, audit_logger: "AuditLogger") -> None:
        """Inject the audit logger (late-binding to avoid circular deps)."""
        self._audit_logger = audit_logger

    def record_follower_signal(self) -> None:
        """Call when a forwarded signal is received to reset heartbeat."""
        self._follower_last_signal_at = datetime.now(timezone.utc)
        self._follower_heartbeat_warned = False

    # ------------------------------------------------------------------
    # Morning Briefing
    # ------------------------------------------------------------------

    async def check_morning_briefing(self) -> None:
        """Send morning briefing at configured ET time (default 6:30 AM)."""
        if not self.telegram_notifier or not self.telegram_notifier.enabled:
            return

        try:
            briefing_config = self._service_config.get("ai_briefings", {})
            if not briefing_config.get("enabled", True):
                return

            morning_time_str = str(briefing_config.get("morning_time", "06:30"))
            try:
                morning_hour, morning_minute = map(int, morning_time_str.split(":"))
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
                morning_hour, morning_minute = 6, 30

            now_utc = datetime.now(timezone.utc)
            try:
                from zoneinfo import ZoneInfo
                et_tz = ZoneInfo("America/New_York")
                now_et = now_utc.astimezone(et_tz)
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
                now_et = now_utc - timedelta(hours=5)

            today_str = now_et.strftime("%Y-%m-%d")

            if self._morning_briefing_sent_date == today_str:
                return

            et_hour = now_et.hour
            et_minute = now_et.minute
            if not (et_hour == morning_hour and morning_minute <= et_minute <= morning_minute + 10):
                return

            self._morning_briefing_sent_date = today_str

            # Gather overnight/previous session data
            perf_file = self.performance_tracker.performance_file
            overnight_trades: list = []
            if perf_file.exists():
                try:
                    perf_data = json.loads(perf_file.read_text(encoding="utf-8"))
                    if isinstance(perf_data, list):
                        trades = perf_data
                    elif isinstance(perf_data, dict):
                        trades = perf_data.get("trades", []) or []
                    else:
                        trades = []

                    yesterday = (now_et - timedelta(days=1)).strftime("%Y-%m-%d")
                    for t in trades:
                        exit_time = t.get("exit_time", "")
                        if exit_time and (exit_time[:10] == today_str or exit_time[:10] == yesterday):
                            overnight_trades.append(t)
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

            state = self.state_manager.load_state()
            daily_pnl = float(state.get("daily_pnl", 0) or 0)
            session_pnl = float(state.get("session_pnl", 0) or 0)

            day_name = now_et.strftime("%A")
            date_str = now_et.strftime("%b %d")

            acct_label = getattr(self.telegram_notifier, "account_label", None)
            acct_tag = f"[{acct_label}] " if acct_label else ""
            msg_parts = [f"{acct_tag}Good morning! {day_name}, {date_str}"]

            if overnight_trades:
                overnight_pnl = sum(t.get("pnl", 0) for t in overnight_trades)
                overnight_wins = sum(1 for t in overnight_trades if t.get("is_win"))
                overnight_losses = len(overnight_trades) - overnight_wins
                pnl_sign = "+" if overnight_pnl >= 0 else ""
                msg_parts.append(
                    f"Overnight: {len(overnight_trades)} trades ({overnight_wins}W/{overnight_losses}L), {pnl_sign}${overnight_pnl:.0f}"
                )
            else:
                msg_parts.append("Overnight: No trades")

            if daily_pnl != 0 or session_pnl != 0:
                pnl_to_show = daily_pnl if daily_pnl != 0 else session_pnl
                pnl_sign = "+" if pnl_to_show >= 0 else ""
                msg_parts.append(f"Session P&L: {pnl_sign}${pnl_to_show:.0f}")

            try:
                from pearlalgo.ai.chat import get_ai_chat
                ai_config = self._service_config.get("ai_chat", {})
                ai_chat = get_ai_chat(config=ai_config)
                if ai_chat.enabled:
                    context = {
                        "daily_pnl": daily_pnl,
                        "session_pnl": session_pnl,
                        "overnight_trades": len(overnight_trades),
                        "recent_trades": [
                            {"pnl": t.get("pnl", 0), "direction": t.get("direction", "")}
                            for t in overnight_trades[-5:]
                        ],
                    }
                    insight = await ai_chat.generate_insight("morning_briefing", context)
                    if insight:
                        msg_parts.append(f"\n{insight}")
            except Exception as e:
                logger.debug(f"Could not generate morning AI insight: {e}")

            msg = "\n".join(msg_parts)
            asyncio.create_task(
                self.notification_queue.enqueue_raw_message(
                    msg, parse_mode=None, dedupe=False, priority=Priority.MEDIUM
                )
            )
            logger.info(f"Morning briefing sent for {today_str}")

        except Exception as e:
            logger.debug(f"Could not send morning briefing: {e}")

    # ------------------------------------------------------------------
    # Market Close Summary
    # ------------------------------------------------------------------

    async def check_market_close_summary(self) -> None:
        """Send daily performance summary at safety close (3:55 PM ET)."""
        if not self.telegram_notifier or not self.telegram_notifier.enabled:
            return

        try:
            now_utc = datetime.now(timezone.utc)
            try:
                import pytz
                et_tz = pytz.timezone("US/Eastern")
                now_et = now_utc.astimezone(et_tz)
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
                now_et = now_utc - timedelta(hours=5)

            today_str = now_et.strftime("%Y-%m-%d")

            if self._daily_summary_sent_date == today_str:
                return

            et_hour = now_et.hour
            et_minute = now_et.minute
            if not ((et_hour == 15 and et_minute >= 55) or (et_hour == 16 and et_minute <= 5)):
                return

            self._daily_summary_sent_date = today_str

            acct_label = getattr(self.telegram_notifier, "account_label", None)
            acct_prefix = f"[{acct_label}] " if acct_label else ""
            is_mffu = acct_label == "MFFU"

            today_trades: list = []
            if is_mffu:
                today_trades = self._get_tradovate_today_trades(today_str)

            if not today_trades:
                perf_file = self.performance_tracker.performance_file
                if perf_file.exists():
                    perf_data = json.loads(perf_file.read_text(encoding="utf-8"))
                    if isinstance(perf_data, list):
                        trades = perf_data
                    elif isinstance(perf_data, dict):
                        trades = perf_data.get("trades", []) or []
                    else:
                        trades = []
                    today_trades = [
                        t for t in trades
                        if t.get("exit_time", "")[:10] == today_str
                    ]

            if not today_trades:
                msg = (
                    f"{acct_prefix}\U0001f4ca *Daily Summary* \u2022 {now_et.strftime('%b %d')}\n\n"
                    "No trades today.\n"
                    "_Session safety close at 3:55 PM ET_"
                )
            else:
                total_pnl = sum(t.get("pnl", 0) for t in today_trades)
                wins = sum(1 for t in today_trades if t.get("is_win"))
                losses = len(today_trades) - wins
                win_rate = (wins / len(today_trades) * 100) if today_trades else 0

                pnl_emoji = "\U0001f7e2" if total_pnl >= 0 else "\U0001f534"
                pnl_sign = "+" if total_pnl >= 0 else ""

                long_trades = [t for t in today_trades if t.get("direction", "").lower() == "long"]
                short_trades = [t for t in today_trades if t.get("direction", "").lower() == "short"]
                long_pnl = sum(t.get("pnl", 0) for t in long_trades)
                short_pnl = sum(t.get("pnl", 0) for t in short_trades)

                msg_parts = [
                    f"{acct_prefix}\U0001f4ca *Daily Summary* \u2022 {now_et.strftime('%b %d')}\n",
                    f"{pnl_emoji} *P&L:* {pnl_sign}${total_pnl:,.2f}",
                    f"\U0001f4c8 *Trades:* {len(today_trades)} ({wins}W/{losses}L)",
                    f"\U0001f3af *Win Rate:* {win_rate:.0f}%",
                ]

                if long_trades and short_trades:
                    long_sign = "+" if long_pnl >= 0 else ""
                    short_sign = "+" if short_pnl >= 0 else ""
                    msg_parts.append(
                        f"\u2197\ufe0f Longs: {long_sign}${long_pnl:.0f} \u2022 \u2198\ufe0f Shorts: {short_sign}${short_pnl:.0f}"
                    )

                if is_mffu:
                    try:
                        _reader = StateReader(self.state_manager.state_dir)
                        ch_data = _reader.read_challenge_state()
                        if ch_data:
                            mffu_cfg = ch_data.get("mffu", {}) or ch_data.get("config", {}) or {}
                            current = ch_data.get("current_attempt", {}) or {}
                            profit_target = float(mffu_cfg.get("profit_target", 3000))
                            cum_pnl = float(current.get("cumulative_pnl", 0))
                            remaining = profit_target - cum_pnl
                            hwm = float(current.get("equity_hwm", 0))
                            drawdown_limit = float(mffu_cfg.get("max_drawdown", 2000))
                            starting_bal = float(mffu_cfg.get("starting_balance", 50000))
                            trail_floor = hwm - drawdown_limit if hwm > 0 else starting_bal - drawdown_limit
                            msg_parts.append("")
                            msg_parts.append(f"\U0001f3c6 *Challenge:* ${remaining:,.0f} to target")
                            if hwm > 0:
                                msg_parts.append(f"\U0001f4c9 *Trail Floor:* ${trail_floor:,.0f}")
                    except Exception as ch_err:
                        logger.debug(f"Could not add challenge context to daily summary: {ch_err}")

                try:
                    briefing_config = self._service_config.get("ai_briefings", {})
                    if briefing_config.get("enabled", True):
                        from pearlalgo.ai.chat import get_ai_chat
                        ai_config = self._service_config.get("ai_chat", {})
                        ai_chat = get_ai_chat(config=ai_config)
                        if ai_chat.enabled:
                            context = {
                                "daily_pnl": total_pnl,
                                "wins_today": wins,
                                "losses_today": losses,
                                "win_rate": win_rate,
                                "long_pnl": long_pnl,
                                "short_pnl": short_pnl,
                                "recent_trades": [
                                    {
                                        "pnl": t.get("pnl", 0),
                                        "direction": t.get("direction", ""),
                                        "type": t.get("type", ""),
                                        "is_win": t.get("is_win", False),
                                    }
                                    for t in today_trades
                                ],
                            }
                            insight = await ai_chat.generate_insight("eod_summary", context)
                            if insight:
                                msg_parts.append(f"\n\U0001f4a1 {insight}")
                except Exception as e:
                    logger.debug(f"Could not generate EOD AI insight: {e}")

                msg_parts.append("\n_Session safety close at 3:55 PM ET_")
                msg = "\n".join(msg_parts)

            asyncio.create_task(
                self.notification_queue.enqueue_raw_message(
                    msg, parse_mode="Markdown", dedupe=False, priority=Priority.MEDIUM
                )
            )
            logger.info(f"Daily summary sent for {today_str}")

        except Exception as e:
            logger.debug(f"Could not send daily summary: {e}")

    def _get_tradovate_today_trades(self, today_str: str) -> list:
        """Reconstruct today's closed trades from Tradovate fills (FIFO matching)."""
        try:
            fills_file = self.state_manager.state_dir / "tradovate_fills.json"
            if not fills_file.exists():
                return []
            fills = json.loads(fills_file.read_text(encoding="utf-8"))
            if not isinstance(fills, list) or not fills:
                return []

            open_queue: list = []
            trades: list = []
            point_value = 2.0

            for f in fills:
                action = str(f.get("action") or f.get("Action") or "").lower()
                price = float(f.get("price") or f.get("Price") or 0)
                qty = int(f.get("qty") or f.get("Qty") or 0)
                ts = str(f.get("timestamp") or f.get("Timestamp") or "")
                if not action or not price or not qty:
                    continue

                remaining = qty
                while remaining > 0 and open_queue:
                    oq_action, oq_price, oq_qty, oq_ts = open_queue[0]
                    if oq_action == action:
                        break
                    match_qty = min(remaining, oq_qty)
                    if oq_action == "buy":
                        pnl = (price - oq_price) * match_qty * point_value
                        direction = "long"
                    else:
                        pnl = (oq_price - price) * match_qty * point_value
                        direction = "short"
                    trades.append({
                        "pnl": round(pnl, 2),
                        "is_win": pnl > 0,
                        "direction": direction,
                        "type": "tradovate_fill",
                        "exit_time": ts,
                    })
                    remaining -= match_qty
                    if oq_qty > match_qty:
                        open_queue[0] = (oq_action, oq_price, oq_qty - match_qty, oq_ts)
                    else:
                        open_queue.pop(0)

                if remaining > 0:
                    open_queue.append((action, price, remaining, ts))

            return [t for t in trades if t.get("exit_time", "")[:10] == today_str]
        except Exception as e:
            logger.debug(f"Could not reconstruct Tradovate trades for daily summary: {e}")
            return []

    # ------------------------------------------------------------------
    # Follower Heartbeat
    # ------------------------------------------------------------------

    async def check_follower_heartbeat(self) -> None:
        """Warn if no forwarded signals arrive during market hours."""
        if not self._signal_follower_mode:
            return

        try:
            if not get_market_hours().is_market_open():
                return
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            return

        if self._follower_last_signal_at is None:
            self._follower_last_signal_at = datetime.now(timezone.utc)
            return

        gap_minutes = (datetime.now(timezone.utc) - self._follower_last_signal_at).total_seconds() / 60
        if gap_minutes < self._follower_heartbeat_timeout_minutes:
            return

        if self._follower_heartbeat_warned:
            return

        self._follower_heartbeat_warned = True
        msg = (
            f"\u26a0\ufe0f *Signal Forwarding Stale*\n\n"
            f"No forwarded signals received in `{int(gap_minutes)}` minutes.\n"
            f"Inception may have stopped writing to `shared_signals.jsonl`.\n\n"
            f"Check Inception agent status: `./pearl.sh agent status`"
        )
        logger.warning(f"Follower heartbeat: no signals for {int(gap_minutes)}m (timeout={self._follower_heartbeat_timeout_minutes}m)")
        try:
            if self.telegram_notifier.enabled and self.telegram_notifier.telegram:
                await self.notification_queue.enqueue_risk_warning(
                    msg, risk_status="WARNING", priority=Priority.HIGH,
                )
        except Exception as e:
            logger.debug(f"Follower heartbeat notification failed: {e}")

    # ------------------------------------------------------------------
    # JSON ↔ SQLite Signal Reconciliation
    # ------------------------------------------------------------------

    async def check_reconciliation(self) -> None:
        """Run signal reconciliation between JSON and SQLite stores every 6 hours.

        Non-blocking: errors are caught and logged without crashing the service.
        The reconciliation itself is offloaded to a thread to avoid blocking the
        event loop during file reads and SQLite queries.
        """
        try:
            now = datetime.now(timezone.utc)

            # Throttle: skip if less than _reconciliation_interval_hours since last run
            if self._last_reconciliation_time is not None:
                elapsed_hours = (now - self._last_reconciliation_time).total_seconds() / 3600
                if elapsed_hours < self._reconciliation_interval_hours:
                    return

            self._last_reconciliation_time = now

            # Run reconciliation in a thread to avoid blocking the event loop
            result = await asyncio.to_thread(self.state_manager.reconcile_signals)

            replayed = result.get("replayed", 0)
            errors = result.get("errors", 0)

            if replayed > 0 or errors > 0:
                logger.info(
                    f"Scheduled reconciliation: json={result.get('json_count', 0)}, "
                    f"sqlite={result.get('sqlite_count', 0)}, "
                    f"replayed={replayed}, errors={errors}"
                )
        except Exception as e:
            logger.debug(f"Scheduled reconciliation error: {e}")

    # ------------------------------------------------------------------
    # Signal History Pruning
    # ------------------------------------------------------------------

    async def check_signal_pruning(self) -> None:
        """Prune signals older than retention period from signals.jsonl.

        Runs once per calendar day (UTC).  Archived signals are backed up to
        ``signals_pruned_<date>.jsonl`` before removal so nothing is lost.
        The write is atomic (temp file + ``os.replace``) to avoid corruption.

        Non-blocking: the file I/O is offloaded to a thread.
        """
        try:
            now_utc = datetime.now(timezone.utc)
            today_str = now_utc.strftime("%Y-%m-%d")

            # Once-per-day guard
            if self._last_pruning_date == today_str:
                return
            self._last_pruning_date = today_str

            signals_file = self.state_manager.signals_file
            if not signals_file.exists():
                return

            # Offload the (potentially blocking) file read/write to a thread
            removed, kept = await asyncio.to_thread(
                self._prune_signals_file, signals_file, now_utc
            )

            if removed > 0:
                logger.info(
                    f"Signal pruning complete: removed {removed}, kept {kept} "
                    f"(retention={self._signal_retention_days} days)"
                )
                # Invalidate caches after pruning
                self.state_manager.invalidate_signals_cache()
                # Reset incremental signal count so it re-counts on next access
                self.state_manager._signal_count = None
            else:
                logger.debug(
                    f"Signal pruning: nothing to prune ({kept} signals all within retention)"
                )

        except Exception as e:
            logger.debug(f"Signal pruning error: {e}")

    def _prune_signals_file(self, signals_file: Path, now_utc: datetime) -> tuple:
        """Synchronous helper: read, filter, back up, and rewrite signals.jsonl.

        Returns:
            Tuple of (removed_count, kept_count).
        """
        cutoff = now_utc - timedelta(days=self._signal_retention_days)

        keep_lines: list[str] = []
        prune_lines: list[str] = []

        with open(signals_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                    timestamp_str = record.get("timestamp", "")
                    if timestamp_str:
                        signal_time = parse_utc_timestamp(timestamp_str)
                        if signal_time < cutoff:
                            prune_lines.append(line)
                            continue
                except (json.JSONDecodeError, ValueError, TypeError):
                    # Malformed lines are kept to avoid silent data loss
                    pass
                keep_lines.append(line)

        if not prune_lines:
            return 0, len(keep_lines)

        # Archive pruned signals to a backup file before removing
        backup_file = signals_file.parent / f"signals_pruned_{now_utc.strftime('%Y%m%d')}.jsonl"
        with open(backup_file, "a", encoding="utf-8") as f:
            f.writelines(prune_lines)

        # Atomic rewrite: temp file + os.replace
        tmp_path = Path(str(signals_file) + ".prune_tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(keep_lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, signals_file)

        return len(prune_lines), len(keep_lines)

    # ------------------------------------------------------------------
    # Audit Retention
    # ------------------------------------------------------------------

    async def check_audit_retention(self) -> None:
        """Run audit event retention once per day.

        Deletes old events per the configured retention policy.
        Non-blocking: offloaded to a thread.
        """
        if self._audit_logger is None:
            return

        try:
            now_utc = datetime.now(timezone.utc)
            today_str = now_utc.strftime("%Y-%m-%d")

            if self._last_audit_retention_date == today_str:
                return
            self._last_audit_retention_date = today_str

            result = await asyncio.to_thread(self._audit_logger.run_retention)
            deleted = result.get("deleted_general", 0) + result.get("deleted_snapshots", 0)
            if deleted > 0:
                logger.info(f"Audit retention complete: {result}")
        except Exception as e:
            logger.debug(f"Audit retention error: {e}")

    # ------------------------------------------------------------------
    # Equity Snapshot
    # ------------------------------------------------------------------

    async def check_equity_snapshot(self) -> None:
        """Record a daily equity snapshot at market close (4:10 PM ET).

        Reads the current equity from state.json (IBKR Virtual) or the cached
        Tradovate account summary (Tradovate Paper) and logs it via AuditLogger.
        """
        if self._audit_logger is None:
            return

        try:
            now_utc = datetime.now(timezone.utc)
            try:
                from zoneinfo import ZoneInfo
                et_tz = ZoneInfo("America/New_York")
                now_et = now_utc.astimezone(et_tz)
            except Exception:
                now_et = now_utc - timedelta(hours=5)

            today_str = now_et.strftime("%Y-%m-%d")

            if self._last_equity_snapshot_date == today_str:
                return

            # Fire at 4:10-4:20 PM ET (after market close)
            et_hour = now_et.hour
            et_minute = now_et.minute
            if not (et_hour == 16 and 10 <= et_minute <= 20):
                return

            self._last_equity_snapshot_date = today_str

            state = self.state_manager.load_state()
            account = self._audit_logger.account

            # Try Tradovate account data first (real broker values)
            tv_account = state.get("tradovate_account", {}) or {}
            if tv_account.get("equity"):
                self._audit_logger.log_equity_snapshot(
                    account=account,
                    equity=float(tv_account.get("equity", 0)),
                    cash_balance=float(tv_account.get("cash_balance", 0)),
                    open_pnl=float(tv_account.get("open_pnl", 0)),
                    realized_pnl=float(tv_account.get("realized_pnl", 0)),
                )
            else:
                # Fall back to virtual equity from state
                challenge = state.get("challenge", {}) or {}
                equity = float(
                    challenge.get("current_balance", 0)
                    or state.get("daily_pnl", 0)
                )
                self._audit_logger.log_equity_snapshot(
                    account=account,
                    equity=equity,
                    cash_balance=0.0,
                    open_pnl=0.0,
                    realized_pnl=float(state.get("daily_pnl", 0)),
                )

            logger.info(f"Equity snapshot recorded for {today_str}")

        except Exception as e:
            logger.debug(f"Equity snapshot error: {e}")
