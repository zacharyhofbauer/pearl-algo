"""
Service P&L and Virtual Trade Exit Methods

Extracted from service.py to improve maintainability.
Contains virtual trade exit handling, P&L tracking, and related functionality.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import parse_utc_timestamp
from pearlalgo.market_agent.notification_queue import Priority

if TYPE_CHECKING:
    from pearlalgo.market_agent.service import MarketAgentService


class ServicePnLMixin:
    """
    Mixin class containing P&L and virtual trade exit methods for MarketAgentService.

    This mixin provides:
    - Virtual trade exit handling
    - P&L tracking and recording
    - Streak tracking and alerts
    - Integration with circuit breaker, challenge tracker, and learning policies
    """

    def _update_virtual_trade_exits(self: "MarketAgentService", market_data: Dict) -> None:
        """
        Update virtual trade exits for any `entered` signals when TP/SL is touched.

        Rules:
        - Gated by `config.virtual_pnl_enabled` (default True).
        - Entry is immediate at signal generation time.
        - Exit occurs on first *touch* of TP/SL using **bars from market_data['df']**
          that are strictly after the entry time (avoids Level1 daily high/low artifacts).
        - If TP and SL are both touched in the same bar, tiebreak is determined by
          config.virtual_pnl_tiebreak ("stop_loss" = conservative, "take_profit" = optimistic).

        Performance: Uses vectorized pandas operations instead of iterrows() for O(signals)
        instead of O(signals × bars) complexity.
        """
        # Gate by config.virtual_pnl_enabled
        if not getattr(self.config, "virtual_pnl_enabled", True):
            return

        # Get bars DataFrame - use actual OHLCV bars, NOT Level1 latest_bar
        df = market_data.get("df") if isinstance(market_data, dict) else None
        if df is None or df.empty:
            return

        # Ensure we have required columns
        required_cols = {"timestamp", "high", "low"}
        if not required_cols.issubset(set(df.columns)):
            return

        # Get tiebreak preference from config (default to conservative "stop_loss")
        tiebreak = getattr(self.config, "virtual_pnl_tiebreak", "stop_loss")

        # Consider only recently tracked signals for performance
        try:
            recent = self.state_manager.get_recent_signals(limit=300)
        except Exception:
            return

        # Precompute bar arrays once (vectorized) for all signals
        try:
            bar_times = pd.to_datetime(df["timestamp"])
            if bar_times.dt.tz is None:
                bar_times = bar_times.dt.tz_localize("UTC")
            else:
                bar_times = bar_times.dt.tz_convert("UTC")
            bar_times_arr = bar_times.values

            bar_highs = df["high"].fillna(df.get("close", 0)).astype(float).values
            bar_lows = df["low"].fillna(df.get("close", 0)).astype(float).values
        except Exception:
            return

        exited_this_cycle: set[str] = set()
        for rec in recent:
            try:
                if not isinstance(rec, dict) or rec.get("status") != "entered":
                    continue
                sig_id = str(rec.get("signal_id") or "")
                if not sig_id or sig_id in exited_this_cycle:
                    continue

                # Parse entry time (UTC)
                entry_time_str = rec.get("entry_time")
                entry_time: Optional[datetime] = None
                if entry_time_str:
                    try:
                        entry_time = parse_utc_timestamp(str(entry_time_str))
                        if entry_time and entry_time.tzinfo is None:
                            entry_time = entry_time.replace(tzinfo=timezone.utc)
                    except Exception:
                        pass

                sig = rec.get("signal", {}) or {}
                direction = str(sig.get("direction") or "long").lower()
                try:
                    stop = float(sig.get("stop_loss") or 0.0)
                    target = float(sig.get("take_profit") or 0.0)
                except Exception:
                    continue
                if stop <= 0 or target <= 0:
                    continue

                # Vectorized: compute hit masks for all bars at once
                if direction == "short":
                    tp_mask = bar_lows <= target
                    sl_mask = bar_highs >= stop
                else:  # long
                    tp_mask = bar_highs >= target
                    sl_mask = bar_lows <= stop

                # Mask for bars strictly after entry time
                if entry_time:
                    import numpy as _np
                    entry_ts = pd.Timestamp(entry_time)
                    if entry_ts.tzinfo is None:
                        entry_ts = entry_ts.tz_localize("UTC")
                    else:
                        entry_ts = entry_ts.tz_convert("UTC")
                    entry_ts_np = entry_ts.tz_localize(None).to_datetime64()
                    after_entry_mask = bar_times_arr > entry_ts_np
                else:
                    import numpy as _np
                    after_entry_mask = _np.ones(len(df), dtype=bool)

                # Mask for valid bars (positive high/low)
                valid_mask = (bar_highs > 0) & (bar_lows > 0)

                # Combined exit mask: (TP or SL hit) AND after entry AND valid
                exit_mask = (tp_mask | sl_mask) & after_entry_mask & valid_mask

                if not exit_mask.any():
                    continue

                # Find first bar index where exit condition is met
                first_exit_idx = exit_mask.argmax()

                # Get values at exit bar
                exit_bar_ts_raw = bar_times_arr[first_exit_idx]
                hit_tp = tp_mask[first_exit_idx]
                hit_sl = sl_mask[first_exit_idx]

                # Determine exit reason and price based on tiebreak
                exit_reason: Optional[str] = None
                exit_price: Optional[float] = None

                if hit_tp and hit_sl:
                    if tiebreak == "take_profit":
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

                if exit_reason and exit_price is not None:
                    # Convert numpy datetime64 to python datetime
                    exit_bar_ts: Optional[datetime] = None
                    try:
                        exit_bar_ts = pd.Timestamp(exit_bar_ts_raw).to_pydatetime()
                        if exit_bar_ts and exit_bar_ts.tzinfo is None:
                            exit_bar_ts = exit_bar_ts.replace(tzinfo=timezone.utc)
                    except Exception:
                        pass

                    logger.info(
                        f"🔍 VIRTUAL EXIT: signal_id={sig_id} | direction={direction.upper()} | "
                        f"entry={sig.get('entry_price', 'N/A')} | exit={exit_price:.2f} | "
                        f"reason={exit_reason} | stop={stop:.2f} | target={target:.2f}"
                    )

                    perf = self.performance_tracker.track_exit(
                        signal_id=sig_id,
                        exit_price=float(exit_price),
                        exit_reason=str(exit_reason),
                        exit_time=exit_bar_ts,
                    )
                    exited_this_cycle.add(sig_id)

                    if perf:
                        self._process_exit_result(
                            perf=perf,
                            sig=sig,
                            sig_id=sig_id,
                            exit_price=exit_price,
                            exit_reason=exit_reason,
                            exit_bar_ts=exit_bar_ts,
                            df=df,
                        )
            except Exception:
                continue

    def _process_exit_result(
        self: "MarketAgentService",
        perf: Dict[str, Any],
        sig: Dict[str, Any],
        sig_id: str,
        exit_price: float,
        exit_reason: str,
        exit_bar_ts: Optional[datetime],
        df: pd.DataFrame,
    ) -> None:
        """Process the result of a virtual trade exit."""
        pnl_value = float(perf.get('pnl', 0.0))
        is_win = bool(perf.get("is_win", pnl_value > 0))

        logger.info(
            "Virtual exit: %s | %s | exit=%s | pnl=%s",
            sig_id[:16],
            exit_reason,
            f"{float(exit_price):.2f}",
            f"{pnl_value:.2f}",
        )

        # Record with trading circuit breaker
        self._record_circuit_breaker_trade(is_win, pnl_value, exit_bar_ts, exit_reason)

        # Record with challenge tracker
        self._record_challenge_trade(pnl_value, is_win)

        # Record with bandit policy
        self._record_bandit_outcome(sig_id, sig, is_win, pnl_value)

        # Record with contextual policy
        self._record_contextual_outcome(sig_id, sig, is_win, pnl_value)

        # Update execution adapter's daily PnL
        self._update_execution_pnl(pnl_value)

        # Send exit notification if configured
        self._send_exit_notification(
            sig_id, sig, exit_price, exit_reason, pnl_value, perf, df
        )

        # Track and alert on streaks
        self._track_streak(is_win)

    def _record_circuit_breaker_trade(
        self: "MarketAgentService",
        is_win: bool,
        pnl_value: float,
        exit_bar_ts: Optional[datetime],
        exit_reason: str,
    ) -> None:
        """Record trade with trading circuit breaker."""
        if self.trading_circuit_breaker is not None:
            try:
                self.trading_circuit_breaker.record_trade_result({
                    "is_win": is_win,
                    "pnl": pnl_value,
                    "exit_time": exit_bar_ts.isoformat() if exit_bar_ts else None,
                    "exit_reason": exit_reason,
                })
            except Exception as cb_err:
                logger.debug(f"Could not record circuit breaker trade: {cb_err}")

    def _record_challenge_trade(
        self: "MarketAgentService",
        pnl_value: float,
        is_win: bool,
    ) -> None:
        """Record trade with 50k challenge tracker."""
        if self._challenge_tracker is not None:
            try:
                challenge_result = self._challenge_tracker.record_trade(
                    pnl=pnl_value,
                    is_win=is_win,
                )
                if challenge_result.get("triggered"):
                    outcome = challenge_result.get("outcome", "")
                    attempt = challenge_result.get("attempt", {})
                    attempt_pnl = attempt.get("pnl", 0.0)
                    attempt_id = attempt.get("attempt_id", 0)
                    logger.info(
                        f"🏆 Challenge attempt #{attempt_id} ended: {outcome.upper()} | "
                        f"Final PnL: ${attempt_pnl:.2f}"
                    )
                    # Send Telegram alert for pass/fail
                    if self.telegram_notifier.enabled:
                        try:
                            emoji = "🎉" if outcome == "pass" else "❌"
                            msg = (
                                f"{emoji} *50k Challenge: {outcome.upper()}*\n\n"
                                f"Attempt #{attempt_id} ended\n"
                                f"Final PnL: `${attempt_pnl:,.2f}`\n"
                                f"Trades: {attempt.get('trades', 0)} | "
                                f"WR: {attempt.get('win_rate', 0):.0f}%\n\n"
                                f"_New attempt starting..._"
                            )
                            asyncio.create_task(
                                self.notification_queue.enqueue_raw_message(
                                    msg, parse_mode="Markdown", dedupe=False, priority=Priority.HIGH
                                )
                            )
                        except Exception as tg_err:
                            logger.debug(f"Could not queue challenge alert: {tg_err}")
            except Exception as challenge_err:
                logger.debug(f"Could not record challenge trade: {challenge_err}")

    def _record_bandit_outcome(
        self: "MarketAgentService",
        sig_id: str,
        sig: Dict[str, Any],
        is_win: bool,
        pnl_value: float,
    ) -> None:
        """Record outcome with bandit policy for learning."""
        if self.bandit_policy is not None:
            try:
                signal_type = str(sig.get("type") or "unknown")
                self.bandit_policy.record_outcome(
                    signal_id=sig_id,
                    signal_type=signal_type,
                    is_win=is_win,
                    pnl=pnl_value,
                )
            except Exception as policy_err:
                logger.debug(f"Could not record policy outcome: {policy_err}")

    def _record_contextual_outcome(
        self: "MarketAgentService",
        sig_id: str,
        sig: Dict[str, Any],
        is_win: bool,
        pnl_value: float,
    ) -> None:
        """Record outcome with contextual policy."""
        # Import here to avoid circular dependency
        try:
            from pearlalgo.learning.contextual_bandit import ContextFeatures
        except ImportError:
            return

        if self.contextual_policy is not None and ContextFeatures is not None:
            try:
                signal_type = str(sig.get("type") or "unknown")
                raw_ctx = sig.get("_context_features")
                if isinstance(raw_ctx, dict):
                    ctx = ContextFeatures.from_dict(raw_ctx)
                    self.contextual_policy.record_outcome(
                        signal_id=sig_id,
                        signal_type=signal_type,
                        context=ctx,
                        is_win=is_win,
                        pnl=pnl_value,
                    )

                    # Log learning metrics
                    try:
                        context_key = ctx.to_dict().get("context_key", "unknown")
                        expected_wr = self.contextual_policy.get_expected_win_rate(
                            signal_type, ctx
                        )
                        logger.info(
                            f"🧠 Learning: {signal_type} in {context_key} -> "
                            f"{'WIN' if is_win else 'LOSS'} (${pnl_value:+.0f}) | "
                            f"Expected WR: {expected_wr:.0%}"
                        )
                    except Exception:
                        logger.info(
                            f"🧠 Learning: {signal_type} -> "
                            f"{'WIN' if is_win else 'LOSS'} (${pnl_value:+.0f})"
                        )
            except Exception as ctx_err:
                logger.debug(f"Could not record contextual policy outcome: {ctx_err}")

    def _update_execution_pnl(self: "MarketAgentService", pnl_value: float) -> None:
        """Update execution adapter's daily PnL for kill switch threshold."""
        if self.execution_adapter is not None:
            try:
                self.execution_adapter.update_daily_pnl(pnl_value)
                logger.debug(f"Updated execution daily PnL: {pnl_value:.2f}")
            except Exception as pnl_err:
                logger.debug(f"Could not update execution daily PnL: {pnl_err}")

    def _send_exit_notification(
        self: "MarketAgentService",
        sig_id: str,
        sig: Dict[str, Any],
        exit_price: float,
        exit_reason: str,
        pnl_value: float,
        perf: Dict[str, Any],
        df: pd.DataFrame,
    ) -> None:
        """Send Telegram exit notification if configured."""
        try:
            virtual_pnl_enabled = bool(getattr(self.config, "virtual_pnl_enabled", True))
            virtual_pnl_notify_exit = bool(getattr(self.config, "virtual_pnl_notify_exit", False))

            notifier_available = (
                self.telegram_notifier is not None
                and self.telegram_notifier.enabled
                and self.telegram_notifier.telegram is not None
            )

            if virtual_pnl_enabled and virtual_pnl_notify_exit and notifier_available:
                hold_mins = perf.get("hold_duration_minutes")
                try:
                    hold_mins = float(hold_mins) if hold_mins is not None else None
                except Exception:
                    hold_mins = None

                logger.info(
                    f"📤 Queuing exit notification for {sig_id[:16]}: "
                    f"exit={exit_price:.2f} | reason={exit_reason} | pnl=${pnl_value:.2f}"
                )

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
            else:
                if not virtual_pnl_enabled:
                    logger.debug(f"Exit notification skipped for {sig_id[:16]}: virtual_pnl_enabled=False")
                elif not virtual_pnl_notify_exit:
                    logger.debug(f"Exit notification skipped for {sig_id[:16]}: virtual_pnl_notify_exit=False")
                elif not notifier_available:
                    logger.warning(
                        f"Exit notification skipped for {sig_id[:16]}: Telegram notifier not available"
                    )
        except Exception as e:
            logger.error(
                f"Could not schedule exit notification for {sig_id[:16]}: {e}",
                exc_info=True
            )

    def _track_streak(self: "MarketAgentService", is_win: bool) -> None:
        """Track win/loss streaks and send alerts."""
        try:
            if is_win:
                if self._streak_type == 'win':
                    self._streak_count += 1
                else:
                    self._streak_type = 'win'
                    self._streak_count = 1
                    self._last_streak_alert_count = 0
            else:
                if self._streak_type == 'loss':
                    self._streak_count += 1
                else:
                    self._streak_type = 'loss'
                    self._streak_count = 1
                    self._last_streak_alert_count = 0

            # Send alert when streak reaches threshold
            if (self._streak_count >= self._streak_alert_threshold
                and self._streak_count > self._last_streak_alert_count
                and self.telegram_notifier
                and self.telegram_notifier.enabled):

                self._last_streak_alert_count = self._streak_count

                if self._streak_type == 'win':
                    emoji = "🔥"
                    msg = f"{emoji} *{self._streak_count} Win Streak!*\n\n"
                    msg += "You're on fire! Consider:\n"
                    msg += "• Locking in profits\n"
                    msg += "• Staying disciplined"
                else:
                    emoji = "❄️"
                    msg = f"{emoji} *{self._streak_count} Loss Streak*\n\n"
                    msg += "Consider taking a break.\n"
                    msg += "Circuit breaker is monitoring."

                asyncio.create_task(
                    self.notification_queue.enqueue_raw_message(
                        msg, parse_mode="Markdown", dedupe=False, priority=Priority.MEDIUM
                    )
                )
                logger.info(f"Streak alert sent: {self._streak_type} x{self._streak_count}")
        except Exception as streak_err:
            logger.debug(f"Could not send streak alert: {streak_err}")
