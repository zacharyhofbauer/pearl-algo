"""
Tests for the IBKR execution adapter (IBKRExecutionAdapter).

Covers:
- Order placement: bracket order success via task, invalid params, dry-run mode
- Position management: formatted data, cached fallback, empty positions
- Error handling: disconnect teardown, not-connected guard
- Fill / order tracking: counter increment, counter skip on failure

Uses unittest.mock to mock ib_insync classes — no real network calls.
"""

from __future__ import annotations

from concurrent.futures import Future as ConcurrentFuture
from unittest.mock import MagicMock, patch

import pytest

from pearlalgo.execution.base import (
    ExecutionConfig,
    ExecutionMode,
    OrderStatus,
    Position,
)
from pearlalgo.execution.ibkr.adapter import IBKRExecutionAdapter


# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_completed_future(result) -> ConcurrentFuture:
    """Create a ConcurrentFuture that is already resolved with *result*."""
    f: ConcurrentFuture = ConcurrentFuture()
    f.set_result(result)
    return f


def _make_ibkr_adapter(
    mode: str = "dry_run",
    armed: bool = False,
    **config_kw,
) -> IBKRExecutionAdapter:
    """Create an IBKRExecutionAdapter with test config (no real IB connection)."""
    exec_config = ExecutionConfig(
        enabled=True,
        armed=armed,
        mode=ExecutionMode(mode),
        symbol_whitelist=["MNQ"],
        **config_kw,
    )
    adapter = IBKRExecutionAdapter(exec_config)
    return adapter


def _arm_adapter(
    adapter: IBKRExecutionAdapter,
    connected: bool = True,
) -> IBKRExecutionAdapter:
    """Put adapter into connected+armed state with a mocked IB object."""
    adapter._connected = connected
    adapter._running = True
    mock_ib = MagicMock()
    mock_ib.isConnected.return_value = connected
    adapter._ib = mock_ib
    return adapter


# ═══════════════════════════════════════════════════════════════════════════
# Order placement
# ═══════════════════════════════════════════════════════════════════════════


class TestIBKRPlaceBracket:
    """Bracket order placement: success, validation, dry-run."""

    @pytest.mark.asyncio
    async def test_place_bracket_success_via_task(self):
        """Paper mode: place_bracket submits task and returns PLACED on success."""
        adapter = _make_ibkr_adapter(mode="paper", armed=True)
        _arm_adapter(adapter)

        adapter._submit_task = MagicMock(return_value=_make_completed_future({
            "success": True,
            "parent_order_id": "100",
            "stop_order_id": "101",
            "take_profit_order_id": "102",
        }))

        signal = {
            "signal_id": "sig1",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 1,
        }

        result = await adapter.place_bracket(signal)

        assert result.success is True
        assert result.status == OrderStatus.PLACED
        assert result.parent_order_id == "100"
        assert result.stop_order_id == "101"
        assert result.take_profit_order_id == "102"
        adapter._submit_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_place_bracket_invalid_prices_rejected(self):
        """Signal with zero prices is rejected before reaching the broker."""
        adapter = _make_ibkr_adapter(mode="paper", armed=True)
        _arm_adapter(adapter)

        signal = {
            "signal_id": "sig2",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 0,
            "stop_loss": 0,
            "take_profit": 0,
            "position_size": 1,
        }

        result = await adapter.place_bracket(signal)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_place_bracket_dry_run_does_not_submit_task(self):
        """Dry-run mode returns success without submitting a real task."""
        adapter = _make_ibkr_adapter(mode="dry_run", armed=True)

        signal = {
            "signal_id": "sig3",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 1,
        }

        result = await adapter.place_bracket(signal)

        assert result.success is True
        assert result.status == OrderStatus.PLACED
        assert result.order_id.startswith("dry_run_")


# ═══════════════════════════════════════════════════════════════════════════
# Position management
# ═══════════════════════════════════════════════════════════════════════════


