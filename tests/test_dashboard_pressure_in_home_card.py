from __future__ import annotations

from pearlalgo.utils.telegram_alerts import format_home_card


def test_home_card_includes_buy_sell_pressure_line() -> None:
    msg = format_home_card(
        symbol="MNQ",
        time_str="08:15 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        buy_sell_pressure="🟢 Pressure: BUYERS ▲▲ (Δ +18%, Vol 1.3x, 2h)",
    )
    assert "Pressure:" in msg
    assert "BUYERS" in msg








