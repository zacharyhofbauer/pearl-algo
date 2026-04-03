"""Tests for position_monitor module.

Tests the core position monitoring logic extracted from service.py.
Uses mocks for the service object and its dependencies.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.market_agent.position_monitor import monitor_open_position


def _make_svc(
    *,
    positions: dict | None = None,
    active_trades: list | None = None,
    has_trailing: bool = False,
    has_runner: bool = False,
):
    """Build a mock service object with the attributes monitor_open_position expects."""
    svc = MagicMock()
    svc.execution_adapter = MagicMock()
    svc.execution_adapter._live_positions = positions or {}
    svc.execution_adapter.get_positions = AsyncMock()

    # Virtual trade manager
    svc.virtual_trade_manager = MagicMock()
    svc.virtual_trade_manager.position_tracker = MagicMock()
    svc.virtual_trade_manager.position_tracker.get_active_virtual_trades = MagicMock(
        return_value=active_trades or []
    )

    # Trailing stop
    svc._trailing_stop_manager = MagicMock() if has_trailing else None
    if has_trailing:
        svc._trailing_stop_manager.enabled = True
        svc._trailing_stop_manager.get_state = MagicMock(return_value=None)
        svc._trailing_stop_manager.register_position = MagicMock()
        svc._trailing_stop_manager.check_and_update = MagicMock(return_value=None)
        svc._trailing_stop_manager.remove_position = MagicMock()

    # Runner
    svc._runner_manager = MagicMock() if has_runner else None
    if has_runner:
        svc._runner_manager.enabled = True
        svc._runner_manager.get_phase = MagicMock(return_value=None)
        svc._runner_manager.register_position = MagicMock()
        svc._runner_manager.update_position = MagicMock(return_value=(None, None, False))
        svc._runner_manager.remove_position = MagicMock()

    # Position monitor state
    svc._pos_monitor = None
    svc._last_broker_stop = None
    svc._stop_order_miss_count = 0
    svc._position_sync_interval = 30
    svc._last_position_sync_time = 0
    svc.notifier = None
    svc.config = {}

    # Helper methods
    svc._get_current_atr = MagicMock(return_value=5.0)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=0)
    svc._find_initial_stop_price = MagicMock(return_value=0)
    svc._find_stop_order_id = AsyncMock(return_value=None)
    svc._find_tp_order_id = AsyncMock(return_value=None)
    svc._ingest_trailing_stop_override = MagicMock()
    svc._apply_regime_trailing_preset = MagicMock()

    # Advanced exit manager (lazy-init in position_monitor via hasattr)
    svc._adv_exit_mgr = None

    return svc


def _make_market_data(close: float = 21500.0) -> dict:
    return {"latest_bar": {"close": close}}


@pytest.mark.asyncio
async def test_returns_early_when_no_execution_adapter() -> None:
    svc = _make_svc()
    svc.execution_adapter = None
    await monitor_open_position(svc, _make_market_data())
    # No error should occur


@pytest.mark.asyncio
async def test_returns_early_when_no_positions() -> None:
    svc = _make_svc(positions={}, active_trades=[])
    await monitor_open_position(svc, _make_market_data())
    assert svc._pos_monitor is None


@pytest.mark.asyncio
async def test_cleans_up_trailing_stop_on_position_close() -> None:
    svc = _make_svc(positions={}, has_trailing=True)
    # Simulate previously tracked position
    svc._pos_monitor = {"entry_price": 21000.0, "direction": "long"}
    svc._trailing_stop_manager._states = {"pos-1": {}}

    await monitor_open_position(svc, _make_market_data())

    svc._trailing_stop_manager.remove_position.assert_called_once_with("pos-1")
    assert svc._pos_monitor is None


@pytest.mark.asyncio
async def test_initializes_monitor_state_for_new_long_position() -> None:
    positions = {"contract-1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    assert svc._pos_monitor is not None
    assert svc._pos_monitor["entry_price"] == 21000.0
    assert svc._pos_monitor["direction"] == "long"
    assert svc._pos_monitor["max_price"] == 21050.0
    assert svc._pos_monitor["min_price"] == 21050.0


@pytest.mark.asyncio
async def test_initializes_monitor_state_for_short_position() -> None:
    positions = {"contract-1": {"net_pos": -1, "net_price": 21500.0}}
    svc = _make_svc(positions=positions)

    await monitor_open_position(svc, _make_market_data(close=21450.0))

    assert svc._pos_monitor is not None
    assert svc._pos_monitor["direction"] == "short"


@pytest.mark.asyncio
async def test_skips_zero_net_pos() -> None:
    positions = {"contract-1": {"net_pos": 0, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)

    await monitor_open_position(svc, _make_market_data())

    assert svc._pos_monitor is None


@pytest.mark.asyncio
async def test_skips_zero_entry_price() -> None:
    positions = {"contract-1": {"net_pos": 1, "net_price": 0}}
    svc = _make_svc(positions=positions)

    await monitor_open_position(svc, _make_market_data())

    assert svc._pos_monitor is None


@pytest.mark.asyncio
async def test_skips_zero_current_price() -> None:
    positions = {"contract-1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)

    await monitor_open_position(svc, _make_market_data(close=0))

    assert svc._pos_monitor is None


@pytest.mark.asyncio
async def test_updates_mfe_mae_across_cycles() -> None:
    positions = {"contract-1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)

    # First cycle: price at 21050
    await monitor_open_position(svc, _make_market_data(close=21050.0))
    assert svc._pos_monitor["max_price"] == 21050.0
    assert svc._pos_monitor["min_price"] == 21050.0

    # Second cycle: price drops to 20980
    await monitor_open_position(svc, _make_market_data(close=20980.0))
    assert svc._pos_monitor["max_price"] == 21050.0  # unchanged
    assert svc._pos_monitor["min_price"] == 20980.0  # updated

    # Third cycle: new high
    await monitor_open_position(svc, _make_market_data(close=21100.0))
    assert svc._pos_monitor["max_price"] == 21100.0  # updated
    assert svc._pos_monitor["min_price"] == 20980.0  # unchanged


@pytest.mark.asyncio
async def test_fallback_to_virtual_positions() -> None:
    """When no broker positions, fall back to virtual trades from signals.jsonl."""
    active_trades = [
        {
            "signal": {
                "direction": "long",
                "entry_price": 21000.0,
                "stop_loss": 20950.0,
                "take_profit": 21100.0,
            }
        }
    ]
    svc = _make_svc(positions={}, active_trades=active_trades)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    assert svc._pos_monitor is not None
    assert svc._pos_monitor["direction"] == "long"


@pytest.mark.asyncio
async def test_periodic_rest_sync_fires() -> None:
    """Position sync should fire when interval elapsed."""
    positions = {"contract-1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)
    svc._last_position_sync_time = 0  # long ago
    svc._position_sync_interval = 0  # always sync

    await monitor_open_position(svc, _make_market_data())

    svc.execution_adapter.get_positions.assert_called_once_with(force_rest=True)


@pytest.mark.asyncio
async def test_registers_trailing_stop_for_new_position() -> None:
    positions = {"contract-1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc._trailing_stop_manager.register_position.assert_called_once_with(
        position_id="contract-1",
        entry_price=21000.0,
        direction="long",
        initial_stop=20950.0,
    )


@pytest.mark.asyncio
async def test_registers_runner_for_new_position() -> None:
    positions = {"contract-1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_runner=True)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc._runner_manager.register_position.assert_called_once()
    call_kwargs = svc._runner_manager.register_position.call_args
    assert call_kwargs[1]["direction"] == "long"
    assert call_kwargs[1]["entry_price"] == 21000.0


# ── Position sync exception handling (lines 47-48) ──


@pytest.mark.asyncio
async def test_position_sync_exception_is_nonfatal() -> None:
    """If REST position sync raises, monitoring continues normally."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)
    svc._position_sync_interval = 0  # force sync
    svc._last_position_sync_time = 0
    svc.execution_adapter.get_positions = AsyncMock(side_effect=RuntimeError("timeout"))

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    # Monitor should still initialize despite sync failure
    assert svc._pos_monitor is not None
    assert svc._pos_monitor["direction"] == "long"


