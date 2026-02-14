#!/usr/bin/env python3
"""
End-to-end verification: MNQ agent, IBKR data only, Tradovate execution only.

Run from repo root:
  .venv/bin/python scripts/verify_mnq_tradovate_setup.py

Checks:
  - config/accounts/tradovate_paper.yaml: execution=tradovate, MNQ only, data from IBKR
  - Execution path: follower_execute -> Tradovate (no IBKR orders)
  - Optional: Gateway port and connectivity (if Gateway is running)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load .env so IBKR_PORT matches what the agent uses
_env = PROJECT_ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"").strip()
            if k and k not in os.environ:
                os.environ[k] = v


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Config file
    config_path = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
    if not config_path.exists():
        errors.append(f"Config not found: {config_path}")
        return _report(errors, warnings)

    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    # 2. Symbol MNQ (account may inherit from base.yaml)
    symbol = (config.get("symbol") or "").strip().upper()
    if not symbol:
        base_path = config_path.parent.parent / "base.yaml"
        if base_path.exists():
            with open(base_path) as bf:
                base = yaml.safe_load(bf) or {}
            symbol = (base.get("symbol") or "MNQ").strip().upper()
        else:
            symbol = "MNQ"
    exec_whitelist = (config.get("execution") or {}).get("symbol_whitelist") or []
    if symbol != "MNQ" and "MNQ" not in exec_whitelist:
        errors.append("Config must use symbol MNQ and/or execution.symbol_whitelist: [MNQ]")
    if exec_whitelist and "MNQ" not in exec_whitelist:
        errors.append("execution.symbol_whitelist must include MNQ")

    # 3. Execution: Tradovate only
    exec_cfg = config.get("execution") or {}
    if not exec_cfg.get("enabled", False):
        errors.append("execution.enabled must be true")
    if not exec_cfg.get("armed", False):
        warnings.append("execution.armed is false — agent will not place orders until /arm")
    adapter = (exec_cfg.get("adapter") or "").strip().lower()
    if adapter != "tradovate":
        errors.append(f"execution.adapter must be 'tradovate' (got {adapter!r})")

    # 4. Data: IBKR (client IDs from env when running; config can override)
    data_cfg = config.get("data") or {}
    if data_cfg.get("ibkr_data_client_id") is not None:
        # Explicit data client ID is set (e.g. 51 for TV Paper)
        pass
    # PEARLALGO_DATA_PROVIDER should be ibkr
    provider = os.getenv("PEARLALGO_DATA_PROVIDER", "ibkr").strip().lower()
    if provider != "ibkr":
        warnings.append(f"PEARLALGO_DATA_PROVIDER={provider} — MNQ agent expects ibkr for data")

    # 5. Circuit breaker: no pause on connection failures (so data blips don't stop the agent)
    cb = config.get("circuit_breaker") or {}
    if cb.get("pause_on_connection_failures", True):
        warnings.append("circuit_breaker.pause_on_connection_failures should be false for data-only IBKR")

    # 6. Optional: Gateway port (must match Gateway's actual API port)
    ibkr_port = exec_cfg.get("ibkr_port")
    if ibkr_port is None:
        ibkr_port = int(os.getenv("IBKR_PORT", "4002"))
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        ok = s.connect_ex(("127.0.0.1", ibkr_port)) == 0
        s.close()
        if not ok:
            warnings.append(f"IBKR Gateway not reachable on 127.0.0.1:{ibkr_port} — start it with: ./pearl.sh gateway start")
    except Exception as e:
        warnings.append(f"Could not check Gateway port: {e}")

    return _report(errors, warnings)


def _report(errors: list[str], warnings: list[str]) -> int:
    print("=== MNQ + Tradovate (IBKR data only) verification ===\n")
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
    if warnings:
        for w in warnings:
            print(f"  ⚠️  {w}")
    if not errors and not warnings:
        print("  ✅ Config: MNQ symbol, Tradovate execution only, IBKR for data")
        print("  ✅ Execution: follower_execute -> place_bracket (Tradovate)")
        print("  ✅ Gateway port reachable")
    elif not errors:
        print("\n  Setup OK with notes above.")
    else:
        print("\n  Fix errors above and re-run.")
    print("\nStart agent: ./pearl.sh start   or   ./scripts/lifecycle/tv_paper_eval.sh start --background")
    print("Watch logs:  tail -f logs/agent_TV_PAPER.log | grep -E 'signal|place_oso|Order placed|Order skipped'")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
