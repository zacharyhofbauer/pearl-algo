#!/usr/bin/env python3
"""Per-file coverage ratchet for the five money-path modules.

Issue 9-A (plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md``).

The existing ``.github/workflows/ci.yml`` enforces a global coverage
floor (43 % as of 2026-04-23) and the frontend re-pins thresholds to
whatever the build happens to measure. Neither approach catches a
regression inside a specific *file*. The files where a regression
matters most on a live-money futures system are:

  * ``src/pearlalgo/execution/tradovate/adapter.py``
  * ``src/pearlalgo/market_agent/trading_circuit_breaker.py``
  * ``src/pearlalgo/market_agent/order_manager.py``
  * ``src/pearlalgo/market_agent/signal_handler.py``
  * ``src/pearlalgo/trading_bots/signal_generator.py``

This linter reads ``coverage.xml`` (produced by the existing
``pytest --cov-report=xml`` step), compares each money-path file's
current line coverage against the floor recorded in
``.github/coverage_floors.yaml``, and fails CI if any file drops below
its floor. Floors only move up — a regression is blocked even if the
global floor is met.

Usage::

    python scripts/testing/check_money_path_coverage.py              # report + enforce
    python scripts/testing/check_money_path_coverage.py --write-floor  # record current as new floor (manual ratchet-up)

Exit codes:
    0 - all money-path files at or above their floor
    1 - one or more regressions (CI-blocking)
    2 - linter itself failed (missing coverage.xml, malformed floors, etc.)
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict

import yaml  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FLOORS_PATH = REPO_ROOT / ".github" / "coverage_floors.yaml"
DEFAULT_COVERAGE_XML = REPO_ROOT / "coverage.xml"

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_LINTER = 2


def _rel_or_abs(p: Path) -> str:
    """Return the path relative to the repo when it lives inside it, else abs.

    Tests construct floors under ``tmp_path`` which is outside the repo,
    so ``relative_to(REPO_ROOT)`` would raise. Use this helper for every
    human-facing path mention.
    """
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _load_floors(path: Path) -> Dict[str, float]:
    if not path.exists():
        print(f"ERROR: floors file missing: {path}", file=sys.stderr)
        sys.exit(EXIT_LINTER)
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "files" not in data:
        print(f"ERROR: {path} must have a top-level `files:` mapping", file=sys.stderr)
        sys.exit(EXIT_LINTER)
    return {str(k): float(v) for k, v in data["files"].items()}


def _read_coverage(xml_path: Path) -> Dict[str, float]:
    """Return {filename_relative_to_repo: line_rate_pct} from coverage.xml."""
    if not xml_path.exists():
        print(f"ERROR: coverage.xml missing at {xml_path}", file=sys.stderr)
        print(
            "Run `pytest --cov-report=xml` (or `make coverage`) first.",
            file=sys.stderr,
        )
        sys.exit(EXIT_LINTER)
    tree = ET.parse(xml_path)
    root = tree.getroot()
    out: Dict[str, float] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        if not filename:
            continue
        out[filename] = float(cls.get("line-rate", 0)) * 100.0
    return out


def _normalize(name: str) -> str:
    """Map any path flavor of a file to a stable key.

    ``pytest --cov=src/pearlalgo`` emits filenames like
    ``execution/tradovate/adapter.py`` (relative to the package root).
    Alternate setups emit ``pearlalgo/execution/...`` or
    ``src/pearlalgo/execution/...``. Strip both prefixes so floors can
    be written in any of those three styles and still match.
    """
    name = name.replace("\\", "/")
    if name.startswith("src/"):
        name = name[len("src/"):]
    if name.startswith("pearlalgo/"):
        name = name[len("pearlalgo/"):]
    return name


def check(
    coverage_xml: Path,
    floors_path: Path,
    *,
    tolerance_pct: float = 0.5,
) -> int:
    floors = _load_floors(floors_path)
    current = _read_coverage(coverage_xml)
    current_normalized = {_normalize(k): v for k, v in current.items()}

    failures: list[tuple[str, float, float]] = []
    successes: list[tuple[str, float, float]] = []

    for filename, floor in sorted(floors.items()):
        key = _normalize(filename)
        actual = current_normalized.get(key)
        if actual is None:
            failures.append((filename, floor, -1.0))
            continue
        if actual + tolerance_pct < floor:
            failures.append((filename, floor, actual))
        else:
            successes.append((filename, floor, actual))

    for name, floor, actual in successes:
        note = ""
        if actual - floor >= 1.0:
            note = " (↑ ratchet candidate)"
        print(f"OK   {name}: {actual:.2f}% ≥ floor {floor:.2f}%{note}")

    if not failures:
        return EXIT_OK

    print("", file=sys.stderr)
    print("COVERAGE FLOOR REGRESSIONS:", file=sys.stderr)
    for name, floor, actual in failures:
        if actual < 0:
            print(
                f"  {name}: missing from coverage.xml — run tests that exercise it",
                file=sys.stderr,
            )
        else:
            drop = floor - actual
            print(
                f"  {name}: {actual:.2f}% < floor {floor:.2f}% (drop {drop:.2f}%)",
                file=sys.stderr,
            )
    print(
        "\nFix: add tests OR if the drop is intentional, update the floor in "
        f"{_rel_or_abs(floors_path)} with a PR note explaining why.",
        file=sys.stderr,
    )
    return EXIT_REGRESSION


def write_floor(coverage_xml: Path, floors_path: Path) -> int:
    """Rewrite the floors file with the current measured coverage (manual
    ratchet-up). Never called by CI; operator runs it locally after a
    coverage-raising PR."""
    current = _read_coverage(coverage_xml)
    current_normalized = {_normalize(k): v for k, v in current.items()}

    if not floors_path.exists():
        print(f"ERROR: floors file missing: {floors_path}", file=sys.stderr)
        return EXIT_LINTER

    data: Dict[str, Any] = yaml.safe_load(floors_path.read_text()) or {}
    files = data.get("files") or {}
    updated = 0
    for filename in list(files.keys()):
        key = _normalize(filename)
        actual = current_normalized.get(key)
        if actual is None:
            print(f"skip {filename}: missing from coverage", file=sys.stderr)
            continue
        # Only allow raises (ratchet). A manual drop still requires a human
        # edit to this file with PR justification.
        if actual > float(files[filename]):
            print(f"raise {filename}: {files[filename]:.2f}% → {actual:.2f}%")
            files[filename] = round(actual, 2)
            updated += 1
    data["files"] = files
    floors_path.write_text(yaml.safe_dump(data, sort_keys=True))
    print(f"\nUpdated {updated} floor(s). Commit {_rel_or_abs(floors_path)}.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage-xml",
        type=Path,
        default=DEFAULT_COVERAGE_XML,
        help="Path to coverage.xml produced by pytest --cov-report=xml",
    )
    parser.add_argument(
        "--floors",
        type=Path,
        default=DEFAULT_FLOORS_PATH,
        help="Path to the floors yaml",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.5,
        help="Tolerance in percentage points for rounding jitter between runs",
    )
    parser.add_argument(
        "--write-floor",
        action="store_true",
        help="Manual ratchet: rewrite floors with current coverage where it has risen",
    )
    args = parser.parse_args(argv)

    if args.write_floor:
        return write_floor(args.coverage_xml, args.floors)
    return check(args.coverage_xml, args.floors, tolerance_pct=args.tolerance)


if __name__ == "__main__":
    sys.exit(main())
