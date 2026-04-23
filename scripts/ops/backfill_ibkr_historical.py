#!/usr/bin/env python3
"""One-shot IBKR historical backfill for the candle archive.

Phase 4 of docs/design/2026-04-23-all-time-archive.md. Pulls OHLCV
history from the IBKR gateway in respectful chunks and writes each bar
to candles.db via the Phase 1 archive. Idempotent (PK
``(symbol, tf, ts)`` dedupes on conflict) — safe to re-run.

Must run on the Beelink where the IBKR gateway is live. The script
uses the same ``IBKRDataProvider`` that the agent uses, so connection
config, credentials, and circuit-breaker behavior are identical.

IBKR pacing we respect:
  - Max ~60 historical requests per 10 minutes.
  - Max 6 identical requests per 2 seconds.
Between chunks we sleep ``--sleep-s`` seconds (default 11s). A
180-day 1m backfill takes ~6 chunks of 30 days each = ~1 minute of
actual requests + pacing = ~2–3 minutes total.

Usage:
  # 180 days of 5m MNQ (recommended for this account):
  python scripts/ops/backfill_ibkr_historical.py \\
      --symbol MNQ --tf 5m --lookback-days 180

  # Multi-TF, smaller granularities back a bit less:
  for tf in 1m 5m 15m 1h; do
      python scripts/ops/backfill_ibkr_historical.py \\
          --symbol MNQ --tf $tf --lookback-days 180
  done

  # Dry run: compute the chunks and exit without hitting IBKR:
  python scripts/ops/backfill_ibkr_historical.py \\
      --symbol MNQ --tf 5m --lookback-days 180 --dry-run

Checkpointing: after each chunk succeeds, the end-of-chunk timestamp
is written to ``data/backfill_checkpoints/<symbol>_<tf>.json``. A
re-run starts from that timestamp forward, so a crashed or killed run
resumes cleanly.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("backfill_ibkr")

# IBKR chunk sizes chosen so the server's hard cap (~2000 bars per
# response) isn't hit. Easy to expand later.
CHUNK_DAYS: Dict[str, int] = {
    "1m": 1,     # ~1,440 bars/day, well under the 2k cap
    "5m": 7,     # ~288 bars/day × 7 = 2,016 — right at the edge; see note
    "15m": 21,
    "30m": 45,
    "1h": 90,
    "4h": 180,
    "1d": 365,
}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--tf", required=True, choices=sorted(CHUNK_DAYS.keys()))
    ap.add_argument("--lookback-days", type=int, default=180,
                    help="How far back from now to backfill.")
    ap.add_argument("--sleep-s", type=float, default=11.0,
                    help="Sleep between IBKR requests to respect pacing.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print chunk plan and exit without hitting IBKR.")
    ap.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path("data/backfill_checkpoints"),
        help="Where to store resume checkpoints.",
    )
    return ap.parse_args()


def _plan_chunks(
    end: datetime, lookback_days: int, chunk_days: int
) -> List[Tuple[datetime, datetime]]:
    """Return chunks [(chunk_start, chunk_end), ...] from oldest to newest.

    Chunks are left-open right-closed; the first chunk starts at
    ``end - lookback_days``. Last chunk ends at ``end``. Adjacent
    chunks share a boundary — dedup at write-time via PK handles it.
    """
    start = end - timedelta(days=lookback_days)
    chunks: List[Tuple[datetime, datetime]] = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=chunk_days), end)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks


def _load_checkpoint(path: Path) -> Optional[datetime]:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        cp = raw.get("completed_through")
        if not cp:
            return None
        dt = datetime.fromisoformat(cp.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        logger.warning("failed to read checkpoint %s: %s", path, e)
        return None


def _save_checkpoint(path: Path, completed_through: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "completed_through": completed_through.astimezone(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def _dataframe_to_bars(df: Any, tf: str) -> List[Dict[str, Any]]:
    """Convert the IBKR provider's DataFrame to the archive's bar dict.

    The provider (IBKRProvider.fetch_historical) returns a DataFrame
    indexed by ``timestamp`` (tz-aware UTC) with columns ``open,
    high, low, close, volume``. We emit bar-open unix seconds (UTC)
    which is what ``candle_archive.append_bars`` expects.
    """
    if df is None or len(df) == 0:
        return []
    bars: List[Dict[str, Any]] = []
    # df.iterrows() yields (index, row). The index IS the timestamp —
    # the provider set it via df = df.set_index("timestamp").
    for idx, row in df.iterrows():
        ts = idx
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        try:
            unix_s = int(ts.timestamp())
            bars.append({
                "time": unix_s,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0.0) or 0.0),
            })
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return bars


def _fetch_one_chunk(
    provider: Any, symbol: str, tf: str, start: datetime, end: datetime
) -> List[Dict[str, Any]]:
    """Call the IBKR provider and convert the result."""
    df = provider.fetch_historical(symbol=symbol, start=start, end=end, timeframe=tf)
    bars = _dataframe_to_bars(df, tf)
    if bars:
        logger.info(
            "  fetched %d bars [%s .. %s]",
            len(bars),
            datetime.fromtimestamp(bars[0]["time"], tz=timezone.utc).isoformat(),
            datetime.fromtimestamp(bars[-1]["time"], tz=timezone.utc).isoformat(),
        )
    return bars


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    chunk_days = CHUNK_DAYS[args.tf]
    now = datetime.now(timezone.utc)
    chunks = _plan_chunks(now, args.lookback_days, chunk_days)
    logger.info(
        "plan: symbol=%s tf=%s lookback=%dd chunk_size=%dd -> %d chunks",
        args.symbol, args.tf, args.lookback_days, chunk_days, len(chunks),
    )

    cp_path = args.checkpoint_dir / f"{args.symbol}_{args.tf}.json"
    cp = _load_checkpoint(cp_path)
    if cp:
        logger.info("resuming from checkpoint: %s", cp.isoformat())
        chunks = [(s, e) for (s, e) in chunks if e > cp]
        logger.info("remaining chunks after resume: %d", len(chunks))

    if args.dry_run:
        for s, e in chunks:
            logger.info("  chunk: %s .. %s", s.isoformat(), e.isoformat())
        return 0

    # Delay-imports so --dry-run works on a laptop without IBKR libs.
    try:
        from pearlalgo.data_providers.factory import create_data_provider
        from pearlalgo.config.settings import get_settings
        from pearlalgo.persistence.candle_archive import get_archive
    except ImportError as e:
        logger.error("failed to import pearlalgo (are we on the Beelink venv?): %s", e)
        return 2

    settings = get_settings()
    provider = create_data_provider(
        os.environ.get("IBKR_PROVIDER_KIND", "ibkr"),
        settings=settings,
        host=os.environ.get("IB_HOST") or settings.ib_host,
        port=int(os.environ.get("IB_PORT") or settings.ib_port),
        client_id=int(
            os.environ.get("IB_CLIENT_ID_BACKFILL")
            or os.environ.get("IBKR_DATA_CLIENT_ID")
            or (settings.ib_data_client_id or settings.ib_client_id) + 7,
        ),
    )
    archive = get_archive()
    logger.info("archive db: %s", archive._db_path)  # noqa: SLF001

    total_written = 0
    for i, (s, e) in enumerate(chunks, 1):
        logger.info(
            "[%d/%d] fetching %s %s: %s .. %s",
            i, len(chunks), args.symbol, args.tf, s.isoformat(), e.isoformat(),
        )
        try:
            bars = _fetch_one_chunk(provider, args.symbol, args.tf, s, e)
        except Exception as exc:
            logger.error("chunk failed (%s); sleeping %.1fs and continuing", exc, args.sleep_s * 3)
            time.sleep(args.sleep_s * 3)
            continue

        if bars:
            n = archive.append_bars(
                symbol=args.symbol, tf=args.tf, bars=bars, source="ibkr_historical",
            )
            total_written += n
            _save_checkpoint(cp_path, e)
            logger.info("  upserted %d rows (running total: %d)", n, total_written)
        else:
            # Still advance checkpoint — this chunk returned nothing (weekend,
            # holiday, pre-contract history). No reason to retry.
            _save_checkpoint(cp_path, e)
            logger.info("  empty response; checkpointed and moving on")

        # Respect IBKR pacing — don't slam the gateway.
        if i < len(chunks):
            time.sleep(args.sleep_s)

    cov = {(r["symbol"], r["tf"]): r for r in archive.coverage()}
    mine = cov.get((args.symbol, args.tf))
    if mine:
        logger.info(
            "done. archive coverage for %s %s: %d rows, ts %d..%d",
            args.symbol, args.tf, mine["n"], mine["min_ts"], mine["max_ts"],
        )
    else:
        logger.info("done. archive is empty for %s %s (unexpected).", args.symbol, args.tf)
    logger.info("total rows written this run: %d", total_written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
