from __future__ import annotations

from datetime import datetime, timezone

from pearlalgo.market_agent.trading_circuit_breaker import TradingCircuitBreaker


def test_session_classification_is_dst_aware() -> None:
    cb = TradingCircuitBreaker()

    # Summer: 13:00 UTC == 09:00 ET (EDT)
    summer = datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc)
    session, et_hour = cb._get_current_session(summer)
    assert session == "morning"
    assert et_hour == 9

    # Winter: 14:00 UTC == 09:00 ET (EST)
    winter = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)
    session, et_hour = cb._get_current_session(winter)
    assert session == "morning"
    assert et_hour == 9


def test_session_boundaries_close_and_overnight() -> None:
    cb = TradingCircuitBreaker()

    # Summer close window: 21:30 UTC == 17:30 ET (EDT)
    summer_close = datetime(2026, 7, 1, 21, 30, tzinfo=timezone.utc)
    session, et_hour = cb._get_current_session(summer_close)
    assert session == "close"
    assert et_hour == 17

    # Winter overnight window: 23:30 UTC == 18:30 ET (EST)
    winter_overnight = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
    session, et_hour = cb._get_current_session(winter_overnight)
    assert session == "overnight"
    assert et_hour == 18
