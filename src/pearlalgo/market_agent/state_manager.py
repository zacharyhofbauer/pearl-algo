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
- learning/trade_database.py (SQLite secondary store)
- storage/async_sqlite_queue.py (non-blocking SQLite writes)

See docs/architecture/state_management.md for full details.
"""

from __future__ import annotations

import json
import os
import fcntl
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_events_file,
    get_signals_file,
    get_state_file,
    get_utc_timestamp,
    parse_utc_timestamp,
)

try:
    from pearlalgo.learning.trade_database import TradeDatabase
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


class MarketAgentStateManager:
    """
    Manages state persistence for NQ agent.
    
    Stores signals, positions, and service state.
    """

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        service_config: Optional[Dict] = None,
    ):
        """
        Initialize state manager.
        
        Args:
            state_dir: Directory for state files (default: ./data/agent_state/<MARKET>)
            service_config: Pre-loaded service config dict. If None, loads from disk
                            (for backward compatibility with tests and standalone usage).
        """
        # Track whether the caller explicitly provided a state_dir (tests do this via tmp_path).
        # If explicit, ALL persistence (including SQLite) must stay inside that directory to
        # avoid unit tests polluting the live agent state under data/agent_state/<MARKET>.
        self._explicit_state_dir = state_dir is not None

        self.state_dir = ensure_state_dir(state_dir)
        self.signals_file = get_signals_file(self.state_dir)
        self.events_file = get_events_file(self.state_dir)
        self.state_file = get_state_file(self.state_dir)

        # Use provided config or load from disk (backward compat)
        if service_config is None:
            try:
                from pearlalgo.config.config_loader import load_service_config
                service_config = load_service_config(validate=False) or {}
            except Exception as e:
                logger.warning(f"State operation failed: {e}")
                service_config = {}

        # Optional SQLite dual-write (platform memory). Keep file writes as-is for Telegram/mobile.
        self._sqlite_enabled = False
        self._trade_db = None
        if SQLITE_AVAILABLE:
            try:
                storage_cfg = service_config.get("storage", {}) or {}
                self._sqlite_enabled = bool(storage_cfg.get("sqlite_enabled", False))
                if self._sqlite_enabled:
                    # IMPORTANT:
                    # - In production (no explicit state_dir), honor config.db_path if provided.
                    # - In tests (explicit state_dir), ALWAYS use state_dir/trades.db regardless of config,
                    #   so tests cannot write into data/agent_state/<MARKET>/trades.db.
                    if self._explicit_state_dir:
                        db_path = self.state_dir / "trades.db"
                    else:
                        db_path_raw = storage_cfg.get("db_path") or str(self.state_dir / "trades.db")
                        db_path = Path(str(db_path_raw))
                    self._trade_db = TradeDatabase(db_path)
            except Exception as e:
                logger.warning(f"SQLite storage not enabled/available: {e}")

        # Load duplicate detection settings from config
        signal_settings = service_config.get("signals", {}) or {}
        self._duplicate_window_seconds = signal_settings.get("duplicate_window_seconds", 120)
        self._duplicate_price_threshold_pct = (
            signal_settings.get("duplicate_price_threshold_pct", 0.5) / 100.0
        )

        # Signal file rotation settings
        self._max_signal_lines = signal_settings.get("max_signal_lines", 5000)
        self._signal_write_count = 0

        # Incremental signal count -- avoids reading entire file to count lines.
        # Initialised lazily on first access (counts lines once, then increments).
        self._signal_count: Optional[int] = None

        # Recent signals cache (see get_recent_signals)
        self._signals_cache: Optional[List[Dict]] = None
        self._signals_cache_time: float = 0.0
        self._signals_cache_limit: int = 0

        logger.info(f"MarketAgentStateManager initialized: state_dir={self.state_dir}")

    def get_signal_count(self) -> int:
        """Return the total number of signals in signals.jsonl.

        The count is initialised lazily by reading the file once, then maintained
        incrementally as signals are written or the file is rotated.  This is O(1)
        after the first call, avoiding a full file scan on every cycle.
        """
        if self._signal_count is None:
            # First access -- count lines once
            try:
                if self.signals_file.exists():
                    with open(self.signals_file, "r") as f:
                        self._signal_count = sum(1 for _ in f)
                else:
                    self._signal_count = 0
            except Exception as e:
                logger.warning(f"Failed to count signals, defaulting to 0: {e}")
                self._signal_count = 0
        return self._signal_count

    def _is_duplicate_signal(self, signal: Dict, recent_signals: List[Dict]) -> bool:
        """
        Check if signal is a duplicate of a recent signal.
        
        Args:
            signal: Signal dictionary to check
            recent_signals: List of recent signal records from file
            
        Returns:
            True if duplicate
        """
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

            # Check if same type and direction
            same_type = recent_type == signal_type
            same_direction = recent_direction == signal_direction
            
            if not (same_type and same_direction):
                continue

            # Check time window
            time_diff = abs((signal_time - recent_time).total_seconds())
            within_time_window = time_diff < self._duplicate_window_seconds

            # Check if price is too close
            price_close = False
            if recent_entry > 0 and signal_entry > 0:
                price_diff_pct = abs(signal_entry - recent_entry) / recent_entry
                price_close = price_diff_pct < self._duplicate_price_threshold_pct

            # A signal is only a true duplicate when it's both:
            # - close in time (within the configured duplicate window), AND
            # - close in price (within the configured threshold)
            #
            # Using `or` here causes legitimate signals hours apart to be dropped from
            # persistence, which then breaks the virtual trade lifecycle (entered/exited).
            if within_time_window and price_close:
                return True

        return False

    def _rotate_signals_file(self) -> None:
        """Rotate signals.jsonl when it exceeds max_signal_lines.

        Keeps the last ``_max_signal_lines`` lines in signals.jsonl and appends
        the rotated-out (oldest) lines to signals_archive.jsonl in the same
        directory.  Called under the existing file lock so no concurrent writers
        can interfere.

        Streams the file line-by-line to avoid loading the entire file into
        memory (the file can be large before rotation kicks in).
        """
        try:
            if not self.signals_file.exists():
                return

            # Count lines without loading the whole file into memory
            line_count = 0
            with open(self.signals_file, "r") as f:
                for _ in f:
                    line_count += 1

            if line_count <= self._max_signal_lines:
                return

            archive_count = line_count - self._max_signal_lines

            # Stream through file: archive the first N lines, keep the rest.
            archive_file = self.signals_file.parent / "signals_archive.jsonl"
            tmp_path = Path(str(self.signals_file) + ".tmp")
            with open(self.signals_file, "r") as src, \
                 open(archive_file, "a") as archive_f, \
                 open(tmp_path, "w") as keep_f:
                for i, line in enumerate(src):
                    if i < archive_count:
                        archive_f.write(line)
                    else:
                        keep_f.write(line)
                keep_f.flush()
                os.fsync(keep_f.fileno())
            os.replace(tmp_path, self.signals_file)

            # Update incremental signal count after rotation
            self._signal_count = self._max_signal_lines

            logger.info(
                f"Rotated signals.jsonl: archived {len(archive_lines)} lines, "
                f"kept {len(keep_lines)} lines"
            )
        except Exception as e:
            logger.warning(f"Critical path error: {e}", exc_info=True)

    def save_signal(self, signal: Dict) -> None:
        """
        Save a signal to persistent storage.
        
        Includes duplicate detection by checking recent signals from file.
        Uses file locking to prevent race conditions.
        
        Saves in the format expected by /signals command:
        {
            "signal_id": "...",
            "timestamp": "...",
            "status": "generated",
            "signal": {...}
        }
        
        Test signals (marked with _is_test=True) are NEVER persisted.
        
        Args:
            signal: Signal dictionary (should already have signal_id set)
        """
        try:
            # GUARD: Never persist test signals
            if signal.get("_is_test", False):
                logger.debug(f"Skipping test signal persistence: {signal.get('type', 'unknown')}")
                return
            
            # Extract signal_id from signal dict (set by performance_tracker)
            signal_id = signal.get("signal_id", "")
            if not signal_id:
                # Generate one if missing (shouldn't happen, but be safe)
                signal_id = f"{signal.get('type', 'unknown')}_{datetime.now(timezone.utc).timestamp()}"
                signal["signal_id"] = signal_id
            
            # Check for duplicates by reading recent signals from file
            # Use file locking to prevent race conditions
            lock_file = Path(str(self.signals_file) + ".lock")
            try:
                with open(lock_file, "w") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        # Read recent signals for duplicate checking.
                        # Use tail-read to avoid loading entire file into memory.
                        recent_signals = self.get_recent_signals_tail(max_lines=100)
                        
                        # Check for duplicates. IMPORTANT: we still persist the record.
                        # Dropping persistence breaks the virtual trade lifecycle (entered/exited),
                        # because status updates expect the base record to exist in signals.jsonl.
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
                        
                        # Create wrapped record in format expected by /signals command
                        signal_record = {
                            "signal_id": signal_id,
                            "timestamp": get_utc_timestamp(),
                            "status": "generated",  # Default status for new signals
                            "signal": _to_json_safe(signal),  # Store JSON-safe signal dict
                        }
                        if is_duplicate:
                            signal_record["duplicate"] = True

                        try:
                            payload = json.dumps(signal_record)
                        except TypeError as e:
                            # Last resort: write a minimal record so the signals view never goes empty.
                            logger.error(
                                f"Signal serialization failed, writing minimal record: {e}",
                                extra={"signal_id": signal_id},
                            )
                            minimal = {
                                "signal_id": signal_id,
                                "timestamp": get_utc_timestamp(),
                                "status": "generated",
                                "signal": {
                                    "signal_id": signal_id,
                                    "timestamp": str(signal.get("timestamp") or ""),
                                    "symbol": str(signal.get("symbol") or ""),
                                    "type": str(signal.get("type") or "unknown"),
                                    "direction": str(signal.get("direction") or "unknown"),
                                    "entry_price": float(signal.get("entry_price") or 0.0),
                                    "stop_loss": float(signal.get("stop_loss") or 0.0),
                                    "take_profit": float(signal.get("take_profit") or 0.0),
                                    "confidence": float(signal.get("confidence") or 0.0),
                                    "reason": str(signal.get("reason") or ""),
                                },
                            }
                            payload = json.dumps(minimal)

                        # Write signal with lock held
                        with open(self.signals_file, "a") as f:
                            f.write(payload + "\n")

                        # Maintain incremental signal count
                        if self._signal_count is not None:
                            self._signal_count += 1

                        # Invalidate cache so next read picks up the new signal
                        self._signals_cache = None

                        # Periodic rotation check (every 100 writes)
                        self._signal_write_count += 1
                        if self._signal_write_count % 100 == 0:
                            self._rotate_signals_file()
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except Exception as e:
                logger.warning(f"File locking failed, falling back to unlocked write: {e}")
                # Fallback: write without lock (should be rare)
                signal_record = {
                    "signal_id": signal_id,
                    "timestamp": get_utc_timestamp(),
                    "status": "generated",
                    "signal": _to_json_safe(signal),
                }
                try:
                    payload = json.dumps(signal_record)
                except TypeError:
                    payload = json.dumps({
                        "signal_id": signal_id,
                        "timestamp": get_utc_timestamp(),
                        "status": "generated",
                        "signal": {
                            "signal_id": signal_id,
                            "type": str(signal.get("type") or "unknown"),
                            "direction": str(signal.get("direction") or "unknown"),
                        },
                    })
                with open(self.signals_file, "a") as f:
                    f.write(payload + "\n")

                # Maintain incremental signal count (fallback path)
                if self._signal_count is not None:
                    self._signal_count += 1

            # Dual-write to SQLite (append-only signal event log, async if enabled)
            try:
                if self._sqlite_enabled and self._trade_db is not None:
                    # Use async queue if available (injected from service.py)
                    if self._async_sqlite_queue is not None:
                        from pearlalgo.storage.async_sqlite_queue import WritePriority
                        
                        self._async_sqlite_queue.enqueue(
                            "add_signal_event",
                            priority=WritePriority.MEDIUM,  # Signal generation is medium priority
                            signal_id=signal_id,
                            status="generated",
                            timestamp=str(signal_record.get("timestamp") or get_utc_timestamp()),
                            payload=signal_record,
                        )
                    else:
                        # Blocking write (legacy/fallback)
                        self._trade_db.add_signal_event(
                            signal_id=signal_id,
                            status="generated",
                            timestamp=str(signal_record.get("timestamp") or get_utc_timestamp()),
                            payload=signal_record,
                        )
            except Exception as e:
                logger.warning(f"Dual-write divergence: signal {signal_id} written to JSON but SQLite write failed: {e}")
            
            logger.debug(f"Saved signal {signal_id} to {self.signals_file}")
        except Exception as e:
            logger.error(f"Error saving signal: {e}", exc_info=True)

    # ---------------------------------------------------------------
    # Recent signals cache (TTL-based, avoids repeated full-file reads)
    # ---------------------------------------------------------------
    _SIGNALS_CACHE_TTL: float = 5.0  # seconds

    def get_recent_signals(self, limit: int = 100) -> List[Dict]:
        """
        Get recent signals with TTL caching and tail-read optimisation.

        The result is cached for ``_SIGNALS_CACHE_TTL`` seconds so that the
        5+ callers per service cycle share a single file read.  Tail-reading
        with ``collections.deque`` avoids loading the entire file.

        Args:
            limit: Maximum number of signals to return

        Returns:
            List of signal dictionaries (most recent last)
        """
        import time

        now = time.monotonic()

        # Check cache -- cache is valid if within TTL and requested limit is
        # <= the limit the cache was populated with.
        if (
            self._signals_cache is not None
            and (now - self._signals_cache_time) < self._SIGNALS_CACHE_TTL
            and limit <= self._signals_cache_limit
        ):
            # Return the tail of the cached list
            return self._signals_cache[-limit:]

        # Cache miss -- read from disk
        signals = self._read_recent_signals_from_disk(limit)

        # Populate cache
        self._signals_cache = signals
        self._signals_cache_time = now
        self._signals_cache_limit = limit

        return signals

    def _read_recent_signals_from_disk(self, limit: int) -> List[Dict]:
        """Read last *limit* signals from signals.jsonl using tail-read."""
        from collections import deque

        if not self.signals_file.exists():
            return []

        signals: List[Dict] = []
        try:
            with open(self.signals_file, "r") as f:
                # deque with maxlen keeps only the last N lines -- avoids
                # loading the full file into memory.
                tail = deque(f, maxlen=limit)
                for line in tail:
                    try:
                        signal = json.loads(line.strip())
                        signals.append(signal)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error reading signals: {e}")

        return signals

    def get_recent_signals_tail(self, max_lines: int = 1000) -> List[Dict]:
        """Read only the LAST *max_lines* of signals.jsonl by seeking from the end.

        This is an efficient alternative to reading the entire file when only
        recent signals are needed (e.g., ``get_performance_metrics`` with a
        7-day window).  It seeks to the end of the file and reads backwards in
        chunks until enough newlines are found, then parses only those lines.

        Args:
            max_lines: Maximum number of trailing lines to read and parse.

        Returns:
            List of parsed signal dictionaries (oldest first within the tail).
        """
        if not self.signals_file.exists():
            return []

        signals: List[Dict] = []
        chunk_size = 8192  # 8 KB chunks for backward reading

        try:
            with open(self.signals_file, "rb") as f:
                # Seek to end to get file size
                f.seek(0, 2)
                file_size = f.tell()

                if file_size == 0:
                    return []

                # Read backwards in chunks to collect enough lines
                remaining = file_size
                tail_bytes = b""
                lines_found = 0

                while remaining > 0 and lines_found <= max_lines:
                    read_size = min(chunk_size, remaining)
                    remaining -= read_size
                    f.seek(remaining)
                    chunk = f.read(read_size)
                    tail_bytes = chunk + tail_bytes
                    # Count newlines in the chunk to estimate progress
                    lines_found = tail_bytes.count(b"\n")

                # Decode and split into lines
                text = tail_bytes.decode("utf-8", errors="replace")
                all_lines = text.splitlines()

                # Take only the last max_lines
                tail_lines = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines

                for line in tail_lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                        signals.append(record)
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            logger.error(f"Error tail-reading signals: {e}")

        return signals

    def invalidate_signals_cache(self) -> None:
        """Force the next ``get_recent_signals`` call to read from disk."""
        self._signals_cache = None

    async def async_get_recent_signals(self, limit: int = 100) -> List[Dict]:
        """Async wrapper -- offloads the (potentially blocking) file read to a thread."""
        import asyncio
        return await asyncio.to_thread(self.get_recent_signals, limit)

    # Maximum events.jsonl size before rotation (20 MB)
    _EVENTS_MAX_BYTES: int = 20 * 1024 * 1024

    def _rotate_events_file(self) -> None:
        """Rotate events.jsonl when it exceeds size threshold.

        Keeps one backup (.1) and starts a fresh file.  Called under the
        existing file lock so no concurrent writers can interfere.
        """
        try:
            if not self.events_file.exists():
                return
            if self.events_file.stat().st_size < self._EVENTS_MAX_BYTES:
                return
            backup = Path(str(self.events_file) + ".1")
            if backup.exists():
                backup.unlink()
            self.events_file.rename(backup)
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
        """
        Append a structured event to events.jsonl for Pearl Algo Monitor.

        This is intentionally simple and resilient:
        - append-only JSONL
        - best-effort file locking
        - payload is converted to JSON-safe primitives
        - automatic rotation when file exceeds 20 MB
        """
        record = {
            "timestamp": get_utc_timestamp(),
            "type": str(event_type or "event"),
            "level": str(level) if level is not None else None,
            "payload": _to_json_safe(payload or {}),
        }

        lock_file = Path(str(self.events_file) + ".lock")
        try:
            with open(lock_file, "w") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    self._rotate_events_file()
                    with open(self.events_file, "a") as f:
                        f.write(json.dumps(record) + "\n")
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            logger.warning(f"State operation failed: {e}")
            # Fallback: unlocked append
            try:
                with open(self.events_file, "a") as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                logger.warning(f"Critical path error: {e}", exc_info=True)

    def get_recent_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Get recent events from events.jsonl (best-effort).

        Uses a tail-read strategy (reading backwards from the end of the file)
        to avoid loading the entire events file into memory.
        """
        events: List[Dict[str, Any]] = []
        if not self.events_file.exists():
            return events

        safe_limit = max(1, int(limit))
        chunk_size = 8192  # 8 KB chunks for backward reading

        try:
            with open(self.events_file, "rb") as f:
                f.seek(0, 2)
                file_size = f.tell()
                if file_size == 0:
                    return events

                remaining = file_size
                tail_bytes = b""
                lines_found = 0

                while remaining > 0 and lines_found <= safe_limit:
                    read_size = min(chunk_size, remaining)
                    remaining -= read_size
                    f.seek(remaining)
                    chunk = f.read(read_size)
                    tail_bytes = chunk + tail_bytes
                    lines_found = tail_bytes.count(b"\n")

                text = tail_bytes.decode("utf-8", errors="replace")
                all_lines = text.splitlines()
                tail_lines = all_lines[-safe_limit:] if len(all_lines) > safe_limit else all_lines

                for line in tail_lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        events.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.debug(f"Error reading events: {e}")
        return events

    def save_state(self, state: Dict) -> None:
        """
        Save service state under exclusive lock.

        Uses the same ``.state.lock`` file that :class:`StateReader` acquires
        a shared lock on, so readers and writers are properly coordinated.
        
        Args:
            state: State dictionary
        """
        lock_file = self.state_dir / ".state.lock"
        try:
            state["last_updated"] = get_utc_timestamp()
            with open(lock_file, "w") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    tmp_path = Path(str(self.state_file) + ".tmp")
                    with open(tmp_path, "w") as f:
                        json.dump(state, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, self.state_file)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            logger.error(f"Error saving state: {e}", exc_info=True)

    def load_state(self) -> Dict:
        """
        Load service state under shared lock.
        
        Returns:
            State dictionary (empty dict if no state exists)
        """
        if not self.state_file.exists():
            return {}

        lock_file = self.state_dir / ".state.lock"
        try:
            with open(lock_file, "w") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
                try:
                    with open(self.state_file, "r") as f:
                        return json.load(f)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            logger.error(f"Error loading state: {e}", exc_info=True)
            return {}

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # JSON Export (for external tools that read signals.jsonl)
    # ------------------------------------------------------------------

    def export_signals_to_json(self, trade_db=None, limit: int = 5000) -> int:
        """Export recent signals from SQLite to ``signals.jsonl`` for external consumers.

        This is the **read path** for tools (API server, Telegram handlers,
        web dashboard) that consume the legacy JSON format.  SQLite is the
        **write path** (single source of truth).

        Returns:
            Number of signals exported.
        """
        db = trade_db or getattr(self, "_trade_db", None)
        if db is None:
            return 0

        try:
            events = db.get_recent_signal_events(limit=limit)
            if not events:
                return 0

            tmp_path = Path(str(self.signals_file) + ".export.tmp")
            with open(tmp_path, "w") as f:
                for event in events:
                    f.write(json.dumps(event) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.signals_file)

            # Update cached count
            self._signal_count = len(events)
            self.invalidate_signals_cache()

            logger.debug(f"Exported {len(events)} signals from SQLite to {self.signals_file}")
            return len(events)
        except Exception as e:
            logger.warning(f"Signal export to JSON failed: {e}")
            return 0

    # ------------------------------------------------------------------
    # JSON ↔ SQLite Reconciliation (DEPRECATED — kept for transition)
    # ------------------------------------------------------------------

    def reconcile_signals(self, trade_db=None, threshold: int = 10) -> Dict:
        """Reconcile signals between JSON and SQLite stores.

        .. deprecated::
            With SQLite as the single source of truth (2A migration),
            reconciliation is no longer necessary.  Use
            :meth:`export_signals_to_json` to regenerate JSON from SQLite.

        Compares the number of signals in ``signals.jsonl`` against the
        ``signal_events`` table in SQLite.  When the JSON count exceeds the
        SQLite count by more than *threshold*, the missing signals are replayed
        from JSON into SQLite via ``trade_db.add_signal_event()``.

        Args:
            trade_db: Optional :class:`TradeDatabase` instance.  Falls back to
                ``self._trade_db`` when *None*.
            threshold: Minimum divergence before replay is triggered (default 10).

        Returns:
            Dict with keys ``json_count``, ``sqlite_count``, ``divergence``,
            ``replayed``, and ``errors``.
        """
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

            # 1. Count JSON signals (line count in signals.jsonl)
            json_count = self.get_signal_count()
            result["json_count"] = json_count

            # 2. Count SQLite signal events (total across all statuses)
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

            # 3. Divergence exceeds threshold -- replay missing signals
            logger.info(
                f"Signal reconciliation: divergence={divergence} exceeds threshold={threshold}, "
                "replaying missing signals from JSON to SQLite"
            )

            # Batch-load existing signal_ids from SQLite for efficient lookup
            existing_ids = db.get_all_signal_ids()

            replayed = 0
            errors = 0

            if self.signals_file.exists():
                with open(self.signals_file, "r") as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            signal_id = record.get("signal_id", "")
                            if not signal_id:
                                continue
                            if signal_id in existing_ids:
                                continue
                            # Replay this signal into SQLite
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
