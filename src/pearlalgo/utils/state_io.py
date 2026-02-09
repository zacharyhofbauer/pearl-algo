"""
Shared state file I/O utilities.

Provides safe reading of JSON and JSONL state files used by the agent.
Both the API server and internal components should use these functions
to ensure consistent parsing behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


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
