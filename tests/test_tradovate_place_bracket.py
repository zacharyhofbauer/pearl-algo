"""
Tests for Tradovate adapter place_bracket method.

Covers:
- Valid long/short bracket placement
- Broker position guard: opposite direction blocked
- Broker position guard: max positions blocked
- Same direction with room: allowed
- Missing TP/SL handled gracefully
- Zero position_size rejected
- Tradovate error response handled
- Connection failure handled
- Structured logging output
"""

from __future__ import annotations

import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter
from pearlalgo.execution.tradovate.config import TradovateConfig
from pearlalgo.execution.tradovate.client import TradovateAPIError
from pearlalgo.execution.base import (
    ExecutionConfig,
    ExecutionMode,
    OrderStatus,
)


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_tradovate_adapter.py)
# ---------------------------------------------------------------------------

def _make_mock_client():
    """Create a fully-mocked TradovateClient with sensible defaults."""
    client = MagicMock()
    client.is_authenticated = True
    client.account_name = "DEMO0001"
    client.account_id = 12345
    client.ws_connected = True

    client.connect = AsyncMock(return_value=True)
    client.disconnect = AsyncMock()
    client.resolve_front_month = AsyncMock(return_value="MNQZ5")
    client.find_contract = AsyncMock(return_value={"id": 999, "name": "MNQZ5"})
    client.start_websocket = AsyncMock()
    client.add_event_handler = MagicMock()
    client.place_oso = AsyncMock(return_value={"orderId": 42})
    client.cancel_order = AsyncMock(return_value={"orderId": 42})
    client.get_positions = AsyncMock(return_value=[])
    client.get_orders = AsyncMock(return_value=[])
    client.liquidate_all_positions = AsyncMock(return_value={"positions_liquidated": 0})
    client.get_fills = AsyncMock(return_value=[])
    client.get_cash_balance_snapshot = AsyncMock(return_value={
        "netLiq": 50000.0,
        "totalCashValue": 50000.0,
    })
    return client


def _make_adapter(mode: str = "paper", armed: bool = True, **config_kw) -> TradovateExecutionAdapter:
    """Create a TradovateExecutionAdapter with mocked client, pre-connected."""
    exec_config = ExecutionConfig(
        enabled=True,
        armed=armed,
        mode=ExecutionMode(mode),
        symbol_whitelist=["MNQ"],
        **config_kw,
    )
    tv_config = TradovateConfig(
        username="test", password="test", cid=1, sec="sec", env="demo",
    )
    adapter = TradovateExecutionAdapter(exec_config, tv_config)
    adapter._client = _make_mock_client()
    adapter._connected = True
    adapter._contract_symbol = "MNQZ5"
    adapter._contract_id = 999
    return adapter


def _long_signal(**overrides) -> dict:
    """Create a valid long signal dict."""
    sig = {
        "signal_id": "test_long_1",
        "symbol": "MNQ",
        "direction": "long",
        "entry_price": 18000.0,
        "stop_loss": 17990.0,
        "take_profit": 18020.0,
        "position_size": 1,
    }
    sig.update(overrides)
    return sig


def _short_signal(**overrides) -> dict:
    """Create a valid short signal dict."""
    sig = {
        "signal_id": "test_short_1",
        "symbol": "MNQ",
        "direction": "short",
        "entry_price": 18000.0,
        "stop_loss": 18020.0,
        "take_profit": 17980.0,
        "position_size": 1,
    }
    sig.update(overrides)
    return sig


# ===========================================================================
# Valid long/short bracket placement
# ===========================================================================


