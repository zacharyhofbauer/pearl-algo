## TradingView Pine references (source-of-truth)

This folder contains **verbatim Pine Script sources** you provided from your TradingView setup.

These files are **not executed by this repo** and are **not a dependency** at runtime. They are kept here as:

- a **visual reference** for the TradingView “HUD” styling we replicate in our `mplfinance` chart outputs
- a **logic reference** for how we compute/label sessions, zones, power/channel bands, and trendline targets in Python

### Files

- `TradingSessions.pine`: session shading/labels (Tokyo/London/New York) and session open/avg/close lines
- `SupplyDemandVisibleRange_LuxAlgo.pine`: visible-range supply/demand zones + avg/wavg + equilibrium
- `SRPowerChannel_ChartPrime.pine`: max/min window + ATR band “power channel” + buy/sell power counts
- `TrendlineBreakoutsWithTargets_ChartPrime.pine`: pivot-based trendlines + breakout detection + targets

### Implementation mapping (Python)

We mirror these behaviors in:

- `src/pearlalgo/…` computations attached to each signal under `hud_context`
- `src/pearlalgo/nq_agent/chart_generator.py` drawing (boxes/bands/labels/RR overlay) to match the screenshots

### TradingView Pine Sources (Reference Only)

This folder stores **verbatim Pine Script sources** you provided (or that you are licensed to share) as **reference artifacts** for the PearlAlgo project.

**Important**
- These scripts are **not executed** by this repo.
- They are used to **mirror behaviors + visuals** in our Python chart generation and signal context (the “TradingView-style HUD”).

### Files
- `TradingSessions.pine`: Session shading + session open/close + avg + range label logic.
- `SupplyDemandVisibleRange_LuxAlgo.pine`: Visible-range supply/demand zones with avg/wavg lines.
- `SRPowerChannel_ChartPrime.pine`: Support/Resistance “power channel” band + buy/sell power text.
- `TrendlineBreakoutsWithTargets_ChartPrime.pine`: Trendline breakouts and projected targets.


