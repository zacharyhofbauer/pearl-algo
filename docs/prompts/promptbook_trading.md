PearlAlgo Trading Promptbook

========================================
RUN CONFIGURATION (EDIT BEFORE PASTING)
========================================

RUN_MODE: STANDARD
  # FAST     - Quick verification, skip deep analysis
  # STANDARD - Balanced depth, full workflow
  # DEEP     - Thorough analysis, all backtests, comprehensive audit

TOGGLES (set true/false):
  RUN_BACKTESTING: true
  RUN_NQ_AGENT_VERIFICATION: true
  RUN_ATS_SAFETY_AUDIT: true
  RUN_PROMPT_DRIFT_AUDIT: true

========================================
PURPOSE
========================================

Unified prompt for PearlAlgo trading system verification and improvement. Covers:
- Strategy backtesting and signal validation
- NQ agent verification and performance stewardship
- ATS execution safety and adaptive learning audit

This promptbook can be invoked standalone or via promptbook_engineering.md with RUN_SCOPE=trading or RUN_SCOPE=all.

========================================
AUTONOMOUS EXECUTION MODE
========================================

You have full read/write access to the repository. You are authorized to:
- Scan trading implementation files autonomously
- Run backtests and analyze results
- Verify agent behavior and state consistency
- Audit execution safety guards
- Propose improvements with concrete examples

You are forbidden from:
- Enabling live trading execution or placing real orders
- Changing strategy intent, risk parameters, or thresholds without authorization
- Changing state schema without explicit approval
- Arming execution adapters or enabling live mode

Progress beats permission. Evidence beats questions.

========================================
SOURCES OF TRUTH
========================================

Authoritative documents (highest to lowest):
1) docs/PROJECT_SUMMARY.md - Architecture, state schema, module boundaries
2) docs/prompts/promptbook_engineering.md - Global constraints (when invoked from there)
3) THIS PROMPTBOOK - Trading domain scope and constraints

========================================
GLOBAL HARD CONSTRAINTS (NON-NEGOTIABLE)
========================================

Trading Safety:
- Do NOT enable live trading execution (disabled/disarmed/shadow by default)
- Do NOT change signal generation logic without explicit authorization
- Do NOT change risk parameters (position sizing, stop distance, R:R ratios)
- Do NOT change state schema; document drift and propose migration

Execution Safety:
- Default state: disabled, disarmed, shadow mode
- Kill switch must remain functional at all times
- Learning cannot "arm" execution; it only influences decisions when already safely enabled
- All safety guards must be additive and default-safe

Backtesting Integrity:
- No curve-fitting to specific date ranges
- No parameter optimization purely to inflate metrics
- Backtest != live performance; treat as approximation
- If strategy produces no signals, that is a primary finding, not a failure to hide

========================================
LANE A vs LANE B
========================================

