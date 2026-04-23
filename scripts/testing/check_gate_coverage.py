#!/usr/bin/env python3
# ============================================================================
# Category: Testing/Validation
# Purpose: Enforce gate-name coverage for Phase 1 observability translators
# Usage: python3 scripts/testing/check_gate_coverage.py [--enforce]
# ============================================================================
"""Gate Coverage Linter

Scans the execution adapter and trading circuit breaker for every reason
string emitted in ``ExecutionDecision(reason=...)`` and
``CircuitBreakerDecision(reason=...)`` literals, and verifies each gate
name is covered by the corresponding canonical set in
``src/pearlalgo/market_agent/gate_translators.py``.

Prevents silent drift: if someone adds a new gate (new reason string) to
the runtime decision path without updating the translator, CI fails with
a clear message naming the uncovered gate.

Exit codes:
    0 - All reason strings in the runtime are covered by the translators
    1 - Uncovered reason strings found (--enforce mode)
    2 - Linter itself failed (couldn't parse a file, missing symbol, etc.)

Design notes:
- Matches only string-literal reasons. Reasons built via f-strings are
  split on the first colon at emit time anyway (gate = head of colon),
  so the linter only requires the **head** to be in the canonical set.
- The translator's own file is excluded from scanning (it defines the
  sets, doesn't emit reasons).
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterable, List, Set, Tuple

# ---------------------------------------------------------------------------
# Config: which decision class maps to which canonical gate set
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSLATORS_FILE = REPO_ROOT / "src" / "pearlalgo" / "market_agent" / "gate_translators.py"

# Files to scan. Keyed by the decision-class name we look for inside.
GATE_SOURCES: List[Tuple[str, str, Path]] = [
    (
        "ExecutionDecision",
        "_EXECUTION_GATE_NAMES",
        REPO_ROOT / "src" / "pearlalgo" / "execution" / "base.py",
    ),
    (
        "CircuitBreakerDecision",
        "_CIRCUIT_BREAKER_GATE_NAMES",
        REPO_ROOT / "src" / "pearlalgo" / "market_agent" / "trading_circuit_breaker.py",
    ),
]


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _load_canonical_sets() -> dict[str, Set[str]]:
    """Import the translators module and read out the frozensets."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from pearlalgo.market_agent import gate_translators  # type: ignore
    except Exception as exc:  # pragma: no cover
        print(f"error: cannot import gate_translators: {exc}", file=sys.stderr)
        sys.exit(2)
    finally:
        try:
            sys.path.remove(str(REPO_ROOT / "src"))
        except ValueError:
            pass

    sets: dict[str, Set[str]] = {}
    for _decision_cls, set_name, _src in GATE_SOURCES:
        if not hasattr(gate_translators, set_name):
            print(
                f"error: gate_translators.{set_name} not found",
                file=sys.stderr,
            )
            sys.exit(2)
        sets[set_name] = set(getattr(gate_translators, set_name))
    return sets


def _iter_reason_literals(
    source_path: Path, decision_cls: str
) -> Iterable[Tuple[int, str]]:
    """Yield (lineno, reason_literal) for every ``<cls>(...reason=<str>...)`` call.

    Matches both keyword and positional-reason calls conservatively.
    Non-literal reason values (f-strings, variables, etc.) are ignored
    by this linter — the colon-head convention makes them safe.
    """
    text = source_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(source_path))
    except SyntaxError as exc:
        print(f"error: failed to parse {source_path}: {exc}", file=sys.stderr)
        sys.exit(2)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _callee_name(node.func)
        if callee != decision_cls:
            continue

        # keyword form: ExecutionDecision(..., reason="xxx")
        for kw in node.keywords:
            if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
                val = kw.value.value
                if isinstance(val, str):
                    yield node.lineno, val

        # positional form is unusual for these classes (they use kwargs),
        # but handle it defensively: reason is the second positional arg
        # (execute, reason) for ExecutionDecision; (allowed, reason) for CB.
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            val = node.args[1].value
            if isinstance(val, str):
                yield node.lineno, val


def _callee_name(node: ast.AST) -> str:
    """Return the string name of a call target, best-effort."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _gate_head(reason: str) -> str:
    """First colon-delimited token of a reason string — the canonical gate name."""
    if ":" in reason:
        return reason.split(":", 1)[0].strip()
    return reason.strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit 1 if uncovered gates found (default: warn only, exit 0)",
    )
    args = parser.parse_args()

    canonical = _load_canonical_sets()

    violations: List[Tuple[Path, int, str, str]] = []
    total_scanned = 0

    for decision_cls, set_name, source_path in GATE_SOURCES:
        if not source_path.exists():
            print(f"error: gate source missing: {source_path}", file=sys.stderr)
            return 2
        known = canonical[set_name]
        for lineno, reason in _iter_reason_literals(source_path, decision_cls):
            total_scanned += 1
            gate = _gate_head(reason)
            # Accepted-outcome reasons are not gate names; skip them.
            # These are strings that name a *successful* check, not a gate.
            if _is_accepted_reason(gate):
                continue
            if gate not in known:
                violations.append((source_path, lineno, decision_cls, reason))

    status_mode = "enforce" if args.enforce else "warn"

    if violations:
        print(
            f"\n❌ Gate coverage check failed ({len(violations)} uncovered "
            f"out of {total_scanned} reason literals scanned, mode={status_mode})",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        for src, lineno, cls, reason in violations:
            rel = src.relative_to(REPO_ROOT)
            gate = _gate_head(reason)
            print(
                f"  {rel}:{lineno}  {cls}(reason={reason!r})  gate={gate!r}",
                file=sys.stderr,
            )
        print(file=sys.stderr)
        print(
            "  fix: add the missing gate name to the corresponding frozenset in\n"
            "       src/pearlalgo/market_agent/gate_translators.py",
            file=sys.stderr,
        )
        return 1 if args.enforce else 0

    print(
        f"✅ Gate coverage OK — {total_scanned} reason literals scanned, all covered"
    )
    return 0


# Reasons that describe a passed/accepted state, not a gate.
# We match on the gate-head (pre-colon) only.
_ACCEPTED_REASONS: Set[str] = {
    # ExecutionAdapterBase.check_preconditions
    "preconditions_passed",
    # TradingCircuitBreaker accepted states (allowed=True with risk_scale=1.0)
    "passed_all_checks",
    "consecutive_losses_ok",
    "tiered_loss_ok",
    "no_losses",
    "no_cooldown",
    "regime_ok",
    "trigger_ok",
    "volatility_ok",
    "equity_curve_ok",
    "tod_ok",
    "tod_full",
    "position_limits_ok",
    "direction_gating_ok",
    "tv_paper_eval_ok",
    "volatility_risk_full",
    "vol_ok",
    "vol_no_data",
    "session_drawdown_ok",
    "daily_drawdown_ok",
    "daily_profit_cap_ok",
    "daily_profit_cap_disabled",
    "rolling_win_rate_ok",
    "equity_curve_insufficient_data",
}


def _is_accepted_reason(gate_head: str) -> bool:
    return gate_head in _ACCEPTED_REASONS


if __name__ == "__main__":
    sys.exit(main())
