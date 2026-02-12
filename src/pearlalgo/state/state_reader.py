"""
State Reader - Safe concurrent reading of agent state files.

Provides locked reads that coordinate with the write locking in
state_manager.py.  Both use fcntl LOCK_EX / LOCK_SH on a shared
lock file to prevent torn reads.

Usage:
    reader = StateReader(state_dir)
    state = reader.read_state()
    signals = reader.read_signals(max_lines=200)
    challenge = reader.read_challenge_state()
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pearlalgo.utils.state_io import load_json_file, load_jsonl_file


class StateReader:
    """Thread-safe reader for agent state files.

    Uses shared (LOCK_SH) file locks that are compatible with the
    exclusive (LOCK_EX) locks taken by MarketAgentStateManager during
    writes.  This prevents torn reads when the API server polls state
    while the agent is mid-write.
    """

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self._state_file = state_dir / "state.json"
        self._signals_file = state_dir / "signals.jsonl"
        self._events_file = state_dir / "events.jsonl"
        self._challenge_file = state_dir / "challenge_state.json"
        # Lock file mirrors state_manager.py convention
        self._lock_file = state_dir / ".state.lock"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_state(self) -> Dict[str, Any]:
        """Read state.json with shared lock.

        Returns empty dict if file is missing or corrupt.
        """
        return self._locked_read_json(self._state_file)

    def read_signals(self, max_lines: int = 2000) -> List[Dict[str, Any]]:
        """Read signals.jsonl with shared lock.

        Args:
            max_lines: Maximum trailing lines to parse.

        Returns:
            List of signal dicts (most recent last).
        """
        return self._locked_read_jsonl(self._signals_file, max_lines=max_lines)

    def read_events(self, max_lines: int = 500) -> List[Dict[str, Any]]:
        """Read events.jsonl with shared lock."""
        return self._locked_read_jsonl(self._events_file, max_lines=max_lines)

    def read_challenge_state(self) -> Optional[Dict[str, Any]]:
        """Read challenge_state.json with shared lock.

        Returns None if file doesn't exist.
        """
        if not self._challenge_file.exists():
            return None
        result = self._locked_read_json(self._challenge_file)
        return result or None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _locked_read_json(self, path: Path) -> Dict[str, Any]:
        """Read a JSON file under shared lock."""
        try:
            with open(self._lock_file, "w") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
                try:
                    return load_json_file(path)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except Exception:
            # Fallback: read without lock (better than no data)
            return load_json_file(path)

    def _locked_read_jsonl(self, path: Path, max_lines: int = 2000) -> List[Dict[str, Any]]:
        """Read a JSONL file under shared lock."""
        try:
            with open(self._lock_file, "w") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
                try:
                    return load_jsonl_file(path, max_lines=max_lines)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except Exception:
            # Fallback: read without lock (better than no data)
            return load_jsonl_file(path, max_lines=max_lines)

    # ------------------------------------------------------------------
    # Async wrappers (offload blocking I/O to thread pool)
    # ------------------------------------------------------------------

    async def async_read_state(self) -> Dict[str, Any]:
        """Async wrapper for read_state -- avoids blocking the event loop."""
        import asyncio
        return await asyncio.to_thread(self.read_state)

    async def async_read_signals(self, max_lines: int = 2000) -> List[Dict[str, Any]]:
        """Async wrapper for read_signals."""
        import asyncio
        return await asyncio.to_thread(self.read_signals, max_lines)
