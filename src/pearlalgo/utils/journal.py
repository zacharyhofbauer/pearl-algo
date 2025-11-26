from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any


JOURNAL_PATH = Path("journal/trades.csv")


def append_trade(row: Dict[str, Any], path: Path = JOURNAL_PATH) -> Path:
    """
    Append a trade/signal row to the journal CSV.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    if "timestamp" not in row:
        row["timestamp"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "symbol",
                "direction",
                "size",
                "price",
                "reason",
                "pnl_after",
                "risk_state",
            ],
        )
        if is_new:
            writer.writeheader()
        writer.writerow(row)
    return path
