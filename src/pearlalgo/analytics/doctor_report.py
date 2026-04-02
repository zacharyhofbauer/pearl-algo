"""
Doctor Report

Builds a rollup of recent trading behavior including signal events,
trade exits, and cycle diagnostics.

This module provides the business logic for the /doctor command.
The CLI wrapper is located at scripts/monitoring/doctor_cli.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


def _fmt_pct(x: float) -> str:
    """Format a float as a percentage string."""
    try:
        return f"{(float(x) * 100):.0f}%"
    except Exception:
        return "0%"


def build_doctor_rollup(db: Any, *, hours: float = 24.0) -> Dict[str, Any]:
    """
    Build a comprehensive rollup of recent trading behavior.

    Args:
        db: TradeDatabase instance for querying trade data
        hours: Lookback window in hours (default: 24)

    Returns:
        Dictionary with events, trade summary, diagnostics, and distributions
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=float(hours))).isoformat()

    event_counts = db.get_signal_event_counts(from_time=cutoff)
    diag = db.get_cycle_diagnostics_aggregate(from_time=cutoff)
    quiet_top = db.get_quiet_reason_counts(from_time=cutoff, limit=5)
    trade_summary = db.get_trade_summary(from_exit_time=cutoff)

    gen_events = db.get_signal_events(status="generated", from_time=cutoff, limit=5000)

    stop_bins = [
        ("<5", 0.0, 5.0),
        ("5-10", 5.0, 10.0),
        ("10-15", 10.0, 15.0),
        ("15-20", 15.0, 20.0),
        ("20-25", 20.0, 25.0),
        (">25", 25.0, 10_000.0),
    ]
    size_bins = [
        ("1", 1.0, 1.0),
        ("2-3", 2.0, 3.0),
        ("4-5", 4.0, 5.0),
        ("6-8", 6.0, 8.0),
        ("9-12", 9.0, 12.0),
        ("13-15", 13.0, 15.0),
        (">15", 15.0, 10_000.0),
    ]

    stop_counts = {k: 0 for (k, _, _) in stop_bins}
    size_counts = {k: 0 for (k, _, _) in size_bins}
    stop_samples: List[float] = []
    size_samples: List[float] = []
    for ev in gen_events:
        payload = ev.get("payload", {}) or {}
        sig = payload.get("signal", {}) if isinstance(payload, dict) else {}
        if not isinstance(sig, dict):
            continue

        # stop distance
        try:
            entry = float(sig.get("entry_price", 0.0) or 0.0)
            stop = float(sig.get("stop_loss", 0.0) or 0.0)
        except Exception:
            entry, stop = 0.0, 0.0

        if entry > 0 and stop > 0:
            dist = abs(entry - stop)
            stop_samples.append(dist)
            for label, lo, hi in stop_bins:
                if lo <= dist < hi:
                    stop_counts[label] += 1
                    break

        # size
        try:
            size = float(sig.get("position_size", 0.0) or 0.0)
        except Exception:
            size = 0.0
        if size > 0:
            size_samples.append(size)
            for label, lo, hi in size_bins:
                if label == "1":
                    if abs(size - 1.0) < 1e-9:
                        size_counts[label] += 1
                        break
                else:
                    if lo <= size <= hi:
                        size_counts[label] += 1
                        break

    stop_avg = None
    stop_med = None
    size_avg = None
    size_med = None
    try:
        import numpy as np

        if stop_samples:
            stop_avg = float(np.mean(stop_samples))
            stop_med = float(np.median(stop_samples))
        if size_samples:
            size_avg = float(np.mean(size_samples))
            size_med = float(np.median(size_samples))
    except Exception:
        pass

    return {
        "window_hours": float(hours),
        "cutoff": cutoff,
        "events": event_counts,
        "trade_summary": trade_summary,
        "cycle_diagnostics": diag,
        "quiet_reasons_top": quiet_top,
        "stop_bins": stop_counts,
        "size_bins": size_counts,
        "stop_avg": stop_avg,
        "stop_median": stop_med,
        "size_avg": size_avg,
        "size_median": size_med,
    }


