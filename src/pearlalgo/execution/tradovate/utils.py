"""
Tradovate utility functions.

Shared helpers for processing Tradovate fill data.
"""

from __future__ import annotations

from typing import Any, Dict, List


def tradovate_fills_to_trades(fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert raw Tradovate fills into trade records using FIFO matching.

    Maintains a FIFO queue of open lots.  Each closing fill is matched
    against the oldest open lot(s) to produce one trade per fill.

    MNQ point value = $2 per point per contract.

    Args:
        fills: List of Tradovate fill dicts with keys: action, price, qty,
               timestamp, id.

    Returns:
        List of trade dicts with keys: signal_id, symbol, direction,
        position_size, entry_time, entry_price, exit_time, exit_price,
        pnl, exit_reason.
    """
    if not fills:
        return []

    POINT_VALUE = 2.0  # MNQ micro

    sorted_fills = sorted(fills, key=lambda f: f.get("timestamp") or "")

    trades: List[Dict[str, Any]] = []
    # FIFO queue of open lots
    open_lots: List[Dict[str, Any]] = []

    for fill in sorted_fills:
        action = str(fill.get("action", "")).lower()
        if action not in ("buy", "sell"):
            continue
        ts = fill.get("timestamp", "")
        raw_price = fill.get("price", 0.0)
        raw_qty = fill.get("qty", 1)
        try:
            price = float(raw_price)
            remaining = int(raw_qty)
        except (TypeError, ValueError):
            continue
        if remaining <= 0:
            continue
        fill_id = fill.get("id", "")

        # Determine if this fill opens or closes
        if not open_lots or open_lots[0]["side"] == action:
            # Same side as existing lots (or no lots) -> opening fill
            open_lots.append({"price": price, "qty": remaining, "time": ts, "id": fill_id, "side": action})
            continue

        # Opposite side -> closing fill.  Match FIFO against open lots.
        while remaining > 0 and open_lots:
            lot = open_lots[0]
            match_qty = min(remaining, lot["qty"])

            direction = "long" if lot["side"] == "buy" else "short"
            if direction == "long":
                pnl = round((price - lot["price"]) * match_qty * POINT_VALUE, 2)
            else:
                pnl = round((lot["price"] - price) * match_qty * POINT_VALUE, 2)

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

        # If remaining > 0, this fill also opens a new position in the opposite direction
        if remaining > 0:
            open_lots.append({"price": price, "qty": remaining, "time": ts, "id": fill_id, "side": action})

    return trades
