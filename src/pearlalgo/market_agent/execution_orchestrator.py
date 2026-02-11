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

**To migrate next (marked with ``# TODO(1A-migrate)`` in service.py):**
- ``_close_all_virtual_trades()`` — force-close all positions
- ``_close_specific_virtual_trades()`` — close by signal_id
- ``_handle_close_all_requests()`` — close-all coordination
- ``_check_execution_health()`` — execution adapter monitoring
- ``_check_execution_control_flags()`` — arm/disarm/kill file checks
- ``_check_daily_reset()`` — daily counter reset
"""

from __future__ import annotations

import json
from datetime import datetime, time
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from zoneinfo import ZoneInfo

from pearlalgo.utils.logger import logger

if TYPE_CHECKING:
    from pearlalgo.market_agent.virtual_trade_manager import VirtualTradeManager
    from pearlalgo.market_agent.order_manager import OrderManager
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager
    from pearlalgo.execution.base import ExecutionAdapter


class ExecutionOrchestrator:
    """
    Orchestrates the execution lifecycle: sizing → placement → tracking → exit.

    Dependencies are injected via the constructor so the class is independently
    testable and avoids circular imports with service.py.

    Current scope (delegation layer):
    - ``execute_signal()``: computes size via OrderManager, delegates placement
    - ``process_virtual_exits()``: delegates to VirtualTradeManager
    - ``get_active_positions()``: reads from state manager

    Future scope (method migration):
    - Auto-flat logic (daily/friday/weekend)
    - Close-all-virtual-trades coordination
    - Execution health checks
    """

    def __init__(
        self,
        *,
        virtual_trade_manager: "VirtualTradeManager",
        order_manager: "OrderManager",
        state_manager: "MarketAgentStateManager",
        execution_adapter: Optional["ExecutionAdapter"] = None,
    ):
        self._virtual_trade_manager = virtual_trade_manager
        self._order_manager = order_manager
        self._state_manager = state_manager
        self._execution_adapter = execution_adapter

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

        if tv_paper_enabled:
            if local_now.time() >= time(16, 8) and local_now.time() < time(16, 11):
                if last_dates.get("tv_paper_session_close") != local_now.date():
                    return "tv_paper_session_close"

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

    def clear_close_signals_requested(self) -> None:
        """Clear the close_signals_requested list in state.json."""
        try:
            self._state_manager.update_state({"close_signals_requested": []})
        except Exception as exc:
            logger.debug("Error clearing close_signals_requested: %s", exc)

    def clear_close_all_flag(self) -> None:
        """Clear close_all_requested flags in state.json."""
        try:
            self._state_manager.update_state({
                "close_all_requested": False,
                "close_all_requested_at": None,
            })
        except Exception as exc:
            logger.debug("Error clearing close_all_flag: %s", exc)
