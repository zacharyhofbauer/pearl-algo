from __future__ import annotations

from datetime import datetime, time, timezone

import pandas as pd

from pearlalgo.strategies.nq_intraday.backtest_adapter import ExitReason, TradeSimulator


def test_eod_close_is_session_aware_for_cross_midnight_sessions() -> None:
    """
    Regression test:

    For cross-midnight futures sessions (e.g., 18:00–16:10 ET), an EOD close time like 15:45 ET
    must be applied on the *session end date*.

    Example: A trade opened at 18:30 ET should NOT be immediately closed just because 18:30 > 15:45.
    It should remain open until the next day's 15:45 ET threshold.
    """
    # Build a minimal bar series that spans the relevant ET times (in UTC for determinism).
    # 2025-12-23 23:30 UTC = 18:30 ET (session start day)
    # 2025-12-24 20:44 UTC = 15:44 ET (session end day, before close)
    # 2025-12-24 20:45 UTC = 15:45 ET (close threshold)
    idx = pd.DatetimeIndex(
        [
            datetime(2025, 12, 23, 23, 30, tzinfo=timezone.utc),
            datetime(2025, 12, 23, 23, 35, tzinfo=timezone.utc),
            datetime(2025, 12, 24, 20, 44, tzinfo=timezone.utc),
            datetime(2025, 12, 24, 20, 45, tzinfo=timezone.utc),
        ],
        name="timestamp",
    )
    df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [101.0, 101.0, 101.0, 101.0],
            "low": [99.0, 99.0, 99.0, 99.0],
            "close": [100.0, 100.0, 100.0, 100.0],
            "volume": [100, 100, 100, 100],
        },
        index=idx,
    )

    # Signal aligns to first bar; stop/target far away so only EOD close can exit.
    signals = [
        {
            "timestamp": idx[0].isoformat(),
            "type": "test_signal",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss": 50.0,
            "take_profit": 150.0,
            "confidence": 0.9,
        }
    ]

    sim = TradeSimulator(
        tick_value=1.0,
        slippage_ticks=0.0,
        max_concurrent_trades=1,
        eod_close_time=time(15, 45),
        session_start_time=time(18, 0),
        session_end_time=time(16, 10),
    )

    closed_trades, metrics = sim.simulate(df, signals, position_size=1)
    assert metrics["total_trades"] == 1
    t = closed_trades[0]
    assert t.exit_reason == ExitReason.END_OF_DAY
    assert t.exit_time == datetime(2025, 12, 24, 20, 45, tzinfo=timezone.utc)



