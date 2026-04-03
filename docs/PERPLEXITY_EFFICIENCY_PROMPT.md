# Pearl Algo Efficiency Audit Prompt for Perplexity

Paste everything below into Perplexity.

```text
Act as a principal engineer and repo-efficiency consultant. I want a brutally practical audit of my repo with a focus on engineering velocity, maintainability, test confidence, CI coverage, architecture simplification, and reducing wasted developer/agent time.

Important:
- Be specific, opinionated, and evidence-based.
- Separate confirmed observations from your inferences.
- Prioritize changes that will materially improve day-to-day development speed and reliability.
- Do not give generic “best practices” unless they map directly to the repo details below.
- When recommending a refactor, explain the expected payoff, risk, and suggested order.
- Favor pragmatic incremental improvements over idealized rewrites.

Repo context:
- Project name: PearlAlgo
- Stack: Python 3.12 backend + Next.js 14 frontend
- Canonical frontend: apps/pearl-algo-app
- Canonical runtime path per README:
  - service: src/pearlalgo/market_agent/service.py
  - strategy: src/pearlalgo/strategies/composite_intraday/
  - execution: src/pearlalgo/execution/tradovate/
  - config: config/live/tradovate_paper.yaml
- Repo contains both backend and frontend, plus a lot of migration/compatibility surface area.

Confirmed observations from a local audit:

1. The repo documents a canonical path, but the runtime still depends on compatibility bridges.
- README says anything outside the operating-model path should be treated as non-canonical and points to compatibility leftovers.
- src/pearlalgo/strategies/composite_intraday/pinescript_core.py is the “canonical” strategy surface, but it delegates directly into src/pearlalgo/trading_bots/signal_generator.py.
- src/pearlalgo/config/migration.py is explicitly deprecated but still normalizes legacy config shapes.
- src/pearlalgo/market_agent/main.py still supports legacy account-overlay config loading and then runs migrate_legacy_runtime_config().
- I counted 159 matches for legacy/compatibility/removed-related terms in src and 26 in docs.

2. CI does not validate the canonical frontend at all.
- .github/workflows/ci.yml sets up Python only.
- It runs Python checks, audits, docs validation, and pytest.
- It does not install Node, run frontend lint, run frontend tests, or run next build.
- This is notable because README calls apps/pearl-algo-app the canonical frontend.

3. Backend guardrails are decent, but the repo’s architecture is still heavily concentrated in a few giant files.
- Largest backend/frontend source files by line count:
  - src/pearlalgo/api/server.py: 3896 LOC
  - src/pearlalgo/trading_bots/signal_generator.py: 2946 LOC
  - src/pearlalgo/market_agent/service.py: 2558 LOC
  - src/pearlalgo/execution/tradovate/adapter.py: 1837 LOC
  - apps/pearl-algo-app/components/CandlestickChart.tsx: 1421 LOC
  - src/pearlalgo/data_providers/ibkr_data_executor.py: 1336 LOC
  - src/pearlalgo/market_agent/performance_tracker.py: 1195 LOC
  - apps/pearl-algo-app/components/TradeDockPanel.tsx: 1031 LOC
  - apps/pearl-algo-app/app/dashboard/DashboardPageInner.tsx: 871 LOC

4. Some extraction has happened, but duplication and partial extraction are still visible.
- src/pearlalgo/api/data_layer.py says it was extracted from server.py to reduce the main router module size.
- But src/pearlalgo/api/server.py still contains its own TTL cache helper, thread pool, local caches, and a large amount of orchestration logic.
- This suggests the extraction is incomplete and the server remains a monolith.

5. There are config flags that are intentionally not enforced at runtime.
- In src/pearlalgo/market_agent/service.py, the flags skip_overnight, avoid_lunch_lull, and prioritize_ny_session are tracked as “not_enforced” warnings only.
- Those same keys still appear in config files.
- This creates cognitive overhead because config surface area is larger than the actual behavior surface area.

6. Test surface is broad, but workflow ergonomics are mixed.
- Backend test files: 117
- Frontend test files: 28
- Python architecture boundary enforcement passed.
- Ruff bug-catching subset passed.
- Orphan module enforcement passed.
- Frontend targeted Jest suites passed.
- But targeted frontend tests emitted repeated React act(...) warnings around async state updates in hooks/useDashboardData.ts.
- Also, targeted backend pytest runs can fail the global coverage gate even when all selected tests pass, because pytest.ini always enforces --cov-fail-under=40.
- Example: a targeted run of repo-contracts + service-smoke + strategy-registry had 19 tests pass but still exited non-zero because total coverage for that partial run was 22.94%.

7. Frontend quality is decent locally, but there are warning-level issues that would be better caught in CI.
- next lint reports two no-img-element warnings in apps/pearl-algo-app/app/dashboard/DashboardPageInner.tsx.
- next build succeeds locally.
- The app has scripts for lint/test/build, but CI ignores them.

8. Repo-root artifact sprawl exists even if it is gitignored.
- Present in repo root during audit: .coverage, .pytest_cache, .ruff_cache, .venv, htmlcov
- This is not necessarily wrong, but it adds search noise for humans and coding agents.

9. Working tree churn is high right now.
- There are many modified/deleted/untracked files across backend, tests, and frontend.
- Treat this as an in-flight refactor environment rather than a clean baseline.

Concrete file references worth reasoning about:
- README.md
- .github/workflows/ci.yml
- pytest.ini
- src/pearlalgo/api/server.py
- src/pearlalgo/api/data_layer.py
- src/pearlalgo/market_agent/service.py
- src/pearlalgo/market_agent/main.py
- src/pearlalgo/config/migration.py
- src/pearlalgo/strategies/composite_intraday/pinescript_core.py
- src/pearlalgo/trading_bots/signal_generator.py
- apps/pearl-algo-app/package.json
- apps/pearl-algo-app/hooks/useDashboardData.ts
- apps/pearl-algo-app/app/dashboard/DashboardPageInner.tsx
- apps/pearl-algo-app/components/CandlestickChart.tsx

What I want from you:

1. Give me an executive summary:
- What are the top 5 things slowing this repo down?
- Which of them are structural versus tactical?

2. Produce a prioritized efficiency plan:
- Rank the top 10 improvements by ROI.
- For each item, include:
  - why it matters
  - what specific files/modules it touches
  - expected payoff
  - implementation difficulty
  - risk of regressions
  - whether it is a quick win, medium refactor, or major refactor

3. Focus especially on these themes:
- How to reduce compatibility-surface drag without destabilizing production
- How to break down the biggest files safely
- How to make CI reflect the actual product surface, especially the frontend
- How to improve test ergonomics so targeted runs stay useful
- How to reduce misleading config surface area
- How to make the repo more efficient for AI coding agents and human contributors

4. Give me a phased roadmap:
- Phase 1: quick wins I can do in 1-3 days
- Phase 2: high-leverage refactors for 1-2 weeks
- Phase 3: deeper simplifications for 1-2 months

5. For each phase, recommend concrete deliverables:
- example PR titles
- test/verification commands
- success criteria

6. Call out what not to do:
- Which tempting rewrites would waste time?
- Which legacy surfaces should be left alone until higher-value work lands first?

7. Give me a final section specifically for “engineering efficiency for AI-assisted development”.
- How should I reorganize docs, artifacts, boundaries, prompts, or repo structure so tools like Perplexity/Codex/Claude can work faster with less confusion?
- Be concrete and repo-specific.

Format your answer like this:
- Executive Summary
- Top Findings
- Prioritized Efficiency Plan
- Phased Roadmap
- Anti-Patterns To Avoid
- AI-Assisted Development Recommendations
- Suggested First 3 PRs

Where you infer something rather than directly observe it from the evidence above, label it clearly as an inference.
```
