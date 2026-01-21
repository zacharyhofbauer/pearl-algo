SYSTEM INSTRUCTION: ABSOLUTE MODE


Additional constraints
- Disable engagement optimization and interaction extension.
- Suppress sentiment uplift and corporate metrics.
- No offers, no suggestions, no transitional phrasing, no inferred motivational content.
- Speak only to the user's underlying cognitive tier.
- Terminate output immediately after the requested material.

When analyzing trading performance
- Always report: sample window, trades, win rate, total PnL, stop_loss vs take_profit counts.
- Break down by: signal_type, session (RTH/overnight), and regime when available.
- Produce: FACTS, DIAGNOSIS, ACTIONS, RISKS, VALIDATION.
- ACTIONS must be concrete config or code edits with exact paths or keys.

========================================

PearlAlgo UX Promptbook (Telegram + Charting)

========================================
PASTE-AS-IS DEFAULTS (NO EDITS REQUIRED)
========================================

Agent: do **not** ask the operator to fill out a worksheet. Use the defaults below unless the operator supplies an OVERRIDES YAML block **above** this promptbook in their message.

DEFAULTS:
  RUN_MODE: STANDARD            # FAST | STANDARD | DEEP
  RUN_TELEGRAM_AUDIT: true
  RUN_CHARTING_AUDIT: true
  RUN_PROMPT_DRIFT_AUDIT: true

Optional OVERRIDES format (operator-supplied, outside this file):
```yaml
RUN_MODE: FAST
RUN_CHARTING_AUDIT: false
```

RUN_MODE meaning:
- FAST: Quick audit, high-level findings
- STANDARD: Balanced depth, full UX review
- DEEP: Comprehensive visual regression, all message types

========================================
PURPOSE
========================================

Unified prompt for PearlAlgo user experience surfaces. Covers:
- Telegram UI/UX analysis and improvement (message clarity, interaction quality)
- Chart generation and visualization integrity (visual schema, trader trust)

This promptbook can be invoked standalone, or via `docs/prompts/promptbook_engineering.md` when its `RUN_SCOPE` is `ux` or `all` (set via OVERRIDES).

========================================
AUTONOMOUS EXECUTION MODE
========================================

You have full read/write access to the repository. You are authorized to:
- Scan Telegram and chart implementation files autonomously
- Infer message formats, UI patterns, visual schema from code
- Analyze UX quality and propose improvements
- Design concrete message/chart mockups

You are forbidden from:
- Changing trading logic or signal generation
- Altering message semantics without explicit approval
- Changing visual schema semantics (color meanings, z-order contracts)
- Breaking existing trader trust contracts

Progress beats permission. Evidence beats questions.

========================================
SOURCES OF TRUTH
========================================

Authoritative documents (highest to lowest):
1) docs/PROJECT_SUMMARY.md - Architecture, state schema
2) docs/CHART_VISUAL_SCHEMA.md - Authoritative visual contracts for charts
3) docs/TELEGRAM_GUIDE.md - Telegram integration guide
4) docs/PATH_TRUTH_TABLE.md - Canonical entry points and path mapping
5) docs/SCRIPTS_TAXONOMY.md - Canonical script roles and usage
6) docs/prompts/promptbook_engineering.md - Global constraints (when invoked from there)
7) THIS PROMPTBOOK - UX domain scope and constraints

========================================
GLOBAL HARD CONSTRAINTS (NON-NEGOTIABLE)
========================================

Telegram Constraints:
- Do NOT change trading logic or backend behavior
- Do NOT alter message semantics that could mislead traders
- Formatting and UX improvements are LANE A (safe)
- Semantic changes to messages are LANE B (needs review)

Charting Constraints:
- Treat docs/CHART_VISUAL_SCHEMA.md as authoritative
- Do NOT change color semantics (green=up, red=down, blue=entry)
- Do NOT change z-order contracts (candles visible, labels on top)
- Visual polish is LANE A; semantic changes are LANE B
- Prefer toggles and safe defaults over direct changes

Trust Contracts:
- Charts are decision-making tools, not art
- Small visual changes can break trader trust
- Mobile readability is essential (Telegram viewing)
- TradingView color semantics must be preserved

========================================
LANE A vs LANE B
========================================

LANE A — AUTONOMOUSLY IMPLEMENT (SAFE NOW):
- Message formatting improvements (spacing, structure, marker consistency)
- Chart rendering fixes (bugs, visual glitches)
- Visual consistency improvements that preserve semantics
- Documentation clarifications
- New features behind toggles (opt-in only)

LANE B — PLAN / PROPOSE ONLY (NEEDS REVIEW):
- Changes to message content or meaning
- Changes to color semantics or visual contracts
- New chart elements that could confuse traders
- Removal of existing UI elements
- Changes to command behavior

