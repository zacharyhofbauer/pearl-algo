#!/usr/bin/env python3
"""
Counterfactual replay: take historical trades from trades.db and project
what NEW SL/TP/confidence settings would have produced, using the actual
MFE (max favorable excursion) and MAE (max adverse excursion) recorded
for each trade.

Method:
- For each historical trade, compute the SL and TP distances that were
  used (from entry/sl/tp prices).
- Compute the NEW SL and TP distances by scaling: new = old * (new_mult / old_mult).
- Use MFE/MAE points to decide which the new bracket would have hit first:
    * If MAE >= new_sl_dist: new bracket would have stopped out (LOSER, bigger loss)
    * Elif MFE >= new_tp_dist: new bracket would have taken profit (WINNER, bigger gain)
    * Else: trade wouldn't have hit either — outcome unknown, project the
      actual exit price (a conservative estimate).
- Filter signals below the new min_confidence threshold (drop them — they wouldn't
  have been taken).

This is APPROXIMATE because:
- It assumes the wider stop/target is hit at the same MFE/MAE pricing the original
  trade saw. In reality, a wider SL might let the trade continue beyond MAE (and
  then hit a NEW low later). MFE/MAE only capture the recorded extremes during
  the original hold window.
- It doesn't simulate position sizing changes.
- It uses the actual hold window — wouldn't model time-based exits differently.

Run:
    python scripts/backtesting/counterfactual.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DB = Path("/home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ/trades.db")
SIGNALS = Path("/home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ/signals.jsonl")

POINT_VALUE_MNQ = 2.0  # $/point/contract

# OLD config (yesterday)
OLD_SL_MULT = 1.5
OLD_TP_MULT = 2.5
OLD_MIN_CONF = 0.40

# NEW config (current YAML, post-audit)
NEW_SL_MULT = 2.5
NEW_TP_MULT = 4.0
NEW_MIN_CONF = 0.55


def load_trades_with_features() -> List[Dict[str, Any]]:
    """Load trades joined with their generated signal payload (for confidence)."""
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT trade_id, signal_id, signal_type, direction, entry_price, exit_price,
               stop_loss, take_profit, pnl, is_win, exit_reason,
               hold_duration_minutes, mfe_points, mae_points, entry_time
        FROM trades
        WHERE entry_price > 1000  -- exclude any leftover stub trades
          AND entry_time >= '2026-03-30'
        ORDER BY entry_time
        """
    ).fetchall()

    # Pull confidence from the matching 'generated' signal_event
    trades: List[Dict[str, Any]] = []
    for r in rows:
        trade = {
            "trade_id": r[0],
            "signal_id": r[1],
            "signal_type": r[2],
            "direction": r[3],
            "entry_price": float(r[4]) if r[4] else 0,
            "exit_price": float(r[5]) if r[5] else 0,
            "stop_loss": float(r[6]) if r[6] else None,
            "take_profit": float(r[7]) if r[7] else None,
            "pnl": float(r[8]) if r[8] is not None else 0,
            "is_win": bool(r[9]),
            "exit_reason": r[10] or "",
            "hold_min": float(r[11]) if r[11] is not None else None,
            "mfe_pts": float(r[12]) if r[12] is not None else None,
            "mae_pts": float(r[13]) if r[13] is not None else None,
            "entry_time": r[14],
            "confidence": None,
        }
        # Look up confidence from signal_event 'generated' record
        ev = cur.execute(
            "SELECT payload_json FROM signal_events "
            "WHERE signal_id = ? AND status = 'generated' LIMIT 1",
            (trade["signal_id"],),
        ).fetchone()
        if ev and ev[0]:
            try:
                p = json.loads(ev[0])
                sig = p.get("signal", {}) if isinstance(p, dict) else {}
                if isinstance(sig, dict):
                    trade["confidence"] = sig.get("confidence")
            except Exception:
                pass
        trades.append(trade)
    con.close()
    return trades


def project_new_outcome(trade: Dict[str, Any]) -> Dict[str, Any]:
    """Project what the NEW tuning would have produced for this trade."""
    entry = trade["entry_price"]
    direction = trade["direction"]
    old_sl = trade["stop_loss"]
    old_tp = trade["take_profit"]
    mfe = trade["mfe_pts"]
    mae = trade["mae_pts"]

    if entry <= 0 or old_sl is None or old_tp is None:
        return {"status": "skipped", "reason": "missing_prices"}

    # Distances in points
    if direction == "long":
        old_sl_dist = entry - old_sl
        old_tp_dist = old_tp - entry
    else:
        old_sl_dist = old_sl - entry
        old_tp_dist = entry - old_tp

    if old_sl_dist <= 0 or old_tp_dist <= 0:
        return {"status": "skipped", "reason": "bad_distances"}

    # New distances scaled by multiplier ratio
    new_sl_dist = old_sl_dist * (NEW_SL_MULT / OLD_SL_MULT)
    new_tp_dist = old_tp_dist * (NEW_TP_MULT / OLD_TP_MULT)

    # Decide the new outcome using MFE/MAE
    if mfe is None or mae is None:
        # No excursion data — fall back to actual outcome scaled by distance ratio
        scale = (NEW_TP_MULT / OLD_TP_MULT) if trade["is_win"] else (NEW_SL_MULT / OLD_SL_MULT)
        new_pnl = trade["pnl"] * scale
        return {
            "status": "no_excursion",
            "new_sl_dist": new_sl_dist,
            "new_tp_dist": new_tp_dist,
            "new_pnl": new_pnl,
            "new_is_win": new_pnl > 0,
            "fallback": "scale_by_ratio",
        }

    # MFE >= new_tp_dist? Trade would have hit the new TP.
    # MAE >= new_sl_dist? Trade would have stopped at new SL.
    # If both, whichever happened first (we don't know — use the original outcome).
    hit_new_tp = mfe >= new_tp_dist
    hit_new_sl = mae >= new_sl_dist

    if hit_new_tp and not hit_new_sl:
        new_pnl = new_tp_dist * POINT_VALUE_MNQ
        outcome = "tp_widened_hit"
    elif hit_new_sl and not hit_new_tp:
        new_pnl = -new_sl_dist * POINT_VALUE_MNQ
        outcome = "sl_widened_hit"
    elif hit_new_tp and hit_new_sl:
        # Both touched — use the original outcome to decide which happened first
        if trade["is_win"]:
            new_pnl = new_tp_dist * POINT_VALUE_MNQ
            outcome = "both_hit_was_win"
        else:
            new_pnl = -new_sl_dist * POINT_VALUE_MNQ
            outcome = "both_hit_was_loss"
    else:
        # Neither hit — trade ran to time-based exit at the actual exit price
        # The relative price change is whatever happened, scaled by the new bracket
        # (no scaling — actual exit was inside both brackets so it's unchanged)
        new_pnl = trade["pnl"]
        outcome = "neither_hit"

    return {
        "status": "ok",
        "new_sl_dist": new_sl_dist,
        "new_tp_dist": new_tp_dist,
        "new_pnl": new_pnl,
        "new_is_win": new_pnl > 0,
        "outcome": outcome,
        "mfe": mfe,
        "mae": mae,
    }


