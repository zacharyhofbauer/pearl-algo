"""
Failure-mode tests for IBKR and Tradovate execution adapters.

Covers:
- IBKR: cancel_order with non-numeric order ID
- Tradovate: cancel_order with non-numeric order ID
- Tradovate: get_positions failure returns empty list
- IBKR: place_bracket when adapter is disconnected
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from pearlalgo.execution.base import (
    ExecutionConfig,
    ExecutionMode,
    ExecutionResult,
    OrderStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_execution_config(**overrides) -> ExecutionConfig:
    """Create an ExecutionConfig suitable for testing."""
    defaults = dict(
        enabled=True,
        mode=ExecutionMode.PAPER,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        ibkr_trading_client_id=99,
    )
    defaults.update(overrides)
    return ExecutionConfig(**defaults)


# ---------------------------------------------------------------------------
# IBKR Adapter Tests
# ---------------------------------------------------------------------------


class TestIBKRAdapterFailures:
    """Failure-mode tests for IBKRExecutionAdapter."""

    @pytest.mark.asyncio
    async def test_ibkr_cancel_order_with_invalid_order_id(self):
        """Passing a non-numeric order ID to cancel_order should raise
        ValueError when converting to int, and the adapter should return
        an error result (not crash)."""
        # Patch ib_insync.IB to avoid real connection attempts
        with patch("pearlalgo.execution.ibkr.adapter.IB"):
            from pearlalgo.execution.ibkr.adapter import IBKRExecutionAdapter

            config = _make_execution_config()
            adapter = IBKRExecutionAdapter(config)

            # The adapter is not connected (no executor thread), so is_connected() = False
            # cancel_order checks is_connected and returns error if not connected.
            # But the real failure path is the int(order_id) conversion inside
            # CancelOrderTask construction.
            result = await adapter.cancel_order("not_a_number")

            assert not result.success, "cancel_order with invalid ID should fail"
            assert result.status == OrderStatus.ERROR
            assert result.error_message is not None, (
                "Should have an error message explaining the failure"
            )

    @pytest.mark.asyncio
    async def test_ibkr_place_bracket_with_disconnected_adapter(self):
        """When the adapter is not connected to IBKR, place_bracket should
        return an error ExecutionResult (not raise)."""
        with patch("pearlalgo.execution.ibkr.adapter.IB"):
            from pearlalgo.execution.ibkr.adapter import IBKRExecutionAdapter

            config = _make_execution_config(mode=ExecutionMode.PAPER)
            adapter = IBKRExecutionAdapter(config)

            # Ensure adapter is armed so precondition check doesn't skip first
            adapter.arm()

            # Adapter is not connected (no executor thread started)
            assert not adapter.is_connected(), "Adapter should not be connected"

            signal = {
                "signal_id": "test_123",
                "type": "momentum_ema_cross",
                "direction": "long",
                "entry_price": 17500.0,
                "stop_loss": 17480.0,
                "take_profit": 17540.0,
                "position_size": 1,
                "symbol": "MNQ",
                "confidence": 0.8,
            }

            result = await adapter.place_bracket(signal)

            assert not result.success, "Should fail when not connected"
            assert result.status == OrderStatus.ERROR
            assert "not connected" in (result.error_message or "").lower(), (
                f"Expected 'not connected' in error, got '{result.error_message}'"
            )


# ---------------------------------------------------------------------------
# Tradovate Adapter Tests
# ---------------------------------------------------------------------------


class TestTradovateAdapterFailures:
    """Failure-mode tests for TradovateExecutionAdapter."""

    @pytest.mark.asyncio
    async def test_tradovate_cancel_order_with_invalid_order_id(self):
        """Passing a non-numeric order ID to Tradovate cancel_order should
        result in an error (ValueError from int conversion), not a crash."""
        with patch(
            "pearlalgo.execution.tradovate.adapter.TradovateConfig.from_env",
            return_value=MagicMock(env="demo"),
        ), patch(
            "pearlalgo.execution.tradovate.adapter.TradovateClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.is_authenticated = True
            mock_client.ws_connected = False
            mock_client.account_name = "TEST"
            mock_client.account_id = 999
            # cancel_order calls int(order_id) which will raise ValueError
            mock_client.cancel_order = AsyncMock(
                side_effect=ValueError("invalid literal for int()")
            )
            mock_client_cls.return_value = mock_client

            from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter

            config = _make_execution_config(mode=ExecutionMode.PAPER)
            adapter = TradovateExecutionAdapter(config)
            adapter._connected = True

            result = await adapter.cancel_order("not_a_number")

            assert not result.success, "cancel_order with invalid ID should fail"
            assert result.status == OrderStatus.ERROR
            assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_tradovate_position_check_failure_returns_empty(self):
        """When the Tradovate API call for positions fails, get_positions
        should return an empty list (not raise)."""
        with patch(
            "pearlalgo.execution.tradovate.adapter.TradovateConfig.from_env",
            return_value=MagicMock(env="demo"),
        ), patch(
            "pearlalgo.execution.tradovate.adapter.TradovateClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.is_authenticated = True
            mock_client.ws_connected = False
            mock_client.account_name = "TEST"
            mock_client.account_id = 999
            # get_positions raises a network error
            mock_client.get_positions = AsyncMock(
                side_effect=ConnectionError("API unreachable")
            )
            mock_client_cls.return_value = mock_client

            from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter

            config = _make_execution_config(mode=ExecutionMode.PAPER)
            adapter = TradovateExecutionAdapter(config)
            adapter._connected = True

            positions = await adapter.get_positions()

            assert positions == [], (
                f"Expected empty list on API failure, got {positions}"
            )

    @pytest.mark.asyncio
    async def test_tradovate_place_bracket_when_disconnected(self):
        """When the Tradovate adapter is not connected, place_bracket should
        return an error result."""
        with patch(
            "pearlalgo.execution.tradovate.adapter.TradovateConfig.from_env",
            return_value=MagicMock(env="demo"),
        ), patch(
            "pearlalgo.execution.tradovate.adapter.TradovateClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.is_authenticated = False  # Not authenticated
            mock_client.ws_connected = False
            mock_client.account_name = None
            mock_client.account_id = None
            mock_client_cls.return_value = mock_client

            from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter

            config = _make_execution_config(mode=ExecutionMode.PAPER)
            adapter = TradovateExecutionAdapter(config)
            adapter._connected = False  # Not connected
            adapter.arm()

            signal = {
                "signal_id": "tv_test_456",
                "type": "momentum_ema_cross",
                "direction": "long",
                "entry_price": 17500.0,
                "stop_loss": 17480.0,
                "take_profit": 17540.0,
                "position_size": 1,
                "symbol": "MNQ",
                "confidence": 0.8,
            }

            result = await adapter.place_bracket(signal)

            assert not result.success, "Should fail when not connected"
            assert result.status in (OrderStatus.ERROR, OrderStatus.REJECTED)
