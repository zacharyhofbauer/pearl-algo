"""
Path and timestamp utilities for consistent file and directory handling.

This module provides centralized utilities for:
- State directory initialization and management
- Standard file path construction (signals, state, performance)
- UTC timestamp formatting and parsing

All functions use consistent defaults and patterns to ensure maintainability.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def ensure_state_dir(state_dir: Optional[Path] = None) -> Path:
    """
    Ensure state directory exists, creating it if necessary.
    
    Args:
        state_dir: Optional state directory path (defaults to "data/nq_agent_state")
        
    Returns:
        Path to the state directory (guaranteed to exist)
    """
    if state_dir is None:
        state_dir = Path("data/nq_agent_state")
    
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    return state_path


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


def get_performance_file(state_dir: Path) -> Path:
    """
    Get path to performance file.
    
    Args:
        state_dir: State directory path
        
    Returns:
        Path to performance.json file
    """
    return state_dir / "performance.json"


def get_utc_timestamp() -> str:
    """
    Get current UTC timestamp in ISO format.
    
    Returns:
        ISO format UTC timestamp string (e.g., "2025-12-16T10:30:45.123456+00:00")
    """
    return datetime.now(timezone.utc).isoformat()


def parse_utc_timestamp(timestamp: str) -> datetime:
    """
    Parse UTC timestamp from ISO format string.
    
    Handles both "Z" suffix and "+00:00" timezone formats.
    
    Args:
        timestamp: ISO format timestamp string
        
    Returns:
        datetime object with UTC timezone
        
    Raises:
        ValueError: If timestamp cannot be parsed
    """
    # Handle "Z" suffix (replace with "+00:00" for fromisoformat)
    normalized = timestamp.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)
