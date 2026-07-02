from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BTC_PINE = ROOT / "pine" / "btc_trend_defender.pine"
BT_JSON = ROOT / "docs" / "audits" / "2026-07-01-btc-trend-defender-backtest.json"


def test_btc_trend_defender_is_muted_research_candidate() -> None:
    source = BTC_PINE.read_text()

    assert "//@version=6" in source
    assert 'strategy("PearlAlgo BTC - Trend Defender Research"' in source
    assert 'input.string("Research - alerts muted"' in source
    assert 'alertsLive = sigStatus == "Candidate - alerts on"' in source
    assert "if alertsLive" in source
    assert "strategy.entry" in source


def test_btc_trend_defender_defaults_match_research_artifact() -> None:
    source = BTC_PINE.read_text()

    assert 'input.int(100, "Donchian breakout"' in source
    assert 'input.bool(false, "Allow shorts"' in source
    assert 'input.float(8.0, "Chandelier stop x ATR"' in source
    assert 'input.float(10.0, "ADX min"' in source
    assert 'input.int(0, "Max bars in trade (0=off)"' in source
    assert "commission_type=strategy.commission.percent" in source
    assert "commission_value=0.06" in source


def test_btc_trend_defender_uses_confirmed_htf_requests() -> None:
    source = BTC_PINE.read_text()

    assert "request.security" in source
    assert "lookahead=barmerge.lookahead_on" in source
    assert "close[1]" in source
    assert "ta.ema(close, htfFastLen)[1]" in source
    assert "ta.ema(close, dailyLen)[1]" in source
    assert "_a[1]" in source


def test_btc_backtest_artifact_records_research_not_promotion() -> None:
    result = json.loads(BT_JSON.read_text())

    assert result["trades"] == 100
    assert result["profit_factor"] >= 1.3
    assert result["bootstrap_mean_pct_trade"]["ci95_pct"][0] < 0
    assert result["params"]["allow_shorts"] is False
    assert result["params"]["trail_atr"] == 8.0