def format_doctor_rollup_text(r: Dict[str, Any]) -> str:
    """
    Format a doctor rollup as human-readable text.

    Args:
        r: Rollup dictionary from build_doctor_rollup()

    Returns:
        Formatted text string
    """
    lines: List[str] = []
    try:
        hours_val = float(r.get("window_hours", 24.0) or 24.0)
    except Exception:
        hours_val = 24.0
    hours_label = str(int(hours_val)) if hours_val.is_integer() else f"{hours_val:.2f}".rstrip("0").rstrip(".")
    lines.append(f"Doctor (last {hours_label}h)")
    lines.append("")

    # Signals
    lines.append("Signals (events):")
    events = r.get("events") or {}
    if events:
        for k in ("generated", "entered", "exited", "expired"):
            if k in events:
                lines.append(f"- {k}: {int(events.get(k, 0) or 0)}")
    else:
        lines.append("- (no events)")
    lines.append("")

    # Trades
    ts = r.get("trade_summary") or {}
    total = int(ts.get("total", 0) or 0)
    lines.append("Trades (exited):")
    lines.append(f"- total: {total}")
    if total > 0:
        lines.append(f"- WR: {_fmt_pct(ts.get('win_rate', 0.0) or 0.0)}")
        try:
            pnl = float(ts.get("total_pnl", 0.0) or 0.0)
            pnl_str = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
        except Exception:
            pnl_str = "$0"
        lines.append(f"- P&L: {pnl_str}")
        try:
            avg_hold = ts.get("avg_hold_minutes")
            if avg_hold is not None:
                lines.append(f"- avg hold: {float(avg_hold):.1f}m")
        except Exception:
            pass
    lines.append("")

    # Rejections
    diag = r.get("cycle_diagnostics") or {}
    lines.append("Rejections (cycle totals):")
    any_rej = False
    for key, label in [
        ("rejected_market_hours", "market hours"),
        ("rejected_confidence", "confidence"),
        ("rejected_risk_reward", "R:R"),
        ("rejected_regime_filter", "regime/session"),
        ("rejected_quality_scorer", "quality"),
        ("rejected_order_book", "order book"),
        ("rejected_invalid_prices", "invalid prices"),
    ]:
        try:
            v = int(diag.get(key, 0) or 0)
        except Exception:
            v = 0
        if v > 0:
            any_rej = True
            lines.append(f"- {label}: {v}")
    if not any_rej:
        lines.append("- (no rejection data)")
    lines.append("")

    # Stops + Size
    stop_avg = r.get("stop_avg")
    stop_med = r.get("stop_median")
    stop_bins = r.get("stop_bins") or {}
    if stop_avg is not None and stop_med is not None:
        lines.append(f"Stops (pts): avg {float(stop_avg):.1f} | med {float(stop_med):.1f}")
    else:
        lines.append("Stops (pts):")
    lines.append("  " + " | ".join([f"{k}:{int(stop_bins.get(k, 0) or 0)}" for k in ["<5","5-10","10-15","15-20","20-25",">25"]]))

    size_avg = r.get("size_avg")
    size_med = r.get("size_median")
    size_bins = r.get("size_bins") or {}
    if size_avg is not None and size_med is not None:
        lines.append(f"Size (cts): avg {float(size_avg):.1f} | med {float(size_med):.1f}")
    else:
        lines.append("Size (cts):")
    lines.append("  " + " | ".join([f"{k}:{int(size_bins.get(k, 0) or 0)}" for k in ["1","2-3","4-5","6-8","9-12","13-15",">15"]]))
    lines.append("")

    # Quiet reasons
    quiet = r.get("quiet_reasons_top") or {}
    if quiet:
        lines.append("Quiet reasons (top):")
        for k, v in quiet.items():
            lines.append(f"- {k}: {int(v)}")

    return "\n".join(lines).strip() + "\n"
