# Pearl Algo Codebase Review and Research Playbook

## Purpose

This document is a practical review of the current Pearl Algo repo as it exists on Friday, April 3, 2026.

It is meant to answer six questions:

1. How the codebase is built.
2. How the live system actually works.
3. Where the repo is strong.
4. Where the repo is fragile or misleading.
5. When the system appears to have worked well this week, and when it clearly did not.
6. How to use Perplexity and Claude Code Plan mode as a force multiplier instead of a source of random advice.

This is based on repo structure, canonical docs, live runtime state, logs, and persisted trading artifacts under the live state directory.

## Executive Review

- The repo has a real canonical operating model and it is reasonably well documented. The intended live path is narrow: `pearl.sh` -> `market_agent.main` -> `MarketAgentService` -> composite intraday strategy -> Tradovate paper execution -> JSON and SQLite state -> FastAPI -> Next.js dashboard.
- The biggest architectural truth gap is that the canonical strategy wrapper still routes through the legacy strategy engine. The repo talks like the live strategy is fully under `src/pearlalgo/strategies/composite_intraday/`, but `pinescript_core.py` still delegates to `src/pearlalgo/trading_bots/signal_generator.py`.
- The biggest operational truth gap is that the system has multiple "performance truths": `performance.json`, `trades.db`, broker fills, and the live broker summary in `state.json`. They do not fully agree yet.
- The system appears to have traded strongly on Tuesday, March 31, 2026 and Wednesday, April 1, 2026. Thursday, April 2, 2026 was mixed and appears to have included restart or arming churn. Friday, April 3, 2026 is mostly a stale-data and IBKR-unavailable day.
- The frontend and API are real products, not just thin monitoring shells. The web app is a substantial Next.js dashboard with Zustand stores, WebSocket updates, polling fallback, charting, logs, signals, trade dock analytics, and operator state views.
- The repo is clearly in the middle of a large cleanup. There is meaningful decomposition work already done, but the service layer and compatibility surfaces are still too large, too mixed, and too easy to misunderstand.

## What The Repo Is

At a high level, Pearl Algo is not just "a trading bot." It is six systems bound together:

1. An operator control surface.
2. A market-data ingestion layer.
3. A strategy and signal generation layer.
4. A signal execution and trade-state layer.
5. A persistence and analytics layer.
6. A monitoring and dashboard layer.

The canonical docs say the intended live path is:

- Operator entry: `pearl.sh`
- Config: `config/live/tradovate_paper.yaml`
- Service: `src/pearlalgo/market_agent/service.py`
- Strategy: `src/pearlalgo/strategies/composite_intraday/`
- Execution: `src/pearlalgo/execution/tradovate/`
- Frontend: `apps/pearl-algo-app/`
- Live state: `/home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ`

That operating model is stated in:

- `README.md`
- `docs/START_HERE.md`
- `docs/PATH_TRUTH_TABLE.md`
- `docs/architecture/state_management.md`

## How It Is Built

### 1. Operator and bootstrap layer

The operator-facing shell entrypoint is `pearl.sh`.

It does more than just "start the app":

- Parses flags like `--market`, `--no-chart`, and `--foreground`.
- Loads `.env` plus machine-local secrets.
- Syncs frontend env values into `apps/pearl-algo-app/.env.local`.
- Checks gateway, agent, and web app status.
- Acts as the top-level control plane for the live stack.

This matters because Pearl is not booted from one Python process alone. Operationally, the shell layer is part of the architecture.

### 2. Agent runtime layer

The Python entrypoint is `python -m pearlalgo.market_agent.main`.

That module is responsible for:

- Acquiring a singleton lock so only one agent runs.
- Setting up logging.
- Loading the runtime config.
- Running runtime validation.
- Building the strategy config view.
- Creating the data provider.
- Resolving the state directory.
- Building service dependencies.
- Instantiating and starting `MarketAgentService`.

This is a good separation point: startup concerns live in `main.py`, while trading concerns live in the service stack.

### 3. Service orchestration layer

`MarketAgentService` is still the center of gravity.

Even with extraction work already done, it still owns or wires together:

- data fetching
- persistence
- audit logging
- state snapshotting
- performance tracking
- risk and circuit breaker logic
- execution adapter state
- operator controls
- scheduled tasks
- cadence control

The good news is that decomposition has started. Important service behavior has been pushed into modules like:

