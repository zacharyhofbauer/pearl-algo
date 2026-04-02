from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_web_app_ci_uses_canonical_app_path() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "web-app-ci.yml").read_text(encoding="utf-8")

    assert "apps/pearl-algo-app/**" in workflow
    assert "working-directory: apps/pearl-algo-app" in workflow
    assert "cache-dependency-path: apps/pearl-algo-app/package-lock.json" in workflow
    assert "pearlalgo_web_app/**" not in workflow


def test_orphan_allowlist_is_current() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/testing/report_orphan_modules.py",
            "--enforce",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
