#!/usr/bin/env python3
"""
Verify that pearl_bot_auto is configured to send trades to Tradovate.

Prints execution config from tradovate_paper.yaml and confirms the signal path.
Run from repo root: python scripts/verify_tradovate_execution.py
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

def main():
    config_path = project_root / "config" / "accounts" / "tradovate_paper.yaml"
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 1

    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    exec_cfg = config.get("execution") or {}
    enabled = exec_cfg.get("enabled", False)
    armed = exec_cfg.get("armed", False)
    adapter = (exec_cfg.get("adapter") or "").strip().lower()
    whitelist = exec_cfg.get("symbol_whitelist") or []

    print("=== Tradovate Paper execution config ===\n")
    print(f"  execution.enabled:    {enabled}")
    print(f"  execution.armed:      {armed}")
    print(f"  execution.adapter:    {adapter}")
    print(f"  execution.symbol_whitelist: {whitelist}")
    print()

    ok = enabled and armed and adapter == "tradovate" and ("MNQ" in whitelist or not whitelist)
    if ok:
        print("  Config OK: signals from pearl_bot_auto will be sent to Tradovate when the agent")
        print("  runs with this config and strategy generates a signal (follower_execute path).")
    else:
        print("  Fix config:")
        if not enabled:
            print("    - Set execution.enabled: true")
        if not armed:
            print("    - Set execution.armed: true")
        if adapter != "tradovate":
            print("    - Set execution.adapter: tradovate")
        if whitelist and "MNQ" not in whitelist:
            print("    - Add MNQ to execution.symbol_whitelist (or leave empty for all)")

    print("\nTo confirm trades in real time:")
    print("  tail -f logs/agent_TV_PAPER.log | grep -E 'Processing.*signal|place_oso|Order placed|Order skipped'")
    print("\nSee also: scripts/verify_tradovate_signal_flow.md")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