- `service_loop.py`
- `signal_handler.py`
- `execution_orchestrator.py`
- `state_manager.py`
- `state_builder.py`
- `performance_tracker.py`

The bad news is that the service layer is still highly coupled, and the repo docs are a little more optimistic about the decomposition than the code really is.

### 4. Strategy layer

The intended strategy namespace is `src/pearlalgo/strategies/composite_intraday/`.

That is the public-facing strategy surface the repo wants people to use.

But the important current truth is this:

- `src/pearlalgo/strategies/composite_intraday/pinescript_core.py` is explicitly a compatibility-backed wrapper.
- It still forwards into `src/pearlalgo/trading_bots/signal_generator.py`.
- `signal_generator.py` is still where much of the real indicator logic, confluence logic, regime logic, and entry construction lives.

So the repo has two simultaneous truths:

- Documentation truth: composite intraday is canonical.
- Runtime truth: the live strategy still depends on a large retained legacy engine.

That does not make the strategy fake. It means the migration is incomplete.

### 5. Data and execution split

Pearl is intentionally split by venue:

- IBKR provides market data.
- Tradovate paper is the execution venue and live trade source of truth.

That split is important because it creates a very specific failure mode:

- Tradovate can remain connected and healthy.
- IBKR can fail.
- The agent can stay alive and keep updating broker account state.
- Signal generation can still stop because the market-data side is stale.

That exact pattern is visible in the April 3 runtime state and logs.

### 6. Persistence layer

Pearl uses a dual-write persistence design:

- JSON and JSONL are the primary store.
- SQLite is the secondary analytical store.

Primary JSON side:

- `state.json`
- `signals.jsonl`
- `performance.json`
- `events.jsonl`

Secondary SQLite side:

- `trades.db`

The docs are explicit that JSON is the recovery source of truth and SQLite may lag in async mode.

This design is sensible for a trading system that wants:

- crash-resilient portable state
- easy inspection
- mobile or API compatibility
- queryable analytics

But the tradeoff is also visible today:

- JSON and broker state have newer information than SQLite.
- Analysts can reach different conclusions depending on which artifact they trust.

### 7. API layer

The backend API is a FastAPI app in `src/pearlalgo/api/server.py`.

Its responsibilities include:

- health checks
- market status
- WebSocket state broadcasting
- candles
- indicators
- markers
- state
- trades
- signals
- performance summary
- positions
- logs
- operator settings like confidence scaling

It is not just a thin proxy. It has caching, multi-market helpers, broadcast helpers, and state-reader logic.

### 8. Frontend layer

The canonical frontend is `apps/pearl-algo-app/`, a Next.js 14 app.

Architecturally, it looks like this:

- `app/dashboard/DashboardPageInner.tsx` is the main dashboard composition point.
- Zustand stores hold agent, chart, UI, and operator state.
- `useWebSocket.ts` handles the live socket connection and reconnect behavior.
- `useDashboardData.ts` provides HTTP polling fallback and cold-data refreshes.
- The charting components, log panels, signals panel, trade dock, and layout are all separate components.

The frontend is not an afterthought. It is a real operator dashboard that combines:

- live state
- chart state
- positions
- trades
- performance summary
- recent signals
- logs
- control or readiness information

## How The Live System Works

Below is the practical boot-to-trade flow.

### Boot flow

1. `pearl.sh` loads env, syncs web env, and starts the stack.
2. `market_agent.main` loads `config/live/tradovate_paper.yaml`.
3. Runtime validation is applied.
4. A data provider is created, usually IBKR.
5. A state directory is chosen, ideally `/home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ`.
6. `MarketAgentService` is constructed with its dependencies.
7. The service starts its main loop.

### One trading cycle

Inside the service loop, a typical cycle does this:

1. Checks execution control flags.
2. Resets daily execution counters if needed.
3. Runs scheduled tasks like morning briefing or daily summaries.
4. Checks execution adapter health.
5. Polls Tradovate account state early.
6. Saves state early so the dashboard can still show broker information during data issues.
7. Fetches latest market data.
8. Applies connection and stale-data error handling.
9. Builds signal candidates from the strategy.
10. Sends each signal through the signal handler.

### Signal handling path

The signal handler is the real gate between "idea" and "trade."

It currently does things like:

