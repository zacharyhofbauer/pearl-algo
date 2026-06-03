from __future__ import annotations

from pathlib import Path


PINE = Path(__file__).resolve().parent.parent / "pine" / "mnq_rth_long_bias.pine"


def _pine() -> str:
    return PINE.read_text()


def test_manual_pine_has_mobile_obvious_pinstripe_identity() -> None:
    source = _pine()

    assert "PearlAlgo PINSTRIPE MNQ — Manual v3" in source
    assert "showPinstripe" in source
    assert "Alert pinstripe" in source


def test_every_manual_alert_path_has_a_chart_visual() -> None:
    source = _pine()

    assert "dailyStopWillFire" in source
    assert "alertVisual = sigFired or dailyStopWillFire" in source
    assert "box.new(bar_index" in source
    assert "BUY MNQ" in source
    assert "SELL MNQ" in source
    assert "DAILY STOP" in source
    assert "Manual alert flash" in source