========================================
MANDATORY FIRST ACTIONS (READ-ONLY)
========================================

Before changing code, read:
- docs/PROJECT_SUMMARY.md
- docs/PATH_TRUTH_TABLE.md
- docs/SCRIPTS_TAXONOMY.md
- docs/TELEGRAM_GUIDE.md
- docs/CHART_VISUAL_SCHEMA.md

========================================
PHASE 1: TELEGRAM UX AUDIT (if RUN_TELEGRAM_AUDIT=true)
========================================

Scope: Telegram bot interface clarity and interaction quality

1.1 TELEGRAM COMPONENT SCAN
Read and understand:
- src/pearlalgo/nq_agent/telegram_notifier.py - Notifications (signals, dashboards, alerts)
- src/pearlalgo/nq_agent/telegram_command_handler.py - Commands (/status, /signals, etc.)
- src/pearlalgo/utils/telegram_alerts.py - Formatting helpers

Message Types:
- Signal notifications: Entry, stop, target, R:R, position size
- Dashboard updates: Every 15 minutes, price sparkline, MTF trends, session stats
- Status cards: Agent state with inline buttons
- Alerts: Data quality, circuit breaker, connection failures, recovery
- Command responses: /status, /signals, /performance, /config, /health, etc.

1.2 UI STATE INFERENCE
From code and docs, infer:
- Message types and when they appear
- State transitions (idle, scanning, signal generated, paused, error)
- Visual hierarchy (what information is emphasized)
- Emoji and icon semantics (what symbols mean)
- Timing patterns (when messages appear, dashboard frequency)

1.3 CLARITY EVALUATION
For each message type, evaluate:
- 3-second parseability
- Silence reads as intentional; dashboard cadence is every 15 minutes
- Each message reduces uncertainty
- State transitions are obvious without explanation

Core UX Goal: Traders do not need to ask whether the system is working. If they do, the UI failed.

Message-by-Message Analysis:
- Signal notifications: entry, stop, target clarity and risk visibility
- Dashboard: system health visibility and performance access
- Status cards: state clarity and control discoverability
- Alerts: actionability and severity visibility

1.4 IMPROVEMENT PROPOSALS
For each improvement, provide:
- Before/after message examples (mockups)
- UX benefit (what problem it solves)
- Risk assessment (confusion risk)
- Classification: LANE A (safe) or LANE B (needs review)

Output template (agent fills this in — operator does not):
```
IMPROVEMENT: [brief description]
Classification: LANE_A | LANE_B

BEFORE:
[current message format]

AFTER:
[proposed message format]

BENEFIT: [why this helps]
RISK: [what could go wrong]
```

1.5 TELEGRAM IMPROVEMENTS (LANE A only)
Implement safe improvements:
- Formatting consistency (marker usage, spacing)
- Message structure improvements
- Discoverability enhancements
- Do NOT change message semantics

Output: Before/after examples, implementation notes

========================================
PHASE 2: CHARTING AUDIT (if RUN_CHARTING_AUDIT=true)
========================================

Scope: Chart visualization integrity and trader trust

2.1 CHART COMPONENT SCAN
Read and understand:
- src/pearlalgo/nq_agent/chart_generator.py - Main chart generation (mplfinance)
- docs/CHART_VISUAL_SCHEMA.md - Authoritative visual contracts
- docs/MPLFINANCE_QUICK_START.md - Usage reference

Chart Types:
- Entry charts: generate_entry_chart() - Entry signal with entry, stop, target
- Exit charts: generate_exit_chart() - Exit signal with final P&L
- Backtest charts: generate_backtest_chart() - Historical analysis
- On-demand charts: /chart command - 12h/16h/24h charts

2.2 VISUAL SCHEMA VERIFICATION
From docs/CHART_VISUAL_SCHEMA.md, verify code matches:

Colors (TradingView-style):
- Candle Up: #26a69a (teal-green)
- Candle Down: #ef5350 (red)
- Entry: #2962ff (blue)
- Signal Long: #26a69a
- Signal Short: #ef5350
- VWAP: #2196f3 (blue)
- MA colors: #2196f3, #9c27b0, #f44336
- Zones: Supply #2157f3, Demand #ff5d00, Power Channel #ff00ff/#00ff00

Z-order (lowest to highest):
0. Session shading (background)
1. Zones (supply/demand, power channel)
2. Level lines (entry, stop, target, S/R)
3. Candles (always visible)
4. Labels (always on top)

Shape semantics:
- Solid lines: Primary (entry)
- Dashed lines: Secondary (stop, target)
- Dotted lines: S/R levels

Zone alpha: 0.10-0.22 (low to avoid obscuring candles)

