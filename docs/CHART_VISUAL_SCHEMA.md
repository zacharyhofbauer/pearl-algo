# Chart Visual Schema & Trust Contracts

**Status**: Authoritative reference for chart visual semantics  
**Last Updated**: 2026-01-27  
**Source of Truth**: `src/pearlalgo/market_agent/chart_generator.py`

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
| Background | `#0b0f17` | (11, 15, 23) | Dark canvas — reduces eye strain |
| Grid | `#242a33` | (36, 42, 51) | Subtle structure — doesn't compete with data |
| Text Primary | `#e5e7ef` | (229, 231, 239) | High-contrast labels — always readable |
| Text Secondary | `#9aa3b2` | (154, 163, 178) | Subdued labels — contextual info |

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
| MA[0] | `#00bcd4` | First MA (EMA9) — cyan (distinct from VWAP) |
| MA[1] | `#2196f3` | Second MA (EMA20) — blue |
| MA[2] | `#9c27b0` | Third MA (EMA50) — purple |
| MA[3] | `#f44336` | Fourth MA (EMA200) — red |
| RSI | `#b388ff` | RSI line in sub-panel — light purple |
| RSI Signal | `#f6c453` | RSI signal/MA line — warm yellow |

**Contract**: Each EMA has a unique color for clear visual distinction. Default periods: [9, 20, 50, 200]. Colors: Cyan (fast) → Blue → Purple → Red (slow). Changing the order changes visual meaning.

### TBT Trendline Colors (Configurable)

| Element | Hex | Constant | Usage |
|---------|-----|----------|-------|
| TBT Resistance | `#ffc107` | `tbt_resistance_color` | Amber/yellow resistance trendline |
| TBT Support | `#00e676` | `tbt_support_color` | Light green support trendline |

**Contract**: Trendlines are dashed by default (`tbt_line_style: "--"`). Colors are configurable but should remain distinct from indicator colors.

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

#### Trade Entry/Exit Markers (Entry/Exit Charts)

| Marker | Size | Color | Usage |
|--------|------|-------|-------|
| `^` (up triangle) | 300 | `#26a69a` (green) | Long signal entry point |
| `v` (down triangle) | 300 | `#ef5350` (red) | Short signal entry point |

**Contract**: Triangles point in trade direction. Placed at/near candle extremes.

#### Dashboard Trade Markers (Outcome-Colored)

On dashboard charts, historical trades are overlaid with outcome-colored markers:

| Marker | Color | Meaning |
|--------|-------|---------|
| `^` (up triangle) | `#26a69a` (green) | Long entry, winning trade |
| `^` (up triangle) | `#ef5350` (red) | Long entry, losing trade |
| `^` (up triangle) | `#26a69a` (light) | Long entry, open/unknown outcome |
| `v` (down triangle) | `#26a69a` (green) | Short entry, winning trade |
| `v` (down triangle) | `#ef5350` (red) | Short entry, losing trade |
| `v` (down triangle) | `#ef5350` (light) | Short entry, open/unknown outcome |
| `o` (circle) | `#26a69a` / `#ef5350` / gray | Exit point (colored by outcome) |

**Contract**: Marker SHAPE indicates direction (up=long, down=short). Marker COLOR indicates outcome (green=win, red=loss).

#### Dashboard Trade Paths (Telegram Profile)

For Telegram/mobile dashboard charts, recent trades are additionally visualized with a **paired entry→exit path**:

- A thin line connects each trade’s entry to its exit
- **Color indicates outcome**: green = win, red = loss, gray = unknown/open
- The path is capped to a small number of recent trades to avoid clutter

**Contract**: The trade path is informational and must never obscure candles (light alpha, behind text labels).

#### Chart Key (Dashboard)

Telegram dashboard charts include a compact **Chart Key** overlay that summarizes:

- Key line types (VWAP/EMA) — color swatches are in the top-right legend
- RSI line + signal (when enabled)
- Session shading and zone overlays
- Trade overlay semantics (markers, colors, paths)

**Contract**: Keep the chart key concise and non-overlapping with price data.

#### EMA Crossover Markers (Dashboard Only)

Dashboard charts include EMA 9/20 crossover markers with **distinct colors** to avoid confusion with trade markers:

| Marker | Color | Hex | Meaning |
|--------|-------|-----|---------|
| `^` (up triangle) | Cyan | `#00bcd4` | Bullish crossover (EMA9 > EMA20) |
| `v` (down triangle) | Pink | `#e91e63` | Bearish crossover (EMA9 < EMA20) |