- signal type whitelist checks
- trading circuit breaker checks
- position sizing
- signal tracking
- entry price validation
- timestamp sanity checks
- execution dispatch through the adapter
- virtual entry tracking if appropriate
- audit logging

### Exit and performance path

After entry:

- active trades are tracked
- virtual exits are processed
- broker-related state is synchronized
- performance and state artifacts are updated
- the dashboard reads that state through the API

## What Is Strong

### Strength 1: There is a real operating model

The repo is not pure sprawl. There is a real "golden path" and the docs do try to keep it narrow.

That is valuable because it lets humans and AI tools ask the right question:

"What is canonical right now?"

instead of

"What is every file in the repository doing?"

### Strength 2: The state model is pragmatic

JSON-first plus SQLite-second is a good fit for a system like this.

It gives you:

- recoverability
- inspectability
- analytics
- compatibility with simple tools

### Strength 3: The service is observable

Even though the service is too large, it logs a lot:

- cycle start
- connection failure
- circuit breaker transitions
- stale data
- signal generation
- execution skips

That is why it is even possible to reconstruct this week.

### Strength 4: The frontend and API are useful, not cosmetic

The dashboard is a substantial operational interface. That increases team efficiency because the operator does not need to reconstruct system state from raw logs alone.

### Strength 5: Recent refactor work is directionally right

The recent commits show deliberate cleanup and runtime hardening:

- layout canonization
- config and strategy plumbing refactors
- runtime simplification
- helper extraction
- paper-trading hardening
- removal of dead legacy wrappers

That is the right direction, even if the repo has not fully landed there yet.

## What Is Fragile Or Misleading

### Finding 1: Strategy documentation is ahead of strategy reality

The docs encourage people to think the live strategy now lives cleanly in `strategies/composite_intraday`.

In reality, the live wrapper still depends on the legacy signal generator.

That mismatch is one of the highest-value things to fix because it confuses:

- humans reading the repo
- AI agents planning changes
- testing expectations
- ownership boundaries

### Finding 2: There are still too many truth surfaces

Right now, trade or performance truth can come from:

- `state.json`
- `performance.json`
- `trades.db`
- `tradovate_fills.json`
- live broker summary fields in state

Those are not fully reconciled today.

That creates avoidable confusion in any review of "did the bot do well?"

### Finding 3: The service layer is still too central

Even after extraction, too much behavior is still coupled through the service object.

That slows:

- testing
- onboarding
- safe refactors
- AI-assisted work

because a lot of behavior is still wired through service state instead of small explicit contracts.

### Finding 4: Some config keys still invite false confidence

The config still includes fields like:

- `signals.skip_overnight`
- `signals.avoid_lunch_lull`
- `signals.prioritize_ny_session`

The service explicitly tracks these as warn-only and not enforced.

That is a team-efficiency problem because it makes people reason about settings that are not actually governing live behavior.

### Finding 5: Docs and repo state still contain stale assumptions

Examples:

- Some docs still mention surfaces already removed or partially removed.
- The AI instructions describe canonical files that are not always the full runtime truth anymore.
- CI and tooling coverage are not yet a perfect match for the current frontend-plus-backend reality.

This is not catastrophic. It is exactly what happens during a large cleanup. But it means "trust the docs" is not enough; you need "trust the docs, then verify against the live path."

## When It Worked, And When It Did Not

Important note:

- `state.json` contains UTC timestamps with offsets.
- `performance.json` and `trades.db` trade dates are summarized here by their stored date prefixes.
- Broker-fill pairing below is an inference from `tradovate_fills.json`, not a guaranteed official brokerage statement.

### Summary view of this week

| Trading date | What the local performance tracker says | What `trades.db` says | What simple broker fill pairing suggests | Read |
|---|---:|---:|---:|---|
| Monday, March 30, 2026 | +83.81 on 3 trades | +83.81 on 3 trades | -22.0 on 1 paired trade | Small sample, not a strong confidence day |
| Tuesday, March 31, 2026 | +662.78 on 58 trades | +662.78 on 58 trades | +981.5 on 57 paired trades | Strong day |
| Wednesday, April 1, 2026 | +457.13 on 31 trades | +457.13 on 31 trades | +527.0 on 34 paired trades | Strong day |
| Thursday, April 2, 2026 | +18.05 on 2 trades | no SQLite exits recorded | +91.5 on 8 paired trades | Mixed day, tracking inconsistency and restart churn |
| Friday, April 3, 2026 | no meaningful fresh trading evidence | no new SQLite exits | no fresh broker pairing evidence | Not working as a healthy live signal day |

