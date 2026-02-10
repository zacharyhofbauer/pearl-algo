"""
Shared helpers for extracting common fields from state dicts.

Centralises the defensive-get patterns used across multiple modules
(market_agent/service.py, telegram_command_handler.py, etc.) so every
caller agrees on types and defaults.
"""

from __future__ import annotations


def extract_state_metrics(state: dict) -> dict:
    """Extract common state metrics used across many modules.

    Centralizes: daily_pnl, wins_today, losses_today, active_trades_count
    extraction pattern that appears 15+ times across the codebase.
    """
    return {
        "daily_pnl": float(state.get("daily_pnl", 0) or 0),
        "wins_today": int(state.get("wins_today", 0) or 0),
        "losses_today": int(state.get("losses_today", 0) or 0),
        "active_trades_count": int(state.get("active_trades_count", 0) or 0),
        "active_positions": int(state.get("active_trades_count", 0) or 0),
    }


def get_signal_id(rec: dict) -> str:
    """Extract signal_id from a signal/trade record.

    Replaces: str(rec.get("signal_id") or "").strip()
    which appears 20+ times across 10+ files.
    """
    return str(rec.get("signal_id") or "").strip()
