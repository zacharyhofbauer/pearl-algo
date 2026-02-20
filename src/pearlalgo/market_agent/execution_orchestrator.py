"""
Execution Orchestrator

Coordinates order management, position tracking, and virtual trade lifecycle.

Part of the Arch-2 decomposition: service.py → orchestrator classes.

**Already migrated:**
- ``process_virtual_exits()`` — TP/SL exit scanning
- ``compute_position_size()`` — risk-based sizing
- ``get_active_virtual_trades()`` — active trade query
- ``auto_flat_due()`` — daily/friday/weekend auto-flat logic
- ``get_close_signals_requested()`` / ``clear_close_signals_requested()``
- ``clear_close_all_flag()``
- ``check_daily_reset()`` — daily counter reset
- ``check_execution_health()`` — execution adapter monitoring

**Not migrated (too coupled to service.py):**
- ``_close_all_virtual_trades()`` — needs performance_tracker, config,
  notification system, internal price helpers, and sets tracking state
  used by get_status()
- ``_close_specific_virtual_trades()`` — same coupling as above
- ``_handle_close_all_requests()`` — master coordinator calling 6+ tightly
  coupled internal methods plus broker flatten operations
- ``_check_execution_control_flags()`` — 278 lines, deeply intertwined
  with operator_handler, data_fetcher, and execution adapter state
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from zoneinfo import ZoneInfo

from pearlalgo.utils.logger import logger

if TYPE_CHECKING:
    from pearlalgo.market_agent.virtual_trade_manager import VirtualTradeManager
    from pearlalgo.market_agent.order_manager import OrderManager
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager
    from pearlalgo.market_agent.notification_queue import NotificationQueue, Priority
    from pearlalgo.execution.base import ExecutionAdapter, ExecutionConfig


class ExecutionOrchestrator:
    """
    Orchestrates the execution lifecycle: sizing → placement → tracking → exit.

    Dependencies are injected via the constructor so the class is independently
    testable and avoids circular imports with service.py.

    Current scope (delegation layer):
    - ``execute_signal()``: computes size via OrderManager, delegates placement
    - ``process_virtual_exits()``: delegates to VirtualTradeManager
    - ``get_active_positions()``: reads from state manager
    - ``check_daily_reset()``: resets execution counters at trading-day boundary
    - ``check_execution_health()``: monitors adapter connection + alerts
    """

    def __init__(
        self,
        *,
        virtual_trade_manager: "VirtualTradeManager",
        order_manager: "OrderManager",
        state_manager: "MarketAgentStateManager",
        execution_adapter: Optional["ExecutionAdapter"] = None,
        execution_config: Optional["ExecutionConfig"] = None,
        notification_queue: Optional["NotificationQueue"] = None,
        connection_alert_cooldown_seconds: int = 300,
    ):
        self._virtual_trade_manager = virtual_trade_manager
        self._order_manager = order_manager
        self._state_manager = state_manager
        self._execution_adapter = execution_adapter
        self._execution_config = execution_config
        self._notification_queue = notification_queue

        # State for check_daily_reset
        self._last_trading_day: Optional[date] = None

        # State for check_execution_health
        self._execution_was_connected: Optional[bool] = None
        self._last_connection_alert_time: Optional[datetime] = None
        self._connection_alert_cooldown_seconds: int = connection_alert_cooldown_seconds

        logger.debug("ExecutionOrchestrator initialized")

    # ------------------------------------------------------------------
    # Delegation: virtual trade exits
    # ------------------------------------------------------------------

    def process_virtual_exits(self, market_data: Dict[str, Any]) -> None:
        """
        Scan active virtual trades for TP/SL exits.

        Delegates to ``VirtualTradeManager.process_exits()`` which handles
        exit detection, performance recording, and policy reward updates.
        """
        try:
            self._virtual_trade_manager.process_exits(market_data)
        except Exception as exc:
            logger.debug("Virtual exit update failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Delegation: position sizing
    # ------------------------------------------------------------------

    def compute_position_size(self, signal: Dict[str, Any]) -> int:
        """
        Compute a position size for *signal* using risk and strategy rules.

        Delegates to ``OrderManager.compute_base_position_size()``.
        """
        return self._order_manager.compute_base_position_size(signal)

    # ------------------------------------------------------------------
    # Delegation: execution adapter queries
    # ------------------------------------------------------------------

    @property
    def is_execution_enabled(self) -> bool:
        """Return True if a live execution adapter is configured."""
        return self._execution_adapter is not None

    async def get_execution_status(self) -> Dict[str, Any]:
        """
        Return execution adapter status (connection, armed state, etc.).

        Returns a minimal dict when no adapter is configured.
        """
        if self._execution_adapter is None:
            return {"enabled": False}
        try:
            return {
                "enabled": True,
                "connected": getattr(self._execution_adapter, "is_connected", False),
                "armed": getattr(self._execution_adapter, "armed", False),
            }
        except Exception as exc:
            logger.debug("Execution status query failed: %s", exc)
            return {"enabled": True, "error": str(exc)}

    # ------------------------------------------------------------------
    # Delegation: active trades
    # ------------------------------------------------------------------

    def get_active_virtual_trades(self, *, limit: int = 300) -> List[Dict[str, Any]]:
        """
        Return active virtual trades (signals.jsonl with status=entered).

        Delegates to state_manager for the underlying file read.
        """
        try:
            recent_signals = self._state_manager.get_recent_signals(limit=limit)
            return [
                s for s in recent_signals
                if s.get("status") == "entered"
            ]
        except Exception as exc:
            logger.warning("Failed to retrieve active virtual trades: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Auto-flat logic (migrated from service.py)
    # ------------------------------------------------------------------

    def auto_flat_due(
        self,
        now_utc: datetime,
        *,
        market_open: Optional[bool],
        auto_flat_cfg: Dict[str, Any],
        last_dates: Dict[str, Any],
        tv_paper_enabled: bool = False,
    ) -> Optional[str]:
        """Return auto-flat reason if a daily/Friday/weekend rule triggers.

        Args:
            now_utc: Current UTC time.
            market_open: Whether the market is currently open.
            auto_flat_cfg: Auto-flat config dict with keys like ``enabled``,
                ``friday_enabled``, ``friday_time``, ``weekend_enabled``,
                ``timezone``, ``daily_enabled``, ``daily_time``.
            last_dates: Mutable dict tracking last-triggered date per reason
                (prevents duplicate triggers on the same day).
            tv_paper_enabled: Whether Tradovate Paper evaluation mode is active.

        Returns:
            Reason string (e.g. ``"daily_auto_flat"``) or ``None``.
        """
        tz_name = auto_flat_cfg.get("timezone", "America/New_York")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("America/New_York")

        local_now = now_utc.astimezone(tz)
        weekday = local_now.weekday()

        if auto_flat_cfg.get("enabled") and auto_flat_cfg.get("daily_enabled"):
            dh, dm = auto_flat_cfg.get("daily_time", (16, 55))
            if local_now.time() >= time(dh, dm):
                if last_dates.get("daily_auto_flat") != local_now.date():
                    return "daily_auto_flat"

        if auto_flat_cfg.get("friday_enabled") and weekday == 4:
            fh, fm = auto_flat_cfg.get("friday_time", (16, 55))
            if local_now.time() >= time(fh, fm):
                if last_dates.get("friday_auto_flat") != local_now.date():
                    return "friday_auto_flat"

        if auto_flat_cfg.get("weekend_enabled") and market_open is False:
            is_weekend_window = (
                weekday == 5
                or (weekday == 6 and local_now.time() < time(18, 0))
                or (weekday == 4 and local_now.time() >= time(17, 0))
            )
            if is_weekend_window:
                if last_dates.get("weekend_auto_flat") != local_now.date():
                    return "weekend_auto_flat"

        return None

    # ------------------------------------------------------------------
    # Close-request helpers (migrated from service.py)
    # ------------------------------------------------------------------

    def get_close_signals_requested(self) -> List[str]:
        """Return list of signal_ids requested for manual close via state.json."""
        try:
            state = self._state_manager.load_state()
            return list(state.get("close_signals_requested", []))
        except Exception as exc:
            logger.debug("Error reading close_signals_requested: %s", exc)
            return []

    def clear_close_signals_requested(self, signal_ids: list = None) -> None:
        """Clear specific signal close requests or all of them from state.json."""
        try:
            state = self._state_manager.load_state()
        except Exception as exc:
            logger.debug("Error loading state for close_signals_requested: %s", exc)
            return
        if not isinstance(state, dict):
            return

        current_requests = state.get("close_signals_requested", [])
        if signal_ids is None:
            # Clear all
            state.pop("close_signals_requested", None)
            state.pop("close_signals_requested_time", None)
        else:
            # Remove specific signal_ids
            state["close_signals_requested"] = [s for s in current_requests if s not in signal_ids]
            if not state["close_signals_requested"]:
                state.pop("close_signals_requested", None)
                state.pop("close_signals_requested_time", None)

        try:
            self._state_manager.save_state(state)
        except Exception as exc:
            logger.debug("Error clearing close_signals_requested: %s", exc)

    def clear_close_all_flag(self) -> None:
        """Clear close_all_requested flags in state.json."""
        try:
            state = self._state_manager.load_state()
        except Exception as exc:
            logger.debug("Error loading state for close_all_flag: %s", exc)
            return
        if not isinstance(state, dict):
            return
        state.pop("close_all_requested", None)
        state.pop("close_all_requested_time", None)
        state.pop("close_all_requested_at", None)
        try:
            self._state_manager.save_state(state)
        except Exception as exc:
            logger.debug("Error clearing close_all_flag: %s", exc)

    # ------------------------------------------------------------------
    # Daily reset (migrated from service.py)
    # ------------------------------------------------------------------

    def check_daily_reset(self) -> None:
        """
        Reset execution daily counters at start of new trading day.

        This ensures:
        - _orders_today counter resets to 0 each day
        - _daily_pnl resets to 0.0 each day (for kill switch threshold)
        - Per-signal-type cooldowns clear

        Called at start of each scan cycle in the main loop.
        """
        if self._execution_adapter is None:
            return

        from pearlalgo.market_agent.stats_computation import get_trading_day_start

        # Use 6pm ET as the trading day boundary
        today = get_trading_day_start().date()

        if self._last_trading_day is None:
            # First cycle - initialize but don't reset (may be mid-day startup)
            self._last_trading_day = today
            return

        if self._last_trading_day != today:
            # New trading day (6pm ET boundary crossed) - reset counters
            self._execution_adapter.reset_daily_counters()
            logger.info(
                f"Execution daily counters reset for {today} "
                f"(previous day: {self._last_trading_day}) - 6pm ET boundary"
            )
            self._last_trading_day = today

    # ------------------------------------------------------------------
    # Execution health monitoring (migrated from service.py)
    # ------------------------------------------------------------------

    async def check_execution_health(self) -> None:
        """
        Check execution adapter connection health and send alerts on state changes.

        Sends Telegram alert when:
        - Connection is lost (was connected, now disconnected)
        - Connection is restored (was disconnected, now connected)

        Deduplicates alerts using cooldown to prevent spam.
        """
        if self._execution_adapter is None:
            return

        # Only check if execution is enabled
        if self._execution_config is None or not self._execution_config.enabled:
            return

        is_connected = self._execution_adapter.is_connected()
        now = datetime.now(timezone.utc)

        # Initialize state on first check
        if self._execution_was_connected is None:
            self._execution_was_connected = is_connected
            return

        # Check for state change
        if is_connected != self._execution_was_connected:
            # Check cooldown to avoid alert spam
            should_alert = True
            if self._last_connection_alert_time is not None:
                elapsed = (now - self._last_connection_alert_time).total_seconds()
                if elapsed < self._connection_alert_cooldown_seconds:
                    should_alert = False

            if should_alert and self._notification_queue is not None:
                self._last_connection_alert_time = now

                if is_connected:
                    # Connection restored
                    message = (
                        "✅ *IBKR Execution Connected*\n\n"
                        "Connection to IBKR Gateway has been restored.\n"
                        f"Execution adapter is now {'armed' if self._execution_adapter.armed else 'disarmed'}."
                    )
                    logger.info("IBKR execution connection restored")
                else:
                    # Connection lost
                    message = (
                        "🔴 *IBKR Execution Disconnected*\n\n"
                        "⚠️ Connection to IBKR Gateway has been lost.\n\n"
                        "• Orders cannot be placed\n"
                        "• Auto-reconnection will be attempted\n"
                        "• Use `/positions` to check status"
                    )
                    logger.warning("IBKR execution connection lost")

                # Send Telegram alert (through notification queue)
                try:
                    from pearlalgo.market_agent.notification_queue import Priority
                    await self._notification_queue.enqueue_raw_message(
                        message,
                        parse_mode="Markdown",
                        priority=Priority.NORMAL,
                    )
                except Exception as e:
                    logger.error(f"Failed to queue connection alert: {e}")

            # Update state
            self._execution_was_connected = is_connected
