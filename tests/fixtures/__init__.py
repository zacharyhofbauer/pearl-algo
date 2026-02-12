"""Test fixtures package containing shared test data generators and assets."""

import json
from pathlib import Path
from typing import Any, Dict, List

FIXTURES_DIR = Path(__file__).parent


def load_sample_state() -> Dict[str, Any]:
    """Load the golden sample state.json fixture."""
    return json.loads((FIXTURES_DIR / "sample_state.json").read_text())


def load_sample_signals() -> List[Dict[str, Any]]:
    """Load the golden sample signals.jsonl fixture (all lines)."""
    lines = (FIXTURES_DIR / "sample_signals.jsonl").read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load_sample_performance() -> List[Dict[str, Any]]:
    """Load the golden sample performance.json fixture."""
    return json.loads((FIXTURES_DIR / "sample_performance.json").read_text())


def load_sample_config_text() -> str:
    """Load the golden sample config.yaml fixture as raw text."""
    return (FIXTURES_DIR / "sample_config.yaml").read_text()
