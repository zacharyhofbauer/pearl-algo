#!/usr/bin/env python3
"""
Multi-market smoke test (no IBKR required).

Validates that the same codebase can load per-market config + isolate state dirs
using environment variables, without duplicating files.

Usage:
  python3 scripts/testing/smoke_multi_market.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def main() -> None:
    project_root = _project_root()
    markets = ["NQ", "ES", "GC"]

    print("=== Smoke: multi-market config + state isolation ===")
    for market in markets:
        config_path = project_root / "config" / "markets" / f"{market.lower()}.yaml"
        if not config_path.exists():
            raise SystemExit(f"Missing config example: {config_path}")

        with tempfile.TemporaryDirectory(prefix=f"pearlalgo_smoke_{market}_") as tmp:
            state_dir = Path(tmp) / "state"
            env = os.environ.copy()
            env["PEARLALGO_MARKET"] = market
            env["PEARLALGO_CONFIG_PATH"] = str(config_path)
            env["PEARLALGO_STATE_DIR"] = str(state_dir)

            # Import inside the loop to ensure env is honored by loaders.
            import subprocess
            import sys

            code = (
                "import os; "
                "from pearlalgo.config.config_file import load_config_yaml; "
                "from pearlalgo.config.config_loader import load_service_config; "
                "from pearlalgo.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG; "
                "from pearlalgo.utils.paths import ensure_state_dir; "
                "cfg = load_config_yaml(); "
                "svc = load_service_config(validate=False); "
                "state = ensure_state_dir(); "
                "config = PEARL_BOT_CONFIG.copy(); "
                "print('symbol', cfg.get('symbol')); "
                "print('timeframe', cfg.get('timeframe')); "
                "print('market', os.getenv('PEARLALGO_MARKET')); "
                "print('state_dir', str(state)); "
                "print('trading_bot_enabled', bool((svc.get('trading_bot') or {}).get('enabled', False))); "
                "print('strategy_symbol', config.get('symbol'))"
            )

            subprocess.run(
                [sys.executable, "-c", code],
                check=True,
                env=env,
                cwd=str(project_root),
            )

        print(f"✅ {market} ok")

    print("✅ All markets ok")


if __name__ == "__main__":
    main()

