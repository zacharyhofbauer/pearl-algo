"""
NQ Agent State Manager

Manages state persistence for the NQ agent service.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_signals_file,
    get_state_file,
    get_utc_timestamp,
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
            state_dir: Directory for state files (default: ./data/nq_agent_state)
        """
        self.state_dir = ensure_state_dir(state_dir)
        self.signals_file = get_signals_file(self.state_dir)
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
                    db_path_raw = storage_cfg.get("db_path") or str(self.state_dir / "trades.db")
                    self._trade_db = TradeDatabase(Path(str(db_path_raw)))
            except Exception as e:
                logger.debug(f"SQLite storage not enabled/available: {e}")

        logger.info(f"NQAgentStateManager initialized: state_dir={self.state_dir}")

    def save_signal(self, signal: Dict) -> None:
        """
        Save a signal to persistent storage.
        
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
                from datetime import datetime, timezone
                signal_id = f"{signal.get('type', 'unknown')}_{datetime.now(timezone.utc).timestamp()}"
                signal["signal_id"] = signal_id
            
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

            with open(self.signals_file, "a") as f:
                f.write(payload + "\n")

            # Dual-write to SQLite (append-only signal event log)
            try:
                if self._sqlite_enabled and self._trade_db is not None:
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

    def save_state(self, state: Dict) -> None:
        """
        Save service state.
        
        Args:
            state: State dictionary
        """
        try:
            state["last_updated"] = get_utc_timestamp()
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
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
