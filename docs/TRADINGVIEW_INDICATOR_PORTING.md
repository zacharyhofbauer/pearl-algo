# TradingView Indicator Scripts: How to Use Them Here

TradingView indicators are written in **Pine Script** and run inside TradingView. You generally **can’t “import” Pine directly into Python**.

You have two practical options:

## Option A (recommended): Port the Pine logic into a Python Indicator

This repo already has an indicator framework built for “Pine → Python” ports:
- Base interface: `src/pearlalgo/strategies/nq_intraday/indicators/base.py`
- Registry: `src/pearlalgo/strategies/nq_intraday/indicators/__init__.py`
- Existing examples:
  - `supply_demand_zones.py`
  - `power_channel.py`
  - `smart_money_divergence.py`

### Step-by-step

1. **Create a new indicator class**
   - Add a file: `src/pearlalgo/strategies/nq_intraday/indicators/<your_indicator>.py`
   - Implement `IndicatorBase.calculate()` and `IndicatorBase.as_features()`
   - (Optional) implement `generate_signal()` if you want it to emit rule-based signals.

2. **Register it**
   - Add it to `INDICATOR_REGISTRY` in `src/pearlalgo/strategies/nq_intraday/indicators/__init__.py`

3. **Enable/disable**
   - Indicators are loaded by the scanner and always contribute **features**.
   - To allow an indicator to emit **signals**, ensure the scanner is configured to generate them and your strategy signal gating allows those signal types.

### What I need from you to port accurately

For each TradingView script, paste:
- The full Pine source
- The chart timeframe(s) you use it on (1m/5m/etc)
- The market/session assumptions (NQ/MNQ, NY session only vs 24h)
- Which alerts/conditions you consider “entry” vs “exit”

## Option B: Keep Pine on TradingView and ingest alerts

If you don’t want to port code, you can:
- Run your Pine script on TradingView
- Fire alerts (webhook or message) when conditions trigger
- Ingest those alerts into this system as “external signals”

This keeps your Pine logic identical to what you see on TradingView, but requires:
- A reachable webhook endpoint (or another ingestion path)
- A small adapter in this repo to turn alerts into standard signal dicts

If you want Option B, tell me whether you prefer:
- Webhook (HTTP) ingestion
- Telegram-only ingestion
- File/queue ingestion