### The "great couple days" this week

The strongest evidence points to:

- Tuesday, March 31, 2026
- Wednesday, April 1, 2026

Why those two stand out:

- Both `performance.json` and `trades.db` agree they were clearly profitable.
- Broker-fill pairing also points positive on both days.
- Exit-reason totals show take-profit gains materially outweighing stop-loss losses.

On Tuesday, March 31, 2026:

- `trades.db` shows 58 exits and about +662.78.
- Fill-pair inference shows 57 paired trades and about +981.5.
- The strongest time bucket was midday, about +580.11 across 17 trades.
- Afternoon was also positive.
- Morning was weak, which means the day was not uniformly strong; it recovered and accelerated later.

On Wednesday, April 1, 2026:

- `trades.db` shows 31 exits and about +457.13.
- Fill-pair inference shows 34 paired trades and about +527.0.
- Morning was the standout bucket, about +454.45 across 6 trades with a very high win rate.
- Overnight was slightly positive.
- Midday and afternoon gave some back.

That pattern is important. It suggests the recent success was not "every hour got better." It was more likely:

- strong intraday windows
- profitable take-profit captures
- enough edge on the good sessions to offset weaker buckets

### What appears to have worked well on those strong days

- The signal engine was active enough to generate real trade volume.
- The execution path was active enough to produce repeated exits.
- Take-profit realization was large enough to overcome accumulated stop losses.
- The dashboard and persistence layers captured enough of the week to reconstruct useful summaries.

### What clearly did not work on Friday, April 3, 2026

The current Friday state is not "bot is fully down." It is more subtle than that.

The system is alive, but the trading path is unhealthy:

- `state.json` says `running: true`.
- `state.json` says execution connectivity fields are true on the Tradovate side.
- `state.json` also says `armed: false`.
- `state.json` says data is not fresh.
- The latest bar timestamp is stale by more than 500 minutes.
- The market is closed at the time of inspection, but the logs also show repeated IBKR connectivity failures and stale-data gating.

The April 3 logs show a repeating pattern:

- connection refused to `127.0.0.1:4001`
- `Not connected to IB Gateway`
- IBKR connection circuit breaker half-open probe fails
- circuit breaker re-opens
- cached latest bar is returned
- stale-data warnings fire
- signal generation is skipped

That is not a healthy trading runtime. It is a live service surviving in degraded mode.

### What appears to have gone wrong on Thursday, April 2, 2026

Thursday looks like a transitional day.

Signals were still being generated, but the logs show repeated cases of:

- `Order skipped: not_armed`
- `follower_execute: skipping virtual entry record — execution_status='skipped:not_armed'`

That means the strategy path and execution path were not aligned for at least part of the day.

April 2 also has repeated evidence of market-data instability:

- `Ticker contains NaN values`
- `No historical data available for MNQ`
- `No contract details found for MNQ`

The current agent `start_time` in `state.json` is also `2026-04-02T13:23:28.598776+00:00`, which lines up with a recent restart or re-arm period.

So Thursday reads like:

- system in motion
- some profitable activity
- but unstable enough that you should treat it as a mixed operational day, not a clean success day

## Performance Truth Hierarchy Right Now

If someone asks "what did Pearl make this week?" this is the safest current answer:

1. The live broker summary in `state.json` is the best single operational headline for realized week PnL.
2. `tradovate_fills.json` is the best local raw artifact for broker-side reconstruction.
3. `performance.json` is a useful local tracker but not the final authority.
4. `trades.db` is useful for analytics but is clearly lagging this week.

Current live snapshot from `state.json` at review time:

- equity: `45135.82`
- week realized pnl: `2883.88`
- positions: none
- working orders: none

Why I would not claim an exact internal weekly PnL from repo data alone:

- `performance.json` totals and `trades.db` totals are lower than the broker weekly number.
- `trades.db` currently stops at Wednesday, April 1, 2026 exits.
- `performance.json` includes Thursday, April 2, 2026 trades but only 2 of them.
- fill pairing produces a stronger Thursday than the local performance tracker does.

So the honest reading is:

- The week was meaningfully positive.
- Tuesday and Wednesday were the standout days.
- The local analytics pipeline still needs broker reconciliation hardening.

