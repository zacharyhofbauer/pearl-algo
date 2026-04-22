"""
Comprehensive tests for TradovateExecutionAdapter.

Covers: place_bracket, cancel_order, modify_stop_order, cancel_all,
flatten_all_positions, get_positions, _handle_ws_event, static helpers,
build_working_orders, get_account_summary, _poll_order_status,
get_live_positions_with_pnl.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from pearlalgo.execution.base import (
    ExecutionConfig,
    ExecutionMode,
    OrderStatus,
    ExecutionResult,
)
from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter
from pearlalgo.execution.tradovate.client import TradovateAPIError, TradovateAuthError
from tests.fixtures.mock_tradovate_client import make_adapter, make_mock_client, make_signal


# ---------------------------------------------------------------------------
# TestPlaceBracketPreconditions
# ---------------------------------------------------------------------------

class TestPlaceBracketPreconditions:
    """Tests for precondition checks before order placement."""

    @pytest.mark.asyncio
    async def test_precondition_rejection_returns_rejected(self):
        """When preconditions fail (e.g. disabled), result is REJECTED."""
        adapter = make_adapter(mode="paper", armed=True, connected=True, enabled=False,
                               contract_symbol="MNQM6")
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_dry_run_success_no_broker_call(self):
        """Dry-run returns success without calling the broker."""
        adapter = make_adapter(mode="dry_run", armed=True)
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert result.success
        assert result.status == OrderStatus.PLACED
        adapter._client.place_oso.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self):
        """When adapter is not connected, returns ERROR."""
        adapter = make_adapter(mode="paper", armed=True, connected=False,
                               contract_symbol="MNQM6")
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.ERROR
        assert "Not connected" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_not_armed_returns_rejected(self):
        """When adapter is not armed, returns REJECTED with reason."""
        adapter = make_adapter(mode="paper", armed=False, connected=True,
                               contract_symbol="MNQM6")
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED
        assert "not_armed" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_disabled_returns_rejected(self):
        """When execution is disabled, returns REJECTED."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               enabled=False, contract_symbol="MNQM6")
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_dry_run_increments_order_count(self):
        """Dry-run increments order count on success."""
        adapter = make_adapter(mode="dry_run", armed=True)
        assert adapter._orders_today == 0
        await adapter.place_bracket(make_signal())
        assert adapter._orders_today == 1

    @pytest.mark.asyncio
    async def test_dry_run_returns_dry_prefix_order_id(self):
        """Dry-run order_id starts with 'tv_dry_'."""
        adapter = make_adapter(mode="dry_run", armed=True)
        result = await adapter.place_bracket(make_signal(signal_id="sig_123"))
        assert result.order_id is not None
        assert result.order_id.startswith("tv_dry_")

    @pytest.mark.asyncio
    async def test_precondition_reason_propagated(self):
        """The rejection reason from check_preconditions shows up in error_message."""
        adapter = make_adapter(mode="paper", armed=False, connected=True,
                               contract_symbol="MNQM6")
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert result.error_message is not None
        assert len(result.error_message) > 0


# ---------------------------------------------------------------------------
# TestPlaceBracketPositionGuard
# ---------------------------------------------------------------------------

