from __future__ import annotations

import pytest

from pearlalgo.utils.telegram_alerts import format_home_card


@pytest.mark.parametrize(
    "buy_sell_pressure,expected_in_msg",
    [
        ("🟢 Pressure: BUYERS ▲▲ (Δ +18%, Vol 1.3x, 2h)", ["Pressure:", "BUYERS"]),
        ("🟡 Pressure: SELLERS ▼▼ (Δ -12%, Vol 0.8x, 1h)", ["Pressure:", "SELLERS"]),
        ("🔴 Pressure: SHORT ▼ (Δ -25%, Vol 2.1x, 3h)", ["Pressure:", "SHORT"]),
        ("", []),  # No pressure data
        (None, []),  # None pressure
    ],
)
@pytest.mark.parametrize(
    "agent_running,gateway_running,futures_market_open,strategy_session_open",
    [
        (True, True, True, True),
        (True, True, False, True),
        (True, False, True, True),
        (False, True, True, True),
        (True, True, True, False),
        (False, False, False, False),
    ],
)
def test_home_card_formats_correctly(
    buy_sell_pressure: str | None,
    expected_in_msg: list[str],
    agent_running: bool,
    gateway_running: bool,
    futures_market_open: bool,
    strategy_session_open: bool,
) -> None:
    """Test format_home_card with various input combinations."""
    msg = format_home_card(
        symbol="MNQ",
        time_str="08:15 AM ET",
        agent_running=agent_running,
        gateway_running=gateway_running,
        futures_market_open=futures_market_open,
        strategy_session_open=strategy_session_open,
        buy_sell_pressure=buy_sell_pressure,
        legacy=True,
    )
    
    # Assert message contains expected pressure indicators
    for expected in expected_in_msg:
        assert expected in msg, f"Expected '{expected}' in message: {msg}"
    
    # Assert message reflects agent/gateway/market/session status
    if agent_running:
        assert "Agent:" in msg or "ON" in msg or "running" in msg.lower()
    if gateway_running:
        assert "Gateway:" in msg or "ON" in msg or "running" in msg.lower()
    
    # Message should always contain symbol and time
    assert "MNQ" in msg
    assert "08:15 AM ET" in msg or "08:15" in msg
















