"""Unit tests for the candle archive (Phase 1)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from pearlalgo.persistence import candle_archive as ca


@pytest.fixture
def tmp_db(monkeypatch):
    """Isolate each test to its own candles.db."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "candles.db"
        monkeypatch.setenv("PEARL_CANDLES_DB", str(path))
        ca.reset_for_tests()
        yield path
        ca.reset_for_tests()


def _sample_bar(ts: int, close: float = 100.0) -> dict:
    return {"time": ts, "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": 10}


def test_schema_created_on_first_use(tmp_db):
    arc = ca.get_archive()
    assert arc.count() == 0
    assert arc._db_path == tmp_db  # noqa: SLF001


def test_append_and_query_roundtrip(tmp_db):
    arc = ca.get_archive()
    bars = [_sample_bar(1000 + i, close=100.0 + i) for i in range(5)]
    n = arc.append_bars(symbol="MNQ", tf="5m", bars=bars)
    assert n == 5
    out = arc.query_range(symbol="MNQ", tf="5m", limit=100)
    assert len(out) == 5
    assert out[0]["time"] == 1000
    assert out[-1]["time"] == 1004
    assert out[2]["close"] == 102.0


def test_insert_or_replace_dedupes_on_pk(tmp_db):
    arc = ca.get_archive()
    arc.append_bars(symbol="MNQ", tf="5m", bars=[_sample_bar(2000, close=100.0)])
    # Re-insert with updated close — should replace, not duplicate.
    arc.append_bars(symbol="MNQ", tf="5m", bars=[_sample_bar(2000, close=200.0)])
    rows = arc.query_range(symbol="MNQ", tf="5m")
    assert len(rows) == 1
    assert rows[0]["close"] == 200.0


def test_tf_validation_rejects_unknown(tmp_db):
    arc = ca.get_archive()
    with pytest.raises(ValueError):
        arc.append_bars(symbol="MNQ", tf="7s", bars=[_sample_bar(1)])


def test_bad_bars_silently_skipped(tmp_db):
    arc = ca.get_archive()
    good = _sample_bar(3000)
    n = arc.append_bars(
        symbol="MNQ",
        tf="1m",
        bars=[
            good,
            {"time": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},  # ts<=0
            {"time": 3001, "open": "not-a-number", "high": 1, "low": 1, "close": 1, "volume": 1},
            {"time": 3002, "open": -1, "high": -1, "low": -1, "close": -1, "volume": 1},  # negative prices
        ],
    )
    assert n == 1
    assert arc.count(symbol="MNQ", tf="1m") == 1


def test_range_bounds(tmp_db):
    arc = ca.get_archive()
    bars = [_sample_bar(t) for t in (100, 200, 300, 400, 500)]
    arc.append_bars(symbol="MNQ", tf="5m", bars=bars)
    inclusive = arc.query_range(symbol="MNQ", tf="5m", ts_from=200, ts_to=400)
    assert [r["time"] for r in inclusive] == [200, 300, 400]
    open_right = arc.query_range(symbol="MNQ", tf="5m", ts_from=300)
    assert [r["time"] for r in open_right] == [300, 400, 500]


def test_multi_symbol_isolation(tmp_db):
    arc = ca.get_archive()
    arc.append_bars(symbol="MNQ", tf="5m", bars=[_sample_bar(1)])
    arc.append_bars(symbol="NQ", tf="5m", bars=[_sample_bar(1)])
    assert arc.count() == 2
    assert arc.count(symbol="MNQ") == 1
    assert arc.count(symbol="NQ") == 1


def test_coverage_summary(tmp_db):
    arc = ca.get_archive()
    arc.append_bars(symbol="MNQ", tf="1m", bars=[_sample_bar(100), _sample_bar(200)])
    arc.append_bars(symbol="MNQ", tf="5m", bars=[_sample_bar(100)])
    cov = {(r["symbol"], r["tf"]): r for r in arc.coverage()}
    assert cov[("MNQ", "1m")]["n"] == 2
    assert cov[("MNQ", "1m")]["min_ts"] == 100
    assert cov[("MNQ", "1m")]["max_ts"] == 200
    assert cov[("MNQ", "5m")]["n"] == 1
