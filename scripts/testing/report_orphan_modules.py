#!/usr/bin/env python3
# ============================================================================
# Category: Testing/Validation
# Purpose: Report orphan modules under src/pearlalgo/
# Usage: python3 scripts/testing/report_orphan_modules.py
# ============================================================================
"""
Orphan Module Report

Builds a static import graph for src/pearlalgo and reports modules that are not
reachable from known entry points or from tests/scripts imports.

By default this is a report (exit code 0). In enforce mode, every remaining
orphan must be explicitly justified in the allowlist, and stale allowlist
entries fail the check.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "pearlalgo"
TESTS_ROOT = REPO_ROOT / "tests"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
ALLOWLIST_PATH = Path(__file__).with_name("orphan_allowlist.txt")

ENTRYPOINTS = {
    "pearlalgo",
    "pearlalgo.market_agent.main",
}


def _load_allowlist() -> Set[str]:
    if not ALLOWLIST_PATH.exists():
        return set()

    allowlist: Set[str] = set()
    for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        allowlist.add(entry)
    return allowlist


def _module_info(file_path: Path) -> Tuple[str, List[str]]:
    rel = file_path.relative_to(SRC_ROOT)
    parts = list(rel.parts)
    is_init = parts[-1] == "__init__.py"
    if is_init:
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    module = ".".join(["pearlalgo"] + parts)
    package_parts = ["pearlalgo"] + parts if is_init else ["pearlalgo"] + parts[:-1]
    return module, package_parts


def _resolve_relative(module_from: Optional[str], level: int, package_parts: List[str]) -> str:
    if level == 0:
        return module_from or ""
    if level > len(package_parts):
        return ""
    if level == 1:
        prefix = package_parts
    else:
        prefix = package_parts[: len(package_parts) - (level - 1)]
    if not module_from:
        return ".".join(prefix)
    return ".".join(prefix + module_from.split("."))


def _normalize_target(target: str, modules: Set[str]) -> Optional[str]:
    if not target:
        return None
    if target in modules:
        return target
    parts = target.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        parts.pop()
    return None


def _extract_imports(path: Path, module: str, package_parts: List[str]) -> Iterable[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("pearlalgo"):
                    yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module is not None:
                target = _resolve_relative(node.module, node.level, package_parts)
                yield target
            elif node.level and node.module is None:
                base = _resolve_relative(None, node.level, package_parts)
                for alias in node.names:
                    yield f"{base}.{alias.name}"
            elif node.module and node.module.startswith("pearlalgo"):
                yield node.module


def _collect_src_modules() -> Dict[str, Path]:
    modules: Dict[str, Path] = {}
    for path in SRC_ROOT.rglob("*.py"):
        module, _ = _module_info(path)
        modules[module] = path
    return modules


def _build_import_graph(modules: Dict[str, Path]) -> Dict[str, Set[str]]:
    graph: Dict[str, Set[str]] = {name: set() for name in modules}
    for module, path in modules.items():
        _, package_parts = _module_info(path)
        for imported in _extract_imports(path, module, package_parts):
            normalized = _normalize_target(imported, set(modules))
            if normalized:
                graph[module].add(normalized)
    return graph


def _collect_roots_from_paths(paths: Iterable[Path], modules: Set[str]) -> Set[str]:
    roots: Set[str] = set()
    for path in paths:
        if path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        package_parts = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("pearlalgo"):
                        normalized = _normalize_target(alias.name, modules)
                        if normalized:
                            roots.add(normalized)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("pearlalgo"):
                    normalized = _normalize_target(node.module, modules)
                    if normalized:
                        roots.add(normalized)
                elif node.level and node.module:
                    target = _resolve_relative(node.module, node.level, package_parts)
                    normalized = _normalize_target(target, modules)
                    if normalized:
                        roots.add(normalized)
    return roots


def _reachable_from_roots(graph: Dict[str, Set[str]], roots: Set[str]) -> Set[str]:
    reachable: Set[str] = set()
    stack = list(roots)
    while stack:
        module = stack.pop()
        if module in reachable:
            continue
        reachable.add(module)
        stack.extend(graph.get(module, set()))
    return reachable


def main() -> int:
    parser = argparse.ArgumentParser(description="Report orphan modules under src/pearlalgo/")
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Fail when unresolved or stale orphan allowlist entries are found.",
    )
    args = parser.parse_args()

    modules = _collect_src_modules()
    graph = _build_import_graph(modules)

    roots = set(ENTRYPOINTS)
    roots |= _collect_roots_from_paths(TESTS_ROOT.rglob("*.py"), set(modules))
    roots |= _collect_roots_from_paths(SCRIPTS_ROOT.rglob("*.py"), set(modules))

    reachable = _reachable_from_roots(graph, roots)
    orphans = sorted(m for m in modules if m not in reachable)
    allowlist = _load_allowlist()
    unexpected_orphans = sorted(m for m in orphans if m not in allowlist)
    stale_allowlist = sorted(m for m in allowlist if m not in orphans)

    print("Orphan Module Report")
    print("=" * 60)
    print(f"Total modules: {len(modules)}")
    print(f"Reachable:     {len(reachable)}")
    print(f"Orphans:       {len(orphans)}")
    print(f"Allowlisted:   {len(sorted(m for m in orphans if m in allowlist))}")
    print("-" * 60)

    if orphans:
        for module in orphans:
            path = modules[module].relative_to(REPO_ROOT)
            print(f"- {module} ({path})")
    else:
        print("No orphan modules detected.")

    if unexpected_orphans:
        print("-" * 60)
        print("Unexpected orphans (not allowlisted):")
        for module in unexpected_orphans:
            print(f"- {module}")

    if stale_allowlist:
        print("-" * 60)
        print("Stale allowlist entries (no longer orphaned):")
        for module in stale_allowlist:
            print(f"- {module}")

    if args.enforce and (unexpected_orphans or stale_allowlist):
        print("-" * 60)
        print("FAILED: Update scripts/testing/orphan_allowlist.txt or remove stale entries.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