**WARNING - Semantic Ambiguity Risk**: EMA crossover markers use the same SHAPES (`^`/`v`) as trade markers but DIFFERENT COLORS (cyan/pink vs green/red). Traders must rely on color to distinguish indicator signals from trade markers.

**Contract**: EMA crossover colors (cyan/pink) must NEVER match trade marker colors (green/red).

**Telegram Profile Note**: Telegram dashboard exports disable EMA crossover markers by default to reduce marker ambiguity on mobile.

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

Labels closer than `min_label_spacing_pts` (10 points default) are collision-detected.

**Desktop Mode**: Lower-priority labels may be dropped to prevent visual clutter.

**Telegram/Mobile Mode**: Collision-free stacking with leader lines:
- Overlapping labels are shifted vertically (stacked)
- A subtle leader line connects the shifted label back to its true price
- Dynamic max label count based on available axis height
- Labels clamped to stay within visible (ymin, ymax) range

### Hybrid Label Policy (Telegram)

For Telegram charts, a hybrid labeling policy reduces clutter while preserving key information:

| Label Kind | Behavior | Rationale |
|------------|----------|-----------|
| `trade` | Always labeled | Entry/Stop/Target are critical |
| `key_level` | Always labeled | PDH, DO, RTH Open, etc. provide context |
| `vwap` | **No label** (line only) | VWAP visible on chart; label adds clutter |

**Contract**: VWAP lines/bands are still drawn (visible on chart); only the right-side text labels are filtered out.

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

### Telegram Unified Dashboard (Trade Recap)