# ── Virtual trade fallback exception (lines 70-71) ──


@pytest.mark.asyncio
async def test_virtual_trade_fallback_exception_is_nonfatal() -> None:
    """If virtual trade lookup raises, treat as no positions."""
    svc = _make_svc(positions={})
    svc.virtual_trade_manager.position_tracker.get_active_virtual_trades = MagicMock(
        side_effect=RuntimeError("db error")
    )

    await monitor_open_position(svc, _make_market_data())

    assert svc._pos_monitor is None


# ── Runner cleanup on position close (lines 81-83) ──


@pytest.mark.asyncio
async def test_cleans_up_runner_on_position_close() -> None:
    """When positions go flat, runner manager states are cleaned up."""
    svc = _make_svc(positions={}, has_runner=True)
    svc._pos_monitor = {"entry_price": 21000.0, "direction": "long"}
    svc._runner_manager._states = {"pos-1": {}}

    await monitor_open_position(svc, _make_market_data())

    svc._runner_manager.remove_position.assert_called_once_with("pos-1")
    assert svc._pos_monitor is None


# ── Trailing stop fallback to virtual trade stop (line 122) ──


@pytest.mark.asyncio
async def test_trailing_stop_falls_back_to_virtual_stop() -> None:
    """When broker stop lookup returns 0, fallback to _find_initial_stop_price."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=0)
    svc._find_initial_stop_price = MagicMock(return_value=20950.0)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc._find_initial_stop_price.assert_called_once_with("long")
    svc._trailing_stop_manager.register_position.assert_called_once_with(
        position_id="c1",
        entry_price=21000.0,
        direction="long",
        initial_stop=20950.0,
    )


# ── Warning when no stop found (line 132) ──


@pytest.mark.asyncio
async def test_trailing_stop_not_registered_when_no_stop_price() -> None:
    """If neither broker nor virtual stop found, trailing stop not registered."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=0)
    svc._find_initial_stop_price = MagicMock(return_value=0)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc._trailing_stop_manager.register_position.assert_not_called()


