#!/usr/bin/env python3
# ============================================================================
# Category: Testing/Validation
# Purpose: Enforce module boundary rules for src/pearlalgo/
# Usage: python3 scripts/testing/check_architecture_boundaries.py [--enforce]
# ============================================================================
"""
Architecture Boundary Checker

Statically analyzes Python imports under src/pearlalgo/ to enforce the
internal module dependency matrix documented in docs/PROJECT_SUMMARY.md.

Layers and allowed dependencies:
- utils:          may import utils, stdlib, third-party only
- config:         may import config, utils
- data_providers: may import data_providers, config, utils
- strategies:     may import strategies, config, utils, learning (for optional ML signal filtering)
- execution:      may import execution, config, utils (ATS execution layer)
- learning:       may import learning, config, utils (adaptive learning layer)
- market_agent:   may import any internal layer (orchestration)

Exit codes:
    0 - No violations (or --warn-only mode)
    1 - Violations found in --enforce mode
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Configuration: Allowed dependency matrix
# ---------------------------------------------------------------------------

# Layers under src/pearlalgo/
LAYERS = {"utils", "config", "data_providers", "strategies", "execution", "learning", "market_agent"}

# For each layer, which other pearlalgo.* layers it MAY import.
# Imports of stdlib and third-party packages are always allowed.
ALLOWED_IMPORTS: Dict[str, Set[str]] = {
    "utils": {"utils"},  # utils is self-contained
    "config": {"config", "utils"},
    "data_providers": {"data_providers", "config", "utils"},
    "strategies": {"strategies", "config", "utils", "learning"},  # learning for optional ML signal filtering
    "execution": {"execution", "config", "utils"},  # ATS execution layer
    "learning": {"learning", "config", "utils"},  # Adaptive learning layer
    "market_agent": LAYERS,  # orchestration layer can import anything
}


@dataclass
class Violation:
    """A single boundary violation."""

    source_file: Path
    source_layer: str
    target_layer: str
    import_statement: str
    line_number: int


@dataclass
class ScanResult:
    """Result of scanning a single file."""

    file_path: Path
    module_path: str
    layer: Optional[str]
    violations: List[Violation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Import extraction (AST-based)
# ---------------------------------------------------------------------------


def get_layer(module_path: str) -> Optional[str]:
    """
    Extract the layer name from a pearlalgo module path.

    Examples:
        pearlalgo.utils.logger         -> utils
        pearlalgo.strategies.trading_bots.pearl_bot_auto -> strategies
        pearlalgo.market_agent.service  -> market_agent
        pandas                          -> None (external)
    """
    if not module_path.startswith("pearlalgo."):
        return None
    parts = module_path.split(".")
    if len(parts) < 2:
        return None
    layer = parts[1]
    return layer if layer in LAYERS else None


def file_to_module_path(file_path: Path, src_root: Path) -> str:
    """Convert a file path to a dotted module path."""
    rel = file_path.relative_to(src_root)
    parts = list(rel.parts)
    # Remove .py extension from last part
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    # Handle __init__.py
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def resolve_relative_import(
    module_from: Optional[str], level: int, current_module: str
) -> str:
    """
    Resolve a relative import to an absolute module path.

    Args:
        module_from: The 'x.y' part of 'from ...x.y import z' (may be None for 'from . import z')
        level: Number of dots (1 for '.', 2 for '..', etc.)
        current_module: The dotted path of the file doing the import

    Returns:
        Absolute module path
    """
    parts = current_module.split(".")
    # Go up `level` packages
    if level > len(parts):
        # Invalid relative import (would go above root), return as-is
        return module_from or ""
    base_parts = parts[:-level] if level > 0 else parts
    if module_from:
        return ".".join(base_parts + module_from.split("."))
    return ".".join(base_parts)


def extract_imports(file_path: Path, current_module: str) -> List[Tuple[str, int]]:
    """
    Extract all import targets from a Python file.

    Returns list of (absolute_module_path, line_number).
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"  WARNING: Could not parse {file_path}: {e}")
        return []

    imports: List[Tuple[str, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # import x, import x.y
            for alias in node.names:
                imports.append((alias.name, node.lineno))

        elif isinstance(node, ast.ImportFrom):
            # from x import y, from . import y, from ..x import y
            level = node.level  # number of dots
            module = node.module  # may be None for 'from . import ...'

            if level == 0:
                # Absolute import: from x.y import z
                if module:
                    imports.append((module, node.lineno))
            else:
                # Relative import: resolve to absolute
                abs_module = resolve_relative_import(module, level, current_module)
                if abs_module:
                    imports.append((abs_module, node.lineno))

    return imports


# ---------------------------------------------------------------------------
# Scanning and violation detection
# ---------------------------------------------------------------------------


def scan_file(file_path: Path, src_root: Path) -> ScanResult:
    """Scan a single Python file for boundary violations."""
    module_path = file_to_module_path(file_path, src_root)
    source_layer = get_layer(module_path)

    result = ScanResult(
        file_path=file_path,
        module_path=module_path,
        layer=source_layer,
    )

    # If not in a recognized layer, skip (e.g., top-level __init__.py)
    if source_layer is None:
        return result

    allowed = ALLOWED_IMPORTS.get(source_layer, set())
    imports = extract_imports(file_path, module_path)

    for imported_module, line_no in imports:
        target_layer = get_layer(imported_module)

        # External imports are always allowed
        if target_layer is None:
            continue

        # Check if this import is allowed
        if target_layer not in allowed:
            result.violations.append(
                Violation(
                    source_file=file_path,
                    source_layer=source_layer,
                    target_layer=target_layer,
                    import_statement=imported_module,
                    line_number=line_no,
                )
            )

    return result


def scan_directory(src_root: Path) -> List[ScanResult]:
    """Scan all Python files under src_root/pearlalgo/."""
    results: List[ScanResult] = []
    pearlalgo_root = src_root / "pearlalgo"

    if not pearlalgo_root.exists():
        print(f"ERROR: {pearlalgo_root} does not exist")
        return results

    for py_file in pearlalgo_root.rglob("*.py"):
        # Skip __pycache__
        if "__pycache__" in py_file.parts:
            continue
        results.append(scan_file(py_file, src_root))

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_violations(results: List[ScanResult]) -> str:
    """Format violations into a human-readable report."""
    all_violations: List[Violation] = []
    for r in results:
        all_violations.extend(r.violations)

    if not all_violations:
        return ""

    # Group by source_layer -> target_layer
    grouped: Dict[Tuple[str, str], List[Violation]] = {}
    for v in all_violations:
        key = (v.source_layer, v.target_layer)
        grouped.setdefault(key, []).append(v)

    lines = []
    lines.append("")
    lines.append("BOUNDARY VIOLATIONS DETECTED")
    lines.append("-" * 60)

    for (src_layer, tgt_layer), violations in sorted(grouped.items()):
        lines.append(f"\n{src_layer} -> {tgt_layer} (forbidden)")
        for v in violations:
            rel_path = v.source_file
            try:
                rel_path = v.source_file.relative_to(Path.cwd())
            except ValueError:
                pass
            lines.append(f"  Line {v.line_number}: {rel_path}")
            lines.append(f"    import: {v.import_statement}")

    lines.append("")
    lines.append("-" * 60)

    return "\n".join(lines)


def print_summary(results: List[ScanResult], violations_count: int) -> None:
    """Print scan summary."""
    files_scanned = len(results)
    files_with_violations = sum(1 for r in results if r.violations)

    print(f"\nScanned {files_scanned} files")
    if violations_count > 0:
        print(f"Found {violations_count} violation(s) in {files_with_violations} file(s)")
    else:
        print("No boundary violations detected")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check module boundary rules for src/pearlalgo/"
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit with code 1 if violations are found (default: warn only)",
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=None,
        help="Path to src/ directory (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show all scanned files"
    )
    args = parser.parse_args()

    # Find src/ directory
    if args.src:
        src_root = args.src
    else:
        # Auto-detect: script is in scripts/testing/, src/ is at repo_root/src/
        script_dir = Path(__file__).parent
        repo_root = script_dir.parent.parent
        src_root = repo_root / "src"

    if not src_root.exists():
        print(f"ERROR: src directory not found at {src_root}")
        return 1

    print("Architecture Boundary Check")
    print("=" * 60)
    print(f"Source root: {src_root}")
    print()

    # Scan
    results = scan_directory(src_root)

    if args.verbose:
        for r in results:
            status = "VIOLATION" if r.violations else "OK"
            layer_info = f"[{r.layer}]" if r.layer else "[external]"
            try:
                rel = r.file_path.relative_to(Path.cwd())
            except ValueError:
                rel = r.file_path
            print(f"  {status:10} {layer_info:18} {rel}")

    # Count violations
    all_violations = [v for r in results for v in r.violations]
    violations_count = len(all_violations)

    # Report
    if violations_count > 0:
        report = format_violations(results)
        print(report)

    print_summary(results, violations_count)
    print("=" * 60)

    if violations_count > 0:
        if args.enforce:
            print("FAILED: Fix the above violations or update the boundary rules.")
            return 1
        else:
            print("WARNING: Violations found (warn-only mode, exiting with 0)")
            return 0
    else:
        print("PASSED: All imports respect module boundaries.")
        return 0


if __name__ == "__main__":
    sys.exit(main())