## How To Use Perplexity Well For This Repo

Perplexity is most valuable here when used as an external research and planning assistant, not as the source of truth about your repo.

Use it for:

- vendor docs and integration best practices
- architecture modernization patterns
- reliability patterns for event-driven trading systems
- FastAPI, Next.js, React, Zustand, WebSocket, and async SQLite patterns
- market-data fault tolerance patterns
- execution reconciliation and ledger design patterns

Do not use it for:

- guessing what your current code does
- deciding which files are canonical without being told
- inferring current runtime state from the repo alone

### The best Perplexity workflow

1. Give Perplexity repo-specific context first.
2. Tell it which files are canonical.
3. Tell it which docs and runtime facts are more trustworthy than generic assumptions.
4. Ask it for ranked recommendations with tradeoffs, not vague brainstorming.
5. Require citations to primary sources or official docs.
6. Ask it to separate "external best practice" from "repo-specific inference."

### What Perplexity should always be told

Paste these facts into the prompt:

- This is a live 24/7 automated futures trading stack.
- Market data is IBKR.
- Execution is Tradovate paper.
- Canonical runtime config is `config/live/tradovate_paper.yaml`.
- Canonical service entry is `python -m pearlalgo.market_agent.main`.
- Canonical operator entry is `./pearl.sh`.
- Canonical frontend is `apps/pearl-algo-app/`.
- Live state root is `/home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ`.
- JSON is the recovery source of truth; SQLite may lag.
- The composite strategy wrapper still delegates into `src/pearlalgo/trading_bots/signal_generator.py`.
- Current observed issues include stale IBKR data, circuit breaker reopen loops, and unreconciled performance surfaces.

## Perplexity Prompt Pack

### Prompt 1: Full efficiency audit

```text
I need a serious efficiency and modernization review for a live automated futures trading codebase.

Context you must treat as authoritative:
- Operator entry: ./pearl.sh
- Python entry: python -m pearlalgo.market_agent.main
- Canonical runtime config: config/live/tradovate_paper.yaml
- Canonical service: src/pearlalgo/market_agent/service.py
- Strategy namespace: src/pearlalgo/strategies/composite_intraday/
- Important truth: the canonical strategy wrapper still delegates into src/pearlalgo/trading_bots/signal_generator.py
- Execution venue: Tradovate paper
- Market data: IBKR
- Frontend: apps/pearl-algo-app/
- FastAPI backend: src/pearlalgo/api/server.py
- Live state root: /home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ
- JSON is the recovery source of truth; SQLite may lag in async mode

Observed repo realities:
- The service layer is still too coupled even after extraction work
- There are multiple performance truth surfaces: state.json, performance.json, trades.db, tradovate_fills.json
- There are warn-only config keys that are not enforced at runtime
- Recent runtime failures include stale data, IBKR connection circuit breaker reopen loops, and execution periods where signals were generated while not armed

Your task:
1. Give me a ranked top-15 list of changes that would most improve developer efficiency and operational reliability together.
2. Separate your answer into:
   - architecture simplification
   - runtime reliability
   - performance/accounting reconciliation
   - test and CI hardening
   - frontend/backend contract cleanup
   - AI-agent-readiness improvements
3. For each recommendation include:
   - why it matters
   - estimated impact
   - implementation difficulty
   - dependency order
   - what to avoid
4. Explicitly call out patterns from official docs or primary sources only.
5. Distinguish clearly between:
   - advice grounded in external authoritative sources
   - advice that is an inference from the repo facts I gave you

I do not want generic software advice. I want recommendations specific to a live trading stack with mixed legacy and canonical surfaces.
```

### Prompt 2: Broker reconciliation research

```text
Research best practices for building a trustworthy realized-PnL source of truth in a live automated futures trading system where:
- broker execution is Tradovate paper
- market data comes from IBKR
- the local app stores state in JSON plus SQLite
- performance.json, trades.db, raw fills, and the broker summary can disagree

I want a practical design memo that answers:
1. What artifact should be the canonical realized-PnL source of truth and why?
2. How should fills be paired and normalized?
3. How should partial fills, reversals, same-direction adds, and daily boundaries be handled?
4. How should the app distinguish:
   - broker-realized PnL
   - strategy-estimated PnL
   - analytics-derived PnL
5. What reconciliation jobs, alerting, and audit trails should exist?
6. What schema and event model would you recommend?

Use official Tradovate docs, brokerage reconciliation best practices, or primary-source trading system references where possible.
```

