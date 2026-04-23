# Phase 1 — Signal Observability

**Status:** Design draft
**Owner:** —
**Target merge:** 3 days after approval

## Problem

When a signal doesn't fire, today you can't tell *why* without tailing agent logs and pattern-matching across multiple warning messages. There are ~30 gates that can reject a signal across `signal_handler.py`, `trading_circuit_breaker.py`, `execution/base.py`, and `execution/tradovate/adapter.py`. Most of them drop the signal silently from the operator's perspective — only signals that *pass* all gates land in `signals.jsonl`.

Concrete example from tonight: the agent went quiet from 03:42 UTC to 04:17 UTC. It took SSH + `journalctl` + a 1-hour grep to rule out the session profit lock, TOD scaling, and the protection guard, and land on "IBKR Gateway lost connectivity." Phase 1 makes that diagnosis a single query.

## Goal

After Phase 1, for any signal emitted by the strategy in the last N sessions, the operator can answer:

1. Did it pass all gates? If not, **which gate** rejected it?
2. What were the signal's key fields (direction, confidence, regime, price) at the moment of rejection?
3. What was the gate's threshold vs the signal's actual value?
4. Across a session: which gates fired most, and on which signal types?

All four answers must be available **without reading source code** and **without shell access to the Beelink** — either from the webapp or from a single CLI command on the Mac.

## Non-goals

