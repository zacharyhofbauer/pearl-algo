from __future__ import annotations

from pathlib import Path


PINE = Path(__file__).resolve().parent.parent / "pine" / "mnq_rth_long_bias.pine"
DEFENDER_PINE = Path(__file__).resolve().parent.parent / "pine" / "mnq_1h_4h_defender.pine"
HOURLY_PINE = Path(__file__).resolve().parent.parent / "pine" / "mnq_hourly.pine"
CRYPTO_V4_PINE = Path(__file__).resolve().parent.parent / "pine" / "pearl_algo_crypto" / "pearl_algo_crypto_v4.pine"


def _pine() -> str:
    return PINE.read_text()


def _defender_pine() -> str:
    return DEFENDER_PINE.read_text()


def _hourly_pine() -> str:
    return HOURLY_PINE.read_text()


def _crypto_v4_pine() -> str:
    return CRYPTO_V4_PINE.read_text()


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


def test_manual_pine_visuals_decoupled_from_alert_delivery() -> None:
    source = _pine()

    # The LOUD VISUAL kit is gated by visArmed (a display toggle), NOT by alert
    # delivery. forceArmed defaults ON so the chart looks armed out of the box.
    assert "visArmed = forceArmed or alertsLive" in source
    assert "Force armed visuals (full kit even when KILLED)" in source
    assert "longOk and visArmed" in source                                # markers
    assert "showSignalFlash and alertVisual and visArmed" in source       # flash
    assert "showPinstripe and alertVisual and visArmed" in source         # pinstripe
    assert "showCallouts and visArmed" in source                          # callouts
    assert "showLevels and visArmed" in source                            # level rays
    # When visuals are NOT armed, only tiny neutral study marks render.
    assert "longOk and not visArmed" in source
    assert "Muted study marker (long)" in source
    assert "Muted study marker (short)" in source
    # LOAD-BEARING HONESTY: real alert() DELIVERY stays gated by alertsLive, so a
    # KILLED signal never pings the phone even with the full armed visuals on.
    assert "if alertsLive" in source
    assert 'alert(f_msg("BUY"' in source
    # Pinstripe and callout are single-instance managed (no accumulation).
    assert "box.delete(alertStripe)" in source
    assert "alertStripe := box.new(" in source
    assert "label.delete(lastCallout)" in source
    assert "lastCallout := label.new(" in source


def test_manual_pine_dashboard_is_compact_and_honest() -> None:
    source = _pine()

    assert 'input.string("Middle Right", "Pos"' in source
    assert 'input.int(22, "Dash opacity"' in source
    assert "Signal Status" in source
    assert "HTF Filter" in source
    assert '"OFF"' in source
    assert "Active Signal" in source
    assert "KILLED" in source
    assert "CANDIDATE" in source


def test_crypto_v4_dashboard_is_compile_safe_and_repaints_last_bar() -> None:
    source = _crypto_v4_pine()

    assert "//@version=6" in source
    assert 'strategy("PEARL Algo Crypto v4"' in source
    assert "var table dash = table.new(f_pos(dashPosIn), 2, 18" in source
    assert "Show PEARL dashboard" in source
    assert "PEARL dashboard position" in source
    assert "PEARL dashboard size" in source
    assert 'input.string("Full", "PEARL dashboard size"' in source
    assert "if showDash and barstate.islast\n    table.clear(dash, 0, 0, 1, 17)" in source
    assert "text_size=dash" not in source
    assert "dashTxtSz" not in source
    assert "f_rowS" in source and "text_size=size.small" in source
    assert "f_rowT" in source and "text_size=size.tiny" in source
    assert source.count("f_rowB(") >= 6


def test_pine_scripts_are_v6() -> None:
    # Both scripts pin margin_long/short = 0 explicitly, so the v5->v6 default
    # margin change (0 -> 100) does not alter fills; the version bump is byte-safe.
    assert "//@version=6" in _pine()
    assert "//@version=6" in _defender_pine()
    assert "margin_long = 0, margin_short = 0" in _pine()
    assert "margin_long=0, margin_short=0" in _defender_pine()


def test_robustness_sweep_is_a_disconfirmation_tool_not_an_optimizer() -> None:
    source = _pine()

    # Default OFF, and explicitly framed as a diagnostic — never a setting picker.
    assert 'input.bool(false, "Show robustness sweep' in source
    assert "diagnostic, not an optimizer" in source
    # Ordered by the swept axis (shape view), NOT ranked best-on-top.
    assert "ORDERED BY THE SWEPT AXIS" in source
    # Numbers are RELATIVE, never mistaken for the honest Strategy Tester.
    assert "RELATIVE" in source
    assert "not be read as real P&L" in source
    # Live setting stays frozen/highlighted; the in-sample peak is flagged DO-NOT-TRADE.
    assert "FROZEN" in source
    assert "DO NOT TRADE" in source
    # Shape verdict, not an auto-pick.
    assert '"PLATEAU"' in source
    assert '"SPIKE"' in source
    assert '"DEAD"' in source
    # Runs only inside the dev window so it never spends the held-out slice.
    assert "sweepActive = showSweep and ordersOk" in source
    # It is a self-contained ARRAY backtest with manual recursive EMAs — it cannot
    # use strategy.entry (one equity curve), so this must never become a real optimizer.
    assert "array.new<float>(nSens" in source
    assert "2.0 / (sLen + 1)" in source
    assert 'input.int(50, "Warmup bars"' in source
    assert "Potential Ratio" in source


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


