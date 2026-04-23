"""Tests for Issue 24-A — pearl.sh backtest-config replay gate.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 1.

Focuses on the deterministic pieces: ``simulate_exit`` first-touch
model, ``Scorecard.record`` math, bucketing, JSON shape, CLI help.
Full walk-forward replay over a real archive is exercised by running
the CLI against the Beelink's backfilled data post-deploy.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "backtest_config.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("backtest_config", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec_module so @dataclass can resolve cls.__module__.
    sys.modules["backtest_config"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


# ---------------------------------------------------------------------------
# tf_minutes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tf,expected",
    [("1m", 1), ("5m", 5), ("15m", 15), ("1h", 60), ("4h", 240), ("1d", 1440)],
)
def test_tf_minutes_recognizes_canonical_timeframes(mod, tf: str, expected: int):
    assert mod._tf_minutes(tf) == expected


def test_tf_minutes_rejects_unsupported(mod):
    with pytest.raises(ValueError):
        mod._tf_minutes("3s")


# ---------------------------------------------------------------------------
# simulate_exit — first-touch SL/TP model
# ---------------------------------------------------------------------------


def _bar(ts: int, o: float, h: float, lo: float, c: float, v: float = 1.0) -> dict:
    return {"time": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v}


def _long_trade(mod, entry_ts: int = 100, entry: float = 100.0, sl: float = 95.0, tp: float = 110.0):
    return mod.SimTrade(
        signal_id="t1",
        trigger="ema_cross",
        direction="long",
        entry_time=entry_ts,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=0.7,
    )


def _short_trade(mod, entry_ts: int = 100, entry: float = 100.0, sl: float = 105.0, tp: float = 90.0):
    return mod.SimTrade(
        signal_id="s1",
        trigger="vwap_cross",
        direction="short",
        entry_time=entry_ts,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=0.7,
    )


def test_simulate_exit_long_hits_take_profit(mod):
    trade = _long_trade(mod)
    bars = [
        _bar(160, 100.5, 101.0, 100.0, 100.2),
        _bar(220, 100.2, 110.5, 100.0, 110.3),  # TP hit (high >= tp)
    ]
    mod.simulate_exit(trade, bars, max_hold_minutes=180)
    assert trade.exit_reason == "tp"
    assert trade.exit_price == trade.take_profit
    assert trade.exit_time == 220


def test_simulate_exit_long_hits_stop_loss_before_tp(mod):
    trade = _long_trade(mod)
    bars = [
        _bar(160, 100.5, 101.0, 94.5, 94.8),  # SL hit first (low <= sl)
        _bar(220, 94.8, 112.0, 94.0, 111.0),  # would be TP but already exited
    ]
    mod.simulate_exit(trade, bars, max_hold_minutes=180)
    assert trade.exit_reason == "sl"
    assert trade.exit_price == trade.stop_loss


def test_simulate_exit_short_hits_take_profit(mod):
    trade = _short_trade(mod)
    bars = [
        _bar(160, 100.5, 101.0, 95.0, 96.0),
        _bar(220, 96.0, 96.5, 89.0, 89.5),  # low <= tp
    ]
    mod.simulate_exit(trade, bars, max_hold_minutes=180)
    assert trade.exit_reason == "tp"
    assert trade.exit_price == trade.take_profit


def test_simulate_exit_short_hits_stop_loss(mod):
    trade = _short_trade(mod)
    bars = [
        _bar(160, 100.5, 105.5, 100.0, 105.2),  # high >= sl
    ]
    mod.simulate_exit(trade, bars, max_hold_minutes=180)
    assert trade.exit_reason == "sl"
    assert trade.exit_price == trade.stop_loss


def test_simulate_exit_times_out(mod):
    trade = _long_trade(mod, entry_ts=0)
    # No SL / TP hit, deadline at 3600s
    bars = [
        _bar(60, 100.5, 100.6, 99.9, 100.2),
        _bar(1800, 100.2, 100.7, 99.8, 100.5),
        _bar(3700, 100.5, 100.7, 99.8, 100.3),  # past deadline
    ]
    mod.simulate_exit(trade, bars, max_hold_minutes=60)
    assert trade.exit_reason == "timeout"
    assert trade.exit_time == 3700


def test_simulate_exit_falls_off_end_without_touch(mod):
    trade = _long_trade(mod, entry_ts=0)
    bars = [
        _bar(60, 100.5, 100.6, 99.9, 100.2),
        _bar(120, 100.2, 100.5, 99.8, 100.1),
    ]
    mod.simulate_exit(trade, bars, max_hold_minutes=180)
    assert trade.exit_reason == "timeout"
    assert trade.exit_price == 100.1  # last close


def test_simulate_exit_ignores_bars_before_entry(mod):
    trade = _long_trade(mod, entry_ts=200)
    bars = [
        _bar(100, 100.0, 120.0, 90.0, 110.0),  # before entry — must be ignored
        _bar(260, 110.0, 111.0, 110.0, 110.5),  # after entry, TP hit at high >= 110
    ]
    mod.simulate_exit(trade, bars, max_hold_minutes=180)
    assert trade.exit_reason == "tp"
    assert trade.exit_time == 260


# ---------------------------------------------------------------------------
# Scorecard math
# ---------------------------------------------------------------------------


def test_scorecard_records_winning_and_losing_trades(mod):
    sc = mod.Scorecard()
    t1 = _long_trade(mod)
    t1.exit_reason = "tp"
    t1.exit_price = 110.0
    t1.exit_time = 500
    t2 = _long_trade(mod)
    t2.exit_reason = "sl"
    t2.exit_price = 95.0
    t2.exit_time = 600

    sc.record(t1, tf_minutes=5)
    sc.record(t2, tf_minutes=5)

    d = sc.to_dict()
    assert d["entries"] == 2
    assert d["wins"] == 1
    assert d["losses"] == 1
    assert d["total_points"] == pytest.approx(10.0 + (-5.0))
    assert d["avg_win_points"] == pytest.approx(10.0)
    assert d["avg_loss_points"] == pytest.approx(-5.0)
    assert d["max_win_points"] == pytest.approx(10.0)
    assert d["max_loss_points"] == pytest.approx(-5.0)
    assert d["win_rate"] == pytest.approx(0.5)


def test_scorecard_tracks_max_drawdown_correctly(mod):
    sc = mod.Scorecard()
    wins_and_losses = [
        ("tp", 110.0),    # +10
        ("tp", 110.0),    # +10  (equity 20, peak 20)
        ("sl", 85.0),     # -15  (equity 5, drawdown 15)
        ("sl", 85.0),     # -15  (equity -10, drawdown from peak 20 -> 30)
        ("tp", 110.0),    # +10  (equity 0)
    ]
    for reason, exit_price in wins_and_losses:
        t = _long_trade(mod)
        t.exit_reason = reason
        t.exit_price = exit_price
        t.exit_time = 500
        sc.record(t, tf_minutes=5)

    d = sc.to_dict()
    assert d["total_points"] == pytest.approx(10 + 10 - 15 - 15 + 10)  # 0
    assert d["max_drawdown_points"] == pytest.approx(30.0)


def test_scorecard_timeout_classifies_by_pnl_sign(mod):
    sc = mod.Scorecard()
    t_pos = _long_trade(mod)
    t_pos.exit_reason = "timeout"
    t_pos.exit_price = 101.5
    t_pos.exit_time = 500
    t_neg = _long_trade(mod)
    t_neg.exit_reason = "timeout"
    t_neg.exit_price = 99.0
    t_neg.exit_time = 600
    sc.record(t_pos, tf_minutes=5)
    sc.record(t_neg, tf_minutes=5)
    d = sc.to_dict()
    assert d["wins"] == 1
    assert d["losses"] == 1
    assert d["timeouts"] == 2


def test_scorecard_per_trigger_breakdown(mod):
    sc = mod.Scorecard()
    for trigger in ("ema_cross", "ema_cross", "vwap_cross"):
        t = _long_trade(mod)
        t.trigger = trigger
        t.exit_reason = "tp"
        t.exit_price = 110.0
        t.exit_time = 500
        sc.record(t, tf_minutes=5)
    d = sc.to_dict()
    assert d["by_trigger"]["ema_cross"]["entries"] == 2
    assert d["by_trigger"]["vwap_cross"]["entries"] == 1
    assert d["by_trigger"]["ema_cross"]["win_rate"] == pytest.approx(1.0)


def test_scorecard_hold_duration_bucketing(mod):
    sc = mod.Scorecard()
    durations_seconds = [60, 300, 1000, 3000, 7000, 15000]  # 1m, 5m, ~17m, 50m, ~2h, ~4h
    for secs in durations_seconds:
        t = _long_trade(mod, entry_ts=0)
        t.exit_reason = "tp"
        t.exit_price = 105.0
        t.exit_time = secs
        sc.record(t, tf_minutes=5)
    d = sc.to_dict()
    buckets = d["hold_duration_buckets"]
    # At least 3 distinct buckets should appear.
    assert len(buckets) >= 3


# ---------------------------------------------------------------------------
# CLI shape
# ---------------------------------------------------------------------------


def test_cli_help_renders():
    # Must not crash even in environments without an archive.
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Pearl-Algo config backtest" in result.stdout
    assert "--tf" in result.stdout
    assert "--json" in result.stdout


def test_main_returns_non_zero_when_archive_empty(mod):
    # days=1 + warmup=5 still needs 5 bars; archive is empty on a fresh test env.
    rc = mod.main([
        "--days", "1", "--tf", "5m", "--warmup-bars", "5",
        "--max-hold-minutes", "60", "--json",
    ])
    assert rc == 1


def test_text_formatter_handles_error_result(mod):
    text = mod._format_scorecard_text({"error": "not enough candles"})
    assert text.startswith("ERROR:")


def test_scorecard_to_dict_is_json_serializable(mod):
    sc = mod.Scorecard()
    t = _long_trade(mod)
    t.exit_reason = "tp"
    t.exit_price = 110.0
    t.exit_time = 500
    sc.record(t, tf_minutes=5)
    d = sc.to_dict()
    # round-trip through json to verify no exotic types escape the dataclass.
    blob = json.dumps(d)
    reloaded = json.loads(blob)
    assert reloaded["entries"] == 1
