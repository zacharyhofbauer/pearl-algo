"""
Virtual Trade Manager

Manages virtual trade exit processing -- detects when TP/SL is touched on
active virtual trades and records the outcome across all tracking systems
(performance tracker, circuit breaker, learning policies).

Extracted from service.py for better code organization and testability.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import parse_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager
    from pearlalgo.market_agent.performance_tracker import PerformanceTracker
    from pearlalgo.market_agent.notification_queue import NotificationQueue
    from pearlalgo.market_agent.trading_circuit_breaker import TradingCircuitBreaker


class VirtualTradeManager:
    """
    Processes virtual trade exits by scanning OHLCV bars for TP/SL hits.

    All dependencies are injected via the constructor so the class is
    independently testable.
    """

    def __init__(
        self,
        *,
        state_manager: "MarketAgentStateManager",
        performance_tracker: "PerformanceTracker",
        notification_queue: "NotificationQueue",
        # Optional dependencies (set via configure_*)
        trading_circuit_breaker: Optional["TradingCircuitBreaker"] = None,
        telegram_notifier: Optional[Any] = None,
        execution_adapter: Optional[Any] = None,
        bandit_policy: Optional[Any] = None,
        contextual_policy: Optional[Any] = None,
        tv_paper_tracker: Optional[Any] = None,
        # Config values
        virtual_pnl_enabled: bool = True,
        virtual_pnl_tiebreak: str = "stop_loss",
        virtual_pnl_notify_exit: bool = False,
        symbol: str = "MNQ",
        streak_alert_threshold: int = 3,
        audit_logger: Optional[Any] = None,
    ):
        # Core dependencies
        self.state_manager = state_manager
        self.performance_tracker = performance_tracker
        self.notification_queue = notification_queue

        # Optional dependencies
        self.trading_circuit_breaker = trading_circuit_breaker
        self.telegram_notifier = telegram_notifier
        self.execution_adapter = execution_adapter
        self.bandit_policy = bandit_policy
        self.contextual_policy = contextual_policy
        self._tv_paper_tracker = tv_paper_tracker
        self._audit_logger = audit_logger

        # Config
        self._virtual_pnl_enabled = virtual_pnl_enabled
        self._tiebreak = virtual_pnl_tiebreak
        self._notify_exit = virtual_pnl_notify_exit
        self._symbol = symbol

        # Streak tracking
        self._streak_type: str = "none"
        self._streak_count: int = 0
        self._last_streak_alert_count: int = 0
        self._streak_alert_threshold: int = streak_alert_threshold

        # Exit notification dedup — prevent duplicate Telegram messages for the same signal
        self._notified_exits: set = set()

        # Dedup: track signal_ids already processed as exits to prevent
        # duplicate exit records in JSONL before performance_tracker persists status.
        self._processed_exits: set = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_exits(self, market_data: Dict) -> None:
        """
        Scan active virtual trades and exit any where TP/SL has been touched.

        This is called once per service cycle.  Uses vectorized pandas
        operations for O(signals) performance instead of O(signals x bars).

        Args:
            market_data: Dict containing at minimum ``df`` (OHLCV DataFrame).
        """
        if not self._virtual_pnl_enabled:
            return

        # Get bars DataFrame
        df = market_data.get("df") if isinstance(market_data, dict) else None
        if df is None or df.empty:
            return

        required_cols = {"timestamp", "high", "low"}
        if not required_cols.issubset(set(df.columns)):
            return

        # Get recently tracked signals
        try:
            recent = self.state_manager.get_recent_signals(limit=300)
        except Exception as e:
            logger.warning(f"Failed to retrieve recent signals for trade exits: {e}")
            return

        # Build signal_id -> signal data lookup from "generated" records
        # (needed because append-only JSONL "entered" lines may lack the signal key)
        _signal_data_map: Dict[str, Dict] = {}
        for _rec in recent:
            if isinstance(_rec, dict) and _rec.get("status") == "generated" and "signal" in _rec:
                _sid = str(_rec.get("signal_id") or "")
                if _sid:
                    _signal_data_map[_sid] = _rec["signal"]

        # Precompute bar arrays once (vectorized)
        try:
            bar_times = pd.to_datetime(df["timestamp"])
            if bar_times.dt.tz is None:
                bar_times = bar_times.dt.tz_localize("UTC")
            else:
                bar_times = bar_times.dt.tz_convert("UTC")
            bar_times_arr = bar_times.values

            bar_highs = df["high"].fillna(df.get("close", 0)).astype(float).values
            bar_lows = df["low"].fillna(df.get("close", 0)).astype(float).values
        except Exception as e:
            logger.warning(f"Failed to compute bar arrays for trade exits: {e}")
            return

        # signals.jsonl is append-only; only the latest status per signal_id
        # should drive exit checks. Otherwise stale "entered" rows can be
        # reprocessed after a later "exited" event already exists.
        latest_by_id: Dict[str, Dict] = {}
        for rec in recent:
            if not isinstance(rec, dict):
                continue
            sig_id = str(rec.get("signal_id") or "")
            if not sig_id:
                continue
            latest_by_id[sig_id] = rec

        exited_this_cycle: set = set()
        for rec in latest_by_id.values():
            try:
                if rec.get("status") != "entered":
                    continue
                sig_id = str(rec.get("signal_id") or "")
                if not sig_id or sig_id in exited_this_cycle:
                    continue
                if sig_id in self._processed_exits:
                    continue

                # Merge signal data from generated record if missing
                if not rec.get("signal") and sig_id in _signal_data_map:
                    rec = {**rec, "signal": _signal_data_map[sig_id]}

                exit_info = self._check_single_trade_exit(
                    rec, sig_id, bar_times_arr, bar_highs, bar_lows, df,
                )
                if exit_info is None:
                    continue

                if len(exit_info) == 6:
                    exit_price, exit_reason, exit_bar_ts, sig, direction, excursion_data = exit_info
                else:
                    exit_price, exit_reason, exit_bar_ts, sig, direction = exit_info
                    excursion_data = {}
                exited_this_cycle.add(sig_id)

                self._record_exit(
                    sig_id=sig_id,
                    sig=sig,
                    direction=direction,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    exit_bar_ts=exit_bar_ts,
                    df=df,
                    excursion_data=excursion_data,
                )
                # Mark as processed to prevent duplicate exits across cycles
                self._processed_exits.add(sig_id)
                if len(self._processed_exits) > 1000:
                    self._processed_exits = set(list(self._processed_exits)[-500:])
            except Exception as e:
                logger.warning(f"Failed to process virtual trade exit: {e}")
                continue

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _check_single_trade_exit(
        self, rec: Dict, sig_id: str,
        bar_times_arr, bar_highs, bar_lows, df,
    ) -> Optional[tuple]:
        """Check if a single active trade should be exited.

        Returns ``(exit_price, exit_reason, exit_bar_ts, sig, direction)``
        or ``None`` if no exit.
        """
        import numpy as _np

        # Parse entry time (naive ET)  # FIXED 2026-03-25: ET timezone migration
        entry_time_str = rec.get("entry_time")
        entry_time: Optional[datetime] = None
        if entry_time_str:
            try:
                entry_time = parse_utc_timestamp(str(entry_time_str))  # FIXED 2026-03-25: returns naive ET
            except Exception as e:
                logger.warning(f"Critical path error: {e}", exc_info=True)

        sig = rec.get("signal", {}) or {}
        direction = str(sig.get("direction") or "long").lower()
        try:
            stop = float(sig.get("stop_loss") or 0.0)
            target = float(sig.get("take_profit") or 0.0)
        except Exception as e:
            logger.warning(f"Failed to parse stop/target for virtual trade exit: {e}")
            return None
        if stop <= 0 or target <= 0:
            logger.warning(f"Skipping exit check for {rec.get('signal_id', '?')}: stop={stop}, target={target} (missing signal data?)")
            return None

        # Vectorized hit masks
        if direction == "short":
            tp_mask = bar_lows <= target
            sl_mask = bar_highs >= stop
        else:
            tp_mask = bar_highs >= target
            sl_mask = bar_lows <= stop

        # Mask for bars strictly after entry time
        if entry_time:
            entry_ts = pd.Timestamp(entry_time)
            if entry_ts.tzinfo is None:
                entry_ts = entry_ts.tz_localize("UTC")
            else:
                entry_ts = entry_ts.tz_convert("UTC")
            entry_ts_np = entry_ts.tz_localize(None).to_datetime64()
            after_entry_mask = bar_times_arr > entry_ts_np
        else:
            after_entry_mask = _np.ones(len(df), dtype=bool)

        valid_mask = (bar_highs > 0) & (bar_lows > 0)
        exit_mask = (tp_mask | sl_mask) & after_entry_mask & valid_mask

        if not exit_mask.any():
            return None

        first_exit_idx = exit_mask.argmax()
        exit_bar_ts_raw = bar_times_arr[first_exit_idx]
        hit_tp = tp_mask[first_exit_idx]
        hit_sl = sl_mask[first_exit_idx]

        # Determine exit reason and price
        if hit_tp and hit_sl:
            if self._tiebreak == "take_profit":
                exit_reason = "take_profit"
                exit_price = target
            else:
                exit_reason = "stop_loss"
                exit_price = stop
        elif hit_sl:
            exit_reason = "stop_loss"
            exit_price = stop
        elif hit_tp:
            exit_reason = "take_profit"
            exit_price = target
        else:
            return None

        # Convert numpy datetime64 to python datetime
        exit_bar_ts: Optional[datetime] = None
        try:
            exit_bar_ts = pd.Timestamp(exit_bar_ts_raw).to_pydatetime()
            if exit_bar_ts and exit_bar_ts.tzinfo is None:
                exit_bar_ts = exit_bar_ts.replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.warning(f"Critical path error: {e}", exc_info=True)

        # Compute MFE/MAE from bars between entry and exit
        excursion_data = {}
        try:
            hold_mask = after_entry_mask.copy()
            hold_mask[first_exit_idx + 1:] = False
            hold_highs = bar_highs[hold_mask]
            hold_lows = bar_lows[hold_mask]
            if len(hold_highs) > 0 and len(hold_lows) > 0:
                max_price = float(hold_highs.max())
                min_price = float(hold_lows.min())
                entry_px = float(rec.get("entry_price") or sig.get("entry_price") or exit_price)
                if direction == "long":
                    mfe_pts = max_price - entry_px
                    mae_pts = entry_px - min_price
                else:
                    mfe_pts = entry_px - min_price
                    mae_pts = max_price - entry_px
                excursion_data = {
                    "max_price": max_price,
                    "min_price": min_price,
                    "mfe_points": round(mfe_pts, 4),
                    "mae_points": round(mae_pts, 4),
                }
        except Exception as e:
            logger.warning(f"MFE/MAE computation failed for {sig_id}: {e}")

        logger.info(
            f"🔍 VIRTUAL EXIT: signal_id={sig_id} | direction={direction.upper()} | "
            f"entry={sig.get('entry_price', 'N/A')} | exit={exit_price:.2f} | "
            f"reason={exit_reason} | stop={stop:.2f} | target={target:.2f}"
            f" | MFE={excursion_data.get('mfe_points', '?')} MAE={excursion_data.get('mae_points', '?')}"
        )

        return (exit_price, exit_reason, exit_bar_ts, sig, direction, excursion_data)

    def _record_exit(
        self,
        *,
        sig_id: str,
        sig: Dict,
        direction: str,
        exit_price: float,
        exit_reason: str,
        exit_bar_ts: Optional[datetime],
        df: pd.DataFrame,
        excursion_data: Optional[Dict] = None,
    ) -> None:
        """Record the exit across all tracking systems."""
        from pearlalgo.market_agent.notification_queue import Priority, NotificationTier

        perf = self.performance_tracker.track_exit(
            signal_id=sig_id,
            exit_price=float(exit_price),
            exit_reason=str(exit_reason),
            exit_time=exit_bar_ts,
            excursion_data=excursion_data,
        )

        if not perf:
            return

        pnl_value = float(perf.get("pnl", 0.0))
        is_win = bool(perf.get("is_win", pnl_value > 0))
        logger.info(
            "Virtual exit: %s | %s | exit=%s | pnl=%s",
            sig_id[:16], exit_reason, f"{exit_price:.2f}", f"{pnl_value:.2f}",
        )

        # --- Audit: trade exited ---
        if self._audit_logger is not None:
            try:
                self._audit_logger.log_trade_exited(
                    sig_id,
                    {
                        "exit_price": float(exit_price),
                        "exit_reason": str(exit_reason),
                        "pnl": pnl_value,
                        "is_win": is_win,
                        "hold_duration_minutes": float(perf.get("hold_duration_minutes", 0)),
                        "direction": direction,
                    },
                )
            except Exception:
                pass  # non-fatal

        # --- Circuit breaker ---
        if self.trading_circuit_breaker is not None:
            try:
                self.trading_circuit_breaker.record_trade_result({
                    "is_win": is_win,
                    "pnl": pnl_value,
                    "exit_time": exit_bar_ts.strftime('%Y-%m-%dT%H:%M:%S') if exit_bar_ts else None,  # FIXED 2026-03-25: naive ET
                    "exit_reason": exit_reason,
                })
            except Exception as cb_err:
                logger.debug(f"Could not record circuit breaker trade: {cb_err}")
            try:
                was_would_block = bool(sig.get("_cb_would_block", False))
                self.trading_circuit_breaker.record_shadow_outcome(
                    pnl=pnl_value, is_win=is_win, was_would_block=was_would_block,
                )
            except Exception as shadow_err:
                logger.debug(f"Could not record shadow outcome: {shadow_err}")

        # --- Tradovate Paper tracker ---
        # DISABLED: Virtual trade P&L does NOT match actual Tradovate fills.
        # The Tradovate Paper challenge state is now driven by Tradovate equity (in the
        # API server / service polling), not by virtual signal P&L.
        # Feeding virtual P&L here caused false pass/fail triggers.
        # See: api_server.py _get_challenge_status() for actual Tradovate Paper tracking.

        # --- Bandit policy ---
        if self.bandit_policy is not None:
            try:
                signal_type = str(sig.get("type") or "unknown")
                self.bandit_policy.record_outcome(
                    signal_id=sig_id, signal_type=signal_type,
                    is_win=is_win, pnl=pnl_value,
                )
            except Exception as policy_err:
                logger.debug(f"Could not record policy outcome: {policy_err}")

        # --- Contextual policy ---
        if self.contextual_policy is not None:
            try:
                from pearlalgo.learning.contextual_bandit import ContextFeatures
                signal_type = str(sig.get("type") or "unknown")
                raw_ctx = sig.get("_context_features")
                if isinstance(raw_ctx, dict):
                    ctx = ContextFeatures.from_dict(raw_ctx)
                    self.contextual_policy.record_outcome(
                        signal_id=sig_id, signal_type=signal_type,
                        context=ctx, is_win=is_win, pnl=pnl_value,
                    )
                    try:
                        expected_wr = self.contextual_policy.get_expected_win_rate(signal_type, ctx)
                        logger.info(
                            f"🧠 Learning: {signal_type} in {ctx.to_dict().get('context_key', 'unknown')} -> "
                            f"{'WIN' if is_win else 'LOSS'} (${pnl_value:+.0f}) | Expected WR: {expected_wr:.0%}"
                        )
                    except Exception:
                        logger.info(
                            f"🧠 Learning: {signal_type} -> {'WIN' if is_win else 'LOSS'} (${pnl_value:+.0f})"
                        )
            except Exception as ctx_err:
                logger.debug(f"Could not record contextual policy outcome: {ctx_err}")

        # --- Execution adapter daily PnL ---
        if self.execution_adapter is not None:
            try:
                self.execution_adapter.update_daily_pnl(pnl_value)
            except Exception as pnl_err:
                logger.debug(f"Could not update execution daily PnL: {pnl_err}")

        # --- Exit notification ---
        self._maybe_send_exit_notification(sig_id, sig, exit_price, exit_reason, pnl_value, perf, df)

        # --- Streak alert ---
        self._update_streak(sig_id, is_win)

    def _maybe_send_exit_notification(
        self, sig_id: str, sig: Dict, exit_price: float,
        exit_reason: str, pnl_value: float, perf: Dict, df: pd.DataFrame,
    ) -> None:
        """Send Telegram exit notification if configured."""
        from pearlalgo.market_agent.notification_queue import Priority

        # Dedup: skip if we already sent a notification for this signal
        if sig_id in self._notified_exits:
            logger.debug(f"Exit notification already sent for {sig_id[:16]}, skipping duplicate")
            return

        try:
            notifier_available = (
                self.telegram_notifier is not None
                and self.telegram_notifier.enabled
                and self.telegram_notifier.telegram is not None
            )
            if self._virtual_pnl_enabled and self._notify_exit and notifier_available:
                hold_mins = perf.get("hold_duration_minutes")
                try:
                    hold_mins = float(hold_mins) if hold_mins is not None else None
                except Exception:
                    hold_mins = None

                self._notified_exits.add(sig_id)
                # Cap dedup set size to prevent unbounded memory growth
                if len(self._notified_exits) > 500:
                    self._notified_exits = set(list(self._notified_exits)[-250:])

                asyncio.create_task(
                    self.notification_queue.enqueue_exit(
                        signal_id=str(sig_id),
                        exit_price=float(exit_price),
                        exit_reason=str(exit_reason),
                        pnl=float(pnl_value),
                        signal=sig,
                        hold_duration_minutes=hold_mins,
                        buffer_data=df,
                        priority=Priority.HIGH,
                    )
                )
        except Exception as e:
            logger.error(f"Could not schedule exit notification for {sig_id[:16]}: {e}", exc_info=True)

    def _update_streak(self, sig_id: str, is_win: bool) -> None:
        """Track win/loss streaks and send alerts when thresholds are hit."""
        from pearlalgo.market_agent.notification_queue import Priority

        try:
            if is_win:
                if self._streak_type == "win":
                    self._streak_count += 1
                else:
                    self._streak_type = "win"
                    self._streak_count = 1
                    self._last_streak_alert_count = 0
            else:
                if self._streak_type == "loss":
                    self._streak_count += 1
                else:
                    self._streak_type = "loss"
                    self._streak_count = 1
                    self._last_streak_alert_count = 0

            if (
                self._streak_count >= self._streak_alert_threshold
                and self._streak_count > self._last_streak_alert_count
                and self.telegram_notifier
                and self.telegram_notifier.enabled
            ):
                self._last_streak_alert_count = self._streak_count
                _acct = getattr(self.telegram_notifier, "account_label", None)
                _atag = f"[{_acct}] " if _acct else ""

                if self._streak_type == "win":
                    msg = f"{_atag}🔥 *{self._streak_count} Win Streak!*\n\nYou're on fire! Consider:\n• Locking in profits\n• Staying disciplined"
                else:
                    msg = f"{_atag}❄️ *{self._streak_count} Loss Streak*\n\nConsider taking a break.\nCircuit breaker is monitoring."

                asyncio.create_task(
                    self.notification_queue.enqueue_raw_message(
                        msg, parse_mode="Markdown", dedupe=False, priority=Priority.MEDIUM,
                    )
                )
                logger.info(f"Streak alert sent: {self._streak_type} x{self._streak_count}")
        except Exception as streak_err:
            logger.debug(f"Could not send streak alert: {streak_err}")
