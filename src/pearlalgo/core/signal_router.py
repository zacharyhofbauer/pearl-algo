"""
Signal Router - Route signals to appropriate handlers with unified deduplication.

Provides:
- Route futures vs options signals
- Unified risk evaluation before routing
- Signal deduplication
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.agents.langgraph_state import Signal, TradingState
# Signal deduplication will be implemented for options


class SignalRouter:
    """
    Routes signals to appropriate handlers based on asset type.

    Handles:
    - Options signals → Options execution engine
    - Signal deduplication
    """

    def __init__(
        self,
        deduplicator: Optional[object] = None,  # Will be replaced with options-specific deduplicator
    ):
        """
        Initialize signal router.

        Args:
            deduplicator: Signal deduplicator instance (optional, will be options-specific)
        """
        self.deduplicator = deduplicator

        logger.info("SignalRouter initialized")

    def is_options(self, symbol: str) -> bool:
        """
        Check if symbol is an options contract.

        Args:
            symbol: Trading symbol

        Returns:
            True if options, False otherwise
        """
        # Options contracts typically have format: SYMBOL YYMMDD C/P STRIKE
        # Or: SYMBOL_YYMMDD_C_STRIKE
        return (
            "_" in symbol
            or len(symbol) > 10
            or any(x in symbol for x in ["C", "P", "Call", "Put"])
        )

    def route_signal(self, signal: Signal) -> str:
        """
        Route a signal to appropriate handler.

        Args:
            signal: Signal to route

        Returns:
            Handler type: "futures" or "options"
        """
        if self.is_options(signal.symbol):
            return "options"
        else:
            # Default: assume equity/options
            return "options"

    def route_signals(
        self, state: TradingState
    ) -> Dict[str, Dict[str, Signal]]:
        """
        Route all signals in state to appropriate handlers.

        Args:
            state: TradingState with signals

        Returns:
            Dictionary: {"futures": {symbol: signal}, "options": {symbol: signal}}
        """
        routed = {"futures": {}, "options": {}}

        for symbol, signal in state.signals.items():
            # Check deduplication
            if not self.deduplicator.should_generate_signal(
                symbol, signal.side, signal.entry_price or 0.0
            ):
                logger.debug(
                    f"Signal for {symbol} deduplicated (recent duplicate)"
                )
                continue

            # Route signal
            handler_type = self.route_signal(signal)
            routed[handler_type][symbol] = signal

            # Record in deduplicator
            self.deduplicator.record_signal(
                symbol, signal.side, signal.entry_price or 0.0
            )

        logger.info(
            f"Routed {len(routed['futures'])} futures signals, "
            f"{len(routed['options'])} options signals"
        )

        return routed

    def filter_by_confidence(
        self, signals: Dict[str, Signal], min_confidence: float = 0.6
    ) -> Dict[str, Signal]:
        """
        Filter signals by minimum confidence threshold.

        Args:
            signals: Dictionary of symbol -> Signal
            min_confidence: Minimum confidence (0-1)

        Returns:
            Filtered signals
        """
        filtered = {
            symbol: signal
            for symbol, signal in signals.items()
            if signal.confidence >= min_confidence
        }

        logger.debug(
            f"Filtered signals: {len(signals)} -> {len(filtered)} "
            f"(min_confidence={min_confidence})"
        )

        return filtered
