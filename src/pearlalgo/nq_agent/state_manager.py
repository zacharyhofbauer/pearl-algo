"""
NQ Agent State Manager

Manages state persistence for the NQ agent service.
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

# Import get_utc_timestamp is already in the import above


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
        except Exception:
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
    except Exception:
        pass

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
    except Exception:
        pass

    # Fallback
    return str(obj)


class NQAgentStateManager:
    """
    Manages state persistence for NQ agent.
    
    Stores signals, positions, and service state.
    """

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize state manager.
        
        Args:
            state_dir: Directory for state files (default: ./data/agent_state/<MARKET>)
        """
        # Track whether the caller explicitly provided a state_dir (tests do this via tmp_path).
        # If explicit, ALL persistence (including SQLite) must stay inside that directory to
        # avoid unit tests polluting the live agent state under data/agent_state/<MARKET>.
        self._explicit_state_dir = state_dir is not None

        self.state_dir = ensure_state_dir(state_dir)
        self.signals_file = get_signals_file(self.state_dir)
        self.events_file = get_events_file(self.state_dir)
        self.state_file = get_state_file(self.state_dir)

        # Optional SQLite dual-write (platform memory). Keep file writes as-is for Telegram/mobile.
        self._sqlite_enabled = False
        self._trade_db = None
        if SQLITE_AVAILABLE:
            try:
                from pearlalgo.config.config_loader import load_service_config

                cfg = load_service_config(validate=False) or {}
                storage_cfg = cfg.get("storage", {}) or {}
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
                logger.debug(f"SQLite storage not enabled/available: {e}")

        # Load duplicate detection settings from config
        try:
            from pearlalgo.config.config_loader import load_service_config
            cfg = load_service_config(validate=False) or {}
            signal_settings = cfg.get("signals", {}) or {}
            self._duplicate_window_seconds = signal_settings.get("duplicate_window_seconds", 120)
            self._duplicate_price_threshold_pct = (
                signal_settings.get("duplicate_price_threshold_pct", 0.5) / 100.0
            )
        except Exception as e:
            logger.debug(f"Could not load duplicate detection settings: {e}")
            self._duplicate_window_seconds = 120
            self._duplicate_price_threshold_pct = 0.005

        logger.info(f"NQAgentStateManager initialized: state_dir={self.state_dir}")

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
        except Exception:
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
            except Exception:
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

            if within_time_window or price_close:
                return True

        return False

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
                        # Read recent signals for duplicate checking
                        recent_signals = []
                        if self.signals_file.exists():
                            try:
                                with open(self.signals_file, "r") as f:
                                    lines = f.readlines()
                                    # Read last 100 signals (enough to cover duplicate window)
                                    for line in lines[-100:]:
                                        try:
                                            record = json.loads(line.strip())
                                            recent_signals.append(record)
                                        except json.JSONDecodeError:
                                            continue
                            except Exception as e:
                                logger.debug(f"Error reading signals for duplicate check: {e}")
                        
                        # Check for duplicates
                        if self._is_duplicate_signal(signal, recent_signals):
                            logger.debug(
                                f"Skipping duplicate signal: {signal_id} (type={signal.get('type')}, "
                                f"direction={signal.get('direction')})"
                            )
                            return
                        
                        # Create wrapped record in format expected by /signals command
                        signal_record = {
                            "signal_id": signal_id,
                            "timestamp": get_utc_timestamp(),
                            "status": "generated",  # Default status for new signals
                            "signal": _to_json_safe(signal),  # Store JSON-safe signal dict
                        }

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
                logger.debug(f"Could not write signal event to SQLite: {e}")
            
            logger.debug(f"Saved signal {signal_id} to {self.signals_file}")
        except Exception as e:
            logger.error(f"Error saving signal: {e}", exc_info=True)

    def get_recent_signals(self, limit: int = 100) -> List[Dict]:
        """
        Get recent signals.
        
        Args:
            limit: Maximum number of signals to return
            
        Returns:
            List of signal dictionaries
        """
        signals = []

        if not self.signals_file.exists():
            return signals

        try:
            with open(self.signals_file, "r") as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    try:
                        signal = json.loads(line.strip())
                        signals.append(signal)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error reading signals: {e}")

        return signals

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
                    with open(self.events_file, "a") as f:
                        f.write(json.dumps(record) + "\n")
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except Exception:
            # Fallback: unlocked append
            try:
                with open(self.events_file, "a") as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                logger.debug(f"Failed to append event: {e}")

    def get_recent_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Get recent events from events.jsonl (best-effort)."""
        events: List[Dict[str, Any]] = []
        if not self.events_file.exists():
            return events
        try:
            with open(self.events_file, "r") as f:
                lines = f.readlines()
            for line in lines[-max(1, int(limit)) :]:
                try:
                    events.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            logger.debug(f"Error reading events: {e}")
        return events

    def save_state(self, state: Dict) -> None:
        """
        Save service state.
        
        Args:
            state: State dictionary
        """
        try:
            state["last_updated"] = get_utc_timestamp()
            tmp_path = Path(str(self.state_file) + ".tmp")
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_file)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def load_state(self) -> Dict:
        """
        Load service state.
        
        Returns:
            State dictionary (empty dict if no state exists)
        """
        if not self.state_file.exists():
            return {}

        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            return {}