### Prompt 3: Market-data reliability research

```text
Research reliability patterns for a live automated trading system with this split:
- IBKR is market data only
- Tradovate is execution only
- the runtime can remain operational on the execution side while the data side becomes stale
- current failure mode includes circuit breaker reopen loops, cached bars, stale-data guards, and skipped signal generation

Give me:
1. A failure taxonomy for this type of architecture
2. Recommended circuit-breaker and recovery patterns
3. Best practices for stale-data signaling to the operator
4. How to separate:
   - healthy execution path
   - degraded but safe mode
   - unsafe mode requiring pause
5. A concrete monitoring and alerting design
6. A proposed state machine for connectivity and data freshness

Prefer official docs and primary references over blogspam.
```

### Prompt 4: Repo modernization sequence

```text
I need a phased modernization roadmap for a live trading codebase where the documentation claims a canonical strategy namespace, but runtime still relies on a legacy strategy engine behind compatibility wrappers.

Design a migration plan that:
- minimizes trading risk
- improves code ownership clarity
- avoids breaking production during refactors
- reduces AI-agent confusion
- preserves testability throughout

Please produce:
1. A 30-day plan
2. A 60-day plan
3. A risk register
4. A definition of done for “legacy bridge fully retired”
5. A documentation plan that keeps runtime truth and docs in sync
```

## Claude Code Plan Mode Prompt Pack

These are prompts for Claude Code Plan mode, not for freeform coding. The goal is to make Claude spend its effort on repo-aware planning before implementation.

### Prompt A: Whole-repo architecture plan

```text
You are in Plan mode inside the Pearl Algo repo.

Treat these as safety-critical constraints:
- This is a live 24/7 automated futures trading system.
- Do not propose changing execution.armed, execution.enabled, execution.mode, guardrails, or contract-size limits without explicit approval.
- IBKR is data only.
- Tradovate paper is execution.
- Canonical runtime config is config/live/tradovate_paper.yaml.
- Canonical operator entry is ./pearl.sh.
- Canonical Python entry is python -m pearlalgo.market_agent.main.
- Live state is under /home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ.

Your task:
1. Read the actual repo first. Do not guess.
2. Build a repo map of:
   - operator entrypoints
   - service/runtime modules
   - strategy modules
   - execution modules
   - state/persistence modules
   - API/frontend modules
   - test and CI surfaces
3. Identify where documentation and runtime truth disagree.
4. Produce a phased improvement plan focused on:
   - simplifying architecture
   - clarifying ownership boundaries
   - reducing compatibility surface
   - improving operational reliability
   - improving AI-agent readability
5. Rank changes by ROI and risk.
6. For each proposed phase, specify:
   - exact files likely to change
   - tests that should be run
   - runtime risks
   - rollback approach

Important:
- Prefer runtime truth over stale docs when they disagree.
- Call out assumptions explicitly.
- Do not start coding; only produce a disciplined plan.
```

### Prompt B: Reliability and stale-data plan

```text
You are in Plan mode inside the Pearl Algo repo.

I want a repo-specific plan to make the runtime resilient to stale market data and split-brain health states where Tradovate looks healthy but IBKR data is stale or unavailable.

First inspect:
- src/pearlalgo/market_agent/main.py
- src/pearlalgo/market_agent/service.py
- src/pearlalgo/market_agent/service_loop.py
- src/pearlalgo/market_agent/data_fetcher.py
- src/pearlalgo/market_agent/execution_orchestrator.py
- src/pearlalgo/api/server.py
- config/live/tradovate_paper.yaml
- current state and logs under /home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ and logs/

Then produce:
1. A current-state diagnosis
2. A list of failure modes
3. A target runtime state machine
4. A file-by-file implementation plan
5. A verification plan
6. Operator-visible dashboard changes needed to make degraded mode obvious

Do not suggest broad rewrites first. Start with the highest-leverage low-risk fixes.
```

### Prompt C: Performance reconciliation plan