# ── Stop/TP lookup exception (lines 174-175) ──


@pytest.mark.asyncio
async def test_stop_tp_lookup_exception_is_nonfatal() -> None:
    """Exception fetching stop/TP from virtual trades doesn't crash."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)
    # With broker positions present, the fallback block (line 57) is skipped.
    # The stop/TP lookup at line 167 is the only call — make it raise.
    svc.virtual_trade_manager.position_tracker.get_active_virtual_trades = MagicMock(
        side_effect=RuntimeError("db error")
    )

    # Should not raise
    await monitor_open_position(svc, _make_market_data(close=21050.0))
    assert svc._pos_monitor is not None


# ── Runner mode: modify stop + cancel TP (lines 186-212) ──


@pytest.mark.asyncio
async def test_runner_modifies_stop_on_action() -> None:
    """Runner returns an action with new stop — broker stop is modified."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_runner=True)
    svc._runner_manager.update_position = MagicMock(
        return_value=("breakeven", 21010.0, False)
    )
    svc._find_stop_order_id = AsyncMock(return_value="order-123")
    svc.execution_adapter.modify_stop_order = AsyncMock(return_value=True)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.execution_adapter.modify_stop_order.assert_called_once_with("order-123", 21010.0)
    assert svc._last_broker_stop == 21010.0


@pytest.mark.asyncio
async def test_runner_modify_stop_failure() -> None:
    """Runner stop modify returns False — last_broker_stop not updated."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_runner=True)
    svc._runner_manager.update_position = MagicMock(
        return_value=("breakeven", 21010.0, False)
    )
    svc._find_stop_order_id = AsyncMock(return_value="order-123")
    svc.execution_adapter.modify_stop_order = AsyncMock(return_value=False)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    assert svc._last_broker_stop is None


@pytest.mark.asyncio
async def test_runner_modify_stop_no_order_found() -> None:
    """Runner action but no stop order found — logs warning, no crash."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_runner=True)
    svc._runner_manager.update_position = MagicMock(
        return_value=("breakeven", 21010.0, False)
    )
    svc._find_stop_order_id = AsyncMock(return_value=None)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.execution_adapter.modify_stop_order.assert_not_called()


