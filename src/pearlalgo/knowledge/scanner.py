from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class RepoScanConfig:
    root_dir: Path
    include_paths: List[str] = field(default_factory=lambda: ["src", "docs", "config", "scripts", "pyproject.toml"])
    exclude_globs: List[str] = field(
        default_factory=lambda: [
            ".env*",
            "data/**",
            "logs/**",
            "tests/artifacts/**",
            ".venv/**",
            "ibkr/**",
            ".git/**",
        ]
    )
    max_file_size_kb: int = 512


class RepoScanner:
    def __init__(self, config: RepoScanConfig):
        self.config = config
        self.root_dir = config.root_dir.resolve()

    def scan(self) -> List[Path]:
        files: List[Path] = []
        for entry in self.config.include_paths:
            path = (self.root_dir / entry).resolve()
            if not path.exists():
                continue
            if path.is_file():
                if self._should_include(path):
                    files.append(path)
                continue
            for root, dirs, filenames in os.walk(path):
                root_path = Path(root)
                dirs[:] = [d for d in dirs if not self._is_excluded_dir(root_path / d)]
                for name in filenames:
                    candidate = root_path / name
                    if self._should_include(candidate):
                        files.append(candidate)
        return files

    def _should_include(self, path: Path) -> bool:
        rel = self._rel_path(path)
        if self._matches_exclude(rel):
            return False
        if not path.is_file():
            return False
        if path.stat().st_size > self.config.max_file_size_kb * 1024:
            return False
        if not self._is_text_file(path):
            return False
        return True

    def _is_excluded_dir(self, path: Path) -> bool:
        rel = self._rel_path(path)
        return self._matches_exclude(rel)

    def _matches_exclude(self, rel_path: str) -> bool:
        rel_norm = rel_path.replace("\\", "/")
        for pattern in self.config.exclude_globs:
            if fnmatch.fnmatch(rel_norm, pattern):
                return True
        return False

    def _rel_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root_dir))
        except Exception:
            return str(path)

    def _is_text_file(self, path: Path) -> bool:
        try:
            with path.open("rb") as f:
                sample = f.read(2048)
            if b"\x00" in sample:
                return False
        except Exception:
            return False
        return True
