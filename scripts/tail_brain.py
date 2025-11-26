#!/usr/bin/env python
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tail trade brain log.")
    parser.add_argument("--date", help="YYYYMMDD; default today", default=None)
    args = parser.parse_args(argv)

    if args.date is None:
        from datetime import datetime, timezone
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    else:
        date_str = args.date

    path = Path("logs/trade_brain") / f"{date_str}.log"
    if not path.exists():
        print(f"Log not found: {path}")
        return 1
    subprocess.call(["tail", "-f", str(path)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