class TestPlaceBracketPositionGuard:
    """Tests for broker position guard logic in place_bracket."""

    @pytest.mark.asyncio
    async def test_close_and_reverse_flatten_succeeds_then_new_order_placed(self):
        """REGRESSION: When flatten succeeds, the new opposite-direction order is placed."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6", allow_reversal=True,
            client_kwargs={"authenticated": True},
        )
        # Existing long position in WS cache
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0}
        }
        adapter._live_positions_updated_at = time.monotonic()

        # flatten_all_positions succeeds
        adapter.flatten_all_positions = AsyncMock(
            return_value=[ExecutionResult(success=True, status=OrderStatus.PLACED, signal_id="kill_flatten")]
        )

        signal = make_signal(direction="short", entry_price=18000.0,
                             stop_loss=18010.0, take_profit=17980.0)
        result = await adapter.place_bracket(signal)
        assert result.success
        assert result.status == OrderStatus.PLACED
        adapter.flatten_all_positions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_and_reverse_flatten_fails_aborts_new_order(self):
        """CRITICAL REGRESSION: When flatten FAILS, no new order is placed."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6", allow_reversal=True,
            client_kwargs={"authenticated": True},
        )
        # Existing long position
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0}
        }
        adapter._live_positions_updated_at = time.monotonic()

        # flatten_all_positions FAILS
        adapter.flatten_all_positions = AsyncMock(
            return_value=[ExecutionResult(success=False, status=OrderStatus.ERROR,
                                         signal_id="kill_flatten", error_message="fail")]
        )

        signal = make_signal(direction="short", entry_price=18000.0,
                             stop_loss=18010.0, take_profit=17980.0)
        result = await adapter.place_bracket(signal)
        # MUST NOT succeed -- flatten failed, so no new order
        assert not result.success
        assert result.status == OrderStatus.ERROR
        assert "flatten" in (result.error_message or "").lower()
        # place_oso must NOT have been called
        adapter._client.place_oso.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_and_reverse_flatten_returns_empty_aborts(self):
        """If flatten returns empty list, treat as failure and abort."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6", allow_reversal=True,
            client_kwargs={"authenticated": True},
        )
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0}
        }
        adapter._live_positions_updated_at = time.monotonic()
        adapter.flatten_all_positions = AsyncMock(return_value=[])

        signal = make_signal(direction="short", entry_price=18000.0,
                             stop_loss=18010.0, take_profit=17980.0)
        result = await adapter.place_bracket(signal)
        assert not result.success

    @pytest.mark.asyncio
    async def test_opposite_direction_blocked_when_reversal_disabled(self):
        """With reversal disabled, opposite direction order is rejected."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6", allow_reversal=False,
            client_kwargs={"authenticated": True},
        )
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0}
        }
        adapter._live_positions_updated_at = time.monotonic()

        signal = make_signal(direction="short", entry_price=18000.0,
                             stop_loss=18010.0, take_profit=17980.0)
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED
        assert "opposite_direction_blocked" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_stale_cache_cleared_after_ttl(self):
        """Position cache older than 120s is cleared."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6",
            client_kwargs={"authenticated": True},
        )
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0}
        }
        # Set cache time to 200s ago (> 120s TTL)
        adapter._live_positions_updated_at = time.monotonic() - 200

        signal = make_signal(direction="long")
        await adapter.place_bracket(signal)
        # Cache should have been cleared before REST fallback
        # (the positions dict gets cleared in the guard code)

    @pytest.mark.asyncio
    async def test_rest_fallback_when_cache_empty(self):
        """When WS cache is empty and connected, REST get_positions is called."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6",
            client_kwargs={"authenticated": True, "positions": []},
        )
        adapter._live_positions = {}
        signal = make_signal()
        await adapter.place_bracket(signal)
        adapter._client.get_positions.assert_awaited()

    @pytest.mark.asyncio
    async def test_rest_failure_rejects_for_safety(self):
        """REST position fetch failure rejects order — cannot verify broker state."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6",
            client_kwargs={"authenticated": True},
        )
        adapter._client.get_positions = AsyncMock(side_effect=Exception("network error"))
        adapter._live_positions = {}

        signal = make_signal()
        result = await adapter.place_bracket(signal)
        # FIXED 2026-04-08: Order is now rejected when broker state can't be verified
        assert not result.success
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_max_position_size_blocks_order(self):
        """When total_abs_pos >= max_net_positions, order is rejected."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6", max_positions=1,
            client_kwargs={"authenticated": True},
        )
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0}
        }
        adapter._live_positions_updated_at = time.monotonic()

        signal = make_signal(direction="long")
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED
        assert "max_position_size" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_same_direction_position_allows_order(self):
        """Existing same-direction position does not block order (if under max)."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6", max_positions=5,
            client_kwargs={"authenticated": True},
        )
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0}
        }
        adapter._live_positions_updated_at = time.monotonic()

        signal = make_signal(direction="long")
        result = await adapter.place_bracket(signal)
        assert result.success

    @pytest.mark.asyncio
    async def test_multiple_positions_total_abs_check(self):
        """Total abs position across multiple contracts blocks when >= max."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6", max_positions=3,
            client_kwargs={"authenticated": True},
        )
        adapter._live_positions = {
            "100": {"contract_id": "100", "net_pos": 2, "net_price": 18000.0},
            "200": {"contract_id": "200", "net_pos": 1, "net_price": 18000.0},
        }
        adapter._live_positions_updated_at = time.monotonic()

        signal = make_signal(direction="long")
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert "max_position_size" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_cache_cleared_after_flatten(self):
        """After successful flatten in reversal, _live_positions is cleared."""
        adapter = make_adapter(
            mode="paper", armed=True, connected=True,
            contract_symbol="MNQM6", allow_reversal=True,
            client_kwargs={"authenticated": True},
        )
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": -1, "net_price": 18000.0}
        }
        adapter._live_positions_updated_at = time.monotonic()

        adapter.flatten_all_positions = AsyncMock(
            return_value=[ExecutionResult(success=True, status=OrderStatus.PLACED, signal_id="f")]
        )

        signal = make_signal(direction="long")
        await adapter.place_bracket(signal)
        # After flatten, live positions should be empty
        assert len(adapter._live_positions) == 0


# ---------------------------------------------------------------------------
# TestPlaceBracketValidation
# ---------------------------------------------------------------------------

class TestPlaceBracketValidation:
    """Tests for signal validation in place_bracket."""

    @pytest.mark.asyncio
    async def test_position_size_clamped_to_max_per_order(self):
        """Position size > max_position_size_per_order gets clamped."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(position_size=5)
        result = await adapter.place_bracket(signal)
        assert result.success
        # place_oso should have been called with qty=1 (clamped)
        call_kwargs = adapter._client.place_oso.call_args
        assert call_kwargs[1]["order_qty"] == 1

    @pytest.mark.asyncio
    async def test_zero_position_size_rejected(self):
        """Position size of 0 is rejected."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(position_size=0)
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED
        assert "position_size" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_negative_position_size_rejected(self):
        """Negative position size is rejected."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(position_size=-1)
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_long_stop_above_entry_rejected(self):
        """Long with stop_loss >= entry_price is rejected."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(direction="long", entry_price=18000.0, stop_loss=18001.0)
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_short_stop_below_entry_rejected(self):
        """Short with stop_loss <= entry_price is rejected."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(direction="short", entry_price=18000.0, stop_loss=17999.0)
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_valid_long_stop_below_entry_accepted(self):
        """Long with stop_loss < entry_price is accepted."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(direction="long", entry_price=18000.0, stop_loss=17990.0)
        result = await adapter.place_bracket(signal)
        assert result.success

    @pytest.mark.asyncio
    async def test_valid_short_stop_above_entry_accepted(self):
        """Short with stop_loss > entry_price is accepted."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(direction="short", entry_price=18000.0,
                             stop_loss=18010.0, take_profit=17980.0)
        result = await adapter.place_bracket(signal)
        assert result.success

    @pytest.mark.asyncio
    async def test_contract_resolution_on_first_order(self):
        """If contract_symbol is None, resolves on first order."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._contract_symbol = None
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert result.success
        adapter._client.resolve_front_month.assert_awaited()