@pytest.mark.asyncio
async def test_runner_cancels_tp_order() -> None:
    """Runner phase requests TP cancellation."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_runner=True)
    svc._runner_manager.update_position = MagicMock(
        return_value=("runner_phase", None, True)  # cancel_tp=True
    )
    svc._find_tp_order_id = AsyncMock(return_value="tp-order-99")
    cancel_result = MagicMock()
    cancel_result.success = True
    svc.execution_adapter.cancel_order = AsyncMock(return_value=cancel_result)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.execution_adapter.cancel_order.assert_called_once_with("tp-order-99")


@pytest.mark.asyncio
async def test_runner_cancel_tp_failure() -> None:
    """Runner TP cancel returns failure — no crash."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_runner=True)
    svc._runner_manager.update_position = MagicMock(
        return_value=("runner_phase", None, True)
    )
    svc._find_tp_order_id = AsyncMock(return_value="tp-order-99")
    cancel_result = MagicMock()
    cancel_result.success = False
    svc.execution_adapter.cancel_order = AsyncMock(return_value=cancel_result)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.execution_adapter.cancel_order.assert_called_once()


@pytest.mark.asyncio
async def test_runner_cancel_tp_no_order() -> None:
    """Runner cancel_tp but no TP order found — graceful."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_runner=True)
    svc._runner_manager.update_position = MagicMock(
        return_value=("runner_phase", None, True)
    )
    svc._find_tp_order_id = AsyncMock(return_value=None)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.execution_adapter.cancel_order.assert_not_called()


@pytest.mark.asyncio
async def test_runner_update_exception_is_nonfatal() -> None:
    """Runner update raising doesn't crash monitor."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_runner=True)
    svc._runner_manager.update_position = MagicMock(side_effect=RuntimeError("boom"))

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    assert svc._pos_monitor is not None


# ── Trailing stop broker sync retry (lines 235-239) ──


@pytest.mark.asyncio
async def test_trailing_stop_broker_sync_retry() -> None:
    """When check_and_update returns None but internal stop differs from broker, retry sync."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    # check_and_update returns None (no new stop), but state has active phase
    svc._trailing_stop_manager.check_and_update = MagicMock(return_value=None)
    svc._trailing_stop_manager.get_state = MagicMock(return_value={
        "current_phase": "initial",
        "current_stop": 20960.0,
    })
    svc._last_broker_stop = None  # broker out of sync
    svc._find_stop_order_id = AsyncMock(return_value="order-55")
    svc.execution_adapter.modify_stop_order = AsyncMock(return_value=True)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.execution_adapter.modify_stop_order.assert_called_once_with("order-55", 20960.0)
    assert svc._last_broker_stop == 20960.0
    assert svc._stop_order_miss_count == 0


# ── Trailing stop modify success (lines 242-253) ──


@pytest.mark.asyncio
async def test_trailing_stop_modify_success() -> None:
    """Trailing stop check_and_update returns new stop, broker modify succeeds."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    svc._trailing_stop_manager.check_and_update = MagicMock(return_value=20970.0)
    svc._find_stop_order_id = AsyncMock(return_value="order-10")
    svc.execution_adapter.modify_stop_order = AsyncMock(return_value=True)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.execution_adapter.modify_stop_order.assert_called_once_with("order-10", 20970.0)
    assert svc._last_broker_stop == 20970.0
    assert svc._stop_order_miss_count == 0


@pytest.mark.asyncio
async def test_trailing_stop_modify_failure() -> None:
    """Trailing stop modify returns False — last_broker_stop not updated."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    svc._trailing_stop_manager.check_and_update = MagicMock(return_value=20970.0)
    svc._find_stop_order_id = AsyncMock(return_value="order-10")
    svc.execution_adapter.modify_stop_order = AsyncMock(return_value=False)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    assert svc._last_broker_stop is None


# ── Trailing stop miss count escalation (lines 254-286) ──


@pytest.mark.asyncio
async def test_trailing_stop_miss_count_increments() -> None:
    """No stop order found increments miss count."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    svc._trailing_stop_manager.check_and_update = MagicMock(return_value=20970.0)
    svc._find_stop_order_id = AsyncMock(return_value=None)  # no stop order
    svc._stop_order_miss_count = 0

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    assert svc._stop_order_miss_count == 1


