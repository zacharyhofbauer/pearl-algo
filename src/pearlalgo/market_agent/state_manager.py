"""
NQ Agent State Manager

Manages state persistence for the NQ agent service.

Architecture Note: Dual-Write State Management
==============================================
This module is the PRIMARY state store using JSON files. It's designed for:
- Fast atomic writes (temp file + rename pattern)
- Human-readable debugging
- Mobile/Telegram bot compatibility

For analytics and querying, see also:
- storage/trade_database.py (SQLite secondary store)
- storage/async_sqlite_queue.py (non-blocking SQLite writes)

See docs/architecture/state_management.md for full details.
"""

from __future__ import annotations

import json
import os
import fcntl
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from pearlalgo.utils.logger import logger
from pearlalgo.utils.state_io import (
    atomic_write_json,
    create_minimal_signal_record,
    file_lock,
    load_json_file,
)
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_events_file,
    get_signals_file,
    get_state_file,
    get_utc_timestamp,
    parse_utc_timestamp,
)

try:
    from pearlalgo.storage.trade_database import TradeDatabase
    SQLITE_AVAILABLE = True
except Exception:
    SQLITE_AVAILABLE = False
    TradeDatabase = None  # type: ignore


def _to_json_safe(obj):
    """
    Recursively convert common non-JSON-serializable types into JSON-safe primitives.

    Signals often contain numpy/pandas scalars (e.g., np.float64, pd.Timestamp) which
    break json.dumps() and cause signals.jsonl to remain empty.
    """
    # JSON primitives
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    # Containers
    if isinstance(obj, dict):
        return {str(k): _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_json_safe(v) for v in obj]

    # Datetime-like
    if isinstance(obj, (datetime, date)):
        try:
            return obj.isoformat()
        except Exception as e:
            logger.warning(f"State operation failed: {e}")
            return str(obj)

    # Paths
    if isinstance(obj, Path):
        return str(obj)

    # numpy scalars/arrays
    try:
        import numpy as np  # type: ignore

        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception as e:
        logger.warning(f"State operation failed: {e}")

    # pandas timestamps/containers
    try:
        import pandas as pd  # type: ignore

        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if isinstance(obj, pd.Timedelta):
            return float(obj.total_seconds())
        if isinstance(obj, pd.Series):
            return {str(k): _to_json_safe(v) for k, v in obj.to_dict().items()}
        if isinstance(obj, pd.DataFrame):
            # Signals should not include large dataframes; if they do, keep it bounded.
            return [_to_json_safe(r) for r in obj.to_dict(orient="records")]
    except Exception as e:
        logger.warning(f"State operation failed: {e}")

    # Fallback
    return str(obj)


# ======================================================================
# Internal submodules — decompose the state manager by responsibility
# ======================================================================


class _StatePersistence:
    """Read/write ``state.json`` under file lock."""

    def __init__(self, state_dir: Path, state_file: Path) -> None:
        self._state_dir = state_dir
        self._state_file = state_file

    def save_state(self, state: Dict) -> None:
        lock_path = self._state_dir / ".state.lock"
        try:
            state["last_updated"] = get_utc_timestamp()
            with file_lock(lock_path):
                atomic_write_json(self._state_file, state)
        except Exception as e:
            logger.error(f"Error saving state: {e}", exc_info=True)

    def load_state(self) -> Dict:
        """Load state.json using canonical helper."""
        from pearlalgo.utils.state_io import load_json_file
        if not self._state_file.exists():
            return {}
        lock_path = self._state_dir / ".state.lock"
        try:
            with file_lock(lock_path, shared=True):
                return load_json_file(self._state_file)
        except Exception as e:
            logger.error(f"Error loading state: {e}", exc_info=True)
            return {}


