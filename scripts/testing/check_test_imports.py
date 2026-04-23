#!/usr/bin/env python3
"""Block new test-side imports of ``pearlalgo.trading_bots`` (Issue 11-A).

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 3.

The legacy module surface ``pearlalgo.trading_bots`` is scheduled for
retirement behind the ``pearlalgo.strategies.composite_intraday`` facade
(Issue 1-A). Every existing test that reaches into the legacy module
has to migrate alongside the seam extraction. Without a guard,
additional tests would keep piling on — this linter freezes the set.

Behavior:
  * Enumerates every ``.py`` file under ``tests/`` (excluding
    ``__pycache__``).
  * Records any that import ``pearlalgo.trading_bots...`` (either
    ``from pearlalgo.trading_bots...`` or ``import pearlalgo.trading_bots``).
  * Compares against the allowlist at
    ``.github/trading_bots_test_allowlist.yaml``.
  * Fails (exit 1) on any test file NOT on the allowlist.
  * Warns when an allowlisted file no longer imports from the legacy
    module — a hint to remove it from the allowlist (the list only
    shrinks).

Exit codes:
    0 - no new imports and no stale allowlist entries
    1 - new unauthorized import (blocks merge)
    2 - linter itself failed (couldn't parse a file, etc.)
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Set

import yaml  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ALLOWLIST = REPO_ROOT / ".github" / "trading_bots_test_allowlist.yaml"
TESTS_DIR = REPO_ROOT / "tests"

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_LINTER = 2


def _imports_trading_bots(source_path: Path) -> bool:
    """Return True iff ``source_path`` imports anything under pearlalgo.trading_bots."""
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except SyntaxError as exc:
        print(
            f"ERROR: could not parse {source_path}: {exc}",
            file=sys.stderr,
        )
        raise
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("pearlalgo.trading_bots"):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("pearlalgo.trading_bots"):
                    return True
    return False


def _load_allowlist(path: Path) -> Set[str]:
    if not path.exists():
        print(f"ERROR: allowlist missing: {path}", file=sys.stderr)
        sys.exit(EXIT_LINTER)
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict) or "allowed_tests" not in data:
        print(
            f"ERROR: {path} must have a top-level `allowed_tests:` list",
            file=sys.stderr,
        )
        sys.exit(EXIT_LINTER)
    return {str(x) for x in data["allowed_tests"]}


def _relative(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))


def scan(tests_dir: Path, allowlist_path: Path) -> int:
    allowlist = _load_allowlist(allowlist_path)
    offenders: list[str] = []
    actual_importers: Set[str] = set()

    for path in sorted(tests_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            if _imports_trading_bots(path):
                rel = _relative(path)
                actual_importers.add(rel)
                if rel not in allowlist:
                    offenders.append(rel)
        except SyntaxError:
            return EXIT_LINTER

    if offenders:
        print("", file=sys.stderr)
        print("NEW tests import from pearlalgo.trading_bots (not allowed):", file=sys.stderr)
        for rel in offenders:
            print(f"  {rel}", file=sys.stderr)
        print(
            "\nUse pearlalgo.strategies.composite_intraday.* in new tests, "
            "or if you must touch the legacy surface, justify in a PR and "
            f"add the path to {_relative(allowlist_path)}.",
            file=sys.stderr,
        )
        return EXIT_VIOLATION

    stale = sorted(allowlist - actual_importers)
    if stale:
        print("Allowlist entries no longer needed (consider removing):")
        for rel in stale:
            print(f"  {rel}")

    print(f"OK: {len(actual_importers)} test file(s) on allowlist import trading_bots.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tests-dir",
        type=Path,
        default=TESTS_DIR,
        help="Root test directory to scan (default: tests/)",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help="Allowlist YAML path",
    )
    args = parser.parse_args(argv)
    return scan(args.tests_dir, args.allowlist)


if __name__ == "__main__":
    sys.exit(main())
