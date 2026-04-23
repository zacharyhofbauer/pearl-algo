"""Tests for Issue 9-A — money-path coverage floor checker.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 2.

Exercises the linter script's public behavior against synthetic
coverage.xml + floors.yaml inputs so the CI gate's semantics are pinned.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "testing" / "check_money_path_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_money_path_coverage", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_money_path_coverage"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


def _write_coverage_xml(path: Path, files: dict[str, float]) -> None:
    """Emit a minimal coverage.xml containing the given file→percent map."""
    classes = []
    for name, pct in files.items():
        rate = pct / 100.0
        classes.append(
            f'<class filename="{name}" line-rate="{rate}"><methods/><lines/></class>'
        )
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<coverage><packages><package><classes>"
        + "".join(classes)
        + "</classes></package></packages></coverage>"
    )
    path.write_text(xml)


def _write_floors(path: Path, files: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"files": files}, sort_keys=True))


def test_exit_codes_constants(mod):
    assert mod.EXIT_OK == 0
    assert mod.EXIT_REGRESSION == 1
    assert mod.EXIT_LINTER == 2


def test_passes_when_all_files_at_or_above_floor(mod, tmp_path: Path):
    xml = tmp_path / "coverage.xml"
    floors = tmp_path / "floors.yaml"
    _write_coverage_xml(
        xml,
        {"pearlalgo/execution/tradovate/adapter.py": 50.0},
    )
    _write_floors(floors, {"pearlalgo/execution/tradovate/adapter.py": 40.0})
    rc = mod.main(["--coverage-xml", str(xml), "--floors", str(floors)])
    assert rc == mod.EXIT_OK


def test_passes_with_src_prefix_normalization(mod, tmp_path: Path):
    xml = tmp_path / "coverage.xml"
    floors = tmp_path / "floors.yaml"
    # Some coverage emitters prefix with src/, floors use the canonical form
    _write_coverage_xml(xml, {"src/pearlalgo/execution/tradovate/adapter.py": 50.0})
    _write_floors(floors, {"pearlalgo/execution/tradovate/adapter.py": 40.0})
    rc = mod.main(["--coverage-xml", str(xml), "--floors", str(floors)])
    assert rc == mod.EXIT_OK


def test_regression_detected(mod, tmp_path: Path):
    xml = tmp_path / "coverage.xml"
    floors = tmp_path / "floors.yaml"
    _write_coverage_xml(xml, {"pearlalgo/market_agent/signal_handler.py": 20.0})
    _write_floors(floors, {"pearlalgo/market_agent/signal_handler.py": 40.0})
    rc = mod.main(["--coverage-xml", str(xml), "--floors", str(floors)])
    assert rc == mod.EXIT_REGRESSION


def test_tolerance_absorbs_rounding_jitter(mod, tmp_path: Path):
    """A 0.3pp drop is within default 0.5pp tolerance; must not fail."""
    xml = tmp_path / "coverage.xml"
    floors = tmp_path / "floors.yaml"
    _write_coverage_xml(xml, {"pearlalgo/x.py": 39.7})
    _write_floors(floors, {"pearlalgo/x.py": 40.0})
    rc = mod.main(["--coverage-xml", str(xml), "--floors", str(floors)])
    assert rc == mod.EXIT_OK


def test_missing_file_flagged_as_regression(mod, tmp_path: Path):
    """Floor names a file that coverage.xml doesn't include — treat as a
    regression so nobody can sneak a money-path file out of the gate."""
    xml = tmp_path / "coverage.xml"
    floors = tmp_path / "floors.yaml"
    _write_coverage_xml(xml, {"pearlalgo/other.py": 90.0})
    _write_floors(floors, {"pearlalgo/execution/tradovate/adapter.py": 30.0})
    rc = mod.main(["--coverage-xml", str(xml), "--floors", str(floors)])
    assert rc == mod.EXIT_REGRESSION


def test_missing_coverage_xml_is_linter_error(mod, tmp_path: Path):
    floors = tmp_path / "floors.yaml"
    _write_floors(floors, {"pearlalgo/x.py": 30.0})
    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--coverage-xml", str(tmp_path / "nope.xml"), "--floors", str(floors)])
    assert exc_info.value.code == mod.EXIT_LINTER


def test_malformed_floors_is_linter_error(mod, tmp_path: Path):
    xml = tmp_path / "coverage.xml"
    bad = tmp_path / "bad.yaml"
    _write_coverage_xml(xml, {"pearlalgo/x.py": 50.0})
    bad.write_text(textwrap.dedent("""
        not_a_files_key: 1
    """))
    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--coverage-xml", str(xml), "--floors", str(bad)])
    assert exc_info.value.code == mod.EXIT_LINTER


def test_write_floor_raises_when_coverage_higher(mod, tmp_path: Path):
    xml = tmp_path / "coverage.xml"
    floors = tmp_path / "floors.yaml"
    _write_coverage_xml(xml, {"pearlalgo/x.py": 65.3})
    _write_floors(floors, {"pearlalgo/x.py": 40.0})
    rc = mod.main(["--coverage-xml", str(xml), "--floors", str(floors), "--write-floor"])
    assert rc == mod.EXIT_OK
    after = yaml.safe_load(floors.read_text())
    assert after["files"]["pearlalgo/x.py"] == 65.3


def test_write_floor_never_lowers(mod, tmp_path: Path):
    """Ratchet-up only. Never silently lower a floor."""
    xml = tmp_path / "coverage.xml"
    floors = tmp_path / "floors.yaml"
    _write_coverage_xml(xml, {"pearlalgo/x.py": 20.0})
    _write_floors(floors, {"pearlalgo/x.py": 40.0})
    rc = mod.main(["--coverage-xml", str(xml), "--floors", str(floors), "--write-floor"])
    assert rc == mod.EXIT_OK
    after = yaml.safe_load(floors.read_text())
    assert after["files"]["pearlalgo/x.py"] == 40.0  # unchanged