class _EventLog:
    """Append-only event log backed by ``events.jsonl``."""

    # Maximum events.jsonl size before rotation (20 MB)
    _EVENTS_MAX_BYTES: int = 20 * 1024 * 1024

    def __init__(self, events_file: Path) -> None:
        self._events_file = events_file

    def _rotate_events_file(self) -> None:
        try:
            if not self._events_file.exists():
                return
            if self._events_file.stat().st_size < self._EVENTS_MAX_BYTES:
                return
            backup = Path(str(self._events_file) + ".1")
            if backup.exists():
                backup.unlink()
            self._events_file.rename(backup)
            logger.info(
                f"Rotated events.jsonl ({self._EVENTS_MAX_BYTES // (1024*1024)}MB limit) → {backup.name}"
            )
        except Exception as e:
            logger.warning(f"Critical path error: {e}", exc_info=True)

    def append_event(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        level: Optional[str] = None,
    ) -> None:
        record = {
            "timestamp": get_utc_timestamp(),
            "type": str(event_type or "event"),
            "level": str(level) if level is not None else None,
            "payload": _to_json_safe(payload or {}),
        }
        lock_path = Path(str(self._events_file) + ".lock")
        try:
            with file_lock(lock_path):
                self._rotate_events_file()
                with open(self._events_file, "a") as f:
                    f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"State operation failed: {e}")
            try:
                with open(self._events_file, "a") as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                logger.warning(f"Critical path error: {e}", exc_info=True)

    def get_recent_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Get recent events from events.jsonl using canonical helper."""
        from pearlalgo.utils.state_io import load_jsonl_file
        if not self._events_file.exists():
            return []
        try:
            return load_jsonl_file(self._events_file, max_lines=limit)
        except Exception as e:
            logger.debug(f"Error reading events: {e}")
            return []


class _SignalStore:
    """Manages ``signals.jsonl`` persistence, caching, rotation, and dedup."""

    # Cache recent signals for this many seconds before re-reading from disk.
    _SIGNALS_CACHE_TTL: float = 15.0

    def __init__(
        self,
        signals_file: Path,
        *,
        duplicate_window_seconds: int = 120,
        duplicate_price_threshold_pct: float = 0.005,
        max_signal_lines: int = 5000,
    ) -> None:
        self._signals_file = signals_file
        self._duplicate_window_seconds = duplicate_window_seconds
        self._duplicate_price_threshold_pct = duplicate_price_threshold_pct
        self._max_signal_lines = max_signal_lines
        self._signal_write_count = 0
        self._signal_count: Optional[int] = None

        # Async SQLite queue (injected via set_sqlite_queue)
        self._async_sqlite_queue: Optional[Any] = None
        self._sqlite_enabled: bool = False
        self._trade_db: Any = None

        # Recent signals TTL cache (protected by lock for thread safety)
        self._signals_cache: Optional[List[Dict]] = None
        self._signals_cache_time: float = 0.0
        self._signals_cache_limit: int = 0
        self._signals_cache_lock = threading.Lock()

    # -- public helpers ------------------------------------------------

    def set_sqlite_queue(self, queue: Any) -> None:
        self._async_sqlite_queue = queue

    def set_sqlite(self, enabled: bool, trade_db: Any) -> None:
        self._sqlite_enabled = enabled
        self._trade_db = trade_db

    def _signals_meta_path(self) -> Path:
        return self._signals_file.parent / "signals_meta.json"

    def _read_signal_count_sidecar(self) -> Optional[int]:
        """Read signal count from sidecar if present and valid."""
        meta = load_json_file(self._signals_meta_path())
        if isinstance(meta, dict) and "count" in meta:
            try:
                return int(meta["count"])
            except (TypeError, ValueError):
                pass
        return None

    def _write_signal_count_sidecar(self, count: int) -> None:
        """Write signal count to sidecar for O(1) reads on next load."""
        try:
            atomic_write_json(self._signals_meta_path(), {"count": count})
        except Exception as e:
            logger.debug("Could not write signals_meta.json: %s", e)

    def get_signal_count(self) -> int:
        if self._signal_count is None:
            sidecar = self._read_signal_count_sidecar()
            if sidecar is not None:
                self._signal_count = sidecar
            else:
                try:
                    if self._signals_file.exists():
                        with open(self._signals_file, "r") as f:
                            self._signal_count = sum(1 for _ in f)
                    else:
                        self._signal_count = 0
                    self._write_signal_count_sidecar(self._signal_count)
                except Exception as e:
                    logger.warning(f"Failed to count signals, defaulting to 0: {e}")
                    self._signal_count = 0
        return self._signal_count

    def invalidate_signals_cache(self) -> None:
        with self._signals_cache_lock:
            self._signals_cache = None

    # -- duplicate detection -------------------------------------------

    def _is_duplicate_signal(self, signal: Dict, recent_signals: List[Dict]) -> bool:
        signal_type = signal.get("type", "")
        signal_direction = signal.get("direction", "")
        signal_entry = float(signal.get("entry_price", 0.0))
        signal_timestamp_str = signal.get("timestamp", "")

        if not signal_timestamp_str:
            return False

        try:
            signal_time = parse_utc_timestamp(signal_timestamp_str)
        except Exception as e:
            logger.warning(f"State operation failed: {e}")
            return False

        for recent_record in recent_signals:
            recent_signal = recent_record.get("signal", {})
            if not recent_signal:
                continue

            recent_type = recent_signal.get("type", "")
            recent_direction = recent_signal.get("direction", "")
            recent_entry = float(recent_signal.get("entry_price", 0.0))
            recent_timestamp_str = recent_signal.get("timestamp", "")

            if not recent_timestamp_str:
                continue

            try:
                recent_time = parse_utc_timestamp(recent_timestamp_str)
            except Exception as e:
                logger.warning(f"State operation failed: {e}")
                continue

            same_type = recent_type == signal_type
            same_direction = recent_direction == signal_direction

            if not (same_type and same_direction):
                continue

            time_diff = abs((signal_time - recent_time).total_seconds())
            within_time_window = time_diff < self._duplicate_window_seconds

            price_close = False
            if recent_entry > 0 and signal_entry > 0:
                price_diff_pct = abs(signal_entry - recent_entry) / recent_entry
                price_close = price_diff_pct < self._duplicate_price_threshold_pct

            if within_time_window and price_close:
                return True

        return False

    # -- rotation ------------------------------------------------------

    def _rotate_signals_file(self) -> None:
        try:
            if not self._signals_file.exists():
                return

            # Prefer sidecar count to avoid a full file read when possible
            line_count = self._read_signal_count_sidecar()
            if line_count is None:
                line_count = 0
                with open(self._signals_file, "r") as f:
                    for _ in f:
                        line_count += 1

            if line_count <= self._max_signal_lines:
                return

            keep_count = self._max_signal_lines
            skip_count = line_count - keep_count
            archive_path = self._signals_file.parent / "signals_archive.jsonl"

            # Single pass: archive first skip_count lines, collect the rest
            keep_lines: list[str] = []
            with open(self._signals_file, "r") as src:
                with open(archive_path, "a") as archive:
                    for i, line in enumerate(src):
                        if i < skip_count:
                            archive.write(line)
                        else:
                            keep_lines.append(line)

            import tempfile as _tempfile
            tmp_fd, tmp_name = _tempfile.mkstemp(
                dir=str(self._signals_file.parent), suffix=".tmp"
            )
            try:
                with os.fdopen(tmp_fd, "w") as tmp_f:
                    tmp_f.writelines(keep_lines)
                    tmp_f.flush()
                    os.fsync(tmp_f.fileno())
                os.replace(tmp_name, self._signals_file)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise

            self._signal_count = keep_count
            self._write_signal_count_sidecar(keep_count)
            self.invalidate_signals_cache()

            logger.info(
                f"Rotated signals.jsonl: archived {skip_count} lines, kept {keep_count} lines"
            )
        except Exception as e:
            logger.warning(f"Signal file rotation failed: {e}", exc_info=True)

    # -- save / read ---------------------------------------------------

    def save_signal(self, signal: Dict) -> None:  # noqa: C901
        """Persist a signal record to ``signals.jsonl`` (and optionally SQLite)."""
        try:
            if signal.get("_is_test", False):
                logger.debug(f"Skipping test signal persistence: {signal.get('type', 'unknown')}")
                return

            signal_id = signal.get("signal_id", "")
            if not signal_id:
                signal_id = f"{signal.get('type', 'unknown')}_{datetime.now(timezone.utc).timestamp()}"
                signal["signal_id"] = signal_id

            lock_path = Path(str(self._signals_file) + ".lock")
            try:
                with file_lock(lock_path):
                    recent_signals = self.get_recent_signals_tail(max_lines=100)

                    is_duplicate = False
                    try:
                        is_duplicate = self._is_duplicate_signal(signal, recent_signals)
                    except Exception as e:
                        logger.warning(f"State operation failed: {e}")
                        is_duplicate = False
                    if is_duplicate:
                        logger.debug(
                            f"Tagging duplicate signal (persisting anyway): {signal_id} "
                            f"(type={signal.get('type')}, direction={signal.get('direction')})"
                        )

                    signal_record = {
                        "signal_id": signal_id,
                        "timestamp": get_utc_timestamp(),
                        "status": "generated",
                        "signal": _to_json_safe(signal),
                    }
                    if is_duplicate:
                        signal_record["duplicate"] = True

                    try:
                        payload = json.dumps(signal_record)
                    except TypeError as e:
                        logger.error(
                            f"Signal serialization failed, writing minimal record: {e}",
                            extra={"signal_id": signal_id},
                        )
                        payload = json.dumps(create_minimal_signal_record(signal_id, signal))

                    with open(self._signals_file, "a") as f:
                        f.write(payload + "\n")

                    if self._signal_count is not None:
                        self._signal_count += 1
                        self._write_signal_count_sidecar(self._signal_count)

                    self._signals_cache = None

                    self._signal_write_count += 1
                    if self._signal_write_count % 100 == 0:
                        self._rotate_signals_file()
            except Exception as e:
                logger.warning(f"File locking failed, falling back to unlocked write: {e}")
                signal_record = {
                    "signal_id": signal_id,
                    "timestamp": get_utc_timestamp(),
                    "status": "generated",
                    "signal": _to_json_safe(signal),
                }
                try:
                    payload = json.dumps(signal_record)
                except TypeError:
                    payload = json.dumps(create_minimal_signal_record(signal_id, signal))
                with open(self._signals_file, "a") as f:
                    f.write(payload + "\n")

                if self._signal_count is not None:
                    self._signal_count += 1
                    self._write_signal_count_sidecar(self._signal_count)

            # Dual-write to SQLite
            try:
                if self._sqlite_enabled and self._trade_db is not None:
                    if self._async_sqlite_queue is not None:
                        from pearlalgo.storage.async_sqlite_queue import WritePriority

                        self._async_sqlite_queue.enqueue(
                            "add_signal_event",
                            priority=WritePriority.MEDIUM,
                            signal_id=signal_id,
                            status="generated",
                            timestamp=str(signal_record.get("timestamp") or get_utc_timestamp()),
                            payload=signal_record,
                        )
                    else:
                        self._trade_db.add_signal_event(
                            signal_id=signal_id,
                            status="generated",
                            timestamp=str(signal_record.get("timestamp") or get_utc_timestamp()),
                            payload=signal_record,
                        )
            except Exception as e:
                logger.debug(f"SQLite dual-write skipped (non-critical): {e}")

        except Exception as e:
            logger.error(f"Critical signal save error: {e}", exc_info=True)

    def get_recent_signals(self, limit: int = 100) -> List[Dict]:
        import time

        now = time.monotonic()

        with self._signals_cache_lock:
            if (
                self._signals_cache is not None
                and (now - self._signals_cache_time) < self._SIGNALS_CACHE_TTL
                and limit <= self._signals_cache_limit
            ):
                return self._signals_cache[-limit:]

        # Read outside lock to avoid blocking concurrent readers
        signals = self.get_recent_signals_tail(max_lines=limit)

        with self._signals_cache_lock:
            self._signals_cache = signals
            self._signals_cache_time = now
            self._signals_cache_limit = limit

        return signals

    def get_recent_signals_tail(self, max_lines: int = 1000) -> List[Dict]:
        """Get recent signals from signals.jsonl using canonical helper."""
        from pearlalgo.utils.state_io import load_jsonl_file
        if not self._signals_file.exists():
            return []
        try:
            return load_jsonl_file(self._signals_file, max_lines=max_lines)
        except Exception as e:
            logger.error(f"Error tail-reading signals: {e}")
            return []

    async def async_get_recent_signals(self, limit: int = 100) -> List[Dict]:
        import asyncio
        return await asyncio.to_thread(self.get_recent_signals, limit)

    # -- export / reconcile --------------------------------------------

    def export_signals_to_json(self, trade_db: Any = None, limit: int = 5000) -> int:
        db = trade_db or self._trade_db
        if db is None:
            return 0

        try:
            events = db.get_recent_signal_events(limit=limit)
            if not events:
                return 0

            tmp_path = Path(str(self._signals_file) + ".export.tmp")
            with open(tmp_path, "w") as f:
                for event in events:
                    f.write(json.dumps(event) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._signals_file)

            self._signal_count = len(events)
            self.invalidate_signals_cache()

            logger.debug(f"Exported {len(events)} signals from SQLite to {self._signals_file}")
            return len(events)
        except Exception as e:
            logger.warning(f"Signal export to JSON failed: {e}")
            return 0

    def reconcile_signals(self, trade_db: Any = None, threshold: int = 10) -> Dict:
        result: Dict = {
            "json_count": 0,
            "sqlite_count": 0,
            "divergence": 0,
            "replayed": 0,
            "errors": 0,
        }

        try:
            db = trade_db or self._trade_db
            if db is None:
                logger.info("Signal reconciliation skipped: no SQLite database available")
                return result

            json_count = self.get_signal_count()
            result["json_count"] = json_count

            counts_by_status = db.get_signal_event_counts()
            sqlite_count = sum(counts_by_status.values())
            result["sqlite_count"] = sqlite_count

            divergence = json_count - sqlite_count
            result["divergence"] = divergence

            if divergence <= threshold:
                logger.info(
                    f"Signal reconciliation OK: json={json_count}, sqlite={sqlite_count}, "
                    f"divergence={divergence} (threshold={threshold})"
                )
                return result

            logger.info(
                f"Signal reconciliation: divergence={divergence} exceeds threshold={threshold}, "
                "replaying missing signals from JSON to SQLite"
            )

            existing_ids = db.get_all_signal_ids()

            replayed = 0
            errors = 0

            if self._signals_file.exists():
                with open(self._signals_file, "r") as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            signal_id = record.get("signal_id", "")
                            if not signal_id:
                                continue
                            if signal_id in existing_ids:
                                continue
                            db.add_signal_event(
                                signal_id=signal_id,
                                status=record.get("status", "generated"),
                                timestamp=record.get("timestamp", ""),
                                payload=record,
                            )
                            replayed += 1
                        except json.JSONDecodeError:
                            errors += 1
                        except Exception as e:
                            errors += 1
                            logger.debug(f"Reconciliation replay error for signal: {e}")

            result["replayed"] = replayed
            result["errors"] = errors

            logger.info(
                f"Signal reconciliation complete: json={json_count}, sqlite={sqlite_count}, "
                f"replayed={replayed}, errors={errors}"
            )

        except Exception as e:
            logger.error(f"Signal reconciliation failed: {e}", exc_info=True)
            result["errors"] = result.get("errors", 0) + 1

        return result


# ======================================================================
# Facade — preserves the original public API
# ======================================================================


class MarketAgentStateManager:
    """Manages state persistence for NQ agent.

    This is a **thin facade** that delegates to three focused submodules:

    * :class:`_SignalStore` – ``signals.jsonl`` persistence, caching, dedup
    * :class:`_EventLog` – ``events.jsonl`` append-only event log
    * :class:`_StatePersistence` – ``state.json`` read/write
    """

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        service_config: Optional[Dict] = None,
    ):
        self._explicit_state_dir = state_dir is not None

        self.state_dir = ensure_state_dir(state_dir)
        self.signals_file = get_signals_file(self.state_dir)
        self.events_file = get_events_file(self.state_dir)
        self.state_file = get_state_file(self.state_dir)

        if service_config is None:
            try:
                from pearlalgo.config.config_loader import load_service_config
                service_config = load_service_config(validate=False) or {}
            except Exception as e:
                logger.warning(f"State operation failed: {e}")
                service_config = {}

        # SQLite dual-write to the secondary analytics store.
        self._sqlite_enabled = False
        self._trade_db = None

        # -- Internal submodules --
        signal_settings = service_config.get("signals", {}) or {}

        self._signal_store = _SignalStore(
            self.signals_file,
            duplicate_window_seconds=signal_settings.get("duplicate_window_seconds", 120),
            duplicate_price_threshold_pct=(
                signal_settings.get("duplicate_price_threshold_pct", 0.5) / 100.0
            ),
            max_signal_lines=signal_settings.get("max_signal_lines", 5000),
        )
        self._signal_store.set_sqlite(False, None)

        self._event_log = _EventLog(self.events_file)
        self._state_persistence = _StatePersistence(self.state_dir, self.state_file)

        logger.info(f"MarketAgentStateManager initialized: state_dir={self.state_dir}")

    # -- delegation: sqlite queue --------------------------------------

    def set_sqlite_queue(self, queue: Any) -> None:
        """Set the async SQLite queue for non-blocking dual-write operations."""
        self._signal_store.set_sqlite_queue(queue)

    # -- delegation: signals -------------------------------------------

    def get_signal_count(self) -> int:
        return self._signal_store.get_signal_count()

    def _is_duplicate_signal(self, signal: Dict, recent_signals: List[Dict]) -> bool:
        return self._signal_store._is_duplicate_signal(signal, recent_signals)

    def save_signal(self, signal: Dict) -> None:
        self._signal_store.save_signal(signal)

    def get_recent_signals(self, limit: int = 100) -> List[Dict]:
        return self._signal_store.get_recent_signals(limit)

    def get_recent_signals_tail(self, max_lines: int = 1000) -> List[Dict]:
        return self._signal_store.get_recent_signals_tail(max_lines)

    def invalidate_signals_cache(self) -> None:
        self._signal_store.invalidate_signals_cache()

    async def async_get_recent_signals(self, limit: int = 100) -> List[Dict]:
        return await self._signal_store.async_get_recent_signals(limit)

    def export_signals_to_json(self, trade_db=None, limit: int = 5000) -> int:
        return self._signal_store.export_signals_to_json(trade_db, limit)

    def reconcile_signals(self, trade_db=None, threshold: int = 10) -> Dict:
        return self._signal_store.reconcile_signals(trade_db, threshold)

    # -- delegation: events --------------------------------------------

    def append_event(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        level: Optional[str] = None,
    ) -> None:
        self._event_log.append_event(event_type, payload, level=level)

    def get_recent_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._event_log.get_recent_events(limit)

    # -- delegation: state persistence ---------------------------------

    def save_state(self, state: Dict) -> None:
        self._state_persistence.save_state(state)

    def load_state(self) -> Dict:
        return self._state_persistence.load_state()
