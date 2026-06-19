from __future__ import annotations

from pathlib import Path


PINE = Path(__file__).resolve().parent.parent / "pine" / "mnq_rth_long_bias.pine"
DEFENDER_PINE = Path(__file__).resolve().parent.parent / "pine" / "mnq_1h_4h_defender.pine"


def _pine() -> str:
    return PINE.read_text()


def _defender_pine() -> str:
    return DEFENDER_PINE.read_text()


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


def test_manual_pine_muted_state_quiets_loud_visuals() -> None:
    source = _pine()

    # The loud manual-alert kit renders only when armed (Candidate status).
    assert "longOk and alertsLive" in source                              # huge markers
    assert "showSignalFlash and alertVisual and alertsLive" in source     # flash
    assert "showPinstripe and alertVisual and alertsLive" in source       # pinstripe
    assert "showCallouts and alertsLive" in source                        # callouts
    assert "showLevels and alertsLive" in source                          # level rays
    # Muted state still shows small neutral study markers.
    assert "Muted study marker (long)" in source
    assert "Muted study marker (short)" in source
    # Pinstripe and callout are single-instance managed (no accumulation).
    assert "box.delete(alertStripe)" in source
    assert "alertStripe := box.new(" in source
    assert "label.delete(lastCallout)" in source
    assert "lastCallout := label.new(" in source


def test_manual_pine_dashboard_is_compact_and_honest() -> None:
    source = _pine()

    assert 'input.string("Middle Right", "Pos"' in source
    assert 'input.int(42, "Dash opacity"' in source
    assert "Signal Status" in source
    assert "HTF Filter" in source
    assert '"OFF"' in source
    assert "Active Signal" in source
    assert "KILLED" in source
    assert "CANDIDATE" in source


def test_defender_pine_uses_confirmed_4h_filter_and_1h_gate() -> None:
    source = _defender_pine()

    assert "PearlAlgo MNQ 1H/4H Defender - Research" in source
    assert "request.security" in source
    assert "lookahead=barmerge.lookahead_off" in source
    assert "close[1]" in source
    assert "timeframe.multiplier == 60" in source
    assert 'input.string("Research - alerts muted"' in source
    assert "alertsLive = signalStatus ==" in source


def test_defender_pine_has_breakout_pullback_and_guardrails() -> None:
    source = _defender_pine()

    assert "longBreakout" in source
    assert "longPullback" in source
    assert "allowShorts" in source
    assert 'input.bool(false, "Allow shorts"' in source
    assert "maxTradesDay" in source
    assert "RTH only" in source
    assert '"strat":"mnq-1h-4h-defender"' in source
