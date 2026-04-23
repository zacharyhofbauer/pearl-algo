#!/usr/bin/env python3
"""Seed candles.db from the existing ``candle_cache_*.json`` rolling caches.

Every call to the live data provider writes a cache file like
``data/candle_cache_MNQ_5m_500.json`` containing the last ``N`` bars.
This script walks every cache file in the state tree and inserts the
bars into the SQLite archive. Idempotent — re-running it is a no-op
because the archive's PK (symbol, tf, ts) deduplicates on conflict.

Covers the boot-up corpus before we wire IBKR historical backfill
(Phase 4).  Gives us ~41h of 5m bars and ~8h of 1m bars immediately,
which is enough to verify the read endpoint and chart lazy-load work
end-to-end.

Usage:
    python scripts/ops/ingest_existing_caches.py --cache-dir data
    python scripts/ops/ingest_existing_caches.py --cache-dir /home/pearlalgo/var/pearl-algo/state/data
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Tuple

from pearlalgo.persistence.candle_archive import (
    ACCEPTED_TFS,
    get_archive,
)

logger = logging.getLogger("ingest_caches")

# Filename pattern: candle_cache_{SYMBOL}_{TF}_{N}.json
# TF is case-insensitive (existing files mix '1d' and '1D').
_FILENAME_RE = re.compile(
    r"^candle_cache_(?P<symbol>[A-Z]+)_(?P<tf>[0-9]+[smhd]|1D)_(?P<n>\d+)\.json$",
    re.IGNORECASE,
)


def parse_cache_filename(name: str) -> Tuple[str, str, int] | None:
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    tf = m.group("tf").lower()  # normalize '1D' -> '1d'
    if tf not in ACCEPTED_TFS:
        return None
    return m.group("symbol"), tf, int(m.group("n"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=Path("data"),
                    help="Directory containing candle_cache_*.json files")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and count but do not write to candles.db")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not args.cache_dir.is_dir():
        logger.error("cache dir not found: %s", args.cache_dir)
        return 2

    archive = get_archive()
    logger.info("archive db: %s", archive._db_path)  # noqa: SLF001

    total_files = 0
    total_bars = 0
    skipped_files = 0
    per_tf: dict = {}

    for path in sorted(args.cache_dir.glob("candle_cache_*.json")):
        parsed = parse_cache_filename(path.name)
        if parsed is None:
            skipped_files += 1
            logger.debug("skip unparseable: %s", path.name)
            continue
        symbol, tf, _n = parsed
        try:
            blob = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            logger.warning("skip %s: %s", path.name, e)
            skipped_files += 1
            continue
        bars = blob.get("candles") if isinstance(blob, dict) else None
        if not bars:
            skipped_files += 1
            continue
        total_files += 1
        total_bars += len(bars)
        per_tf[(symbol, tf)] = per_tf.get((symbol, tf), 0) + len(bars)
        if args.dry_run:
            continue
        n = archive.append_bars(
            symbol=symbol, tf=tf, bars=bars, source="cache_ingest",
        )
        logger.info("%s -> %d bars ingested", path.name, n)

    logger.info("SUMMARY: %d files ingested, %d skipped, %d bars", total_files, skipped_files, total_bars)
    for (sym, tf), n in sorted(per_tf.items()):
        logger.info("  %s %s: %d bars (pre-dedup)", sym, tf, n)

    if not args.dry_run:
        for row in archive.coverage():
            logger.info(
                "coverage: %s %s: %d rows, ts %d..%d",
                row["symbol"], row["tf"], row["n"], row["min_ts"], row["max_ts"],
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