class TestPlaceBracketValidOrders:
    """place_bracket succeeds for valid long and short signals."""

    @pytest.mark.asyncio
    async def test_valid_long_bracket_placed(self):
        adapter = _make_adapter()
        result = await adapter.place_bracket(_long_signal())

        assert result.success is True
        assert result.status == OrderStatus.PLACED
        assert result.order_id == "42"

        # Verify the client was called with Buy action
        adapter._client.place_oso.assert_awaited_once()
        call_kw = adapter._client.place_oso.call_args.kwargs
        assert call_kw["action"] == "Buy"
        assert call_kw["order_qty"] == 1
        assert call_kw["tp_price"] == 18020.0
        assert call_kw["sl_price"] == 17990.0

    @pytest.mark.asyncio
    async def test_valid_short_bracket_placed(self):
        adapter = _make_adapter()
        result = await adapter.place_bracket(_short_signal())

        assert result.success is True
        assert result.status == OrderStatus.PLACED

        call_kw = adapter._client.place_oso.call_args.kwargs
        assert call_kw["action"] == "Sell"
        assert call_kw["order_qty"] == 1
        assert call_kw["tp_price"] == 17980.0
        assert call_kw["sl_price"] == 18020.0

    @pytest.mark.asyncio
    async def test_order_tracked_in_open_orders(self):
        adapter = _make_adapter()
        await adapter.place_bracket(_long_signal(signal_id="track_me"))

        assert "42" in adapter._open_orders
        tracked = adapter._open_orders["42"]
        assert tracked["signal_id"] == "track_me"
        assert tracked["direction"] == "long"
        assert tracked["qty"] == 1


# ===========================================================================
# Broker position guard: opposite direction blocked
# ===========================================================================


class TestBrokerPositionGuardOpposite:
    """Opposite-direction orders are blocked when a position exists."""

    @pytest.mark.asyncio
    async def test_long_blocked_when_short_position_exists(self):
        adapter = _make_adapter()
        # Simulate existing short position from WS cache
        adapter._live_positions["999"] = {
            "contract_id": "999",
            "net_pos": -1,
            "net_price": 18050.0,
        }

        result = await adapter.place_bracket(_long_signal())

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "opposite_direction_blocked" in result.error_message

    @pytest.mark.asyncio
    async def test_short_blocked_when_long_position_exists(self):
        adapter = _make_adapter()
        adapter._live_positions["999"] = {
            "contract_id": "999",
            "net_pos": 2,
            "net_price": 17900.0,
        }

        result = await adapter.place_bracket(_short_signal())

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "opposite_direction_blocked" in result.error_message


# ===========================================================================
# Broker position guard: max positions blocked
# ===========================================================================


class TestBrokerPositionGuardMax:
    """Orders blocked when max broker positions are already filled."""

    @pytest.mark.asyncio
    async def test_max_positions_reached_same_direction(self):
        adapter = _make_adapter()
        # Default max_net_positions = 1; already have 1 long position
        adapter._live_positions["999"] = {
            "contract_id": "999",
            "net_pos": 1,
            "net_price": 18000.0,
        }

        result = await adapter.place_bracket(_long_signal())

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "max_broker_positions" in result.error_message

    @pytest.mark.asyncio
    async def test_same_direction_with_room_allowed(self):
        """When max_net_positions > 1 and room exists, order goes through."""
        adapter = _make_adapter()
        # Override max_net_positions to 3
        adapter.config.max_net_positions = 3

        # One existing long position — room for 2 more
        adapter._live_positions["999"] = {
            "contract_id": "999",
            "net_pos": 1,
            "net_price": 18000.0,
        }

        result = await adapter.place_bracket(_long_signal())

        # Should be allowed (opposite-direction check: long vs long is fine,
        # max check: 1 < 3, so it passes)
        assert result.success is True
        assert result.status == OrderStatus.PLACED

    @pytest.mark.asyncio
    async def test_position_guard_falls_back_to_rest(self):
        """When _live_positions is empty, REST get_positions is used."""
        adapter = _make_adapter()
        adapter._live_positions = {}  # Empty WS cache
        adapter._client.get_positions = AsyncMock(return_value=[
            {"netPos": -2, "contractId": 999}
        ])

        result = await adapter.place_bracket(_long_signal())

        # Should detect short position from REST, block long
        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "opposite_direction_blocked" in result.error_message


# ===========================================================================
# Missing TP/SL handled gracefully
# ===========================================================================


