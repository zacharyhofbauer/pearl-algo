from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def append_chat_example(
    state_dir: Path,
    *,
    user_text: str,
    response: str,
    system_snapshot: Optional[str] = None,
    memory_summary: Optional[str] = None,
    code_context: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_text": user_text,
        "response": response,
        "system_snapshot": system_snapshot or "",
        "memory_summary": memory_summary or "",
        "code_context": code_context or "",
        "model": model or "",
    }
    _append_jsonl(state_dir / "exports" / "pearl_chat_dataset.jsonl", payload)


def append_patch_example(
    state_dir: Path,
    *,
    instruction: str,
    file_path: str,
    diff: str,
    additional_context: Optional[str] = None,
    code_context: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instruction": instruction,
        "file_path": file_path,
        "diff": diff,
        "additional_context": additional_context or "",
        "code_context": code_context or "",
        "model": model or "",
    }
    _append_jsonl(state_dir / "exports" / "pearl_patch_dataset.jsonl", payload)