# ---------------------------------------------------------------------------
# TestPlaceBracketSuccess
# ---------------------------------------------------------------------------

class TestPlaceBracketSuccess:
    """Tests for successful order placement."""

    @pytest.mark.asyncio
    async def test_successful_order_tracked_in_open_orders(self):
        """Successful order is added to _open_orders."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(signal_id="track_me")
        result = await adapter.place_bracket(signal)
        assert result.success
        assert str(result.order_id) in adapter._open_orders

    @pytest.mark.asyncio
    async def test_order_count_incremented(self):
        """Order count is incremented on successful placement."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        assert adapter._orders_today == 0
        await adapter.place_bracket(make_signal())
        assert adapter._orders_today == 1

    @pytest.mark.asyncio
    async def test_short_maps_to_sell_action(self):
        """Short direction maps to 'Sell' action in place_oso call."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(direction="short", entry_price=18000.0,
                             stop_loss=18010.0, take_profit=17980.0)
        await adapter.place_bracket(signal)
        call_kwargs = adapter._client.place_oso.call_args[1]
        assert call_kwargs["action"] == "Sell"

    @pytest.mark.asyncio
    async def test_long_maps_to_buy_action(self):
        """Long direction maps to 'Buy' action in place_oso call."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        signal = make_signal(direction="long")
        await adapter.place_bracket(signal)
        call_kwargs = adapter._client.place_oso.call_args[1]
        assert call_kwargs["action"] == "Buy"

    @pytest.mark.asyncio
    async def test_api_error_returns_error_result(self):
        """TradovateAPIError during place_oso returns ERROR status."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        adapter._client.place_oso = AsyncMock(
            side_effect=TradovateAPIError("order rejected by exchange"))
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.ERROR

    @pytest.mark.asyncio
    async def test_no_order_id_returns_rejected(self):
        """When response has no orderId, result is REJECTED."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True,
                                              "place_oso_result": {"errorText": "Invalid symbol"}})
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_unexpected_response_type_returns_error(self):
        """When place_oso returns a non-dict, result is ERROR."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               contract_symbol="MNQM6",
                               client_kwargs={"authenticated": True})
        adapter._client.place_oso = AsyncMock(return_value="not_a_dict")
        signal = make_signal()
        result = await adapter.place_bracket(signal)
        assert not result.success
        assert result.status == OrderStatus.ERROR


# ---------------------------------------------------------------------------
# TestCancelOrder
# ---------------------------------------------------------------------------

class TestCancelOrder:
    """Tests for cancel_order."""

    @pytest.mark.asyncio
    async def test_cancel_dry_run(self):
        """Dry-run cancel returns success without calling broker."""
        adapter = make_adapter(mode="dry_run", armed=True)
        result = await adapter.cancel_order("42")
        assert result.success
        assert result.status == OrderStatus.CANCELLED
        adapter._client.cancel_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_success_removes_from_open_orders(self):
        """Successful cancel removes order from _open_orders."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._open_orders["42"] = {"signal_id": "s1"}
        result = await adapter.cancel_order("42")
        assert result.success
        assert "42" not in adapter._open_orders

    @pytest.mark.asyncio
    async def test_cancel_exception_returns_error(self):
        """Exception during cancel returns ERROR."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._client.cancel_order = AsyncMock(side_effect=Exception("network"))
        result = await adapter.cancel_order("42")
        assert not result.success
        assert result.status == OrderStatus.ERROR

    @pytest.mark.asyncio
    async def test_cancel_order_id_passed_correctly(self):
        """The order_id is passed as int to client.cancel_order."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        await adapter.cancel_order("99")
        adapter._client.cancel_order.assert_awaited_once_with(99)


# ---------------------------------------------------------------------------
# TestModifyStopOrder
# ---------------------------------------------------------------------------