@pytest.mark.asyncio
async def test_trailing_stop_miss_count_3_replaces_stop() -> None:
    """After 3 misses, attempts to re-place the stop order."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    svc._trailing_stop_manager.check_and_update = MagicMock(return_value=20970.0)
    svc._find_stop_order_id = AsyncMock(return_value=None)
    svc._stop_order_miss_count = 2  # will become 3
    svc.config = {"symbol": "MNQ"}
    svc.execution_adapter.place_stop_order = AsyncMock(return_value=True)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.execution_adapter.place_stop_order.assert_called_once_with(
        symbol="MNQ", action="Sell", quantity=1, stop_price=20970.0,
    )
    assert svc._last_broker_stop == 20970.0
    assert svc._stop_order_miss_count == 0


@pytest.mark.asyncio
async def test_trailing_stop_miss_count_3_replace_fails() -> None:
    """Re-place attempt returns falsy — miss count stays reset (by the place logic)."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    svc._trailing_stop_manager.check_and_update = MagicMock(return_value=20970.0)
    svc._find_stop_order_id = AsyncMock(return_value=None)
    svc._stop_order_miss_count = 2
    svc.config = {"symbol": "MNQ"}
    svc.execution_adapter.place_stop_order = AsyncMock(return_value=False)

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    # place failed, miss count stays at 3
    assert svc._stop_order_miss_count == 3


@pytest.mark.asyncio
async def test_trailing_stop_miss_count_3_replace_exception() -> None:
    """Re-place attempt raises — error logged, no crash."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    svc._trailing_stop_manager.check_and_update = MagicMock(return_value=20970.0)
    svc._find_stop_order_id = AsyncMock(return_value=None)
    svc._stop_order_miss_count = 2
    svc.config = {"symbol": "MNQ"}
    svc.execution_adapter.place_stop_order = AsyncMock(
        side_effect=RuntimeError("network error")
    )

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    assert svc._stop_order_miss_count == 3


@pytest.mark.asyncio
async def test_trailing_stop_miss_count_6_deregisters() -> None:
    """After 6 misses, position is deregistered from trailing stop."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    svc._trailing_stop_manager.check_and_update = MagicMock(return_value=20970.0)
    svc._find_stop_order_id = AsyncMock(return_value=None)
    svc._stop_order_miss_count = 5  # will become 6

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc._trailing_stop_manager.remove_position.assert_called_with("c1")
    assert svc._stop_order_miss_count == 0


@pytest.mark.asyncio
async def test_trailing_stop_exception_is_nonfatal() -> None:
    """Exception in trailing stop block doesn't crash monitor."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    svc._trailing_stop_manager.check_and_update = MagicMock(
        side_effect=RuntimeError("check failed")
    )

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    assert svc._pos_monitor is not None


# ── Short position trailing stop re-place uses Buy (line 264) ──


@pytest.mark.asyncio
async def test_trailing_stop_short_position_replace_uses_buy() -> None:
    """Short position re-places stop with action='Buy'."""
    positions = {"c1": {"net_pos": -2, "net_price": 21500.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=21550.0)
    svc._trailing_stop_manager.check_and_update = MagicMock(return_value=21540.0)
    svc._find_stop_order_id = AsyncMock(return_value=None)
    svc._stop_order_miss_count = 2
    svc.config = {"symbol": "MNQ"}
    svc.execution_adapter.place_stop_order = AsyncMock(return_value=True)

    await monitor_open_position(svc, _make_market_data(close=21450.0))

    svc.execution_adapter.place_stop_order.assert_called_once_with(
        symbol="MNQ", action="Buy", quantity=2, stop_price=21540.0,
    )


# ── Advanced Exit Manager initialization (lines 292-297) ──


@pytest.mark.asyncio
async def test_advanced_exit_manager_initialized_from_config() -> None:
    """Advanced exit manager is lazily created from config."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)
    # Remove _adv_exit_mgr attribute to trigger hasattr check
    del svc._adv_exit_mgr
    svc.config = {"advanced_exits": {"time_stop_minutes": 30}}

    with patch("pearlalgo.market_agent.position_monitor.AdvancedExitManager") as MockAEM:
        mock_instance = MagicMock()
        mock_instance.should_exit = MagicMock(return_value=(False, ""))
        MockAEM.return_value = mock_instance

        await monitor_open_position(svc, _make_market_data(close=21050.0))

        MockAEM.assert_called_once_with({"time_stop_minutes": 30})
        assert svc._adv_exit_mgr is mock_instance


