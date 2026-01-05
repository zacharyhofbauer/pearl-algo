"""
Tradovate Execution Adapter (skeleton)

Implements the ExecutionAdapter interface with safety-first behavior:
- Fully supports DRY_RUN (logs + state counters)
- PAPER/LIVE return explicit "not implemented" errors until API wiring is added

This lets the rest of the system (ATS wiring, /arm, prop-firm guardrails) work end-to-end
without risking real orders.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List

from pearlalgo.execution.base import ExecutionAdapter, ExecutionConfig, ExecutionResult, OrderStatus, Position
from pearlalgo.utils.logger import logger


class TradovateExecutionAdapter(ExecutionAdapter):
    """Tradovate implementation placeholder for ExecutionAdapter."""

    def __init__(self, config: ExecutionConfig):
        super().__init__(config)
        self._connected = False
        logger.info(f"TradovateExecutionAdapter initialized (mode={config.mode.value})")

    async def connect(self) -> bool:
        # DRY_RUN: allow "connected" so status/UI flows are testable.
        if self.config.mode.value == "dry_run":
            self._connected = True
            return True

        logger.warning(
            "TradovateExecutionAdapter: PAPER/LIVE not implemented yet. "
            "Use execution.mode=dry_run or wire Tradovate API credentials + endpoints."
        )
        self._connected = False
        return False

    async def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return bool(self._connected)

    async def place_bracket(self, signal: Dict) -> ExecutionResult:
        signal_id = str(signal.get("signal_id") or str(uuid.uuid4()))

        # Preconditions (enabled/armed/limits/geometry)
        decision = self.check_preconditions(signal)
        if not decision.execute:
            return ExecutionResult(
                success=False,
                status=OrderStatus.REJECTED,
                signal_id=signal_id,
                error_message=decision.reason,
            )

        # DRY_RUN: simulate placement and update counters
        if self.config.mode.value == "dry_run":
            self._orders_today += 1
            signal_type = str(signal.get("type") or "unknown")
            self._last_order_time[signal_type] = datetime.now(timezone.utc)
            logger.info(f"TRADOVATE DRY_RUN: Would place bracket order for {signal_id}")
            return ExecutionResult(
                success=True,
                status=OrderStatus.PLACED,
                signal_id=signal_id,
                parent_order_id=f"tradovate_dry_run_{signal_id}",
            )

        # PAPER/LIVE not implemented yet
        return ExecutionResult(
            success=False,
            status=OrderStatus.ERROR,
            signal_id=signal_id,
            error_message="Tradovate execution not implemented (paper/live)",
        )

    async def cancel_order(self, order_id: str) -> ExecutionResult:
        if self.config.mode.value == "dry_run":
            return ExecutionResult(
                success=True,
                status=OrderStatus.CANCELLED,
                signal_id="",
                order_id=order_id,
            )
        return ExecutionResult(
            success=False,
            status=OrderStatus.ERROR,
            signal_id="",
            order_id=order_id,
            error_message="Tradovate cancel not implemented (paper/live)",
        )

    async def cancel_all(self) -> List[ExecutionResult]:
        # Disarm immediately for safety
        self.disarm()
        if self.config.mode.value == "dry_run":
            return [
                ExecutionResult(
                    success=True,
                    status=OrderStatus.CANCELLED,
                    signal_id="kill_switch",
                )
            ]
        return [
            ExecutionResult(
                success=False,
                status=OrderStatus.ERROR,
                signal_id="kill_switch",
                error_message="Tradovate kill switch not implemented (paper/live)",
            )
        ]

    async def get_positions(self) -> List[Position]:
        # DRY_RUN returns cached positions (normally empty)
        return list(self._positions.values())