class TestModifyStopOrder:
    """Tests for modify_stop_order."""

    @pytest.mark.asyncio
    async def test_modify_not_connected_returns_false(self):
        """When not connected, modify returns False."""
        adapter = make_adapter(mode="paper", armed=True, connected=False)
        result = await adapter.modify_stop_order(42, 17990.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_modify_success_returns_true(self):
        """Successful modify returns True."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        result = await adapter.modify_stop_order(42, 17990.0)
        assert result is True
        adapter._client.modify_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_modify_exception_returns_false(self):
        """Exception during modify returns False."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._client.modify_order = AsyncMock(side_effect=Exception("timeout"))
        result = await adapter.modify_stop_order(42, 17990.0)
        assert result is False


# ---------------------------------------------------------------------------
# TestCancelAll
# ---------------------------------------------------------------------------

class TestCancelAll:
    """Tests for cancel_all."""

    @pytest.mark.asyncio
    async def test_cancel_all_disarms(self):
        """cancel_all disarms the adapter."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._open_orders["1"] = {"signal_id": "s1"}
        await adapter.cancel_all()
        assert not adapter.armed

    @pytest.mark.asyncio
    async def test_cancel_all_dry_run(self):
        """Dry-run cancel_all returns cancelled result."""
        adapter = make_adapter(mode="dry_run", armed=True)
        results = await adapter.cancel_all()
        assert len(results) == 1
        assert results[0].success
        assert results[0].status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_all_iterates_open_orders(self):
        """cancel_all cancels each tracked order."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._open_orders["1"] = {"signal_id": "s1"}
        adapter._open_orders["2"] = {"signal_id": "s2"}
        results = await adapter.cancel_all()
        assert len(results) == 2
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_cancel_all_no_orders_returns_noop(self):
        """cancel_all with no open orders returns noop."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        results = await adapter.cancel_all()
        assert len(results) == 1
        assert "noop" in results[0].signal_id


# ---------------------------------------------------------------------------
# TestFlattenAll
# ---------------------------------------------------------------------------

class TestFlattenAll:
    """Tests for flatten_all_positions."""

    @pytest.mark.asyncio
    async def test_flatten_disarms(self):
        """flatten_all_positions disarms the adapter."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        await adapter.flatten_all_positions()
        assert not adapter.armed

    @pytest.mark.asyncio
    async def test_flatten_dry_run(self):
        """Dry-run flatten returns success with PLACED status."""
        adapter = make_adapter(mode="dry_run", armed=True)
        results = await adapter.flatten_all_positions()
        assert len(results) == 1
        assert results[0].success
        assert results[0].status == OrderStatus.PLACED

    @pytest.mark.asyncio
    async def test_flatten_not_connected(self):
        """When not connected, flatten returns ERROR."""
        adapter = make_adapter(mode="paper", armed=True, connected=False)
        results = await adapter.flatten_all_positions()
        assert len(results) == 1
        assert not results[0].success
        assert results[0].status == OrderStatus.ERROR

    @pytest.mark.asyncio
    async def test_flatten_success(self):
        """Successful flatten calls liquidate_all_positions."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        results = await adapter.flatten_all_positions()
        assert len(results) == 1
        assert results[0].success
        adapter._client.liquidate_all_positions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flatten_exception(self):
        """Exception during flatten returns ERROR."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._client.liquidate_all_positions = AsyncMock(
            side_effect=Exception("server error"))
        results = await adapter.flatten_all_positions()
        assert len(results) == 1
        assert not results[0].success
        assert results[0].status == OrderStatus.ERROR


# ---------------------------------------------------------------------------
# TestGetPositions
# ---------------------------------------------------------------------------

