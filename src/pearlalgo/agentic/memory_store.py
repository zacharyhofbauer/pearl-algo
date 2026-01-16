from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class MemoryStore:
    """
    Durable, agent-scoped memory.

    Storage
    - JSON file under the agent state directory

    Contract
    - Explicit key/value store
    - No implicit writes
    - Last-write-wins
    """

    path: Path

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save(self, data: Dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        data = self.load()
        return data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        data = self.load()
        data[key] = value
        data["_updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save(data)

    def append_event(self, name: str, payload: Optional[Dict[str, Any]] = None, *, limit: int = 200) -> None:
        data = self.load()
        events = data.get("events", [])
        if not isinstance(events, list):
            events = []
        events.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "name": str(name),
                "payload": payload or {},
            }
        )
        data["events"] = events[-int(limit) :]
        data["_updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save(data)

