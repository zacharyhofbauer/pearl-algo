"""
Tradovate data helpers for the Pearl API server.

Functions for loading, normalising, and transforming Tradovate fill and
position data.  Used by both the REST endpoints and the WebSocket broadcast
loop for Tradovate Paper accounts.

Extracted from server.py for testability and DRY.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pearlalgo.execution.tradovate.utils import (
    tradovate_fills_to_trades as _raw_fills_to_trades,
)

from pearlalgo.api.data_layer import (
    cached,
    read_state_for_dir,
    get_start_balance,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fill normalisation
# ---------------------------------------------------------------------------


def normalize_fill(f: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Tradovate fill to consistent snake_case keys.

    Older fills may use camelCase (contractId, orderId) from the raw
    Tradovate API, while newer fills from the adapter use snake_case.
    """
    return {
        "id": f.get("id"),
        "order_id": f.get("order_id") or f.get("orderId"),
        "contract_id": f.get("contract_id") or f.get("contractId"),
        "timestamp": f.get("timestamp"),
        "action": f.get("action"),
        "qty": f.get("qty", 0),
        "price": f.get("price", 0.0),
        "net_pos": f.get("net_pos") if f.get("net_pos") is not None else f.get("netPos"),
    }


# ---------------------------------------------------------------------------
# State loading
# ---------------------------------------------------------------------------


def get_tradovate_state(state_dir: Path) -> tuple:
    """Load tradovate_account and tradovate_fills.

    Fills are read from state.json first, then from the persistent
    tradovate_fills.json file (which survives session resets since
    Tradovate's /fill/list clears at end of day).

    All fills are normalized to snake_case keys for consistency.

    Returns ``(tradovate_account_dict, fills_list)``.
    """
    tv: Dict[str, Any] = {}
    fills: List[Dict[str, Any]] = []
    try:
        data = read_state_for_dir(state_dir)
        if data:
            tv = data.get("tradovate_account") or {}
            fills = data.get("tradovate_fills") or []
    except Exception as e:
        logger.warning(f"Non-critical: {e}")

    # Fallback: read from persistent fills file when state.json has none
    if not fills:
        try:
            fills_file = state_dir / "tradovate_fills.json"
            if fills_file.exists():
                fills = json.loads(fills_file.read_text()) or []
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

    fills = [normalize_fill(f) for f in fills]
    return tv, fills


# ---------------------------------------------------------------------------
# Cached paired trades (replaces 12+ raw calls)
# ---------------------------------------------------------------------------


def _parse_signal_timestamp(row: Dict[str, Any], signal: Dict[str, Any]) -> Optional[datetime]:
    """Return a comparable naive ET datetime for a signal row."""
    from pearlalgo.utils.paths import parse_trade_timestamp

    for candidate in (
        row.get("entry_time"),
        row.get("timestamp"),
        signal.get("entry_time"),
        signal.get("timestamp"),
    ):
        if not candidate:
            continue
        try:
            return parse_trade_timestamp(str(candidate))
        except (TypeError, ValueError):
            continue
    return None


def _load_pearl_execution_order_ids(state_dir: Path) -> Set[str]:
    """Load PEARL-owned Tradovate order IDs persisted in ``signals.jsonl``."""
    signals_file = state_dir / "signals.jsonl"
    if not signals_file.exists():
        return set()

    order_ids: Set[str] = set()
    keys = (
        "_execution_order_id",
        "_execution_stop_order_id",
        "_execution_take_profit_order_id",
    )

    try:
        with signals_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line.strip())
                except (json.JSONDecodeError, ValueError):
                    continue
                sources = [row]
                signal = row.get("signal")
                if isinstance(signal, dict):
                    sources.append(signal)
                for source in sources:
                    for key in keys:
                        value = source.get(key)
                        if value not in (None, ""):
                            order_ids.add(str(value))
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    return order_ids


def _load_signal_trade_candidates(state_dir: Path) -> List[Dict[str, Any]]:
    """Load signal rows suitable for heuristic PEARL trade attribution."""
    signals_file = state_dir / "signals.jsonl"
    if not signals_file.exists():
        return []

    candidates: List[Dict[str, Any]] = []
    try:
        with signals_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line.strip())
                except (json.JSONDecodeError, ValueError):
                    continue

                signal = row.get("signal")
                if not isinstance(signal, dict):
                    continue

                direction = str(signal.get("direction") or "").lower()
                if direction not in ("long", "short"):
                    continue

                try:
                    entry_price = float(signal.get("entry_price"))
                    position_size = int(signal.get("position_size") or 1)
                except (TypeError, ValueError):
                    continue

                signal_time = _parse_signal_timestamp(row, signal)
                if signal_time is None:
                    continue

                candidates.append({
                    "signal_id": str(row.get("signal_id") or ""),
                    "direction": direction,
                    "entry_price": entry_price,
                    "position_size": position_size,
                    "timestamp": signal_time,
                })
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    return candidates


