"""Gate decision value type for Phase 1 signal observability.

A ``GateDecision`` captures a single gate's verdict on a signal: accepted,
rejected (dropped), or risk-scaled (downsized). Each decision is emitted at
a known layer (signal handler, circuit breaker, execution adapter,
protection guard) and names the specific gate that produced the verdict.

The value is immutable and self-describing — given only a GateDecision,
an operator should be able to answer: what gate, what layer, which
threshold, what the signal's actual value was, and why.

See ``docs/design/observability-phase-1.md`` for the full design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class GateOutcome(str, Enum):
    """Terminal verdict a gate produces for a signal."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RISK_SCALED = "risk_scaled"


class GateLayer(str, Enum):
    """Which subsystem's gate produced the decision.

    Ordered by the pipeline the signal flows through:
    signal_handler → circuit_breaker → execution_adapter → protection_guard.
    """

    SIGNAL_HANDLER = "signal_handler"
    CIRCUIT_BREAKER = "circuit_breaker"
    EXECUTION_ADAPTER = "execution_adapter"
    PROTECTION_GUARD = "protection_guard"


@dataclass(frozen=True)
class GateDecision:
    """Immutable record of one gate's verdict on one signal.

    ``gate`` names the specific check (``"not_armed"``, ``"regime_avoidance"``,
    ``"cooldown_active"``, ...). ``threshold`` and ``actual`` are small dicts
    that let an operator reconstruct the comparison without source code.
    ``message`` is a human-readable summary for the audit feed.

    For ACCEPTED outcomes, ``gate`` is None and ``threshold``/``actual`` may
    be empty — the decision is a positive signal that all gates at ``layer``
    passed.
    """

    outcome: GateOutcome
    layer: GateLayer
    gate: str | None = None
    threshold: Dict[str, Any] = field(default_factory=dict)
    actual: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    risk_scale_applied: float = 1.0

    def __post_init__(self) -> None:
        if self.outcome == GateOutcome.ACCEPTED and self.gate is not None:
            raise ValueError("ACCEPTED decisions must not name a gate")
        if self.outcome != GateOutcome.ACCEPTED and self.gate is None:
            raise ValueError(f"{self.outcome.value} decisions must name the gate")
        if self.outcome == GateOutcome.RISK_SCALED and not (0.0 <= self.risk_scale_applied < 1.0):
            raise ValueError(
                f"RISK_SCALED requires 0 <= risk_scale_applied < 1, got {self.risk_scale_applied}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the ``signal_audit.jsonl`` record shape."""
        return {
            "outcome": self.outcome.value,
            "layer": self.layer.value,
            "gate": self.gate,
            "threshold": self.threshold,
            "actual": self.actual,
            "message": self.message,
            "risk_scale_applied": self.risk_scale_applied,
        }


def accepted(layer: GateLayer, message: str = "") -> GateDecision:
    """Convenience constructor for an accept-at-layer decision."""
    return GateDecision(outcome=GateOutcome.ACCEPTED, layer=layer, message=message)


def rejected(
    layer: GateLayer,
    gate: str,
    *,
    threshold: Dict[str, Any] | None = None,
    actual: Dict[str, Any] | None = None,
    message: str = "",
) -> GateDecision:
    """Convenience constructor for a rejection."""
    return GateDecision(
        outcome=GateOutcome.REJECTED,
        layer=layer,
        gate=gate,
        threshold=threshold or {},
        actual=actual or {},
        message=message,
    )


def risk_scaled(
    layer: GateLayer,
    gate: str,
    risk_scale: float,
    *,
    threshold: Dict[str, Any] | None = None,
    actual: Dict[str, Any] | None = None,
    message: str = "",
) -> GateDecision:
    """Convenience constructor for a downsize-but-allow decision."""
    return GateDecision(
        outcome=GateOutcome.RISK_SCALED,
        layer=layer,
        gate=gate,
        threshold=threshold or {},
        actual=actual or {},
        message=message,
        risk_scale_applied=risk_scale,
    )
