Master Task Prompt (All-in-One) - PearlAlgo

PURPOSE: Single consolidated directive to run a long, autonomous “cleanup → validate → verify → improve” session across the PearlAlgo MNQ Trading Agent codebase.

OPERATOR STATUS: The human operator is away/unavailable. Do not ask questions unless progress is impossible. Infer first, proceed, and label assumptions explicitly.

REUSABILITY: This prompt is designed to be copied as ONE message into an AI coding assistant (Cursor Agent, etc.) to orchestrate a multi-hour session spanning cleanup, backtesting, ATS execution safety, Telegram UX, charting integrity, NQ agent verification, and testing.

========================================

AUTHORITY & SCOPE (MASTER ORCHESTRATOR)

You have full read/write access to the repository. You are authorized to:
- Scan the entire repository autonomously (code, scripts, tests, docs)
- Run commands and analyze results
- Perform cleanup actions (delete/merge/update) using evidence
- Implement safe, low-risk improvements without asking for permission
- Produce a clear plan for medium/high-risk work that needs human review

You are forbidden from:
- Asking “what should I do next?” (follow the phases below)
- Asking the operator to explain the system before you scan docs/code
- Enabling live trading execution or placing real orders
- Changing strategy intent, risk parameters, or state schema without explicit authorization

Progress beats permission. Evidence beats questions.

========================================

SOURCES OF TRUTH & CONFLICT RESOLUTION

Authoritative documents (highest to lowest):
1) docs/PROJECT_SUMMARY.md
   - Architecture, module boundaries, state schema, “what owns what”
2) THIS FILE (master orchestration)
   - Phase order, cross-cutting constraints, output requirements
3) Sub-prompts (domain scopes)
   - docs/prompts/project_cleanup.md
   - docs/prompts/project_building.md
   - docs/prompts/full_testing.md
   - docs/prompts/backtesting_upgrades.md
   - docs/prompts/ats_execution.md
   - docs/prompts/nq_agent.md
   - docs/prompts/telegram_suite.md
   - docs/prompts/charting_suite.md

If two documents conflict:
- docs/PROJECT_SUMMARY.md wins
- then THIS FILE
- then the domain-specific prompt within its scope

========================================

GLOBAL HARD CONSTRAINTS (NON-NEGOTIABLE)

Architecture:
- Respect dependency boundaries (utils -> config -> data_providers -> strategies -> nq_agent).
- Do not collapse layers or introduce circular dependencies.
- Keep business logic separate from I/O, integrations, messaging, and infrastructure.

Runtime safety:
- Do NOT enable live trading execution. Execution must remain safety-first (disabled/disarmed/shadow by default).
- Do NOT change signal generation logic, risk parameters, or strategy behavior unless explicitly authorized.
- Do NOT change state schema unless explicitly authorized; if you find schema drift, document and propose a migration plan.

Change posture:
- Prefer additive changes, toggles, and reversible refactors.
- No rewrites. The system already works; your job is to remove confusion and strengthen trust.
- Don’t “simplify” by deleting nuance that exists for safety or clarity.

Repository hygiene:
- Do not keep files “just in case.” Each retained file must pass the deletion test:
  “If this file disappeared tomorrow, would the system lose required behavior, safety, or clarity?”

========================================

SESSION OPERATING MODE (USER IS AWAY)

Work in two lanes:

LANE A — AUTONOMOUSLY IMPLEMENT (SAFE NOW)
- Dead code removal + de-duplication (low risk)
- Fix broken imports/references and documentation drift
- Improve observability/logging (no behavior change)
- Improve tests (unit/integration) for existing behavior
- Backtest observability/explainability (why signals fired / didn’t fire), without changing strategy thresholds
- Telegram formatting/UX improvements that don’t change backend logic
- Chart rendering safety fixes and visual consistency improvements that preserve existing visual semantics (prefer toggles)
- ATS safety guard improvements that are additive and default-safe (do not arm/enable)

LANE B — PLAN / PROPOSE ONLY (NEEDS HUMAN REVIEW)
- Anything that alters trading decisions or strategy thresholds/logic
- Any change that could place/modify/cancel real orders in live mode
- State schema changes or migrations
- Large architectural refactors or new dependencies
- Changes that could materially change message semantics or chart semantics

If you reach LANE B work:
- Write a concrete plan (files, steps, risks, rollback)
- Implement only preparatory refactors that are clearly behavior-preserving
- Stop after producing the plan (do not “guess” approval)

========================================

MANDATORY FIRST ACTIONS (READ-ONLY)

Before changing code, you must read:
- docs/PROJECT_SUMMARY.md
- docs/CHEAT_SHEET.md
- docs/TESTING_GUIDE.md
- docs/TELEGRAM_GUIDE.md
- docs/CHART_VISUAL_SCHEMA.md
- docs/ATS_ROLLOUT_GUIDE.md

Then, read each domain prompt listed above and treat them as scope-specific constraints.

========================================

REQUIRED OUTPUTS (WHAT YOU MUST LEAVE BEHIND)

You must produce BOTH:

A) A written end-of-session report (in your final response) containing:
- Executive summary
- What you changed (file-level), why, and risk level
- Commands run + test/backtest results
- What you did NOT change (and why)
- Open issues, follow-ups, and next steps (prioritized)

B) A repository artifact log:
- Create or append: docs/AI_SESSION_LOG.md
- Include:
  - Timestamp + “session goal”
  - Assumptions made
  - Commands run (and key outputs)
  - Changes made (high level + key files)
  - Risks noted
  - Follow-ups / TODOs

If docs/AI_SESSION_LOG.md already exists, append; do not rewrite history.

