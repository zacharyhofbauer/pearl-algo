"""SQLite-backed cumulative candle archive.

Motivation: the live agent writes rolling-window JSON caches
(``candle_cache_MNQ_5m_500.json`` etc.) that overwrite everything older
than ``N`` bars on each refresh. Anything past the window is lost. This
module maintains an append-only archive indexed by ``(symbol, tf, ts)``
so we can keep all history and later serve it to the chart, to
backtests, and to /api/candles endpoints.

Design: see ``docs/design/2026-04-23-all-time-archive.md``.

Usage:
    from pearlalgo.persistence.candle_archive import get_archive

    archive = get_archive()
    archive.append_bars(
        symbol="MNQ", tf="5m", source="ibkr_live",
        bars=[{"time": 1776757800, "open": 26826.75, "high": 26839.75,
               "low": 26816.0, "close": 26820.25, "volume": 3290}],
    )
    rows = archive.query_range(symbol="MNQ", tf="5m",
                               ts_from=1776757800, ts_to=None, limit=500)

Concurrency: one shared connection protected by a threading.Lock. SQLite
is in WAL mode so readers never block writers. Writes are batched inside
a single transaction per ``append_bars`` call.

Write rate (Issue 16-A, updated 2026-04-23): live runtime uses 1m as
primary TF plus 5m and 15m MTF overlays, so per-market the effective
write cadence can briefly peak at ~3 append_bars() calls per minute
during open-of-session bar bursts (still well below the lock's
throughput). Readers never block because of WAL. If a future expansion
pushes multiple symbols through the single archive, revisit the
single-connection design. ``archive.write_count()`` exposes the running
count for observability.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol      TEXT    NOT NULL,
    tf          TEXT    NOT NULL,
    ts          INTEGER NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      REAL    NOT NULL,
    source      TEXT    NOT NULL,
    inserted_at INTEGER NOT NULL,
    PRIMARY KEY (symbol, tf, ts)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_candles_lookup ON candles(symbol, tf, ts DESC);
CREATE INDEX IF NOT EXISTS idx_candles_source ON candles(source);
"""

# Valid timeframe labels the archive accepts (mirrors the data provider's
# supported TFs). New TFs can be added here without a migration.
ACCEPTED_TFS = frozenset({"1m", "5m", "15m", "30m", "1h", "4h", "1d"})


def _default_db_path() -> Path:
    """Where to put candles.db.

    Honors PEARL_CANDLES_DB if set (useful for tests / alt state trees).
    Otherwise mirrors the convention used for other state files — under
    the repo's ``data/`` directory which on the Beelink symlinks into
    ``~/var/pearl-algo/state/data/``.
    """
    env = os.environ.get("PEARL_CANDLES_DB")
    if env:
        return Path(env)
    # Follow PEARL_STATE_DIR if the caller set one; else use repo-relative.
    state_root = os.environ.get("PEARL_STATE_DIR")
    if state_root:
        return Path(state_root) / "candles.db"
    # Repo-relative fallback — works on Mac for tests and on Beelink
    # because `data/` is a symlink into ~/var/pearl-algo/state/data/.
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    return repo_root / "data" / "candles.db"


