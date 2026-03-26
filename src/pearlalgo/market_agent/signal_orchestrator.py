"""
Signal Orchestrator

Coordinates signal processing.

Part of the Arch-2 decomposition: service.py -> orchestrator classes.

**Already migrated:**
- ``process_signals()`` -- batch signal processing

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from pearlalgo.utils.logger import logger

if TYPE_CHECKING:
    from pearlalgo.market_agent.signal_handler import SignalHandler
    from pearlalgo.market_agent.order_manager import OrderManager
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager


class SignalOrchestrator:
    """
    Orchestrates the full signal lifecycle: generation -> filtering -> decision -> dispatch.

    Dependencies are injected via the constructor so the class is independently
    testable and avoids circular imports with service.py.

    Scope:
    - ``process_signals()``: delegates to SignalHandler.process_signal()
    """

    def __init__(
        self,
        *,
        signal_handler: "SignalHandler",
        order_manager: "OrderManager",
        state_manager: "MarketAgentStateManager",
    ):
        self._signal_handler = signal_handler
        self._order_manager = order_manager
        self._state_manager = state_manager

        logger.debug("SignalOrchestrator initialized")

    # ------------------------------------------------------------------
    # Delegation: signal processing
    # ------------------------------------------------------------------

    async def process_signals(
        self,
        signals: list[Dict[str, Any]],
        market_data: Dict[str, Any],
        *,
        sync_counters_callback: Any = None,
    ) -> int:
        """
        Process a batch of signals through the full pipeline.

        Delegates each signal to ``SignalHandler.process_signal()`` and
        invokes the counter-sync callback after each one.

        Args:
            signals: List of signal dicts from strategy analysis.
            market_data: Current cycle market data (contains ``df``).
            sync_counters_callback: Called after each signal to sync
                handler counters back to the service.

        Returns:
            Number of signals processed.
        """
        buffer_data = market_data.get("df", pd.DataFrame())
        processed = 0
        for signal in signals:
            try:
                await self._signal_handler.process_signal(signal, buffer_data=buffer_data)
                processed += 1
            except Exception as exc:
                logger.error("SignalOrchestrator: error processing signal: %s", exc, exc_info=True)
            finally:
                if sync_counters_callback is not None:
                    try:
                        sync_counters_callback()
                    except Exception as exc:
                        logger.debug("Non-critical counter sync error: %s", exc)
        return processed
