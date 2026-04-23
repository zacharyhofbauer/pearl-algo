"""Tests for Issue 12-A — IBKR reconnect chaos scenarios.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 2.

Focus: the persistence layer's tolerance for out-of-order + duplicate +
post-reconnect-backfill bar arrivals. This isolates the archive's
correctness from the live executor (which is covered in
``test_ibkr_data_executor_comprehensive.py``).
"""

from __future__ import annotations

from pathlib import Path


from pearlalgo.persistence.candle_archive import CandleArchive


def _bar(ts: int, close: float, source: str = "ibkr_live") -> dict:
    return {
        "time": ts,
        "open": close,
        "high": close + 0.25,
        "low": close - 0.25,
        "close": close,
        "volume": 10,
    }


def test_archive_query_returns_ascending_after_out_of_order_write(tmp_path: Path):
    """A reconnect backfill often delivers bars in a non-monotonic order.
    The archive must still return ascending-by-ts on query_range."""
    arc = CandleArchive(db_path=tmp_path / "a.db")
    # Simulate a reconnect-storm: bars arrive 3, 1, 2, 5, 4
    order = [3, 1, 2, 5, 4]
    for i in order:
        arc.append_bars(symbol="MNQ", tf="5m", bars=[_bar(1_000_000 + i * 300, 100 + i)])

    rows = arc.query_range(symbol="MNQ", tf="5m", limit=10)
    timestamps = [r["time"] for r in rows]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == 5


def test_archive_duplicate_bar_with_different_data_is_replaced(tmp_path: Path):
    """When a reconnect delivers a bar we already have but with corrected
    OHLC, the archive must accept the replacement (source / quality can
    improve). PK on (symbol, tf, ts) + ON CONFLICT UPDATE guarantees this."""
    arc = CandleArchive(db_path=tmp_path / "a.db")
    ts = 1_776_757_800
    # First write: low-quality
    arc.append_bars(symbol="MNQ", tf="5m", source="partial", bars=[_bar(ts, 100.0)])
    # Second write: same ts, different data, higher-quality
    arc.append_bars(symbol="MNQ", tf="5m", source="ibkr_backfill", bars=[_bar(ts, 200.0)])

    rows = arc.query_range(symbol="MNQ", tf="5m", limit=10)
    assert len(rows) == 1
    assert rows[0]["close"] == 200.0


def test_archive_duplicate_with_identical_data_is_idempotent(tmp_path: Path):
    arc = CandleArchive(db_path=tmp_path / "a.db")
    ts = 1_776_757_800
    for _ in range(5):
        arc.append_bars(symbol="MNQ", tf="5m", bars=[_bar(ts, 100.0)])
    rows = arc.query_range(symbol="MNQ", tf="5m", limit=10)
    assert len(rows) == 1


def test_archive_handles_interleaved_symbols_and_tfs(tmp_path: Path):
    """Reconnect backfill can interleave multiple (symbol, tf) streams
    inside a single burst. Each stream must remain independent."""
    arc = CandleArchive(db_path=tmp_path / "a.db")
    interleaved = [
        ("MNQ", "1m", 1000),
        ("ES", "5m", 1050),
        ("MNQ", "5m", 1100),
        ("MNQ", "1m", 1060),
        ("ES", "5m", 1150),
        ("MNQ", "5m", 1200),
    ]
    for symbol, tf, ts in interleaved:
        arc.append_bars(symbol=symbol, tf=tf, bars=[_bar(ts, 100.0)])

    mnq_1m = arc.query_range(symbol="MNQ", tf="1m")
    mnq_5m = arc.query_range(symbol="MNQ", tf="5m")
    es_5m = arc.query_range(symbol="ES", tf="5m")

    assert [r["time"] for r in mnq_1m] == [1000, 1060]
    assert [r["time"] for r in mnq_5m] == [1100, 1200]
    assert [r["time"] for r in es_5m] == [1050, 1150]


def test_archive_partial_batch_with_mix_of_valid_and_corrupt_bars(tmp_path: Path):
    """A reconnect can deliver a batch with a few corrupted rows. The
    valid rows must still persist."""
    arc = CandleArchive(db_path=tmp_path / "a.db")
    batch = [
        _bar(1000, 100.0),
        {"time": "bad", "open": 0, "high": 0, "low": 0, "close": 0},  # corrupt
        _bar(1060, 100.5),
        {"time": 0, "open": 1, "high": 1, "low": 1, "close": 1},  # ts<=0 dropped
        _bar(1120, 101.0),
    ]
    n = arc.append_bars(symbol="MNQ", tf="5m", bars=batch)
    assert n == 3
    rows = arc.query_range(symbol="MNQ", tf="5m")
    assert [r["time"] for r in rows] == [1000, 1060, 1120]


def test_archive_range_filter_clamps_correctly_across_gap(tmp_path: Path):
    """A disconnect causes a gap in bar timestamps. query_range must still
    return only the bars within (ts_from, ts_to)."""
    arc = CandleArchive(db_path=tmp_path / "a.db")
    # Pre-disconnect:  1000, 1060, 1120
    # Gap of 1 hour
    # Post-reconnect: 4720 (1hr later), 4780
    for ts in (1000, 1060, 1120, 4720, 4780):
        arc.append_bars(symbol="MNQ", tf="1m", bars=[_bar(ts, 100.0)])

    around_gap = arc.query_range(
        symbol="MNQ", tf="1m", ts_from=1100, ts_to=4725
    )
    assert [r["time"] for r in around_gap] == [1120, 4720]
