#!/usr/bin/env python3
"""
Migrate data from old agent_state/{MARKET}/ structure to new broker-separated structure.

Old:
    data/agent_state/NQ/          -> data/archive/ibkr_virtual/  (archive)
    data/agent_state/TV_PAPER_EVAL/ -> data/tradovate/paper/     (active)

Usage:
    python scripts/maintenance/migrate_data_dirs.py
    python scripts/maintenance/migrate_data_dirs.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

MIGRATIONS = [
    {
        "source": "data/agent_state/NQ",
        "dest": "data/archive/ibkr_virtual",
        "description": "Archive IBKR Virtual NQ data",
        "files": [
            "state.json",
            "performance.json",
            "signals.jsonl",
            "trades.db",
            "events.jsonl",
            "policy_state.json",
            "telegram_prefs.json",
            "alert_state.json",
        ],
    },
    {
        "source": "data/agent_state/TV_PAPER_EVAL",
        "dest": "data/tradovate/paper",
        "description": "Migrate Tradovate Paper data",
        "files": [
            "state.json",
            "performance.json",
            "signals.jsonl",
            "trades.db",
            "events.jsonl",
            "challenge_state.json",
            "challenge_history.json",
            "tradovate_fills.json",
        ],
    },
]


def migrate(dry_run: bool = False) -> None:
    for migration in MIGRATIONS:
        src_dir = PROJECT_ROOT / migration["source"]
        dst_dir = PROJECT_ROOT / migration["dest"]

        print(f"\n{'[DRY RUN] ' if dry_run else ''}{migration['description']}")
        print(f"  From: {src_dir}")
        print(f"  To:   {dst_dir}")

        if not src_dir.exists():
            print(f"  SKIP: Source directory does not exist")
            continue

        if not dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        for filename in migration["files"]:
            src_file = src_dir / filename
            dst_file = dst_dir / filename
            if src_file.exists():
                if dry_run:
                    print(f"  COPY: {filename} ({src_file.stat().st_size:,} bytes)")
                else:
                    shutil.copy2(src_file, dst_file)
                    print(f"  COPIED: {filename} ({src_file.stat().st_size:,} bytes)")
                copied += 1
            else:
                print(f"  SKIP: {filename} (not found)")

        # Also copy exports/ directory if it exists
        src_exports = src_dir / "exports"
        if src_exports.exists() and src_exports.is_dir():
            dst_exports = dst_dir / "exports"
            if dry_run:
                export_count = sum(1 for _ in src_exports.rglob("*") if _.is_file())
                print(f"  COPY: exports/ ({export_count} files)")
            else:
                if dst_exports.exists():
                    shutil.rmtree(dst_exports)
                shutil.copytree(src_exports, dst_exports)
                export_count = sum(1 for _ in dst_exports.rglob("*") if _.is_file())
                print(f"  COPIED: exports/ ({export_count} files)")

        print(f"  Total: {copied} files migrated")

    print("\nDone." if not dry_run else "\n[DRY RUN] No files were actually copied.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate data to broker-separated directories")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without copying")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
