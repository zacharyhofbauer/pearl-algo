"""Tests for ExecutionOrchestrator -- Issue 13."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from pearlalgo.market_agent.execution_orchestrator import ExecutionOrchestrator


@pytest.fixture
def mock_vtm():
    vtm = MagicMock()
    vtm.process_exits = MagicMock()
    return vtm


@pytest.fixture
def mock_order_mgr():
    om = MagicMock()
    om.compute_base_position_size = MagicMock(return_value=2)
    return om


@pytest.fixture
def mock_state_mgr():
    sm = MagicMock()
    sm.get_recent_signals = MagicMock(return_value=[])
    sm.load_state = MagicMock(return_value={})
    sm.update_state = MagicMock()
    return sm


@pytest.fixture
def orch(mock_vtm, mock_order_mgr, mock_state_mgr):
    return ExecutionOrchestrator(
        virtual_trade_manager=mock_vtm,
        order_manager=mock_order_mgr,
        state_manager=mock_state_mgr,
    )


class TestProcessVirtualExits:
    def test_delegates_to_vtm(self, orch, mock_vtm):
        orch.process_virtual_exits({"close": 17500.0})
        mock_vtm.process_exits.assert_called_once_with({"close": 17500.0})

    def test_swallows_exception(self, orch, mock_vtm):
        mock_vtm.process_exits.side_effect = RuntimeError("boom")
        orch.process_virtual_exits({"close": 17500.0})  # should NOT raise


class TestComputePositionSize:
    def test_delegates_to_order_manager(self, orch, mock_order_mgr):
        sig = {"type": "long", "confidence": 0.85}
        assert orch.compute_position_size(sig) == 2
        mock_order_mgr.compute_base_position_size.assert_called_once_with(sig)

    def test_returns_custom_size(self, orch, mock_order_mgr):
        mock_order_mgr.compute_base_position_size.return_value = 5
        assert orch.compute_position_size({"type": "short"}) == 5


class TestExecutionStatus:
    def test_no_adapter(self, orch):
        import asyncio
        r = asyncio.get_event_loop().run_until_complete(orch.get_execution_status())
        assert r == {"enabled": False}

    def test_is_execution_enabled_false(self, orch):
        assert orch.is_execution_enabled is False

    def test_is_execution_enabled_true(self, mock_vtm, mock_order_mgr, mock_state_mgr):
        eo = ExecutionOrchestrator(
            virtual_trade_manager=mock_vtm,
            order_manager=mock_order_mgr,
            state_manager=mock_state_mgr,
            execution_adapter=MagicMock(),
        )
        assert eo.is_execution_enabled is True


class TestGetActiveVirtualTrades:
    def test_returns_entered_only(self, orch, mock_state_mgr):
        mock_state_mgr.get_recent_signals.return_value = [
            {"signal_id": "s1", "status": "entered"},
            {"signal_id": "s2", "status": "exited"},
            {"signal_id": "s3", "status": "entered"},
        ]
        result = orch.get_active_virtual_trades()
        assert len(result) == 2

    def test_empty_on_error(self, orch, mock_state_mgr):
        mock_state_mgr.get_recent_signals.side_effect = RuntimeError("disk")
        assert orch.get_active_virtual_trades() == []


class TestAutoFlatDue:
    def _cfg(self, **kw):
        base = {
            "enabled": True, "daily_enabled": True, "daily_time": (16, 55),
            "friday_enabled": True, "friday_time": (16, 55),
            "weekend_enabled": True, "timezone": "America/New_York",
        }
        base.update(kw)
        return base

    def test_no_trigger_during_trading(self, orch):
        now = datetime(2026, 2, 9, 14, 0, tzinfo=timezone.utc)
        assert orch.auto_flat_due(now, market_open=True, auto_flat_cfg=self._cfg(), last_dates={}) is None

    def test_daily_trigger(self, orch):
        now = datetime(2026, 2, 9, 21, 56, tzinfo=timezone.utc)
        assert orch.auto_flat_due(now, market_open=True, auto_flat_cfg=self._cfg(), last_dates={}) == "daily_auto_flat"

    def test_daily_no_repeat(self, orch):
        now = datetime(2026, 2, 9, 21, 56, tzinfo=timezone.utc)
        et_date = now.astimezone(ZoneInfo("America/New_York")).date()
        assert orch.auto_flat_due(now, market_open=True, auto_flat_cfg=self._cfg(), last_dates={"daily_auto_flat": et_date}) is None

    def test_disabled(self, orch):
        now = datetime(2026, 2, 9, 21, 56, tzinfo=timezone.utc)
        assert orch.auto_flat_due(now, market_open=True, auto_flat_cfg={"enabled": False}, last_dates={}) is None


class TestCloseRequestHelpers:
    def test_get_close_signals(self, orch, mock_state_mgr):
        mock_state_mgr.load_state.return_value = {"close_signals_requested": ["s1", "s2"]}
        assert orch.get_close_signals_requested() == ["s1", "s2"]

    def test_get_close_signals_on_error(self, orch, mock_state_mgr):
        mock_state_mgr.load_state.side_effect = RuntimeError("disk")
        assert orch.get_close_signals_requested() == []

    def test_clear_close_signals(self, orch, mock_state_mgr):
        orch.clear_close_signals_requested()
        mock_state_mgr.save_state.assert_called_once()

    def test_clear_close_all_flag(self, orch, mock_state_mgr):
        orch.clear_close_all_flag()
        mock_state_mgr.save_state.assert_called_once()