```
┌─────────────────────────────────────────────────────┐
│  Price Panel (ratio: 9.0)                           │
│  - Candlesticks, MAs, VWAP, zones, levels           │
│  - Right labels                                     │
├─────────────────────────────────────────────────────┤
│  Volume Panel (ratio: 1.5)                          │
├─────────────────────────────────────────────────────┤
│  Trade Recap Panel (ratio: 1.0)                     │
│  - Equity curve + drawdown + summary stats          │
├─────────────────────────────────────────────────────┤
│  RSI Panel (ratio: 1.0) [optional]                  │
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

- Session name (top line)
- Range in ticks and session average price (second line, comma-separated)
- Open/Close levels (dashed lines within session span)

**Format**: `"SessionName\nRange: X, Avg: Y,YYY.YY"` (controlled by `show_session_range_stats`)

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

### Visual Regression Tests

All chart types have dedicated visual regression tests with baseline images:

| Chart Type | Test File | Baseline Image | Tolerance |
|------------|-----------|----------------|-----------|
| Dashboard | `tests/test_dashboard_chart_visual_regression.py` | `dashboard_baseline.png` | 2.0 px / 1% |
| Mobile Dashboard | `tests/test_mobile_chart_visual_regression.py` | `mobile_dashboard_baseline.png` | 2.5 px / 2% |
| On-Demand (12h) | `tests/test_on_demand_chart_visual_regression.py` | `on_demand_chart_12h_baseline.png` | 2.0 px / 1% |
| Entry Chart | `tests/test_entry_exit_chart_visual_regression.py` | `entry_baseline.png` | 2.0 px / 1% |
| Exit Chart | `tests/test_entry_exit_chart_visual_regression.py` | `exit_baseline.png` | 2.0 px / 1% |
| Backtest Chart | `tests/test_backtest_chart_visual_regression.py` | `backtest_baseline.png` | 2.0 px / 1% |

All baselines are located in: `tests/fixtures/charts/`

### Shared Visual Regression Utilities

Common utilities for all visual regression tests are centralized in:
- `tests/fixtures/visual_regression_utils.py`

This module provides:
- `validate_png_file()` - PNG header and integrity validation
- `load_image_as_array()` - Image loading with PIL/matplotlib fallback
- `compare_images()` - Pixel-wise comparison with tolerance
- `save_diff_artifact()` - Diff visualization for debugging
- Standard tolerance constants (`DEFAULT_PIXEL_TOLERANCE`, `MOBILE_PIXEL_TOLERANCE`, etc.)

### Semantic Contract Tests (Non-Rendering)

Fast unit tests that verify visual contracts without rendering:
- File: `tests/test_chart_semantic_contracts.py`

Tests include:
- Color constant values (candle, signal, entry, VWAP, MA colors)
- Z-order hierarchy (session < zones < lines < candles < labels)
- Alpha caps (zones transparent enough to see through)
- Font size bounds (readable range)
- Marker color distinctness (trade vs EMA crossover)
- `_merge_levels` anchor-price contract
- Priority hierarchy for right-side labels
- ChartConfig default values

### Cross-Timeframe Consistency Tests

- File: `tests/test_cross_timeframe_chart_consistency.py`

Verifies that the same signal looks consistent across 1m, 5m, and 15m timeframes.

### Edge Case Stress Tests

- File: `tests/test_chart_edge_cases.py`

Tests chart behavior under extreme conditions:
- High volatility data
- Data gaps (missing bars)
- Zero/minimal volume
- Extreme price levels

### Determinism Hooks

- `title_time` parameter for fixed timestamps in titles
- `tests/fixtures/deterministic_data.py` provides reproducible OHLCV
- `SEED = 42`, `BASE_TIMESTAMP = 2024-12-20 00:00:00 UTC`

### Baseline Update Process

Only update baselines after intentional visual changes with explicit approval,
then re-run the visual regression tests to confirm.

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

### Telegram Render Profile

For Telegram dashboard charts, a special render profile is automatically applied for mobile-optimized, no-overlap visuals:

**Automatically Enabled**:
- `mobile_mode=True` (all mobile optimizations)
- `compact_labels=True` (reduced label clutter)
- `show_session_range_stats=False` (session names only, no Range/Avg text)
- `max_right_labels=6` (fewer right-side labels)
- `ylabel=""` (removes "Price ($)" axis label to avoid collision with right labels)

**Telegram-Only Dashboard Enhancements (Service-Controlled Render Params)**:
- Template:
  - Unified template size: **12×9 @ 200dpi** (4:3 middle ground)
- Trade clarity:
  - EMA crossover markers **disabled** (reduces arrow ambiguity with trades)
  - Trade overlay defaults to **path-only detailed** (arrowheads + fade-by-age + last P&L label)
  - Per-trade letters **disabled** (reduces clutter)
  - Compact overlay legend **enabled** (decodes trade overlays at a glance)
  - Safe cap: `trade_markers_max=12`
- VWAP bands **hidden** (keep main VWAP line only)
- Panel layout:
  - **Trade Recap panel replaces Pressure** (equity + drawdown + summary stats)
- Pixel utilization / preview stability:
  - Reduced PNG save padding (less dead space around the chart)
  - Slightly reduced top headroom (more price area while keeping title readable)
  - Optional lossless PNG optimization (smaller payload for faster preview load)

**Hybrid Label Policy (No VWAP Right Labels)**:
- VWAP lines and bands are still drawn on the chart
- VWAP right-side text labels are hidden (filtered by `kind="vwap"`)
- Key levels (Entry, Stop, Target, PDH, DO, etc.) are always labeled
- Reduces visual clutter while preserving important price reference lines

**Collision-Free Label Stacking**:
- Labels that would overlap are automatically stacked vertically
- Subtle leader lines connect shifted labels back to their true price level
- Dynamic max label count based on available axis height
- Labels clamped to stay within visible y-range

**Session Labels**:
- Name-only (no "Range: X, Avg: Y" stats)
- Positioned 8% above ymin (vs 3% desktop) to avoid RR-box overlap

### Mobile Mode (Consolidated)

Enable all mobile-friendly optimizations with a single flag:

```python
config = ChartConfig(
    mobile_mode=True,  # Enables all mobile optimizations
)
```

This automatically sets:
- `mobile_enhanced_fonts=True` (larger fonts)
- `rr_box_font_size=10` (larger RR box labels)
- `compact_labels=True` (reduced clutter)
- `max_right_labels=6` (fewer labels)
- `right_label_merge_ticks=6` (more aggressive merging)

### Mobile Readability Enhancement (P7)

Enable larger RR box fonts for mobile viewing (without full mobile mode):

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

### Trade Recap Panel (Telegram)

Replace the Pressure panel with a Trade Recap panel (equity + drawdown + stats):

```python
config = ChartConfig(
    show_trade_recap_panel=True,
    show_pressure_panel=False,
)
```

### Power Meter Display

Show buy/sell power ratio in top-left corner (independent of power channel zones):

```python
config = ChartConfig(
    show_power_readout=True,   # Show "Power X/Y" in top-left (default: True)
    show_power_channel=False,  # Can hide zones while keeping readout
)
```

**Contract**: Power readout shows buy/sell candle count from the lookback period. Format: "Power {buy}/{sell}".

### VWAP Band Fills

Enable semi-transparent fills between VWAP line and ±1σ bands:

```python
config = ChartConfig(
    vwap_fill_bands=True,  # Default: False
)
```

**Contract**: Fills use VWAP_COLOR with alpha 0.08, placed at ZORDER_ZONES (behind candles).

### Indicator Legend

Show/hide the indicator legend in top-right corner:

```python
config = ChartConfig(
    show_legend=True,  # Default: True
)
```

**Contract**: Legend shows VWAP first, then EMAs in configured order. Placed in upper-right to avoid collision with power readout (upper-left).

### TBT Trendline Customization

Customize TBT trendline appearance:

```python
config = ChartConfig(
    tbt_resistance_color="#ffc107",  # Amber/yellow (default)
    tbt_support_color="#00e676",     # Light green (default)
    tbt_line_style="--",             # Dashed (default)
    tbt_line_width=1.8,              # Line width (default)
)
```

**Note**: All optional features are disabled by default (except show_legend and show_power_readout) to preserve baseline stability and existing visual contracts.

---

## Optional Render Manifest (Semantic Regression)

For semantic regression checks that don't depend on pixel-level comparison, charts can emit a JSON manifest capturing render inputs and drawn elements.

### Usage

```python
from pathlib import Path

