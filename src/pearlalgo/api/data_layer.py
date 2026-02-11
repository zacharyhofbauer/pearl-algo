"""
Data layer for the Pearl API server.

Provides TTL-cached file I/O, state reading, MFFU account detection, and
signal/performance data loading.  All functions are synchronous unless noted.

This module was extracted from server.py to improve testability and reduce
the size of the main router module.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from pearlalgo.market_agent.state_reader import StateReader
from pearlalgo.utils.state_io import (
    load_json_file as _load_json_file,
    load_jsonl_file as _load_jsonl_file,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL Cache
# ---------------------------------------------------------------------------

_ttl_cache: Dict[str, Any] = {}
_ttl_cache_lock = threading.Lock()
_TTL_CLEANUP_INTERVAL = 60.0  # seconds between expired-entry sweeps
_last_ttl_cleanup: float = 0.0


def _cleanup_ttl_cache() -> None:
    """Remove all expired entries from ``_ttl_cache``.

    Must be called while ``_ttl_cache_lock`` is held.
    """
    global _last_ttl_cleanup
    now = time.monotonic()
    expired_keys = [k for k, (_, expires) in _ttl_cache.items() if now >= expires]
    for k in expired_keys:
        del _ttl_cache[k]
    _last_ttl_cleanup = now


def cached(key: str, ttl_seconds: float, fn, *args, **kwargs):
    """Return cached result if still fresh, otherwise call *fn* and cache.

    This is the central TTL cache used throughout the API server.
    """
    now = time.monotonic()
    with _ttl_cache_lock:
        if now - _last_ttl_cleanup >= _TTL_CLEANUP_INTERVAL:
            _cleanup_ttl_cache()

        entry = _ttl_cache.get(key)
        if entry is not None:
            value, expires = entry
            if now < expires:
                return value
    # Compute outside lock to avoid blocking other readers
    result = fn(*args, **kwargs)
    with _ttl_cache_lock:
        _ttl_cache[key] = (result, now + ttl_seconds)
    return result


# ---------------------------------------------------------------------------
# StateReader cache (bounded LRU)
# ---------------------------------------------------------------------------

_STATE_READER_CACHE_MAX = 10
_state_reader_cache: OrderedDict[str, StateReader] = OrderedDict()
_state_reader_cache_lock = threading.Lock()


def read_state_for_dir(state_dir: Path) -> Dict[str, Any]:
    """Read state.json via a locked StateReader for the given directory.

    Caches the StateReader per directory to avoid repeated construction.
    Thread-safe with LRU eviction (max ``_STATE_READER_CACHE_MAX`` entries).
    """
    key = str(state_dir)
    with _state_reader_cache_lock:
        if key in _state_reader_cache:
            _state_reader_cache.move_to_end(key)
            return _state_reader_cache[key].read_state()
    # Build outside lock to avoid blocking other readers during construction
    reader = StateReader(state_dir)
    with _state_reader_cache_lock:
        if key not in _state_reader_cache:
            _state_reader_cache[key] = reader
            while len(_state_reader_cache) > _STATE_READER_CACHE_MAX:
                _state_reader_cache.popitem(last=False)
        else:
            _state_reader_cache.move_to_end(key)
    return reader.read_state()


# ---------------------------------------------------------------------------
# MFFU account detection
# ---------------------------------------------------------------------------

def is_mffu_account(state_dir: Path) -> bool:
    """Check if this state_dir has live Tradovate account data (MFFU mode).

    Uses key-presence (``"equity" in tv``) rather than truthiness so that
    equity == 0 during initialisation is still detected as MFFU.
    """
    try:
        data = read_state_for_dir(state_dir)
        if data:
            tv = data.get("tradovate_account")
            if tv and isinstance(tv, dict) and "equity" in tv:
                equity = tv.get("equity")
                if equity == 0:
                    logger.warning(
                        "MFFU account detected with equity=0 — "
                        "Tradovate data may still be initialising"
                    )
                return True
    except Exception as e:
        logger.warning(f"Non-critical: {e}")
    return False


# ---------------------------------------------------------------------------
# Start balance
# ---------------------------------------------------------------------------

_DEFAULT_START_BALANCE = 50_000.0


def get_start_balance(state_dir: Path) -> float:
    """Read MFFU start balance from challenge_state.json, or return default."""
    try:
        ch_file = state_dir / "challenge_state.json"
        if ch_file.exists():
            ch_data = json.loads(ch_file.read_text())
            return float(
                ch_data.get("config", {}).get("start_balance", _DEFAULT_START_BALANCE)
            )
    except Exception as e:
        logger.debug(f"Could not read start_balance: {e}")
    return _DEFAULT_START_BALANCE


# ---------------------------------------------------------------------------
# Performance data loading
# ---------------------------------------------------------------------------

def get_cached_performance_data(state_dir: Path) -> dict:
    """Load performance.json with a 5-second TTL cache.

    Returns a dict with a ``"trades"`` key holding the list of trade records,
    or an empty dict when the file is missing / invalid.
    """
    def _read_perf() -> dict:
        pf = state_dir / "performance.json"
        if not pf.exists():
            return {}
        try:
            data = json.loads(pf.read_text())
            if isinstance(data, list):
                return {"trades": data}
            return {}
        except Exception:
            return {}

    return cached(f"perf_data:{state_dir}", 5.0, _read_perf)


def load_performance_data(state_dir: Path) -> Optional[list]:
    """Load and parse performance.json (shared by equity_curve & risk_metrics).

    Delegates to :func:`get_cached_performance_data` so the underlying
    disk read is shared across all callers within the 5-second TTL window.
    """
    return get_cached_performance_data(state_dir).get("trades")


# ---------------------------------------------------------------------------
# Signals loading (TTL-cached)
# ---------------------------------------------------------------------------

def get_signals(state_dir: Path, max_lines: int = 2000) -> List[Dict[str, Any]]:
    """Load signals.jsonl with a short TTL cache.

    The cache key includes ``max_lines`` so callers requesting different
    limits get appropriately sized results.
    """
    def _read_signals() -> List[Dict[str, Any]]:
        signals_file = state_dir / "signals.jsonl"
        if not signals_file.exists():
            return []
        return _load_jsonl_file(signals_file, max_lines=max_lines)

    return cached(f"signals:{state_dir}:{max_lines}", 2.0, _read_signals)