class TestMissingTPSL:
    """Zero TP/SL are rejected at the precondition level (non-positive prices)."""

    @pytest.mark.asyncio
    async def test_zero_tp_and_sl_rejected_by_preconditions(self):
        """check_preconditions rejects zero stop_loss and take_profit."""
        adapter = _make_adapter()
        signal = _long_signal(take_profit=0, stop_loss=0)

        result = await adapter.place_bracket(signal)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        # The precondition check rejects non-positive prices
        assert "non_positive" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_zero_sl_rejected_by_preconditions(self):
        """check_preconditions rejects zero stop_loss even with valid TP."""
        adapter = _make_adapter()
        signal = _long_signal(stop_loss=0, take_profit=18020.0)

        result = await adapter.place_bracket(signal)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_valid_tp_sl_passes_to_client(self):
        """Verify valid non-zero TP/SL values are forwarded to place_oso."""
        adapter = _make_adapter()
        signal = _long_signal(stop_loss=17990.0, take_profit=18020.0)

        result = await adapter.place_bracket(signal)

        assert result.success is True
        call_kw = adapter._client.place_oso.call_args.kwargs
        assert call_kw["tp_price"] == 18020.0
        assert call_kw["sl_price"] == 17990.0


# ===========================================================================
# Zero position_size rejected
# ===========================================================================


class TestZeroPositionSize:
    """Zero or negative position_size is rejected."""

    @pytest.mark.asyncio
    async def test_zero_position_size_rejected(self):
        adapter = _make_adapter()
        signal = _long_signal(position_size=0)

        result = await adapter.place_bracket(signal)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "position_size" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_negative_position_size_rejected(self):
        adapter = _make_adapter()
        signal = _long_signal(position_size=-1)

        result = await adapter.place_bracket(signal)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED


# ===========================================================================
# Tradovate error response handled
# ===========================================================================


class TestTradovateErrorResponse:
    """Tradovate API errors and rejection responses are handled."""

    @pytest.mark.asyncio
    async def test_api_error_returns_error_status(self):
        adapter = _make_adapter()
        adapter._client.place_oso = AsyncMock(
            side_effect=TradovateAPIError("Insufficient margin")
        )

        result = await adapter.place_bracket(_long_signal())

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "Insufficient margin" in result.error_message

    @pytest.mark.asyncio
    async def test_rejected_response_no_order_id(self):
        """Tradovate returns a dict without orderId (rejected by exchange)."""
        adapter = _make_adapter()
        adapter._client.place_oso = AsyncMock(return_value={
            "errorText": "Order rejected: outside trading hours",
        })

        result = await adapter.place_bracket(_long_signal())

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "outside trading hours" in result.error_message

    @pytest.mark.asyncio
    async def test_unexpected_response_type_handled(self):
        """place_oso returns non-dict (e.g. None or string)."""
        adapter = _make_adapter()
        adapter._client.place_oso = AsyncMock(return_value=None)

        result = await adapter.place_bracket(_long_signal())

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "response type" in result.error_message.lower()


# ===========================================================================
# Connection failure handled
# ===========================================================================


class TestConnectionFailure:
    """Orders fail cleanly when not connected."""

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self):
        adapter = _make_adapter()
        adapter._connected = False
        adapter._client.is_authenticated = False

        result = await adapter.place_bracket(_long_signal())

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "Not connected" in result.error_message

    @pytest.mark.asyncio
    async def test_general_exception_returns_error(self):
        """Unexpected exception during order placement is caught."""
        adapter = _make_adapter()
        adapter._client.place_oso = AsyncMock(
            side_effect=RuntimeError("socket closed")
        )

        result = await adapter.place_bracket(_long_signal())

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "socket closed" in result.error_message


# ===========================================================================
# Structured logging output
# ===========================================================================


class TestStructuredLogging:
    """Verify that structured log messages are emitted during placement."""

    @pytest.mark.asyncio
    async def test_place_oso_request_logged(self, caplog):
        adapter = _make_adapter()

        with caplog.at_level(logging.INFO):
            await adapter.place_bracket(_long_signal(signal_id="log_test"))

        # Should log the structured request line
        log_text = caplog.text
        assert "place_oso request" in log_text or "bracket placed" in log_text

    @pytest.mark.asyncio
    async def test_rejection_logged(self, caplog):
        adapter = _make_adapter()
        adapter._live_positions["999"] = {
            "contract_id": "999",
            "net_pos": -1,
            "net_price": 18050.0,
        }

        with caplog.at_level(logging.INFO):
            await adapter.place_bracket(_long_signal(signal_id="reject_log"))

        assert "position guard" in caplog.text.lower() or "opposite" in caplog.text.lower()
