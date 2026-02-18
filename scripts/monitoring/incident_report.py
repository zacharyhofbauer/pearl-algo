#!/usr/bin/env python3
# ============================================================================
# Category: Monitoring
# Purpose: Generate incident report for recent drawdown window
# Usage:
#   python3 scripts/monitoring/incident_report.py --market NQ
# ============================================================================
"""
Incident Report Generator

Summarizes performance since a session start time (default: 18:00 ET) with:
- total PnL
- trade breakdown by direction/trigger/regime
- largest-loss drivers
- exposure metrics (concurrent positions, stop-risk exposure)
- duplicate signal counts

Outputs a JSON report into data/agent_state/<MARKET>/exports/.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

from pearlalgo.analytics.incident_analysis import (
    build_incident_report,
    load_events,
    load_trades,
)
from pearlalgo.utils.market_hours import ET
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_events_file,
    get_signals_file,
    parse_utc_timestamp,
)


def _parse_time_hhmm(value: str) -> Tuple[int, int]:
    parts = str(value).split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {value}")
    return int(parts[0]), int(parts[1])


def _default_window_start(now_utc: Optional[datetime] = None, start_hhmm: str = "18:00") -> datetime:
    now_utc = now_utc or datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    sh, sm = _parse_time_hhmm(start_hhmm)
    start_et = now_et.replace(hour=sh, minute=sm, second=0, microsecond=0)
    if now_et < start_et:
        start_et -= timedelta(days=1)
    return start_et.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a recent drawdown incident report")
    parser.add_argument("--market", default="NQ", help="Market label (default: NQ)")
    parser.add_argument("--state-dir", default=None, help="Override state directory")
    parser.add_argument("--since-iso", default=None, help="Explicit UTC ISO timestamp to start from")
    parser.add_argument("--since-et", default="18:00", help="Start time (ET, HH:MM). Default: 18:00")
    parser.add_argument("--output-path", default=None, help="Override report output path")
    args = parser.parse_args()

    state_dir = ensure_state_dir(Path(args.state_dir) if args.state_dir else None)
    signals_file = get_signals_file(state_dir)
    events_file = get_events_file(state_dir)

    if args.since_iso:
        try:
            start_utc = parse_utc_timestamp(args.since_iso)
        except Exception as e:
            raise SystemExit(f"Invalid --since-iso: {e}")
    else:
        start_utc = _default_window_start(start_hhmm=args.since_et)

    trades, _ = load_trades(signals_file, start_utc)
    event_counts = load_events(events_file, start_utc)

    report = build_incident_report(
        trades=trades,
        start_utc=start_utc,
        event_counts=event_counts,
    )

    exports_dir = state_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output_path) if args.output_path else (exports_dir / f"incident_report_{timestamp}.json")
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote incident report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
