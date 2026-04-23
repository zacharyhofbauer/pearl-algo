#!/usr/bin/env python3
"""Pre-deploy smoke test for pearl-algo.

Runs after ``git reset`` on the Beelink to validate the new SHA before
any service restart. Fails fast with a non-zero exit code so
``deploy-from-mac.sh`` can automatically roll the Beelink back to the
prior SHA.

Checks (fast tier, always run):
  1. YAML validate ``config/live/tradovate_paper.yaml`` with the same
     MFF safety gates that ``.github/workflows/ci.yml`` enforces.
  2. Import the load-bearing runtime modules:
     ``pearlalgo.market_agent.service``,
     ``pearlalgo.market_agent.main``,
     ``pearlalgo.strategies.registry``,
     ``pearlalgo.execution.tradovate.adapter``,
     ``pearlalgo.api.server``.

Optional (``--full``): pytest subset (``not requires_ibkr and not
requires_telegram``) with ``--maxfail=3 -q``. Slower but catches
regressions the fast tier cannot.

Exit codes:
  0  smoke passed
  2  could not locate the repo root
  10 YAML validation failed
  11 one of the runtime-module imports failed
  12 pytest subset failed

Paired with ``scripts/ops/deploy-from-mac.sh``; see Issue 22-A in
``~/.claude/plans/this-session-work-cosmic-horizon.md``.
"""
from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_REPO = 2
EXIT_YAML = 10
EXIT_IMPORT = 11
EXIT_PYTEST = 12

_RUNTIME_MODULES: tuple[str, ...] = (
    "pearlalgo.market_agent.service",
    "pearlalgo.market_agent.main",
    "pearlalgo.strategies.registry",
    "pearlalgo.execution.tradovate.adapter",
    "pearlalgo.api.server",
)


def _log(message: str) -> None:
    print(f"[predeploy-smoke] {message}", flush=True)


def _fail(code: int, message: str) -> int:
    print(f"[predeploy-smoke][FAIL] {message}", file=sys.stderr, flush=True)
    return code


def smoke_yaml(repo_root: Path) -> int:
    import yaml

    cfg_path = repo_root / "config" / "live" / "tradovate_paper.yaml"
    if not cfg_path.exists():
        return _fail(EXIT_YAML, f"missing canonical live config: {cfg_path}")
    try:
        with cfg_path.open() as handle:
            cfg = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        return _fail(EXIT_YAML, f"YAML parse failed for {cfg_path.name}: {exc}")
    if not isinstance(cfg, dict):
        return _fail(EXIT_YAML, f"{cfg_path.name} did not parse to a mapping")

    exec_cfg = cfg.get("execution") or {}
    guardrails = cfg.get("guardrails") or {}
    mps = exec_cfg.get("max_position_size") or guardrails.get("max_position_size")
    mpspo = (
        exec_cfg.get("max_position_size_per_order")
        or guardrails.get("max_position_size_per_order")
    )

    errors: list[str] = []
    if mps is not None and mps > 5:
        errors.append(f"max_position_size={mps} exceeds MFF limit of 5")
    if mpspo is not None and mps is not None and mpspo > mps:
        errors.append(
            f"max_position_size_per_order={mpspo} exceeds max_position_size={mps}"
        )
    if errors:
        for err in errors:
            print(f"[predeploy-smoke][FAIL] {err}", file=sys.stderr, flush=True)
        return EXIT_YAML

    account = (cfg.get("account") or {}).get("name", "unknown")
    _log(f"YAML OK ({cfg_path.relative_to(repo_root)}, account={account})")
    return EXIT_OK


def smoke_imports() -> int:
    failed: list[str] = []
    for name in _RUNTIME_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 — smoke must catch any import failure
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    if failed:
        for detail in failed:
            print(f"[predeploy-smoke][FAIL] import {detail}", file=sys.stderr, flush=True)
        return EXIT_IMPORT
    _log(f"IMPORT OK ({len(_RUNTIME_MODULES)} modules)")
    return EXIT_OK


def smoke_pytest(repo_root: Path) -> int:
    _log("running pytest subset (not requires_ibkr and not requires_telegram)…")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "not requires_ibkr and not requires_telegram",
            "--maxfail=3",
            "-q",
        ],
        cwd=str(repo_root),
        check=False,
    )
    if proc.returncode != 0:
        return _fail(EXIT_PYTEST, f"pytest subset failed with exit code {proc.returncode}")
    _log("PYTEST SUBSET OK")
    return EXIT_OK


def resolve_repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "config" / "live").exists():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pearl-Algo pre-deploy smoke test.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also run the pytest subset (slower; ~60–180 s on the Beelink).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Override repo root detection (mainly for tests).",
    )
    args = parser.parse_args(argv)

    if args.repo_root is not None:
        repo_root = args.repo_root.resolve()
    else:
        repo_root = resolve_repo_root(Path(__file__).resolve())
    if repo_root is None or not (repo_root / "pyproject.toml").exists():
        return _fail(EXIT_REPO, f"cannot locate repo root from {__file__}")

    _log(f"root={repo_root}")

    status = smoke_yaml(repo_root)
    if status != EXIT_OK:
        return status

    status = smoke_imports()
    if status != EXIT_OK:
        return status

    if args.full:
        status = smoke_pytest(repo_root)
        if status != EXIT_OK:
            return status

    _log("all smoke checks passed")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