def test_hourly_pine_is_v6_premium_and_any_timeframe() -> None:
    source = _hourly_pine()

    # v6 + the byte-safe margin pin.
    assert "//@version=6" in source
    assert 'strategy("PearlAlgo MNQ — Hourly v5"' in source
    assert "margin_long=0, margin_short=0" in source

    # ANY-TIMEFRAME: 1h exec + 4h regime both pulled via anti-repaint request.security,
    # signal fires once per confirmed exec bar regardless of chart timeframe.
    assert "ANY CHART TIMEFRAME" in source
    assert source.count("request.security") >= 4
    assert source.count("lookahead=barmerge.lookahead_off") >= 2
    assert "newExecBar = ta.change(time(execTf))" in source

    # Confluence cockpit: external data points pulled in Pine (graceful degradation),
    # display-only by default; the entry-gate filter is OFF by default (no fill change).
    assert "USI:TICK" in source
    assert "CBOE:VIX" in source
    assert "CME_MINI:ES1!" in source
    assert "ignore_invalid_symbol=true" in source
    assert "Confluence" in source
    assert 'input.bool(false, "Require confluence' in source
    assert "confLongOk" in source

    # Prop-firm risk engine: buffer-based sizing + partials + breakeven + session/news
    # halts. Defaults OFF (inert: base 1-contract bracket reproduces prior fills).
    assert 'input.bool(false, "Enable risk engine"' in source
    assert "Trailing-DD buffer" in source
    assert "sizedQty" in source
    assert "qtyUsed     = riskEngine ? sizedQty : contracts" in source
    assert "qty=qtyUsed" in source
    assert "qty_percent=50" in source                 # partial at +1R
    assert "beHit" in source                          # sticky breakeven
    assert "sessionOk" in source                      # midday/news halts (inert when off)
    assert "if not riskEngine" in source              # off => original bracket

    # Phantom Flow visual layer: two-sided sells (decoupled study vs trade), market
    # structure (BOS/CHoCH), diamonds, power gauge, ribbon. All descriptive, not wired
    # to orders (only longSig/shortSig place trades).
    assert "shortSigStudy" in source                                  # display-only short
    assert "shortSig      = allowShorts and shortSigStudy" in source  # tradeable short gated
    assert "ta.pivothigh(high, pivLeft, pivRight)" in source          # market structure
    assert '"CHoCH"' in source and '"BOS"' in source
    assert "array<line>" in source                                    # FIFO managed drawings
    assert "shape.diamond" in source                                  # confirmation diamonds
    assert "buyPower" in source and "powIsBuy" in source              # power gauge
    assert "Multi-band ribbon" in source

    # Final polish: PEARL layer forced IN FRONT of candles (transparent, non-blocking);
    # confirmation diamonds OFF by default ("the dots" removed). force_overlay is valid on
    # plot/plotshape/line/label but NOT on fill() — fills must ride their plots' z-order.
    assert "force_overlay=true" in source
    assert 'input.bool(false, "Confirmation diamonds' in source
    # Buy/Sell are full two-sided signals with DISTINCT colors (outside the cloud/
    # structure/brand palette) so they pop off everything else.
    assert 'input.bool(true, "Allow shorts' in source                 # Sell fully works
    assert 'input.color(#2979ff, "Buy signal"' in source              # distinct blue
    assert 'input.color(#ff2d9b, "Sell signal"' in source             # distinct magenta
    assert "color.new(colBuy, 0),  text=\"Buy\"" in source
    assert "color.new(colSell, 0), text=\"Sell\"" in source
    assert "fill(pF, pS" in source and "force_overlay=true)" not in source.split("fill(pF")[1].split("\n")[0]

    # PREMIUM, CLUTTER-FREE: corner dashboard is the only home for trade detail — NO
    # on-price callout labels/boxes at all; markers are small glyphs; gradient cloud;
    # VWAP line broken at the session reset (no vertical jump).
    assert "table.new(f_pos(dashPosIn)" in source
    assert "box.new" not in source            # no over-candle boxes burying price
    # Market-structure labels/lines are used now, but MUST be FIFO-managed (capped,
    # oldest recycled) so they never accumulate or hit the drawing caps.
    assert "line.delete(array.shift(msLines))" in source
    assert "label.delete(array.shift(msLabels))" in source
    assert "size=size.small" in source
    assert "BUY\\nMNQ" not in source          # no multiline marker text
    assert "Trend cloud" in source                                  # cloud is the primary trend cue
    assert 'input.bool(false, "Color candles by trend' in source    # candles stay plain by default
    assert "not newSession ? rthVwap : na" in source

    # Clean settings dropdowns (input.string + switch — enum tripped the v6 translator)
    # and the cyan brand.
    assert 'input.string("Research — alerts muted"' in source
    assert 'input.string("Top Right", "Dashboard position"' in source
    assert "enum " not in source          # enum syntax failed to translate — must stay out
    assert 'input.color(#00e5ff, "Brand"' in source

    # HONESTY: alerts gated by status (muted research default), dev-window Tester gate,
    # MFF + RTH discipline preserved.
    assert 'sigStatusIn == "Candidate — alerts on"' in source
    assert "ordersOk    = not useBtWindow or" in source
    assert "if alertsLive" in source
    assert 'alert(f_msg("BUY"' in source
    assert "Max MNQ (MFF)" in source
    assert 'strategy.close_all("RTH end")' in source
