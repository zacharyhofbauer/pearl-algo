"""
Execution Orchestrator

Coordinates order management, position tracking, and virtual trade lifecycle.
Thin delegation layer that routes calls to ExecutionAdapter,
VirtualTradeManager, and OrderManager.

Part of the Arch-2 decomposition: service.py → orchestrator classes.
This file provides the framework; actual method migration happens incrementally.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

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
