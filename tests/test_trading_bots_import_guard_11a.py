"""Tests for Issue 11-A — trading_bots test-import guard.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 3.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "testing" / "check_test_imports.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_test_imports", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_test_imports"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


def _write_allowlist(path: Path, entries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"allowed_tests": entries}, sort_keys=True))


def test_exit_codes_constants(mod):
    assert mod.EXIT_OK == 0
    assert mod.EXIT_VIOLATION == 1
    assert mod.EXIT_LINTER == 2


def test_imports_trading_bots_detects_from_import(mod, tmp_path: Path):
    f = tmp_path / "t.py"
    f.write_text("from pearlalgo.trading_bots.signal_generator import foo\n")
    assert mod._imports_trading_bots(f) is True


def test_imports_trading_bots_detects_plain_import(mod, tmp_path: Path):
    f = tmp_path / "t.py"
    f.write_text("import pearlalgo.trading_bots.signal_generator\n")
    assert mod._imports_trading_bots(f) is True


def test_imports_trading_bots_ignores_other_packages(mod, tmp_path: Path):
    f = tmp_path / "t.py"
    f.write_text(dedent("""
        from pearlalgo.strategies.composite_intraday import generate_signals
        import pearlalgo.utils.paths as paths
    """))
    assert mod._imports_trading_bots(f) is False


def test_imports_trading_bots_ignores_comments_and_strings(mod, tmp_path: Path):
    f = tmp_path / "t.py"
    f.write_text(dedent("""
        # from pearlalgo.trading_bots import x — this is a comment
        x = 'from pearlalgo.trading_bots.signal_generator import y'
    """))
    assert mod._imports_trading_bots(f) is False


def test_scan_passes_when_only_allowlisted_files_import(mod, tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    allowlist = tmp_path / "allow.yaml"

    (tests_dir / "test_legacy.py").write_text(
        "from pearlalgo.trading_bots.signal_generator import foo\n"
    )
    (tests_dir / "test_modern.py").write_text(
        "from pearlalgo.strategies.composite_intraday import generate_signals\n"
    )
    _write_allowlist(allowlist, ["tests/test_legacy.py"])

    # monkey-patch the canonical REPO_ROOT so the _relative helper works
    mod.REPO_ROOT = tmp_path
    rc = mod.scan(tests_dir, allowlist)
    assert rc == mod.EXIT_OK


def test_scan_fails_on_unauthorized_new_import(mod, tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    allowlist = tmp_path / "allow.yaml"

    (tests_dir / "test_legacy.py").write_text(
        "from pearlalgo.trading_bots.signal_generator import foo\n"
    )
    (tests_dir / "test_new_offender.py").write_text(
        "from pearlalgo.trading_bots.smc_signals import foo\n"
    )
    _write_allowlist(allowlist, ["tests/test_legacy.py"])

    mod.REPO_ROOT = tmp_path
    rc = mod.scan(tests_dir, allowlist)
    assert rc == mod.EXIT_VIOLATION


def test_scan_warns_on_stale_allowlist_entry(mod, tmp_path: Path, capsys):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    allowlist = tmp_path / "allow.yaml"

    (tests_dir / "test_migrated.py").write_text(
        "from pearlalgo.strategies.composite_intraday import generate_signals\n"
    )
    _write_allowlist(allowlist, ["tests/test_migrated.py"])  # stale — no longer imports

    mod.REPO_ROOT = tmp_path
    rc = mod.scan(tests_dir, allowlist)
    assert rc == mod.EXIT_OK
    out = capsys.readouterr().out
    assert "tests/test_migrated.py" in out
    assert "no longer needed" in out


def test_allowlist_matches_current_actual_importers():
    """Meta-test: the checked-in allowlist reflects today's reality.

    If this fails, either (a) someone added a new trading_bots import and
    forgot to update the allowlist (add it), or (b) someone migrated a
    test off trading_bots and forgot to drop it from the allowlist
    (remove it).
    """
    m = _load()
    rc = m.scan(REPO_ROOT / "tests", REPO_ROOT / ".github" / "trading_bots_test_allowlist.yaml")
    assert rc == m.EXIT_OK


def test_scan_handles_empty_tests_dir(mod, tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    allowlist = tmp_path / "allow.yaml"
    _write_allowlist(allowlist, [])

    mod.REPO_ROOT = tmp_path
    assert mod.scan(tests_dir, allowlist) == mod.EXIT_OK
