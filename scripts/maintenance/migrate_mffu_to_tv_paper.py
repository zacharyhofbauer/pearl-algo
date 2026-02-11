#!/usr/bin/env python3
"""
One-time migration: rename the "mffu" key to "tv_paper" in challenge_state.json files.

Usage:
    python scripts/maintenance/migrate_mffu_to_tv_paper.py [--dry-run]

The script:
1. Scans data/agent_state/ recursively for challenge_state.json files.
2. If a file contains a top-level "mffu" key, renames it to "tv_paper".
3. Backs up the original file as challenge_state.json.bak before modifying.
4. Reports what was changed.

Pass --dry-run to preview changes without writing.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def migrate_file(path: Path, *, dry_run: bool = False) -> bool:
    """Migrate a single challenge_state.json file.

    Returns True if the file was (or would be) modified.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  SKIP  {path} — cannot read: {exc}")
        return False

    if not isinstance(data, dict):
        return False

    if "mffu" not in data:
        return False

    if "tv_paper" in data:
        print(f"  SKIP  {path} — already has 'tv_paper' key (and 'mffu' key)")
        return False

    if dry_run:
        print(f"  WOULD MIGRATE  {path}")
        return True

    # Back up original
    backup = path.with_suffix(".json.bak")
    shutil.copy2(path, backup)

    # Rename key
    data["tv_paper"] = data.pop("mffu")

    # Write atomically via temp file
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)

    print(f"  MIGRATED  {path}  (backup: {backup.name})")
    return True


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    project_root = Path(__file__).resolve().parent.parent.parent
    state_root = project_root / "data" / "agent_state"

    if not state_root.exists():
        print(f"No agent_state directory found at {state_root}")
        return 0

    files = list(state_root.rglob("challenge_state.json"))
    if not files:
        print("No challenge_state.json files found.")
        return 0

    print(f"Found {len(files)} challenge_state.json file(s):")
    migrated = sum(1 for f in files if migrate_file(f, dry_run=dry_run))

    mode = "DRY RUN" if dry_run else "DONE"
    print(f"\n{mode}: {migrated}/{len(files)} file(s) {'would be ' if dry_run else ''}migrated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
