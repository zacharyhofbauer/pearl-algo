from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def brain_log(entry: Dict[str, Any], base_dir: Path | None = None) -> Path:
    """
    Append a JSON line to logs/trade_brain/YYYYMMDD.log.
    """
    base = base_dir or Path("logs/trade_brain")
    base.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = base / f"{today}.log"
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return path
