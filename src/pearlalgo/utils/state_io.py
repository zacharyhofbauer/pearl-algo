"""
Shared state file I/O utilities.

Provides safe reading/writing of JSON and JSONL state files used by the agent.
Both the API server and internal components should use these functions
to ensure consistent parsing behavior.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List

from pearlalgo.utils.paths import get_utc_timestamp


def load_json_file(path: Path) -> Dict[str, Any]:
    """Load a JSON file, returning empty dict on error.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed dict, or empty dict if file is missing/corrupt.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_jsonl_file(path: Path, max_lines: int = 2000) -> List[Dict[str, Any]]:
    """Load last *max_lines* entries from a JSONL file.

    Args:
        path: Path to the JSONL file.
        max_lines: Maximum number of trailing lines to parse.

    Returns:
        List of parsed dicts (skips malformed lines).
    """
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        result: List[Dict[str, Any]] = []
        for line in lines[-max_lines:]:
            if line.strip():
                try:
                    result.append(json.loads(line))
                except Exception:
                    pass
        return result
    except Exception:
        return []



# ---------------------------------------------------------------------------
# File locking
# ---------------------------------------------------------------------------

@contextmanager
def file_lock(
    lock_path: Path,
    *,
    shared: bool = False,
) -> Generator[None, None, None]:
    """Context manager that acquires an ``fcntl`` file lock.

    Usage::

        with file_lock(Path("my.lock")):
            # ... exclusive access ...

    Args:
        lock_path: Path to the lock file (created if it doesn't exist).
        shared: If ``True``, acquire a shared (read) lock instead of
            exclusive (write) lock.

    Yields:
        ``None`` – the lock is released when the context exits.
    """
    mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    with open(lock_path, "w") as lock:
        fcntl.flock(lock.fileno(), mode)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------

def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Atomically write a JSON file using temp-file + fsync + rename.

    Ensures that readers never see a partially-written file.  On failure
    the original file is left untouched and the temp file is cleaned up.

    Args:
        path: Destination file path.
        data: JSON-serializable data.
        indent: JSON indentation level (set to ``None`` for compact).
    """
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(path.parent),
            delete=False,
            suffix=".tmp",
        ) as tmp_f:
            json.dump(data, tmp_f, indent=indent)
            tmp_f.flush()
            os.fsync(tmp_f.fileno())
            tmp_path = tmp_f.name
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def atomic_write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    """Atomically write a JSONL file using temp-file + fsync + rename.

    Each record is written as a single JSON line.  On failure the original
    file is left untouched and the temp file is cleaned up.

    Args:
        path: Destination file path.
        records: List of JSON-serializable dicts (one per line).
    """
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(path.parent),
            delete=False,
            suffix=".tmp",
        ) as tmp_f:
            for record in records:
                tmp_f.write(json.dumps(record) + "\n")
            tmp_f.flush()
            os.fsync(tmp_f.fileno())
            tmp_path = tmp_f.name
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


# ---------------------------------------------------------------------------
# Signal record helpers
# ---------------------------------------------------------------------------

def create_minimal_signal_record(signal_id: str, signal: Dict[str, Any]) -> Dict[str, Any]:
    """Create a minimal, guaranteed-serializable signal record.

    Used as a fallback when full signal serialization fails (e.g. due to
    numpy/pandas types that ``json.dumps`` cannot handle).  The returned
    dict contains only primitive types and is always JSON-safe.

    Args:
        signal_id: Unique identifier for the signal.
        signal: The original signal dict (values are coerced to strings/floats).

    Returns:
        A dict suitable for ``json.dumps()`` without a custom encoder.
    """
    return {
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