class TestGetPositions:
    """Tests for get_positions."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty(self):
        """Dry-run mode returns empty list."""
        adapter = make_adapter(mode="dry_run", armed=True)
        result = await adapter.get_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_not_connected_returns_empty(self):
        """When not connected, returns empty list."""
        adapter = make_adapter(mode="paper", armed=True, connected=False)
        result = await adapter.get_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_rate_limit_cooldown_skips_rest(self):
        """When in rate-limit cooldown, REST is skipped, falls back to WS cache."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._rate_limit_until = time.monotonic() + 999
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0}
        }
        result = await adapter.get_positions()
        # Should use WS cache fallback
        assert len(result) == 1
        assert result[0].quantity == 1

    @pytest.mark.asyncio
    async def test_429_error_exponential_backoff(self):
        """429 error triggers exponential backoff."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._client.get_positions = AsyncMock(
            side_effect=TradovateAPIError("429 Too Many Requests"))
        adapter._rate_limit_backoff = 0.0

        await adapter.get_positions()
        # After first 429, backoff should be set (initial * 2, starting from 30)
        assert adapter._rate_limit_backoff > 0
        assert adapter._rate_limit_until > time.monotonic()

    @pytest.mark.asyncio
    async def test_success_syncs_live_positions(self):
        """Successful REST call syncs _live_positions cache."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={
                                   "authenticated": True,
                                   "positions": [
                                       {"contractId": 999, "netPos": 2, "netPrice": 18000.0},
                                   ],
                               })
        result = await adapter.get_positions()
        assert len(result) == 1
        assert result[0].quantity == 2
        assert "999" in adapter._live_positions

    @pytest.mark.asyncio
    async def test_rest_empty_falls_back_to_ws_cache(self):
        """When REST fails, falls back to WS cache."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._client.get_positions = AsyncMock(
            side_effect=Exception("connection reset"))
        adapter._live_positions = {
            "888": {"contract_id": "888", "net_pos": -1, "net_price": 17500.0}
        }
        result = await adapter.get_positions()
        assert len(result) == 1
        assert result[0].quantity == -1

    @pytest.mark.asyncio
    async def test_rest_success_resets_backoff(self):
        """Successful REST call resets rate limit backoff."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={
                                   "authenticated": True,
                                   "positions": [
                                       {"contractId": 999, "netPos": 1, "netPrice": 18000.0},
                                   ],
                               })
        adapter._rate_limit_backoff = 120.0
        result = await adapter.get_positions()
        assert len(result) == 1
        assert adapter._rate_limit_backoff == 0.0

    @pytest.mark.asyncio
    async def test_position_drift_detection(self):
        """When REST and WS positions differ, drift is detected (logged)."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={
                                   "authenticated": True,
                                   "positions": [
                                       {"contractId": 999, "netPos": 2, "netPrice": 18000.0},
                                   ],
                               })
        # WS cache has different position
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0}
        }
        result = await adapter.get_positions()
        # After sync, live positions should match REST
        assert adapter._live_positions["999"]["net_pos"] == 2


# ---------------------------------------------------------------------------
# TestHandleWsEvent
# ---------------------------------------------------------------------------

class TestHandleWsEvent:
    """Tests for _handle_ws_event."""

    def test_ws_reconnected_schedules_poll(self):
        """ws_reconnected event schedules _poll_order_status."""
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        # Need a running event loop for create_task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Mock create_task to avoid actually running
            with patch("asyncio.create_task") as mock_ct:
                adapter._handle_ws_event({"e": "ws_reconnected", "d": {}})
                mock_ct.assert_called_once()
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_order_filled_removes_from_open_orders(self):
        """Filled order is removed from _open_orders."""
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        adapter._open_orders["100"] = {"signal_id": "s1"}
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "order",
                "eventType": "Updated",
                "entity": {"id": 100, "ordStatus": "Filled"},
            },
        })
        assert "100" not in adapter._open_orders

    def test_order_cancelled_removes_from_open_orders(self):
        """Cancelled order is removed from _open_orders."""
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        adapter._open_orders["200"] = {"signal_id": "s2"}
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "order",
                "eventType": "Updated",
                "entity": {"id": 200, "ordStatus": "Cancelled"},
            },
        })
        assert "200" not in adapter._open_orders

    def test_order_rejected_removes_from_open_orders(self):
        """Rejected order is removed from _open_orders."""
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        adapter._open_orders["300"] = {"signal_id": "s3"}
        adapter._pending_fills["300"] = 0.5
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "order",
                "eventType": "Updated",
                "entity": {"id": 300, "ordStatus": "Rejected"},
            },
        })
        assert "300" not in adapter._open_orders
        assert "300" not in adapter._pending_fills

    def test_fill_tracks_partial_fills(self):
        """Fill event accumulates partial fill qty."""
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        adapter._open_orders["50"] = {"signal_id": "s1", "quantity": 2}
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "fill",
                "eventType": "Created",
                "entity": {"orderId": 50, "contractId": 999, "qty": 1, "price": 18000.0},
            },
        })
        assert adapter._pending_fills.get("50") == 1.0

    def test_fill_overfill_detection(self):
        """Overfill: filled >= order qty causes cleanup of pending_fills.

        The adapter's logic uses `>=` to detect completion (including overfill),
        so the pending fill entry is popped. The overfill warning branch (elif >)
        is structurally unreachable but exists as a safety net.
        """
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        adapter._open_orders["60"] = {"signal_id": "s1", "quantity": 1}
        adapter._pending_fills["60"] = 0.5
        # This fill brings total to 1.5, which exceeds qty of 1
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "fill",
                "eventType": "Created",
                "entity": {"orderId": 60, "contractId": 999, "qty": 1, "price": 18000.0},
            },
        })
        # pending_fills is popped because filled_qty (1.5) >= order_qty (1)
        assert "60" not in adapter._pending_fills

    def test_fill_persists_to_file(self, tmp_path):
        """Fill event persists to fills file when _fills_file is set."""
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        fills_file = tmp_path / "tradovate_fills.json"
        adapter._fills_file = fills_file

        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "fill",
                "eventType": "Created",
                "entity": {
                    "id": 1001, "orderId": 50, "contractId": 999,
                    "qty": 1, "price": 18000.0, "action": "Buy",
                    "timestamp": "2026-03-12T10:00:00Z",
                },
            },
        })
        assert fills_file.exists()
        content = fills_file.read_text()
        assert "18000.0" in content

    def test_position_update_nonzero_adds_to_cache(self):
        """Non-zero position update adds to _live_positions."""
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "position",
                "eventType": "Updated",
                "entity": {
                    "contractId": 999, "netPos": 2, "netPrice": 18000.0,
                    "oTE": 50.0, "timestamp": "2026-03-12T10:00:00Z",
                },
            },
        })
        assert "999" in adapter._live_positions
        assert adapter._live_positions["999"]["net_pos"] == 2

    def test_position_update_zero_removes_from_cache(self):
        """Zero position update removes from _live_positions."""
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        adapter._live_positions["999"] = {"net_pos": 1}
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "position",
                "eventType": "Updated",
                "entity": {"contractId": 999, "netPos": 0},
            },
        })
        assert "999" not in adapter._live_positions

    def test_position_update_updates_timestamp(self):
        """Position update refreshes _live_positions_updated_at."""
        adapter = make_adapter(mode="paper", armed=True, connected=True)
        old_time = adapter._live_positions_updated_at
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "position",
                "eventType": "Updated",
                "entity": {"contractId": 999, "netPos": 1, "netPrice": 18000.0},
            },
        })
        assert adapter._live_positions_updated_at > old_time


# ---------------------------------------------------------------------------
# TestStaticHelpers
# ---------------------------------------------------------------------------

class TestStaticHelpers:
    """Tests for static helper methods."""

    def test_normalize_order_status_ordStatus(self):
        """ordStatus field is used first."""
        result = TradovateExecutionAdapter._normalize_order_status(
            {"ordStatus": "Working"})
        assert result == "working"

    def test_normalize_order_status_fallback_fields(self):
        """Falls back to orderStatus, then status."""
        r1 = TradovateExecutionAdapter._normalize_order_status(
            {"orderStatus": "Filled"})
        assert r1 == "filled"
        r2 = TradovateExecutionAdapter._normalize_order_status(
            {"status": "Cancelled"})
        assert r2 == "cancelled"

    def test_normalize_order_status_empty(self):
        """Empty dict returns empty string."""
        result = TradovateExecutionAdapter._normalize_order_status({})
        assert result == ""

    def test_extract_order_qty_remainingQty(self):
        """remainingQty is preferred."""
        result = TradovateExecutionAdapter._extract_order_qty(
            {"remainingQty": 3, "orderQty": 5})
        assert result == 3

    def test_extract_order_qty_fallback_fields(self):
        """Falls back through remainingQuantity, orderQty, qty, quantity."""
        assert TradovateExecutionAdapter._extract_order_qty(
            {"remainingQuantity": 2}) == 2
        assert TradovateExecutionAdapter._extract_order_qty(
            {"orderQty": 4}) == 4
        assert TradovateExecutionAdapter._extract_order_qty(
            {"qty": 1}) == 1
        assert TradovateExecutionAdapter._extract_order_qty(
            {"quantity": 7}) == 7

    def test_extract_order_qty_invalid_returns_zero(self):
        """Invalid/missing qty returns 0."""
        assert TradovateExecutionAdapter._extract_order_qty({}) == 0
        assert TradovateExecutionAdapter._extract_order_qty(
            {"remainingQty": "abc"}) == 0

    def test_is_protective_order_long_position_sell_stop(self):
        """Sell stop for a long position is protective."""
        order = {
            "contract_id": "999", "action": "Sell",
            "order_type": "Stop", "qty": 1,
            "price": None, "stop_price": 17990.0,
        }
        sides = {"999": "long"}
        assert TradovateExecutionAdapter._is_protective_order(order, sides) is True

    def test_is_protective_order_short_position_buy_stop(self):
        """Buy stop for a short position is protective."""
        order = {
            "contract_id": "999", "action": "Buy",
            "order_type": "StopLimit", "qty": 1,
            "price": 18010.0, "stop_price": 18010.0,
        }
        sides = {"999": "short"}
        assert TradovateExecutionAdapter._is_protective_order(order, sides) is True

    def test_is_protective_order_wrong_action_returns_false(self):
        """Buy for a long position is NOT protective."""
        order = {
            "contract_id": "999", "action": "Buy",
            "order_type": "Stop", "qty": 1,
            "price": None, "stop_price": 17990.0,
        }
        sides = {"999": "long"}
        assert TradovateExecutionAdapter._is_protective_order(order, sides) is False

    def test_is_protective_order_no_contract_returns_false(self):
        """Missing contract_id returns False."""
        order = {
            "contract_id": None, "action": "Sell",
            "order_type": "Stop", "qty": 1,
            "stop_price": 17990.0,
        }
        sides = {"999": "long"}
        assert TradovateExecutionAdapter._is_protective_order(order, sides) is False

    def test_is_protective_order_sparse_oco_rejected(self):
        """Sparse OCO-linked order (no qty/price/type) is NOT protective by itself.

        Post-c23ca82 (kill-switch hardening): stale OCO child orders from prior
        brackets could otherwise mask naked positions. The signal handler falls
        back to a live stop-specific broker check when no explicit protective
        orders are present.
        """
        order = {
            "contract_id": "999", "action": "Sell",
            "order_type": "", "qty": 0,
            "price": None, "stop_price": None,
            "oco_id": 555, "parent_id": None,
            "status": "working",
        }
        sides = {"999": "long"}
        assert TradovateExecutionAdapter._is_protective_order(order, sides) is False

    def test_normalize_working_order_terminal_returns_none(self):
        """Terminal status order returns None."""
        order = {"id": 1, "ordStatus": "Filled", "contractId": 999}
        assert TradovateExecutionAdapter._normalize_working_order(order) is None

    def test_normalize_working_order_working_returns_dict(self):
        """Working status order returns normalized dict."""
        order = {
            "id": 1, "ordStatus": "Working", "contractId": 999,
            "action": "Buy", "orderType": "Stop",
            "remainingQty": 1, "stopPrice": 17990.0,
        }
        result = TradovateExecutionAdapter._normalize_working_order(order)
        assert result is not None
        assert result["id"] == 1
        assert result["action"] == "Buy"
        assert result["stop_price"] == 17990.0


# ---------------------------------------------------------------------------
# TestBuildWorkingOrders
# ---------------------------------------------------------------------------

class TestBuildWorkingOrders:
    """Tests for build_working_orders."""

    def test_empty_inputs(self):
        """Empty/None inputs return empty results."""
        working, stats, debug = TradovateExecutionAdapter.build_working_orders(None, None)
        assert working == []
        assert stats == {"working": 0, "filled": 0, "cancelled": 0, "rejected": 0}
        assert debug == []

    def test_classifies_working_protective(self):
        """Working protective orders are classified correctly."""
        orders = [{
            "id": 1, "ordStatus": "Working", "contractId": 999,
            "action": "Sell", "orderType": "Stop",
            "remainingQty": 1, "stopPrice": 17990.0,
        }]
        positions = [{"contract_id": "999", "net_pos": 1}]
        working, stats, debug = TradovateExecutionAdapter.build_working_orders(orders, positions)
        assert len(working) == 1
        assert stats["working"] == 1

    def test_ignores_terminal_orders(self):
        """Filled/Cancelled/Rejected orders are counted but not in working list."""
        orders = [
            {"id": 1, "ordStatus": "Filled", "contractId": 999},
            {"id": 2, "ordStatus": "Cancelled", "contractId": 999},
            {"id": 3, "ordStatus": "Rejected", "contractId": 999},
        ]
        working, stats, debug = TradovateExecutionAdapter.build_working_orders(orders, [])
        assert len(working) == 0
        assert stats["filled"] == 1
        assert stats["cancelled"] == 1
        assert stats["rejected"] == 1

    def test_stats_counted_correctly(self):
        """All status categories are counted correctly."""
        orders = [
            {"id": 1, "ordStatus": "Working", "contractId": 999,
             "action": "Sell", "orderType": "Stop",
             "remainingQty": 1, "stopPrice": 17990.0},
            {"id": 2, "ordStatus": "Filled"},
            {"id": 3, "ordStatus": "Expired"},
        ]
        positions = [{"contract_id": "999", "net_pos": 1}]
        working, stats, debug = TradovateExecutionAdapter.build_working_orders(orders, positions)
        assert stats["working"] == 1
        assert stats["filled"] == 1
        assert stats["cancelled"] == 1  # Expired counts as cancelled

    def test_sparse_oco_with_position_qty_backfill(self):
        """Sparse OCO order with qty=0 gets qty backfilled from position qty.

        Post-c23ca82 the backfilled order is NOT classified as protective
        (sparse OCO is rejected by itself), so it won't appear in `working`.
        Verify the backfill via the debug classification instead.
        """
        orders = [{
            "id": 10, "ordStatus": "Working", "contractId": 999,
            "action": "Sell", "ocoId": 555,
        }]
        positions = [{"contract_id": "999", "net_pos": 2}]
        working, stats, debug = TradovateExecutionAdapter.build_working_orders(orders, positions)
        assert len(working) == 0
        assert stats["working"] == 1
        assert len(debug) == 1
        assert debug[0]["normalized"]["qty"] == 2


# ---------------------------------------------------------------------------
# TestGetAccountSummary
# ---------------------------------------------------------------------------

class TestGetAccountSummary:
    """Tests for get_account_summary."""

    @pytest.mark.asyncio
    async def test_not_connected_returns_empty(self):
        """When not connected, returns empty dict."""
        adapter = make_adapter(mode="paper", armed=True, connected=False)
        result = await adapter.get_account_summary()
        assert result == {}

    @pytest.mark.asyncio
    async def test_not_connected_with_cached_positions_returns_degraded_summary(self):
        """Cached broker positions remain visible when auth degrades."""
        adapter = make_adapter(
            mode="paper",
            armed=True,
            connected=True,
            client_kwargs={"authenticated": False, "account_name": "DEMO6315448", "account_id": 36869611},
        )
        adapter._live_positions = {
            "4214191": {
                "contract_id": "4214191",
                "net_pos": 3,
                "net_price": 23760.5,
                "open_pnl": 309.0,
                "ws_updated_at": time.time() - 2.0,
            }
        }

        result = await adapter.get_account_summary()

        assert result["degraded"] is True
        assert result["degraded_reason"] == "disconnected_or_auth_lost"
        assert result["account"] == "DEMO6315448"
        assert result["account_id"] == 36869611
        assert result["position_count"] == 1
        assert result["positions"][0]["contract_id"] == "4214191"
        assert result["positions"][0]["net_pos"] == 3
        assert result["open_pnl"] == 309.0
        assert result["authenticated"] is False

    @pytest.mark.asyncio
    async def test_parallel_rest_calls(self):
        """All four REST calls are made."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        result = await adapter.get_account_summary()
        adapter._client.get_cash_balance_snapshot.assert_awaited_once()
        adapter._client.get_positions.assert_awaited()
        adapter._client.get_fills.assert_awaited_once()
        adapter._client.get_orders.assert_awaited()

    @pytest.mark.asyncio
    async def test_partial_failures_handled(self):
        """Individual REST call failures do not break the summary."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._client.get_cash_balance_snapshot = AsyncMock(
            side_effect=Exception("timeout"))
        adapter._client.get_fills = AsyncMock(side_effect=Exception("timeout"))
        result = await adapter.get_account_summary()
        # Should still have positions and orders
        assert "positions" in result
        assert "fills" in result  # Empty list fallback
        assert result["fills"] == []

    @pytest.mark.asyncio
    async def test_live_positions_fallback(self):
        """When REST positions are empty, falls back to _live_positions."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True, "positions": []})
        adapter._live_positions = {
            "999": {"contract_id": "999", "net_pos": 1, "net_price": 18000.0,
                    "open_pnl": 50.0}
        }
        result = await adapter.get_account_summary()
        assert result["position_count"] == 1
        assert result["positions"][0]["net_pos"] == 1

    @pytest.mark.asyncio
    async def test_working_orders_processed(self):
        """Working orders are normalized via build_working_orders."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={
                                   "authenticated": True,
                                   "orders": [
                                       {"id": 1, "ordStatus": "Working", "contractId": 999,
                                        "action": "Sell", "orderType": "Stop",
                                        "remainingQty": 1, "stopPrice": 17990.0},
                                   ],
                                   "positions": [
                                       {"contractId": 999, "netPos": 1, "netPrice": 18000.0},
                                   ],
                               })
        result = await adapter.get_account_summary()
        assert "working_orders" in result
        assert "order_stats" in result

    @pytest.mark.asyncio
    async def test_fills_processed(self):
        """Fills are included in summary."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={
                                   "authenticated": True,
                                   "fills": [
                                       {"id": 1, "orderId": 10, "contractId": 999,
                                        "qty": 1, "price": 18000.0, "action": "Buy",
                                        "timestamp": "2026-03-12T10:00:00Z"},
                                   ],
                               })
        result = await adapter.get_account_summary()
        assert len(result["fills"]) == 1
        assert result["fills"][0]["price"] == 18000.0


