"""Tests for the gate_translators module.

Covers:
- ``execution_decision_to_gate``  — ExecutionDecision → GateDecision
- ``circuit_breaker_decision_to_gate`` — CircuitBreakerDecision → GateDecision
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from pearlalgo.market_agent.gate_decision import GateLayer, GateOutcome
from pearlalgo.market_agent.gate_translators import (
    _CIRCUIT_BREAKER_GATE_NAMES,
    _EXECUTION_GATE_NAMES,
    circuit_breaker_decision_to_gate,
    execution_decision_to_gate,
)


# A minimal stand-in for ExecutionDecision — the translator is duck-typed
# on `.execute` and `.reason`, so we don't need to import the real class.
@dataclass
class FakeDecision:
    execute: bool
    reason: Optional[str] = None


class TestExecutionDecisionAccepted:
    def test_accepted_with_passed_reason(self) -> None:
        d = execution_decision_to_gate(FakeDecision(execute=True, reason="preconditions_passed"))
        assert d.outcome == GateOutcome.ACCEPTED
        assert d.gate is None
        assert d.layer == GateLayer.EXECUTION_ADAPTER
        assert d.message == "preconditions_passed"

    def test_accepted_with_empty_reason(self) -> None:
        d = execution_decision_to_gate(FakeDecision(execute=True, reason=""))
        assert d.outcome == GateOutcome.ACCEPTED
        assert d.message == "all preconditions passed"

    def test_accepted_with_none_reason(self) -> None:
        d = execution_decision_to_gate(FakeDecision(execute=True, reason=None))
        assert d.outcome == GateOutcome.ACCEPTED


class TestExecutionDecisionRejected:
    """Cover every reason string the real ExecutionAdapterBase emits.

    Source: src/pearlalgo/execution/base.py check_preconditions()
    """

    @pytest.mark.parametrize(
        "reason,expected_gate,expected_raw_detail",
        [
            # Check 1: execution disabled
            ("execution_disabled", "execution_disabled", None),
            # Check 2: not armed
            ("not_armed", "not_armed", None),
            # Check 3: symbol whitelist
            ("symbol_not_whitelisted:ES", "symbol_not_whitelisted", "ES"),
            # Check 4: max positions
            ("max_positions_reached:5/5", "max_positions_reached", "5/5"),
            # Check 5: daily order cap
            ("max_daily_orders_reached:80/80", "max_daily_orders_reached", "80/80"),
            # Check 6: daily loss limit
            ("daily_loss_limit_hit:-500.00", "daily_loss_limit_hit", "-500.00"),
            # Check 7: cooldown
            (
                "cooldown_active:pearlbot_pinescript:30s_remaining",
                "cooldown_active",
                "pearlbot_pinescript:30s_remaining",
            ),
            # Check 8: invalid direction
            ("invalid_direction:flat", "invalid_direction", "flat"),
            # Check 9a: invalid prices (non-numeric)
            ("invalid_prices:non_numeric", "invalid_prices", "non_numeric"),
            # Check 9b: invalid prices (non-positive)
            (
                "invalid_prices:non_positive:entry=0.0,sl=0.0,tp=0.0",
                "invalid_prices",
                "non_positive:entry=0.0,sl=0.0,tp=0.0",
            ),
            # Check 10a: bracket geometry long
            (
                "invalid_bracket_geometry:long:sl=100,entry=95,tp=110",
                "invalid_bracket_geometry",
                "long:sl=100,entry=95,tp=110",
            ),
            # Check 10b: bracket geometry short
            (
                "invalid_bracket_geometry:short:tp=120,entry=100,sl=90",
                "invalid_bracket_geometry",
                "short:tp=120,entry=100,sl=90",
            ),
            # Check 11a: invalid position size (non-integer)
            ("invalid_position_size:non_integer", "invalid_position_size", "non_integer"),
            # Check 11b: invalid position size (non-positive)
            ("invalid_position_size:non_positive:-1", "invalid_position_size", "non_positive:-1"),
        ],
    )
    def test_rejection_maps_to_canonical_gate(
        self, reason: str, expected_gate: str, expected_raw_detail: Optional[str]
    ) -> None:
        d = execution_decision_to_gate(FakeDecision(execute=False, reason=reason))
        assert d.outcome == GateOutcome.REJECTED
        assert d.layer == GateLayer.EXECUTION_ADAPTER
        assert d.gate == expected_gate
        if expected_raw_detail is None:
            assert "raw_detail" not in d.actual
        else:
            assert d.actual["raw_detail"] == expected_raw_detail
        assert "unknown_gate" not in d.actual
        assert d.message == reason

    def test_empty_reason_maps_to_unknown(self) -> None:
        d = execution_decision_to_gate(FakeDecision(execute=False, reason=""))
        assert d.outcome == GateOutcome.REJECTED
        assert d.gate == "unknown"
        # empty reason is not unknown_gate — it's genuinely absent
        assert "unknown_gate" not in d.actual

    def test_unknown_gate_name_is_tagged(self) -> None:
        d = execution_decision_to_gate(
            FakeDecision(execute=False, reason="martian_pacing_violation:7")
        )
        assert d.outcome == GateOutcome.REJECTED
        assert d.gate == "martian_pacing_violation"
        assert d.actual["unknown_gate"] is True
        assert d.actual["raw_detail"] == "7"

    def test_every_known_gate_in_base_py_is_covered(self) -> None:
        # Drift guard: if someone adds a new gate string to
        # ExecutionAdapterBase.check_preconditions, this test doesn't
        # automatically catch it — but _EXECUTION_GATE_NAMES should be
        # updated in the same PR. This test just asserts the canonical
        # set is stable.
        expected = {
            "execution_disabled",
            "not_armed",
            "symbol_not_whitelisted",
            "max_positions_reached",
            "max_daily_orders_reached",
            "daily_loss_limit_hit",
            "cooldown_active",
            "invalid_direction",
            "invalid_prices",
            "invalid_bracket_geometry",
            "invalid_position_size",
        }
        assert _EXECUTION_GATE_NAMES == expected


class TestDuckTyping:
    """The translator only reads .execute and .reason — any object works."""

    def test_accepts_namespace_object(self) -> None:
        from types import SimpleNamespace
        d = execution_decision_to_gate(
            SimpleNamespace(execute=False, reason="not_armed")
        )
        assert d.gate == "not_armed"

    def test_missing_attributes_default_safely(self) -> None:
        # Object with no .execute and no .reason — translator must not crash
        class Empty:
            pass
        d = execution_decision_to_gate(Empty())
        assert d.outcome == GateOutcome.REJECTED  # .execute defaults False
        assert d.gate == "unknown"


# ===========================================================================
# CircuitBreakerDecision translator
# ===========================================================================


@dataclass
class FakeCbDecision:
    allowed: bool
    reason: str = ""
    risk_scale: float = 1.0
    details: Dict[str, Any] = field(default_factory=dict)


class TestCircuitBreakerAccepted:
    def test_fully_allowed_maps_to_accepted(self) -> None:
        d = circuit_breaker_decision_to_gate(
            FakeCbDecision(allowed=True, reason="passed_all_checks", risk_scale=1.0)
        )
        assert d.outcome == GateOutcome.ACCEPTED
        assert d.layer == GateLayer.CIRCUIT_BREAKER
        assert d.gate is None

    def test_allowed_with_risk_scale_1_is_accepted(self) -> None:
        # Edge case: allowed + 1.0 — no scaling applied
        d = circuit_breaker_decision_to_gate(
            FakeCbDecision(allowed=True, reason="consecutive_losses_ok", risk_scale=1.0)
        )
        assert d.outcome == GateOutcome.ACCEPTED

    def test_allowed_empty_reason_defaults_message(self) -> None:
        d = circuit_breaker_decision_to_gate(FakeCbDecision(allowed=True, reason=""))
        assert d.outcome == GateOutcome.ACCEPTED
        assert "checks passed" in d.message.lower()


class TestCircuitBreakerRejected:
    @pytest.mark.parametrize(
        "reason,expected_gate,expected_detail",
        [
            ("in_cooldown:session_profit_lock", "in_cooldown", "session_profit_lock"),
            ("consecutive_losses", "consecutive_losses", None),
            ("tiered_loss:5:halt", "tiered_loss", "5:halt"),
            ("session_drawdown", "session_drawdown", None),
            ("daily_drawdown", "daily_drawdown", None),
            ("daily_profit_cap", "daily_profit_cap", None),
            ("rolling_win_rate", "rolling_win_rate", None),
            ("position_limits_clustering", "position_limits_clustering", None),
            ("direction_gating", "direction_gating", None),
            ("regime_avoidance", "regime_avoidance", None),
            ("trigger_filters", "trigger_filters", None),
            ("volatility_filter", "volatility_filter", None),
            ("tv_paper_eval_gate", "tv_paper_eval_gate", None),
            ("risk_scale_zero", "risk_scale_zero", None),
        ],
    )
    def test_rejection_maps_to_canonical_gate(
        self, reason: str, expected_gate: str, expected_detail: Optional[str]
    ) -> None:
        d = circuit_breaker_decision_to_gate(FakeCbDecision(allowed=False, reason=reason))
        assert d.outcome == GateOutcome.REJECTED
        assert d.layer == GateLayer.CIRCUIT_BREAKER
        assert d.gate == expected_gate
        if expected_detail is None:
            assert "raw_detail" not in d.actual
        else:
            assert d.actual["raw_detail"] == expected_detail
        assert "unknown_gate" not in d.actual

    def test_unknown_reason_is_tagged(self) -> None:
        d = circuit_breaker_decision_to_gate(
            FakeCbDecision(allowed=False, reason="moon_phase_blocked:full")
        )
        assert d.gate == "moon_phase_blocked"
        assert d.actual["unknown_gate"] is True


class TestCircuitBreakerRiskScaled:
    def test_risk_scaled_extracts_dominant_gate_from_details(self) -> None:
        d = circuit_breaker_decision_to_gate(
            FakeCbDecision(
                allowed=True,
                reason="passed_all_checks",
                risk_scale=0.5,
                details={"scale_reasons": ["tod:0.50", "equity_curve:0.75"]},
            )
        )
        assert d.outcome == GateOutcome.RISK_SCALED
        assert d.layer == GateLayer.CIRCUIT_BREAKER
        assert d.gate == "tod"
        assert d.risk_scale_applied == 0.5
        assert d.actual["scale_reasons"] == ["tod:0.50", "equity_curve:0.75"]

    def test_risk_scaled_with_no_scale_reasons_uses_fallback(self) -> None:
        d = circuit_breaker_decision_to_gate(
            FakeCbDecision(
                allowed=True,
                reason="passed_all_checks",
                risk_scale=0.75,
                details={},
            )
        )
        assert d.outcome == GateOutcome.RISK_SCALED
        assert d.gate == "unknown_scaler"

    def test_risk_scale_zero_with_allowed_false_is_rejected(self) -> None:
        # CB returns allowed=False + risk_scale=0 when cumulative scaling zeroes out
        d = circuit_breaker_decision_to_gate(
            FakeCbDecision(
                allowed=False,
                reason="risk_scale_zero",
                risk_scale=0.0,
                details={"scale_reasons": ["tod:0.0"]},
            )
        )
        assert d.outcome == GateOutcome.REJECTED
        assert d.gate == "risk_scale_zero"


class TestCircuitBreakerDuckTyping:
    def test_missing_attrs_default_safely(self) -> None:
        class Empty:
            pass
        d = circuit_breaker_decision_to_gate(Empty())
        # allowed defaults False
        assert d.outcome == GateOutcome.REJECTED
        assert d.gate == "unknown"

    def test_nondict_details_ignored(self) -> None:
        d = circuit_breaker_decision_to_gate(
            FakeCbDecision(allowed=True, risk_scale=0.5, details="oops not a dict")  # type: ignore[arg-type]
        )
        assert d.outcome == GateOutcome.RISK_SCALED
        assert d.gate == "unknown_scaler"

    def test_non_numeric_risk_scale_defaults_to_1(self) -> None:
        class BadScale:
            allowed = True
            reason = "passed_all_checks"
            risk_scale = "nonsense"
            details: Dict[str, Any] = {}
        d = circuit_breaker_decision_to_gate(BadScale())
        assert d.outcome == GateOutcome.ACCEPTED


class TestCircuitBreakerGateNamesComplete:
    def test_all_known_gates_present(self) -> None:
        expected = {
            "in_cooldown",
            "consecutive_losses",
            "tiered_loss",
            "session_drawdown",
            "daily_drawdown",
            "daily_profit_cap",
            "rolling_win_rate",
            "position_limits_clustering",
            "direction_gating",
            "regime_avoidance",
            "trigger_filters",
            "volatility_filter",
            "tv_paper_eval_gate",
            "equity_curve",
            "tod",
            "tod_risk_scaling",
            "volatility",
            "volatility_risk_scaling",
            "risk_scale_zero",
        }
        assert _CIRCUIT_BREAKER_GATE_NAMES == expected


# ===========================================================================
# SignalHandler._audit_reject helper
# ===========================================================================


class TestSignalHandlerAuditReject:
    """Integration-style tests: SignalHandler records rejections to the
    SignalAuditLogger for its gate sites (whitelist + entry price)."""

    def _make_handler_with_logger(self, tmp_path):
        from unittest.mock import MagicMock
        from pearlalgo.market_agent.signal_audit_logger import SignalAuditLogger
        from pearlalgo.market_agent.signal_handler import SignalHandler

        logger = SignalAuditLogger(tmp_path, enabled=True)
        handler = SignalHandler(
            state_manager=MagicMock(),
            performance_tracker=MagicMock(),
            notification_queue=MagicMock(),
            order_manager=MagicMock(),
            signal_audit_logger=logger,
        )
        return handler, logger

    def _drain_and_read(self, logger, tmp_path):
        import time
        import json
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if logger._queue.empty():
                time.sleep(0.05)
                break
            time.sleep(0.02)
        logger.shutdown()
        path = tmp_path / "signal_audit.jsonl"
        if not path.exists():
            return []
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_audit_reject_emits_record(self, tmp_path):
        handler, logger = self._make_handler_with_logger(tmp_path)
        handler._audit_reject(
            {"signal_id": "s1", "direction": "long", "confidence": 0.5, "type": "foo"},
            "signal_type_whitelist",
            actual={"signal_type": "foo"},
            message="not in whitelist",
        )
        records = self._drain_and_read(logger, tmp_path)
        assert len(records) == 1
        r = records[0]
        assert r["outcome"] == "rejected"
        assert r["layer"] == "signal_handler"
        assert r["gate"] == "signal_type_whitelist"
        assert r["actual"]["signal_type"] == "foo"
        assert r["signal_id"] == "s1"

    def test_audit_reject_with_no_logger_is_noop(self):
        # No logger attached — must not raise
        from unittest.mock import MagicMock
        from pearlalgo.market_agent.signal_handler import SignalHandler

        handler = SignalHandler(
            state_manager=MagicMock(),
            performance_tracker=MagicMock(),
            notification_queue=MagicMock(),
            order_manager=MagicMock(),
            # no signal_audit_logger
        )
        handler._audit_reject({"signal_id": "x"}, "any_gate")
        # if we got here without exception we're good
