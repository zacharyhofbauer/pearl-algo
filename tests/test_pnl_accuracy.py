"""
P&L Accuracy Tests -- Acceptance test for the restructure.

Hand-calculated trade scenarios with known expected P&L values.
MNQ = $2.00 per point (0.25 tick = $0.50, 1 point = $2.00).

This test suite verifies that:
  1. Individual trade P&L is calculated correctly for longs and shorts
  2. Multi-trade summaries aggregate correctly
  3. Position sizing is applied correctly
  4. Edge cases (zero P&L, very small moves, large positions) are handled
  5. Performance tracker round-trips (write + read) produce consistent results

Run before and after every restructure phase to verify P&L math is intact.
"""

from __future__ import annotations

import json
import math
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock

import pytest

from pearlalgo.market_agent.performance_tracker import (
    PerformanceTracker,
    validate_trade_prices,
    DEFAULT_MNQ_TICK_VALUE,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# MNQ: $2 per point, $0.50 per tick (0.25 point)
MNQ_DOLLAR_PER_POINT = 2.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_performance_tracker(state_dir: Path) -> PerformanceTracker:
    """Create a PerformanceTracker with minimal dependencies."""
    state_manager = MagicMock()
    state_manager.state_dir = state_dir
    state_manager.get_state.return_value = {"signals": {}}

    tracker = PerformanceTracker(
        state_dir=state_dir,
        state_manager=state_manager,
    )
    return tracker


def _make_signal_record(
    signal_id: str,
    direction: str,
    entry_price: float,
    position_size: float = 1.0,
    tick_value: float = MNQ_DOLLAR_PER_POINT,
    signal_type: str = "unified_strategy",
    entry_time: str | None = None,
) -> Dict:
    """Create a signal record as it would appear in signals.jsonl."""
    if entry_time is None:
        entry_time = datetime.now(timezone.utc).isoformat()

    return {
        "signal_id": signal_id,
        "status": "active",
        "entry_price": entry_price,
        "entry_time": entry_time,
        "signal": {
            "direction": direction,
            "entry_price": entry_price,
            "type": signal_type,
            "position_size": position_size,
            "tick_value": tick_value,
        },
    }


def _write_signals_jsonl(state_dir: Path, records: List[Dict]) -> None:
    """Write signal records to the signals.jsonl file."""
    signals_file = state_dir / "signals.jsonl"
    with open(signals_file, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def _read_performance_json(state_dir: Path) -> List[Dict]:
    """Read performance records from performance.json."""
    perf_file = state_dir / "performance.json"
    if not perf_file.exists():
        return []
    with open(perf_file) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Test: Validate trade prices
# ---------------------------------------------------------------------------

class TestValidateTradePrices:
    """Test the price validation guard used before P&L calculation."""

    def test_valid_prices(self):
        ok, reason = validate_trade_prices(17500.0, 17510.0)
        assert ok is True
        assert reason == ""

    def test_zero_entry_rejected(self):
        ok, reason = validate_trade_prices(0.0, 17510.0)
        assert ok is False
        assert "positive" in reason

    def test_zero_exit_rejected(self):
        ok, reason = validate_trade_prices(17500.0, 0.0)
        assert ok is False
        assert "positive" in reason

    def test_negative_price_rejected(self):
        ok, reason = validate_trade_prices(-100.0, 17510.0)
        assert ok is False

    def test_nan_rejected(self):
        ok, reason = validate_trade_prices(float("nan"), 17510.0)
        assert ok is False
        assert "finite" in reason

    def test_inf_rejected(self):
        ok, reason = validate_trade_prices(float("inf"), 17510.0)
        assert ok is False
        assert "finite" in reason


# ---------------------------------------------------------------------------
# Test: Individual trade P&L calculation
# ---------------------------------------------------------------------------

class TestIndividualTradePnL:
    """
    Hand-calculated P&L for individual MNQ trades.

    Formula:
      Long:  pnl = (exit - entry) * tick_value * position_size
      Short: pnl = (entry - exit) * tick_value * position_size

    MNQ tick_value = $2.00 per point.
    """

    def test_long_winner_1_contract(self, tmp_path):
        """Long 1 MNQ at 17500.00, exit at 17510.00.
        Expected: (17510 - 17500) * 2.0 * 1 = +$20.00"""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("sig-001", "long", 17500.0, position_size=1)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("sig-001", 17510.0, "take_profit")

        assert result is not None
        assert result["direction"] == "long"
        assert result["entry_price"] == 17500.0
        assert result["exit_price"] == 17510.0
        assert math.isclose(result["pnl"], 20.0, abs_tol=0.01), (
            f"Expected $20.00, got ${result['pnl']:.2f}"
        )
        assert result["is_win"] is True

    def test_long_loser_1_contract(self, tmp_path):
        """Long 1 MNQ at 17500.00, stop at 17480.00.
        Expected: (17480 - 17500) * 2.0 * 1 = -$40.00"""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("sig-002", "long", 17500.0, position_size=1)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("sig-002", 17480.0, "stop_loss")

        assert result is not None
        assert math.isclose(result["pnl"], -40.0, abs_tol=0.01), (
            f"Expected -$40.00, got ${result['pnl']:.2f}"
        )
        assert result["is_win"] is False

    def test_short_winner_1_contract(self, tmp_path):
        """Short 1 MNQ at 17600.00, exit at 17580.00.
        Expected: (17600 - 17580) * 2.0 * 1 = +$40.00"""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("sig-003", "short", 17600.0, position_size=1)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("sig-003", 17580.0, "take_profit")

        assert result is not None
        assert math.isclose(result["pnl"], 40.0, abs_tol=0.01), (
            f"Expected $40.00, got ${result['pnl']:.2f}"
        )
        assert result["is_win"] is True

    def test_short_loser_3_contracts(self, tmp_path):
        """Short 3 MNQ at 17600.00, stop at 17620.00.
        Expected: (17600 - 17620) * 2.0 * 3 = -$120.00"""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("sig-004", "short", 17600.0, position_size=3)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("sig-004", 17620.0, "stop_loss")

        assert result is not None
        assert math.isclose(result["pnl"], -120.0, abs_tol=0.01), (
            f"Expected -$120.00, got ${result['pnl']:.2f}"
        )
        assert result["is_win"] is False

    def test_long_winner_5_contracts(self, tmp_path):
        """Long 5 MNQ at 17450.00, exit at 17475.00.
        Expected: (17475 - 17450) * 2.0 * 5 = +$250.00"""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("sig-005", "long", 17450.0, position_size=5)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("sig-005", 17475.0, "take_profit")

        assert result is not None
        assert math.isclose(result["pnl"], 250.0, abs_tol=0.01), (
            f"Expected $250.00, got ${result['pnl']:.2f}"
        )
        assert result["is_win"] is True

    def test_breakeven_trade(self, tmp_path):
        """Long 1 MNQ at 17500.00, exit at 17500.00.
        Expected: 0 * 2.0 * 1 = $0.00 (loss, since pnl is not > 0)"""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("sig-006", "long", 17500.0, position_size=1)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("sig-006", 17500.0, "manual")

        assert result is not None
        assert math.isclose(result["pnl"], 0.0, abs_tol=0.01)
        # Breakeven is NOT a win (pnl > 0 required)
        assert result["is_win"] is False

    def test_fractional_point_move(self, tmp_path):
        """Long 1 MNQ at 17500.00, exit at 17500.25 (1 tick).
        Expected: 0.25 * 2.0 * 1 = +$0.50"""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("sig-007", "long", 17500.0, position_size=1)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("sig-007", 17500.25, "take_profit")

        assert result is not None
        assert math.isclose(result["pnl"], 0.50, abs_tol=0.01), (
            f"Expected $0.50, got ${result['pnl']:.2f}"
        )

    def test_large_position_size(self, tmp_path):
        """Long 20 MNQ at 17500.00, exit at 17505.00.
        Expected: 5 * 2.0 * 20 = +$200.00"""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("sig-008", "long", 17500.0, position_size=20)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("sig-008", 17505.0, "take_profit")

        assert result is not None
        assert math.isclose(result["pnl"], 200.0, abs_tol=0.01), (
            f"Expected $200.00, got ${result['pnl']:.2f}"
        )


# ---------------------------------------------------------------------------
# Test: Multi-trade P&L aggregation
# ---------------------------------------------------------------------------

class TestMultiTradePnLAggregation:
    """
    Verify that multiple trades aggregate correctly.

    Scenario:
      Trade 1: Long 1 @ 17500, exit @ 17510  = +$20.00
      Trade 2: Short 3 @ 17600, stop @ 17620  = -$120.00
      Trade 3: Long 5 @ 17450, exit @ 17475   = +$250.00
      Net P&L = +$150.00
      Wins = 2, Losses = 1, Win Rate = 66.67%
    """

    def test_net_pnl_across_three_trades(self, tmp_path):
        tracker = _make_performance_tracker(tmp_path)

        t1 = _make_signal_record("agg-001", "long", 17500.0, position_size=1)
        t2 = _make_signal_record("agg-002", "short", 17600.0, position_size=3)
        t3 = _make_signal_record("agg-003", "long", 17450.0, position_size=5)
        _write_signals_jsonl(tmp_path, [t1, t2, t3])

        r1 = tracker.track_exit("agg-001", 17510.0, "take_profit")
        r2 = tracker.track_exit("agg-002", 17620.0, "stop_loss")
        r3 = tracker.track_exit("agg-003", 17475.0, "take_profit")

        assert r1 is not None and r2 is not None and r3 is not None

        net_pnl = r1["pnl"] + r2["pnl"] + r3["pnl"]
        assert math.isclose(net_pnl, 150.0, abs_tol=0.01), (
            f"Expected net P&L $150.00, got ${net_pnl:.2f}"
        )

        # Individual P&L correctness
        assert math.isclose(r1["pnl"], 20.0, abs_tol=0.01)
        assert math.isclose(r2["pnl"], -120.0, abs_tol=0.01)
        assert math.isclose(r3["pnl"], 250.0, abs_tol=0.01)

        # Win/loss classification
        assert r1["is_win"] is True
        assert r2["is_win"] is False
        assert r3["is_win"] is True

    def test_performance_metrics_summary(self, tmp_path):
        """Verify get_performance_metrics aggregates correctly after 3 trades."""
        tracker = _make_performance_tracker(tmp_path)

        t1 = _make_signal_record("sum-001", "long", 17500.0, position_size=1)
        t2 = _make_signal_record("sum-002", "short", 17600.0, position_size=3)
        t3 = _make_signal_record("sum-003", "long", 17450.0, position_size=5)
        _write_signals_jsonl(tmp_path, [t1, t2, t3])

        tracker.track_exit("sum-001", 17510.0, "take_profit")
        tracker.track_exit("sum-002", 17620.0, "stop_loss")
        tracker.track_exit("sum-003", 17475.0, "take_profit")

        metrics = tracker.get_performance_metrics()

        assert metrics["exited_signals"] == 3
        assert metrics["wins"] == 2
        assert metrics["losses"] == 1
        assert math.isclose(metrics["total_pnl"], 150.0, abs_tol=0.01), (
            f"Expected total P&L $150.00, got ${metrics['total_pnl']:.2f}"
        )
        assert math.isclose(metrics["win_rate"], 2 / 3, abs_tol=0.01), (
            f"Expected win rate 66.67%, got {metrics['win_rate']:.2%}"
        )
        assert math.isclose(metrics["avg_pnl"], 50.0, abs_tol=0.01), (
            f"Expected avg P&L $50.00, got ${metrics['avg_pnl']:.2f}"
        )


# ---------------------------------------------------------------------------
# Test: Edge cases that have caused bugs historically
# ---------------------------------------------------------------------------

class TestPnLEdgeCases:
    """Edge cases that should not crash or produce incorrect results."""

    def test_missing_signal_returns_none(self, tmp_path):
        """Exiting a signal that doesn't exist returns None, not a crash."""
        tracker = _make_performance_tracker(tmp_path)
        _write_signals_jsonl(tmp_path, [])

        result = tracker.track_exit("nonexistent", 17500.0, "manual")
        assert result is None

    def test_missing_tick_value_uses_default(self, tmp_path):
        """If tick_value is missing from signal, use DEFAULT_MNQ_TICK_VALUE."""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("edge-001", "long", 17500.0, position_size=1)
        # Remove tick_value from signal
        record["signal"].pop("tick_value", None)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("edge-001", 17510.0, "take_profit")

        assert result is not None
        # Should still use default $2/point: 10 * 2.0 * 1 = $20
        assert math.isclose(result["pnl"], 20.0, abs_tol=0.01)

    def test_missing_position_size_defaults_to_1(self, tmp_path):
        """If position_size is missing, default to 1 contract."""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("edge-002", "long", 17500.0)
        record["signal"].pop("position_size", None)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("edge-002", 17510.0, "take_profit")

        assert result is not None
        # 10 * 2.0 * 1 = $20
        assert math.isclose(result["pnl"], 20.0, abs_tol=0.01)

    def test_invalid_exit_price_zero(self, tmp_path):
        """Exit price of 0 should be rejected (validation guard)."""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("edge-003", "long", 17500.0)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("edge-003", 0.0, "manual")
        assert result is None  # Rejected by validate_trade_prices

    def test_invalid_entry_price_zero(self, tmp_path):
        """Entry price of 0 should be rejected (validation guard)."""
        tracker = _make_performance_tracker(tmp_path)
        record = _make_signal_record("edge-004", "long", 0.0)
        _write_signals_jsonl(tmp_path, [record])

        result = tracker.track_exit("edge-004", 17500.0, "manual")
        assert result is None  # Rejected by validate_trade_prices

    def test_tick_value_constant_is_correct(self):
        """Verify the MNQ tick value constant matches the known value."""
        # MNQ: $0.50 per tick (0.25 points), so $2.00 per full point
        assert DEFAULT_MNQ_TICK_VALUE == 2.0
