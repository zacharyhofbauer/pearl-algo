"""
Signal Orchestrator

Coordinates signal processing, ML filtering, and bandit/policy decisions.

Part of the Arch-2 decomposition: service.py → orchestrator classes.

**Already migrated:**
- ``process_signals()`` — batch signal processing
- ``configure_ml_filter()`` — ML filter reconfiguration
- ``build_context_features()`` — contextual bandit feature building
- ``refresh_ml_lift()`` — ML lift evaluation
- ``compute_ml_lift_metrics()`` — shadow A/B lift calculation
- ``build_ml_training_trades_from_signals()`` — training sample extraction

**Not migrated (too coupled to service.py):**
- Signal forwarding coordination — already lives in SignalForwarder class
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from pearlalgo.utils.logger import logger

if TYPE_CHECKING:
    from pearlalgo.market_agent.signal_handler import SignalHandler
    from pearlalgo.market_agent.order_manager import OrderManager
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager
    from pearlalgo.market_agent.signal_forwarder import SignalForwarder
    from pearlalgo.market_agent.ml_manager import MLManager
    from pearlalgo.learning.ml_signal_filter import MLSignalFilter
    from pearlalgo.learning.bandit_policy import BanditPolicy


class SignalOrchestrator:
    """
    Orchestrates the full signal lifecycle: generation → filtering → decision → dispatch.

    Dependencies are injected via the constructor so the class is independently
    testable and avoids circular imports with service.py.

    Scope:
    - ``process_signals()``: delegates to SignalHandler.process_signal()
    - ``configure_ml_filter()``: reconfigures ML components at runtime
    - ``refresh_ml_lift()`` / ``compute_ml_lift_metrics()``: ML lift evaluation
    - ``build_ml_training_trades_from_signals()``: training sample extraction
    - ``build_context_features()``: contextual bandit feature building
    """

    def __init__(
        self,
        *,
        signal_handler: "SignalHandler",
        order_manager: "OrderManager",
        state_manager: "MarketAgentStateManager",
        signal_forwarder: Optional["SignalForwarder"] = None,
        ml_signal_filter: Optional["MLSignalFilter"] = None,
        bandit_policy: Optional["BanditPolicy"] = None,
        ml_filter_enabled: bool = False,
        ml_filter_mode: str = "shadow",
        ml_manager: Optional["MLManager"] = None,
    ):
        self._signal_handler = signal_handler
        self._order_manager = order_manager
        self._state_manager = state_manager
        self._signal_forwarder = signal_forwarder
        self._ml_signal_filter = ml_signal_filter
        self._bandit_policy = bandit_policy
        self._ml_filter_enabled = ml_filter_enabled
        self._ml_filter_mode = ml_filter_mode
        self._ml_manager = ml_manager

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

    # ------------------------------------------------------------------
    # Delegation: ML filter configuration
    # ------------------------------------------------------------------

    def configure_ml_filter(
        self,
        ml_signal_filter: Optional["MLSignalFilter"],
        *,
        enabled: bool = False,
        mode: str = "shadow",
    ) -> None:
        """
        Reconfigure the ML signal filter at runtime (e.g. after re-training).

        Updates both the orchestrator's reference and the underlying
        SignalHandler + OrderManager so all downstream consumers see the
        new filter.
        """
        self._ml_signal_filter = ml_signal_filter
        self._ml_filter_enabled = enabled
        self._ml_filter_mode = mode

        # Propagate to handler and order manager
        self._signal_handler.configure_ml_filter(ml_signal_filter, enabled=enabled, mode=mode)
        self._order_manager.configure_ml_sizing(ml_signal_filter)

        logger.info(
            "SignalOrchestrator: ML filter reconfigured",
            extra={"enabled": enabled, "mode": mode},
        )

    # ------------------------------------------------------------------
    # ML lift / training (migrated from service.py)
    # ------------------------------------------------------------------

    def refresh_ml_lift(self, *, force: bool = False) -> None:
        """Refresh ML lift metrics + blocking allowance (delegates to MLManager)."""
        if self._ml_manager is not None:
            self._ml_manager.refresh_lift(force=force)

    def compute_ml_lift_metrics(self, trades: list) -> Dict[str, Any]:
        """Compute shadow A/B lift for ML gating (delegates to MLManager)."""
        if self._ml_manager is None:
            return {}
        return self._ml_manager.compute_lift_metrics(trades)

    def build_ml_training_trades_from_signals(self, *, limit: int = 2000) -> List[dict]:
        """Build supervised training samples (delegates to MLManager)."""
        if self._ml_manager is None:
            return []
        return self._ml_manager.build_training_trades_from_signals(limit=limit)

    async def build_ml_training_trades_from_signals_async(self, *, limit: int = 2000) -> List[dict]:
        """Async wrapper (delegates to MLManager)."""
        if self._ml_manager is None:
            return []
        return await self._ml_manager.build_training_trades_from_signals_async(limit=limit)

    # ------------------------------------------------------------------
    # Contextual features (migrated from service.py)
    # ------------------------------------------------------------------

    def build_context_features(
        self,
        signal: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build contextual features for bandit policy from signal + market data.

        Extracts signal metadata (type, confidence, direction) and market
        context (regime, volume ratio, spread) into a flat dict suitable
        for contextual bandit policies.

        Returns:
            Dict of string feature-name → numeric/string feature-value.
        """
        features: Dict[str, Any] = {}
        try:
            features["signal_type"] = signal.get("type", "unknown")
            features["confidence"] = float(signal.get("confidence", 0.0))
            features["direction"] = signal.get("direction", "unknown")
            features["risk_reward"] = float(signal.get("risk_reward", 0.0))

            # Market context
            df = market_data.get("df")
            if df is not None and not df.empty:
                features["regime"] = signal.get("market_regime", "unknown")
                features["volume_ratio"] = float(signal.get("volume_ratio", 1.0))
        except Exception as exc:
            logger.debug("Error building context features: %s", exc)
        return features
