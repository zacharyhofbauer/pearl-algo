#!/usr/bin/env python3
# ============================================================================
# Category: Testing/Validation
# Purpose: Validate doc path references exist in repo
# Usage: python3 scripts/testing/check_doc_references.py
# ============================================================================
"""
Documentation Reference Checker

Scans README.md and docs/*.md for path references and verifies they exist in
the repository. Prevents stale references (paths, scripts, modules) from
drifting over time.

Exit codes:
    0 - All referenced paths exist (or are intentionally ignored)
    1 - Missing path references found
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"

ROOT_FILES = {
    "README.md",
    "pyproject.toml",
    "Makefile",
    "pytest.ini",
    "mypy.ini",
    "env.example",
    "Dockerfile",
    ".gitignore",
    ".cursorignore",
}

PATH_PREFIXES = (
    "src/",
    "scripts/",
    "docs/",
    "config/",
    "tests/",
    "models/",
    "resources/",
    ".github/",
    ".devcontainer/",
)

RUNTIME_PREFIXES = (
    "data/",
    "logs/",
    "ibkr/",
)

LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
# Inline code only (avoid accidentally scanning fenced code blocks like ```bash ... ```)
CODE_PATTERN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
PATH_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:\./)?(?:"
    r"src|scripts|docs|config|tests|models|resources|ibkr|\.github|\.devcontainer|data|logs"
    r")/[^\s`]+"
    r"|"
    r"(?<![A-Za-z0-9_])(?:README\.md|pyproject\.toml|Makefile|pytest\.ini|mypy\.ini|env\.example|Dockerfile|\.gitignore|\.cursorignore)"
)


def _is_ignorable(path_str: str) -> bool:
    if path_str.startswith(("http://", "https://", "mailto:", "#")):
        return True
    if path_str.startswith(("/", "~")):
        return True
    if any(token in path_str for token in ("<", ">", "{", "}", "*", "$")):
        return True
    return False


def _normalize_path(path_str: str) -> str:
    if path_str.startswith("./"):
        path_str = path_str[2:]
    return path_str.strip(").,;:[]")


def _extract_paths_from_code(code_text: str) -> Iterable[str]:
    for match in PATH_TOKEN_PATTERN.finditer(code_text):
        token = _normalize_path(match.group(0))
        if _is_ignorable(token):
            continue
        yield token


def _extract_links(text: str) -> Iterable[str]:
    for match in LINK_PATTERN.finditer(text):
        target = match.group(1).strip()
        if _is_ignorable(target):
            continue
        yield _normalize_path(target)


def _extract_code_paths(text: str) -> Iterable[str]:
    for match in CODE_PATTERN.finditer(text):
        code = match.group(1).strip()
        for token in _extract_paths_from_code(code):
            yield token


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _scan_file(path: Path) -> List[Tuple[Path, int, str]]:
    text = path.read_text(encoding="utf-8")
    missing: List[Tuple[Path, int, str]] = []

    for match in LINK_PATTERN.finditer(text):
        target = match.group(1).strip()
        if _is_ignorable(target):
            continue
        target = _normalize_path(target)
        if not _path_exists(target):
            missing.append((path, _line_for_offset(text, match.start()), target))

    for match in CODE_PATTERN.finditer(text):
        code = match.group(1).strip()
        for token in _extract_paths_from_code(code):
            if not _path_exists(token):
                missing.append((path, _line_for_offset(text, match.start()), token))

    return missing


def _path_exists(path_str: str) -> bool:
    if path_str.startswith(RUNTIME_PREFIXES):
        return True
    if path_str in ROOT_FILES:
        return (REPO_ROOT / path_str).exists()
    if path_str.startswith(PATH_PREFIXES):
        return (REPO_ROOT / path_str).exists()
    return True  # Ignore unknown prefixes (commands, non-path tokens, etc.)


def main() -> int:
    doc_files = [REPO_ROOT / "README.md"]
    if DOCS_DIR.exists():
        doc_files.extend(sorted(DOCS_DIR.glob("*.md")))

    missing_refs: List[Tuple[Path, int, str]] = []
    for doc in doc_files:
        if not doc.exists():
            continue
        missing_refs.extend(_scan_file(doc))

    if missing_refs:
        print("Documentation Reference Audit")
        print("=" * 60)
        print("❌ Missing path references detected:")
        print("-" * 60)
        for file_path, line_no, ref in missing_refs:
            rel = file_path.relative_to(REPO_ROOT)
            print(f"{rel}:{line_no}: {ref}")
        print("-" * 60)
        print("FAILED: Update docs or restore referenced paths.")
        return 1

    print("Documentation Reference Audit")
    print("=" * 60)
    print("✅ All referenced paths exist")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
