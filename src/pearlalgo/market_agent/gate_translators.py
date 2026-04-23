"""Translate layer-specific decision objects into canonical GateDecisions.

Each gate layer (execution_adapter, circuit_breaker, signal_handler,
protection_guard) has its own verdict type. These translators turn those
verdicts into the uniform ``GateDecision`` used by the signal audit log,
so downstream tooling (CLI, webapp, Phase 2 archive) reasons about a
single shape.

Translators are intentionally narrow — they map reason strings to gate
names and extract a compact ``threshold`` / ``actual`` pair when cheap to
do so. They never log, never raise, never inspect state outside the
passed-in object.

See ``docs/design/observability-phase-1.md``.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from pearlalgo.market_agent.gate_decision import (
    GateDecision,
    GateLayer,
    accepted,
    rejected,
)


# ---------------------------------------------------------------------------
# execution_adapter layer
# ---------------------------------------------------------------------------

# Canonical gate names for ExecutionDecision.reason strings. See
# `ExecutionAdapterBase.check_preconditions()` in src/pearlalgo/execution/base.py
# for the source of the reason string format.
_EXECUTION_GATE_NAMES = frozenset(
    {
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
)


def execution_decision_to_gate(decision: Any) -> GateDecision:
    """Translate an ExecutionDecision into a canonical GateDecision.

    ``decision`` is duck-typed to avoid importing the execution module
    (keeps this translator testable without standing up the adapter
    stack). We only read ``.execute`` and ``.reason``.

    For accepted decisions the layer is ``execution_adapter`` and the
    gate is None. For rejected decisions the gate name is the first
    colon-delimited token of ``reason``; anything after the first colon
    is preserved as ``actual.raw_detail`` so operators can still
    reconstruct the original string from the audit record.

    An unknown gate name is recorded as-is under the ``unknown`` bucket
    so nothing is silently dropped; the CI AST linter (Phase 1 PR 5)
    will catch the drift.
    """
    execute = bool(getattr(decision, "execute", False))
    reason = str(getattr(decision, "reason", "") or "")

    if execute:
        return accepted(
            GateLayer.EXECUTION_ADAPTER,
            message=reason or "all preconditions passed",
        )

    gate, detail = _split_reason(reason)
    actual: Dict[str, Any] = {}
    if detail:
        actual["raw_detail"] = detail

    if gate and gate not in _EXECUTION_GATE_NAMES:
        # Don't silently lose unknown rejection reasons. Tag them for
        # follow-up but keep the audit record clean.
        actual["unknown_gate"] = True

    return rejected(
        GateLayer.EXECUTION_ADAPTER,
        gate or "unknown",
        actual=actual,
        message=reason,
    )


def _split_reason(reason: str) -> Tuple[str, str]:
    """Split ``reason`` on its first colon.

    Returns (gate_name, detail). ``detail`` is empty if no colon present.
    A leading/trailing whitespace on the gate name is stripped.
    """
    if not reason:
        return "", ""
    head, sep, tail = reason.partition(":")
    return head.strip(), tail
