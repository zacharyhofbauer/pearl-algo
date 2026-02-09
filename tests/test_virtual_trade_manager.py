"""
Tests for VirtualTradeManager lifecycle scenarios.

Comprehensive lifecycle tests covering virtual trade entry, exit via TP/SL,
concurrent trades, and edge cases with stale or malformed market data.

Uses @pytest.mark.unit for all tests.  Follows patterns from test_service_core.py
(mock factories, _make_entered_signal, _make_ohlcv_df helpers).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from pearlalgo.market_agent.virtual_trade_manager import VirtualTradeManager


# ---------------------------------------------------------------------------
# Helper factories (mirrors test_service_core.py patterns)
# ---------------------------------------------------------------------------

def _make_mock_state_manager():
    """Create a mock MarketAgentStateManager with safe defaults."""
    sm = MagicMock()
    sm.get_recent_signals.return_value = []
    sm.get_signal_count.return_value = 0
    sm.load_state.return_value = {}
    return sm


def _make_mock_performance_tracker(pnl: float = 25.0, is_win: bool = True):
    """Create a mock PerformanceTracker with configurable return values."""
    pt = MagicMock()
    pt.track_exit.return_value = {
        "pnl": pnl,
        "is_win": is_win,
        "hold_duration_minutes": 15,
    }
    return pt


def _make_mock_notification_queue():
    """Create a mock NotificationQueue."""
    nq = MagicMock()
    nq.enqueue_exit = AsyncMock(return_value=True)
    nq.enqueue_raw_message = AsyncMock(return_value=True)
    nq.enqueue_data_quality_alert = AsyncMock(return_value=True)
    nq.stop = AsyncMock()
    nq.get_stats.return_value = {"pending": 0, "sent": 0}
    return nq


def _make_entered_signal(
    *,
    signal_id: str = "test-sig-001",
    direction: str = "long",
    entry_price: float = 17500.0,
    stop_loss: float = 17480.0,
    take_profit: float = 17530.0,
    entry_time: str = "2025-12-23T10:00:00+00:00",
    extra_signal_fields: dict | None = None,
) -> dict:
    """Build a signal record in 'entered' state."""
    signal = {
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    }
    if extra_signal_fields:
        signal.update(extra_signal_fields)
    return {
        "signal_id": signal_id,
        "status": "entered",
        "entry_time": entry_time,
        "signal": signal,
    }


def _make_ohlcv_df(
    *,
    timestamps: list[datetime],
    highs: list[float],
    lows: list[float],
    opens: list[float] | None = None,
    closes: list[float] | None = None,
    volumes: list[int] | None = None,
) -> pd.DataFrame:
    """Build an OHLCV DataFrame suitable for process_exits."""
    n = len(timestamps)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens or [17500.0] * n,
        "high": highs,
        "low": lows,
        "close": closes or [17500.0] * n,
        "volume": volumes or [1000] * n,
    })


def _make_vtm(
    *,
    pnl: float = 25.0,
    is_win: bool = True,
    virtual_pnl_enabled: bool = True,
    tiebreak: str = "stop_loss",
    performance_tracker: MagicMock | None = None,
) -> VirtualTradeManager:
    """Create a VirtualTradeManager with all dependencies mocked."""
    pt = performance_tracker or _make_mock_performance_tracker(pnl=pnl, is_win=is_win)
    return VirtualTradeManager(
        state_manager=_make_mock_state_manager(),
        performance_tracker=pt,
        notification_queue=_make_mock_notification_queue(),
        virtual_pnl_enabled=virtual_pnl_enabled,
        virtual_pnl_tiebreak=tiebreak,
        symbol="MNQ",
    )


# ===========================================================================
# Lifecycle Tests
# ===========================================================================


@pytest.mark.unit
class TestVirtualTradeManagerLifecycle:
    """End-to-end lifecycle tests for VirtualTradeManager."""

    # -----------------------------------------------------------------------
    # 1. Happy-path lifecycle
    # -----------------------------------------------------------------------

    def test_happy_path_lifecycle(self):
        """Full lifecycle: create VTM -> enter virtual trade -> TP hit -> recorded as win."""
        # 1. Create VTM with mock returning a winning result
        vtm = _make_vtm(pnl=30.0, is_win=True)

        # 2. "Enter" a virtual trade (state_manager reports it as entered)
        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="lifecycle-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17530.0,
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        # 3. Price data where second bar hits take_profit
        df = _make_ohlcv_df(
            timestamps=[
                entry_time + timedelta(minutes=5),
                entry_time + timedelta(minutes=10),
            ],
            highs=[17510.0, 17535.0],  # Second bar crosses TP (17530)
            lows=[17495.0, 17505.0],   # Never crosses SL (17480)
        )

        # 4. Process exits
        vtm.process_exits({"df": df})

        # 5. Verify trade was recorded
        vtm.performance_tracker.track_exit.assert_called_once()
        call_kw = vtm.performance_tracker.track_exit.call_args[1]
        assert call_kw["signal_id"] == "lifecycle-001"
        assert call_kw["exit_reason"] == "take_profit"
        assert call_kw["exit_price"] == 17530.0

        # 6. Verify the exit was recorded as a win via streak tracking
        assert vtm._streak_type == "win"
        assert vtm._streak_count == 1

    # -----------------------------------------------------------------------
    # 2. TP exit (long)
    # -----------------------------------------------------------------------

    def test_tp_exit(self):
        """Long trade exits at take_profit with positive P&L."""
        vtm = _make_vtm(pnl=30.0, is_win=True)

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="tp-exit-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17530.0,
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        # Bar high crosses TP, low stays above SL
        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[17535.0],   # >= TP (17530)
            lows=[17495.0],    # > SL (17480) — only TP hit
        )

        vtm.process_exits({"df": df})

        vtm.performance_tracker.track_exit.assert_called_once()
        call_kw = vtm.performance_tracker.track_exit.call_args[1]
        assert call_kw["exit_reason"] == "take_profit"
        assert call_kw["exit_price"] == 17530.0

        # Confirm positive P&L: exit_price (17530) > entry_price (17500)
        perf = vtm.performance_tracker.track_exit.return_value
        assert perf["pnl"] > 0
        assert perf["is_win"] is True

    # -----------------------------------------------------------------------
    # 3. SL exit (long)
    # -----------------------------------------------------------------------

    def test_sl_exit(self):
        """Long trade exits at stop_loss with negative P&L."""
        vtm = _make_vtm(pnl=-20.0, is_win=False)

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="sl-exit-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17530.0,
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        # Bar low crosses SL, high stays below TP
        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[17510.0],   # < TP (17530)
            lows=[17475.0],    # <= SL (17480) — only SL hit
        )

        vtm.process_exits({"df": df})

        vtm.performance_tracker.track_exit.assert_called_once()
        call_kw = vtm.performance_tracker.track_exit.call_args[1]
        assert call_kw["exit_reason"] == "stop_loss"
        assert call_kw["exit_price"] == 17480.0

        # Confirm negative P&L: exit_price (17480) < entry_price (17500)
        perf = vtm.performance_tracker.track_exit.return_value
        assert perf["pnl"] < 0
        assert perf["is_win"] is False

    # -----------------------------------------------------------------------
    # 4. Time-based exit (trade stays open when no TP/SL hit)
    # -----------------------------------------------------------------------

    def test_time_based_exit(self):
        """Trade without TP/SL hit stays open across many bars.

        VirtualTradeManager has no max-hold-time mechanism, so a trade
        that never touches TP or SL simply remains active indefinitely.
        This verifies no spurious exits over a prolonged period.
        """
        vtm = _make_vtm()

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="no-exit-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17530.0,
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        # 24 bars over 2 hours — price stays strictly between SL and TP
        bar_count = 24
        timestamps = [
            entry_time + timedelta(minutes=5 * (i + 1))
            for i in range(bar_count)
        ]
        highs = [17520.0] * bar_count   # Below TP (17530)
        lows = [17490.0] * bar_count     # Above SL (17480)

        df = _make_ohlcv_df(timestamps=timestamps, highs=highs, lows=lows)

        vtm.process_exits({"df": df})

        # No exit triggered — trade remains active
        vtm.performance_tracker.track_exit.assert_not_called()

    # -----------------------------------------------------------------------
    # 5. Multiple concurrent trades
    # -----------------------------------------------------------------------

    def test_multiple_concurrent_trades(self):
        """Three concurrent trades: one hits TP, one hits SL, one stays open."""
        # track_exit returns different results per call
        pt = MagicMock()
        pt.track_exit.side_effect = [
            {"pnl": 30.0, "is_win": True, "hold_duration_minutes": 10},   # TP trade
            {"pnl": -15.0, "is_win": False, "hold_duration_minutes": 8},  # SL trade
        ]
        vtm = _make_vtm(performance_tracker=pt)

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)

        # Trade 1: TP will be hit  (long, TP=17530)
        sig_tp = _make_entered_signal(
            signal_id="multi-tp-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17530.0,
            entry_time=entry_time.isoformat(),
        )
        # Trade 2: SL will be hit  (long, SL=17490)
        sig_sl = _make_entered_signal(
            signal_id="multi-sl-002",
            direction="long",
            entry_price=17505.0,
            stop_loss=17490.0,
            take_profit=17540.0,
            entry_time=entry_time.isoformat(),
        )
        # Trade 3: neither TP nor SL hit  (wide TP/SL levels)
        sig_open = _make_entered_signal(
            signal_id="multi-open-003",
            direction="long",
            entry_price=17510.0,
            stop_loss=17460.0,
            take_profit=17560.0,
            entry_time=entry_time.isoformat(),
        )

        vtm.state_manager.get_recent_signals.return_value = [sig_tp, sig_sl, sig_open]

        # Single bar:
        #   high=17535 → hits sig_tp TP(17530), misses sig_sl TP(17540), misses sig_open TP(17560)
        #   low=17485  → misses sig_tp SL(17480), hits sig_sl SL(17490), misses sig_open SL(17460)
        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[17535.0],
            lows=[17485.0],
        )

        vtm.process_exits({"df": df})

        # Exactly 2 exits recorded
        assert pt.track_exit.call_count == 2

        # Build a lookup of signal_id → kwargs for each exit call
        exit_calls = {
            c[1]["signal_id"]: c[1]
            for c in pt.track_exit.call_args_list
        }

        # Trade 1: exits at TP
        assert "multi-tp-001" in exit_calls
        assert exit_calls["multi-tp-001"]["exit_reason"] == "take_profit"
        assert exit_calls["multi-tp-001"]["exit_price"] == 17530.0

        # Trade 2: exits at SL
        assert "multi-sl-002" in exit_calls
        assert exit_calls["multi-sl-002"]["exit_reason"] == "stop_loss"
        assert exit_calls["multi-sl-002"]["exit_price"] == 17490.0

        # Trade 3: NOT exited
        assert "multi-open-003" not in exit_calls

    # -----------------------------------------------------------------------
    # 6. Stale / NaN data
    # -----------------------------------------------------------------------

    def test_entry_with_stale_data(self):
        """Trade entered when data has old timestamps and NaN values.

        Bars before entry_time are masked by after_entry_mask.
        Bars with NaN high/low are neutralised via fillna + valid_mask.
        A subsequent valid bar that doesn't hit TP/SL leaves the trade open.
        """
        vtm = _make_vtm()

        entry_time = datetime(2025, 12, 23, 14, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="stale-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17530.0,
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        # Bar 1-2: timestamps BEFORE entry (stale) — extreme prices that
        #          would trigger an exit if not masked by after_entry_mask.
        # Bar 3:   after entry but NaN high/low — neutralised by fillna+valid_mask.
        # Bar 4:   valid bar, price between SL and TP — no exit.
        timestamps = [
            entry_time - timedelta(hours=2),
            entry_time - timedelta(hours=1),
            entry_time + timedelta(minutes=5),
            entry_time + timedelta(minutes=10),
        ]
        df = _make_ohlcv_df(
            timestamps=timestamps,
            highs=[18000.0, 18000.0, float("nan"), 17510.0],
            lows=[17000.0, 17000.0, float("nan"), 17495.0],
            closes=[17500.0, 17500.0, 0.0, 17500.0],
        )

        # Should not crash and should not exit
        vtm.process_exits({"df": df})
        vtm.performance_tracker.track_exit.assert_not_called()


# ===========================================================================
# Short-direction tests
# ===========================================================================


@pytest.mark.unit
class TestVirtualTradeManagerShortDirection:
    """Tests for short-direction trade exits."""

    def test_tp_exit_short(self):
        """Short trade exits at take_profit when bar low <= target."""
        vtm = _make_vtm(pnl=30.0, is_win=True)

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="tp-short-001",
            direction="short",
            entry_price=17500.0,
            stop_loss=17520.0,   # Above entry (loss for short)
            take_profit=17470.0, # Below entry (profit for short)
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[17510.0],    # < SL (17520) — SL not hit
            lows=[17465.0],     # <= TP (17470) — TP hit
        )

        vtm.process_exits({"df": df})

        vtm.performance_tracker.track_exit.assert_called_once()
        call_kw = vtm.performance_tracker.track_exit.call_args[1]
        assert call_kw["exit_reason"] == "take_profit"
        assert call_kw["exit_price"] == 17470.0

    def test_sl_exit_short(self):
        """Short trade exits at stop_loss when bar high >= stop."""
        vtm = _make_vtm(pnl=-20.0, is_win=False)

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="sl-short-001",
            direction="short",
            entry_price=17500.0,
            stop_loss=17520.0,
            take_profit=17470.0,
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[17525.0],    # >= SL (17520) — SL hit
            lows=[17490.0],     # > TP (17470) — TP not hit
        )

        vtm.process_exits({"df": df})

        vtm.performance_tracker.track_exit.assert_called_once()
        call_kw = vtm.performance_tracker.track_exit.call_args[1]
        assert call_kw["exit_reason"] == "stop_loss"
        assert call_kw["exit_price"] == 17520.0


# ===========================================================================
# Edge-case tests (additional robustness coverage)
# ===========================================================================


@pytest.mark.unit
class TestVirtualTradeManagerEdgeCases:
    """Edge-case coverage for VirtualTradeManager.process_exits."""

    def test_missing_df_key_no_crash(self):
        """process_exits with market_data missing 'df' key is a safe no-op."""
        vtm = _make_vtm()
        vtm.process_exits({})
        vtm.performance_tracker.track_exit.assert_not_called()

    def test_none_market_data_no_crash(self):
        """process_exits with None market_data is a safe no-op."""
        vtm = _make_vtm()
        vtm.process_exits(None)
        vtm.performance_tracker.track_exit.assert_not_called()

    def test_empty_dataframe_no_crash(self):
        """process_exits with an empty DataFrame is a safe no-op."""
        vtm = _make_vtm()
        signal = _make_entered_signal(signal_id="empty-df-001")
        vtm.state_manager.get_recent_signals.return_value = [signal]

        vtm.process_exits({"df": pd.DataFrame()})
        vtm.performance_tracker.track_exit.assert_not_called()

    def test_signal_with_zero_stop_or_target_skipped(self):
        """Signals with stop_loss=0 or take_profit=0 are skipped."""
        vtm = _make_vtm()

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="zero-levels-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=0.0,
            take_profit=0.0,
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[18000.0],
            lows=[17000.0],
        )

        vtm.process_exits({"df": df})
        vtm.performance_tracker.track_exit.assert_not_called()

    def test_non_entered_status_skipped(self):
        """Signals not in 'entered' status are ignored."""
        vtm = _make_vtm()

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(signal_id="pending-001")
        signal["status"] = "pending"  # Override to non-entered status
        vtm.state_manager.get_recent_signals.return_value = [signal]

        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[18000.0],
            lows=[17000.0],
        )

        vtm.process_exits({"df": df})
        vtm.performance_tracker.track_exit.assert_not_called()

    def test_disabled_virtual_pnl_skips_entirely(self):
        """When virtual_pnl_enabled=False, process_exits returns immediately."""
        vtm = _make_vtm(virtual_pnl_enabled=False)

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(signal_id="disabled-001")
        vtm.state_manager.get_recent_signals.return_value = [signal]

        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[18000.0],
            lows=[17000.0],
        )

        vtm.process_exits({"df": df})

        # Should not even call get_recent_signals
        vtm.state_manager.get_recent_signals.assert_not_called()
        vtm.performance_tracker.track_exit.assert_not_called()

    def test_duplicate_signal_id_exits_only_once(self):
        """If the same signal_id appears twice, only the first triggers an exit."""
        vtm = _make_vtm(pnl=30.0, is_win=True)

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="dup-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17530.0,
            entry_time=entry_time.isoformat(),
        )
        # Same signal returned twice (simulates a state_manager quirk)
        vtm.state_manager.get_recent_signals.return_value = [signal, signal.copy()]

        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[17535.0],
            lows=[17495.0],
        )

        vtm.process_exits({"df": df})

        # Only one exit despite duplicate entries
        vtm.performance_tracker.track_exit.assert_called_once()

    def test_df_missing_required_columns_no_crash(self):
        """DataFrame without 'high' or 'low' columns is a safe no-op."""
        vtm = _make_vtm()
        signal = _make_entered_signal(signal_id="bad-cols-001")
        vtm.state_manager.get_recent_signals.return_value = [signal]

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        # DataFrame with timestamp but missing high/low
        df = pd.DataFrame({
            "timestamp": [entry_time + timedelta(minutes=5)],
            "close": [17500.0],
        })

        vtm.process_exits({"df": df})
        vtm.performance_tracker.track_exit.assert_not_called()

    def test_tiebreak_stop_loss_when_both_hit(self):
        """When both TP and SL are hit in the same bar, stop_loss tiebreak picks SL."""
        vtm = _make_vtm(tiebreak="stop_loss", pnl=-20.0, is_win=False)

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="tie-sl-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17530.0,
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        # Bar touches BOTH TP and SL
        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[17535.0],   # Above TP
            lows=[17475.0],    # Below SL
        )

        vtm.process_exits({"df": df})

        call_kw = vtm.performance_tracker.track_exit.call_args[1]
        assert call_kw["exit_reason"] == "stop_loss"
        assert call_kw["exit_price"] == 17480.0

    def test_tiebreak_take_profit_when_both_hit(self):
        """When tiebreak='take_profit' and both hit, TP is chosen."""
        vtm = _make_vtm(tiebreak="take_profit", pnl=30.0, is_win=True)

        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        signal = _make_entered_signal(
            signal_id="tie-tp-001",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17530.0,
            entry_time=entry_time.isoformat(),
        )
        vtm.state_manager.get_recent_signals.return_value = [signal]

        # Bar touches BOTH TP and SL
        df = _make_ohlcv_df(
            timestamps=[entry_time + timedelta(minutes=5)],
            highs=[17535.0],
            lows=[17475.0],
        )

        vtm.process_exits({"df": df})

        call_kw = vtm.performance_tracker.track_exit.call_args[1]
        assert call_kw["exit_reason"] == "take_profit"
        assert call_kw["exit_price"] == 17530.0
