"""
Path and timestamp utilities for consistent file and directory handling.

This module provides centralized utilities for:
- State directory initialization and management
- Standard file path construction (signals, state, performance)
- ET timestamp formatting and parsing (America/New_York)

All functions use consistent defaults and patterns to ensure maintainability.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional


def ensure_state_dir(state_dir: Optional[Path] = None) -> Path:
    """
    Ensure state directory exists, creating it if necessary.
    
    Args:
        state_dir: Optional state directory path (defaults to "data/agent_state/<MARKET>")
        
    Returns:
        Path to the state directory (guaranteed to exist)
    """
    if state_dir is None:
        env_state_dir = os.getenv("PEARLALGO_STATE_DIR")
        if env_state_dir:
            state_dir = Path(env_state_dir)
        else:
            market = os.getenv("PEARLALGO_MARKET")
            market_label = str(market or "NQ").strip().upper()
            state_dir = Path("data") / "agent_state" / market_label
    
    state_path = Path(state_dir).expanduser()
    state_path.mkdir(parents=True, exist_ok=True)
    # Return an absolute path for consistency (tests + operators).
    return state_path.resolve()


def get_signals_file(state_dir: Path) -> Path:
    """
    Get path to signals file.
    
    Args:
        state_dir: State directory path
        
    Returns:
        Path to signals.jsonl file
    """
    return state_dir / "signals.jsonl"


def get_state_file(state_dir: Path) -> Path:
    """
    Get path to state file.
    
    Args:
        state_dir: State directory path
        
    Returns:
        Path to state.json file
    """
    return state_dir / "state.json"


def get_events_file(state_dir: Path) -> Path:
    """
    Get path to events file (append-only JSONL).

    Args:
        state_dir: State directory path

    Returns:
        Path to events.jsonl file
    """
    return state_dir / "events.jsonl"


def get_performance_file(state_dir: Path) -> Path:
    """
    Get path to performance file.
    
    Args:
        state_dir: State directory path
        
    Returns:
        Path to performance.json file
    """
    return state_dir / "performance.json"


_ET = ZoneInfo("America/New_York")


def get_et_timestamp() -> str:  # FIXED 2026-03-25: store ET not UTC
    """
    Get current ET timestamp as naive ISO string.

    Returns:
        Naive ISO format ET timestamp string (e.g., "2025-12-16T10:30:45")
    """
    return datetime.now(_ET).strftime('%Y-%m-%dT%H:%M:%S')


def get_utc_timestamp() -> str:
    """Deprecated: use get_et_timestamp(). Kept for non-trade callers."""
    return datetime.now(timezone.utc).isoformat()


def parse_utc_timestamp(timestamp: str) -> datetime:
    """Deprecated wrapper — calls parse_trade_timestamp()."""
    return parse_trade_timestamp(timestamp)


def parse_trade_timestamp(timestamp: str) -> datetime:
    """
    Parse a trade timestamp string and return a naive ET datetime.

    Handles all formats:
    - Naive ET strings (post-migration): '2026-03-25T14:28:00'
    - UTC with +00:00 suffix (legacy): '2026-03-25T18:28:00+00:00'
    - UTC with Z suffix (legacy): '2026-03-25T18:28:00Z'

    Always returns a naive datetime in ET for consistent comparison.

    Args:
        timestamp: ISO format timestamp string

    Returns:
        Naive datetime in America/New_York

    Raises:
        ValueError: If timestamp cannot be parsed
    """
    normalized = timestamp.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        # Already naive ET (post-migration)
        return dt
    # Legacy tz-aware timestamp — convert to naive ET
    dt_et = dt.astimezone(_ET)
    return dt_et.replace(tzinfo=None)






