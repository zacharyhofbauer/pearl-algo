# Service Composition — MarketAgentService

**Status:** Canonical live architecture as of 2026-04-23.
**Audience:** engineers making changes to the market agent's orchestrator or its collaborators.
**Related plan:** Tier 3 / Issue 2-A in `~/.claude/plans/this-session-work-cosmic-horizon.md`.

`MarketAgentService` (`src/pearlalgo/market_agent/service.py`) is a 2,578-LOC orchestrator-of-orchestrators. After several extraction phases it now composes 17+ submodules via direct attribute assignment, 2 mixins, and 3 delegated orchestrators. This document is the single place to look up **what each collaborator owns, where it fires in the main loop, and how it relates to the mixins and orchestrators**.

## Composition at a glance

```
                        ┌──────────────────────────┐
                        │   MarketAgentService     │
                        │   (service.py, 2578 LOC) │
                        └─────────────┬────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         │                            │                            │
   ┌─────▼──────┐               ┌─────▼──────┐               ┌─────▼──────┐
   │   MIXINS   │               │ COMPOSED   │               │ THREE      │
   │            │               │ COLLABORS. │               │ ORCHEST.   │
   └────────────┘               └────────────┘               └────────────┘
    Lifecycle                    data_fetcher                 signal_
    Loop                         performance_tracker          orchestrator
                                 state_manager                execution_
                                 state_reader                 orchestrator
                                 state_builder                observability_
                                 signal_handler               orchestrator
                                 order_manager
                                 position_monitor
                                 position_tracker
                                 reconciliation
                                 health_monitor
                                 audit_logger
                                 signal_audit_logger
                                 trading_circuit_breaker
                                 scheduled_tasks
                                 operator_handler
                                 tv_paper_eval_tracker
                                 virtual_trade_manager
                                 notification_queue ⚠ shim
                                 execution_adapter
                                 data_provider
```

## Mixins (inheritance-level composition)

| Mixin | File | Owns | Hooks into |
|---|---|---|---|
| `ServiceLifecycleMixin` | `service_lifecycle.py` | `start()`, `stop()`, `_initialize_*()`, graceful-shutdown wiring, PID/lock handling | Bookends every run |
| `ServiceLoopMixin` | `service_loop.py` | The scan loop itself — adaptive cadence (15 s / 60 s / 300 s / 1.5 s velocity), pause/resume transitions, `_compute_effective_interval`, diagnostics per cycle | Runs continuously while the service is active |

**Rule of thumb:** anything that happens **around** the scan (setup, teardown, cadence math, pause state) is in a mixin. Anything that happens **inside** a scan cycle is in a collaborator or orchestrator.

## Three orchestrators

| Orchestrator | File | Input | Output | Why it exists |
|---|---|---|---|---|
| `SignalOrchestrator` | `signal_orchestrator.py` (25 LOC shim) | Strategy's `generate_signals` output | Normalized signal records | Tiny facade; lives one call-site away from being inlined. |
| `ExecutionOrchestrator` | `execution_orchestrator.py` | Signal records + gate decisions | Orders dispatched via `order_manager` / `execution_adapter` | Coordinates six tightly-coupled pieces: CB gate → size decision → flag clearance → bracket place → post-place reconcile → audit log. |
| `ObservabilityOrchestrator` | `observability_orchestrator.py` | Service-cycle telemetry events | Pushes to `audit_logger`, `signal_audit_logger`, health snapshots | Wraps the three audit / health sinks so `service.py` doesn't call all three each cycle. |

**Ownership boundaries (bright lines):**

- **SignalOrchestrator never calls an execution method.** Its output is shape normalization only.
- **ExecutionOrchestrator never inspects raw indicators.** It consumes already-scored signal records.
- **ObservabilityOrchestrator never writes to state.json.** That's `state_manager.save()` territory.

## Key collaborators — one-line ownership