def _attribute_trades_to_pearl_signals(
    trades: List[Dict[str, Any]],
    signal_candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Match paired trades back to PEARL signals when explicit order IDs are absent."""
    if not trades or not signal_candidates:
        return []

    from pearlalgo.utils.paths import parse_trade_timestamp

    attributed: List[Dict[str, Any]] = []
    remaining = list(signal_candidates)

    for trade in trades:
        try:
            trade_time = parse_trade_timestamp(str(trade.get("entry_time") or ""))
            trade_price = float(trade.get("entry_price") or 0.0)
            trade_size = int(trade.get("position_size") or 0)
        except (TypeError, ValueError):
            continue

        direction = str(trade.get("direction") or "").lower()
        eligible = []
        for idx, candidate in enumerate(remaining):
            if candidate["direction"] != direction:
                continue
            if candidate["position_size"] != trade_size:
                continue
            price_delta = abs(candidate["entry_price"] - trade_price)
            if price_delta > 2.0:
                continue
            time_delta = abs((candidate["timestamp"] - trade_time).total_seconds())
            if time_delta > 180:
                continue
            eligible.append((time_delta, price_delta, idx))

        if not eligible:
            continue

        _, _, best_idx = min(eligible)
        attributed.append(trade)
        remaining.pop(best_idx)

    return attributed


def get_paired_tradovate_trades(
    state_dir: Path,
    fills: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Load fills and pair them into trades with a short TTL cache.

    This is the single call site for ``tradovate_fills_to_trades`` in the
    API layer.  All endpoint/broadcast code should use this instead of
    calling the raw pairing function directly.
    """
    def _pair() -> List[Dict[str, Any]]:
        active_fills = fills
        if active_fills is None:
            _, active_fills = get_tradovate_state(state_dir)
        else:
            active_fills = [normalize_fill(f) for f in active_fills]

        active_fills = [
            fill
            for fill in active_fills
            if str(fill.get("action") or "").lower() in ("buy", "sell")
            and fill.get("timestamp")
            and float(fill.get("price", 0.0) or 0.0) > 0
            and int(fill.get("qty", 0) or 0) > 0
        ]

        owned_order_ids = _load_pearl_execution_order_ids(state_dir)
        if owned_order_ids:
            active_fills = [
                fill for fill in active_fills
                if str(fill.get("order_id") or "") in owned_order_ids
            ]
            return _raw_fills_to_trades(active_fills)

        paired = _raw_fills_to_trades(active_fills)
        signal_candidates = _load_signal_trade_candidates(state_dir)
        if signal_candidates:
            return _attribute_trades_to_pearl_signals(paired, signal_candidates)
        return paired

    # TTL of 10s is safe — fills arrive at most every 30s (cooldown_seconds).
    return cached(f"tv_paired_trades:{state_dir}", 10.0, _pair)


def estimate_commission_per_trade(
    trades: List[Dict[str, Any]],
    *,
    equity: float,
    start_balance: float,
) -> float:
    """Estimate round-turn commission from fill P&L vs live equity delta."""
    if equity <= 0 or not trades:
        return 0.0

    total_fill_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
    equity_pnl = equity - start_balance
    if total_fill_pnl <= equity_pnl:
        return 0.0
    return (total_fill_pnl - equity_pnl) / len(trades)


def summarize_paired_trades_for_period(
    trades: List[Dict[str, Any]],
    start_utc: datetime,
    end_utc: Optional[datetime] = None,
    commission_per_trade: float = 0.0,
) -> Dict[str, Any]:
    """Build period stats from an already-paired Tradovate trade list."""
    filtered = []
    for t in trades:
        exit_ts = t.get("exit_time", "")
        if not exit_ts:
            continue
        try:
            from pearlalgo.utils.paths import parse_trade_timestamp
            exit_dt = parse_trade_timestamp(exit_ts)  # FIXED 2026-03-25: ET timestamps
        except (ValueError, TypeError):
            continue
        if exit_dt < start_utc:
            continue
        if end_utc and exit_dt >= end_utc:
            continue
        filtered.append(t)

    total = len(filtered)
    wins = sum(1 for t in filtered if (t.get("pnl") or 0) > 0)
    losses = total - wins
    raw_pnl = sum(t.get("pnl") or 0 for t in filtered)
    pnl = round(raw_pnl - (total * commission_per_trade), 2)
    win_rate = round(wins / total * 100, 1) if total > 0 else 0.0

    return {
        "pnl": pnl,
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
    }


# ---------------------------------------------------------------------------
# Position helpers
# ---------------------------------------------------------------------------


def tradovate_positions_for_api(tv: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert tradovate_account positions to the format ``/api/positions`` expects.

    When individual position openPnL is 0 but account-level open_pnl is
    non-zero (common with Tradovate REST), distribute the account open_pnl
    across positions proportionally by contract count.
    """
    raw_positions = [p for p in tv.get("positions", []) if p.get("net_pos", 0) != 0]
    if not raw_positions:
        return []

    account_open_pnl = float(tv.get("open_pnl", 0))
    sum_pos_pnl = sum(float(p.get("open_pnl", 0)) for p in raw_positions)
    total_contracts = sum(abs(p.get("net_pos", 0)) for p in raw_positions)

    use_account_pnl = sum_pos_pnl == 0 and account_open_pnl != 0 and total_contracts > 0

    positions = []
    for pos in raw_positions:
        net_pos = pos.get("net_pos", 0)
        direction = "long" if net_pos > 0 else "short"
        if use_account_pnl:
            pos_pnl = round(account_open_pnl * abs(net_pos) / total_contracts, 2)
        else:
            pos_pnl = pos.get("open_pnl", 0)
        positions.append({
            "signal_id": f"tv_pos_{pos.get('contract_id', '')}",
            "symbol": "MNQ",
            "direction": direction,
            "position_size": abs(net_pos),
            "entry_price": pos.get("net_price", 0),
            "entry_time": None,
            "stop_loss": None,
            "take_profit": None,
            "open_pnl": pos_pnl,
        })
    return positions


def enrich_positions_with_signal_brackets(
    positions: List[Dict[str, Any]],
    signals: List[Dict[str, Any]],
) -> None:
    """
    Mutate Tradovate positions in-place with SL/TP from active signal records.

    signals.jsonl is append-only and "entered" rows often do not include the
    nested ``signal`` payload. To reliably recover SL/TP, this function:
    1) keeps only the latest record per signal_id,
    2) backfills missing ``signal`` from the latest "generated" record, then
    3) matches active signals to positions by direction + closest entry price.
    """
    if not positions or not signals:
        return

    signal_data_by_id: Dict[str, Dict[str, Any]] = {}
    latest_by_id: Dict[str, Dict[str, Any]] = {}
    for rec in signals:
        if not isinstance(rec, dict):
            continue
        sid = str(rec.get("signal_id") or "")
        if not sid:
            continue
        if rec.get("status") == "generated" and isinstance(rec.get("signal"), dict):
            signal_data_by_id[sid] = rec["signal"]
        latest_by_id[sid] = rec

    active_signals: List[Dict[str, Any]] = []
    for sid, rec in latest_by_id.items():
        if rec.get("status") != "entered":
            continue
        sig = rec.get("signal")
        if not isinstance(sig, dict):
            sig = signal_data_by_id.get(sid)
        if not isinstance(sig, dict):
            continue
        if sig.get("stop_loss") is None and sig.get("take_profit") is None:
            continue
        active_signals.append({**rec, "signal": sig})

    if not active_signals:
        return

    for pos in positions:
        direction = str(pos.get("direction") or "").lower()
        if not direction:
            continue
        matching = [
            s for s in active_signals
            if str(s.get("signal", {}).get("direction") or "").lower() == direction
        ]
        if not matching:
            continue
        best = min(
            matching,
            key=lambda s: abs(float(s.get("entry_price", 0) or 0) - float(pos.get("entry_price", 0) or 0)),
        )
        sig = best.get("signal", {})
        if sig.get("stop_loss") is not None:
            pos["stop_loss"] = sig.get("stop_loss")
        if sig.get("take_profit") is not None:
            pos["take_profit"] = sig.get("take_profit")


# ---------------------------------------------------------------------------
# Performance helpers
# ---------------------------------------------------------------------------


def tradovate_performance_summary(
    tv: Dict[str, Any],
    fills: List[Dict[str, Any]],
    state_dir: Path,
    *,
    paired_trades: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build overall performance summary from Tradovate data.

    When live equity is available (adapter connected), P&L is equity-based.
    When offline (equity=0), P&L is computed from raw fills and equity is
    estimated as start_balance + fill_pnl.
    """
    start_balance = get_start_balance(state_dir)

    trades = paired_trades if paired_trades is not None else _raw_fills_to_trades(fills)
    total = len(trades)
    wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
    losses = total - wins
    win_rate = round(wins / total * 100, 1) if total > 0 else 0.0

    equity = float(tv.get("equity", 0))
    if equity > 0:
        pnl = round(equity - start_balance, 2)
    else:
        fill_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
        pnl = round(fill_pnl, 2)
        equity = round(start_balance + fill_pnl, 2)

    return {
        "pnl": pnl,
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "tradovate_equity": round(equity, 2),
    }


def tradovate_performance_for_period(
    fills: List[Dict[str, Any]],
    start_utc: datetime,
    end_utc: Optional[datetime] = None,
    commission_per_trade: float = 0.0,
    *,
    paired_trades: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build performance stats from Tradovate fills filtered to a time range.

    Filters completed trades whose exit_time falls within ``[start_utc, end_utc)``.
    ``commission_per_trade``: estimated round-turn commission to deduct per trade
    (derived from equity vs fill P&L gap).
    """
    trades = paired_trades if paired_trades is not None else _raw_fills_to_trades(fills)
    return summarize_paired_trades_for_period(
        trades,
        start_utc,
        end_utc=end_utc,
        commission_per_trade=commission_per_trade,
    )
