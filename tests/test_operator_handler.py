"""
Tests for OperatorHandler - Process operator requests and grade commands.

Tests cover:
- process_grade_request: valid grade, invalid JSON, already-exited signal,
  force mode, feedback file update, cleanup of request file
- process_operator_requests: accept feedback, dismiss feedback, invalid action,
  missing fields, empty directory, file cleanup
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pearlalgo.market_agent.operator_handler import OperatorHandler
from pearlalgo.market_agent.notification_queue import Priority


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_deps(tmp_path):
    """Create a full set of mock dependencies for OperatorHandler."""
    state_manager = MagicMock()
    state_manager.state_dir = tmp_path
    state_manager.signals_file = tmp_path / "signals.jsonl"

    notification_queue = AsyncMock()
    notification_queue.enqueue_raw_message = AsyncMock()

    shadow_tracker = MagicMock()
    shadow_tracker.mark_followed = MagicMock()
    shadow_tracker.mark_dismissed = MagicMock()

    bandit_policy = MagicMock()
    bandit_policy.record_outcome = MagicMock()

    return {
        "state_manager": state_manager,
        "notification_queue": notification_queue,
        "shadow_tracker": shadow_tracker,
        "bandit_policy": bandit_policy,
        "get_status_snapshot": lambda: {"daily_pnl": 100, "wins_today": 3, "losses_today": 1},
    }


@pytest.fixture
def handler(mock_deps):
    """Create an OperatorHandler with default dependencies."""
    return OperatorHandler(**mock_deps)


@pytest.fixture
def handler_no_bandit(mock_deps):
    """Create an OperatorHandler without a bandit policy."""
    mock_deps["bandit_policy"] = None
    return OperatorHandler(**mock_deps)


def _write_grade_file(tmp_path: Path, data: dict) -> Path:
    """Write a grade request JSON file and return its path."""
    grade_file = tmp_path / "grade_request.json"
    grade_file.write_text(json.dumps(data), encoding="utf-8")
    return grade_file


def _write_signals_file(signals_file: Path, records: list) -> None:
    """Write signal records as JSONL."""
    lines = [json.dumps(r) for r in records]
    signals_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_feedback_file(state_dir: Path, records: list) -> Path:
    """Write a feedback.jsonl file."""
    fb_file = state_dir / "feedback.jsonl"
    lines = [json.dumps(r) for r in records]
    fb_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return fb_file


# =========================================================================
# process_grade_request
# =========================================================================


class TestProcessGradeRequest:
    """Tests for process_grade_request()."""

    @pytest.mark.asyncio
    async def test_valid_grade_applies_to_learning(self, handler, tmp_path):
        """Should record outcome with bandit_policy for a valid grade."""
        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-001",
            "signal_type": "momentum",
            "is_win": True,
            "pnl": 250.0,
        })

        await handler.process_grade_request(grade_file)

        handler.bandit_policy.record_outcome.assert_called_once_with(
            signal_id="sig-001",
            signal_type="momentum",
            is_win=True,
            pnl=250.0,
        )

    @pytest.mark.asyncio
    async def test_sends_applied_notification(self, handler, tmp_path):
        """Should send 'Grade Applied' notification when learning is updated."""
        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-001",
            "signal_type": "momentum",
            "is_win": True,
        })

        await handler.process_grade_request(grade_file)

        handler.notification_queue.enqueue_raw_message.assert_awaited_once()
        call_args = handler.notification_queue.enqueue_raw_message.call_args
        assert "Grade Applied" in call_args[0][0] or "Grade Applied" in str(call_args)

    @pytest.mark.asyncio
    async def test_cleanup_removes_grade_file(self, handler, tmp_path):
        """Should always remove the grade file, even on success."""
        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-001",
            "signal_type": "test",
            "is_win": False,
        })
        assert grade_file.exists()

        await handler.process_grade_request(grade_file)

        assert not grade_file.exists()

    @pytest.mark.asyncio
    async def test_cleanup_on_invalid_json(self, handler, tmp_path):
        """Should clean up the file even when JSON is invalid."""
        grade_file = tmp_path / "grade_request.json"
        grade_file.write_text("not valid json!!!", encoding="utf-8")

        await handler.process_grade_request(grade_file)

        assert not grade_file.exists()

    @pytest.mark.asyncio
    async def test_already_exited_skips_learning(self, handler, tmp_path):
        """Should not apply to learning if signal is already exited and force=False."""
        _write_signals_file(handler.state_manager.signals_file, [
            {"signal_id": "sig-001", "status": "exited"},
        ])
        handler.state_manager.get_recent_signals = MagicMock(return_value=[
            {"signal_id": "sig-001", "status": "exited"},
        ])

        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-001",
            "signal_type": "momentum",
            "is_win": True,
            "force": False,
        })

        await handler.process_grade_request(grade_file)

        handler.bandit_policy.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_exited_sends_logged_notification(self, handler, tmp_path):
        """Should send 'Grade Logged' when skipping an already-exited signal."""
        _write_signals_file(handler.state_manager.signals_file, [
            {"signal_id": "sig-001", "status": "exited"},
        ])
        handler.state_manager.get_recent_signals = MagicMock(return_value=[
            {"signal_id": "sig-001", "status": "exited"},
        ])

        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-001",
            "signal_type": "momentum",
            "is_win": True,
            "force": False,
        })

        await handler.process_grade_request(grade_file)

        handler.notification_queue.enqueue_raw_message.assert_awaited_once()
        call_args = handler.notification_queue.enqueue_raw_message.call_args
        assert "Grade Logged" in call_args[0][0] or "Grade Logged" in str(call_args)

    @pytest.mark.asyncio
    async def test_force_applies_even_if_exited(self, handler, tmp_path):
        """Should apply to learning when force=True, even for exited signals."""
        _write_signals_file(handler.state_manager.signals_file, [
            {"signal_id": "sig-001", "status": "exited"},
        ])

        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-001",
            "signal_type": "momentum",
            "is_win": False,
            "pnl": -100.0,
            "force": True,
        })

        await handler.process_grade_request(grade_file)

        handler.bandit_policy.record_outcome.assert_called_once_with(
            signal_id="sig-001",
            signal_type="momentum",
            is_win=False,
            pnl=-100.0,
        )

    @pytest.mark.asyncio
    async def test_no_bandit_policy_still_sends_not_applied(self, handler_no_bandit, tmp_path):
        """Should send logged notification when bandit_policy is None."""
        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-001",
            "signal_type": "test",
            "is_win": True,
        })

        await handler_no_bandit.process_grade_request(grade_file)

        handler_no_bandit.notification_queue.enqueue_raw_message.assert_awaited_once()
        call_args = handler_no_bandit.notification_queue.enqueue_raw_message.call_args
        assert "Grade Logged" in call_args[0][0] or "Grade Logged" in str(call_args)

    @pytest.mark.asyncio
    async def test_feedback_file_update(self, handler, tmp_path):
        """Should update feedback.jsonl with applied_to_learning flag."""
        fb_file = _write_feedback_file(tmp_path, [
            {"signal_id": "sig-001", "feedback": "good"},
            {"signal_id": "sig-002", "feedback": "bad"},
        ])

        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-001",
            "signal_type": "momentum",
            "is_win": True,
        })

        await handler.process_grade_request(grade_file)

        # Read back the feedback file
        lines = fb_file.read_text(encoding="utf-8").strip().split("\n")
        records = [json.loads(l) for l in lines if l.strip()]

        updated = [r for r in records if r.get("signal_id") == "sig-001"]
        assert len(updated) == 1
        assert updated[0]["applied_to_learning"] is True
        assert "applied_at" in updated[0]

    @pytest.mark.asyncio
    async def test_default_values_for_missing_fields(self, handler, tmp_path):
        """Should use defaults when fields are missing in the grade request."""
        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-partial",
        })

        await handler.process_grade_request(grade_file)

        handler.bandit_policy.record_outcome.assert_called_once_with(
            signal_id="sig-partial",
            signal_type="unknown",
            is_win=False,
            pnl=0.0,
        )

    @pytest.mark.asyncio
    async def test_signal_not_found_in_signals_file(self, handler, tmp_path):
        """Should treat unknown signals as not-exited and apply grade."""
        _write_signals_file(handler.state_manager.signals_file, [
            {"signal_id": "sig-other", "status": "active"},
        ])

        grade_file = _write_grade_file(tmp_path, {
            "signal_id": "sig-not-in-file",
            "signal_type": "reversal",
            "is_win": True,
        })

        await handler.process_grade_request(grade_file)

        handler.bandit_policy.record_outcome.assert_called_once()


# =========================================================================
# process_operator_requests
# =========================================================================


class TestProcessOperatorRequests:
    """Tests for process_operator_requests()."""

    @pytest.mark.asyncio
    async def test_noop_when_dir_does_not_exist(self, handler, tmp_path):
        """Should return silently if operator_requests dir doesn't exist."""
        await handler.process_operator_requests(tmp_path)
        handler.shadow_tracker.mark_followed.assert_not_called()
        handler.shadow_tracker.mark_dismissed.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_dir_is_empty(self, handler, tmp_path):
        """Should return silently if no feedback files exist."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        await handler.process_operator_requests(tmp_path)
        handler.shadow_tracker.mark_followed.assert_not_called()
        handler.shadow_tracker.mark_dismissed.assert_not_called()

    @pytest.mark.asyncio
    async def test_accept_feedback(self, handler, tmp_path):
        """Should call mark_followed for accept action."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        fb = {
            "type": "pearl_suggestion_feedback",
            "action": "accept",
            "suggestion_id": "sug-001",
        }
        (req_dir / "pearl_suggestion_feedback_001.json").write_text(json.dumps(fb))

        await handler.process_operator_requests(tmp_path)

        handler.shadow_tracker.mark_followed.assert_called_once()
        call_args = handler.shadow_tracker.mark_followed.call_args
        assert call_args[0][0] == "sug-001"

    @pytest.mark.asyncio
    async def test_dismiss_feedback(self, handler, tmp_path):
        """Should call mark_dismissed for dismiss action."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        fb = {
            "type": "pearl_suggestion_feedback",
            "action": "dismiss",
            "suggestion_id": "sug-002",
        }
        (req_dir / "pearl_suggestion_feedback_002.json").write_text(json.dumps(fb))

        await handler.process_operator_requests(tmp_path)

        handler.shadow_tracker.mark_dismissed.assert_called_once()
        call_args = handler.shadow_tracker.mark_dismissed.call_args
        assert call_args[0][0] == "sug-002"

    @pytest.mark.asyncio
    async def test_invalid_action_is_ignored(self, handler, tmp_path):
        """Should log warning for unknown actions without crashing."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        fb = {
            "type": "pearl_suggestion_feedback",
            "action": "upvote",
            "suggestion_id": "sug-003",
        }
        (req_dir / "pearl_suggestion_feedback_003.json").write_text(json.dumps(fb))

        await handler.process_operator_requests(tmp_path)

        handler.shadow_tracker.mark_followed.assert_not_called()
        handler.shadow_tracker.mark_dismissed.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_fields_skipped(self, handler, tmp_path):
        """Should skip records missing action or suggestion_id."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        # Missing suggestion_id
        fb1 = {"type": "pearl_suggestion_feedback", "action": "accept"}
        (req_dir / "pearl_suggestion_feedback_001.json").write_text(json.dumps(fb1))

        # Missing action
        fb2 = {"type": "pearl_suggestion_feedback", "suggestion_id": "sug-004"}
        (req_dir / "pearl_suggestion_feedback_002.json").write_text(json.dumps(fb2))

        await handler.process_operator_requests(tmp_path)

        handler.shadow_tracker.mark_followed.assert_not_called()
        handler.shadow_tracker.mark_dismissed.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_type_skipped(self, handler, tmp_path):
        """Should skip records with wrong type field."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        fb = {
            "type": "some_other_type",
            "action": "accept",
            "suggestion_id": "sug-005",
        }
        (req_dir / "pearl_suggestion_feedback_005.json").write_text(json.dumps(fb))

        await handler.process_operator_requests(tmp_path)

        handler.shadow_tracker.mark_followed.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_cleanup_after_processing(self, handler, tmp_path):
        """Should delete each feedback file after processing it."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        fb = {
            "type": "pearl_suggestion_feedback",
            "action": "accept",
            "suggestion_id": "sug-006",
        }
        fp = req_dir / "pearl_suggestion_feedback_006.json"
        fp.write_text(json.dumps(fb))

        assert fp.exists()
        await handler.process_operator_requests(tmp_path)
        assert not fp.exists()

    @pytest.mark.asyncio
    async def test_file_cleanup_even_on_error(self, handler, tmp_path):
        """Should still clean up file when mark_followed raises."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        handler.shadow_tracker.mark_followed.side_effect = RuntimeError("tracker error")

        fb = {
            "type": "pearl_suggestion_feedback",
            "action": "accept",
            "suggestion_id": "sug-err",
        }
        fp = req_dir / "pearl_suggestion_feedback_err.json"
        fp.write_text(json.dumps(fb))

        await handler.process_operator_requests(tmp_path)

        # File should still be cleaned up despite the error
        assert not fp.exists()

    @pytest.mark.asyncio
    async def test_multiple_files_processed(self, handler, tmp_path):
        """Should process multiple feedback files in one call."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        for i in range(5):
            fb = {
                "type": "pearl_suggestion_feedback",
                "action": "accept" if i % 2 == 0 else "dismiss",
                "suggestion_id": f"sug-batch-{i}",
            }
            (req_dir / f"pearl_suggestion_feedback_{i:03d}.json").write_text(json.dumps(fb))

        await handler.process_operator_requests(tmp_path)

        # 3 accepts (0,2,4), 2 dismisses (1,3)
        assert handler.shadow_tracker.mark_followed.call_count == 3
        assert handler.shadow_tracker.mark_dismissed.call_count == 2

    @pytest.mark.asyncio
    async def test_shadow_context_includes_snapshot(self, handler, tmp_path):
        """Should pass daily snapshot context to shadow_tracker calls."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        fb = {
            "type": "pearl_suggestion_feedback",
            "action": "accept",
            "suggestion_id": "sug-ctx",
        }
        (req_dir / "pearl_suggestion_feedback_ctx.json").write_text(json.dumps(fb))

        await handler.process_operator_requests(tmp_path)

        call_args = handler.shadow_tracker.mark_followed.call_args
        context = call_args[0][1]
        assert "daily_pnl" in context
        assert context["daily_pnl"] == 100

    @pytest.mark.asyncio
    async def test_non_matching_filenames_ignored(self, handler, tmp_path):
        """Should only process files matching pearl_suggestion_feedback_*.json."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        # This file doesn't match the glob
        fb = {
            "type": "pearl_suggestion_feedback",
            "action": "accept",
            "suggestion_id": "sug-bad-name",
        }
        (req_dir / "other_request.json").write_text(json.dumps(fb))

        await handler.process_operator_requests(tmp_path)

        handler.shadow_tracker.mark_followed.assert_not_called()

    @pytest.mark.asyncio
    async def test_status_snapshot_failure_uses_empty(self, mock_deps, tmp_path):
        """Should use empty context if _get_status_snapshot raises."""
        mock_deps["get_status_snapshot"] = MagicMock(side_effect=RuntimeError("snap fail"))
        h = OperatorHandler(**mock_deps)

        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        fb = {
            "type": "pearl_suggestion_feedback",
            "action": "accept",
            "suggestion_id": "sug-snap-fail",
        }
        (req_dir / "pearl_suggestion_feedback_snap.json").write_text(json.dumps(fb))

        await h.process_operator_requests(tmp_path)

        # Should still succeed with empty context
        h.shadow_tracker.mark_followed.assert_called_once()
        call_context = h.shadow_tracker.mark_followed.call_args[0][1]
        assert call_context["daily_pnl"] == 0