class CandleArchive:
    """Thread-safe SQLite writer/reader for the candle archive.

    Single shared connection in WAL mode. All methods are safe to call
    from any thread (FastAPI's request threads and the service loop).
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        # Issue 16-A: surface a running count of successful append_bars
        # calls so operators can see actual archive write rate (docstring
        # assumption was "≤1 bar / 15s / TF"; live is ~3 TFs in parallel).
        self._write_count = 0
        self._rows_written = 0
        self._ensure_schema()

    def write_count(self) -> int:
        """Running number of successful ``append_bars`` calls since boot."""
        return self._write_count

    def rows_written(self) -> int:
        """Running number of rows actually inserted or replaced since boot."""
        return self._rows_written

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                isolation_level=None,  # autocommit — we BEGIN/COMMIT explicitly
                timeout=30.0,
            )
            # WAL allows concurrent readers; synchronous=NORMAL is safe
            # for this use case (loss of the last ~1s of commits on hard
            # power-off is acceptable, we can always re-fetch from IBKR).
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA temp_store = MEMORY")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def append_bars(
        self,
        *,
        symbol: str,
        tf: str,
        bars: Iterable[Dict[str, Any]],
        source: str = "ibkr_live",
    ) -> int:
        """Insert-or-replace each bar in ``bars`` for ``(symbol, tf)``.

        Idempotent: re-inserting the same bar twice is a no-op because
        the PK ``(symbol, tf, ts)`` collides. On collision the new row
        wins — this is intentional so a fresh fetch can correct a bar
        we previously wrote with lower-quality data.

        Returns the number of rows actually inserted or replaced (which
        equals ``len(bars)`` after filtering obviously-bad rows).
        """
        if tf not in ACCEPTED_TFS:
            raise ValueError(f"unknown tf {tf!r}; must be one of {sorted(ACCEPTED_TFS)}")
        rows: List[tuple] = []
        now = int(time.time())
        for b in bars:
            try:
                ts = int(b["time"])
                o = float(b["open"])
                h = float(b["high"])
                lo = float(b["low"])
                c = float(b["close"])
                v = float(b.get("volume", 0.0))
            except (KeyError, TypeError, ValueError):
                continue
            if ts <= 0 or not all(map(lambda x: x > 0, (o, h, lo, c))):
                continue
            rows.append((symbol, tf, ts, o, h, lo, c, v, source, now))

        if not rows:
            return 0

        sql = (
            "INSERT INTO candles (symbol, tf, ts, open, high, low, close, volume, source, inserted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol, tf, ts) DO UPDATE SET "
            "  open=excluded.open, high=excluded.high, low=excluded.low, "
            "  close=excluded.close, volume=excluded.volume, "
            "  source=excluded.source, inserted_at=excluded.inserted_at"
        )
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("BEGIN")
                conn.executemany(sql, rows)
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise
            # Issue 16-A: count only after a successful commit.
            self._write_count += 1
            self._rows_written += len(rows)
        return len(rows)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def query_range(
        self,
        *,
        symbol: str,
        tf: str,
        ts_from: Optional[int] = None,
        ts_to: Optional[int] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Return candles in [ts_from, ts_to] ascending, capped at limit.

        Either bound may be None (open-ended).  Output shape matches the
        JSON cache files: ``{time, open, high, low, close, volume}``.
        """
        clauses = ["symbol = ?", "tf = ?"]
        params: List[Any] = [symbol, tf]
        if ts_from is not None:
            clauses.append("ts >= ?")
            params.append(int(ts_from))
        if ts_to is not None:
            clauses.append("ts <= ?")
            params.append(int(ts_to))
        where = " AND ".join(clauses)
        params.append(int(limit))
        sql = (
            f"SELECT ts AS time, open, high, low, close, volume "
            f"FROM candles WHERE {where} ORDER BY ts ASC LIMIT ?"
        )
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def count(self, symbol: Optional[str] = None, tf: Optional[str] = None) -> int:
        """Return the number of rows matching an optional (symbol, tf) filter."""
        clauses = []
        params: List[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if tf:
            clauses.append("tf = ?")
            params.append(tf)
        sql = "SELECT COUNT(*) FROM candles"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._lock:
            cur = self._get_conn().execute(sql, params)
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def coverage(self) -> List[Dict[str, Any]]:
        """Return one row per (symbol, tf) with min/max ts and count."""
        sql = (
            "SELECT symbol, tf, MIN(ts) AS min_ts, MAX(ts) AS max_ts, COUNT(*) AS n "
            "FROM candles GROUP BY symbol, tf ORDER BY symbol, tf"
        )
        with self._lock:
            cur = self._get_conn().execute(sql)
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Teardown (tests)
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_archive: Optional[CandleArchive] = None
_archive_lock = threading.Lock()


def get_archive() -> CandleArchive:
    """Return the process-wide ``CandleArchive`` singleton."""
    global _archive
    with _archive_lock:
        if _archive is None:
            _archive = CandleArchive()
        return _archive


def reset_for_tests() -> None:
    """Drop the singleton so tests can point at a fresh ``PEARL_CANDLES_DB``."""
    global _archive
    with _archive_lock:
        if _archive is not None:
            _archive.close()
        _archive = None