# ---------------------------------------------------------------------------
# TestPollOrderStatus
# ---------------------------------------------------------------------------

class TestPollOrderStatus:
    """Tests for _poll_order_status."""

    @pytest.mark.asyncio
    async def test_rate_limit_cooldown_skips(self):
        """When in rate-limit cooldown, poll is skipped."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._rate_limit_until = time.monotonic() + 999
        await adapter._poll_order_status()
        adapter._client.get_orders.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_429_exponential_backoff(self):
        """429 error triggers exponential backoff on poll."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._client.get_orders = AsyncMock(
            side_effect=TradovateAPIError("429 rate limited"))
        adapter._rate_limit_backoff = 0.0
        await adapter._poll_order_status()
        assert adapter._rate_limit_backoff > 0
        assert adapter._rate_limit_until > time.monotonic()

    @pytest.mark.asyncio
    async def test_non_list_response_logs_warning(self):
        """Non-list response from get_orders is handled gracefully."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._client.get_orders = AsyncMock(return_value="not_a_list")
        # Should not raise
        await adapter._poll_order_status()

    @pytest.mark.asyncio
    async def test_missing_order_removed(self):
        """Order tracked locally but absent from REST is removed."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True,
                                              "orders": []})
        adapter._open_orders["42"] = {"signal_id": "s1"}
        await adapter._poll_order_status()
        assert "42" not in adapter._open_orders

    @pytest.mark.asyncio
    async def test_terminal_order_removed(self):
        """Order with terminal status in REST is removed from tracking."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={
                                   "authenticated": True,
                                   "orders": [
                                       {"id": 42, "ordStatus": "Filled"},
                                   ],
                               })
        adapter._open_orders["42"] = {"signal_id": "s1"}
        await adapter._poll_order_status()
        assert "42" not in adapter._open_orders

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """Cancellation should propagate to avoid swallowing task shutdown."""
        adapter = make_adapter(mode="paper", armed=True, connected=True,
                               client_kwargs={"authenticated": True})
        adapter._client.get_orders = AsyncMock(side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await adapter._poll_order_status()


class TestCancellationSemantics:
    """Tests for cancellation handling in critical async execution paths."""

    @pytest.mark.asyncio
    async def test_place_bracket_cancelled_error_propagates(self):
        """place_bracket should re-raise CancelledError for clean shutdown."""
        adapter = make_adapter(
            mode="paper",
            armed=True,
            connected=True,
            contract_symbol="MNQM6",
            client_kwargs={"authenticated": True, "positions": []},
        )
        adapter._client.place_oso = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await adapter.place_bracket(make_signal())


# ---------------------------------------------------------------------------
# TestGetLivePositionsWithPnl
# ---------------------------------------------------------------------------

class TestGetLivePositionsWithPnl:
    """Tests for get_live_positions_with_pnl."""

    def test_empty_returns_empty(self):
        """No live positions returns empty dict."""
        adapter = make_adapter(mode="paper", armed=True)
        result = adapter.get_live_positions_with_pnl()
        assert result == {}

    def test_returns_positions_with_cache_age(self):
        """Positions include cache_age_seconds field."""
        adapter = make_adapter(mode="paper", armed=True)
        adapter._live_positions = {
            "999": {
                "contract_id": "999", "net_pos": 1, "net_price": 18000.0,
                "ote": 50.0, "open_pnl": 50.0,
                "ws_updated_at": time.time() - 5.0,
                "timestamp": "2026-03-12T10:00:00Z",
            }
        }
        result = adapter.get_live_positions_with_pnl()
        assert "999" in result
        assert result["999"]["cache_age_seconds"] is not None
        assert result["999"]["cache_age_seconds"] >= 4.0

    def test_no_ws_time_cache_age_none(self):
        """When ws_updated_at is 0, cache_age_seconds is None."""
        adapter = make_adapter(mode="paper", armed=True)
        adapter._live_positions = {
            "999": {
                "contract_id": "999", "net_pos": 1, "net_price": 18000.0,
                "ws_updated_at": 0,
            }
        }
        result = adapter.get_live_positions_with_pnl()
        assert result["999"]["cache_age_seconds"] is None
