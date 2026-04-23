"""Tests for gate_translators.execution_decision_to_gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from pearlalgo.market_agent.gate_decision import GateLayer, GateOutcome
from pearlalgo.market_agent.gate_translators import (
    _EXECUTION_GATE_NAMES,
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