def summarize(label: str, trades: List[Dict[str, Any]], pnl_key: str, win_key: str) -> Dict[str, Any]:
    n = len(trades)
    wins = sum(1 for t in trades if t.get(win_key))
    losses = n - wins
    pnl = sum(t.get(pnl_key, 0) or 0 for t in trades)
    win_pnls = [t.get(pnl_key, 0) for t in trades if t.get(win_key)]
    loss_pnls = [t.get(pnl_key, 0) for t in trades if not t.get(win_key)]
    avg_w = sum(win_pnls) / len(win_pnls) if win_pnls else 0
    avg_l = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
    wr = wins / n * 100 if n else 0
    return {
        "label": label,
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_rate": wr,
        "net_pnl": pnl,
        "avg_winner": avg_w,
        "avg_loser": avg_l,
    }


def main() -> None:
    print("=" * 70)
    print("COUNTERFACTUAL: NEW vs OLD config on actual historical trades")
    print("=" * 70)
    print()

    trades = load_trades_with_features()
    print(f"Loaded {len(trades)} historical trades from current trades.db")
    print(f"  with confidence:    {sum(1 for t in trades if t['confidence'] is not None)}")
    print(f"  with MFE/MAE:       {sum(1 for t in trades if t['mfe_pts'] is not None and t['mae_pts'] is not None)}")
    print()

    # Project new outcomes
    for t in trades:
        t["projection"] = project_new_outcome(t)

    # Filter: NEW config would have dropped signals below NEW_MIN_CONF
    accepted_new = []
    rejected_by_conf = 0
    for t in trades:
        c = t.get("confidence")
        if c is None:
            # No confidence data — keep it (can't filter)
            accepted_new.append(t)
            continue
        if float(c) >= NEW_MIN_CONF:
            accepted_new.append(t)
        else:
            rejected_by_conf += 1

    print(f"NEW config min_confidence={NEW_MIN_CONF} would have rejected: {rejected_by_conf}/{len(trades)}")
    print()

    # Summarize OLD (actual) performance using all trades
    old_summary = summarize("OLD (actual)", trades, "pnl", "is_win")

    # Summarize NEW (projected) performance using accepted trades only
    new_trades_with_proj = []
    skipped = 0
    for t in accepted_new:
        proj = t["projection"]
        if proj.get("status") == "skipped":
            skipped += 1
            continue
        new_trades_with_proj.append({
            "new_pnl": proj.get("new_pnl", 0),
            "new_is_win": proj.get("new_is_win", False),
            "outcome": proj.get("outcome") or proj.get("status"),
        })
    new_summary = summarize("NEW (projected)", new_trades_with_proj, "new_pnl", "new_is_win")

    print(f"  skipped (bad data): {skipped}")
    print()

    def fmt_row(label: str, s: Dict[str, Any]) -> str:
        return (
            f"{label:25}  n={s['n']:>4}  W={s['wins']:>3}  L={s['losses']:>3}  "
            f"WR={s['win_rate']:>5.1f}%  net=${s['net_pnl']:>+9.2f}  "
            f"avgW=${s['avg_winner']:>+7.2f}  avgL=${s['avg_loser']:>+7.2f}"
        )

    print(fmt_row("OLD (actual results)", old_summary))
    print(fmt_row("NEW (projected)", new_summary))
    print()
    delta_pnl = new_summary["net_pnl"] - old_summary["net_pnl"]
    print(f"Δ net P&L:  {delta_pnl:+.2f}")
    if old_summary["n"] > 0:
        days = 11  # Mar 30 - Apr 10
        print(f"OLD daily avg: ${old_summary['net_pnl']/days:+.2f}")
        print(f"NEW daily avg: ${new_summary['net_pnl']/days:+.2f}")

    # Outcome distribution for the projection
    print("\nProjection outcome distribution (NEW config):")
    outcome_count: Dict[str, int] = {}
    for t in accepted_new:
        proj = t["projection"]
        oc = proj.get("outcome") or proj.get("status")
        outcome_count[oc] = outcome_count.get(oc, 0) + 1
    for k, v in sorted(outcome_count.items(), key=lambda x: -x[1]):
        print(f"  {k:25}  {v:>4}")


if __name__ == "__main__":
    main()
