"""
Tests for Tradovate Paper execution guard.

Covers:
- Position guard: opposite direction blocked
- Position guard: max positions reached
- Position guard: same direction allowed
- Intraday breach: blocks when equity below floor
- Intraday breach: allows when equity above floor
- follower_execute: uses the streamlined execution path
"""

from __future__ import annotations

import asyncio
import time
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter
from pearlalgo.execution.tradovate.config import TradovateConfig
from pearlalgo.execution.base import (
    ExecutionConfig,
    ExecutionMode,
    OrderStatus,
)
from pearlalgo.market_agent.tv_paper_eval_tracker import (
    TvPaperEvalConfig,
    TvPaperEvalTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client():
    """Create a fully-mocked TradovateClient."""
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
    client.place_oso = AsyncMock(return_value={"orderId": 100})
    client.cancel_order = AsyncMock()
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
    """Create a connected, armed adapter with mocked client."""
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
    adapter._live_positions_updated_at = time.monotonic()
    return adapter


def _make_tracker(tmp_path: Path, **overrides) -> TvPaperEvalTracker:
    """Create a tracker rooted in tmp_path."""
    cfg = TvPaperEvalConfig(**overrides)
    return TvPaperEvalTracker(config=cfg, state_dir=tmp_path)


def _long_signal() -> dict:
    return {
        "signal_id": "guard_long_1",
        "symbol": "MNQ",
        "direction": "long",
        "entry_price": 18000.0,
        "stop_loss": 17990.0,
        "take_profit": 18020.0,
        "position_size": 1,
    }


def _short_signal() -> dict:
    return {
        "signal_id": "guard_short_1",
        "symbol": "MNQ",
        "direction": "short",
        "entry_price": 18000.0,
        "stop_loss": 18020.0,
        "take_profit": 17980.0,
        "position_size": 1,
    }


# ===========================================================================
# Position guard: opposite direction blocked
# ===========================================================================


class TestPositionGuardOpposite:
    """Opposite-direction orders are rejected when a broker position exists."""

    @pytest.mark.asyncio
    async def test_long_blocked_by_short_position(self):
        adapter = _make_adapter(allow_reversal_on_opposite_signal=False)
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
    async def test_short_blocked_by_long_position(self):
        adapter = _make_adapter(allow_reversal_on_opposite_signal=False)
        adapter._live_positions["999"] = {
            "contract_id": "999",
            "net_pos": 2,
            "net_price": 17950.0,
        }

        result = await adapter.place_bracket(_short_signal())

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "opposite_direction_blocked" in result.error_message


# ===========================================================================
# Position guard: max positions reached
# ===========================================================================


class TestPositionGuardMax:
    """Orders blocked when at maximum position count."""

    @pytest.mark.asyncio
    async def test_max_positions_blocks_same_direction(self):
        adapter = _make_adapter()
        # Default max_net_positions = 1; one long position already
        adapter._live_positions["999"] = {
            "contract_id": "999",
            "net_pos": 1,
            "net_price": 18000.0,
        }

        result = await adapter.place_bracket(_long_signal())

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "max_position_size" in result.error_message


# ===========================================================================
# Position guard: same direction allowed (when room exists)
# ===========================================================================


class TestPositionGuardSameDirectionAllowed:
    """Same-direction orders allowed when below max positions."""

    @pytest.mark.asyncio
    async def test_same_direction_with_room(self):
        adapter = _make_adapter()
        adapter.config.max_positions = 3

        adapter._live_positions["999"] = {
            "contract_id": "999",
            "net_pos": 1,
            "net_price": 18000.0,
        }

        result = await adapter.place_bracket(_long_signal())

        assert result.success is True
        assert result.status == OrderStatus.PLACED

    @pytest.mark.asyncio
    async def test_no_positions_allows_order(self):
        adapter = _make_adapter()

        result = await adapter.place_bracket(_long_signal())

        assert result.success is True
        assert result.status == OrderStatus.PLACED


# ===========================================================================
# Intraday breach: blocks when equity below floor
# ===========================================================================


class TestIntradayBreachBlocks:
    """check_intraday_breach returns True and ends attempt when equity < floor."""

    def test_breach_detected_below_floor(self, tmp_path):
        # Disable auto-reset so current_attempt stays on the failed attempt
        tracker = _make_tracker(tmp_path, auto_reset_on_fail=False)
        # Default floor = 50000 - 2000 = 48000
        assert tracker.current_attempt.outcome == "active"

        breached = tracker.check_intraday_breach(47_999.0)

        assert breached is True
        assert tracker.current_attempt.outcome == "fail"

    def test_breach_auto_reset_creates_new_attempt(self, tmp_path):
        """With auto_reset_on_fail=True (default), a new active attempt is started."""
        tracker = _make_tracker(tmp_path, auto_reset_on_fail=True)
        original_id = tracker.current_attempt.attempt_id

        breached = tracker.check_intraday_breach(47_999.0)

        assert breached is True
        # Auto-reset creates a new active attempt
        assert tracker.current_attempt.outcome == "active"
        assert tracker.current_attempt.attempt_id == original_id + 1

    def test_breach_exact_floor_not_breached(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        # Equity exactly at floor is NOT below floor
        breached = tracker.check_intraday_breach(48_000.0)

        assert breached is False
        assert tracker.current_attempt.outcome == "active"


# ===========================================================================
# Intraday breach: allows when equity above floor
# ===========================================================================


class TestIntradayBreachAllows:
    """check_intraday_breach returns False when equity is above floor."""

    def test_no_breach_above_floor(self, tmp_path):
        tracker = _make_tracker(tmp_path)

        breached = tracker.check_intraday_breach(50_000.0)

        assert breached is False
        assert tracker.current_attempt.outcome == "active"

    def test_no_breach_when_already_failed(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.current_attempt.outcome = "fail"

        # Even with low equity, should return False (already ended)
        breached = tracker.check_intraday_breach(40_000.0)

        assert breached is False


# ===========================================================================
# follower_execute: streamlined execution path
# ===========================================================================


class TestFollowerExecuteFastPath:
    """follower_execute only runs the streamlined circuit-breaker + execution path."""

    @pytest.mark.asyncio
    async def test_follower_execute_calls_execute_signal(self):
        """Verify follower_execute calls _execute_signal directly."""
        from pearlalgo.market_agent.signal_handler import SignalHandler

        # Create a minimal SignalHandler with mocked dependencies
        handler = object.__new__(SignalHandler)
        handler.signal_count = 0
        handler.error_count = 0
        handler.last_signal_generated_at = None
        handler.last_signal_id_prefix = None
        handler._execution_semaphore = asyncio.Semaphore(1)

        # Mock all collaborators
        handler._circuit_breaker = MagicMock()
        handler._circuit_breaker.check = MagicMock(return_value=True)

        handler.performance_tracker = MagicMock()
        handler.performance_tracker.track_signal_generated = MagicMock(return_value="sig_001")
        handler.performance_tracker.update_signal_execution_metadata = MagicMock()

        handler._order_manager = MagicMock()
        handler._audit_logger = None
        handler._notification_queue = MagicMock()
        handler._notification_queue.enqueue_raw_message = AsyncMock()

        handler._check_circuit_breaker = MagicMock(return_value=True)
        handler._track_virtual_entry = MagicMock(return_value=18000.0)
        handler._execute_signal = AsyncMock()
        handler._queue_entry_notification = AsyncMock()

        signal = _long_signal()

        await handler.follower_execute(signal)

        # _execute_signal should be called on the streamlined path.
        handler._execute_signal.assert_awaited_once()
        # policy_decision arg should be None on the streamlined path.
        call_args = handler._execute_signal.call_args
        assert call_args.kwargs.get("policy_decision") is None or call_args[0][1] is None

    @pytest.mark.asyncio
    async def test_follower_execute_no_intraday_breach_check(self):
        """follower_execute does not accept or check intraday breach (moved to service loop)."""
        from pearlalgo.market_agent.signal_handler import SignalHandler
        import inspect

        # Verify follower_execute no longer accepts tv_paper_equity / tv_paper_tracker
        sig = inspect.signature(SignalHandler.follower_execute)
        param_names = list(sig.parameters.keys())
        assert "tv_paper_equity" not in param_names, "tv_paper_equity should not be a param"
        assert "tv_paper_tracker" not in param_names, "tv_paper_tracker should not be a param"
