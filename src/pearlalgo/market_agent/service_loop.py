"""
Service Loop Mixin -- _run_loop() and its direct helpers.

Extracted from service.py for better code organization.
This is the main trading scan loop -- handle with care.
"""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.utils.formatting import fmt_currency
from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.paths import parse_utc_timestamp
from pearlalgo.utils.market_hours import get_market_hours
from pearlalgo.market_agent.audit_logger import AuditEventType
from pearlalgo.market_agent.notification_queue import Priority

if TYPE_CHECKING:
    pass  # MarketAgentService accessed via self


class ServiceLoopMixin:
    """Mixin providing the main scan loop for MarketAgentService."""

    async def _run_loop(self) -> None:
        """Main service loop."""
        logger.info(
            "Starting main loop",
            extra={
                "scan_interval": self.config.scan_interval,
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "cadence_mode": self.cadence_mode,
            },
        )

        while not self.shutdown_requested:
            # Check for execution control flag files (from Telegram commands)
            await self._check_execution_control_flags()

            # Reset execution daily counters if new trading day
            self.execution_orchestrator.check_daily_reset()

            # Check for morning briefing (6:30 AM ET)
            await self.scheduled_tasks.check_morning_briefing()

            # Check for safety close daily summary (3:55 PM ET / 4:00 PM ET)
            await self.scheduled_tasks.check_market_close_summary()

            # Check execution adapter connection health and alert on issues
            await self.execution_orchestrator.check_execution_health()

            # Prune old signals from signals.jsonl (once per day)
            await self.scheduled_tasks.check_signal_pruning()

            # Audit scheduled tasks: retention + equity snapshot (once per day each)
            await self.scheduled_tasks.check_audit_retention()
            await self.scheduled_tasks.check_equity_snapshot()

            # Adaptive cadence: compute effective interval for this cycle (includes velocity mode)
            if self._adaptive_cadence_enabled:
                self._effective_interval = self._compute_effective_interval()
                if self._effective_interval != self._last_effective_interval:
                    # Log interval change (velocity transitions are logged separately in _compute_effective_interval)
                    if not self._velocity_mode_active:
                        logger.info(
                            f"Adaptive cadence: interval changed {self._last_effective_interval}s → {self._effective_interval}s",
                            extra={
                                "old_interval": self._last_effective_interval,
                                "new_interval": self._effective_interval,
                                "cycle": self.cycle_count,
                            },
                        )
                    # Update cadence scheduler with new interval (velocity mode state already set in _compute_effective_interval)
                    if self.cadence_scheduler and not self._velocity_mode_active:
                        self.cadence_scheduler.set_interval(self._effective_interval, velocity_mode=False)
                    self._last_effective_interval = self._effective_interval

            # Mark cycle start for cadence tracking (fixed-cadence mode)
            if self.cadence_scheduler:
                cadence_lag = self.cadence_scheduler.mark_cycle_start()
                if cadence_lag > 1000:  # More than 1s lag
                    logger.warning(
                        f"Cadence lag detected: {cadence_lag:.0f}ms behind schedule",
                        extra={"cycle": self.cycle_count, "cadence_lag_ms": cadence_lag},
                    )

            try:
                # Skip if paused
                if self.paused:
                    logger.info(
                        "Service paused; skipping cycle",
                        extra={
                            "cycle": self.cycle_count,
                            "pause_reason": self.pause_reason,
                        },
                    )
                    try:
                        self.state_manager.append_event(
                            "paused_cycle_skipped",
                            {"cycle": int(self.cycle_count or 0), "pause_reason": str(self.pause_reason or "")},
                            level="info",
                        )
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")
                    # Reset cadence scheduler on pause to avoid catch-up storm on resume
                    if self.cadence_scheduler:
                        self.cadence_scheduler.reset()
                    # SAFETY: Use interruptible sleep so kill commands are processed even when paused
                    await self._interruptible_sleep(self._scan_interval_paused)
                    continue

                # Poll Tradovate account data early (before data fetch)
                # so dashboard shows live broker values even when IBKR data is unavailable
                _tv_polled = False
                if self.execution_adapter is not None and hasattr(self.execution_adapter, "get_account_summary"):
                    try:
                        self._tradovate_account = await self.execution_adapter.get_account_summary()
                        _tv_polled = True
                    except Exception as e:
                        logger.debug(f"Tradovate account poll (non-critical): {e}")

                # Save state after Tradovate poll even if data fetch will fail.
                # This ensures the dashboard shows live broker values during IBKR outages.
                if _tv_polled:
                    try:
                        self._save_state(force=True)
                    except Exception as e:
                        logger.debug(f"Early state save (non-critical): {e}")

                # Fetch latest data with error handling
                try:
                    try:
                        self.state_manager.append_event(
                            "scan_started",
                            {
                                "cycle": int(self.cycle_count or 0),
                                "scan_interval_effective": float(getattr(self, "_effective_interval", self.config.scan_interval) or 0),
                                "symbol": str(self.config.symbol),
                            },
                            level="info",
                        )
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")
                    market_data = await self.data_fetcher.fetch_latest_data()

                    # Check if data is empty due to connection issues
                    is_connection_error = ErrorHandler.is_connection_error_from_data(
                        market_data,
                        data_provider=self.data_fetcher.data_provider,
                        last_successful_cycle=self.last_successful_cycle,
                    )

                    if is_connection_error:
                        # This is a connection issue, not just empty data
                        self.connection_failures += 1
                        self.data_fetch_errors += 1
                        self.error_count += 1
                        run_cycle_despite_connection_error = False

                        # Circuit breaker: pause service if too many connection failures (unless disabled)
                        if self.connection_failures >= self.max_connection_failures:
                            if getattr(self, "pause_on_connection_failures", True):
                                logger.error(
                                    "Circuit breaker triggered: connection failures",
                                    extra={
                                        "connection_failures": self.connection_failures,
                                        "max_connection_failures": self.max_connection_failures,
                                        "cycle": self.cycle_count,
                                    },
                                )
                                # Audit: connection drop threshold
                                if self.audit_logger is not None:
                                    self.audit_logger.log_system_event(
                                        AuditEventType.CONNECTION_DROP,
                                        {
                                            "connection_failures": self.connection_failures,
                                            "max_connection_failures": self.max_connection_failures,
                                            "cycle": self.cycle_count,
                                        },
                                    )
                                # Guard: only send the circuit breaker notification once per event
                                if not self._cb_connection_notified:
                                    self._cb_connection_notified = True
                                    await self.notification_queue.enqueue_circuit_breaker(
                                        "IB Gateway connection lost",
                                        {
                                            "connection_failures": self.connection_failures,
                                            "error_type": "connection",
                                            "action_taken": "Service paused - IB Gateway appears to be down",
                                        },
                                        priority=Priority.CRITICAL,
                                    )
                                self.paused = True
                                self.pause_reason = "connection_failures"
                            else:
                                # pause_on_connection_failures=false: if we have usable data, run loop anyway
                                # (executor may report disconnected while data is actually flowing)
                                df = market_data.get("df")
                                if df is not None and not df.empty:
                                    self.data_fetch_errors = 0
                                    self.connection_failures = 0
                                    self._cb_connection_notified = False
                                    self.last_successful_cycle = datetime.now(timezone.utc)
                                    run_cycle_despite_connection_error = True
                                    logger.info(
                                        "Connection-failure threshold hit but pause disabled; data usable, continuing cycle",
                                        extra={"cycle": self.cycle_count},
                                    )
                                else:
                                    logger.warning(
                                        "Connection failures threshold reached (pause disabled for this account)",
                                        extra={
                                            "connection_failures": self.connection_failures,
                                            "max_connection_failures": self.max_connection_failures,
                                            "cycle": self.cycle_count,
                                        },
                                    )
                                    await self._handle_connection_failure()
                                    await self._sleep_until_next_cycle()
                                    continue
                        else:
                            await self._handle_connection_failure()

                        if not run_cycle_despite_connection_error:
                            await self._sleep_until_next_cycle()
                            continue

                    # Success - reset error counters (or run_cycle_despite_connection_error with data)
                    self.data_fetch_errors = 0
                    self.connection_failures = 0
                    self._cb_connection_notified = False
                    self.last_successful_cycle = datetime.now(timezone.utc)

                    # Check data quality
                    await self._check_data_quality(market_data)

                    # Close-all handler (manual flag + auto-flat rules)
                    try:
                        await self._handle_close_all_requests(market_data)
                    except Exception as e:
                        logger.warning(f"Critical path error: {e}", exc_info=True)

                except Exception as e:
                    # Use ErrorHandler for standardized error handling
                    error_info = ErrorHandler.handle_data_fetch_error(
                        e,
                        context={"cycle_count": self.cycle_count},
                    )
                    self.data_fetch_errors += 1
                    self.error_count += 1

                    # Check if this is a connection error
                    if error_info.get("is_connection_error", False):
                        self.connection_failures += 1
                        await self._handle_connection_failure()

                    # Alert on consecutive fetch failures
                    if self.data_fetch_errors >= 3:
                        await self.notification_queue.enqueue_data_quality_alert(
                            "fetch_failure",
                            f"Consecutive data fetch failures: {self.data_fetch_errors}",
                            {"consecutive_failures": self.data_fetch_errors},
                            priority=Priority.NORMAL,
                        )

                    # Circuit breaker: if too many data fetch errors, wait longer
                    if self.data_fetch_errors >= self.max_data_fetch_errors:
                        logger.warning(
                            "Data fetch error threshold reached; backing off",
                            extra={
                                "data_fetch_errors": self.data_fetch_errors,
                                "max_data_fetch_errors": self.max_data_fetch_errors,
                                "backoff_seconds": self.config.scan_interval * 2,
                                "cycle": self.cycle_count,
                            },
                        )
                        # Audit: error threshold reached
                        if self.audit_logger is not None:
                            self.audit_logger.log_system_event(
                                AuditEventType.ERROR_THRESHOLD,
                                {
                                    "data_fetch_errors": self.data_fetch_errors,
                                    "max_data_fetch_errors": self.max_data_fetch_errors,
                                    "cycle": self.cycle_count,
                                },
                            )
                        await self._notify_error("Data fetch failures", f"{self.data_fetch_errors} consecutive errors")
                        # Backoff: sleep longer than normal cycle, reset cadence scheduler
                        if self.cadence_scheduler:
                            self.cadence_scheduler.reset()
                        # SAFETY: Use interruptible sleep so kill commands are processed during backoff
                        await self._interruptible_sleep(self.config.scan_interval * 2)
                    else:
                        await self._sleep_until_next_cycle()
                    continue

                if market_data["df"].empty:
                    # Empty data could be normal (market closed) or a problem
                    # Check if we've had recent successful cycles
                    if self.last_successful_cycle:
                        time_since_success = (datetime.now(timezone.utc) - self.last_successful_cycle).total_seconds()
                        timeout_seconds = self.connection_timeout_minutes * 60
                        if time_since_success > timeout_seconds:
                            logger.warning(f"No market data for {self.connection_timeout_minutes}+ minutes - possible connection issue")
                            await self._handle_connection_failure()

                    # Determine quiet reason for observability
                    quiet_reason = self._get_quiet_reason(market_data, has_data=False)

                    # Persist to instance variables for _save_state() (surfaced in /status)
                    self._last_quiet_reason = quiet_reason
                    self._last_signal_diagnostics = None

                    logger.debug(
                        "No market data available, waiting",
                        extra={
                            "cycle": self.cycle_count,
                            "connection_failures": self.connection_failures,
                            "quiet_reason": quiet_reason,
                        },
                    )

                    # Check for proactive Pearl suggestions (agentic)
                    await self._check_pearl_suggestions()

                    # Still emit dashboard even when quiet (observability)
                    self.cycle_count += 1

                    await self._sleep_until_next_cycle()
                    continue

                # New-bar gating: skip heavy analysis if df hasn't advanced (performance optimization).
                # When enabled, we only run strategy.analyze() when a new bar arrives.
                # This is high leverage for configs like 5m bars + 30s scan interval.
                skip_analysis = False
                current_bar_ts = None
                if self._enable_new_bar_gating and not market_data["df"].empty:
                    # Extract latest bar timestamp from df
                    df = market_data["df"]
                    if "timestamp" in df.columns:
                        current_bar_ts = df["timestamp"].max()
                        if isinstance(current_bar_ts, pd.Timestamp):
                            current_bar_ts = current_bar_ts.to_pydatetime()
                        if current_bar_ts is not None and current_bar_ts.tzinfo is None:
                            current_bar_ts = current_bar_ts.replace(tzinfo=timezone.utc)

                        # Check if bar has advanced since last analyzed cycle
                        if self._last_analyzed_bar_ts is not None and current_bar_ts == self._last_analyzed_bar_ts:
                            skip_analysis = True
                            self._analysis_skip_count += 1
                            logger.debug(
                                "New-bar gating: skipping analysis (bar unchanged)",
                                extra={
                                    "bar_ts": current_bar_ts.isoformat() if current_bar_ts else None,
                                    "skip_count": self._analysis_skip_count,
                                    "run_count": self._analysis_run_count,
                                    "cycle": self.cycle_count,
                                },
                            )

                # Inject safety/learning state into market_data so downstream signal generation can:
                # - run ML filter in score-only or lift-gated blocking mode
                # - apply drift guard cooldown adjustments (tighten filters + reduce size)
                try:
                    if isinstance(market_data, dict):
                        market_data["ml_blocking_allowed"] = bool(getattr(self, "_ml_blocking_allowed", False))
                except Exception as e:
                    logger.warning(f"Critical path error: {e}", exc_info=True)

                # Generate signals (or skip if no new bar)
                signals = []
                if skip_analysis:
                    # Lightweight cycle: skip heavy analysis, but still run health/status/exit grading
                    pass
                else:
                    # Full analysis: new bar arrived
                    # Run pearl_bot_auto strategy
                    # Use run_in_executor to avoid blocking the event loop during
                    # CPU-bound indicator computation (EMA, ATR, S&R channels, etc.)
                    df = market_data.get("df")
                    if df is not None and not df.empty:
                        _analyze_fn = functools.partial(
                            self.strategy.analyze, df, current_time=datetime.now(timezone.utc)
                        )
                        loop = asyncio.get_event_loop()
                        signals = await loop.run_in_executor(None, _analyze_fn)
                    else:
                        signals = []
                    self._analysis_run_count += 1
                    # Update last analyzed bar timestamp
                    if current_bar_ts is not None:
                        self._last_analyzed_bar_ts = current_bar_ts

                # Log cycle summary for observability
                data_fresh = True
                latest_bar_time: Optional[datetime] = None
                if market_data.get("latest_bar"):
                    raw_bar_time = market_data["latest_bar"].get("timestamp")
                    if raw_bar_time:
                        if isinstance(raw_bar_time, str):
                            latest_bar_time = parse_utc_timestamp(raw_bar_time)
                        else:
                            latest_bar_time = raw_bar_time
                        # Timezone-safe age computation: convert to UTC if aware, assume UTC if naive
                        if latest_bar_time.tzinfo is None:
                            latest_bar_time = latest_bar_time.replace(tzinfo=timezone.utc)
                        else:
                            latest_bar_time = latest_bar_time.astimezone(timezone.utc)
                        age_seconds = (datetime.now(timezone.utc) - latest_bar_time).total_seconds()
                        stale_threshold_seconds = self.stale_data_threshold_minutes * 60
                        data_fresh = age_seconds < stale_threshold_seconds

                # Prefer latest_bar timestamp for session check (reduces wall-clock drift issues).
                # Fall back to wall-clock time if no latest_bar available.
                from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
                check_time = latest_bar_time if latest_bar_time else datetime.now(timezone.utc)
                strategy_session_open = check_trading_session(check_time, self.config)
                futures_market_open = False
                try:
                    futures_market_open = bool(get_market_hours().is_market_open())
                except Exception as e:
                    logger.warning(f"Market hours check failed in run loop: {e}")
                    futures_market_open = False
                logger.info(
                    "Cycle completed",
                    extra={
                        "cycle": self.cycle_count,
                        "signals": len(signals),
                        "data_fresh": data_fresh,
                        # Keep legacy field name for backward compatibility, but make semantics explicit.
                        # Historically this has meant the strategy trading session window (09:30–16:00 ET).
                        "market_open": strategy_session_open,
                        "strategy_session_open": strategy_session_open,
                        "futures_market_open": futures_market_open,
                        "buffer_size": self.data_fetcher.get_buffer_size(),
                        "error_count": self.error_count,
                        "consecutive_errors": self.consecutive_errors,
                        "connection_failures": self.connection_failures,
                        "data_fetch_errors": self.data_fetch_errors,
                    },
                )

                # Process signals
                if signals:
                    logger.info(f"🔔 Processing {len(signals)} signal(s) from strategy analysis")
                    for i, signal_obj in enumerate(signals, 1):
                        signal_type = signal_obj.get('type', 'unknown')
                        signal_direction = signal_obj.get('direction', 'unknown')
                        trade_type = signal_obj.get('trade_type', 'scalp')
                        logger.info(f"  Signal {i}/{len(signals)}: {signal_type} {signal_direction} ({trade_type})")

                        # Notify if swing trade detected
                        if trade_type == "swing":
                            try:
                                await self.notification_queue.enqueue_raw_message(
                                    f"📈 Swing Trade Detected: {signal_type} {signal_direction}\n"
                                    f"Confidence: {signal_obj.get('confidence', 0):.1%}\n"
                                    f"Target: {fmt_currency(signal_obj.get('take_profit', 0))}",
                                    priority=Priority.NORMAL,
                                )
                            except Exception as e:
                                logger.debug(f"Non-critical: {e}")

                        # Attach bar timestamp for signal forwarding (writer mode)
                        if current_bar_ts is not None:
                            signal_obj["_bar_timestamp"] = current_bar_ts.isoformat()

                        # Get buffer data for chart generation
                        buffer_data = market_data.get("df", pd.DataFrame())

                        # Audit: signal generated
                        if self.audit_logger is not None:
                            try:
                                self.audit_logger.log_signal_generated(signal_obj)
                            except Exception as exc:
                                ErrorHandler.log_and_continue("audit_signal_generated", exc, level="warning")

                        try:
                            self.state_manager.append_event(
                                "signal_generated",
                                {
                                    "cycle": int(self.cycle_count or 0),
                                    "symbol": str(signal_obj.get("symbol") or self.config.symbol),
                                    "type": str(signal_obj.get("type") or "unknown"),
                                    "direction": str(signal_obj.get("direction") or "unknown"),
                                    "trade_type": str(signal_obj.get("trade_type") or ""),
                                    "confidence": float(signal_obj.get("confidence") or 0.0),
                                    "entry_price": float(signal_obj.get("entry_price") or 0.0),
                                    "stop_loss": float(signal_obj.get("stop_loss") or 0.0),
                                    "take_profit": float(signal_obj.get("take_profit") or 0.0),
                                },
                                level="info",
                            )
                        except Exception as e:
                            logger.debug(f"Non-critical: {e}")
                        if self._signal_follower_mode:
                            # Follower: use streamlined path (skips ML/bandit)
                            await self._signal_handler.follower_execute(signal_obj)
                        else:
                            await self._signal_handler.process_signal(signal_obj, buffer_data=buffer_data)
                        self._sync_signal_handler_counters()
                else:
                    logger.debug(f"No signals generated in cycle {self.cycle_count}")

                # Virtual PnL lifecycle: exit signals when TP/SL is touched (no Telegram spam).
                # This grades signal quality without auto-trading.
                try:
                    self._update_virtual_trade_exits(market_data)
                except Exception as e:
                    logger.debug(f"Virtual exit update failed (non-fatal): {e}")

                # Refresh ML lift metrics AFTER we grade exits (so decisions use latest outcomes).
                try:
                    self.signal_orchestrator.refresh_ml_lift()
                except Exception as e:
                    logger.debug(f"ML lift refresh failed (non-fatal): {e}")

                # Send periodic dashboard (replaces status + heartbeat)
                # Determine quiet reason (for observability) and capture diagnostics every cycle (for SQLite rollups).
                quiet_reason = "Active" if signals else self._get_quiet_reason(market_data, has_data=True, no_signals=True)
                signal_diagnostics = None
                signal_diagnostics_raw = None

                # Persist to instance variables for _save_state() (surfaced in /status)
                self._last_quiet_reason = quiet_reason
                self._last_signal_diagnostics = signal_diagnostics
                self._last_signal_diagnostics_raw = signal_diagnostics_raw

                # SQLite observability: persist per-cycle diagnostics for 24h /doctor summaries.
                self._persist_cycle_diagnostics(
                    quiet_reason=quiet_reason,
                    diagnostics_raw=signal_diagnostics_raw,
                )

                # Check for proactive Pearl suggestions (agentic)
                await self._check_pearl_suggestions()

                try:
                    self.state_manager.append_event(
                        "scan_finished",
                        {
                            "cycle": int(self.cycle_count or 0),
                            "signals": int(len(signals) if signals else 0),
                            "quiet_reason": str(quiet_reason or ""),
                            "signal_diagnostics": str(signal_diagnostics or "") if signal_diagnostics is not None else None,
                            "data_fresh": bool(data_fresh),
                            "strategy_session_open": bool(strategy_session_open),
                            "futures_market_open": bool(futures_market_open),
                            "buffer_size": int(self.data_fetcher.get_buffer_size() or 0),
                            "error_count": int(self.error_count or 0),
                        },
                        level="info",
                    )
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

                # Poll Tradovate account data (Tradovate Paper: real broker values for dashboard)
                if self.execution_adapter is not None and hasattr(self.execution_adapter, "get_account_summary"):
                    try:
                        self._tradovate_account = await self.execution_adapter.get_account_summary()
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")  # non-fatal: stale cache is fine

                # Detect Tradovate Paper connection state changes for Telegram alerts
                if self.execution_adapter is not None and hasattr(self.execution_adapter, 'is_connected'):
                    _now_connected = self.execution_adapter.is_connected()
                    if self._tv_paper_was_connected is not None and _now_connected != self._tv_paper_was_connected:
                        if _now_connected:
                            logger.info("Tradovate Paper execution reconnected")
                            try:
                                await self.notification_queue.enqueue_raw_message(
                                    "✅ Tradovate Paper execution reconnected.",
                                    priority=Priority.NORMAL,
                                )
                            except Exception as exc:
                                ErrorHandler.log_and_continue("tradovate_reconnect_notification", exc, level="warning")
                        else:
                            logger.warning("Tradovate Paper execution disconnected")
                            try:
                                await self.notification_queue.enqueue_raw_message(
                                    "🚨 Tradovate Paper execution DISCONNECTED. Auto-reconnect will attempt.",
                                    priority=Priority.HIGH,
                                )
                            except Exception as exc:
                                ErrorHandler.log_and_continue("tradovate_disconnect_notification", exc, level="warning")
                    self._tv_paper_was_connected = _now_connected

                # Save state periodically, OR immediately when a signal was
                # generated/entered this cycle (so the API serves fresh data).
                _signal_this_cycle = bool(
                    self.last_signal_generated_at
                    and self._last_signal_diagnostics is not None
                )
                if _signal_this_cycle:
                    self.mark_state_dirty()
                if self._state_dirty or self.cycle_count % self.state_save_interval == 0:
                    self._save_state(force=True)

                self.cycle_count += 1

                # Wait for next cycle (fixed-cadence or legacy sleep-after-work)
                await self._sleep_until_next_cycle()

            except asyncio.CancelledError:
                logger.info("Service loop cancelled", extra={"cycle": self.cycle_count})
                break
            except Exception as e:
                logger.error(
                    f"Error in service loop: {e}",
                    exc_info=True,
                    extra={"cycle": self.cycle_count},
                )
                try:
                    self.state_manager.append_event(
                        "error",
                        {"cycle": int(self.cycle_count or 0), "message": str(e)[:500]},
                        level="error",
                    )
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")
                self.error_count += 1
                self.consecutive_errors += 1

                # Circuit breaker: if too many consecutive errors, pause service
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logger.error(
                        "Circuit breaker triggered: consecutive errors",
                        extra={
                            "consecutive_errors": self.consecutive_errors,
                            "max_consecutive_errors": self.max_consecutive_errors,
                            "cycle": self.cycle_count,
                        },
                    )
                    try:
                        self.state_manager.append_event(
                            "circuit_breaker",
                            {
                                "cycle": int(self.cycle_count or 0),
                                "type": "consecutive_errors",
                                "consecutive_errors": int(self.consecutive_errors or 0),
                                "max_consecutive_errors": int(self.max_consecutive_errors or 0),
                            },
                            level="error",
                        )
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")
                    if not self._cb_connection_notified:
                        # Only notify if the connection CB hasn't already sent an alert
                        await self.notification_queue.enqueue_circuit_breaker(
                            "Too many consecutive errors",
                            {
                                "consecutive_errors": self.consecutive_errors,
                                "error_type": "general",
                                "action_taken": "Service paused",
                            },
                            priority=Priority.CRITICAL,
                        )
                    self.paused = True
                    self.pause_reason = "consecutive_errors"

                await self._sleep_until_next_cycle()
            else:
                # Reset consecutive errors on successful cycle
                had_errors = self.consecutive_errors > 0
                self.consecutive_errors = 0

                # Send recovery notification if we had errors and now recovered
                if had_errors:
                    try:
                        await self.notification_queue.enqueue_recovery(
                            {
                                "issue": "Consecutive errors resolved",
                                "recovery_time_seconds": 0,
                            },
                            priority=Priority.NORMAL,
                        )
                    except Exception as e:
                        logger.warning(f"Could not queue recovery notification: {e}")
