#!/usr/bin/env python3
"""
Strategy Selection Report CLI

CLI wrapper for the strategy report business logic.
Business logic is in: src/pearlalgo/analytics/strategy_report.py

Usage:
    python scripts/backtesting/strategy_selection.py
    python scripts/backtesting/strategy_selection.py --signals-path data/agent_state/MNQ/signals.jsonl
    python scripts/backtesting/strategy_selection.py --out-dir data/exports
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pearlalgo.analytics.strategy_report import build_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a drawdown-aware strategy selection report")
    parser.add_argument(
        "--signals-path",
        type=Path,
        default=Path("data/agent_state/MNQ/signals.jsonl"),
        help="Path to signals.jsonl with exited trades",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/agent_state/MNQ/exports"),
        help="Output directory for report JSON",
    )
    parser.add_argument(
        "--out-name",
        type=str,
        default=None,
        help="Optional output filename (defaults to strategy_selection_<timestamp>.json)",
    )
    args = parser.parse_args()

    if not args.signals_path.exists():
        raise FileNotFoundError(f"signals.jsonl not found: {args.signals_path}")

    report = build_report(args.signals_path)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.out_name:
        out_path = args.out_dir / args.out_name
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = args.out_dir / f"strategy_selection_{ts}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote strategy selection report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
