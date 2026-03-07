"""
Position Tracker Module

Handles virtual trade lifecycle: entry tracking, exit detection, and position management.
Extracted from service.py for better code organization.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from zoneinfo import ZoneInfo

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import parse_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager
    from pearlalgo.market_agent.performance_tracker import PerformanceTracker
    from pearlalgo.market_agent.trading_circuit_breaker import TradingCircuitBreaker
    from pearlalgo.market_agent.notification_queue import NotificationQueue
    from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
    from pearlalgo.learning.bandit_policy import BanditPolicy
    from pearlalgo.learning.contextual_bandit import ContextualBanditPolicy, ContextFeatures


class VirtualPositionTracker:
    """
    Manages virtual trade positions and their lifecycle.

    Tracks:
    - Active positions (entered but not exited)
    - Exit detection (TP/SL hits)
    - Close-all operations
    - Auto-flat rules
    - Streak tracking
    """

    def __init__(
        self,
        state_manager: "MarketAgentStateManager",
        performance_tracker: "PerformanceTracker",
        notification_queue: "NotificationQueue",
        telegram_notifier: "MarketAgentTelegramNotifier",
        config: Any,
        *,
        trading_circuit_breaker: Optional["TradingCircuitBreaker"] = None,
        bandit_policy: Optional["BanditPolicy"] = None,
        contextual_policy: Optional["ContextualBanditPolicy"] = None,
        execution_adapter: Optional[Any] = None,
    ):
        """
        Initialize the position tracker.

        Args:
            state_manager: For reading/writing signal state
            performance_tracker: For tracking trade performance
            notification_queue: For sending Telegram notifications
            telegram_notifier: Telegram notifier instance
            config: Service configuration
            trading_circuit_breaker: Optional circuit breaker for risk management
            bandit_policy: Optional bandit policy for learning
            contextual_policy: Optional contextual bandit for context-aware learning
            execution_adapter: Optional execution adapter for order management
        """
        self.state_manager = state_manager
        self.performance_tracker = performance_tracker
        self.notification_queue = notification_queue
        self.telegram_notifier = telegram_notifier
        self.config = config

        # Optional components
        self.trading_circuit_breaker = trading_circuit_breaker
        self.bandit_policy = bandit_policy
        self.contextual_policy = contextual_policy
        self.execution_adapter = execution_adapter

        # Streak tracking
        self._streak_count: int = 0
        self._streak_type: str = ""  # 'win' or 'loss'
        self._streak_alert_threshold: int = 3
        self._last_streak_alert_count: int = 0

        # Close-all tracking
        self._last_close_all_at: Optional[str] = None
        self._last_close_all_reason: Optional[str] = None
        self._last_close_all_count: int = 0
        self._last_close_all_pnl: float = 0.0
        self._last_close_all_price_source: Optional[str] = None

        # Auto-flat configuration
        self._auto_flat_enabled: bool = False
        self._auto_flat_daily_enabled: bool = False
        self._auto_flat_friday_enabled: bool = False
        self._auto_flat_weekend_enabled: bool = False
        self._auto_flat_notify: bool = True
        self._auto_flat_timezone: str = "America/New_York"
        self._auto_flat_daily_time: tuple[int, int] = (15, 55)
        self._auto_flat_friday_time: tuple[int, int] = (15, 55)
        self._auto_flat_last_dates: Dict[str, Any] = {}

        # For contextual learning
        self._context_features_class: Optional[type] = None
        try:
            from pearlalgo.learning.contextual_bandit import ContextFeatures
            self._context_features_class = ContextFeatures
        except ImportError:
            pass

    def configure_auto_flat(
        self,
        enabled: bool = False,
        daily_enabled: bool = False,
        friday_enabled: bool = False,
        weekend_enabled: bool = False,
        notify: bool = True,
        timezone: str = "America/New_York",
        daily_time: tuple[int, int] = (15, 55),
        friday_time: tuple[int, int] = (15, 55),
    ) -> None:
        """Configure auto-flat settings."""
        self._auto_flat_enabled = enabled
        self._auto_flat_daily_enabled = daily_enabled
        self._auto_flat_friday_enabled = friday_enabled
        self._auto_flat_weekend_enabled = weekend_enabled
        self._auto_flat_notify = notify
        self._auto_flat_timezone = timezone
        self._auto_flat_daily_time = daily_time
        self._auto_flat_friday_time = friday_time

    def configure_streak_alerts(self, threshold: int = 3) -> None:
        """Configure streak alert threshold."""
        self._streak_alert_threshold = threshold

    def get_active_virtual_trades(self, *, limit: int = 300) -> List[Dict]:
        """Return active virtual trades (signals.jsonl status=entered)."""
        try:
            recent_signals = self.state_manager.get_recent_signals(limit=limit)
        except Exception as e:
            logger.error(f"Failed to get recent signals for active trades: {e}")
            return []
        active: List[Dict] = []
        for rec in recent_signals:
            if isinstance(rec, dict) and rec.get("status") == "entered":
                active.append(rec)
        return active

    def resolve_latest_prices(self, market_data: Optional[Dict], data_fetcher: Any = None) -> Dict:
        """Resolve latest bid/ask/close prices from market_data or cached data."""
        latest_bar = None
        if isinstance(market_data, dict):
            latest_bar = market_data.get("latest_bar")
        if not isinstance(latest_bar, dict) and data_fetcher is not None:
            try:
                cached = getattr(data_fetcher, "_last_market_data", None) or {}
                latest_bar = cached.get("latest_bar")
            except Exception:
                latest_bar = None
        if not isinstance(latest_bar, dict):
            return {"close": None, "bid": None, "ask": None, "source": None}

        def _f(v: Any) -> Optional[float]:
            try:
                out = float(v)
                return out if out > 0 else None
            except Exception:
                return None

        close_px = _f(latest_bar.get("close"))
        bid_px = _f(latest_bar.get("bid"))
        ask_px = _f(latest_bar.get("ask"))
        source = latest_bar.get("_data_level") or latest_bar.get("_data_source")
        return {
            "close": close_px,
            "bid": bid_px,
            "ask": ask_px,
            "source": str(source) if source is not None else None,
        }

    def auto_flat_due(self, now_utc: datetime, *, market_open: Optional[bool]) -> Optional[str]:
        """Return auto-flat reason if daily/Friday/weekend rule should trigger."""
        if not self._auto_flat_enabled:
            return None
        try:
            tz = ZoneInfo(self._auto_flat_timezone)
        except Exception:
            tz = ZoneInfo("America/New_York")

        local_now = now_utc.astimezone(tz)
        weekday = local_now.weekday()  # 0=Mon .. 6=Sun

        if self._auto_flat_daily_enabled:
            dh, dm = self._auto_flat_daily_time
            if local_now.time() >= time(dh, dm):
                if self._auto_flat_last_dates.get("daily_auto_flat") != local_now.date():
                    return "daily_auto_flat"

        if self._auto_flat_friday_enabled and weekday == 4:
            fh, fm = self._auto_flat_friday_time
            if local_now.time() >= time(fh, fm):
                if self._auto_flat_last_dates.get("friday_auto_flat") != local_now.date():
                    return "friday_auto_flat"

        if self._auto_flat_weekend_enabled and market_open is False:
            is_weekend_window = (
                weekday == 5  # Saturday
                or (weekday == 6 and local_now.time() < time(18, 0))  # Sunday pre-open
                or (weekday == 4 and local_now.time() >= time(17, 0))  # Friday after close
            )
            if is_weekend_window:
                if self._auto_flat_last_dates.get("weekend_auto_flat") != local_now.date():
                    return "weekend_auto_flat"

        return None

    def update_virtual_trade_exits(self, market_data: Dict) -> None:
        """
        Update virtual trade exits for any `entered` signals when TP/SL is touched.

        Rules:
        - Gated by `config.virtual_pnl_enabled` (default True).
        - Entry is immediate at signal generation time.
        - Exit occurs on first *touch* of TP/SL using **bars from market_data['df']**
          that are strictly after the entry time.
        - If TP and SL are both touched in the same bar, tiebreak is determined by
          config.virtual_pnl_tiebreak ("stop_loss" = conservative, "take_profit" = optimistic).
        """
        # Gate by config.virtual_pnl_enabled
        if not getattr(self.config, "virtual_pnl_enabled", True):
            return

        # Get bars DataFrame
        df = market_data.get("df") if isinstance(market_data, dict) else None
        if df is None or df.empty:
            return

        # Ensure we have required columns
        required_cols = {"timestamp", "high", "low"}
        if not required_cols.issubset(set(df.columns)):
            return

        # Get tiebreak preference from config
        tiebreak = getattr(self.config, "virtual_pnl_tiebreak", "stop_loss")

        try:
            recent = self.state_manager.get_recent_signals(limit=300)
        except Exception as e:
            logger.warning(f"Failed to get recent signals for exit check: {e}")
            return

        # Precompute bar arrays
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
            logger.warning(f"Failed to precompute bar arrays for exit check: {e}")
            return

        exited_this_cycle: set = set()
        for rec in recent:
            try:
                if not isinstance(rec, dict) or rec.get("status") != "entered":
                    continue
                sig_id = str(rec.get("signal_id") or "")
                if not sig_id or sig_id in exited_this_cycle:
                    continue

                # Parse entry time
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

                # Vectorized hit masks
                if direction == "short":
                    tp_mask = bar_lows <= target
                    sl_mask = bar_highs >= stop
                else:
                    tp_mask = bar_highs >= target
                    sl_mask = bar_lows <= stop

                # Mask for bars after entry time
                import numpy as _np
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
                    continue

                first_exit_idx = exit_mask.argmax()
                exit_bar_ts_raw = bar_times_arr[first_exit_idx]
                hit_tp = tp_mask[first_exit_idx]
                hit_sl = sl_mask[first_exit_idx]

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
                    exit_bar_ts: Optional[datetime] = None
                    try:
                        exit_bar_ts = pd.Timestamp(exit_bar_ts_raw).to_pydatetime()
                        if exit_bar_ts and exit_bar_ts.tzinfo is None:
                            exit_bar_ts = exit_bar_ts.replace(tzinfo=timezone.utc)
                    except Exception as e:
                        logger.warning(f"Failed to parse exit bar timestamp for {sig_id}: {e}")

                    # Compute MFE/MAE from bars between entry and exit
                    excursion_data = {}
                    try:
                        hold_mask = after_entry_mask.copy()
                        hold_mask[first_exit_idx + 1:] = False  # only bars up to exit
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

                    perf = self.performance_tracker.track_exit(
                        signal_id=sig_id,
                        exit_price=float(exit_price),
                        exit_reason=str(exit_reason),
                        exit_time=exit_bar_ts,
                        excursion_data=excursion_data or None,
                    )
                    exited_this_cycle.add(sig_id)

                    if perf:
                        self._handle_exit_callbacks(
                            sig_id=sig_id,
                            sig=sig,
                            perf=perf,
                            exit_price=exit_price,
                            exit_reason=exit_reason,
                            exit_bar_ts=exit_bar_ts,
                            df=df,
                        )
            except Exception:
                continue

    def _handle_exit_callbacks(
        self,
        sig_id: str,
        sig: Dict,
        perf: Dict,
        exit_price: float,
        exit_reason: str,
        exit_bar_ts: Optional[datetime],
        df: Optional[pd.DataFrame],
    ) -> None:
        """Handle all callbacks after a virtual trade exit."""
        from pearlalgo.market_agent.notification_queue import Priority

        pnl_value = float(perf.get('pnl', 0.0))
        is_win = bool(perf.get("is_win", pnl_value > 0))

        logger.info(
            "Virtual exit: %s | %s | exit=%s | pnl=%s",
            sig_id[:16],
            exit_reason,
            f"{float(exit_price):.2f}",
            f"{pnl_value:.2f}",
        )

        # Circuit breaker
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

        # Bandit policy
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

        # Contextual policy
        if self.contextual_policy is not None and self._context_features_class is not None:
            try:
                signal_type = str(sig.get("type") or "unknown")
                raw_ctx = sig.get("_context_features")
                if isinstance(raw_ctx, dict):
                    ctx = self._context_features_class.from_dict(raw_ctx)
                    self.contextual_policy.record_outcome(
                        signal_id=sig_id,
                        signal_type=signal_type,
                        context=ctx,
                        is_win=is_win,
                        pnl=pnl_value,
                    )
            except Exception as ctx_err:
                logger.debug(f"Could not record contextual policy outcome: {ctx_err}")

        # Execution adapter daily PnL
        if self.execution_adapter is not None:
            try:
                self.execution_adapter.update_daily_pnl(pnl_value)
            except Exception as pnl_err:
                logger.debug(f"Could not update execution daily PnL: {pnl_err}")

        # Exit notification
        self._maybe_send_exit_notification(sig_id, sig, exit_price, exit_reason, pnl_value, perf, df)

        # Streak tracking
        self._update_streak(is_win)

    def _maybe_send_exit_notification(
        self,
        sig_id: str,
        sig: Dict,
        exit_price: float,
        exit_reason: str,
        pnl_value: float,
        perf: Dict,
        df: Optional[pd.DataFrame],
    ) -> None:
        """Send exit notification if configured."""
        from pearlalgo.market_agent.notification_queue import Priority

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
        except Exception as e:
            logger.error(f"Could not schedule exit notification for {sig_id[:16]}: {e}", exc_info=True)

    def _update_streak(self, is_win: bool) -> None:
        """Update streak tracking and send alerts if threshold reached."""
        from pearlalgo.market_agent.notification_queue import Priority

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

    async def close_all_virtual_trades(self, *, market_data: Dict, reason: str, data_fetcher: Any = None) -> int:
        """Force-close all virtual trades (status=entered) using latest price."""
        from pearlalgo.market_agent.notification_queue import Priority

        if not getattr(self.config, "virtual_pnl_enabled", True):
            logger.warning("Auto/close-all requested but virtual PnL is disabled")
            return 0

        active = self.get_active_virtual_trades(limit=500)
        if not active:
            return 0

        prices = self.resolve_latest_prices(market_data, data_fetcher)
        close_px = prices.get("close")
        if close_px is None:
            logger.warning("Close-all requested but no valid latest price available")
            return 0

        bid_px = prices.get("bid")
        ask_px = prices.get("ask")
        price_source = prices.get("source")

        now = datetime.now(timezone.utc)
        closed_count = 0
        total_pnl = 0.0

        for rec in active:
            sig_id = str(rec.get("signal_id") or "").strip()
            if not sig_id:
                continue
            sig = rec.get("signal", {}) or {}
            direction = str(sig.get("direction") or "long").lower()

            exit_px = close_px
            if direction == "long" and isinstance(bid_px, float):
                exit_px = bid_px
            elif direction == "short" and isinstance(ask_px, float):
                exit_px = ask_px

            perf = self.performance_tracker.track_exit(
                signal_id=sig_id,
                exit_price=float(exit_px),
                exit_reason=str(reason),
                exit_time=now,
            )
            closed_count += 1
            if isinstance(perf, dict):
                try:
                    total_pnl += float(perf.get("pnl") or 0.0)
                except Exception:
                    pass

        # Update state
        try:
            state = self.state_manager.load_state() if self.state_manager else {}
            if isinstance(state, dict):
                state["active_trades_count"] = 0
                state["active_trades_unrealized_pnl"] = 0.0
                self.state_manager.save_state(state)
        except Exception:
            pass

        self._last_close_all_at = now.isoformat()
        self._last_close_all_reason = str(reason)
        self._last_close_all_count = int(closed_count)
        self._last_close_all_pnl = float(total_pnl)
        self._last_close_all_price_source = str(price_source) if price_source else None

        try:
            self.state_manager.append_event(
                "close_all_trades",
                {
                    "reason": str(reason),
                    "count": int(closed_count),
                    "total_pnl": float(total_pnl),
                    "price_source": self._last_close_all_price_source,
                },
                level="warning",
            )
        except Exception:
            pass

        if self._auto_flat_notify and self.telegram_notifier.enabled:
            try:
                msg = (
                    f"🚫 *Close All Trades Executed*\n\n"
                    f"Reason: `{reason}`\n"
                    f"Closed: `{closed_count}`\n"
                    f"Total P&L: `${total_pnl:,.2f}`"
                )
                await self.notification_queue.enqueue_raw_message(
                    msg, parse_mode="Markdown", dedupe=False, priority=Priority.HIGH
                )
            except Exception:
                pass

        return closed_count

    @property
    def streak_info(self) -> Dict[str, Any]:
        """Return current streak information."""
        return {
            "count": self._streak_count,
            "type": self._streak_type,
            "threshold": self._streak_alert_threshold,
        }

    @property
    def last_close_all_info(self) -> Dict[str, Any]:
        """Return information about the last close-all operation."""
        return {
            "at": self._last_close_all_at,
            "reason": self._last_close_all_reason,
            "count": self._last_close_all_count,
            "pnl": self._last_close_all_pnl,
            "price_source": self._last_close_all_price_source,
        }
