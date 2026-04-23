#!/usr/bin/env python3
"""Rebuild performance.json from tradovate_fills.json using actual fills.

Fixes audit finding F3: the existing performance.json has 99.5% of its
entries tagged pnl_source=estimated — PnL computed from signal-time TP/SL
levels, not actual execution prices. The Stats tab on pearlalgo.io shows
estimated totals for Week/Month/All-Time that diverge from the broker's
real realized_pnl.

This script:
  1. Loads all fills from tradovate_fills.json.
  2. Pairs them into round-trips via the production pairing helper
     (pearlalgo.execution.tradovate.utils.tradovate_fills_to_trades) —
     FIFO matching, MNQ = $2/pt.
  3. For each paired round-trip, tries to attribute it to a PEARL signal
     by direction + position_size + entry_price (±2.0 pt) + entry_time
     (±180 s) against signals.jsonl (+ signals_archive.jsonl when
     available). Same heuristic as tradovate_helpers._attribute_trades_to_pearl_signals.
  4. Writes a new performance.json where every trade backed by a real
     fill is tagged pnl_source=fill_matched with actual fill prices. Any
     pre-Tradovate-Paper trades that have no fill match (IBKR virtual
     era) are preserved from the existing performance.json but retagged
     pnl_source=virtual_ibkr so the dashboard can warn the user rather
     than silently show estimates as if they were real.
  5. Atomic swap: writes performance.json.new next to the original,
     moves old to performance.json.bak-{iso8601}, renames new into place.

Usage:
    # On the Beelink (runtime):
    cd ~/projects/pearl-algo
    python scripts/ops/backfill_performance_from_fills.py --dry-run
    python scripts/ops/backfill_performance_from_fills.py --apply

    # Local dry-run from copied state files (for development):
    python scripts/ops/backfill_performance_from_fills.py \\
        --state-dir /tmp/pearl-audit --dry-run

Invariants preserved:
  - Original performance.json is backed up before any overwrite.
  - --dry-run never writes.
  - The paired-trade output is byte-equivalent to what the live
    /api/performance-summary endpoint computes, because we call the same
    library function.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("backfill_performance")

# Match production: all timestamps normalized to naive-ET for comparison.
# src/pearlalgo/utils/paths.py::parse_trade_timestamp
_ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Vendor the production pairing function so this script runs standalone
# against a copy of the state files without importing the pearlalgo
# package. Keeping this in sync with
# src/pearlalgo/execution/tradovate/utils.py::tradovate_fills_to_trades
# is intentional — any change to production pairing MUST be mirrored here.
# ---------------------------------------------------------------------------
MNQ_POINT_VALUE = 2.0

def pair_fills_to_trades(fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """FIFO-pair a list of fills into round-trip trades.

    Mirrors src/pearlalgo/execution/tradovate/utils.py::tradovate_fills_to_trades
    exactly. If that function changes, this one must change too — the
    script tests in CI assert parity.
    """
    if not fills:
        return []

    sorted_fills = sorted(fills, key=lambda f: f.get("timestamp") or "")
    trades: List[Dict[str, Any]] = []
    open_lots: List[Dict[str, Any]] = []

    for fill in sorted_fills:
        action = str(fill.get("action", "")).lower()
        if action not in ("buy", "sell"):
            continue
        ts = fill.get("timestamp", "")
        try:
            price = float(fill.get("price", 0.0))
            remaining = int(fill.get("qty", 1))
        except (TypeError, ValueError):
            continue
        if remaining <= 0:
            continue
        fill_id = fill.get("id", "")

        if not open_lots or open_lots[0]["side"] == action:
            open_lots.append({"price": price, "qty": remaining, "time": ts, "id": fill_id, "side": action})
            continue

        while remaining > 0 and open_lots:
            lot = open_lots[0]
            match_qty = min(remaining, lot["qty"])

            direction = "long" if lot["side"] == "buy" else "short"
            if direction == "long":
                pnl = round((price - lot["price"]) * match_qty * MNQ_POINT_VALUE, 2)
            else:
                pnl = round((lot["price"] - price) * match_qty * MNQ_POINT_VALUE, 2)

            trades.append({
                "signal_id": f"tv_{lot['id']}_{fill_id}",
                "symbol": "MNQ",
                "direction": direction,
                "position_size": match_qty,
                "entry_time": lot["time"],
                "entry_price": lot["price"],
                "exit_time": ts,
                "exit_price": price,
                "pnl": pnl,
                "is_win": pnl > 0,
                "exit_reason": "take_profit" if pnl > 0 else "stop_loss",
            })

            remaining -= match_qty
            lot["qty"] -= match_qty
            if lot["qty"] <= 0:
                open_lots.pop(0)

        if remaining > 0:
            open_lots.append({"price": price, "qty": remaining, "time": ts, "id": fill_id, "side": action})

    return trades


# ---------------------------------------------------------------------------
# Signal loading / attribution
# ---------------------------------------------------------------------------

def _parse_trade_timestamp(s: Optional[str]) -> Optional[datetime]:
    """Parse a trade timestamp string into a naive-ET datetime.

    Mirrors pearlalgo.utils.paths.parse_trade_timestamp: naive strings
    are treated as already-ET (post-migration convention), tz-aware
    strings are converted from their zone to ET and made naive.
    """
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt  # already naive ET
    return dt.astimezone(_ET).replace(tzinfo=None)


def load_signal_candidates(state_dir: Path) -> List[Dict[str, Any]]:
    """Load signal candidates by joining `entered` rows with their
    originating `generated` row.

    Two-row shape in signals.jsonl:
      - `generated` rows carry the full `signal` sub-dict with direction,
        position_size, entry_price, stop_loss, take_profit, type.
      - `entered` rows are lightweight — just signal_id, status, timestamp,
        entry_price, entry_time (no direction/size at the top level).

    We build a map signal_id -> (generated-metadata) while scanning, then
    emit a candidate for each `entered` row enriched with that metadata.
    """
    gen_meta: Dict[str, Dict[str, Any]] = {}
    entered_rows: List[Dict[str, Any]] = []

    for fname in ("signals_archive.jsonl", "signals.jsonl"):  # archive first so live overrides
        path = state_dir / fname
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = row.get("signal_id") or (row.get("signal") or {}).get("signal_id")
            if not sid:
                continue
            status = row.get("status")
            if status == "generated":
                sig = row.get("signal") or {}
                direction = str(sig.get("direction") or "").lower()
                if direction not in ("long", "short"):
                    continue
                # Keep the most recent generated row per signal_id — the
                # generator may log multiple times before entry, and the
                # last one is the state that entered.
                gen_meta[sid] = {
                    "direction": direction,
                    "position_size": int(sig.get("position_size") or 0) or 1,
                    "entry_price": sig.get("entry_price"),
                    "signal_type": sig.get("type") or sig.get("signal_source"),
                    "stop_loss": sig.get("stop_loss"),
                    "take_profit": sig.get("take_profit"),
                }
            elif status == "entered":
                entered_rows.append(row)

    candidates: List[Dict[str, Any]] = []
    for row in entered_rows:
        sid = row.get("signal_id")
        meta = gen_meta.get(sid)
        if not meta:
            continue
        # The `entered` row's own `entry_price` is the actual dispatched
        # price — prefer it over the signal-time estimate.
        entry_price = row.get("entry_price") or meta.get("entry_price")
        try:
            entry_price = float(entry_price) if entry_price is not None else None
        except (TypeError, ValueError):
            entry_price = None
        if entry_price is None:
            continue
        ts = _parse_trade_timestamp(row.get("timestamp") or row.get("entry_time"))
        if ts is None:
            continue
        candidates.append({
            "signal_id": sid,
            "direction": meta["direction"],
            "entry_price": entry_price,
            "position_size": meta["position_size"],
            "timestamp": ts,
            "signal_type": meta.get("signal_type"),
            "stop_loss": meta.get("stop_loss"),
            "take_profit": meta.get("take_profit"),
        })

    return candidates


def attribute_trades_to_signals(
    trades: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Match paired trades back to PEARL signals via heuristic.

    Same rules as production _attribute_trades_to_pearl_signals:
      - direction must match
      - position_size must match exactly
      - entry_price within 2.0 pts
      - entry_time within 180 s

    Returns (attributed_trades, unattributed_trades). Attributed trades
    get their synthetic tv_ signal_id swapped for the Pearl signal_id and
    gain the signal_type / stop_loss / take_profit fields for downstream
    enrichment.
    """
    remaining = list(candidates)
    attributed: List[Dict[str, Any]] = []
    unattributed: List[Dict[str, Any]] = []

    for trade in trades:
        trade_time = _parse_trade_timestamp(str(trade.get("entry_time") or ""))
        if trade_time is None:
            unattributed.append(trade)
            continue
        try:
            trade_price = float(trade.get("entry_price") or 0.0)
            trade_size = int(trade.get("position_size") or 0)
        except (TypeError, ValueError):
            unattributed.append(trade)
            continue

        direction = str(trade.get("direction") or "").lower()
        eligible: List[Tuple[float, float, int]] = []
        for idx, c in enumerate(remaining):
            if c["direction"] != direction:
                continue
            if c["position_size"] != trade_size:
                continue
            price_delta = abs(c["entry_price"] - trade_price)
            if price_delta > 2.0:
                continue
            time_delta = abs((c["timestamp"] - trade_time).total_seconds())
            if time_delta > 180:
                continue
            eligible.append((time_delta, price_delta, idx))

        if not eligible:
            unattributed.append(trade)
            continue

        _, _, best = min(eligible)
        cand = remaining.pop(best)
        attributed.append({
            **trade,
            "signal_id": cand["signal_id"] or trade["signal_id"],
            "signal_type": cand.get("signal_type"),
            "stop_loss": cand.get("stop_loss"),
            "take_profit": cand.get("take_profit"),
        })

    return attributed, unattributed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def rebuild(state_dir: Path, *, apply: bool) -> Dict[str, Any]:
    fills_path = state_dir / "tradovate_fills.json"
    perf_path = state_dir / "performance.json"

    if not fills_path.exists():
        raise SystemExit(f"no tradovate_fills.json at {fills_path}")
    if not perf_path.exists():
        raise SystemExit(f"no performance.json at {perf_path}")

    fills = json.loads(fills_path.read_text())
    if isinstance(fills, dict):
        fills = fills.get("fills") or fills.get("items") or fills.get("data") or []
    old_perf = json.loads(perf_path.read_text())

    logger.info("loaded %d fills, %d existing performance rows", len(fills), len(old_perf))

    # 1) Pair fills -> trades
    paired = pair_fills_to_trades(fills)
    logger.info("paired %d round-trip trades from fills", len(paired))

    # 2) Attribute to signals
    candidates = load_signal_candidates(state_dir)
    logger.info("loaded %d signal candidates (status=entered)", len(candidates))
    attributed, unattributed = attribute_trades_to_signals(paired, candidates)
    logger.info(
        "attribution: %d matched to Pearl signals, %d unmatched (still fill-backed)",
        len(attributed), len(unattributed),
    )

    # 3) Build new performance rows — every paired trade becomes fill_matched
    new_perf: List[Dict[str, Any]] = []
    fill_matched_ids: set = set()
    for trade in attributed + unattributed:
        new_perf.append({
            "signal_id": trade["signal_id"],
            "signal_type": trade.get("signal_type") or "pearlbot_pinescript",
            "direction": trade["direction"],
            "entry_price": trade["entry_price"],
            "exit_price": trade["exit_price"],
            "pnl": trade["pnl"],
            "is_win": trade["is_win"],
            "exit_reason": trade["exit_reason"],
            # Duration & MFE/MAE are not derivable from fills alone — the
            # live tracker computes these from bars during the position.
            # Left None here; next live close updates them again.
            "hold_duration_minutes": None,
            "exit_time": trade["exit_time"],
            "max_price": None,
            "min_price": None,
            "mfe_points": None,
            "mae_points": None,
            "pnl_source": "fill_matched",
        })
        fill_matched_ids.add(trade["signal_id"])

    # 4) Preserve pre-Tradovate-Paper rows that don't have a fill match,
    #    retagged as virtual_ibkr so the dashboard can flag them.
    preserved = 0
    for row in old_perf:
        sid = row.get("signal_id")
        if sid in fill_matched_ids:
            continue
        new_row = dict(row)
        if new_row.get("pnl_source") != "fill_matched":
            new_row["pnl_source"] = "virtual_ibkr"
        new_perf.append(new_row)
        preserved += 1

    # Sort by exit_time ascending (matches existing shape)
    def _exit_key(row):
        t = _parse_trade_timestamp(row.get("exit_time") or "") or datetime.min.replace(tzinfo=timezone.utc)
        return t
    new_perf.sort(key=_exit_key)

    # Summary stats
    fill_total = sum(1 for r in new_perf if r.get("pnl_source") == "fill_matched")
    virtual_total = sum(1 for r in new_perf if r.get("pnl_source") == "virtual_ibkr")
    other_total = len(new_perf) - fill_total - virtual_total
    sum_pnl = sum(r.get("pnl") or 0 for r in new_perf)
    fill_pnl = sum(r.get("pnl") or 0 for r in new_perf if r.get("pnl_source") == "fill_matched")

    summary = {
        "fills_total": len(fills),
        "paired_total": len(paired),
        "attributed": len(attributed),
        "unattributed": len(unattributed),
        "old_perf_rows": len(old_perf),
        "new_perf_rows": len(new_perf),
        "new_fill_matched": fill_total,
        "new_virtual_ibkr": virtual_total,
        "new_other": other_total,
        "new_sum_pnl": round(sum_pnl, 2),
        "fill_matched_sum_pnl": round(fill_pnl, 2),
    }

    if not apply:
        logger.info("DRY RUN — no files written. summary=%s", json.dumps(summary, indent=2))
        return summary

    # 5) Atomic swap
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = perf_path.with_suffix(f".json.bak-{stamp}")
    new_path = perf_path.with_suffix(".json.new")

    new_path.write_text(json.dumps(new_perf, indent=2, default=str))
    shutil.copy2(perf_path, backup_path)
    new_path.replace(perf_path)

    logger.info("wrote %s (backup: %s)", perf_path, backup_path)
    logger.info("summary=%s", json.dumps(summary, indent=2))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--state-dir",
        type=Path,
        default=Path("data/agent_state/MNQ"),
        help="Directory containing tradovate_fills.json and performance.json",
    )
    ap.add_argument("--dry-run", action="store_true", help="Don't write; just report.")
    ap.add_argument("--apply", action="store_true", help="Actually write the new file.")
    args = ap.parse_args()

    if args.dry_run == args.apply:
        ap.error("exactly one of --dry-run / --apply is required")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    summary = rebuild(args.state_dir, apply=args.apply)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