chart_path = generator.generate_dashboard_chart(
    data=data,
    symbol="MNQ",
    timeframe="5m",
    manifest_path=Path("/tmp/chart_manifest.json"),  # Optional
)
# Produces both chart.png and chart_manifest.json
```

### Manifest Schema

```json
{
  "chart_type": "dashboard",
  "symbol": "MNQ",
  "timeframe": "5m",
  "lookback_bars": 288,
  "figsize": [16, 7],
  "dpi": 150,
  "render_mode": "telegram",
  "render_timestamp": "2026-01-21T12:00:00+00:00",
  "title_time": "12:00 UTC",
  "num_candles": 288,
  "price_range": [24900.0, 25100.0],
  "indicators": ["EMA9", "EMA20", "EMA50", "VWAP", "RSI"],
  "sessions": ["Tokyo", "London", "New York"],
  "config_snapshot": {
    "show_sessions": true,
    "show_key_levels": true,
    "show_vwap": true,
    "show_ma": true,
    "show_rsi": true,
    "show_pressure": true
  }
}
```

**Note**: The manifest is OFF by default. Enable only when needed for debugging or semantic regression checks.

---

## Document History

| Date | Change | Author |
|------|--------|--------|
| 2026-01-27 | Added Telegram render profile with collision-free label stacking and leader lines | AI Agent |
| 2026-01-27 | Implemented hybrid label policy: no VWAP right labels for Telegram (lines still drawn) | AI Agent |
| 2026-01-27 | Removed ylabel='Price ($)' for Telegram mode to avoid collision with right labels | AI Agent |
| 2026-01-27 | Added kind tag to level candidates (trade, vwap, key_level) for filtering | AI Agent |
| 2026-01-27 | Session labels repositioned higher (8% vs 3%) in mobile mode to avoid RR-box overlap | AI Agent |
| 2026-01-27 | Changed EMA9 color to cyan (#00bcd4) for unique visual distinction from VWAP | AI Agent |
| 2026-01-27 | Improved legend layout with ncol=2, better positioning, and tighter spacing | AI Agent |
| 2026-01-27 | Increased min_label_spacing_pts from 8.0 to 10.0 for better readability | AI Agent |
| 2026-01-27 | Added mobile_mode consolidated flag for all mobile optimizations | AI Agent |
| 2026-01-27 | Added show_power_readout option (independent of power channel zones) | AI Agent |
| 2026-01-27 | Added vwap_fill_bands option for VWAP band fills | AI Agent |
| 2026-01-27 | Added show_legend config option | AI Agent |
| 2026-01-27 | Added configurable TBT trendline colors (tbt_resistance_color, tbt_support_color) | AI Agent |
| 2026-01-27 | Enhanced session labels with Range/Avg stats (show_session_range_stats) | AI Agent |
| 2026-01-27 | Expanded MA_COLORS to 4 colors, default ma_periods now [9, 20, 50, 200] | AI Agent |
| 2026-01-21 | Added optional render manifest for semantic regression | AI Agent |
| 2026-01-21 | Added comprehensive baseline/test/generator inventory | AI Agent |
| 2026-01-21 | Documented EMA crossover markers (cyan/pink) with semantic ambiguity warning | AI Agent |
| 2026-01-21 | Documented dashboard trade markers (outcome-colored) | AI Agent |
| 2026-01-21 | Added reference to semantic contract tests | AI Agent |
| 2026-01-21 | Added shared visual regression utilities documentation | AI Agent |
| 2025-12-31 | Added optional config: mobile_enhanced_fonts, compact_labels | AI Agent |
| 2025-12-31 | Added font size and alpha constants for code clarity | AI Agent |
| 2025-12-31 | Added z-order comments explaining layering rationale | AI Agent |
| 2025-12-29 | Initial visual schema documentation | AI Agent |


