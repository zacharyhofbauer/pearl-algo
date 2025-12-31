# Chart Visual Schema & Trust Contracts

**Status**: Authoritative reference for chart visual semantics  
**Last Updated**: 2025-12-29  
**Source of Truth**: `src/pearlalgo/nq_agent/chart_generator.py`

---

## Purpose

This document defines the **visual contracts** that traders rely on when reading charts.
Any change to these elements requires explicit approval and side-by-side validation.

A great chart feels boring — because the trader never has to wonder whether it changed.

---

## Color Semantics

### Core Palette (TradingView Dark Theme)

| Element | Hex | RGB | Meaning |
|---------|-----|-----|---------|
| Background | `#0e1013` | (14, 16, 19) | Dark canvas — reduces eye strain |
| Grid | `#1e2127` | (30, 33, 39) | Subtle structure — doesn't compete with data |
| Text Primary | `#d1d4dc` | (209, 212, 220) | High-contrast labels — always readable |
| Text Secondary | `#787b86` | (120, 123, 134) | Subdued labels — contextual info |

### Candle Colors

| Element | Hex | Meaning |
|---------|-----|---------|
| Candle Up | `#26a69a` | Teal-green — bullish close > open |
| Candle Down | `#ef5350` | Red — bearish close < open |

**Contract**: These colors match TradingView defaults. Traders have muscle memory for green=up, red=down.

### Signal Colors

| Element | Hex | Usage |
|---------|-----|-------|
| Signal Long | `#26a69a` | Long entry markers, take-profit zones |
| Signal Short | `#ef5350` | Short entry markers, stop-loss zones |
| Entry | `#2962ff` | Entry price line — distinct blue |

**Contract**: Entry line is always blue to stand out from directional colors.

### Indicator Colors

| Element | Hex | Usage |
|---------|-----|-------|
| VWAP | `#2196f3` | VWAP line and bands — blue family |
| MA[0] | `#2196f3` | First MA (e.g., MA20) — blue |
| MA[1] | `#9c27b0` | Second MA (e.g., MA50) — purple |
| MA[2] | `#f44336` | Third MA (e.g., MA200) — red |
| RSI | `#b388ff` | RSI line in sub-panel — light purple |

**Contract**: MA colors are assigned in order. Changing the order changes visual meaning.

### Zone Colors (HUD Overlays)

| Element | Hex | Constant | Alpha | Usage |
|---------|-----|----------|-------|-------|
| Supply Zone | `#2157f3` | `SUPPLY_ZONE_COLOR` | 0.18 | LuxAlgo-style supply area (resistance) |
| Demand Zone | `#ff5d00` | `DEMAND_ZONE_COLOR` | 0.18 | LuxAlgo-style demand area (support) |
| Power Channel Resistance | `#ff00ff` | `POWER_CHANNEL_RESISTANCE` | 0.10 | ChartPrime-style upper channel |
| Power Channel Support | `#00ff00` | `POWER_CHANNEL_SUPPORT` | 0.10 | ChartPrime-style lower channel |
| RR Box Profit | `#26a69a` | `SIGNAL_LONG` | 0.20-0.22 | Risk/reward profit zone |
| RR Box Risk | `#ef5350` | `SIGNAL_SHORT` | 0.20-0.22 | Risk/reward loss zone |

**Contract**: Zones use low alpha to avoid obscuring candles. Zone shading is informational, not directive.

---

## Z-Order (Layering Rules)

Elements are layered from back to front. Lower z-order = further back.

| Z-Order | Constant | Element | Rationale |
|---------|----------|---------|-----------|
| 0 | `ZORDER_SESSION_SHADING` | Session backgrounds | Ambient context — never obscures data |
| 1 | `ZORDER_ZONES` | Supply/demand, power channel, RR boxes | Structural zones — behind price action |
| 2 | `ZORDER_LEVEL_LINES` | Key levels, VWAP bands, S/R lines | Reference lines — visible but not dominant |
| 3 | `ZORDER_CANDLES` | Candlesticks (mplfinance default) | Primary data — always visible |
| 4 | `ZORDER_TEXT_LABELS` | Right labels, session names, RR text | Critical info — never hidden |

**Contract**: Candles are always visible. Labels are always on top. Session shading never obscures candles.

---

## Shape Semantics

### Lines

| Style | Width | Alpha | Usage |
|-------|-------|-------|-------|
| Solid `-` | 1.8-2.5 | 0.9 | Entry price, primary levels |
| Dashed `--` | 1.0-2.0 | 0.7 | Stop loss, take profit, secondary levels |
| Dotted `:` | 1.0-1.2 | 0.45-0.55 | Support/resistance, session averages |

**Contract**: Solid = actionable level. Dashed = reference. Dotted = contextual.

### Markers

| Marker | Size | Usage |
|--------|------|-------|
| `^` (up triangle) | 300 | Long signal entry point |
| `v` (down triangle) | 300 | Short signal entry point |

**Contract**: Triangles point in trade direction. Placed at/near candle extremes.

### Boxes/Zones

| Element | Shape | Meaning |
|---------|-------|---------|
| RR Box | Filled rectangle | Risk/reward visualization to right of last bar |
| Session Shading | Vertical span | Trading session context (Tokyo/London/NY) |
| Supply/Demand | Horizontal span | Price zones from volume analysis |
| Power Channel | Horizontal bands | Dynamic support/resistance areas |

---

## Right-Side Labels

### Merge Logic

Labels within `right_label_merge_ticks` (default: 4 ticks = 1.0 points) are merged.
The merged label uses the **top-priority level's exact price** (not averaged).

### Priority Hierarchy

