"""
Reconciliation Engine

Compares agent-tracked P&L against broker-reported P&L and flags drift.
Used by the audit system to detect discrepancies between virtual tracking
and actual broker account values.

- IBKR Virtual: returns N/A (no broker to reconcile against)
- Tradovate Paper: compares agent fills P&L vs Tradovate account summary
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger


@dataclass
class ReconciliationResult:
    """Result of a single reconciliation check."""

    account: str
    date: str
    agent_pnl: float
    broker_pnl: float
    drift: float
    drift_pct: float
    status: str  # "within_tolerance", "drift_detected", "not_applicable"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dict."""
        return {
            "account": self.account,
            "date": self.date,
            "agent_pnl": round(self.agent_pnl, 2),
            "broker_pnl": round(self.broker_pnl, 2),
            "drift": round(self.drift, 2),
            "drift_pct": round(self.drift_pct, 2),
            "status": self.status,
            "details": self.details,
        }


class ReconciliationEngine:
    """
    Compares agent-tracked P&L with broker-reported P&L.

    Args:
        state_dir: Path to agent state directory
        account: Account identifier (e.g., "ibkr_virtual", "tradovate_paper")
        drift_threshold: Absolute drift threshold in dollars (default $5)
        drift_pct_threshold: Percentage drift threshold (default 0.5%)
        timing_tolerance_seconds: Max time difference between agent and broker (default 5s)
    """

    def __init__(
        self,
        state_dir: Path,
        account: str = "unknown",
        *,
        drift_threshold: float = 5.0,
        drift_pct_threshold: float = 0.5,
        timing_tolerance_seconds: float = 5.0,
    ) -> None:
        self.state_dir = state_dir
        self.account = account
        self._drift_threshold = drift_threshold
        self._drift_pct_threshold = drift_pct_threshold
        self._timing_tolerance = timing_tolerance_seconds

    def reconcile(self, date: Optional[str] = None) -> ReconciliationResult:
        """
        Run reconciliation for a given date (default: today).

        Returns a ReconciliationResult with drift analysis.
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # IBKR Virtual: no broker to reconcile against
        if "ibkr" in self.account.lower() or "virtual" in self.account.lower():
            return ReconciliationResult(
                account=self.account,
                date=date,
                agent_pnl=0.0,
                broker_pnl=0.0,
                drift=0.0,
                drift_pct=0.0,
                status="not_applicable",
                details={"reason": "Virtual account - no broker to reconcile against"},
            )

        # Tradovate Paper: compare fills P&L vs account summary
        try:
            agent_pnl = self._get_agent_pnl(date)
            broker_pnl = self._get_broker_pnl(date)

            drift = agent_pnl - broker_pnl
            drift_pct = (abs(drift) / abs(broker_pnl) * 100) if broker_pnl != 0 else 0.0

            # Determine status
            if abs(drift) <= self._drift_threshold and drift_pct <= self._drift_pct_threshold:
                status = "within_tolerance"
            else:
                status = "drift_detected"

            return ReconciliationResult(
                account=self.account,
                date=date,
                agent_pnl=agent_pnl,
                broker_pnl=broker_pnl,
                drift=drift,
                drift_pct=drift_pct,
                status=status,
                details={
                    "drift_threshold": self._drift_threshold,
                    "drift_pct_threshold": self._drift_pct_threshold,
                },
            )
        except Exception as e:
            logger.warning(f"Reconciliation error: {e}")
            return ReconciliationResult(
                account=self.account,
                date=date,
                agent_pnl=0.0,
                broker_pnl=0.0,
                drift=0.0,
                drift_pct=0.0,
                status="error",
                details={"error": str(e)},
            )

    def _get_agent_pnl(self, date: str) -> float:
        """Get agent-tracked P&L from Tradovate fills for a given date."""
        fills_file = self.state_dir / "tradovate_fills.json"
        if not fills_file.exists():
            return 0.0

        try:
            fills = json.loads(fills_file.read_text(encoding="utf-8"))
            if not isinstance(fills, list):
                return 0.0

            # FIFO matching for the given date
            open_queue: List[tuple] = []
            total_pnl = 0.0
            point_value = 2.0  # MNQ micro

            for f in fills:
                action = str(f.get("action") or f.get("Action") or "").lower()
                price = float(f.get("price") or f.get("Price") or 0)
                qty = int(f.get("qty") or f.get("Qty") or 0)
                ts = str(f.get("timestamp") or f.get("Timestamp") or "")
                if not action or not price or not qty:
                    continue

                remaining = qty
                while remaining > 0 and open_queue:
                    oq_action, oq_price, oq_qty, oq_ts = open_queue[0]
                    if oq_action == action:
                        break
                    match_qty = min(remaining, oq_qty)
                    if oq_action == "buy":
                        pnl = (price - oq_price) * match_qty * point_value
                    else:
                        pnl = (oq_price - price) * match_qty * point_value
                    # Only count trades closed on the target date
                    if ts[:10] == date:
                        total_pnl += pnl
                    remaining -= match_qty
                    if oq_qty > match_qty:
                        open_queue[0] = (oq_action, oq_price, oq_qty - match_qty, oq_ts)
                    else:
                        open_queue.pop(0)

                if remaining > 0:
                    open_queue.append((action, price, remaining, ts))

            return round(total_pnl, 2)
        except Exception as e:
            logger.warning(f"Agent P&L calculation error: {e}")
            return 0.0

    def _get_broker_pnl(self, date: str) -> float:
        """Get broker-reported P&L from cached Tradovate account state."""
        state_file = self.state_dir / "state.json"
        if not state_file.exists():
            return 0.0

        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            tv_account = state.get("tradovate_account", {}) or {}
            realized_pnl = float(tv_account.get("realized_pnl", 0))
            return round(realized_pnl, 2)
        except Exception as e:
            logger.warning(f"Broker P&L read error: {e}")
            return 0.0