@pytest.mark.asyncio
async def test_advanced_exit_manager_none_when_no_config() -> None:
    """No advanced_exits config -> _adv_exit_mgr set to None."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)
    del svc._adv_exit_mgr
    svc.config = {}

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    assert svc._adv_exit_mgr is None


# ── Advanced exit triggers flatten (lines 300-329) ──


@pytest.mark.asyncio
async def test_advanced_exit_triggers_flatten() -> None:
    """When advanced exit manager says should_exit, position is flattened."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)
    mock_aem = MagicMock()
    mock_aem.should_exit = MagicMock(return_value=(True, "time_stop: held too long"))
    svc._adv_exit_mgr = mock_aem

    flatten_result = MagicMock()
    flatten_result.success = True
    svc.execution_adapter.flatten_all_positions = AsyncMock(return_value=[flatten_result])

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.execution_adapter.flatten_all_positions.assert_called_once()


@pytest.mark.asyncio
async def test_advanced_exit_sends_notification() -> None:
    """Advanced exit with notifier sends critical notification."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)
    mock_aem = MagicMock()
    mock_aem.should_exit = MagicMock(return_value=(True, "time_stop"))
    svc._adv_exit_mgr = mock_aem
    svc.notifier = AsyncMock()

    flatten_result = MagicMock()
    flatten_result.success = True
    svc.execution_adapter.flatten_all_positions = AsyncMock(return_value=[flatten_result])

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc.notifier.send.assert_called_once()
    call_args = svc.notifier.send.call_args
    assert "ADVANCED EXIT" in call_args[0][0]


@pytest.mark.asyncio
async def test_advanced_exit_flatten_exception() -> None:
    """Advanced exit flatten raising doesn't crash monitor."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions)
    mock_aem = MagicMock()
    mock_aem.should_exit = MagicMock(return_value=(True, "time_stop"))
    svc._adv_exit_mgr = mock_aem
    svc.execution_adapter.flatten_all_positions = AsyncMock(
        side_effect=RuntimeError("flatten failed")
    )

    # Should not raise
    await monitor_open_position(svc, _make_market_data(close=21050.0))


# ── Logging branches: short distance, runner/trail info (lines 344, 349, 355, 359) ──


@pytest.mark.asyncio
async def test_short_position_distance_logging() -> None:
    """Short position logs dist_stop and dist_tp correctly."""
    positions = {"c1": {"net_pos": -1, "net_price": 21500.0}}
    active_trades = [
        {"signal": {"direction": "short", "stop_loss": 21550.0, "take_profit": 21400.0}}
    ]
    svc = _make_svc(positions=positions, active_trades=active_trades)
    # Set log_counter so it triggers on this cycle (counter % 4 == 1)
    svc._pos_monitor = None  # fresh init will set log_counter=0, then +1 = 1 % 4 == 1

    await monitor_open_position(svc, _make_market_data(close=21450.0))

    # If no error, logging succeeded for short position distances
    assert svc._pos_monitor is not None
    assert svc._pos_monitor["direction"] == "short"


@pytest.mark.asyncio
async def test_runner_phase_in_log() -> None:
    """Runner phase info is included in periodic log output."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_runner=True)
    svc._runner_manager.get_phase = MagicMock(return_value="breakeven")

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    svc._runner_manager.get_phase.assert_called_with("c1")


@pytest.mark.asyncio
async def test_trailing_stop_phase_in_log() -> None:
    """Trailing stop phase info in periodic log when no runner."""
    positions = {"c1": {"net_pos": 1, "net_price": 21000.0}}
    svc = _make_svc(positions=positions, has_trailing=True)
    svc._find_initial_stop_from_broker = AsyncMock(return_value=20950.0)
    svc._trailing_stop_manager.get_state = MagicMock(return_value={
        "current_phase": "phase2",
        "current_stop": 20980.0,
    })

    await monitor_open_position(svc, _make_market_data(close=21050.0))

    # get_state should be called during log formatting
    svc._trailing_stop_manager.get_state.assert_called()