- Changing any gate's behavior (pure instrumentation — zero logic change)
- Re-architecting signal flow (Phase 4 territory)
- Historical backfill of rejections that happened before this ships (we only capture forward)
- Per-gate toggles / "log but don't enforce" mode (that's Phase 3 shadow mode)

## Design

### Data model — one event per signal-gate decision

Append to a new file `data/agent_state/<symbol>/signal_audit.jsonl` (same dir as `signals.jsonl`, same lock semantics, same rotation logic at 20MB).

```jsonc
{
  "ts": "2026-04-23T04:17:42.123456+00:00",
  "signal_id": "pearlbot_pinescript_1776915732.612687",
  "signal_type": "pearlbot_pinescript",
  "direction": "long",
  "confidence": 0.64,
  "entry_price": 26879.25,
  "regime": "trending_down",
  "atr_ratio": 1.08,
  "outcome": "rejected",                 // "accepted" | "rejected" | "risk_scaled"
  "gate": "regime_avoidance",            // null if accepted
  "gate_layer": "circuit_breaker",       // "signal_handler" | "circuit_breaker" | "execution_adapter" | "protection_guard"
  "threshold": {"blocked_regimes": ["ranging", "volatile"], "min_confidence": 0.70},
  "actual": {"regime": "trending_down", "confidence": 0.64},
  "message": "regime=trending_down not blocked, but confidence 0.64 < 0.70 threshold — allowed",
  "risk_scale_applied": 1.0              // <1.0 means gate downsized but didn't reject
}
```

**Why a new file instead of extending `signals.jsonl`:** `signals.jsonl` is already a downstream-of-acceptance log (entered trades). Rejected signals never reach it. A parallel audit file keeps existing consumers (backtest, performance tracker) unchanged while giving us full-spectrum visibility.

### Code changes

**1. Add `GateDecision` value type** — `src/pearlalgo/market_agent/gate_decision.py` (new file, ~60 LOC):

```python
@dataclass(frozen=True)
class GateDecision:
    outcome: Literal["accepted", "rejected", "risk_scaled"]
    gate: str | None
    layer: Literal["signal_handler", "circuit_breaker", "execution_adapter", "protection_guard"]
    threshold: dict
    actual: dict
    message: str
    risk_scale_applied: float = 1.0
```

**2. Instrument the four gate sites** — each early-return and risk-scale branch records a `GateDecision` and hands it to a central `SignalAuditLogger` (new, ~80 LOC):

| File | Lines to touch | Gates covered |
|---|---|---|
| `signal_handler.py` | 115, 140, 180, 190, 205, 210, 238, 290, 312 | 9 gates (whitelist, CB block, CB risk scaling, price validation, future-ts, exec status, follower CB, follower exec status) |
| `trading_circuit_breaker.py` | 130, 152, 160, 166, 172, 178, 184, 191, 197, 202, 210, 219, 228, 238, 244, 254, 261 | 17 gates (every early-return and risk-scale return) |
| `execution/base.py` | 327, 335, 343, 351, 360, 370, 384, 398, 407, 428, 444 | 11 precondition gates |
| `execution/tradovate/adapter.py` | 374, 409, 436, 743 | 4 adapter-level gates (dedup, broker position conflict, protection guard) |

Total: **~41 call-sites**, each a 3-line insertion (construct decision → `audit.record(sig, decision)` → existing return).

**3. `SignalAuditLogger`** — `src/pearlalgo/market_agent/signal_audit_logger.py` (new, ~80 LOC):
- Append-only JSONL writer with file lock (copy pattern from `state_manager.py` line 273)
- 20MB rotation
- `record(signal: dict, decision: GateDecision) -> None` — non-blocking (put on the existing async queue if one exists, else inline)
- Wire into DI container in `service_factory.py`

**4. Cycle-level summary rollup** — extend existing `_cycle_rejections` dict in `signal_handler.py` (it already counts ~5 buckets) to count by exact gate name. Emit a one-line cycle summary every N cycles: `cycle=103583 accepted=2 rejected={regime_avoidance:1, cooldown:1} risk_scaled={tod:1}`.

### Surfacing

**CLI** (new, 1 file ~100 LOC — `scripts/ops/why_no_signal.py`):
```
$ ./scripts/ops/why_no_signal.py --since "1 hour ago"
Last hour: 47 signals evaluated
  ✅ accepted:     3 (2 long, 1 short)
  🔻 risk_scaled: 12 (mostly volatility_risk_scaling @ 0.5x)
  ❌ rejected:    32
     - duplicate_signal_id: 14
     - cooldown_active:      9
     - regime_avoidance:     6
     - min_confidence:       3

$ ./scripts/ops/why_no_signal.py --signal-id pearlbot_pinescript_1776915732.612687
Rejected by: circuit_breaker / regime_avoidance
  signal.regime=trending_down, threshold blocks [ranging, volatile]
  signal.confidence=0.64, threshold 0.70
  message: "regime not blocked, but confidence below direction-gating threshold"
```

**Webapp** (extend `apps/pearl-algo-app/`):
- New route `/signals/audit` — reverse-chronological table of the last 200 signal decisions with gate, direction, confidence, regime, outcome
- Color-coded: green accepted, yellow risk-scaled, red rejected
- Click-through to full JSON for one signal
- Rejection-reason bar chart for the current session (reuses existing chart lib)

### Testing

- Unit test per gate site: construct a `(signal, state)` pair that should hit the gate, assert the `GateDecision` emitted matches expected
- Fixture: `tests/fixtures/gate_scenarios.py` — one scenario per gate (~41 scenarios). This becomes the canonical gate inventory.
- Integration test: run a 10-signal synthetic session against the real handler + CB + adapter chain, verify every signal ends with exactly one terminal `GateDecision` (accepted or rejected).
- Regression guard: CI fails if any `if` branch in the four files returns `None`/drops a signal without a `GateDecision`. (Implemented as a simple AST linter in `scripts/testing/check_gate_coverage.py`.)

### Rollout

Single PR, ~600 LOC added, ~0 LOC changed (pure insertion at gate sites). Ships behind a feature flag `observability.enabled` in the yaml config, default **true**. Tested in paper for 48h before declaring done. Reversion is the flag flip — no rollback drama.

### Risks & mitigations

| Risk | Mitigation |
|---|---|
| Audit logger blocks the hot path | Non-blocking — enqueue + drain async, never raise in `record()` |
| Disk growth (~500KB/day estimated at current signal rate) | 20MB rotation, 14-day retention (configurable) |
| Coverage drift — new gate added without instrumentation | AST linter (`check_gate_coverage.py`) in CI fails the build |
| Schema churn in `signal_audit.jsonl` | Version field `_schema: 1` in every record; reader tolerates old records |

### Out of scope for Phase 1

- Decision replay / time-travel debugging
- Parquet export of audit stream (Phase 2 will build the archive infrastructure; this file can feed into it later)
- Per-gate alerting / anomaly detection
- Cross-session trend analysis (Phase 3 shadow mode will reuse this stream for comparison)

---

**Rough effort**: 2.5 days of implementation + 0.5 day CI/tests = 3 days to merge-ready PR. 48h paper soak = total 5 calendar days to "done."