class TestIBKRPositions:
    """Position queries: formatted output, empty results, cached fallback."""

    @pytest.mark.asyncio
    async def test_get_positions_returns_formatted_data(self):
        """Paper mode: get_positions returns Position objects from task result."""
        adapter = _make_ibkr_adapter(mode="paper")
        _arm_adapter(adapter)

        adapter._submit_task = MagicMock(return_value=_make_completed_future({
            "success": True,
            "positions": [
                {"symbol": "MNQ", "quantity": 2, "avg_price": 18000.0},
                {"symbol": "NQ", "quantity": -1, "avg_price": 17500.0},
            ],
        }))

        positions = await adapter.get_positions()

        assert len(positions) == 2
        assert positions[0].symbol == "MNQ"
        assert positions[0].quantity == 2
        assert positions[0].avg_price == 18000.0
        assert positions[1].symbol == "NQ"
        assert positions[1].quantity == -1

    @pytest.mark.asyncio
    async def test_get_positions_not_connected_returns_cached(self):
        """When disconnected, returns previously cached positions."""
        adapter = _make_ibkr_adapter(mode="paper")
        adapter._connected = False
        adapter._ib = None

        # Pre-populate cache
        adapter._positions["MNQ"] = Position(
            symbol="MNQ", quantity=1, avg_price=18000.0,
        )

        positions = await adapter.get_positions()

        assert len(positions) == 1
        assert positions[0].symbol == "MNQ"
        assert positions[0].quantity == 1

    @pytest.mark.asyncio
    async def test_get_positions_empty_returns_empty_list(self):
        """No positions on the broker returns an empty list."""
        adapter = _make_ibkr_adapter(mode="paper")
        _arm_adapter(adapter)

        adapter._submit_task = MagicMock(return_value=_make_completed_future({
            "success": True,
            "positions": [],
        }))

        positions = await adapter.get_positions()

        assert positions == []


# ═══════════════════════════════════════════════════════════════════════════
# Error handling
# ═══════════════════════════════════════════════════════════════════════════


class TestIBKRErrorHandling:
    """Disconnect, connection state, error propagation."""

    @pytest.mark.asyncio
    async def test_disconnect_sets_not_connected(self):
        """After disconnect, adapter reports not running and not connected."""
        adapter = _make_ibkr_adapter(mode="paper")
        adapter._running = True
        adapter._connected = True

        # Mock the executor thread so join works immediately
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        adapter._executor_thread = mock_thread

        await adapter.disconnect()

        assert adapter._running is False
        assert adapter._connected is False

    @pytest.mark.asyncio
    async def test_place_bracket_not_connected_returns_error(self):
        """When not connected, place_bracket returns ERROR with message."""
        adapter = _make_ibkr_adapter(mode="paper", armed=True)
        adapter._connected = False
        adapter._ib = None

        signal = {
            "signal_id": "sig4",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 1,
        }

        result = await adapter.place_bracket(signal)

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "Not connected" in result.error_message


# ═══════════════════════════════════════════════════════════════════════════
# Fill / order tracking
# ═══════════════════════════════════════════════════════════════════════════


class TestIBKRFillTracking:
    """Order count tracking and cancel operations."""

    @pytest.mark.asyncio
    async def test_successful_order_increments_daily_count(self):
        """After a successful bracket order, _orders_today is incremented."""
        adapter = _make_ibkr_adapter(mode="paper", armed=True)
        _arm_adapter(adapter)

        adapter._submit_task = MagicMock(return_value=_make_completed_future({
            "success": True,
            "parent_order_id": "100",
            "stop_order_id": "101",
            "take_profit_order_id": "102",
        }))

        assert adapter._orders_today == 0

        signal = {
            "signal_id": "sig5",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 1,
        }

        await adapter.place_bracket(signal)

        assert adapter._orders_today == 1

    @pytest.mark.asyncio
    async def test_failed_task_does_not_increment_daily_count(self):
        """When the task returns success=False, _orders_today stays at zero."""
        adapter = _make_ibkr_adapter(mode="paper", armed=True)
        _arm_adapter(adapter)

        adapter._submit_task = MagicMock(return_value=_make_completed_future({
            "success": False,
            "error": "Contract not found for MNQ",
        }))

        assert adapter._orders_today == 0

        signal = {
            "signal_id": "sig6",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 1,
        }

        result = await adapter.place_bracket(signal)

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "Contract not found" in result.error_message
        assert adapter._orders_today == 0