| Priority | Label Type | Color |
|----------|------------|-------|
| 100 | Entry | Blue `#2962ff` |
| 95 | Stop / Target | Red/Green |
| 90 | Exit | Blue (MA color) |
| 60 | Daily Open (DO) | Blue |
| 60 | VWAP | Blue |
| 58 | PDH / PDL | Gray |
| 52 | PDM | Gray |
| 50 | RTH Open | Blue |
| 45 | RTH PDH/PDL | Gray |
| 40 | VWAP ±1 | Blue |
| 35 | POC | Gray |
| 30 | VAH/VAL, VWAP ±2 | Gray |
| 25 | Support/Resistance | Gray |

**Contract**: Trade-related labels (Entry/Stop/Target) always take priority over contextual levels.

### Collision Prevention

Labels closer than `min_label_spacing_pts` (8 points default) are de-duplicated.
Lower-priority labels are dropped to prevent visual clutter.

---

## Panel Layout

### Standard Dashboard Chart

```
┌─────────────────────────────────────────────────────┐
│  Price Panel (ratio: 6-7)                           │
│  - Candlesticks, MAs, VWAP, zones, levels           │
│  - Right labels                                     │
├─────────────────────────────────────────────────────┤
│  Volume Panel (ratio: 2)                            │
│  - Volume bars colored by candle direction          │
├─────────────────────────────────────────────────────┤
│  Pressure Panel (ratio: 1.6-2) [optional]           │
│  - Signed volume histogram (+/- by direction)       │
├─────────────────────────────────────────────────────┤
│  RSI Panel (ratio: 1.6-2) [optional]                │
│  - RSI line with 30/50/70 reference lines           │
└─────────────────────────────────────────────────────┘
```

### Entry/Exit Charts

Same structure as dashboard, plus:
- RR box extends to the right of last candle
- Entry/Stop/TP lines span full chart width

---

## Session Overlays

### Session Definitions

| Session | Color | Typical Hours (ET) |
|---------|-------|-------------------|
| Tokyo | Varies | 19:00-02:00 |
| London | Varies | 03:00-08:00 |
| New York | Varies | 08:00-17:00 |

**Contract**: Session shading is background-only (alpha 0.08). Session names and metrics are anchored at `ymin + 3%` for consistent placement.

### Session Metrics Displayed

- Range in ticks
- Session average price
- Open/Close levels (dashed lines within session span)

---

## Cross-Timeframe Consistency

### What Stays Stable

- Color meanings (green=up, red=down, blue=entry)
- Z-order layering
- Right-label format and priority
- RR box positioning (always right of last bar)

### What Adapts

- Candle width (adjusted by mplfinance for bar count)
- MA periods may be shorter on smaller timeframes
- Session shading may span different bar counts

**Contract**: A signal on 5m should look visually consistent with the same signal on 15m (same colors, same relative positions, same label formats).

---

## Implicit Trader Contracts (Do Not Violate)

1. **Green means profit/bullish, red means loss/bearish** — universal trading color convention.

2. **Entry line is always blue** — distinct from directional colors, always identifiable.

3. **Candles are never obscured** — all overlays use z-order < 3 or transparent fills.

4. **Right labels show actual prices** — merged labels use the exact anchor price, not interpolations.

5. **Same inputs produce identical outputs** — deterministic rendering for regression testing.

6. **Level lines reach the right edge** — horizontal levels extend to the right label area.

7. **RR box shows dollar amounts** — not just ticks or points, includes position-aware USD values.

8. **Session shading is ambient, not directive** — low alpha, never suggests trade action.

---

## Testing & Regression

### Visual Regression Test

- File: `tests/test_dashboard_chart_visual_regression.py`
- Baseline: `tests/fixtures/charts/dashboard_baseline.png`
- Tolerance: 2.0 mean pixel diff, 1% max differing pixels

### Determinism Hooks

- `title_time` parameter for fixed timestamps in titles
- `tests/fixtures/deterministic_data.py` provides reproducible OHLCV
- `SEED = 42`, `BASE_TIMESTAMP = 2024-12-20 00:00:00 UTC`

### Baseline Update Process

```bash
python3 scripts/testing/generate_dashboard_baseline.py
```

Only run after intentional visual changes with explicit approval.

---

## Change Classification (Required for All Chart Changes)

| Classification | Description | Approval |
|----------------|-------------|----------|
| No-op preservation | Explicit confirmation of no visual change | Auto |
| Safe visual refactor | Zero semantic change (e.g., code cleanup) | Auto |
| Optional enhancement | New feature behind toggle (default off) | Review |
| Experimental visualization | Not default, clearly labeled | Review |
| Semantic change | Changes color/shape meaning | **Explicit approval required** |

---

## Optional Configuration

### Mobile Readability Enhancement (P7)

Enable larger RR box fonts for mobile viewing:

```python
config = ChartConfig(
    mobile_enhanced_fonts=True,
    rr_box_font_size=10,  # Default 9pt, set to 10 for mobile
)
```

### Compact Label Mode (P6)

Reduce label clutter on range-bound days:

```python
config = ChartConfig(
    compact_labels=True,  # Reduces max_right_labels to 6, merge_ticks to 6
)
```

**Note**: These options are disabled by default to preserve baseline stability and existing visual contracts.

---

## Document History

| Date | Change | Author |
|------|--------|--------|
| 2025-12-31 | Added optional config: mobile_enhanced_fonts, compact_labels | AI Agent |
| 2025-12-31 | Added font size and alpha constants for code clarity | AI Agent |
| 2025-12-31 | Added z-order comments explaining layering rationale | AI Agent |
| 2025-12-29 | Initial visual schema documentation | AI Agent |


