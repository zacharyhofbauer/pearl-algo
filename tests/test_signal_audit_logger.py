"""Tests for SignalAuditLogger and GateDecision (Phase 1 observability)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from pearlalgo.market_agent.gate_decision import (
    GateDecision,
    GateLayer,
    GateOutcome,
    accepted,
    rejected,
    risk_scaled,
)
from pearlalgo.market_agent.signal_audit_logger import SignalAuditLogger


# ---------------------------------------------------------------------------
# GateDecision value type
# ---------------------------------------------------------------------------


class TestGateDecision:
    def test_accepted_has_no_gate(self) -> None:
        d = accepted(GateLayer.SIGNAL_HANDLER, "all signal-handler checks passed")
        assert d.outcome == GateOutcome.ACCEPTED
        assert d.gate is None
        assert d.layer == GateLayer.SIGNAL_HANDLER

    def test_accepted_with_gate_raises(self) -> None:
        with pytest.raises(ValueError, match="must not name a gate"):
            GateDecision(
                outcome=GateOutcome.ACCEPTED,
                layer=GateLayer.CIRCUIT_BREAKER,
                gate="anything",
            )

    def test_rejected_requires_gate(self) -> None:
        with pytest.raises(ValueError, match="must name the gate"):
            GateDecision(
                outcome=GateOutcome.REJECTED,
                layer=GateLayer.EXECUTION_ADAPTER,
                gate=None,
            )

    def test_risk_scaled_bounds(self) -> None:
        with pytest.raises(ValueError, match="0 <= risk_scale_applied < 1"):
            risk_scaled(GateLayer.CIRCUIT_BREAKER, "equity_curve", 1.0)
        with pytest.raises(ValueError, match="0 <= risk_scale_applied < 1"):
            risk_scaled(GateLayer.CIRCUIT_BREAKER, "equity_curve", -0.1)
        # valid
        d = risk_scaled(GateLayer.CIRCUIT_BREAKER, "equity_curve", 0.5)
        assert d.risk_scale_applied == 0.5

    def test_rejected_helper(self) -> None:
        d = rejected(
            GateLayer.EXECUTION_ADAPTER,
            "not_armed",
            threshold={"armed": True},
            actual={"armed": False},
            message="adapter is not armed",
        )
        assert d.outcome == GateOutcome.REJECTED
        assert d.gate == "not_armed"
        assert d.threshold == {"armed": True}
        assert d.actual == {"armed": False}

    def test_to_dict_round_trip(self) -> None:
        d = rejected(
            GateLayer.CIRCUIT_BREAKER,
            "regime_avoidance",
            threshold={"blocked": ["ranging", "volatile"], "min_confidence": 0.7},
            actual={"regime": "ranging", "confidence": 0.5},
            message="regime ranging is blocked and confidence below threshold",
        )
        j = d.to_dict()
        assert j["outcome"] == "rejected"
        assert j["layer"] == "circuit_breaker"
        assert j["gate"] == "regime_avoidance"
        assert j["threshold"]["min_confidence"] == 0.7


# ---------------------------------------------------------------------------
# SignalAuditLogger
# ---------------------------------------------------------------------------


def _drain(logger: SignalAuditLogger, timeout: float = 1.0) -> None:
    """Wait for the writer thread to flush."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if logger._queue.empty():  # type: ignore[attr-defined]
            # give the worker one tick to finish writing
            time.sleep(0.05)
            return
        time.sleep(0.02)


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestSignalAuditLogger:
    def test_disabled_is_noop(self, tmp_path: Path) -> None:
        log = SignalAuditLogger(tmp_path, enabled=False)
        assert not log.enabled
        log.record({"signal_id": "x"}, rejected(GateLayer.EXECUTION_ADAPTER, "not_armed"))
        # nothing should be written
        assert not (tmp_path / "signal_audit.jsonl").exists()
        log.shutdown()

    def test_records_rejection(self, tmp_path: Path) -> None:
        log = SignalAuditLogger(tmp_path)
        signal = {
            "signal_id": "sig_123",
            "type": "pearlbot_pinescript",
            "direction": "long",
            "confidence": 0.64,
            "entry_price": 26879.25,
            "market_regime": {"regime": "trending_down", "volatility_ratio": 1.08},
        }
        decision = rejected(
            GateLayer.CIRCUIT_BREAKER,
            "regime_avoidance",
            threshold={"blocked": ["ranging", "volatile"], "min_confidence": 0.7},
            actual={"regime": "trending_down", "confidence": 0.64},
            message="below direction-gating threshold",
        )
        log.record(signal, decision)
        _drain(log)
        log.shutdown()

        records = _read_records(tmp_path / "signal_audit.jsonl")
        assert len(records) == 1
        r = records[0]
        assert r["_schema"] == 1
        assert r["signal_id"] == "sig_123"
        assert r["signal_type"] == "pearlbot_pinescript"
        assert r["direction"] == "long"
        assert r["confidence"] == 0.64
        assert r["entry_price"] == 26879.25
        assert r["regime"] == "trending_down"
        assert r["atr_ratio"] == 1.08
        assert r["outcome"] == "rejected"
        assert r["layer"] == "circuit_breaker"
        assert r["gate"] == "regime_avoidance"
        assert r["message"] == "below direction-gating threshold"

    def test_records_accepted_and_risk_scaled(self, tmp_path: Path) -> None:
        log = SignalAuditLogger(tmp_path)
        signal = {"signal_id": "sig_ok", "direction": "long", "confidence": 0.8}
        log.record(signal, accepted(GateLayer.SIGNAL_HANDLER, "all checks passed"))
        log.record(
            signal,
            risk_scaled(
                GateLayer.CIRCUIT_BREAKER,
                "equity_curve",
                0.5,
                threshold={"equity_above_ma": True},
                actual={"equity_above_ma": False},
                message="equity below 20-trade MA — half size",
            ),
        )
        _drain(log)
        log.shutdown()

        records = _read_records(tmp_path / "signal_audit.jsonl")
        assert len(records) == 2
        assert records[0]["outcome"] == "accepted"
        assert records[0]["gate"] is None
        assert records[1]["outcome"] == "risk_scaled"
        assert records[1]["gate"] == "equity_curve"
        assert records[1]["risk_scale_applied"] == 0.5

    def test_rotation_at_threshold(self, tmp_path: Path) -> None:
        log = SignalAuditLogger(tmp_path, rotation_bytes=1024)  # 1 KB
        # each record ~200 bytes, write enough to trip rotation
        for i in range(30):
            log.record(
                {"signal_id": f"s{i}", "direction": "long", "confidence": 0.5},
                rejected(GateLayer.EXECUTION_ADAPTER, "not_armed"),
            )
        _drain(log, timeout=2.0)
        log.shutdown()

        main_path = tmp_path / "signal_audit.jsonl"
        backup_path = tmp_path / "signal_audit.jsonl.1"
        assert main_path.exists()
        assert backup_path.exists(), "expected rotation to create .1 backup"

    def test_record_never_raises(self, tmp_path: Path) -> None:
        log = SignalAuditLogger(tmp_path)
        # malformed signal (non-dict) shouldn't crash the caller
        log.record({}, rejected(GateLayer.SIGNAL_HANDLER, "whitelist"))
        _drain(log)
        log.shutdown()
        # as long as we got here without exception, we're good

    def test_shutdown_is_idempotent(self, tmp_path: Path) -> None:
        log = SignalAuditLogger(tmp_path)
        log.shutdown()
        log.shutdown()  # second call must not raise
