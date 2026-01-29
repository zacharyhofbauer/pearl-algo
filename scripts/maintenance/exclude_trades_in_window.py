#!/usr/bin/env python3
"""
Exclude trades that fall within a specific time window.

This script edits performance.json, signals.jsonl, and trades.db (if present)
so trades within the given window no longer count toward PnL. Use for gateway
outage periods.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover - best-effort fallback
    ZoneInfo = None  # type: ignore

from pearlalgo.utils.paths import ensure_state_dir


def _resolve_state_dir(state_dir: Optional[str], market: Optional[str]) -> Path:
    if state_dir:
        return ensure_state_dir(Path(state_dir))
    if market:
        market_label = str(market).strip().upper()
        return ensure_state_dir(Path("data") / "agent_state" / market_label)
    return ensure_state_dir(None)


def _get_tzinfo(tz_name: Optional[str]) -> timezone:
    if not tz_name:
        return timezone.utc
    if ZoneInfo is None:
        # zoneinfo not available; default to UTC
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def _parse_time(value: str, tz_name: Optional[str]) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp: {value}") from exc

    if dt.tzinfo is None:
        tzinfo = _get_tzinfo(tz_name)
        dt = dt.replace(tzinfo=tzinfo)
    return dt.astimezone(timezone.utc)


def _time_in_window(ts: datetime, start: datetime, end: datetime) -> bool:
    return start <= ts <= end


def _parse_trade_time(trade: dict, field: str, tz_name: Optional[str]) -> Optional[datetime]:
    raw = trade.get(field)
    if not raw:
        return None
    try:
        return _parse_time(str(raw), tz_name)
    except Exception:
        return None


def _trade_matches(
    trade: dict,
    match_mode: str,
    start: datetime,
    end: datetime,
    tz_name: Optional[str],
) -> bool:
    if match_mode == "exit":
        ts = _parse_trade_time(trade, "exit_time", tz_name)
        return bool(ts and _time_in_window(ts, start, end))
    if match_mode == "entry":
        ts = _parse_trade_time(trade, "entry_time", tz_name)
        return bool(ts and _time_in_window(ts, start, end))

    # either
    exit_ts = _parse_trade_time(trade, "exit_time", tz_name)
    entry_ts = _parse_trade_time(trade, "entry_time", tz_name)
    return bool(
        (exit_ts and _time_in_window(exit_ts, start, end))
        or (entry_ts and _time_in_window(entry_ts, start, end))
    )


def _sum_pnl(trades: Iterable[dict]) -> float:
    total = 0.0
    for trade in trades:
        try:
            total += float(trade.get("pnl", 0) or 0.0)
        except Exception:
            continue
    return total


def _atomic_write_json(path: Path, data: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(path.parent),
            delete=False,
            suffix=".tmp",
            encoding="utf-8",
        ) as tmp_file:
            json.dump(data, tmp_file, indent=2)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = tmp_file.name
        os.replace(tmp_path, path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _atomic_write_lines(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(path.parent),
            delete=False,
            suffix=".tmp",
            encoding="utf-8",
        ) as tmp_file:
            for line in lines:
                tmp_file.write(line)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = tmp_file.name
        os.replace(tmp_path, path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _chunks(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _delete_by_ids(cursor: sqlite3.Cursor, table: str, column: str, ids: List[str]) -> int:
    if not ids:
        return 0
    deleted = 0
    for chunk in _chunks(ids, 900):
        placeholders = ",".join("?" for _ in chunk)
        cursor.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", chunk)
        deleted += cursor.rowcount
    return deleted


def _sync_sqlite(
    db_path: Path,
    match_mode: str,
    start: datetime,
    end: datetime,
) -> Tuple[int, float, int, int]:
    if not db_path.exists():
        return 0, 0.0, 0, 0

    start_iso = start.isoformat()
    end_iso = end.isoformat()

    if match_mode == "exit":
        where_clause = "exit_time >= ? AND exit_time <= ?"
        params = (start_iso, end_iso)
    elif match_mode == "entry":
        where_clause = "entry_time >= ? AND entry_time <= ?"
        params = (start_iso, end_iso)
    else:
        where_clause = "(exit_time >= ? AND exit_time <= ?) OR (entry_time >= ? AND entry_time <= ?)"
        params = (start_iso, end_iso, start_iso, end_iso)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT trade_id, signal_id, pnl FROM trades WHERE {where_clause}",
            params,
        )
        rows = cursor.fetchall()
        trade_ids = [str(r["trade_id"]) for r in rows if r["trade_id"]]
        signal_ids = [str(r["signal_id"]) for r in rows if r["signal_id"]]
        count = len(rows)
        total_pnl = sum(float(r["pnl"] or 0.0) for r in rows)

        features_deleted = _delete_by_ids(cursor, "trade_features", "trade_id", trade_ids)
        signal_events_deleted = _delete_by_ids(cursor, "signal_events", "signal_id", signal_ids)
        cursor.execute(f"DELETE FROM trades WHERE {where_clause}", params)
        conn.commit()
        return count, total_pnl, features_deleted, signal_events_deleted
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exclude trades in a time window from performance.json, signals.jsonl, and trades.db."
    )
    parser.add_argument("--from", dest="start", required=True, help="Window start (ISO timestamp).")
    parser.add_argument("--to", dest="end", required=True, help="Window end (ISO timestamp).")
    parser.add_argument("--tz", default="UTC", help="Timezone for naive timestamps (default: UTC).")
    parser.add_argument(
        "--match",
        choices=("exit", "entry", "either"),
        default="exit",
        help="Which time field to match (default: exit).",
    )
    parser.add_argument("--state-dir", help="Explicit agent state directory.")
    parser.add_argument("--market", help="Market label (e.g., NQ).")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    args = parser.parse_args()

    try:
        start_utc = _parse_time(args.start, args.tz)
        end_utc = _parse_time(args.end, args.tz)
    except ValueError as exc:
        print(str(exc))
        return 2

    if start_utc >= end_utc:
        print("Start time must be before end time.")
        return 2

    state_dir = _resolve_state_dir(args.state_dir, args.market)
    performance_file = state_dir / "performance.json"
    if not performance_file.exists():
        print(f"No performance.json found at {performance_file}")
        return 1

    try:
        trades = json.loads(performance_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to read performance.json: {exc}")
        return 1

    if not isinstance(trades, list):
        print("performance.json is not a list of trade records.")
        return 1

    removed: List[dict] = []
    kept: List[dict] = []
    for trade in trades:
        if _trade_matches(trade, args.match, start_utc, end_utc, args.tz):
            removed.append(trade)
        else:
            kept.append(trade)
    removed_pnl = _sum_pnl(removed)
    removed_ids = {
        str(t.get("signal_id") or t.get("trade_id") or "").strip()
        for t in removed
        if str(t.get("signal_id") or t.get("trade_id") or "").strip()
    }

    print(f"Window (UTC): {start_utc.isoformat()} → {end_utc.isoformat()}")
    print(f"Matched {len(removed)} trades; total PnL delta: {removed_pnl:+.2f}")

    if args.dry_run:
        for trade in removed:
            trade_id = trade.get("signal_id") or trade.get("trade_id") or "unknown"
            exit_time = trade.get("exit_time")
            pnl = trade.get("pnl")
            print(f"- {trade_id} | exit={exit_time} | pnl={pnl}")
        print("Dry run complete; no changes written.")
        return 0

    _atomic_write_json(performance_file, kept)
    print(f"Wrote updated performance.json ({len(kept)} trades remaining).")

    signals_file = state_dir / "signals.jsonl"
    if signals_file.exists() and removed_ids:
        kept_lines: List[str] = []
        removed_lines = 0
        for line in signals_file.read_text(encoding="utf-8").splitlines(keepends=True):
            try:
                record = json.loads(line.strip())
            except Exception:
                kept_lines.append(line)
                continue
            signal_id = str(record.get("signal_id") or "").strip()
            if signal_id and signal_id in removed_ids:
                removed_lines += 1
                continue
            kept_lines.append(line)
        _atomic_write_lines(signals_file, kept_lines)
        print(f"Wrote updated signals.jsonl ({removed_lines} records removed).")
    elif signals_file.exists():
        print("No matching signals.jsonl records to remove.")
    else:
        print("signals.jsonl not found; skipping.")

    db_path = state_dir / "trades.db"
    if db_path.exists():
        deleted_count, deleted_pnl, features_deleted, events_deleted = _sync_sqlite(
            db_path, args.match, start_utc, end_utc
        )
        if deleted_count:
            print(f"Deleted {deleted_count} trades from trades.db (PnL delta {deleted_pnl:+.2f}).")
            if features_deleted or events_deleted:
                print(f"Removed {features_deleted} trade_features rows and {events_deleted} signal_events rows.")
        else:
            print("No matching trades deleted from trades.db.")
    else:
        print("trades.db not found; skipping.")

    print("Restart the agent to reset in-memory circuit breaker PnL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
