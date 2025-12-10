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
from pearlalgo.futures.signal_deduplicator import SignalDeduplicator


class SignalRouter:
    """
    Routes signals to appropriate handlers based on asset type.

    Handles:
    - Futures signals → Futures execution engine
    - Options signals → Options execution engine
    - Unified deduplication
    """

    # Futures symbols (common)
    FUTURES_SYMBOLS = ["ES", "NQ", "MES", "MNQ", "CL", "GC", "ZN", "ZB"]

    def __init__(
        self,
        deduplicator: Optional[SignalDeduplicator] = None,
        futures_symbols: Optional[List[str]] = None,
    ):
        """
        Initialize signal router.

        Args:
            deduplicator: SignalDeduplicator instance (optional)
            futures_symbols: List of futures symbols (default: common futures)
        """
        self.deduplicator = deduplicator or SignalDeduplicator()
        self.futures_symbols = futures_symbols or self.FUTURES_SYMBOLS

        logger.info("SignalRouter initialized")

    def is_futures(self, symbol: str) -> bool:
        """
        Check if symbol is a futures contract.

        Args:
            symbol: Trading symbol

        Returns:
            True if futures, False if options/equity
        """
        # Simple check: futures symbols are typically short (2-4 chars)
        # and match known futures list
        return symbol in self.futures_symbols or len(symbol) <= 4

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
        if self.is_futures(signal.symbol):
            return "futures"
        elif self.is_options(signal.symbol):
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
