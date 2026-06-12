from __future__ import annotations

from pathlib import Path


PINE = Path(__file__).resolve().parent.parent / "pine" / "mnq_rth_long_bias.pine"


def _pine() -> str:
    return PINE.read_text()


def test_manual_pine_has_mobile_obvious_pinstripe_identity() -> None:
    source = _pine()

    assert "PearlAlgo PINSTRIPE MNQ — Manual v4" in source
    assert "showPinstripe" in source
    assert "Alert pinstripe" in source


def test_manual_pine_honesty_hardening_is_present() -> None:
    source = _pine()

    # Strategy Tester honesty: real costs in the declaration, not the UI.
    assert "commission_type = strategy.commission.cash_per_contract" in source
    assert "commission_value = 0.95" in source
    assert "slippage = 1" in source
    assert "backtest_fill_limits_assumption = 1" in source
    # KILLED signal ships with entry alerts muted by default.
    assert 'input.string("KILLED — alerts muted"' in source
    assert "alertsLive = signalStatus ==" in source
    # Tester order placement is gated to the registered dev window by default.
    assert 'input.bool(true, "Limit Strategy Tester to dev window"' in source
    assert "ordersOk = not useBtWindow or" in source
    # No HTF lookahead surface at all.
    assert "request.security" not in source


def test_every_manual_alert_path_has_a_chart_visual() -> None:
    source = _pine()

    assert "dailyStopWillFire" in source
    assert "alertVisual = sigFired or dailyStopWillFire" in source
    assert "box.new(bar_index" in source
    assert "BUY MNQ" in source
    assert "SELL MNQ" in source
    assert "DAILY STOP" in source
    assert "Manual alert flash" in source