```text
You are in Plan mode inside the Pearl Algo repo.

I need a concrete plan to reconcile all performance surfaces so that realized PnL, estimated PnL, and analytics PnL are clearly separated and internally consistent.

Inspect at minimum:
- src/pearlalgo/market_agent/performance_tracker.py
- src/pearlalgo/storage/trade_database.py
- src/pearlalgo/storage/async_sqlite_queue.py
- src/pearlalgo/market_agent/state_manager.py
- src/pearlalgo/api/server.py
- any code that reads tradovate_fills.json or broker summaries
- runtime artifacts in /home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ

I want:
1. The current accounting truth hierarchy
2. The exact mismatches between state.json, performance.json, trades.db, and raw fills
3. A target data model
4. A migration plan that does not break the dashboard
5. A testing and backfill plan
6. A proposal for operator-facing labels so the UI stops mixing estimated and broker-realized values

Stay repo-specific and use exact file references.
```

### Prompt D: Strategy de-legacying plan

```text
You are in Plan mode inside the Pearl Algo repo.

The repo presents src/pearlalgo/strategies/composite_intraday/ as canonical, but runtime still delegates through src/pearlalgo/trading_bots/signal_generator.py.

I need a disciplined migration plan to retire the legacy bridge safely.

Your plan must:
1. Identify the exact functions and behaviors still delegated through the legacy engine.
2. Map what belongs in the canonical strategy bundle.
3. Define a safe extraction order.
4. Specify test coverage needed before each move.
5. Identify any runtime or config compatibility traps.
6. Define the finish line for “legacy strategy bridge retired.”

Do not recommend a blind rewrite. I want an incremental plan that keeps trading behavior measurable across each stage.
```

### Prompt E: Frontend and API contract plan

```text
You are in Plan mode inside the Pearl Algo repo.

I need a repo-specific plan to tighten the dashboard/API contract so the web app is easier to reason about, less noisy under async updates, and more explicit about live vs cached vs broker-derived data.

Inspect at minimum:
- src/pearlalgo/api/server.py
- apps/pearl-algo-app/app/dashboard/DashboardPageInner.tsx
- apps/pearl-algo-app/hooks/useDashboardData.ts
- apps/pearl-algo-app/hooks/useWebSocket.ts
- apps/pearl-algo-app/stores/

Then produce:
1. The current data flow from runtime to API to WS/polling to UI stores
2. Where state duplication exists
3. Where the UI can show misleading freshness or authority signals
4. A phased cleanup plan
5. Suggested contract changes that minimize breakage
6. Tests that should cover the new contract
```

## Best Combined Workflow: Perplexity Plus Claude

The best workflow is not "ask Perplexity everything" and not "ask Claude to wing it."

Use this sequence:

1. Use Perplexity to research external best practices and vendor-specific patterns.
2. Give Claude Code Plan mode the repo-specific task with explicit safety rules.
3. Ask Claude to compare the repo against the Perplexity research.
4. Only after the plan is solid should you move to implementation.

### Good division of labor

Use Perplexity for:

- external architecture patterns
- official API and framework research
- design alternatives
- risk tradeoff framing

Use Claude Plan mode for:

- file-accurate repo analysis
- exact change sequencing
- test planning
- migration planning
- rollback-aware implementation plans

Use implementation mode only after Plan mode has:

- named the files
- named the tests
- named the rollout order
- named the risks

## The Most Important Research Questions For The Team Right Now

If I were optimizing Pearl Algo efficiency first, I would prioritize research and planning around these five questions:

1. How do we establish one explicit broker-reconciled performance truth without losing local strategy analytics?
2. How do we retire the legacy strategy bridge without changing live trading behavior unexpectedly?
3. How do we formalize degraded-mode behavior when execution health and data health diverge?
4. How do we reduce service-layer coupling so smaller safe changes become easier?
5. How do we make the repo easier for AI agents to reason about by shrinking stale compatibility and ambiguous docs?

## Bottom Line

Pearl Algo is a real system with real strengths.

It is not a toy bot, and it is not total chaos.

Its current form is best described as:

- a legitimate live trading platform
- in the middle of a serious cleanup
- with real recent profitable trading evidence
- but with unresolved truth-surface and reliability issues that still cost team efficiency

If you want the highest-ROI improvement path, focus on:

1. performance source-of-truth reconciliation
2. stale-data and split-health reliability
3. legacy strategy retirement
4. service-layer decomposition
5. doc and AI-readiness cleanup

Those five things would improve both developer speed and operator confidence more than almost any cosmetic cleanup.
