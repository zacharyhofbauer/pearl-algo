# One-Shot Prompt: TradingView-Style Right Panels for PEARL Algo

**Purpose:** Hand this prompt to Claude Opus (or similar) to produce a complete, production-ready implementation of TradingView-style right panels that **push** the chart (not overlay), with zero follow-up.

**Before running:** Paste the full contents of the 6 files listed in `<existing_code>` into the corresponding `[PASTE: ...]` sections. The prompt is designed to work with your exact codebase.

---

```xml
<system>
You are an expert frontend engineer specializing in Next.js 14, React, TypeScript,
and CSS. You implement UI components that exactly match design specifications. You
output complete, production-ready files with no abbreviations, truncations, or
placeholder comments. Every CSS class referenced in JSX has a corresponding definition.
</system>

<context>
Project: PEARL Algo — production Next.js 14 trading dashboard at pearlalgo.io
Stack: Next.js 14 App Router, TypeScript, Zustand + persist, CSS (not Tailwind)
Architecture:
  - pearlalgo_web_app/ directory
  - DashboardLayout.tsx wraps the main layout (header, chart, panels, rightPanelContent)
  - DashboardPageInner.tsx is the main chart page, passes rightPanelContent to DashboardLayout
  - uiStore.ts has Zustand store with persist — activeRightPanel causes hydration mismatch
  - CSS: _right-panel.css, _tv-layout.css, tokens.css
  - The right panel currently uses position:absolute + transform:translateX (OVERLAY — wrong)
  - Data: agentState, recentSignals, candles from useDashboardData / useAgentStore
  - CandlestickChart uses autoSize:true (ResizeObserver built-in)

GOAL: Convert the right panel from OVERLAY to PUSH layout. When the panel opens, the chart
must SHRINK (flexbox reflow), not get covered. Match TradingView's dark theme exactly.
Fix the Zustand hydration mismatch so activeRightPanel never causes server/client mismatch.
</context>

<current_problem>
1. Right panel uses position:absolute + transform:translateX(100%) — it overlays the chart.
   TradingView PUSHES content: the chart area shrinks when the panel opens.
2. uiStore persists activeRightPanel — on hydration, localStorage has a value but server
   rendered null → "Extra attributes from server" / "Text content mismatch" errors.
3. Panel styling is close but not pixel-perfect TradingView (row heights, section headers,
   scrollbar, content fade during animation).
</current_problem>

<existing_code>

--- FILE: components/DashboardLayout.tsx ---
[PASTE: Full contents of DashboardLayout.tsx]

--- FILE: app/dashboard/DashboardPageInner.tsx (relevant section: rightPanelContent) ---
[PASTE: The rightPanelContent JSX block and how it's passed to DashboardLayout — lines ~560-575]

--- FILE: components/WatchlistPanel.tsx ---
[PASTE: Full contents of WatchlistPanel.tsx]

--- FILE: components/SystemLogsPanel.tsx ---
[PASTE: Full contents of SystemLogsPanel.tsx]

--- FILE: stores/uiStore.ts ---
[PASTE: Full contents of uiStore.ts]

--- FILE: styles/components/_right-panel.css ---
[PASTE: Full contents of _right-panel.css]

--- FILE: styles/layouts/_tv-layout.css ---
[PASTE: Full contents of _tv-layout.css]

</existing_code>

<task>
Implement TradingView-style right sidebar panels for the PEARL Algo dashboard.
This is a COMPLETE implementation — output every modified and new file in its entirety.
The panels must PUSH the chart content left (not overlay). Animate smoothly.
Match TradingView's dark theme aesthetic. Fix the Zustand hydration mismatch.
</task>

<requirements>

1. LAYOUT — Flexbox push (not overlay):
   - .tv-body already has display:flex. The structure is: [left sidebar 40px] [tv-main flex:1] [right sidebar 40px].
   - The right PANEL (content area) must be INSIDE the flex flow, not position:absolute.
   - NEW STRUCTURE: [left sidebar] [tv-main (chart + bottom panels)] [right sidebar icons] [right panel content].
   - The right panel content is a FLEX SIBLING of tv-main. When open: flex:0 0 320px, width:320px.
   When closed: width:0, overflow:hidden, flex:0 0 0.
   - tv-main gets flex:1 1 0 and min-width:0 so it shrinks when the panel opens.
   - CRITICAL: min-width:0 on tv-main (or its flex parent) — without it, flex items won't shrink below content size.

2. PANEL ANIMATION:
   - Use width transition: 0.3s cubic-bezier(0.4, 0, 0.2, 1).
   - Panel: width 320px when open, width 0 when closed. overflow:hidden.
   - Content inside panel: opacity fades in with transition-delay 0.12s when opening, 0s when closing.
   - Do NOT use transform:translateX — that only moves visually, doesn't affect layout.

3. WATCHLIST PANEL — TradingView spec:
   - Symbol row: ticker left, price right, change % far right. Row height 34px. Padding 0 12px.
   - Section headers: ALL-CAPS, 11px, font-weight 600, letter-spacing 0.5px, color #787B86.
   - Active row: background #363a45, border-left 2px solid #2962FF.
   - Hover row: background #2a2e39.
   - Green #26A69A for positive, red #EF5350 for negative.
   - font-variant-numeric: tabular-nums on all numeric displays.

4. SYMBOL DETAILS (if you add it): Large price 28px bold, exchange badges (#2a2e39 bg, 3px radius, 10px uppercase).

5. HYDRATION FIX:
   - Remove activeRightPanel from persist partialize. It must NOT be persisted.
   - Add skipHydration: true to the persist config.
   - Create StoreHydration.tsx: useEffect(() => { useUIStore.persist.rehydrate() }, []). Return null.
   - Add <StoreHydration /> in app/layout.tsx (inside body, after NavBar).
   - activeRightPanel always starts null on both server and client — no mismatch.

6. SCROLLBAR: 6px width, thumb #3d4150, track transparent, hover #565b6b. WebKit + Firefox.

7. CHART RESIZE: CandlestickChart uses autoSize:true. The chart container is inside tv-chart-area.
   When the right panel opens, tv-main shrinks → chart container shrinks → ResizeObserver fires.
   Verify the chart container is the direct resize target. If not, ensure the flex chain allows
   the chart div to shrink (min-width:0, min-height:0 where needed).

8. PANEL HEADER: 48px height, title 13px 600 uppercase, close button 28x28px, hover bg rgba(255,255,255,0.06).

9. RIGHT SIDEBAR: DOM order inside .tv-body: [tv-sidebar-left] [tv-main] [tv-right-panel] [tv-sidebar-right].
   The panel sits BETWEEN tv-main and the 40px icon strip. When closed: panel width 0 (invisible).
   When open: panel width 320px. Icons stay at 40px. Total right side: 320+40px open, 40px closed.

</requirements>

<css_specifications>
Use these EXACT values. Do not modify.

Color tokens:
  --bg-primary: #131722
  --bg-panel: #1e222d
  --bg-elevated: #2a2e39
  --bg-hover: #363a45
  --border-color: #434651
  --text-primary: #d1d4dc
  --text-secondary: #787B86
  --color-bullish: #26A69A
  --color-bearish: #EF5350
  --color-accent: #2962FF

Typography:
  font-family: -apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, Ubuntu, sans-serif
  All numeric: font-variant-numeric: tabular-nums

Layout — .tv-body children order:
  1. .tv-sidebar-left (flex: 0 0 40px)
  2. .tv-main (flex: 1 1 0; min-width: 0) — chart + bottom panels
  3. .tv-right-panel (flex: 0 0 auto; width: 320px or 0; transition width 0.3s cubic-bezier(0.4,0,0.2,1))
  4. .tv-sidebar-right (flex: 0 0 40px)

Panel:
  .tv-right-panel { width: 320px; overflow: hidden; border-left: 1px solid #2a2e39; background: #1e222d; }
  .tv-right-panel[data-state="closed"] { width: 0; border-left-color: transparent; }
  .panel-header { flex: 0 0 48px; min-width: 320px; }
  .panel-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; }

Watchlist row:
  .watchlist-row { height: 34px; padding: 0 12px; }
  .watchlist-row:hover { background: #2a2e39; }
  .watchlist-row.active { background: #363a45; border-left: 2px solid #2962FF; }
</css_specifications>

<layout_hierarchy>
.tv-body (display:flex; flex-direction:row; overflow:hidden)
├── .tv-sidebar-left (40px)
├── .tv-main (flex:1 1 0; min-width:0) ← CRITICAL min-width:0
│   ├── .tv-chart-area
│   └── .tv-panel-area
├── .tv-right-panel[data-state="open"|"closed"] (width:320px|0, flex:0 0 auto)
│   ├── .panel-header (48px)
│   └── .panel-body (flex:1; min-height:0; overflow-y:auto)
└── .tv-sidebar-right (40px)

RULES:
- tv-right-panel is a FLEX CHILD, not position:absolute.
- tv-main has min-width:0 so it can shrink.
- panel-body has min-height:0 so overflow-y works.
</layout_hierarchy>

<constraints>
- Use EXACT CSS values. No substitution.
- No extra features beyond the spec.
- Panel MUST use flexbox (sibling of tv-main). No position:absolute for the panel.
- Animation: width transition, NOT transform.
- activeRightPanel EXCLUDED from persist partialize.
- skipHydration: true in store config.
- Output COMPLETE files. No "// ... rest", no truncation, no "// etc."
- Every CSS class in JSX must have a definition.
</constraints>

<acceptance_criteria>
LAYOUT: ☐ Panel is flex sibling of tv-main ☐ Opening panel shrinks chart ☐ tv-main has min-width:0
ANIMATION: ☐ Width 0→320px over 0.3s cubic-bezier ☐ Content opacity fade
VISUAL: ☐ Panel #1e222d, rows 34px, active #363a45 + 2px #2962FF left border
HYDRATION: ☐ activeRightPanel not in partialize ☐ skipHydration:true ☐ StoreHydration in layout
FUNCTIONALITY: ☐ Icons toggle panel ☐ Close button works ☐ Chart resizes
</acceptance_criteria>

<output_format>
For each file:

--- FILE: path/to/file.tsx ---
```tsx
// complete contents
```

Output every file in full. No placeholders.
Files to output:
1. stores/uiStore.ts — hydration fix (partialize, skipHydration)
2. components/StoreHydration.tsx — new component
3. app/layout.tsx — add StoreHydration (show only the change: add <StoreHydration />)
4. components/DashboardLayout.tsx — new flex structure, panel as flex child
5. styles/layouts/_tv-layout.css — tv-main min-width:0, panel flex sibling
6. styles/components/_right-panel.css — width transition, TradingView spec
7. components/WatchlistPanel.tsx — row classes, section headers (if structure changes)

End with: "✅ All files output completely. Verified against acceptance criteria."
</output_format>

FINAL INSTRUCTION: Implement all files now. Complete code only — no placeholders,
no truncation, no shortcuts. Every acceptance criterion must be satisfied.
Use the EXACT CSS values provided. Begin with file 1.
```