========================================

PHASED EXECUTION PLAN (STRICT ORDER)

Phase 0 — Pre-flight / Repo discovery (read-only)
- Scan repository structure (src/, scripts/, tests/, docs/, config/)
- Map key entry points:
  - Agent service loop, strategy, state, Telegram, charting, execution/learning, backtesting
- Confirm architecture boundaries from docs/PROJECT_SUMMARY.md
- Identify duplicate/overlapping utilities and scripts
- Identify stale docs references and broken paths
Output: Inventory + “top risks” list

Phase 1 — Cleanup planning (decision phase)
- Apply deletion test to files and scripts
- Propose authoritative owners for cross-cutting responsibilities:
  - Retry, error handling, logging, state persistence, notifications, execution safety
- Produce a file-level plan: KEEP / MERGE / DELETE with risk
Output: Structured cleanup plan (file-level)

Phase 2 — Cleanup execution (LANE A only)
- Delete low-risk, unreferenced artifacts
- Consolidate duplicates to a single authoritative implementation
- Fix imports, docs references, script entry points
- Rationalize scripts into a clear taxonomy (lifecycle/gateway/telegram/testing/monitoring/maintenance/backtesting)
Output: Execution log + diff summary

Phase 3 — Baseline verification
- Run the project test suite per docs/TESTING_GUIDE.md
- Ensure architecture boundary checks pass
- Fix any regressions introduced by cleanup
Output: Test results + verification checklist

Phase 4 — Backtesting verification & upgrades (LANE A unless strategy changes)
- Read and follow docs/prompts/backtesting_upgrades.md
- Verify backtest entry points and data format assumptions (parquet cache, OHLCV)
- Run signal-only backtests first; then full trade simulation if appropriate
- Perform:
  - Signal existence + frequency analysis
  - Condition blocking analysis (which filters bind most)
  - Regime sanity checks (trending vs ranging / high vs low vol windows)
- Improve explainability tooling/logging (why signals didn’t trigger) without changing thresholds
Output: Backtest findings + observability improvements

Phase 5 — NQ agent verification & observability (LANE A)
- Read and follow docs/prompts/nq_agent.md
- Audit lifecycle reliability:
  - 30s cadence, no drift, no silent stalls
  - market hours vs strategy session awareness
  - state persistence + recovery
  - circuit breaker correctness and clarity
- Improve monitoring surfaces (logs/state fields/Telegram status), preserving behavior
Output: Verification findings + improvements list

Phase 6 — ATS execution safety & learning audit (LANE A only; no live enablement)
- Read and follow docs/prompts/ats_execution.md
- Verify safety invariants:
  - disabled/disarmed/shadow defaults
  - precondition checks are complete and defensive
  - kill switch works quickly and reliably
  - learning cannot “arm” execution; it only influences decisions when already safely enabled
- Add missing safety guards, alerts, and observability as additive, default-safe changes
Output: Safety audit + proposed rollouts (shadow → paper → live) per docs/ATS_ROLLOUT_GUIDE.md

Phase 7 — Telegram suite (LANE A for formatting; LANE B for semantic changes)
- Read and follow docs/prompts/telegram_suite.md
- Audit message clarity and interaction quality:
  - status cards, dashboards, signals, alerts, commands
  - “under 3 seconds” comprehension goal
- Improve formatting, consistency, and discoverability without altering trading logic
Output: Before/after message examples + implementation notes

Phase 8 — Charting suite (LANE A only; propose first, preserve schema)
- Read and follow docs/prompts/charting_suite.md
- Treat docs/CHART_VISUAL_SCHEMA.md as authoritative
- Audit for regressions:
  - color semantics, z-order, mobile readability, occlusion, timeframes
- Prefer toggles and safe defaults; preserve trader trust contracts
Output: Visual integrity report + safe improvements (with rollback strategy)

Phase 9 — Project building proposals (PLAN/PROPOSE)
- Read and follow docs/prompts/project_building.md
- Surface opportunities across correctness/reliability/observability/maintainability
- Provide options with trade-offs; do not execute high-risk changes without approval
Output: Ranked proposal list (safe now vs safe later vs requires approval)

Phase 10 — Full testing strategy and additions (LANE A)
- Read and follow docs/prompts/full_testing.md
- Add missing tests for critical paths uncovered during phases 2–8
- Expand integration tests and failure-mode tests where feasible
Output: Test plan + new tests + results

Phase 11 — Final consolidation
- Ensure docs and cheat sheets reflect reality (no stale commands/paths)
- Ensure no broken imports, no broken doc references
- Update docs/AI_SESSION_LOG.md with final summary
Output: Final report + next actions

========================================

REQUIRED FINAL RESPONSE FORMAT (END-OF-SESSION REPORT)

1) EXECUTIVE SUMMARY (2-4 sentences)
2) WHAT CHANGED (File-level list)
   - For each: action (ADD/UPDATE/DELETE), reason, risk, verification performed
3) VERIFICATION
   - Commands run
   - Test results (and any notable skips)
4) BACKTESTING FINDINGS (if executed)
   - Signal frequency summary
   - Condition blockers
   - Any observability improvements added
5) ATS SAFETY FINDINGS (if audited)
   - Safety invariants status
   - Proposed safe rollouts (shadow/paper/live)
6) TELEGRAM + CHARTING NOTES (if audited)
   - Before/after examples (brief)
   - Visual/schema integrity notes
7) OPEN ISSUES / FOLLOW-UPS (Prioritized)
   - Safe now
   - Safe later
   - Needs explicit approval

========================================

REMINDER: You are here to strengthen trust. Prefer evidence, clarity, and reversible changes.


