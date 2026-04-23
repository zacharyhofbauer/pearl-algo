"""Tests for ``scripts/ops/predeploy_smoke.py``.

Issue 22-A (plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md``).
These tests validate that the pre-deploy smoke catches the failure classes
that would otherwise silently ship to the Beelink and require manual
rollback.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_PATH = REPO_ROOT / "scripts" / "ops" / "predeploy_smoke.py"


def _load_smoke_module():
    """Load predeploy_smoke.py as an in-memory module (it is not packaged)."""
    spec = importlib.util.spec_from_file_location("predeploy_smoke", SMOKE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def smoke():
    return _load_smoke_module()


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Minimal repo-shaped tmp dir with a pyproject.toml and config/live/."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fake'\n")
    (tmp_path / "config" / "live").mkdir(parents=True)
    return tmp_path


def _write_cfg(repo: Path, cfg: dict) -> Path:
    path = repo / "config" / "live" / "tradovate_paper.yaml"
    with path.open("w") as f:
        yaml.safe_dump(cfg, f)
    return path


def _minimal_valid_cfg() -> dict:
    return {
        "account": {"name": "tradovate_paper"},
        "execution": {"max_position_size": 1, "max_position_size_per_order": 1},
        "guardrails": {},
    }


def test_exit_code_constants_match_documented_contract(smoke):
    """Exit codes are public-ish contract with deploy-from-mac.sh — lock them."""
    assert smoke.EXIT_OK == 0
    assert smoke.EXIT_REPO == 2
    assert smoke.EXIT_YAML == 10
    assert smoke.EXIT_IMPORT == 11
    assert smoke.EXIT_PYTEST == 12


def test_smoke_yaml_happy_path(smoke, fake_repo):
    _write_cfg(fake_repo, _minimal_valid_cfg())
    assert smoke.smoke_yaml(fake_repo) == smoke.EXIT_OK


def test_smoke_yaml_missing_config_returns_yaml_exit(smoke, fake_repo):
    # No yaml written.
    assert smoke.smoke_yaml(fake_repo) == smoke.EXIT_YAML


def test_smoke_yaml_max_position_over_mff_cap(smoke, fake_repo):
    cfg = _minimal_valid_cfg()
    cfg["execution"]["max_position_size"] = 10
    _write_cfg(fake_repo, cfg)
    assert smoke.smoke_yaml(fake_repo) == smoke.EXIT_YAML


def test_smoke_yaml_per_order_exceeds_total(smoke, fake_repo):
    cfg = _minimal_valid_cfg()
    cfg["execution"]["max_position_size"] = 3
    cfg["execution"]["max_position_size_per_order"] = 5
    _write_cfg(fake_repo, cfg)
    assert smoke.smoke_yaml(fake_repo) == smoke.EXIT_YAML


def test_smoke_yaml_parse_error(smoke, fake_repo):
    path = fake_repo / "config" / "live" / "tradovate_paper.yaml"
    path.write_text("this: is: not: valid yaml: [unterminated")
    assert smoke.smoke_yaml(fake_repo) == smoke.EXIT_YAML


def test_smoke_yaml_not_a_mapping(smoke, fake_repo):
    path = fake_repo / "config" / "live" / "tradovate_paper.yaml"
    path.write_text("- just\n- a\n- list\n")
    assert smoke.smoke_yaml(fake_repo) == smoke.EXIT_YAML


def test_smoke_yaml_mff_cap_boundary_exact_5_passes(smoke, fake_repo):
    cfg = _minimal_valid_cfg()
    cfg["execution"]["max_position_size"] = 5
    cfg["execution"]["max_position_size_per_order"] = 5
    _write_cfg(fake_repo, cfg)
    assert smoke.smoke_yaml(fake_repo) == smoke.EXIT_OK


def test_smoke_yaml_reads_guardrails_fallback(smoke, fake_repo):
    # When execution.max_position_size absent, the smoke falls back to
    # guardrails.max_position_size (same rule as CI config validation).
    cfg = _minimal_valid_cfg()
    cfg["execution"] = {}
    cfg["guardrails"]["max_position_size"] = 6  # exceeds MFF cap
    _write_cfg(fake_repo, cfg)
    assert smoke.smoke_yaml(fake_repo) == smoke.EXIT_YAML


def test_smoke_imports_happy_path(smoke):
    # In the editable-install test env, every runtime module is importable.
    assert smoke.smoke_imports() == smoke.EXIT_OK


def test_resolve_repo_root_finds_actual_repo(smoke):
    found = smoke.resolve_repo_root(SMOKE_PATH)
    assert found == REPO_ROOT


def test_resolve_repo_root_none_when_not_a_repo(smoke, tmp_path: Path):
    # tmp_path has no pyproject.toml.
    assert smoke.resolve_repo_root(tmp_path) is None


def test_main_returns_repo_exit_when_root_missing(smoke, tmp_path: Path):
    # Point --repo-root at a dir with no pyproject.toml.
    assert smoke.main(["--repo-root", str(tmp_path)]) == smoke.EXIT_REPO


def test_main_happy_path_fast_mode_against_real_repo(smoke):
    # Fast mode (no --full): YAML + imports only.
    assert smoke.main([]) == smoke.EXIT_OK


def test_main_surfaces_yaml_failure_through_main(smoke, fake_repo):
    cfg = _minimal_valid_cfg()
    cfg["execution"]["max_position_size"] = 99
    _write_cfg(fake_repo, cfg)
    assert smoke.main(["--repo-root", str(fake_repo)]) == smoke.EXIT_YAML
