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
    risk_scaled,
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


# ---------------------------------------------------------------------------
# circuit_breaker layer
# ---------------------------------------------------------------------------

# Canonical gate names from `TradingCircuitBreaker.should_allow_signal()`
# in src/pearlalgo/market_agent/trading_circuit_breaker.py. Hard-block
# checks return reasons that match these names (possibly prefixed with
# `tiered_loss:` etc); scale-only checks are surfaced via the
# `scale_reasons` list in decision.details.
_CIRCUIT_BREAKER_GATE_NAMES = frozenset(
    {
        # Cooldown (wrapper; reason often prefixes `in_cooldown:`)
        "in_cooldown",
        # Hard-block gates
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
        # Scale-only gates (surface as risk_scaled outcomes)
        "equity_curve",
        "tod",
        "tod_risk_scaling",
        "volatility",
        "volatility_risk_scaling",
        # Final-fallback hard block when cumulative scaling reaches zero
        "risk_scale_zero",
    }
)


def circuit_breaker_decision_to_gate(decision: Any) -> GateDecision:
    """Translate a CircuitBreakerDecision into a canonical GateDecision.

    Duck-typed on ``.allowed``, ``.reason``, ``.risk_scale``, ``.details``.

    Three outcomes:
    - ``allowed=False`` → rejected, gate = first token of ``reason``.
    - ``allowed=True`` and ``risk_scale < 1.0`` → risk_scaled. The
      dominant scaling gate is taken from the first entry of
      ``details["scale_reasons"]`` (format ``"<gate>:<scale>"``).
    - ``allowed=True`` and ``risk_scale >= 1.0`` → accepted.
    """
    allowed = bool(getattr(decision, "allowed", False))
    reason = str(getattr(decision, "reason", "") or "")
    try:
        risk_scale = float(getattr(decision, "risk_scale", 1.0))
    except (TypeError, ValueError):
        risk_scale = 1.0
    details = getattr(decision, "details", {}) or {}
    if not isinstance(details, dict):
        details = {}

    # --- Hard block -------------------------------------------------------
    if not allowed:
        gate, detail = _split_reason(reason)
        actual: Dict[str, Any] = {}
        if detail:
            actual["raw_detail"] = detail
        if gate and gate not in _CIRCUIT_BREAKER_GATE_NAMES:
            actual["unknown_gate"] = True
        return rejected(
            GateLayer.CIRCUIT_BREAKER,
            gate or "unknown",
            actual=actual,
            message=reason,
        )

    # --- Allowed but risk-scaled ------------------------------------------
    # The top-level `reason` for a fully-passed check is "passed_all_checks";
    # the actual scaling gate is in details.scale_reasons. Take the first
    # (the CB accumulates min across all scalers, so order isn't strict —
    # but the first is typically the dominant one).
    if 0.0 <= risk_scale < 1.0:
        scale_reasons = details.get("scale_reasons") or []
        if isinstance(scale_reasons, list) and scale_reasons:
            first = str(scale_reasons[0])
            scaler_gate, _ = _split_reason(first)
            scaler_gate = scaler_gate or "unknown_scaler"
        else:
            scaler_gate = "unknown_scaler"
        actual_rs: Dict[str, Any] = {"scale_reasons": scale_reasons}
        if scaler_gate not in _CIRCUIT_BREAKER_GATE_NAMES:
            actual_rs["unknown_gate"] = True
        return risk_scaled(
            GateLayer.CIRCUIT_BREAKER,
            scaler_gate,
            risk_scale,
            actual=actual_rs,
            message=reason,
        )

    # --- Fully allowed ----------------------------------------------------
    return accepted(
        GateLayer.CIRCUIT_BREAKER,
        message=reason or "all circuit-breaker checks passed",
    )
