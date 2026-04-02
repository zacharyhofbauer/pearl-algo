from __future__ import annotations

from pathlib import Path

from pearlalgo.learning.trade_database import TradeDatabase


def test_trade_database_creates_runtime_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "trades.db"
    db = TradeDatabase(db_path=db_path)
    db.close()

    import sqlite3

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "trades" in tables
    assert "signal_events" in tables
    assert "cycle_diagnostics" in tables
    assert "regime_history" in tables


def test_trade_database_round_trips_signal_and_trade(tmp_path: Path) -> None:
    db = TradeDatabase(db_path=tmp_path / "trades.db")

    db.add_signal_event(
        signal_id="sig-1",
        status="generated",
        timestamp="2026-04-01T20:00:00+00:00",
        payload={"signal_id": "sig-1", "status": "generated", "signal": {"type": "pearlbot_pinescript"}},
    )
    db.add_trade(
        trade_id="trade-1",
        signal_id="sig-1",
        signal_type="pearlbot_pinescript",
        direction="long",
        entry_price=100.0,
        exit_price=110.0,
        pnl=20.0,
        is_win=True,
        entry_time="2026-04-01T20:00:00+00:00",
        exit_time="2026-04-01T20:15:00+00:00",
        features={"rsi": 55.0},
    )

    signal = db.get_signal_event_by_id("sig-1")
    summary = db.get_summary()
    trade_summary = db.get_trade_summary()
    db.close()

    assert signal is not None
    assert signal["signal_id"] == "sig-1"
    assert summary["total_trades"] == 1
    assert summary["wins"] == 1
    assert trade_summary["total"] == 1
    assert trade_summary["wins"] == 1
