#!/usr/bin/env python3
# ============================================================================
# Category: Testing/Validation
# Purpose: Ensure config_schema.py references defaults.py instead of hardcoding
# Usage: python3 scripts/testing/check_config_defaults.py [--enforce]
# ============================================================================
"""
Config Defaults Consistency Checker

Scans config_schema.py for Pydantic Field(default=...) and bare assignments
that use hardcoded numeric or string literals instead of referencing
``pearlalgo.config.defaults``.

This prevents configuration drift where config_schema.py and defaults.py
define different default values for the same setting.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import List, Tuple


def _find_hardcoded_defaults(file_path: Path) -> List[Tuple[int, str]]:
    """
    Find lines in config_schema.py where Pydantic Field defaults are hardcoded
    numeric or string literals instead of referencing defaults.*.

    Returns list of (line_number, line_text) tuples.
    """
    issues: List[Tuple[int, str]] = []

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"  WARNING: Could not parse {file_path}: {e}")
        return issues

    lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Only check classes that look like Pydantic models (end with Config)
        if not node.name.endswith("Config"):
            continue

        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign):
                continue
            if stmt.value is None:
                continue

            # Check bare assignments like: field: type = 3600
            if isinstance(stmt.value, (ast.Constant,)):
                val = stmt.value.value
                # Only flag numeric and string literals (not bool)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    line = lines[stmt.lineno - 1] if stmt.lineno <= len(lines) else ""
                    # Skip if it already references defaults.*
                    if "defaults." in line:
                        continue
                    issues.append((stmt.lineno, line.strip()))
                elif isinstance(val, str):
                    line = lines[stmt.lineno - 1] if stmt.lineno <= len(lines) else ""
                    if "defaults." in line:
                        continue
                    issues.append((stmt.lineno, line.strip()))

            # Check Field(default=<literal>) calls
            elif isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                func_name = ""
                if isinstance(func, ast.Name):
                    func_name = func.id
                elif isinstance(func, ast.Attribute):
                    func_name = func.attr

                if func_name != "Field":
                    continue

                for kw in stmt.value.keywords:
                    if kw.arg != "default":
                        continue
                    if isinstance(kw.value, ast.Constant):
                        val = kw.value.value
                        if isinstance(val, (int, float)) and not isinstance(val, bool):
                            line = lines[stmt.lineno - 1] if stmt.lineno <= len(lines) else ""
                            if "defaults." in line:
                                continue
                            issues.append((stmt.lineno, line.strip()))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that config_schema.py uses defaults.py instead of hardcoded values"
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit with code 1 if hardcoded defaults are found",
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=None,
        help="Path to src/ directory (default: auto-detect)",
    )
    args = parser.parse_args()

    if args.src:
        src_root = args.src
    else:
        script_dir = Path(__file__).parent
        repo_root = script_dir.parent.parent
        src_root = repo_root / "src"

    schema_file = src_root / "pearlalgo" / "config" / "config_schema.py"
    if not schema_file.exists():
        print(f"ERROR: {schema_file} not found")
        return 1

    print("Config Defaults Consistency Check")
    print("=" * 60)
    print(f"Checking: {schema_file}")
    print()

    issues = _find_hardcoded_defaults(schema_file)

    if issues:
        print(f"Found {len(issues)} hardcoded default(s) that should reference defaults.py:")
        print()
        for lineno, line_text in issues:
            print(f"  Line {lineno}: {line_text}")
        print()
        print("These should use `defaults.CONSTANT_NAME` instead of literal values.")
        print("=" * 60)

        if args.enforce:
            print("FAILED: Fix the above hardcoded defaults.")
            return 1
        else:
            print(f"WARNING: {len(issues)} hardcoded default(s) found (warn-only mode)")
            return 0
    else:
        print("No hardcoded defaults found in Pydantic model fields.")
        print("=" * 60)
        print("PASSED: All config defaults reference defaults.py.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
