"""Tests for scripts/ops/why_no_signal.py (Phase 1 CLI)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Load the script as a module (it's under scripts/ops/, not in a package)
_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "ops" / "why_no_signal.py"

_spec = importlib.util.spec_from_file_location("why_no_signal", _SCRIPT)
assert _spec and _spec.loader
wns = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wns)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rec(
    *,
    ts: str | None = None,
    signal_id: str = "s1",
    outcome: str = "rejected",
    layer: str = "execution_adapter",
    gate: str | None = "not_armed",
    direction: str = "long",
    confidence: float = 0.6,
    risk_scale_applied: float = 1.0,
    message: str = "",
    threshold: Dict[str, Any] | None = None,
    actual: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    return {
        "_schema": 1,
        "ts": ts,
        "signal_id": signal_id,
        "signal_type": "pearlbot_pinescript",
        "direction": direction,
        "confidence": confidence,
        "entry_price": 26900.0,
        "outcome": outcome,
        "layer": layer,
        "gate": gate,
        "threshold": threshold or {},
        "actual": actual or {},
        "message": message,
        "risk_scale_applied": risk_scale_applied,
    }


def _write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


class TestTimeParsing:
    def test_relative_hours(self):
        ts = wns._parse_relative_time("1h")
        assert ts is not None
        delta = datetime.now(timezone.utc) - ts
        assert timedelta(minutes=59) < delta < timedelta(minutes=61)

    def test_relative_minutes(self):
        ts = wns._parse_relative_time("30m")
        assert ts is not None
        delta = datetime.now(timezone.utc) - ts
        assert timedelta(minutes=29) < delta < timedelta(minutes=31)

    def test_absolute_iso_z_suffix(self):
        ts = wns._parse_relative_time("2026-04-23T04:00:00Z")
        assert ts == datetime(2026, 4, 23, 4, 0, 0, tzinfo=timezone.utc)

    def test_absolute_iso_plus_offset(self):
        ts = wns._parse_relative_time("2026-04-23T04:00:00+00:00")
        assert ts is not None

    def test_invalid_returns_none(self):
        assert wns._parse_relative_time("nonsense") is None
        assert wns._parse_relative_time("") is None


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestFiltering:
    def test_since_excludes_old(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        records = [_rec(ts=old, signal_id="old"), _rec(ts=new, signal_id="new")]
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        out = wns.filter_records(records, since=since)
        assert len(out) == 1 and out[0]["signal_id"] == "new"

    def test_filter_by_gate(self):
        records = [
            _rec(gate="not_armed", signal_id="a"),
            _rec(gate="cooldown_active", signal_id="b"),
        ]
        out = wns.filter_records(records, gate="not_armed")
        assert [r["signal_id"] for r in out] == ["a"]

    def test_filter_by_outcome(self):
        records = [
            _rec(outcome="accepted", gate=None, signal_id="a"),
            _rec(outcome="rejected", signal_id="b"),
        ]
        out = wns.filter_records(records, outcome="rejected")
        assert [r["signal_id"] for r in out] == ["b"]

    def test_filter_by_signal_id(self):
        records = [_rec(signal_id="x"), _rec(signal_id="y")]
        out = wns.filter_records(records, signal_id="y")
        assert [r["signal_id"] for r in out] == ["y"]


# ---------------------------------------------------------------------------
# Subcommand output
# ---------------------------------------------------------------------------


class TestSummary:
    def test_empty(self):
        out = wns.cmd_summary([], window_label="last 1h")
        assert "no audit records" in out

    def test_breakdown(self):
        records = [
            _rec(outcome="accepted", gate=None),
            _rec(outcome="accepted", gate=None),
            _rec(outcome="risk_scaled", gate="tod", risk_scale_applied=0.5),
            _rec(outcome="rejected", gate="not_armed"),
            _rec(outcome="rejected", gate="not_armed"),
            _rec(outcome="rejected", gate="regime_avoidance"),
        ]
        out = wns.cmd_summary(records, window_label="last 1h")
        assert "last 1h" in out
        assert "accepted" in out and "2" in out
        assert "rejected" in out and "3" in out
        assert "risk_scaled" in out and "1" in out
        # Top rejections section
        assert "not_armed" in out
        assert "regime_avoidance" in out
        # tod appears in risk-scaled section
        assert "tod" in out


class TestSignalLookup:
    def test_no_match(self):
        out = wns.cmd_signal([_rec(signal_id="x")], "missing")
        assert "no audit records" in out

    def test_full_history(self):
        sid = "pearlbot_42"
        records = [
            _rec(
                signal_id=sid,
                layer="signal_handler",
                gate=None,
                outcome="accepted",
                ts="2026-04-23T04:00:00Z",
                message="whitelist passed",
            ),
            _rec(
                signal_id=sid,
                layer="circuit_breaker",
                outcome="rejected",
                gate="regime_avoidance",
                ts="2026-04-23T04:00:01Z",
                threshold={"blocked": ["ranging"]},
                actual={"regime": "ranging"},
                message="regime ranging is blocked",
            ),
        ]
        out = wns.cmd_signal(records, sid)
        assert "2 decision" in out
        assert "signal_handler" in out
        assert "circuit_breaker" in out
        assert "regime_avoidance" in out
        assert "blocked" in out


class TestTail:
    def test_tail_limit(self):
        records = [_rec(signal_id=f"s{i}") for i in range(5)]
        out = wns.cmd_tail(records, n=2)
        assert "s3" in out
        assert "s4" in out
        # earlier records should not show
        assert "s0" not in out


# ---------------------------------------------------------------------------
# End-to-end via main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_summary_from_file(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        audit = tmp_path / "signal_audit.jsonl"
        _write_jsonl(
            audit,
            [
                _rec(outcome="accepted", gate=None),
                _rec(outcome="rejected", gate="not_armed"),
            ],
        )
        rc = wns.main(["--state-dir", str(tmp_path), "--no-color", "summary"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "accepted" in out and "rejected" in out

    def test_signal_from_stdin(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ):
        recs = [_rec(signal_id="sig_x", gate="not_armed")]
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO("\n".join(json.dumps(r) for r in recs)),
        )
        rc = wns.main(["--stdin", "--no-color", "signal", "sig_x"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "sig_x" in out
        assert "not_armed" in out

    def test_missing_file_errors_cleanly(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        rc = wns.main(["--state-dir", str(tmp_path), "--no-color", "summary"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "audit file not found" in err

    def test_invalid_since_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ):
        audit = tmp_path / "signal_audit.jsonl"
        _write_jsonl(audit, [])
        rc = wns.main(
            [
                "--state-dir", str(tmp_path), "--no-color",
                "--since", "not-a-time", "summary",
            ]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "could not parse" in err
