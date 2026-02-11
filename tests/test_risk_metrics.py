"""
Tests for the pure risk metrics computation functions in api/metrics.py.

Covers:
- compute_risk_metrics: known-answer tests for Sharpe, Sortino, drawdown, profit factor
- Edge cases: empty pnls, all wins, all losses, single trade, exactly 5 trades
- Streaks: consecutive wins/losses, break-even trades
- Regression: Sharpe uses daily (not per-trade) returns when timestamps are available
- Kelly criterion, Calmar ratio, drawdown duration
"""

from __future__ import annotations

import pytest

from pearlalgo.api.metrics import (
    DEFAULT_RISK_METRICS,
    compute_risk_metrics,
    _compute_streaks,
    _compute_drawdown,
    _group_pnls_by_day,
    _compute_sharpe,
    _compute_sortino,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _trades_with_times(pnls_and_dates: list) -> list:
    """Build trade dicts with exit_time for daily grouping tests."""
    return [
        {"pnl": pnl, "exit_time": f"2025-01-{day:02d}T14:00:00Z", "signal_id": f"sig_{i}"}
        for i, (pnl, day) in enumerate(pnls_and_dates)
    ]


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_pnls_returns_defaults(self):
        result = compute_risk_metrics([])
        assert result["max_drawdown"] == 0.0
        assert result["sharpe_ratio"] is None
        assert result["profit_factor"] is None
        assert result["max_consecutive_wins"] == 0
        assert result["max_consecutive_losses"] == 0
        assert result["current_streak"] == 0

    def test_single_trade_win(self):
        result = compute_risk_metrics([50.0])
        assert result["avg_win"] == 50.0
        assert result["avg_loss"] == 0.0
        assert result["largest_win"] == 50.0
        assert result["max_drawdown"] == 0.0
        assert result["sharpe_ratio"] is None  # <5 observations
        assert result["max_consecutive_wins"] == 1
        assert result["current_streak"] == 1

    def test_single_trade_loss(self):
        result = compute_risk_metrics([-30.0])
        assert result["avg_loss"] == -30.0
        assert result["avg_win"] == 0.0
        assert result["largest_loss"] == -30.0
        assert result["max_drawdown"] == 30.0
        assert result["max_consecutive_losses"] == 1
        assert result["current_streak"] == -1

    def test_all_wins(self):
        pnls = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        result = compute_risk_metrics(pnls)
        assert result["profit_factor"] is None  # no losses
        assert result["max_drawdown"] == 0.0
        assert result["max_consecutive_wins"] == 6
        assert result["max_consecutive_losses"] == 0
        assert result["current_streak"] == 6
        assert result["expectancy"] > 0

    def test_all_losses(self):
        pnls = [-10.0, -20.0, -30.0, -40.0, -50.0]
        result = compute_risk_metrics(pnls)
        # profit_factor = 0 / 150 = 0.0 (not None, since total_losses > 0)
        assert result["profit_factor"] == 0.0
        assert result["max_drawdown"] > 0
        assert result["max_consecutive_losses"] == 5
        assert result["max_consecutive_wins"] == 0
        assert result["current_streak"] == -5


# ---------------------------------------------------------------------------
# Known-answer tests
# ---------------------------------------------------------------------------

class TestKnownAnswers:

    def test_drawdown_simple(self):
        pnls = [100.0, -50.0, -30.0, 40.0, 20.0]
        result = compute_risk_metrics(pnls)
        # Peak is 100, trough is 100 - 50 - 30 = 20, so max DD = 80
        assert result["max_drawdown"] == 80.0
        # max_drawdown_pct = 80 / 100 * 100 = 80.0%
        assert result["max_drawdown_pct"] == 80.0

    def test_profit_factor(self):
        pnls = [100.0, -50.0, 80.0, -30.0]
        result = compute_risk_metrics(pnls)
        # total_wins = 180, total_losses = 80
        assert result["profit_factor"] == 2.25

    def test_expectancy(self):
        pnls = [100.0, -50.0, 80.0, -30.0]
        result = compute_risk_metrics(pnls)
        # win_rate = 0.5, avg_win = 90, avg_loss = -40
        # expectancy = 0.5 * 90 + 0.5 * (-40) = 25
        assert result["expectancy"] == 25.0

    def test_avg_rr(self):
        pnls = [100.0, -50.0, 80.0, -30.0]
        result = compute_risk_metrics(pnls)
        # avg_win = 90, avg_loss = -40, R:R = |90 / -40| = 2.25
        assert result["avg_rr"] == 2.25

    def test_kelly(self):
        pnls = [100.0, -50.0, 80.0, -30.0]
        result = compute_risk_metrics(pnls)
        # win_rate = 0.5, avg_rr = 2.25
        # kelly = 0.5 - (0.5 / 2.25) = 0.5 - 0.2222 = 0.2778
        assert result["kelly_criterion"] is not None
        assert abs(result["kelly_criterion"] - 0.2778) < 0.001


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------

class TestStreaks:

    def test_simple_streaks(self):
        max_w, max_l, cur = _compute_streaks([10, 20, -5, -10, -15, 30])
        assert max_w == 2
        assert max_l == 3
        assert cur == 1  # ends on a win

    def test_break_even_resets_streak(self):
        max_w, max_l, cur = _compute_streaks([10, 20, 0, 30])
        assert max_w == 2  # first 2 wins, then break-even resets, then 1 win
        assert cur == 1

    def test_empty(self):
        max_w, max_l, cur = _compute_streaks([])
        assert max_w == 0
        assert max_l == 0
        assert cur == 0


# ---------------------------------------------------------------------------
# Daily grouping + Sharpe regression test
# ---------------------------------------------------------------------------

class TestDailyGrouping:

    def test_groups_by_day(self):
        trades = _trades_with_times([
            (10, 1), (20, 1),  # Day 1: sum = 30
            (-5, 2),           # Day 2: sum = -5
            (15, 3),           # Day 3: sum = 15
        ])
        pnls = [10, 20, -5, 15]
        daily = _group_pnls_by_day(pnls, trades)
        assert sorted(daily) == [-5, 15, 30]

    def test_no_trades_returns_pnls_unchanged(self):
        pnls = [10, 20, -5]
        daily = _group_pnls_by_day(pnls, None)
        assert daily == pnls

    def test_sharpe_with_daily_grouping(self):
        """Sharpe should be computed on daily returns, not per-trade returns."""
        # 6 trades across 3 days
        trades = _trades_with_times([
            (50, 1), (50, 1),   # Day 1: $100
            (-20, 2), (-10, 2), # Day 2: -$30
            (40, 3), (30, 3),   # Day 3: $70
            (20, 4), (10, 4),   # Day 4: $30
            (-15, 5), (-5, 5),  # Day 5: -$20
        ])
        pnls = [50, 50, -20, -10, 40, 30, 20, 10, -15, -5]

        sharpe = _compute_sharpe(pnls, trades)
        assert sharpe is not None
        # Verify it's a reasonable value (positive since net P&L is positive)
        assert sharpe > 0

    def test_sortino_excludes_positive_returns(self):
        trades = _trades_with_times([
            (50, 1), (-20, 2), (40, 3), (-10, 4), (30, 5),
        ])
        pnls = [50, -20, 40, -10, 30]
        sortino = _compute_sortino(pnls, trades)
        assert sortino is not None
        # Sortino should be higher than Sharpe (fewer observations in denominator)
        sharpe = _compute_sharpe(pnls, trades)
        if sharpe is not None:
            assert sortino >= sharpe


# ---------------------------------------------------------------------------
# Drawdown duration
# ---------------------------------------------------------------------------

class TestDrawdownDuration:

    def test_duration_with_timestamps(self):
        trades = _trades_with_times([
            (100, 1),   # Peak
            (-80, 3),   # Drawdown starts
            (-20, 5),   # Deepest point
            (50, 7),    # Partial recovery
        ])
        pnls = [100, -80, -20, 50]
        dd, dd_pct, dd_dur = _compute_drawdown(pnls, trades)
        assert dd == 100.0  # Peak 100, trough 0
        assert dd_dur is not None
        assert dd_dur > 0  # Some seconds between day 1 and day 5

    def test_no_drawdown_no_duration(self):
        pnls = [10, 20, 30]
        dd, dd_pct, dd_dur = _compute_drawdown(pnls, None)
        assert dd == 0.0
        assert dd_dur is None


# ---------------------------------------------------------------------------
# Top losses
# ---------------------------------------------------------------------------

class TestTopLosses:

    def test_top_losses_with_trades(self):
        trades = [
            {"pnl": 50, "signal_id": "a", "exit_reason": "tp"},
            {"pnl": -100, "signal_id": "b", "exit_reason": "sl"},
            {"pnl": -20, "signal_id": "c", "exit_reason": "sl"},
            {"pnl": 30, "signal_id": "d", "exit_reason": "tp"},
            {"pnl": -80, "signal_id": "e", "exit_reason": "sl"},
        ]
        pnls = [t["pnl"] for t in trades]
        result = compute_risk_metrics(pnls, trades)
        assert len(result["top_losses"]) == 3
        assert result["top_losses"][0]["pnl"] == -100
        assert result["top_losses"][1]["pnl"] == -80
        assert result["top_losses"][2]["pnl"] == -20

    def test_no_losses(self):
        result = compute_risk_metrics([10, 20, 30])
        assert result["top_losses"] == []

    def test_top_losses_without_trades_metadata(self):
        """When trades is None, top_losses should still work (pnls-only path)."""
        pnls = [50, -100, -20, 30, -80]
        result = compute_risk_metrics(pnls, None)
        assert len(result["top_losses"]) == 3
        assert result["top_losses"][0]["pnl"] == -100
        assert result["top_losses"][1]["pnl"] == -80


# ---------------------------------------------------------------------------
# Calmar ratio
# ---------------------------------------------------------------------------

class TestCalmar:

    def test_calmar_positive(self):
        from pearlalgo.api.metrics import _compute_calmar
        # 5 trades over 5 days = 1 trade/day, total pnl=100, max_dd=30
        trades = _trades_with_times([(40, 1), (-30, 2), (50, 3), (-10, 4), (50, 5)])
        pnls = [40, -30, 50, -10, 50]
        calmar = _compute_calmar(pnls, trades, max_dd=30.0)
        assert calmar is not None
        assert calmar > 0

    def test_calmar_zero_drawdown_returns_none(self):
        from pearlalgo.api.metrics import _compute_calmar
        calmar = _compute_calmar([10, 20, 30], None, max_dd=0.0)
        assert calmar is None

    def test_calmar_negative_pnl(self):
        from pearlalgo.api.metrics import _compute_calmar
        trades = _trades_with_times([(-20, 1), (-30, 2), (-10, 3), (-40, 4), (-50, 5)])
        pnls = [-20, -30, -10, -40, -50]
        calmar = _compute_calmar(pnls, trades, max_dd=150.0)
        assert calmar is not None
        assert calmar < 0


# ---------------------------------------------------------------------------
# _estimate_trading_days
# ---------------------------------------------------------------------------

class TestEstimateTradingDays:

    def test_counts_unique_days(self):
        from pearlalgo.api.metrics import _estimate_trading_days
        trades = _trades_with_times([(10, 1), (20, 1), (30, 2), (40, 3)])
        days = _estimate_trading_days(trades)
        assert days == 3  # Jan 1, 2, 3

    def test_empty_trades(self):
        from pearlalgo.api.metrics import _estimate_trading_days
        assert _estimate_trading_days([]) is None

    def test_missing_timestamps(self):
        from pearlalgo.api.metrics import _estimate_trading_days
        trades = [{"pnl": 10}, {"pnl": 20}]  # no exit_time
        assert _estimate_trading_days(trades) is None

    def test_bad_timestamps_ignored(self):
        from pearlalgo.api.metrics import _estimate_trading_days
        trades = [{"exit_time": "not-a-date"}, {"exit_time": "2025-01-05T12:00:00Z"}]
        days = _estimate_trading_days(trades)
        assert days == 1  # Only the valid one


# ---------------------------------------------------------------------------
# _parse_exit_time
# ---------------------------------------------------------------------------

class TestParseExitTime:

    def test_valid_iso_timestamp(self):
        from pearlalgo.api.metrics import _parse_exit_time
        trades = [{"exit_time": "2025-01-15T14:30:00Z"}]
        dt = _parse_exit_time(trades, 0)
        assert dt is not None
        assert dt.year == 2025

    def test_index_out_of_range(self):
        from pearlalgo.api.metrics import _parse_exit_time
        assert _parse_exit_time([], 0) is None
        assert _parse_exit_time([{"exit_time": "2025-01-01T00:00:00Z"}], 5) is None

    def test_invalid_format(self):
        from pearlalgo.api.metrics import _parse_exit_time
        trades = [{"exit_time": "not-valid"}]
        assert _parse_exit_time(trades, 0) is None

    def test_missing_exit_time(self):
        from pearlalgo.api.metrics import _parse_exit_time
        trades = [{"pnl": 10}]
        assert _parse_exit_time(trades, 0) is None


# ---------------------------------------------------------------------------
# Sortino edge cases
# ---------------------------------------------------------------------------

class TestSortinoEdge:

    def test_all_positive_returns_none(self):
        """Sortino with no negative returns should return None (infinite)."""
        trades = _trades_with_times([(10, 1), (20, 2), (30, 3), (40, 4), (50, 5)])
        pnls = [10, 20, 30, 40, 50]
        sortino = _compute_sortino(pnls, trades)
        assert sortino is None

    def test_fewer_than_5_observations_returns_none(self):
        trades = _trades_with_times([(10, 1), (-5, 2)])
        pnls = [10, -5]
        assert _compute_sortino(pnls, trades) is None
        assert _compute_sharpe(pnls, trades) is None


# ---------------------------------------------------------------------------
# DEFAULT_RISK_METRICS contract
# ---------------------------------------------------------------------------

class TestDefaultMetricsContract:

    def test_compute_returns_all_default_keys(self):
        """Returned dict should have every key from DEFAULT_RISK_METRICS."""
        result = compute_risk_metrics([10, -5, 20, -10, 15])
        for key in DEFAULT_RISK_METRICS:
            assert key in result, f"Missing key: {key}"

    def test_empty_returns_matches_defaults(self):
        result = compute_risk_metrics([])
        assert result == DEFAULT_RISK_METRICS

    def test_avg_rr_none_when_no_losses(self):
        result = compute_risk_metrics([10, 20, 30, 40, 50])
        # avg_loss = 0 → avg_rr should be None (division by zero guard)
        assert result["avg_rr"] is None
