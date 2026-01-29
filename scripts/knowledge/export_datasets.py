#!/usr/bin/env python3
# ============================================================================
# Category: Knowledge
# Purpose: Export PEARL chat + patch datasets for fine-tuning
# Usage:
#   python3 scripts/knowledge/export_datasets.py --market NQ --out-dir reports
# ============================================================================
from __future__ import annotations

import argparse
from pathlib import Path

from pearlalgo.utils.paths import ensure_state_dir


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Export PEARL datasets")
    parser.add_argument("--market", default="NQ", help="Market label")
    parser.add_argument("--state-dir", default=None, help="Override state directory")
    parser.add_argument("--out-dir", default="reports", help="Output directory")
    args = parser.parse_args()

    state_dir = ensure_state_dir(Path(args.state_dir) if args.state_dir else None)
    exports_dir = state_dir / "exports"
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = (Path(__file__).resolve().parent.parent.parent / out_dir).resolve()

    chat_src = exports_dir / "pearl_chat_dataset.jsonl"
    patch_src = exports_dir / "pearl_patch_dataset.jsonl"

    chat_ok = _copy_if_exists(chat_src, out_dir / "pearl_chat_dataset.jsonl")
    patch_ok = _copy_if_exists(patch_src, out_dir / "pearl_patch_dataset.jsonl")

    print(f"Chat dataset exported: {chat_ok} -> {out_dir / 'pearl_chat_dataset.jsonl'}")
    print(f"Patch dataset exported: {patch_ok} -> {out_dir / 'pearl_patch_dataset.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