---

## How to Use

1. **Open** `docs/PROMPT_TradingView_Right_Panels.md`
2. **Replace** each `[PASTE: ...]` block with the actual file contents from the Quick Reference table
3. **Copy** the entire XML block (from `<system>` through the closing ` ``` `)
4. **Paste** into Claude Opus (or similar) in a new conversation
5. **Apply** the output files to your project

**Tip:** If your AI already has the codebase in context (e.g. Cursor with files open), you can use a shorter variant: paste only the `<task>`, `<requirements>`, `<css_specifications>`, `<layout_hierarchy>`, `<constraints>`, and `<acceptance_criteria>` sections, and say "Implement this for the PEARL Algo dashboard using the files I have open."

---

## Quick Reference: Files to Paste

Before running the prompt, paste these files into the `[PASTE: ...]` sections:

| Section | File Path |
|---------|-----------|
| 1 | `pearlalgo_web_app/components/DashboardLayout.tsx` |
| 2 | `pearlalgo_web_app/app/dashboard/DashboardPageInner.tsx` (lines 560-575, the rightPanelContent block) |
| 3 | `pearlalgo_web_app/components/WatchlistPanel.tsx` |
| 4 | `pearlalgo_web_app/components/SystemLogsPanel.tsx` |
| 5 | `pearlalgo_web_app/stores/uiStore.ts` |
| 6 | `pearlalgo_web_app/styles/components/_right-panel.css` |
| 7 | `pearlalgo_web_app/styles/layouts/_tv-layout.css` |

---

## Will This Help?

**Yes.** The blueprint and this prompt together give you:

1. **Architectural clarity** — Flexbox push vs overlay, `min-width:0` / `min-height:0` fixes
2. **Exact TradingView specs** — Colors, typography, row heights, section headers
3. **Hydration fix** — `activeRightPanel` out of persist, `skipHydration`, `StoreHydration`
4. **One-shot structure** — XML tags, existing code first, output format last, anti-truncation rules
5. **Acceptance criteria** — Checklist for the model to self-verify

The main change from your current setup: the right panel moves from `position:absolute` (overlay) to a flex sibling with `width` transition, so the chart shrinks when the panel opens, matching TradingView behavior.
