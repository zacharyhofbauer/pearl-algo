"""
Data layer for the Pearl API server.

Provides TTL-cached file I/O, state reading, Tradovate Paper account detection, and
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
# Tradovate Paper account detection
# ---------------------------------------------------------------------------

_TV_PAPER_ACCOUNT_TTL = 60.0  # seconds — account type rarely changes mid-session


def _detect_tv_paper_account(state_dir: Path) -> bool:
    """Inner detection logic (uncached)."""
    try:
        data = read_state_for_dir(state_dir)
        if data:
            tv = data.get("tradovate_account")
            if tv and isinstance(tv, dict) and "equity" in tv:
                equity = tv.get("equity")
                if equity == 0:
                    logger.warning(
                        "Tradovate Paper account detected with equity=0 — "
                        "Tradovate data may still be initialising"
                    )
                return True
    except Exception as e:
        logger.warning(f"Non-critical: {e}")
    return False


def is_tv_paper_account(state_dir: Path) -> bool:
    """Check if this state_dir has live Tradovate account data (Tradovate Paper mode).

    Uses key-presence (``"equity" in tv``) rather than truthiness so that
    equity == 0 during initialisation is still detected as Tradovate Paper.

    Result is cached with a 60-second TTL to avoid repeated disk reads —
    account type does not change during a session.
    """
    return cached(
        f"is_tv_paper:{state_dir}", _TV_PAPER_ACCOUNT_TTL,
        _detect_tv_paper_account, state_dir,
    )


# ---------------------------------------------------------------------------
# TvPaperChallengeState — typed representation of challenge state extensions
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field


@dataclass
class TvPaperChallengeState:
    """Typed representation of the Tradovate Paper challenge state extensions.

    Replaces the repeated ``.get("tv_paper")`` chains scattered through
    server.py, providing typed access and sensible defaults.
    """

    stage: str = "evaluation"
    eod_high_water_mark: Optional[float] = None
    current_drawdown_floor: Optional[float] = None
    drawdown_locked: bool = False
    consistency: Dict[str, Any] = field(default_factory=dict)
    min_days: Dict[str, Any] = field(default_factory=dict)
    trading_days_count: int = 0
    max_contracts_mini: int = 5

    @classmethod
    def from_challenge_data(cls, data: Dict[str, Any]) -> Optional["TvPaperChallengeState"]:
        """Parse from a challenge_state.json dict.

        Returns ``None`` if no ``"tv_paper"`` key is present.
        """
        tv_paper = data.get("tv_paper")
        if not tv_paper or not isinstance(tv_paper, dict):
            return None
        return cls(
            stage=str(tv_paper.get("stage", "evaluation")),
            eod_high_water_mark=_safe_float(tv_paper.get("eod_high_water_mark")),
            current_drawdown_floor=_safe_float(tv_paper.get("current_drawdown_floor")),
            drawdown_locked=bool(tv_paper.get("drawdown_locked", False)),
            consistency=tv_paper.get("consistency", {}) if isinstance(tv_paper.get("consistency"), dict) else {},
            min_days=tv_paper.get("min_days", {}) if isinstance(tv_paper.get("min_days"), dict) else {},
            trading_days_count=int(tv_paper.get("trading_days_count", 0)),
            max_contracts_mini=int(tv_paper.get("max_contracts_mini", 5)),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a dict suitable for JSON API responses."""
        return {
            "stage": self.stage,
            "eod_high_water_mark": self.eod_high_water_mark,
            "current_drawdown_floor": self.current_drawdown_floor,
            "drawdown_locked": self.drawdown_locked,
            "consistency": self.consistency,
            "min_days": self.min_days,
            "trading_days_count": self.trading_days_count,
            "max_contracts_mini": self.max_contracts_mini,
        }


def _safe_float(value: Any) -> Optional[float]:
    """Convert to float if possible, otherwise return ``None``."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Cached challenge state accessor
# ---------------------------------------------------------------------------

_CHALLENGE_STATE_TTL = 10.0  # seconds — refreshes often enough for dashboards


def get_cached_challenge_state(state_dir: Path) -> Optional[TvPaperChallengeState]:
    """Load and parse challenge_state.json with a 10-second TTL cache.

    Returns ``None`` if the file doesn't exist or has no ``"tv_paper"`` key.
    """
    def _read() -> Optional[TvPaperChallengeState]:
        ch_file = state_dir / "challenge_state.json"
        if not ch_file.exists():
            return None
        try:
            data = json.loads(ch_file.read_text(encoding="utf-8"))
            return TvPaperChallengeState.from_challenge_data(data)
        except Exception as exc:
            logger.debug(f"Could not parse challenge_state.json: {exc}")
            return None

    return cached(f"challenge_state:{state_dir}", _CHALLENGE_STATE_TTL, _read)


# ---------------------------------------------------------------------------
# Start balance
# ---------------------------------------------------------------------------

_DEFAULT_START_BALANCE = 50_000.0


def get_start_balance(state_dir: Path) -> float:
    """Read Tradovate Paper start balance from challenge_state.json, or return default."""
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


# ---------------------------------------------------------------------------
# Cursor-based paginated signals reader
# ---------------------------------------------------------------------------

# Per-directory tracking of the file offset we last read to.
_signals_cursor: Dict[str, int] = {}  # state_dir_str -> last_read_byte_offset
_signals_cursor_lock = threading.Lock()


def get_signals_paginated(
    state_dir: Path,
    *,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """Return paginated signals with a cursor for incremental reads.

    Parameters
    ----------
    state_dir : Path
        Agent state directory containing ``signals.jsonl``.
    limit : int
        Maximum number of signal entries to return.
    cursor : str, optional
        Opaque cursor string from a previous call.  When ``None`` or
        ``"latest"``, returns the most recent *limit* entries.

    Returns
    -------
    dict with keys:
        ``"signals"`` — list of signal dicts (newest last)
        ``"cursor"``  — opaque cursor for the next call
        ``"has_more"`` — whether older signals exist before the cursor
    """
    signals_file = state_dir / "signals.jsonl"
    if not signals_file.exists():
        return {"signals": [], "cursor": "0", "has_more": False}

    try:
        file_size = signals_file.stat().st_size
    except OSError:
        return {"signals": [], "cursor": "0", "has_more": False}

    if file_size == 0:
        return {"signals": [], "cursor": "0", "has_more": False}

    # Parse cursor — it encodes a byte offset in the file
    start_offset: int = 0
    if cursor and cursor != "latest":
        try:
            start_offset = int(cursor)
        except (ValueError, TypeError):
            start_offset = 0

    # If no cursor (or "latest"), read the last N entries via tail-read
    if start_offset <= 0 or cursor == "latest" or cursor is None:
        entries = _load_jsonl_file(signals_file, max_lines=limit)
        new_cursor = str(file_size)
        return {
            "signals": entries,
            "cursor": new_cursor,
            "has_more": file_size > 0 and len(entries) >= limit,
        }

    # Incremental read: read only bytes added since last cursor
    if start_offset >= file_size:
        # No new data
        return {"signals": [], "cursor": str(file_size), "has_more": False}

    try:
        with open(signals_file, "r", encoding="utf-8") as f:
            f.seek(start_offset)
            new_bytes = f.read()
    except OSError:
        return {"signals": [], "cursor": str(file_size), "has_more": False}

    entries: List[Dict[str, Any]] = []
    for line in new_bytes.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Only return up to limit (most recent)
    if len(entries) > limit:
        entries = entries[-limit:]

    return {
        "signals": entries,
        "cursor": str(file_size),
        "has_more": len(entries) >= limit,
    }


