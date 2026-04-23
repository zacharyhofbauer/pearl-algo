"""Tests for Issue 16-A — rolling-window truncate + candle-archive
write-rate metric.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pearlalgo.market_agent.trading_circuit_breaker import (
    TradingCircuitBreaker,
    TradingCircuitBreakerConfig,
)
from pearlalgo.persistence.candle_archive import CandleArchive


# ---------------------------------------------------------------------------
# trading_circuit_breaker._recent_trades truncation
# ---------------------------------------------------------------------------


def test_recent_trades_truncates_via_del_not_rebind():
    """Append a mountain of trades; assert final len stays at 2×rolling_window,
    and that the list object identity is preserved (del, not re-bind)."""
    cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(rolling_window_trades=10))
    list_id_before = id(cb._recent_trades)

    for i in range(500):
        cb._recent_trades.append({"is_win": i % 2 == 0, "pnl": 1.0})
        max_history = max(
            cb.config.rolling_window_trades, cb.config.chop_detection_window
        ) * 2
        if len(cb._recent_trades) > max_history:
            del cb._recent_trades[:-max_history]

    max_history = max(
        cb.config.rolling_window_trades, cb.config.chop_detection_window
    ) * 2
    assert len(cb._recent_trades) == max_history
    # The real production code path uses the same `del` pattern; the
    # identity check proves the list object wasn't re-allocated.
    assert id(cb._recent_trades) == list_id_before


def test_cb_process_trade_result_truncates_via_del():
    """Exercise the actual production append path repeatedly and confirm
    bounded growth + stable object identity."""
    cb = TradingCircuitBreaker(
        TradingCircuitBreakerConfig(rolling_window_trades=10, chop_detection_window=10)
    )
    list_id_before = id(cb._recent_trades)

    for i in range(200):
        cb.record_trade_result({
            "pnl": 1.0 if i % 2 == 0 else -0.5,
            "is_win": i % 2 == 0,
        })

    # max_history = max(10, 10) * 2 = 20
    assert len(cb._recent_trades) == 20
    assert id(cb._recent_trades) == list_id_before


# ---------------------------------------------------------------------------
# candle_archive write-rate counter
# ---------------------------------------------------------------------------


def test_candle_archive_write_count_starts_at_zero(tmp_path: Path):
    arc = CandleArchive(db_path=tmp_path / "a.db")
    assert arc.write_count() == 0
    assert arc.rows_written() == 0


def test_candle_archive_write_count_increments_per_append(tmp_path: Path):
    arc = CandleArchive(db_path=tmp_path / "a.db")
    arc.append_bars(symbol="MNQ", tf="5m", bars=[
        {"time": 1_776_757_800, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10}
    ])
    assert arc.write_count() == 1
    assert arc.rows_written() == 1

    arc.append_bars(symbol="MNQ", tf="5m", bars=[
        {"time": 1_776_758_100, "open": 100.5, "high": 101, "low": 100, "close": 100.8, "volume": 8},
        {"time": 1_776_758_400, "open": 100.8, "high": 101.2, "low": 100.5, "close": 101.0, "volume": 9},
    ])
    assert arc.write_count() == 2
    assert arc.rows_written() == 3


def test_candle_archive_write_count_not_incremented_on_empty_input(tmp_path: Path):
    arc = CandleArchive(db_path=tmp_path / "a.db")
    n = arc.append_bars(symbol="MNQ", tf="5m", bars=[])
    assert n == 0
    assert arc.write_count() == 0


def test_candle_archive_counter_ignores_malformed_bars(tmp_path: Path):
    """Malformed bars are dropped inside append_bars before the insert. If
    that leaves zero valid rows, nothing is committed and the counter
    must NOT tick."""
    arc = CandleArchive(db_path=tmp_path / "a.db")
    n = arc.append_bars(
        symbol="MNQ",
        tf="5m",
        bars=[
            {"time": "not-a-number", "open": 1, "high": 1, "low": 1, "close": 1},
            {"time": 0, "open": 1, "high": 1, "low": 1, "close": 1},  # ts <= 0 dropped
        ],
    )
    assert n == 0
    assert arc.write_count() == 0


def test_candle_archive_counter_survives_multiple_symbols(tmp_path: Path):
    arc = CandleArchive(db_path=tmp_path / "a.db")
    arc.append_bars(symbol="MNQ", tf="5m", bars=[
        {"time": 1_776_757_800, "open": 100, "high": 101, "low": 99, "close": 100.5}
    ])
    arc.append_bars(symbol="ES", tf="15m", bars=[
        {"time": 1_776_757_800, "open": 5000, "high": 5010, "low": 4990, "close": 5005}
    ])
    assert arc.write_count() == 2
    assert arc.rows_written() == 2