| Collaborator | Purpose |
|---|---|
| `data_fetcher.MarketAgentDataFetcher` | Pulls OHLCV frames from the configured `DataProvider`; handles caching + MTF fetches. |
| `state_manager.MarketAgentStateManager` | Writes `state.json`, appends `signals.jsonl`, fsyncs on every signal (see Issue 6-A / 13-A). |
| `state_reader.StateReader` | Thread-safe locked reads for `/api/state` consumers. |
| `state_builder.StateBuilder` | Assembles the dashboard/export payload from state, performance, and runtime config. |
| `performance_tracker.PerformanceTracker` | `trades.db` writes, equity-curve tracking, signal→trade pairing. |
| `signal_handler.SignalHandler` | The pipeline: circuit-breaker check → execution handoff → notification enqueue. |
| `order_manager.OrderManager` | Size math, idempotency-key generation, dispatch to `execution_adapter.place_bracket`. |
| `position_monitor` | Per-cycle watcher for an already-open live position (stop-walk decisions, stale-bracket detection). |
| `position_tracker` | In-memory + JSON-backed record of every known open position. |
| `reconciliation` | Cross-checks local position state against broker REST snapshot. |
| `health_monitor` | Per-cycle health-check aggregation; feeds the dashboard "health" card. |
| `audit_logger.AuditLogger` | Typed JSONL event log for SIGNAL_GENERATED / EXECUTION / ERROR / KILL_SWITCH. |
| `signal_audit_logger` | Separate JSONL specifically for every signal's full trigger context (regime, indicators, confidence). |
| `trading_circuit_breaker.TradingCircuitBreaker` | The 1,480-LOC guardrail — consecutive losses, drawdown, regime avoidance, direction gating, session profit lock. |
| `scheduled_tasks.ScheduledTasks` | Periodic non-scan jobs (heartbeat, auto-flat at 15:55 ET, daily-resets, eval-tracker ticks). |
| `operator_handler.OperatorHandler` | Watches `operator_requests/` flag files (kill-switch, close-all, close-trade, resume). |
| `tv_paper_eval_tracker` | Tradovate Paper prop-firm evaluation rules (per-contract caps, consistency). |
| `virtual_trade_manager` | Virtual-PnL bookkeeping when `virtual_pnl.enabled=true` (disabled in live). |
| `execution_adapter` | Tradovate (or IBKR) adapter — `place_bracket`, `cancel_all`, `flatten_all_positions`, `_reconnect_loop`, etc. |
| `data_provider` | IBKR adapter for market data (1m / 5m / 15m MTF). |

## Compatibility surfaces still present

Documented in `docs/COMPATIBILITY_SURFACES.md`. Two that affect service composition:

1. **`notification_queue.NotificationQueue`** — a retained no-op shim after the Telegram removal. Still imported at `service.py:45` and invoked from 15+ call-sites (`enqueue_heartbeat`, `enqueue_raw_message`, `enqueue_risk_warning`, `enqueue_data_quality_alert`, etc.). Future deletion: inline each call-site with the equivalent `audit_logger` / `logger.info` invocation in a dedicated PR, then remove the import. Do not add new features on top of it.
2. **`pearlalgo.trading_bots.*`** — legacy strategy surface. Issue 1-A plans its extraction behind `strategies.composite_intraday`. Issue 11-A's CI guard prevents new imports from `tests/`.

## Where to add a new collaborator

Decision tree:

1. **Is it lifecycle / cadence related?** → add to one of the mixins.
2. **Does it coordinate three or more existing collaborators during a scan cycle?** → consider an orchestrator (but only a fourth one; otherwise dissolve into an existing one).
3. **Does it own a specific resource (DB, flag file, external service)?** → it's a collaborator — add it as an attribute on `MarketAgentService.__init__` via `ServiceDependencies`.

**Anti-pattern:** adding a new "helper module" imported directly from the scan loop. Everything that persists beyond a single cycle gets a home in this table.

## Flow of a single scan cycle

```
1. ServiceLoopMixin._compute_effective_interval()        # adaptive cadence
2. data_fetcher.fetch()                                  # 1m / 5m / 15m frames
3. strategy.generate_signals(df, config=…)               # composite_intraday
4. SignalOrchestrator.normalize(signals)                 # shape pass
5. For each normalized signal:
   a. trading_circuit_breaker.should_allow_signal(…)     # gate
   b. signal_handler.process_signal(…)                   # decide
   c. order_manager.compute_base_position_size(…)
   d. execution_orchestrator.execute(…)                  # place_bracket
   e. state_manager.record_signal_generated(…)           # fsync
   f. audit_logger.log_signal_generated(…)               # JSONL
6. position_monitor.monitor_open_positions(…)            # stop-walk, stale bracket
7. reconciliation.poll_if_needed(…)                      # REST drift
8. ObservabilityOrchestrator.emit_cycle_telemetry(…)
9. scheduled_tasks.run_if_due(…)                         # heartbeat, auto-flat
10. operator_handler.consume_flag_files(…)               # kill-switch, close-all
```

Cycle latency target: < 200 ms p95 in velocity mode (1.5 s cadence). Signal-write fsync is the known hot-spot (Issues 6-A + 13-A track it).