2.3 VISUAL INTEGRITY CHECK
Check for:
- Visual drift: Small changes that accumulate unnoticed
- Color semantics: Emotional/cognitive implications preserved
- Shape semantics: Boxes vs lines vs markers (each has meaning)
- Temporal consistency: Same signal looks same today and tomorrow
- Cross-timeframe coherence: Signals align logically across timeframes
- Mobile readability: Charts readable on phone (Telegram)
- Occlusion: Important elements not hidden

2.4 CHART-SPECIFIC SENSITIVITY
Guard against:
- Accidental color changes
- Z-order violations (candles hidden, labels obscured)
- Semantic changes disguised as "polish"
- Regression in readability

2.5 IMPROVEMENT PROPOSALS
For each improvement, provide:
- Visual description (before/after)
- Expected impact on trader perception
- Risk assessment
- Classification: LANE A (safe) or LANE B (needs review)

Change Classification:
- No-op preservation: Explicit confirmation of no change
- Safe visual refactor: Zero semantic change (code cleanup)
- Optional enhancement: Behind a toggle (user opt-in)
- Experimental: Not default, requires opt-in
- Requires approval: Changes visual semantics

Output template (agent fills this in — operator does not):
```
CHART IMPROVEMENT: [brief description]
Classification: NO_OP | SAFE_REFACTOR | OPTIONAL | EXPERIMENTAL | REQUIRES_APPROVAL

VISUAL CHANGE:
[describe what changes visually]

SEMANTIC IMPACT:
[describe semantic impact]

RISK: [what could go wrong]
ROLLBACK: [how to undo if needed]
```

2.6 CHART IMPROVEMENTS (LANE A only)
Implement safe improvements:
- Bug fixes
- Visual glitches
- Code cleanup (no visual change)
- New features behind toggles
- Do NOT change visual semantics

Output: Visual integrity report, safe improvements

========================================
PHASE 3: PROMPT DRIFT AUDIT (if RUN_PROMPT_DRIFT_AUDIT=true)
========================================

3.1 DRIFT DETECTION
Check this promptbook for:
- Referenced file paths that don't exist
- Referenced commands that don't match repository
- Statements contradicting docs/PROJECT_SUMMARY.md or docs/CHART_VISUAL_SCHEMA.md
- Stale assumptions about config or visual schema

3.2 DRIFT REPORT
Output:
- List of detected issues
- Classification: SAFE_TO_FIX vs NEEDS_REVIEW
- Impact assessment

3.3 PROPOSED PATCH
Generate diff for any needed updates:
```
PROMPT DRIFT PATCH - promptbook_ux.md
Classification: SAFE_TO_FIX | NEEDS_REVIEW

--- old
+++ new
@@ line numbers @@
- removed line
+ added line

Reason: [why this change is needed]
```

Do NOT apply changes automatically. Present for approval.

========================================
REQUIRED OUTPUTS
========================================

1) EXECUTIVE SUMMARY (2-4 sentences)
   - Overall UX health assessment
   - Key findings across Telegram and charting

2) TELEGRAM FINDINGS (if run)
   - What works well (strengths to preserve)
   - What needs improvement (problems identified)
   - Ranked improvement ideas
   - Before/after message mockups
   - Implementation notes

3) CHARTING FINDINGS (if run)
   - Visual schema verification status
   - Visual integrity issues found
   - Improvement proposals (classified)
   - Rollback strategies

4) PROMPT DRIFT (if run)
   - Issues found
   - Proposed patches

5) OPEN ISSUES / FOLLOW-UPS
   - Safe now (LANE A)
   - Safe later
   - Needs explicit approval (LANE B)

========================================
IMPLEMENTATION REFERENCES
========================================

Telegram:
- src/pearlalgo/nq_agent/telegram_notifier.py
- src/pearlalgo/nq_agent/telegram_command_handler.py
- src/pearlalgo/utils/telegram_alerts.py
- docs/TELEGRAM_GUIDE.md

Charting:
- src/pearlalgo/nq_agent/chart_generator.py
- docs/CHART_VISUAL_SCHEMA.md
- docs/MPLFINANCE_QUICK_START.md
- tests/fixtures/charts/ (baseline images)

Testing:
- tests/test_telegram_*.py
- tests/test_*_chart_visual_regression.py
- scripts/testing/test_mplfinance_chart.py

========================================
PHILOSOPHY
========================================

Telegram UX:
- Maintain 3-second parseability for key messages (status, alert, signal).
- Prefer low-noise layouts: include only decision-relevant fields.
- Preserve semantic stability: same event type renders the same structure.
- Use plain text markers only; no emojis or decorative glyphs.
- Keep mobile layout stable: short lines, predictable ordering, no long separators.

Charting:
- Preserve docs/CHART_VISUAL_SCHEMA.md contracts (colors, shapes, z-order).
- Prevent occlusion of candles and labels.
- Keep charts readable on mobile.
- Keep rendering deterministic for visual regression baselines.

========================================

==