LANE A — AUTONOMOUSLY IMPLEMENT (SAFE NOW):
- Backtest observability/explainability improvements (why signals fired/didn't fire)
- Agent monitoring and logging improvements
- Safety guard additions that are additive and default-safe
- Test additions for existing behavior
- Documentation fixes

LANE B — PLAN / PROPOSE ONLY (NEEDS REVIEW):
- Strategy threshold or filter changes
- Risk parameter modifications
- State schema changes
- Execution enablement or arming
- Learning parameter tuning that could affect live decisions

========================================
MANDATORY FIRST ACTIONS (READ-ONLY)
========================================

Before changing code, read:
- docs/PROJECT_SUMMARY.md
- docs/TESTING_GUIDE.md
- docs/ATS_ROLLOUT_GUIDE.md

========================================
PHASE 1: BACKTESTING VERIFICATION (if RUN_BACKTESTING=true)
========================================

Scope: Strategy validation and signal analysis

1.1 INFRASTRUCTURE SCAN
Read and understand:
- src/pearlalgo/strategies/nq_intraday/backtest_adapter.py
- scripts/backtesting/backtest_cli.py
- Data format: data/historical/*.parquet (OHLCV, DatetimeIndex UTC)

Backtest modes:
- Signal-only: run_signal_backtest() - Fast, no trade simulation
- Full backtest: run_full_backtest() - Complete trade simulation with P&L
- 5m decision variants: run_*_5m_decision()

1.2 SIGNAL EXISTENCE ANALYSIS
Run signal-only backtests to answer:
- Does the strategy generate signals at all?
- How many signals per day/week/month?
- What market conditions trigger signals?
- Are signals distributed across different regimes?

Commands:
```bash
python scripts/backtesting/backtest_cli.py signal --data-path data/historical/MNQ_1m_2w.parquet --decision 1m
python scripts/backtesting/backtest_cli.py signal --data-path data/historical/MNQ_1m_2w.parquet --decision 5m
```

Output: Signal frequency summary, distribution analysis

1.3 CONDITION BLOCKING ANALYSIS
Identify which filters/conditions block signals most:
- Entry conditions (trend, momentum, zones)
- Time windows (strategy session hours)
- Risk filters (R:R ratio, stop distance cap)
- MTF alignment requirements

Goal: Understand if signal scarcity is intentional or over-constrained

1.4 FULL BACKTEST (if RUN_MODE=STANDARD or DEEP)
Run full trade simulation:
```bash
python scripts/backtesting/backtest_cli.py full --data-path data/historical/MNQ_1m_2w.parquet --contracts 5
python scripts/backtesting/backtest_cli.py full --data-path data/historical/MNQ_1m_2w.parquet --account-balance 50000 --max-risk-per-trade 0.01
```

Analyze:
- Trade lifecycle (entry -> stop/target -> exit)
- Skipped signals (why? concurrency, risk budget, stop cap)
- P&L distribution and regime behavior

Output: Backtest findings, behavioral observations

1.5 OBSERVABILITY IMPROVEMENTS (LANE A)
Add logging/instrumentation to explain:
- Why signals fired (conditions met)
- Why signals didn't fire (which condition blocked)
- Do NOT change thresholds; only improve visibility

========================================
PHASE 2: NQ AGENT VERIFICATION (if RUN_NQ_AGENT_VERIFICATION=true)
========================================

Scope: Agent lifecycle, reliability, and observability

2.1 AGENT COMPONENT SCAN
Read and understand:
- src/pearlalgo/nq_agent/service.py - Main service loop (30-second interval)
- src/pearlalgo/nq_agent/scanner.py - Market scanning
- src/pearlalgo/nq_agent/signal_generator.py - Signal validation
- src/pearlalgo/nq_agent/state_manager.py - State persistence
- src/pearlalgo/nq_agent/performance_tracker.py - Performance metrics

State files:
- data/nq_agent_state/state.json - Agent state
- data/nq_agent_state/signals.jsonl - Signal history

2.2 LIFECYCLE VERIFICATION
Verify:
- 30-second scan interval accuracy (no drift, no silent stalls)
- Market hours vs strategy session awareness
- State persistence and recovery across restarts
- Circuit breaker correctness (10 consecutive errors -> pause)

Monitoring questions:
- Is agent scanning every 30 seconds? (check cycle_count, last_successful_cycle)
- Is data fresh? (check latest_bar_age_minutes, data_fresh flag)
- Are signals generated when conditions met? (check signal_count, signals.jsonl)
- Are errors handled? (check error_count, consecutive_errors)

2.3 MARKET STATE AWARENESS
Verify correct identification of:
- Futures market open vs closed (CME ETH hours)
- Strategy session open vs closed (18:00-16:10 ET default)
- Holidays, partial sessions, DST transitions

Test files:
- tests/test_market_hours.py
- tests/test_strategy_session_hours.py

2.4 STATE CONSISTENCY
Check for:
- State file corruption or invalid values
- Signal lifecycle tracking accuracy
- Performance metrics correctness (win rate, P&L calculations)
- No phantom trades or orphan signals

2.5 OBSERVABILITY IMPROVEMENTS (LANE A)
Improve monitoring surfaces:
- Add missing log messages for state transitions
- Enhance state.json fields for debugging
- Improve Telegram status visibility
- Do NOT change agent behavior

Output: Verification findings, observability improvements

========================================
PHASE 3: ATS EXECUTION SAFETY AUDIT (if RUN_ATS_SAFETY_AUDIT=true)
========================================

Scope: Execution control and adaptive learning

3.1 EXECUTION ARCHITECTURE SCAN
Read and understand:
- src/pearlalgo/execution/base.py - ExecutionAdapter interface, ExecutionConfig
- src/pearlalgo/execution/ibkr/adapter.py - IBKR implementation
- src/pearlalgo/execution/ibkr/tasks.py - Order placement tasks
- src/pearlalgo/learning/bandit_policy.py - Thompson sampling policy
- src/pearlalgo/learning/policy_state.py - Policy statistics persistence

Config reference (config/config.yaml):
```yaml
execution:
  enabled: false         # Master toggle (default: disabled)
  armed: false           # Runtime toggle (default: disarmed)
  mode: "dry_run"        # "dry_run", "paper", "live"
  max_positions: 1
  max_orders_per_day: 20
  max_daily_loss: 500.0
  cooldown_seconds: 60

learning:
  enabled: true
  mode: "shadow"         # "shadow" (observe) or "live" (affects execution)
  min_samples_per_type: 10
  explore_rate: 0.1
  decision_threshold: 0.3
```

3.2 SAFETY INVARIANTS CHECK
Verify these invariants hold:
- [ ] Default state is disabled + disarmed + shadow mode
- [ ] Precondition checks are complete and defensive
- [ ] Kill switch cancels all orders AND disarms immediately
- [ ] Learning cannot arm execution; only influences when already enabled
- [ ] Daily loss limit triggers automatic disarm
- [ ] Cooldowns prevent rapid-fire orders

3.3 EXECUTION FLOW AUDIT
Trace the signal-to-order flow:
1. Signal generated by strategy
2. Policy decides execute/skip (shadow or live mode)
3. Preconditions checked (enabled, armed, limits, cooldowns)
4. Bracket order placed (entry + stop loss + take profit)
5. Outcome recorded for learning
6. State updated for observability

Check for gaps in:
- Error handling at each step
- Logging for auditability
- Alerting for failures

3.4 KILL SWITCH VERIFICATION
Verify kill switch behavior:
- /kill command cancels all orders AND disarms
- Kill is fast (under 1 second)
- Kill works even if IBKR connection is degraded
- Manual backup procedure documented

3.5 LEARNING SAFETY
Verify adaptive learning safety:
- Shadow mode allows observation without risk
- Live mode cannot execute without enabled+armed
- Policy state is persisted correctly
- Bad learning can be reset without data loss

3.6 SAFETY IMPROVEMENTS (LANE A only)
Add missing safety guards:
- New precondition checks (additive, default-safe)
- Better alerting for edge cases
- Improved logging for auditability
- Do NOT arm or enable execution

Output: Safety audit report, proposed rollout stages (shadow -> paper -> live)

========================================
PHASE 4: PROMPT DRIFT AUDIT (if RUN_PROMPT_DRIFT_AUDIT=true)
========================================

4.1 DRIFT DETECTION
Check this promptbook for:
- Referenced file paths that don't exist
- Referenced commands that don't match repository
- Statements contradicting docs/PROJECT_SUMMARY.md
- Stale assumptions about config or architecture

4.2 DRIFT REPORT
Output:
- List of detected issues
- Classification: SAFE_TO_FIX vs NEEDS_REVIEW
- Impact assessment

4.3 PROPOSED PATCH
Generate diff for any needed updates:
```
PROMPT DRIFT PATCH - promptbook_trading.md
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
   - Overall trading system health
   - Key findings across domains

2) BACKTESTING FINDINGS (if run)
   - Signal frequency summary
   - Condition blockers identified
   - Regime coverage analysis
   - Observability improvements added

3) NQ AGENT VERIFICATION (if run)
   - Lifecycle reliability status
   - State consistency findings
   - Monitoring improvements added

4) ATS SAFETY AUDIT (if run)
   - Safety invariants status (pass/fail each)
   - Gaps identified
   - Proposed rollout stages per docs/ATS_ROLLOUT_GUIDE.md

5) PROMPT DRIFT (if run)
   - Issues found
   - Proposed patches

6) OPEN ISSUES / FOLLOW-UPS
   - Safe now (LANE A)
   - Safe later
   - Needs explicit approval (LANE B)

========================================
IMPLEMENTATION REFERENCES
========================================

Backtesting:
- src/pearlalgo/strategies/nq_intraday/backtest_adapter.py
- scripts/backtesting/backtest_cli.py
- scripts/backtesting/run_variants.py
- data/historical/*.parquet

NQ Agent:
- src/pearlalgo/nq_agent/service.py
- src/pearlalgo/nq_agent/scanner.py
- src/pearlalgo/nq_agent/signal_generator.py
- src/pearlalgo/nq_agent/state_manager.py
- data/nq_agent_state/state.json

Execution & Learning:
- src/pearlalgo/execution/base.py
- src/pearlalgo/execution/ibkr/adapter.py
- src/pearlalgo/learning/bandit_policy.py
- data/nq_agent_state/policy_state.json

Documentation:
- docs/PROJECT_SUMMARY.md
- docs/ATS_ROLLOUT_GUIDE.md
- docs/TESTING_GUIDE.md

========================================
PHILOSOPHY
========================================

Optimize for:
- Trust over aggression (reliability over activity)
- Understanding over performance (know why it works)
- Signal existence over elegance (signals matter)
- Robustness over clever filters (works across conditions)
- Safety over speed (no unintended trades)

A good trading system feels boring - because it behaves exactly as expected.

========================================

