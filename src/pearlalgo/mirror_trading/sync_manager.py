"""
Mirror Trading Sync Manager.

Manages synchronization between internal simulation and external prop firm execution.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from pearlalgo.core.events import FillEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.mirror_trading.manual_fill_interface import ManualFillInterface

logger = logging.getLogger(__name__)


class MirrorTradingSyncManager:
    """
    Manages mirror trading workflow.

    Supports:
    - Internal signal generation
    - Internal simulation
    - Manual prop firm execution
    - PnL reconciliation
    - Position sync verification
    """

    def __init__(
        self,
        internal_portfolio: Portfolio,
        manual_fill_interface: Optional[ManualFillInterface] = None,
    ):
        """
        Initialize mirror trading sync manager.

        Args:
            internal_portfolio: Portfolio for internal simulation
            manual_fill_interface: Manual fill interface (created if None)
        """
        self.internal_portfolio = internal_portfolio
        self.manual_fill_interface = (
            manual_fill_interface or ManualFillInterface(internal_portfolio)
        )

        # Track simulated vs actual fills
        self.simulated_fills: list[FillEvent] = []
        self.actual_fills: list[FillEvent] = []

    def record_simulated_fill(self, fill: FillEvent) -> None:
        """
        Record a simulated fill from internal engine.

        Args:
            fill: Simulated FillEvent
        """
        self.simulated_fills.append(fill)
        logger.debug(f"Recorded simulated fill: {fill.symbol} @ {fill.price}")

    def record_actual_fill(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        timestamp: Optional[datetime] = None,
        commission: float = 0.0,
    ) -> FillEvent:
        """
        Record an actual fill from prop firm execution.

        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            quantity: Fill quantity
            price: Fill price
            timestamp: Fill timestamp
            commission: Commission

        Returns:
            Created FillEvent
        """
        fill = self.manual_fill_interface.enter_fill(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            timestamp=timestamp,
            commission=commission,
            override_simulated=True,
        )

        self.actual_fills.append(fill)
        return fill

    def reconcile_pnl(
        self,
        simulated_pnl: float,
        actual_pnl: float,
        tolerance: float = 0.01,  # 1% tolerance
    ) -> Dict[str, float]:
        """
        Reconcile PnL between simulated and actual.

        Args:
            simulated_pnl: PnL from internal simulation
            actual_pnl: PnL from prop firm
            tolerance: Acceptable difference (as decimal)

        Returns:
            Dict with reconciliation results
        """
        difference = actual_pnl - simulated_pnl
        difference_pct = (
            (difference / abs(simulated_pnl) * 100) if simulated_pnl != 0 else 0.0
        )

        is_within_tolerance = abs(difference_pct) <= (tolerance * 100)

        result = {
            "simulated_pnl": simulated_pnl,
            "actual_pnl": actual_pnl,
            "difference": difference,
            "difference_pct": difference_pct,
            "is_within_tolerance": is_within_tolerance,
        }

        if not is_within_tolerance:
            logger.warning(
                f"PnL reconciliation failed: difference {difference:.2f} "
                f"({difference_pct:.2f}%) exceeds tolerance"
            )
        else:
            logger.info(
                f"PnL reconciled: difference {difference:.2f} ({difference_pct:.2f}%)"
            )

        return result

    def sync_positions(
        self,
        internal_positions: Dict[str, float],
        external_positions: Dict[str, float],
    ) -> Dict[str, Dict[str, float]]:
        """
        Sync positions between internal and external.

        Args:
            internal_positions: Internal position dict (symbol -> quantity)
            external_positions: External position dict (symbol -> quantity)

        Returns:
            Dict with sync status per symbol
        """
        all_symbols = set(internal_positions.keys()) | set(external_positions.keys())
        sync_status = {}

        for symbol in all_symbols:
            internal_qty = internal_positions.get(symbol, 0.0)
            external_qty = external_positions.get(symbol, 0.0)
            difference = external_qty - internal_qty

            sync_status[symbol] = {
                "internal": internal_qty,
                "external": external_qty,
                "difference": difference,
                "is_synced": abs(difference) < 0.01,  # Allow small rounding differences
            }

            if not sync_status[symbol]["is_synced"]:
                logger.warning(
                    f"Position mismatch for {symbol}: internal={internal_qty}, "
                    f"external={external_qty}, diff={difference}"
                )

        return sync_status

    def generate_reconciliation_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        """
        Generate reconciliation report.

        Args:
            start_date: Report start date
            end_date: Report end date

        Returns:
            Dict with reconciliation report
        """
        # Filter fills by date range
        simulated = self.simulated_fills
        actual = self.actual_fills

        if start_date:
            simulated = [f for f in simulated if f.timestamp >= start_date]
            actual = [f for f in actual if f.timestamp >= start_date]

        if end_date:
            simulated = [f for f in simulated if f.timestamp <= end_date]
            actual = [f for f in actual if f.timestamp <= end_date]

        # Calculate PnL
        simulated_pnl = sum(
            (1.0 if f.side.upper() == "SELL" else -1.0) * f.quantity * f.price
            - f.commission
            for f in simulated
        )

        actual_pnl = sum(
            (1.0 if f.side.upper() == "SELL" else -1.0) * f.quantity * f.price
            - f.commission
            for f in actual
        )

        reconciliation = self.reconcile_pnl(simulated_pnl, actual_pnl)

        return {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "num_simulated_fills": len(simulated),
            "num_actual_fills": len(actual),
            "reconciliation": reconciliation,
        }





