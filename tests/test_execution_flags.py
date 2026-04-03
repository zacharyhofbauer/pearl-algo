"""Tests for execution_flags.check_execution_control_flags."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.market_agent.execution_flags import check_execution_control_flags


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flag(state_dir: Path, name: str, *, age_seconds: int = 0) -> Path:
    """Write a flag file with a timestamp embedded."""
    flag = state_dir / name
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    prefix = name.replace("_request.flag", "")
    flag.write_text(f"{prefix}_requested_at={ts.isoformat()}")
    return flag


def _make_service(tmp_path: Path, *, execution_adapter=None) -> MagicMock:
    """Build a minimal mock service object matching the attributes used by the module."""
    svc = MagicMock()
    svc.state_manager.state_dir = tmp_path

    # operator_handler — async methods
    svc.operator_handler.process_operator_requests = AsyncMock()
    svc.operator_handler.process_close_trade_requests = AsyncMock()
    svc.operator_handler.process_close_all_flag = AsyncMock()
    svc.operator_handler.process_grade_request = AsyncMock()

    # notification_queue
    svc.notification_queue.enqueue_raw_message = AsyncMock()

    # data fetcher
    svc.data_fetcher._last_market_data = {}

    # execution adapter
    svc.execution_adapter = execution_adapter

    # virtual trade closer
    svc._close_all_virtual_trades = AsyncMock(return_value=(0, []))

    # resume
    svc.resume = MagicMock()

    # state persistence helpers
    svc.mark_state_dirty = MagicMock()
    svc._save_state = MagicMock()

    return svc


def _make_adapter(*, armed: bool = False) -> MagicMock:
    """Build a mock execution adapter."""
    adapter = MagicMock()
    adapter.arm.return_value = True
    adapter.disarm.return_value = None

    # cancel_all / flatten_all_positions return lists of result objects
    adapter.cancel_all = AsyncMock(return_value=[])
    adapter.flatten_all_positions = AsyncMock(return_value=[])
    return adapter


# ---------------------------------------------------------------------------
# Resume flag
# ---------------------------------------------------------------------------

class TestResumeFlag:
    @pytest.mark.asyncio
    async def test_resume_flag_calls_resume(self, tmp_path):
        svc = _make_service(tmp_path)
        (tmp_path / "resume_request.flag").write_text("1")

        await check_execution_control_flags(svc)

        svc.resume.assert_called_once()
        assert not (tmp_path / "resume_request.flag").exists()

    @pytest.mark.asyncio
    async def test_no_resume_flag_no_call(self, tmp_path):
        svc = _make_service(tmp_path)

        await check_execution_control_flags(svc)

        svc.resume.assert_not_called()


# ---------------------------------------------------------------------------
# Stale flag cleanup
# ---------------------------------------------------------------------------

class TestStaleFlagCleanup:
    @pytest.mark.asyncio
    async def test_stale_flags_deleted(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)

        # Create flags older than 5 minutes
        _make_flag(tmp_path, "arm_request.flag", age_seconds=600)
        _make_flag(tmp_path, "disarm_request.flag", age_seconds=600)
        _make_flag(tmp_path, "kill_request.flag", age_seconds=600)

        await check_execution_control_flags(svc)

        # All stale flags should be cleaned up
        assert not (tmp_path / "arm_request.flag").exists()
        assert not (tmp_path / "disarm_request.flag").exists()
        assert not (tmp_path / "kill_request.flag").exists()

        # No arm/disarm/kill actions should have been taken
        adapter.arm.assert_not_called()
        adapter.disarm.assert_not_called()

    @pytest.mark.asyncio
    async def test_fresh_flags_not_deleted_early(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)

        _make_flag(tmp_path, "arm_request.flag", age_seconds=10)

        await check_execution_control_flags(svc)

        # Fresh flag should be processed (arm called), file removed by handler
        adapter.arm.assert_called_once()

    @pytest.mark.asyncio
    async def test_flag_without_timestamp_falls_back_to_mtime(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)

        flag = tmp_path / "arm_request.flag"
        flag.write_text("no timestamp here")
        # File was just created so mtime is fresh — should be processed
        await check_execution_control_flags(svc)

        adapter.arm.assert_called_once()

    @pytest.mark.asyncio
    async def test_flag_with_unparseable_content_treated_as_stale(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)

        flag = tmp_path / "arm_request.flag"
        flag.write_text("requested_at=NOT_A_DATE")

        await check_execution_control_flags(svc)

        # Unparseable → stale → deleted without action
        assert not flag.exists()
        adapter.arm.assert_not_called()


# ---------------------------------------------------------------------------
# No execution adapter
# ---------------------------------------------------------------------------

class TestNoExecutionAdapter:
    @pytest.mark.asyncio
    async def test_arm_flag_cleared_and_ignored(self, tmp_path):
        svc = _make_service(tmp_path, execution_adapter=None)
        _make_flag(tmp_path, "arm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        assert not (tmp_path / "arm_request.flag").exists()
        svc.notification_queue.enqueue_raw_message.assert_called()
        msg = svc.notification_queue.enqueue_raw_message.call_args_list[-1]
        assert "ARM IGNORED" in msg.args[0]

    @pytest.mark.asyncio
    async def test_disarm_flag_cleared_and_ignored(self, tmp_path):
        svc = _make_service(tmp_path, execution_adapter=None)
        _make_flag(tmp_path, "disarm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        assert not (tmp_path / "disarm_request.flag").exists()
        svc.notification_queue.enqueue_raw_message.assert_called()
        msg = svc.notification_queue.enqueue_raw_message.call_args_list[-1]
        assert "DISARM IGNORED" in msg.args[0]

    @pytest.mark.asyncio
    async def test_kill_flag_closes_virtual_trades_only(self, tmp_path):
        svc = _make_service(tmp_path, execution_adapter=None)
        svc._close_all_virtual_trades = AsyncMock(return_value=(3, []))
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        assert not (tmp_path / "kill_request.flag").exists()
        svc._close_all_virtual_trades.assert_awaited_once()
        # Should send a notification about kill with adapter disabled
        calls = svc.notification_queue.enqueue_raw_message.call_args_list
        assert any("KILL SWITCH EXECUTED" in c.args[0] for c in calls)
        assert any("DISABLED" in c.args[0] for c in calls)

    @pytest.mark.asyncio
    async def test_kill_with_virtual_close_error(self, tmp_path):
        svc = _make_service(tmp_path, execution_adapter=None)
        svc._close_all_virtual_trades = AsyncMock(side_effect=RuntimeError("db locked"))
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        # Flag still cleaned up despite error
        assert not (tmp_path / "kill_request.flag").exists()


# ---------------------------------------------------------------------------
# Kill switch (with execution adapter)
# ---------------------------------------------------------------------------

class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_kill_disarms_cancels_flattens(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        adapter.disarm.assert_called()
        adapter.cancel_all.assert_awaited_once()
        adapter.flatten_all_positions.assert_awaited_once()
        assert not (tmp_path / "kill_request.flag").exists()

    @pytest.mark.asyncio
    async def test_kill_also_removes_pending_disarm_flag(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)
        _make_flag(tmp_path, "disarm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        assert not (tmp_path / "kill_request.flag").exists()
        assert not (tmp_path / "disarm_request.flag").exists()

    @pytest.mark.asyncio
    async def test_kill_closes_virtual_trades(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        svc._close_all_virtual_trades = AsyncMock(return_value=(2, []))
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        svc._close_all_virtual_trades.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_kill_sends_notification(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        calls = svc.notification_queue.enqueue_raw_message.call_args_list
        assert any("KILL SWITCH EXECUTED" in c.args[0] for c in calls)

    @pytest.mark.asyncio
    async def test_kill_skips_arm_disarm_processing(self, tmp_path):
        """After kill, arm/disarm flags should not be processed."""
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)
        _make_flag(tmp_path, "arm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        # arm() should NOT be called — kill returns early
        adapter.arm.assert_not_called()

    @pytest.mark.asyncio
    async def test_kill_still_disarms_on_cancel_error(self, tmp_path):
        adapter = _make_adapter()
        adapter.cancel_all = AsyncMock(side_effect=RuntimeError("broker down"))
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        # disarm should be called at least twice: once in try, once in except
        assert adapter.disarm.call_count >= 2
        assert not (tmp_path / "kill_request.flag").exists()

    @pytest.mark.asyncio
    async def test_kill_with_cancel_and_flatten_results(self, tmp_path):
        adapter = _make_adapter()
        # Mock some cancel results
        ok_result = MagicMock(success=True, order_id="ORD-1", error_message=None)
        fail_result = MagicMock(success=False, order_id=None, error_message="timeout")
        adapter.cancel_all = AsyncMock(return_value=[ok_result, fail_result])
        adapter.flatten_all_positions = AsyncMock(return_value=[ok_result])

        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        calls = svc.notification_queue.enqueue_raw_message.call_args_list
        kill_msg = next(c.args[0] for c in calls if "KILL SWITCH" in c.args[0])
        assert "Cancelled Orders: `1`" in kill_msg
        assert "Flattened Positions: `1`" in kill_msg
        assert "Errors: 1" in kill_msg


# ---------------------------------------------------------------------------
# Disarm
# ---------------------------------------------------------------------------

class TestDisarm:
    @pytest.mark.asyncio
    async def test_disarm_calls_adapter_disarm(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "disarm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        adapter.disarm.assert_called_once()
        assert not (tmp_path / "disarm_request.flag").exists()

    @pytest.mark.asyncio
    async def test_disarm_persists_state(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "disarm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        svc.mark_state_dirty.assert_called_once()
        svc._save_state.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_disarm_sends_notification(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "disarm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        calls = svc.notification_queue.enqueue_raw_message.call_args_list
        assert any("Execution DISARMED" in c.args[0] for c in calls)

    @pytest.mark.asyncio
    async def test_disarm_skips_arm_processing(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "disarm_request.flag", age_seconds=5)
        _make_flag(tmp_path, "arm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        # disarm returns early before arm is checked
        adapter.arm.assert_not_called()


# ---------------------------------------------------------------------------
# Arm
# ---------------------------------------------------------------------------

class TestArm:
    @pytest.mark.asyncio
    async def test_arm_calls_adapter_arm(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "arm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        adapter.arm.assert_called_once()
        assert not (tmp_path / "arm_request.flag").exists()

    @pytest.mark.asyncio
    async def test_arm_persists_state(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "arm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        svc.mark_state_dirty.assert_called_once()
        svc._save_state.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_arm_success_sends_notification_with_mode(self, tmp_path):
        adapter = _make_adapter()
        adapter.arm.return_value = True
        svc = _make_service(tmp_path, execution_adapter=adapter)
        svc._execution_config.mode.value = "paper"
        _make_flag(tmp_path, "arm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        calls = svc.notification_queue.enqueue_raw_message.call_args_list
        arm_msg = next(c.args[0] for c in calls if "Execution ARMED" in c.args[0])
        assert "paper" in arm_msg

    @pytest.mark.asyncio
    async def test_arm_failure_sends_warning(self, tmp_path):
        adapter = _make_adapter()
        adapter.arm.return_value = False
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "arm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        calls = svc.notification_queue.enqueue_raw_message.call_args_list
        assert any("ARM FAILED" in c.args[0] for c in calls)
        # Flag should still be cleaned up
        assert not (tmp_path / "arm_request.flag").exists()


# ---------------------------------------------------------------------------
# Grade request
# ---------------------------------------------------------------------------

class TestGradeRequest:
    @pytest.mark.asyncio
    async def test_grade_request_processed(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        grade_file = tmp_path / "grade_request.json"
        grade_file.write_text('{"trade_id": "123", "grade": "A"}')

        await check_execution_control_flags(svc)

        svc.operator_handler.process_grade_request.assert_awaited_once_with(grade_file)


# ---------------------------------------------------------------------------
# Operator handler integration
# ---------------------------------------------------------------------------

class TestOperatorHandler:
    @pytest.mark.asyncio
    async def test_operator_requests_called(self, tmp_path):
        svc = _make_service(tmp_path)

        await check_execution_control_flags(svc)

        svc.operator_handler.process_operator_requests.assert_awaited_once_with(tmp_path)
        svc.operator_handler.process_close_trade_requests.assert_awaited_once_with(tmp_path)
        svc.operator_handler.process_close_all_flag.assert_awaited_once_with(tmp_path)

    @pytest.mark.asyncio
    async def test_operator_handler_errors_are_non_fatal(self, tmp_path):
        svc = _make_service(tmp_path)
        svc.operator_handler.process_operator_requests = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        svc.operator_handler.process_close_trade_requests = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        svc.operator_handler.process_close_all_flag = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        # Should not raise
        await check_execution_control_flags(svc)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_flags_no_side_effects(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)

        await check_execution_control_flags(svc)

        adapter.arm.assert_not_called()
        adapter.disarm.assert_not_called()
        adapter.cancel_all.assert_not_awaited()
        svc.notification_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_failure_is_non_fatal(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        svc.notification_queue.enqueue_raw_message = AsyncMock(
            side_effect=RuntimeError("telegram down")
        )
        _make_flag(tmp_path, "arm_request.flag", age_seconds=5)

        # Should not raise even though notification fails
        await check_execution_control_flags(svc)

        adapter.arm.assert_called_once()

    @pytest.mark.asyncio
    async def test_top_level_exception_caught(self, tmp_path):
        svc = MagicMock()
        svc.state_manager.state_dir = None  # Will cause AttributeError

        # Should not propagate
        await check_execution_control_flags(svc)

    @pytest.mark.asyncio
    async def test_priority_order_kill_before_disarm_before_arm(self, tmp_path):
        """Kill takes priority; disarm and arm are not processed."""
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)
        _make_flag(tmp_path, "disarm_request.flag", age_seconds=5)
        _make_flag(tmp_path, "arm_request.flag", age_seconds=5)

        await check_execution_control_flags(svc)

        # Kill processes, disarm+arm do not
        adapter.cancel_all.assert_awaited_once()
        adapter.arm.assert_not_called()
        # disarm IS called by the kill handler itself, but not by the disarm flag handler
        # kill also cleans up the disarm flag
        assert not (tmp_path / "disarm_request.flag").exists()

    @pytest.mark.asyncio
    async def test_last_market_data_non_dict_handled(self, tmp_path):
        adapter = _make_adapter()
        svc = _make_service(tmp_path, execution_adapter=adapter)
        svc.data_fetcher._last_market_data = "not a dict"
        _make_flag(tmp_path, "kill_request.flag", age_seconds=5)

        # Should not raise
        await check_execution_control_flags(svc)

        # Virtual trade close should get an empty dict
        call_kwargs = svc._close_all_virtual_trades.call_args
        assert call_kwargs.kwargs.get("market_data") == {} or call_kwargs[1].get("market_data") == {}
