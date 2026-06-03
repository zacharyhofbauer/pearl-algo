from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pearl_sh_is_bash_syntax_clean() -> None:
    subprocess.run(["bash", "-n", "pearl.sh"], cwd=REPO_ROOT, check=True)


def test_quick_status_tracks_manual_pivot_not_tv_paper_runtime() -> None:
    result = subprocess.run(
        ["bash", "pearl.sh", "quick"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    output = result.stdout.strip()
    ok = "\u2705"
    assert output.startswith("PEARL:")
    assert "TV-Paper" not in output
    assert f"Pine {ok}" in output
    assert f"Alerts {ok}" in output
    assert f"ExecDisarmed {ok}" in output
    assert f"AutoBotDormant {ok}" in output
